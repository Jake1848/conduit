# Invoices API

## Create

`POST /v1/invoices` — requires `write`

```json
{
  "agent_id": "agt_…",
  "amount": 5000,
  "memo": "data feed",
  "expiry": 3600
}
```

Returns:

```json
{
  "id": "inv_…",
  "agent_id": "agt_…",
  "payment_request": "lnbc50u1p3...",
  "payment_hash": "<hex>",
  "amount_sats": 5000,
  "memo": "data feed",
  "status": "pending",
  "expires_at": "2026-05-25T01:00:00Z",
  "created_at": "2026-05-25T00:00:00Z"
}
```

## Get

`GET /v1/invoices/{invoice_id}` — requires `read`

## List

`GET /v1/invoices?agent_id=…&limit=50` — requires `read`
