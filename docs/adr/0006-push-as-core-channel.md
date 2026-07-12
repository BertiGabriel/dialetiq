# 0006. Push as the core channel, mirrored by an in-app message center

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

The product's core promise to a tenant is: *reach your customers*. Push notification (FCM)
is the channel.

But push is not a reliable channel. iOS push opt-in averages around 50%. A "core channel"
with a 50% ceiling on day one, and no fallback, is a product with a 50% ceiling.

Separately, a naive fan-out has a failure mode that ends companies: a worker dies mid-blast,
retries, and re-sends to all 500,000 recipients.

## Decision

Push via FCM is the primary channel, with two structural safeguards.

**1. Every campaign is persisted as an in-app message**, whether or not the push is
delivered. The app has a message center that mirrors all sends. The message exists in the
database independently of delivery.

**2. The audience is materialized in the database before any send.** A `campaign_recipient`
row per addressee, with a state machine, created idempotently:

```sql
INSERT INTO campaign_recipient (id, tenant_id, campaign_id, tenant_customer_id, status)
SELECT gen_uuid_v7(), :tid, :cid, tc.id, 'PENDING'
FROM tenant_customer tc WHERE tc.tenant_id = :tid AND <segment>
ON CONFLICT (campaign_id, tenant_customer_id) DO NOTHING;
```

Workers claim batches with `FOR UPDATE SKIP LOCKED`. A retry resumes; it does not restart.

## Consequences

**We gain:** delivery is idempotent and resumable. The message center lifts the effective
reach ceiling above the push opt-in rate, and it also enables a global frequency cap
implemented as *delay* rather than as visible suppression — which matters, because visible
suppression would hand a tenant the list of consumers its competitors also reach.

**We pay:**

- A row per recipient per campaign. A 500k-device campaign writes 500k rows. Storage is
  cheap; correctness is not.
- `campaign_recipient` must never carry `device_id`, `fcm_token`, or a device count.
  Per-device delivery errors from FCM (`QUOTA_EXCEEDED`, `THROTTLED`) must collapse into a
  single opaque `PENDING_RETRY` bucket — otherwise a tenant can observe that a specific
  consumer's device is being hammered, and infer another tenant's traffic.
- `collapse_key` must be scoped to `(tenant_id, campaign_id)`. A shared collapse key lets
  one store's push replace another's in the tray, and the resulting open-rate difference
  reveals which consumers are shared.
- FCM has no batch endpoint (it was deprecated). 500k messages is 500k HTTP/2 requests.
  Throughput must be engineered, not assumed.
