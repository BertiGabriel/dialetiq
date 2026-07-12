# Glossary — Ubiquitous Language

This is the canonical vocabulary of Dialetiq. It is **not** a style preference.

In this system, a vocabulary mistake is a **security failure**. Dialetiq guarantees that
no tenant can learn which other tenants a consumer belongs to. That guarantee lives or
dies on the distinction between `person` (the real human, global) and `tenant_customer`
(one tenant's relationship with that human). If an engineer believes those are the same
thing, they will write the wrong `JOIN`, and the isolation between competing companies
collapses.

Use these words. Only these words.

---

## Core entities

| Term | Meaning | Never call it |
|---|---|---|
| **`tenant`** | The company/store that sends campaigns. **This is the isolation boundary.** | `store`, `merchant`, `company`, `client`, `account` |
| **`staff_user`** | A human who works for a `tenant` and signs in to the admin panel. | `user`, `admin`, `employee` |
| **`person`** | The real end consumer. A **global** identity, one per human. **Never exposed to a tenant.** | `user`, `customer`, `consumer` |
| **`tenant_customer`** | The *link* between one `tenant` and one `person`. **This is the only consumer identity the admin panel ever sees.** | `customer`, `contact`, `subscriber` |
| **`device`** | A phone with the app installed. Belongs to a `person`, **not** to a `tenant`. | — |
| **`campaign`** | A promotion authored by a `tenant`. | `broadcast`, `blast` |
| **`campaign_recipient`** | One addressee of one campaign, with its delivery state machine. | `delivery`, `message`, `send` |
| **`conversation`** / **`message`** | In-app chat between a `tenant` and a `tenant_customer`. | `thread`, `ticket` |
| **`lead`** | A purchase intent registered by a `tenant_customer`. There is no cart and no payment. | `order`, `purchase`, `checkout` |
| **`event`** | An append-only record of something that happened. Always scoped by `tenant_id`. | `log`, `analytics`, `tracking` |
| **`audit_log`** | An append-only, immutable record of a **staff or agent action**. | `history` |

---

## Banned word: `user`

**`user` is forbidden as a bare identifier anywhere in this codebase.**

It is ambiguous between *the person who runs a store* and *the person who shops at it* —
and that ambiguity is precisely how someone joins `person` to a tenant-scoped table and
destroys the privacy model.

It is always one of: `staff_user`, `person`, or `tenant_customer`. Never `user`.

A CI grep enforces this. It is the cheapest rule in the project and one of the most
protective.

---

## Why `tenant` and not `merchant`

`tenant` is jargon. That is the point.

`merchant` reads better to a non-engineer, but `tenant` makes **every line of code that
mentions it announce that an isolation boundary exists**. In a system whose central
promise is isolation between competing companies, that constant reminder is worth more
than business readability.

The column is `tenant_id` in every table that carries it. Seeing `tenant_id` should
trigger the reflex: *is this query scoped? is RLS on? is `SET LOCAL` set?*

---

## The invariant that follows from all of this

**`person_id` never crosses the admin API boundary.**

It does not appear in an admin response, a CSV export, a log line, a trace span, an
analytics event, or an LLM prompt. Structurally, it does not even live in a table the
tenant-facing database role can read — it sits in the `private` schema, and the
tenant-facing role has no `USAGE` on it.

Analytics and events use **`tenant_customer_id`**. The same human, in two stores, is two
unrelated rows. That is the entire product promise, expressed as a column choice.

See [ADR 0004](docs/adr/0004-private-schema-for-consumer-identity.md) and
[ADR 0011](docs/adr/0011-events-use-tenant-customer-id.md).
