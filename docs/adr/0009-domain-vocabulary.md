# 0009. Domain vocabulary: `tenant`, `person`, `tenant_customer`

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

This system holds two kinds of humans — people who run stores and people who shop at them —
and one of them exists in two forms: the real global human (`person`) and one store's
relationship with that human (`tenant_customer`).

That distinction is not a modeling nicety. It **is** the privacy guarantee. An engineer who
believes `customer` and `person` are the same thing will write the wrong `JOIN` and expose
one company's customer base to a competitor.

Vocabulary drift — `store` here, `merchant` there, `company` in a third place, `user`
everywhere — is therefore a security risk, not a style problem.

## Decision

The canonical terms are fixed in [GLOSSARY.md](../../GLOSSARY.md):

- **`tenant`** — the company. The isolation boundary.
- **`staff_user`** — a human who works for a tenant and signs into the panel.
- **`person`** — the real consumer. Global. Never exposed to a tenant.
- **`tenant_customer`** — the link between a tenant and a person. The only consumer identity
  the panel ever sees.

**The word `user` is banned as a bare identifier.** It is ambiguous between store operator
and consumer, and that ambiguity is exactly how the wrong join gets written. It is always
`staff_user`, `person`, or `tenant_customer`. A CI grep enforces it.

We chose `tenant` over `merchant` deliberately. `merchant` reads better to a
non-engineer — but `tenant` is jargon that makes **every line mentioning it announce that
an isolation boundary exists.** In a system whose central promise is isolation between
competitors, that constant reminder is worth more than business readability.

## Consequences

**We gain:** the most dangerous confusion in the codebase is prevented by naming, and
enforced by a two-line CI check — the cheapest protective rule in the project.

**We pay:**

- `tenant` is jargon. Onboarding a non-technical stakeholder requires translating it, and
  product documents aimed at merchants must use business language while the code does not.
- Renaming later is a breaking change across tables, APIs, and the mobile app. This decision
  is effectively permanent, which is why it is an ADR and not a convention.
