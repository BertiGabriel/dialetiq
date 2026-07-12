# 0008. English code, Portuguese content

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

The team is Brazilian; the users — store operators and consumers — are Brazilian. The
codebase should be readable by any engineer, including a future non-Portuguese speaker.

Left implicit, this produces the worst outcome: an English codebase sprinkled with
`const mensagemErro = "Erro"`.

## Decision

Two distinct concerns, two distinct answers.

| | Language |
|---|---|
| Code — identifiers, functions, classes, files, DB tables and columns | **en-US** |
| Comments, ADRs, docs, commit messages, PR titles, branch names | **en-US** |
| User-facing content — app, panel, push copy, emails, validation messages | **pt-BR**, via i18n |
| Data — a campaign title a merchant typed | whatever they typed; it is data, not code |

The consequence that matters: **i18n from day one**, in both the app and the panel. Never a
Portuguese string literal inside a component. This is not preparation for
internationalization — it is the mechanism that keeps the language rule coherent.

Comments explain **why**, never **what**. A comment describing what the line does means the
name is wrong.

## Consequences

**We gain:** a codebase any engineer can read, aligned with the surrounding ecosystem
(FastAPI, Flutter, Postgres are all English). The vocabulary in
[GLOSSARY.md](../../GLOSSARY.md) has one canonical form, which is what makes the
`tenant` / `person` / `tenant_customer` distinction enforceable.

**We pay:**

- The team writes ADRs and commit messages in a second language. Early on this is slower and
  carries less nuance than writing in Portuguese would. We accept that cost for
  consistency; a doc half in each language is worse than either.
- An i18n layer in the panel and the app from day one, before there is any second locale to
  justify it.
