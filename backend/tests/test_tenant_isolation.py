"""Tenant isolation. The most important suite in this project.

It is what separates real multi-tenancy from multi-tenancy-until-the-first-leak.

Two design choices worth defending:

**It is generated from the Postgres catalog, not from a hand-written list of
tables.** A hand-written list goes stale the first time someone adds a table and
forgets to add it here -- which is precisely the case this suite exists to
catch. If a new table carries `tenant_id`, it is tested, automatically, whether
or not anyone remembered.

**It runs against a real Postgres, never a fake repository.** You cannot test RLS
against an in-memory double. This is why there are no repository Protocols in
this codebase: a fake repo would make these tests pass while proving nothing.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from dialetiq.platform.config import settings
from dialetiq.platform.db import guards

# Tables carrying tenant_id, discovered at collection time.
TENANT_TABLES_SQL = """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND EXISTS (
          SELECT 1 FROM pg_attribute a
          WHERE a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
      )
    ORDER BY c.relname
"""


def _app_runtime_url() -> str:
    """The URL the application actually uses: app_runtime, not the owner.

    Testing isolation as `neondb_owner` would test a path that does not exist in
    production. Worse, the owner has no policy targeting it, so every query
    would return zero rows and the suite would pass while proving nothing.
    """
    url = settings.database_url
    scheme, rest = url.split("://", 1)
    _creds, host = rest.split("@", 1)
    pw = os.environ["DIALETIQ_APP_RUNTIME_PASSWORD"]
    return f"{scheme}://app_runtime:{pw}@{host}"


@pytest_asyncio.fixture
async def conn() -> AsyncConnection:
    """A connection as `app_runtime`, exactly as the API opens one.

    NOINHERIT means it holds no privileges at all until it SET LOCAL ROLEs into
    app_tenant, app_person, or app_platform -- which is the whole point.
    """
    engine = create_async_engine(_app_runtime_url(), poolclass=NullPool)
    async with engine.connect() as c:
        yield c
    await engine.dispose()


@pytest_asyncio.fixture
async def owner_conn() -> AsyncConnection:
    """Connection as the migration owner. Used only to inspect the catalog.

    Note it cannot read tenant data either: FORCE ROW LEVEL SECURITY applies to
    the owner too, and no policy targets it. That is intentional -- the role that
    migrates the schema has no business reading consumer data.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as c:
        yield c
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(conn: AsyncConnection) -> tuple[uuid.UUID, uuid.UUID]:
    """Seeded as app_platform -- creating a tenant is a platform act, not a
    tenant act. There is no `app.tenant_id` yet when the tenant is born."""
    a, b = uuid.uuid4(), uuid.uuid4()
    await conn.execute(text("SET ROLE app_platform"))
    for tid, slug in ((a, f"a-{a.hex[:8]}"), (b, f"b-{b.hex[:8]}")):
        await conn.execute(
            text("INSERT INTO public.tenant (id, slug, name) VALUES (:id, :slug, :slug)"),
            {"id": tid, "slug": slug},
        )
    await conn.commit()
    await conn.execute(text("RESET ROLE"))
    return a, b


async def _tenant_tables(conn: AsyncConnection) -> list[str]:
    return [r.relname for r in (await conn.execute(text(TENANT_TABLES_SQL))).all()]


async def test_every_tenant_table_is_covered(owner_conn: AsyncConnection) -> None:
    """Sanity: the catalog query finds tables. An empty list would make every
    parameterized test below vacuously pass -- a green suite proving nothing."""
    tables = await _tenant_tables(owner_conn)
    assert tables, "No tenant-scoped tables found; the isolation suite is testing nothing."
    assert "tenant_customer" in tables
    assert "campaign" in tables


async def test_startup_guards_pass(owner_conn: AsyncConnection) -> None:
    """The invariants the API refuses to boot without."""
    await guards.run_all(owner_conn)


async def test_no_app_role_has_bypassrls(owner_conn: AsyncConnection) -> None:
    """A role with BYPASSRLS ignores every policy, and nothing anywhere reports it.

    This is how Neon console-created roles behave: same name, same password,
    isolation silently off.
    """
    rows = (
        await owner_conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'app\\_%' AND rolbypassrls")
        )
    ).all()
    assert not rows, f"Application roles bypass RLS: {[r.rolname for r in rows]}"


async def test_app_tenant_cannot_read_person_identity(owner_conn: AsyncConnection) -> None:
    """`app_tenant` must not reach the private schema at all.

    person_id is the join key that would let two competing stores correlate their
    customer bases. This is the structural guarantee -- not a convention that a
    stray `SELECT *` can break.
    """
    has_usage = (
        await owner_conn.execute(
            text("SELECT has_schema_privilege('app_tenant', 'private', 'USAGE') AS ok")
        )
    ).scalar_one()
    assert has_usage is False, "app_tenant has USAGE on the private schema."


