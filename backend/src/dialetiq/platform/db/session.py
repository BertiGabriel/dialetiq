"""Tenant-scoped database sessions.

This module is the load-bearing wall of the whole product. Every cross-tenant
leak this system could suffer runs through the code below, so read the reasoning
before changing anything here.

The guarantee: a tenant can never read or write another tenant's rows, even if
an ORM query forgets its `WHERE tenant_id = ?`. That is enforced by Postgres
Row-Level Security, not by developer discipline. See ADR 0003.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dialetiq.platform.config import settings

# Connections are the scarcest resource we have. Neon's compute exposes roughly
# ~100 max_connections on a small CU, and every replica multiplies our pool.
# All traffic goes through Neon's pooled endpoint (PgBouncer in transaction
# mode), which makes SQLAlchemy's own pool largely redundant -- so we keep it
# deliberately small. The default (5 + 10 overflow, per process) blows the
# budget on the first scale-up, and the symptom ("too many connections") reads
# like an application bug when it is a topology bug.
_engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=0,
    pool_pre_ping=True,
    # NEVER set isolation_level="AUTOCOMMIT" here. Each statement would become
    # its own transaction, and the SET LOCAL below would evaporate before the
    # query ran -- silently disabling tenant isolation.
)

_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Open a session scoped to exactly one tenant.

    Every statement inside runs as `app_tenant`, and RLS policies filter on
    `app.tenant_id`. A forgotten WHERE clause yields zero rows instead of
    another company's customer list.

    Both `SET LOCAL ROLE` and `set_config(..., is_local=true)` are
    transaction-scoped: they revert on COMMIT/ROLLBACK, and PgBouncer in
    transaction mode only returns the connection to the pool at COMMIT. So this
    is safe under pooling *by construction*.

    What is NOT safe, and must never appear in this codebase (CI greps for all
    three):

      * `SET app.tenant_id = ...` without LOCAL -- the connection goes back to
        the pool still carrying the GUC, and the next request, possibly for a
        different tenant, inherits it.
      * asyncpg's `server_settings={...}` -- a startup parameter, bound to the
        physical connection, not the transaction.
      * an AUTOCOMMIT engine -- see the comment on the engine above.
    """
    async with _session_factory() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL ROLE app_tenant"))
            # Bind parameter, never an f-string. String interpolation here would
            # be a SQL injection that could RESET ROLE and escape the tenant.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            yield session


@asynccontextmanager
async def person_session(person_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Open a session for a consumer acting on their own behalf (the mobile app).

    Runs as `app_person`, which is scoped to the authenticated person and is the
    only HTTP-facing path that may touch the `private` schema at all.

    `app_tenant` has no USAGE on `private`, so no amount of carelessness in a
    panel endpoint can expose `person_id` -- the join key that would let two
    competing stores correlate their customer bases. See ADR 0004.
    """
    async with _session_factory() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL ROLE app_person"))
            await session.execute(
                text("SELECT set_config('app.person_id', :person_id, true)"),
                {"person_id": str(person_id)},
            )
            yield session
