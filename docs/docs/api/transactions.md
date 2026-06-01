# Transactions API

## List for an agent

`GET /v1/agents/{agent_id}/transactions?limit=50&direction=send&status=settled`

Filters (all optional):

- `direction` — `send` | `receive`
- `status` — `pending` | `settled` | `failed`
- `limit` — 1–500 (default 50)

Returns:

```json
{
  "data": [
    {
      "id": "tx_…",
      "agent_id": "agt_…",
      "direction": "send",
      "amount_sats": 150,
      "fee_sats": 1,
      "destination": "alice@strike.me",
      "payment_hash": "<hex>",
      "status": "settled",
      "memo": "lunch",
      "settled_at": "2026-05-25T00:00:00Z",
      "latency_ms": 42,
      "created_at": "2026-05-25T00:00:00Z"
    }
  ],
  "has_more": false
}
```

## Recent across the fleet

`GET /v1/transactions/recent?limit=50` — requires `read` _(added in 0.6.0)_

The `limit` (1–500, default 50) most recent transactions across **all** agents,
ordered by `created_at` desc. One query — used by the dashboard live feed and
audit log instead of polling every agent. Returns the same
`{ "data": [Transaction], "has_more": bool }` shape as the per-agent list above.

## Get one

`GET /v1/transactions/{tx_id}` — requires `read`
