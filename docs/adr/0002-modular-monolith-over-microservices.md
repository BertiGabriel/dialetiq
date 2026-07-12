# 0002. Modular monolith over microservices

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

The system must scale to large push fan-outs (hundreds of thousands of devices per
campaign) and must eventually support multiple teams working in parallel. The instinct is
to reach for microservices.

But the actual bottlenecks here are **three shared resources**, and none of them is the
Python process:

1. The Firebase project's send quota — one app means one Firebase project, one quota,
   shared by every tenant.
2. The queue — a single FIFO lane lets one tenant's 500k-device blast block another
   tenant's chat reply for 40 minutes.
3. Neon's connection budget — more services means more pools, and connections are the
   scarcest resource we have.

Microservices solve none of these. They multiply the operational cost and add network
failure modes.

## Decision

A modular monolith. One codebase, one image, several entrypoints deployed as distinct
Kubernetes Deployments: `api`, `ws`, `worker-transactional`, `worker-bulk`.

Splitting `worker-transactional` from `worker-bulk` is **not** an optimization — it is a
correctness requirement, and it follows from bottleneck (2).

Modules communicate through in-process function calls via each other's `api.py`, and
through domain events for async work. **Never over HTTP.** Module-to-module HTTP inside one
system is a distributed monolith: you pay network latency and network failure modes and
receive nothing in return.

## Consequences

**We gain:** one deploy, one place to debug, no service mesh, no distributed tracing
required to answer "why was this push slow". Refactoring across module boundaries is a
compiler-checked rename, not a versioned API migration.

**We pay:**

- A single deploy pipeline: a chat hotfix waits behind a campaigns migration.
- Every process loads every module's code, including `identity` with the HMAC pepper in its
  address space.
- Module boundaries are enforced only by `import-linter`, not by the network. If that CI
  check is ever disabled, the boundaries evaporate silently. This is the trade: the linter
  *is* the architecture.

**The escape hatch stays open.** Because modules are decoupled by contract, extracting one
into its own service later is an infrastructure task — swap the in-process event bus for a
broker — not a rewrite. That option is exactly what the `import-linter` contracts preserve.
