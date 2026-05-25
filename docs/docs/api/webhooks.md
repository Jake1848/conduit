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
X-Conduit-Signature: sha256=<hex hmac-sha256(secret, body)>

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

Verify the signature in your handler. Conduit retries up to 6 times with
exponential backoff on any non-2xx response.

## Events

| event              | when |
| ------------------ | ---- |
| `payment.settled`  | an outbound payment was successfully routed |
| `payment.failed`   | an outbound payment failed at the Lightning layer |
| `invoice.settled`  | someone paid an invoice you created (planned) |

## List / unsubscribe

`GET /v1/webhooks` — requires `admin`
`DELETE /v1/webhooks/{id}` — requires `admin`
