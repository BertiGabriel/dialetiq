# Architecture Decision Records

An ADR records **why** a decision was made, on the date it was made.

## Rules

1. **ADRs are immutable.** Once merged, an ADR is never edited to reflect a new reality.
2. **To change a decision, write a new ADR** that supersedes the old one. Update the old
   one's `Status` line to `Superseded by NNNN` — that is the only edit ever allowed.
3. Keep them short. Five paragraphs, not five pages. If it needs a diagram, it needs a
   design doc, not an ADR.
4. Numbered sequentially: `NNNN-kebab-case-title.md`.

This is why ADRs don't rot: they are a **log**, not a description. A doc that describes how
the system works today is a lie by next quarter. A doc that records what we decided in
July 2026, and why, is true forever.

## Template

```markdown
# NNNN. Title

- **Status:** Accepted | Superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
What forced a decision. The constraints in play.

## Decision
What we chose. Stated plainly.

## Consequences
What this buys us, and what it costs us. Be honest about the cost — that is the part a
future reader needs and the part everyone omits.
```

## Index

| # | Decision |
|---|---|
| [0001](0001-monorepo.md) | Monorepo |
| [0002](0002-modular-monolith-over-microservices.md) | Modular monolith over microservices |
| [0003](0003-multi-tenancy-via-shared-schema-and-rls.md) | Multi-tenancy via shared schema + RLS |
| [0004](0004-private-schema-for-consumer-identity.md) | `private` schema for consumer identity |
| [0005](0005-single-multi-brand-consumer-app.md) | A single multi-brand consumer app |
| [0006](0006-push-as-core-channel.md) | Push as core channel, mirrored by an in-app message center |
| [0007](0007-no-build-spa-with-esm-cdn.md) | No-build SPA via ESM + CDN |
| [0008](0008-english-code-portuguese-content.md) | English code, Portuguese content |
| [0009](0009-domain-vocabulary.md) | Domain vocabulary |
| [0010](0010-ai-ports-now-agents-later.md) | AI: ports now, agents later |
| [0011](0011-events-use-tenant-customer-id.md) | Events key on `tenant_customer_id` |
