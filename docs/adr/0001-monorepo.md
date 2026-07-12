# 0001. Monorepo

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Dialetiq ships three deployable artifacts — a Python backend, a Flutter app, and a
JavaScript admin panel — plus infrastructure. They evolve together: a change to the API
contract touches all three.

## Decision

One repository: `backend/`, `frontend/`, `mobile/`, `infra/`, `docs/`, and `contracts/`.

Team boundaries and access hierarchy come from `CODEOWNERS` and GitHub Environments, not
from repository boundaries.

## Consequences

**We gain:** a change that spans backend and mobile is one atomic PR, not two coordinated
ones. The API contract cannot drift between artifacts, because there is only one copy of
it. Onboarding is one `git clone`.

**We pay:**

- CI must be path-filtered, or every PR runs every job. This is a day-1 concern, not a
  later optimization.
- Access control is per-directory (`CODEOWNERS`), not per-repository. That is a weaker
  boundary than "you don't have the repo" — it prevents merging, not reading. If we ever
  need a contractor who must not *see* the backend, the monorepo cannot deliver that.
- The repository grows monotonically. Flutter and its build artifacts are large; the
  `.gitignore` matters more than usual.
