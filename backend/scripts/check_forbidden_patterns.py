#!/usr/bin/env python3
"""Fail the build on the three patterns that silently break tenant isolation.

Each of these looks harmless in review, passes every test, and leaves every
tenant's data readable by every other tenant:

  1. `SET app.<x>` without LOCAL
       The GUC survives COMMIT. Under PgBouncer transaction pooling the
       connection returns to the pool still carrying it, and the next request --
       possibly for a different tenant -- inherits it.

  2. asyncpg's `server_settings={...}`
       A startup parameter bound to the physical connection, not the
       transaction. Same leak, different door.

  3. an engine with `isolation_level="AUTOCOMMIT"`
       Every statement becomes its own transaction, so `SET LOCAL` evaporates
       before the query runs. Isolation is simply off.

This walks the AST rather than grepping, because grep cannot tell code from a
comment -- and platform/db/session.py *documents* all three patterns in prose.
A grep-based check flags its own documentation and fails on a clean tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _is_docstring(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    if not isinstance(parent, ast.Expr):
        return False
    grandparent = parents.get(parent)
    if not isinstance(
        grandparent, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ):
        return False
    return bool(grandparent.body) and grandparent.body[0] is parent


def check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    problems: list[str] = []

    for node in ast.walk(tree):
        # 1 and 3: string literals in actual code (not docstrings).
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_docstring(node, parents):
                continue
            text = node.value
            upper = text.upper()
            if "SET APP." in upper and "SET LOCAL" not in upper:
                problems.append(
                    f"{path}:{node.lineno}: `SET app.*` without LOCAL — "
                    f"the GUC leaks across pooled connections to another tenant."
                )
            if "AUTOCOMMIT" in upper:
                problems.append(
                    f"{path}:{node.lineno}: AUTOCOMMIT — "
                    f"SET LOCAL evaporates before the query runs; isolation is off."
                )

        # 2: server_settings passed as a keyword argument.
        if isinstance(node, ast.keyword) and node.arg == "server_settings":
            problems.append(
                f"{path}:{node.lineno}: `server_settings` binds state to the physical "
                f"connection, not the transaction — it leaks across tenants."
            )

        # 4: the banned identifier `user`.
        #
        # It is ambiguous between a store operator and a consumer, and that
        # ambiguity is exactly how someone writes the wrong JOIN and hands one
        # company's customer base to a competitor. It is always `staff_user`,
        # `person`, or `tenant_customer`. See GLOSSARY.md and ADR 0009.
        #
        # Checked on binding sites (assignments, parameters, attributes), not on
        # arbitrary text -- so `POSTGRES_USER` and `staff_user` are untouched.
        name = _bound_name(node)
        if name in BANNED_NAMES:
            problems.append(
                f"{path}:{node.lineno}: banned identifier `{name}` — ambiguous between a "
                f"store operator and a consumer. Use staff_user, person, or tenant_customer."
            )

    return problems


BANNED_NAMES = frozenset({"user", "users"})


def _bound_name(node: ast.AST) -> str | None:
    """Return the identifier this node binds, if it binds one."""
    if isinstance(node, ast.arg):
        return node.arg
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return node.attr
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    if isinstance(node, ast.keyword):
        return node.arg
    return None


def main() -> int:
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        problems.extend(check_file(path))

    if problems:
        for p in problems:
            print(f"::error::{p}")  # noqa: T201 — this is a CI reporter
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
