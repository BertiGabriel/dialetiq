# 0004. A `private` schema for consumer identity

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Dialetiq ships a single multi-brand app ([ADR 0005](0005-single-multi-brand-consumer-app.md)),
so a consumer has **one** account. Their identity is global by construction. Yet no tenant
may learn which other tenants that consumer belongs to.

The obvious design puts `person_id` as a foreign key on `tenant_customer`, and relies on a
convention: *"the admin API only ever speaks in `tenant_customer.id`."*

That convention is worthless. It dies to a `SELECT *`, a CSV export endpoint, a Pydantic
serializer without `exclude`, a debug log line, or a trace attribute. And a stable
`person_id` is precisely the **join key** two colluding tenants — or one tenant and one
leaked dump — need to correlate their customer bases.

A convention cannot defend an invariant this important. Structure can.

## Decision

`person_id` does not exist in any table the tenant-facing role can read.

```sql
CREATE SCHEMA private;
REVOKE ALL ON SCHEMA private FROM PUBLIC;   -- app_tenant never gets USAGE

-- tenant-visible: no person_id anywhere
public.tenant_customer(id, tenant_id, external_ref, consent_state, ...)

-- tenant-invisible
private.person(id, phone_hmac, phone_enc, email_hmac, email_enc, pepper_version)
private.person_link(tenant_customer_id PK, person_id)
private.device(id, person_id, fcm_token UNIQUE, platform, last_seen_at)
```

Only `app_delivery` — the push worker, which serves **no HTTP route** — has `USAGE` on
`private`. The join from `tenant_customer` to a device happens only inside that worker, and
its result is never persisted anywhere a tenant can read.

Identifiers are stored twice: as an HMAC (peppered, for deterministic matching during base
import) and encrypted (for actual use — SMS, `wa.me` links). A database dump alone yields
neither the phone list nor the tenant graph.

A CI query asserts that `app_tenant` holds no `SELECT` privilege on any column named
`person_id`, `fcm_token`, `phone_hmac`, or `phone_enc`. It must return zero rows.

## Consequences

**We gain:** the invariant is enforced by Postgres privileges, not by code review. A
careless `SELECT *` returns a permission error instead of leaking the join key.

**We pay:**

- Every read that genuinely needs the identity (sending a push, sending an SMS) must run in
  the delivery worker under a different role. That boundary is real work and cannot be
  short-circuited "just this once".
- Two roles, two credentials, two secrets to rotate.
- **The HMAC pepper becomes a crown jewel.** Brazilian phone numbers span ~10⁹ values and
  HMAC-SHA256 is fast; a pepper leaked alongside a dump makes the whole base reidentifiable
  in minutes. It lives in an external secret manager, with `pepper_version` on the row so it
  can be rotated. Envelope encryption via KMS, never AES with a key in an env var.
- Any future analytics or AI feature must respect the same boundary — see
  [ADR 0011](0011-events-use-tenant-customer-id.md), which is where this invariant is
  most likely to be broken by accident.
