# 0012. Defer Kubernetes; deploy to a managed platform first

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

The original intent was Kubernetes from day one. Two facts, established after that intent
was set, change the calculus:

1. **This is being built by one person.**
2. **The cross-tenant privacy guarantee is contractual** — we will sell to directly
   competing stores. Nothing in the threat model can be cut.

Since the security work is fixed, the schedule can only be recovered from infrastructure and
features.

Kubernetes costs roughly three to four weeks before the first feature exists: cluster,
Helm charts, ingress, cert-manager, External Secrets, HPA, KEDA for queue-depth scaling,
migrations as a pre-upgrade Job, PodDisruptionBudgets, probes, and the operational learning
to debug all of it.

And it buys nothing at zero users. The real bottlenecks in this system are the **Firebase
send quota**, the **queue**, and **Neon's connection budget** — see
[ADR 0002](0002-modular-monolith-over-microservices.md). Kubernetes addresses none of them.

## Decision

Docker from day one. **Deploy to Cloud Run or Fly.io for the MVP.** Adopt Kubernetes when
scale — or an enterprise customer's requirements — actually demands it.

The application stays strictly 12-factor and stateless, exactly as it would be under
Kubernetes. The separate process types (`api`, `worker-transactional`, `worker-bulk`) remain
separate; they are simply deployed as managed services rather than as Deployments.

## Consequences

**We gain:** three to four weeks of product work, and a far smaller operational surface for
a solo developer to debug at 2 a.m.

**We pay:**

- Less control over scheduling, and platform-specific deployment configuration that will be
  discarded at migration time.
- Queue-depth autoscaling (KEDA) is not available in the same form. At MVP volumes, fixed
  worker counts are sufficient; this is the first thing that will hurt if a large tenant
  arrives early.
- We must keep the discipline of statelessness even without Kubernetes enforcing it.

**The migration is cheap by construction.** A containerized, stateless, 12-factor app moves
to Kubernetes as an infrastructure task, not a rewrite. The Kubernetes design already
worked out — HPA on `api`, KEDA on `worker-bulk`, migrations as a Job, connection budget
discipline against Neon — remains valid and is retained in the plan for that day.

Supersedes the Kubernetes-from-day-one intent. Does **not** supersede
[ADR 0002](0002-modular-monolith-over-microservices.md): the modular monolith and its
separate process types stand.
