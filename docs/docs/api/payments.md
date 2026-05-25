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
  "settled_in_ms": 47,
  "destination": "alice@strike.me",
  "memo": "lunch",
  "created_at": "2026-05-25T00:00:00Z"
}
```

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

## Get one

`GET /v1/payments/{payment_id}` — requires `read`
