"""Startup assertions that refuse to boot a database that cannot isolate tenants.

Row-Level Security has two silent killers. Both leave the application working
perfectly, all tests green, and every tenant's data readable by every other
tenant:

  1. **The table owner bypasses RLS.** Alembic runs as the owner, so the tables
     belong to it. The day someone hits `permission denied` and "fixes" it by
     granting the owner role to the application role, RLS stops applying and
     nothing anywhere reports a problem.

  2. **BYPASSRLS.** On Neon, roles created through the *console* are members of
     `neon_superuser` and bypass RLS. Roles created by SQL migration are not.
     Same name, same password, completely different security posture.

Neither failure raises an error. Neither breaks a test. The only defense is to
assert the invariants directly against the catalog and refuse to start.

Alembic's --autogenerate cannot see policies, GRANTs, FORCE ROW LEVEL SECURITY,
or roles. Drift is therefore guaranteed over time. These checks are what turn
that drift into a failed deploy instead of a data breach.

Run at API startup (the process exits) and in CI (the build fails).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

APP_ROLES = ("app_runtime", "app_tenant", "app_person", "app_platform", "app_delivery")

# Columns that must never be readable by the tenant-facing role. `person_id` is
# the cross-tenant join key; the rest are consumer PII. See ADR 0004.
FORBIDDEN_COLUMNS = ("person_id", "fcm_token", "phone_hmac", "phone_enc", "email_hmac", "email_enc")


class DatabaseGuardError(RuntimeError):
    """The database cannot enforce tenant isolation. Do not serve traffic."""


async def assert_no_bypassrls(conn: AsyncConnection) -> None:
    rows = (
        await conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles) AND rolbypassrls"),
            {"roles": list(APP_ROLES)},
        )
    ).all()
    if rows:
        names = ", ".join(r.rolname for r in rows)
        raise DatabaseGuardError(
            f"Application roles have BYPASSRLS and silently ignore every RLS policy: {names}. "
            "These roles were almost certainly created through the Neon console, which makes "
            "them members of neon_superuser. Create application roles by SQL migration only."
        )


async def assert_roles_do_not_inherit_owner(conn: AsyncConnection) -> None:
    rows = (
        await conn.execute(
            text("""
                SELECT r.rolname, g.rolname AS granted
                FROM pg_auth_members m
                JOIN pg_roles r ON r.oid = m.member
                JOIN pg_roles g ON g.oid = m.roleid
                WHERE r.rolname = ANY(:roles)
                  AND g.rolname NOT LIKE 'app\\_%'
            """),
            {"roles": list(APP_ROLES)},
        )
    ).all()
    if rows:
        detail = ", ".join(f"{r.rolname} -> {r.granted}" for r in rows)
        raise DatabaseGuardError(
            f"Application roles are members of a non-application role: {detail}. "
            "If that role owns the tables, RLS does not apply to them at all."
        )


async def assert_rls_enabled_and_forced(conn: AsyncConnection) -> None:
    """Every table carrying tenant_id must have RLS both ENABLEd and FORCEd.

    Derived from the catalog, not from a hand-maintained list -- a list goes
    stale the first time someone adds a table and forgets to update it, which is
    exactly the case this must catch.
    """
    rows = (
        await conn.execute(
            text("""
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                  AND EXISTS (
                      SELECT 1 FROM pg_attribute a
                      WHERE a.attrelid = c.oid
                        AND a.attname = 'tenant_id'
                        AND NOT a.attisdropped
                  )
                  AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
            """)
        )
    ).all()
    if rows:
        names = ", ".join(r.relname for r in rows)
        raise DatabaseGuardError(
            f"Tables carry tenant_id but lack forced RLS: {names}. "
            "Every one of them is readable across tenants right now. "
            "Both ENABLE and FORCE ROW LEVEL SECURITY are required -- ENABLE alone "
            "still exempts the table owner."
        )


async def assert_tenant_role_cannot_read_identity(conn: AsyncConnection) -> None:
    """`app_tenant` must hold no SELECT on any consumer-identity column.

    This is the structural version of "person_id never crosses the admin API
    boundary". A convention dies to a `SELECT *`; a revoked privilege does not.
    """
    rows = (
        await conn.execute(
            text("""
                SELECT c.relname, a.attname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND NOT a.attisdropped
                WHERE a.attname = ANY(:cols)
                  AND has_table_privilege('app_tenant', c.oid, 'SELECT')
            """),
            {"cols": list(FORBIDDEN_COLUMNS)},
        )
    ).all()
    if rows:
        detail = ", ".join(f"{r.relname}.{r.attname}" for r in rows)
        raise DatabaseGuardError(
            f"app_tenant can read consumer identity columns: {detail}. "
            "person_id is the join key that lets two competing tenants correlate their "
            "customer bases. It must live in the `private` schema, which app_tenant has "
            "no USAGE on."
        )


async def run_all(conn: AsyncConnection) -> None:
    """Refuse to serve traffic unless every isolation invariant holds."""
    await assert_no_bypassrls(conn)
    await assert_roles_do_not_inherit_owner(conn)
    await assert_rls_enabled_and_forced(conn)
    await assert_tenant_role_cannot_read_identity(conn)
