# 0003. Multi-tenancy via shared schema and Row-Level Security

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Several companies (tenants) use Dialetiq. They may share end consumers, but no tenant may
learn which other tenants a consumer belongs to.

The options were a database per tenant, a schema per tenant, or a shared schema with a
`tenant_id` column. Database- and schema-per-tenant give the strongest isolation but make
migrations, connection pooling, and cross-tenant operations (which we legitimately need for
platform operations) expensive and slow — and Neon's connection budget makes hundreds of
pools untenable.

The real risk in a shared schema is a forgotten `WHERE tenant_id = ?`. One missing clause
in one ORM query leaks one company's customer list to a competitor.

## Decision

Shared schema, `tenant_id` column, and **Postgres Row-Level Security** as an enforcement
layer beneath the application.

- The app connects as `app_runtime`, which has neither `BYPASSRLS` nor membership in the
  table owner. Application roles are created **by SQL migration, never via the Neon
  console** — console-created roles are members of `neon_superuser` and silently bypass
  RLS.
- Every tenant-scoped transaction sets `SET LOCAL ROLE app_tenant` and
  `set_config('app.tenant_id', $1, true)`. Both are transaction-scoped, so they survive
  PgBouncer transaction pooling by construction.
- Policies fail **closed**: an unset GUC yields `NULL`, which matches no rows.
- Every tenant-scoped table has RLS both `ENABLE`d and `FORCE`d.

RLS is the **second** line of defense. The first is a base repository that requires
`tenant_id` at construction. Belt and suspenders.

## Consequences

**We gain:** a missing `WHERE` clause becomes zero rows instead of a cross-tenant leak. The
guarantee is enforced by the database, not by developer discipline.

**We pay:**

- Alembic's `--autogenerate` **cannot see** policies, `FORCE ROW LEVEL SECURITY`, `GRANT`s,
  or roles. All of it is hand-written `op.execute()`, and schema drift is therefore
  guaranteed unless we assert against it. We run configuration assertions at API startup —
  the pod refuses to boot if any application role has `BYPASSRLS`, is a member of the
  owner, or if any table carrying `tenant_id` lacks forced RLS.
- Failing closed means a forgotten GUC surfaces as *zero rows* — a silent product bug, not
  an error. The base-repository requirement is what catches it early.
- A parameterized isolation test suite, generated from the Postgres catalog rather than a
  hand-maintained list, is mandatory. Without it, RLS is theater.
- **Accepted residual risk:** anyone with direct database access can still correlate tenant
  bases. Mitigated by [ADR 0004](0004-private-schema-for-consumer-identity.md) and by
  organizational controls (nobody holds production credentials by default). Per-tenant
  pseudonymization would close this, at a cost we chose not to pay now. The door is open.
