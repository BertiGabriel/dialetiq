# 0013. Defer first-party chat and base import out of the MVP

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Same trigger as [ADR 0012](0012-defer-kubernetes.md): a solo build, and a privacy guarantee
that is contractual and therefore uncuttable. The schedule has to come from features.

Two features are both expensive and, on inspection, not load-bearing for the MVP.

**First-party chat** is two to three weeks of construction — WebSocket transport, presence,
history, offline delivery, reconnection with jittered backoff — plus permanent operational
cost (a `ws` process that cannot be drained carelessly without dropping live conversations).
Its user-facing job is "let me talk to the store." A `wa.me` deep link already does that, at
zero cost, in the app the consumer already uses every day.

**Base import** — a store uploading its customer list to invite them — is the most expensive
*and* the most dangerous feature in the product. Doing it safely requires all of:

- temporal quantization of invitation acceptance (else acceptance *speed* is an oracle
  revealing which phone numbers already had the app, i.e. belong to a competitor);
- a first-party link shortener (else the store's own SMS gateway sees the click and deferred
  deep-linking gives the answer away);
- **SMS to every invitee, always** — including those who already have the app, or the
  delivery channel itself becomes the oracle. This is a recurring cash cost;
- an SMS gateway, spend caps, and SMS-pumping fraud defenses.

See [docs/threat-model.md](../threat-model.md) §3.

## Decision

Neither ships in the MVP.

- **"Talk to the store"** is a WhatsApp deep link, plus an Instagram profile link.
- **Store onboarding** happens through organic discovery in the app and a **QR code** the
  store displays in its physical location — the consumer scans it and follows the store,
  giving explicit first-party consent.

Chat ships when a paying tenant asks for the unified inbox. Base import ships with its full
privacy design, or not at all.

## Consequences

**We gain:** roughly five weeks, and we avoid taking on a recurring SMS bill before there is
any revenue.

**We pay:**

- No conversation history and no unified inbox in the panel. Once a consumer moves to
  WhatsApp, we lose visibility into that conversation — and therefore some of the analytics
  in [ADR 0011](0011-events-use-tenant-customer-id.md). We can still record
  `whatsapp.clicked`; we cannot record what was said.
- Stores cannot bring an existing customer base on day one. This is a real go-to-market
  cost, and it is the argument most likely to be raised against this decision. The QR code
  is a partial answer, not a complete one.
- The WhatsApp conversation happens on the store's own number, outside our platform. That is
  fine for the MVP and becomes a strategic weakness if the relationship never returns to us.

**What we deliberately keep:** the *organic* path — public sign-up and store discovery by
category and location. That is not a growth feature we could trade away; it is a **privacy
requirement**. Without an organic front door, "has the app" would prove "belongs to some
store," and every defense around invitations would be theater. See
[ADR 0005](0005-single-multi-brand-consumer-app.md).
