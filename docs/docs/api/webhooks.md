# Webhooks API

## Subscribe

`POST /v1/webhooks` — requires `admin`

```json
{
  "url": "https://my-app.example.com/conduit/events",
  "events": ["payment.settled", "payment.failed"]
}
```

Response includes a `secret` shown **exactly once**:

```json
{
  "id": "wh_…",
  "url": "…",
  "events": ["payment.settled", "payment.failed"],
  "secret": "whsec_…",
  "active": true,
  "created_at": "2026-05-25T00:00:00Z"
}
```

## Delivery format

```http
POST /your/endpoint
Content-Type: application/json
X-Conduit-Event: payment.settled
X-Conduit-Webhook-Id: wh_…
X-Conduit-Signature:        sha256=<hex hmac-sha256(webhook_secret, body)>
X-Conduit-Server-Signature: sha256=<hex hmac-sha256(API_SECRET_KEY, body)>

{
  "event": "payment.settled",
  "ts": 1748140800,
  "data": {
    "transaction_id": "tx_…",
    "agent_id": "agt_…",
    "amount_sats": 150,
    "fee_sats": 1,
    "hash": "<hex>"
  }
}
```

Every delivery carries **two** signatures:

- `X-Conduit-Signature` — per-webhook secret. Different for every
  subscription; rotates if you delete and recreate the webhook.
- `X-Conduit-Server-Signature` — server-wide `API_SECRET_KEY`. Same key for
  every webhook. Useful as defense-in-depth: an attacker who steals one
  webhook secret still cannot forge events without the server key.

Verify whichever fits your threat model (typically the per-webhook one).
Conduit retries up to 6 times with exponential backoff on any non-2xx
response.

## Events

| event              | when |
| ------------------ | ---- |
| `payment.settled`  | an outbound payment was successfully routed |
| `payment.failed`   | an outbound payment failed at the Lightning layer |
| `invoice.settled`  | someone paid an invoice you created — the agent has been credited |
| `invoice.expired`  | an invoice you created expired (or was canceled) without payment |

### `invoice.settled` payload

```json
{
  "event": "invoice.settled",
  "ts": 1748140800,
  "data": {
    "transaction_id": "tx_…",
    "agent_id": "agt_…",
    "amount_sats": 5000,
    "payment_hash": "<hex>"
  }
}
```

The `amount_sats` is the amount actually received, which can exceed the
invoice value on AMP payments. The agent's `balance_sats` has already been
credited by the time this fires.

### `invoice.expired` payload

```json
{
  "event": "invoice.expired",
  "ts": 1748140800,
  "data": {
    "transaction_id": "tx_…",
    "agent_id": "agt_…",
    "payment_hash": "<hex>"
  }
}
```

## List / unsubscribe

`GET /v1/webhooks` — requires `admin`
`DELETE /v1/webhooks/{id}` — requires `admin`