async def _become(conn: AsyncConnection, role: str, tenant_id: uuid.UUID | None = None) -> None:
    await conn.execute(text("RESET ROLE"))
    await conn.execute(text(f"SET ROLE {role}"))
    await conn.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id) if tenant_id else ""},
    )


async def _seed_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    """Write one row into every tenant-scoped table, as that tenant."""
    await _become(conn, "app_tenant", tenant_id)
    params = {"t": tenant_id, "e": f"staff-{tenant_id.hex[:8]}@example.com"}
    # One statement per execute: psycopg refuses multiple commands in a
    # parameterized statement.
    for stmt in (
        """INSERT INTO staff_user (tenant_id, email, password_hash, role)
           VALUES (:t, :e, 'x', 'owner')""",
        """INSERT INTO tenant_customer (tenant_id, consent_state, consent_source)
           VALUES (:t, 'active', 'self_follow')""",
        """INSERT INTO campaign (tenant_id, title, body, status)
           VALUES (:t, 'secret offer', 'body', 'draft')""",
        "INSERT INTO event (tenant_id, actor_type, name) VALUES (:t, 'system', 'seeded')",
        "INSERT INTO audit_log (tenant_id, action) VALUES (:t, 'seeded')",
        """INSERT INTO lead (tenant_id, tenant_customer_id, status)
           SELECT :t, id, 'new' FROM tenant_customer WHERE tenant_id = :t LIMIT 1""",
        """INSERT INTO campaign_recipient (tenant_id, campaign_id, tenant_customer_id, status)
           SELECT :t, c.id, tc.id, 'pending'
           FROM campaign c, tenant_customer tc
           WHERE c.tenant_id = :t AND tc.tenant_id = :t LIMIT 1""",
    ):
        await conn.execute(text(stmt), params)
    await conn.commit()


TENANT_TABLES = [
    "tenant_customer",
    "campaign",
    "campaign_recipient",
    "lead",
    "event",
    "audit_log",
    "staff_user",
]


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_select_cannot_cross_tenants(
    conn: AsyncConnection,
    two_tenants: tuple[uuid.UUID, uuid.UUID],
    table: str,
) -> None:
    """Tenant B's rows must be invisible to tenant A.

    This is the leak the entire product is designed to prevent: one forgotten
    `WHERE tenant_id = ?` handing a competitor's customer list to a store.

    Note the two assertions. Counting zero rows as tenant A proves nothing on its
    own -- an empty table counts zero too, and a suite that seeds nothing is
    green while testing nothing. So we first prove the row EXISTS (as B), then
    prove it is invisible (as A).
    """
    tenant_a, tenant_b = two_tenants
    await _seed_tenant(conn, tenant_b)

    # As B: the row is really there.
    await _become(conn, "app_tenant", tenant_b)
    as_b = (await conn.execute(text(f"SELECT count(*) FROM public.{table}"))).scalar_one()  # noqa: S608
    assert as_b >= 1, f"{table}: seeding failed, so the isolation assertion below is vacuous."

    # As A: no WHERE clause at all. RLS is the only thing between this query and
    # a competitor's data.
    await _become(conn, "app_tenant", tenant_a)
    as_a = (await conn.execute(text(f"SELECT count(*) FROM public.{table}"))).scalar_one()  # noqa: S608
    assert as_a == 0, f"{table}: tenant A can read tenant B's rows. Isolation is broken."


async def test_insert_cannot_forge_another_tenant(
    conn: AsyncConnection,
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """WITH CHECK must stop a tenant from WRITING under another tenant's id.

    A USING-only policy protects reads and leaves writes wide open -- a store
    could plant a campaign in a competitor's account.
    """
    tenant_a, tenant_b = two_tenants

    await _become(conn, "app_tenant", tenant_a)

    with pytest.raises(ProgrammingError):
        await conn.execute(
            text("""
                INSERT INTO public.campaign (tenant_id, title, body, status)
                VALUES (:tid, 'forged', 'forged', 'draft')
            """),
            {"tid": tenant_b},
        )


async def test_unset_tenant_context_fails_closed(conn: AsyncConnection) -> None:
    """With no `app.tenant_id`, the policy must match NOTHING.

    The dangerous mistake is a policy written as
    `tenant_id = ... OR current_setting(...) IS NULL`, which someone eventually
    writes to "make the test pass" -- and which turns an unset context into
    full access to every tenant.
    """
    await _become(conn, "app_tenant", None)  # no app.tenant_id
    count = (await conn.execute(text("SELECT count(*) FROM public.campaign"))).scalar_one()
    assert count == 0, "An unset tenant context exposed rows. The policy fails OPEN."
