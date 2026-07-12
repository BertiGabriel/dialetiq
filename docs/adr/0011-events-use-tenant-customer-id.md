# 0011. Events and analytics key on `tenant_customer_id`, never `person_id`

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

We want rich behavioral data: what consumers view, when they open a push, what they ask in
chat, what converts. This is the foundation for product analytics and, later, for any AI
feature.

Every data-warehouse tutorial ever written says the same thing: give each user a stable
global id so you can follow them across the product. That instinct is correct in every
system except this one.

**In Dialetiq, a global consumer id in the event stream is the cross-tenant join key.**

If `person_id` lands in the `event` table, then RLS ([ADR 0003](0003-multi-tenancy-via-shared-schema-and-rls.md)),
the `private` schema ([ADR 0004](0004-private-schema-for-consumer-identity.md)), and every
other privacy control become decorative — because the warehouse now holds the answer they
exist to withhold. Anyone with warehouse access can compute, for any consumer, the exact
set of competing stores they shop at.

This is the single most likely way this product's central promise gets broken, and it will
happen in a sprint that nobody thinks is about privacy.

## Decision

`event` carries `tenant_id` and `tenant_customer_id`. **It never carries `person_id`.**

```sql
event(
  id            uuid,        -- UUIDv7
  tenant_id     uuid NOT NULL,
  actor_type    text,        -- 'staff' | 'customer' | 'system'
  actor_id      uuid,        -- staff_user.id or tenant_customer.id
  name          text,        -- 'campaign.sent', 'offer.viewed', 'lead.created'
  payload       jsonb,
  occurred_at   timestamptz
)
```

The same human, active in two stores, is two unrelated rows. There is no key that connects
them anywhere outside the `private` schema. This holds in the warehouse too, whenever we
build one.

Telemetry from the app and panel is sent to **our** API, not to a third-party analytics
SDK. A third-party SDK inside the app would observe the consumer's behavior across *all*
stores — reconstituting precisely the information the product promises not to reveal, in
someone else's database.

`person_id` is likewise banned from logs and trace spans. The OTel processor attaches
`tenant_id` and never `person_id`.

## Consequences

**We gain:** the privacy guarantee survives contact with the analytics stack, which is where
guarantees like this normally die.

**We pay:**

- We cannot answer "how many *humans* use Dialetiq?" from the warehouse — only "how many
  tenant relationships exist". Deduplicated human counts require a query inside `private`,
  under audit. That is a feature.
- Cross-tenant personalization and lookalike modeling are impossible **by construction**.
  Product will ask for them; the answer is no, permanently. See the ban in `CLAUDE.md`.
- Any future ML model is trained **per tenant**, on that tenant's data. A model trained
  across tenants leaks patterns between competitors by construction, even if no row is
  shared.
- Behavior we don't record today cannot be recovered retroactively. This makes the `event`
  table the **one irreversible item** in the foundation phase — it ships in Phase 0, before
  there is any consumer of it.
