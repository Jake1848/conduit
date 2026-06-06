# Payments API

## Pay a Lightning address or BOLT11

`POST /v1/payments/pay` — requires `write`

```json
{
  "agent_id": "agt_…",
  "to": "alice@strike.me",
  "sats": 500,
  "memo": "lunch"
}
```

`to` accepts either a Lightning address (`name@host`) or a BOLT11 invoice.

Returns a `Receipt`:

```json
{
  "id": "tx_…",
  "agent_id": "agt_…",
  "status": "settled",
  "hash": "<64 hex chars>",
  "amount_sats": 500,
  "fee_sats": 2,
  "platform_fee_sats": 3,
  "settled_in_ms": 47,
  "destination": "alice@strike.me",
  "memo": "lunch",
  "created_at": "2026-05-25T00:00:00Z"
}
```

- **`fee_sats`** — the Lightning routing fee LND paid to route the payment.
- **`platform_fee_sats`** — the operator's configurable revenue. This is charged
  **on top of** `amount_sats`, debited from the agent on send, kept by the
  operator when the payment settles, and **refunded in full** if the payment
  fails. It is computed from your `PLATFORM_FEE_*` settings and is separate from
  the LND routing fee. See [Platform fees](fees.md).

## Send (BOLT11 or keysend)

`POST /v1/payments/send` — requires `write`

```json
{
  "agent_id": "agt_…",
  "payment_request": "lnbc500u1p3...",
  "memo": "optional"
}
```

Or for keysend:

```json
{
  "agent_id": "agt_…",
  "dest_pubkey": "03abcdef...",
  "sats": 120,
  "memo": "vector embedding"
}
```

## Idempotency

Both payment endpoints accept an optional `Idempotency-Key` request header so
a retried request can never produce a second Lightning payment.

```
POST /v1/payments/send
POST /v1/payments/pay
Idempotency-Key: 7d3f9c1e-1a2b-4c3d-8e5f-0a1b2c3d4e5f
```

- **Format** — any unique string, **max 200 characters**. A UUID4 is
  recommended.
- **Same key + same body** → the original response is returned verbatim
  (same status and body), without re-executing the payment.
- **Same key + different body** → `409 Conflict`
  (`code: IDEMPOTENCY_CONFLICT`). A key is permanently bound to the exact
  request body it was first used with.
- **Failure responses are cached too** (Stripe-style). If the first call
  returned a 4xx/5xx, a retry with the same key replays that same error. A
  *fix-then-retry* workflow must therefore use a **fresh** key.
- **Scoped per API key** — the namespace is `(api_key_id, key)`, so two
  different API keys can use the same idempotency value without colliding.
- **No expiry** — records are kept permanently, so retries are safe
  indefinitely.

The Conduit SDKs attach an `Idempotency-Key` automatically on every payment
(a fresh UUID4 per call, reused across the SDK's own retries). See the
[Python](../sdk/python.md) and [TypeScript](../sdk/typescript.md) SDK docs
for the `idempotency_key` / `idempotencyKey` override.

!!! note "Concurrency"
    Two *simultaneous* requests carrying the same key may both execute (each
    misses the cache before the other commits). Sequential retries — the
    common case, and what the SDKs do — are fully protected. Do not fan the
    same key out across parallel in-flight requests.

## Get one

`GET /v1/payments/{payment_id}` — requires `read`

Returns the same `Receipt` shape as above, including `platform_fee_sats`.
