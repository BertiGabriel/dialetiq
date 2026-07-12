# 0005. A single multi-brand consumer app

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Either every tenant publishes its own white-labeled app, or all tenants share one app in
which consumers follow the stores they care about.

White-label means a build pipeline per tenant, an Apple and Google developer account per
tenant, and a store review per tenant. It does not scale for an early-stage product.

## Decision

One Flutter app, "Dialetiq", in the App Store and Play Store. A consumer has **one**
account and follows multiple stores.

A consumer becomes linked to a store in **two** ways: by discovering and following it in
the app, or by accepting an invitation from a store that imported its customer base.

## Consequences

**We gain:** one build, one review, one Firebase project, one push token per device.

**We pay:**

- **Consumer identity is global by construction.** One account, one `person`. This is what
  forces the entire `private`-schema design in [ADR 0004](0004-private-schema-for-consumer-identity.md).
- **Organic sign-up is now a privacy requirement, not a growth feature.** If invitation were
  the only way in, then "has the app" would be logically equivalent to "belongs to some
  store", and every defense around base import would be theater — a store could learn that a
  phone number belongs to a competitor simply by observing that the person already had the
  app. Public sign-up and store discovery by category/location therefore **cannot be cut**
  from the MVP.
- One shared Firebase send quota across all tenants, which forces per-tenant rate limiting
  ([ADR 0002](0002-modular-monolith-over-microservices.md)).
- One shared notification tray. A consumer who follows six stores sees six stores' pushes.
  This produces a residual statistical side channel (a full tray depresses open rates for
  shared consumers) that we accept and document in the threat model.
- **App Store review risk.** One app sending marketing on behalf of dozens of companies
  resembles a "store app generator" to a reviewer (Apple guideline 4.2.6). We mitigate by
  giving the app standalone value — discovery, feed, chat — and explicit per-store opt-in.
  We submit a build to TestFlight in Phase 1 specifically to surface this early. If Apple
  rejects the model, the product stops; that must not be discovered at launch.
