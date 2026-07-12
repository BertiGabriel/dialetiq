# Dialetiq

Multi-tenant platform where companies (**tenants**) send promotions to end consumers via a
single multi-brand mobile app. Consumers browse offers, chat with the store, and register
purchase intent (**leads**).

Read [GLOSSARY.md](GLOSSARY.md) before writing any code. The vocabulary is load-bearing.

## The central guarantee

**Two tenants may share a consumer. Neither may ever learn that the other has them.**

Everything below exists to protect that sentence. When a change appears to conflict with
it, the guarantee wins — raise it, don't work around it.

## Privacy invariants — non-negotiable

1. **`person_id` never leaves the `private` schema.** Not in an API response, a CSV
   export, a log, a trace, an analytics event, or an LLM prompt. The tenant-facing DB role
   has no `USAGE` on `private`.
2. **Analytics and events key on `tenant_customer_id`, never `person_id`.** A global
   consumer id in the event stream *is* the cross-tenant join key. It would silently undo
   RLS, the `private` schema, and everything else.
3. **No unique constraint, dedup key, cache key, or rate-limit bucket may be scoped by
   `person_id` without `tenant_id`** — outside the `private` schema. Deduplicating a lead
   globally tells tenant B that someone else already got it.
4. **No cross-tenant aggregate features. Ever.** No lookalike, no "similar customers", no
   industry benchmark, no audience overlap. Product will ask for these. The answer is no.
5. **Frequency capping is per tenant.** A global cap that reports suppression hands a
   tenant the exact list of consumers its competitors also reach.
6. **No global presence in chat.** "Online now" reveals that *someone else* sent a push.

The subtle attacks (timing oracles in base import, collapse keys, delivery receipts) are
in [docs/threat-model.md](docs/threat-model.md). Read it before touching invites, push, or
analytics.

## Architecture

Modular monolith, hexagonal. One image, several entrypoints (`api`, `ws`,
`worker-transactional`, `worker-bulk`).

- Group by **feature first, layer second**: `modules/engagement/domain/`, never
  `domain/engagement/`.
- `domain/` and `application/` import no infrastructure. No SQLAlchemy, no FastAPI.
- Modules talk to each other **only** through each other's `api.py`, as in-process
  function calls. Never over HTTP — that would be a distributed monolith.
- `platform/` is dumb infrastructure. **It must never import a module.** This is the line
  that stops it from becoming the god-module.

`import-linter` enforces all of the above in CI. The folder layout is a suggestion; the
linter is the contract.

## Language

- **Code, comments, docs, commits, PRs, ADRs: en-US.** Identifiers, tables, columns, branches.
- **User-facing content: pt-BR**, always through i18n. Never a Portuguese string inside a
  component.
- Comments explain **why**, never **what**. If a comment describes what the line does, the
  name is wrong.

## Database

- Postgres (Neon). Row-Level Security is the second line of defense, not the first.
- Every tenant-scoped transaction: `BEGIN` → `SET LOCAL ROLE app_tenant` →
  `set_config('app.tenant_id', $1, true)` → work → `COMMIT`.
- **`SET` without `LOCAL` leaks across tenants** under transaction pooling. So does
  asyncpg `server_settings`, and so does an `AUTOCOMMIT` engine. CI greps for all three.
- Policies fail **closed**: `nullif(current_setting('app.tenant_id', true), '')::uuid`.
  Always `ENABLE` **and** `FORCE ROW LEVEL SECURITY`.
- Exposed ids are UUIDv7. A global sequence leaks platform-wide activity volume.
- Migrations run as owner, on the **direct** (non-pooled) endpoint, as a Job — never on
  app startup.

## Conventions

- `uv` for dependencies and Python version. `ruff` for lint and format.
- Conventional Commits. SemVer via git tag. App **build number comes from CI**, never by
  hand — stores reject a reused number and it can never decrease.
- Never commit secrets. The HMAC pepper, the APNs `.p8`, and Neon credentials live in the
  secret manager. `gitleaks` runs in CI.

## Docs

- A rule that can be checked is a **CI check**, not a paragraph.
- A decision is an **ADR** in `docs/adr/` — immutable and dated. To change one, write a new
  ADR that supersedes it. Never edit history.
