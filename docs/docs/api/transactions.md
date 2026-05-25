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

## Get one

`GET /v1/transactions/{tx_id}` — requires `read`
