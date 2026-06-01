# Agents API

## Create

`POST /v1/agents` — requires `admin`

```json
{ "name": "compute-router-7", "daily_limit": 50000 }
```

`daily_limit` is convenience: if provided, Conduit attaches a policy with
`max_per_day=<value>` in the same request.

New agents start with a **balance of 0**. Use `POST /v1/agents/{id}/credit`
to fund them before they can pay anyone.

## List

`GET /v1/agents` — requires `read`

```json
{ "data": [{"id": "agt_…", "name": "…", "active": true, "balance_sats": 12408, "created_at": "…"}] }
```

Each agent object carries `balance_sats` (the denormalized spendable balance,
added in 0.6.0) so you can sum a fleet treasury without an `/balance` call per
agent. `pending_sats` is still only available on the per-agent balance endpoint.

## Get one

`GET /v1/agents/{agent_id}` — requires `read` (same object shape, incl. `balance_sats`)

## Deactivate

`DELETE /v1/agents/{agent_id}` — requires `admin`. Soft-delete; the agent
remains visible but blocks all outbound payments.

## Balance

`GET /v1/agents/{agent_id}/balance` — requires `read`

```json
{
  "agent_id": "agt_…",
  "available_sats": 1234567,
  "pending_sats": 4321,
  "total_sats": 1238888
}
```

- **`available_sats`** — what the agent can spend right now. Already net of
  any pending outbound HTLCs (the payment route debits before going pending).
- **`pending_sats`** — sats currently locked in pending outbound payments. If
  those payments all fail and refund, you get these back.
- **`total_sats`** — `available_sats + pending_sats`. The amount the agent
  would have if every in-flight payment failed.

The aggregate of `available_sats` across all agents is bounded above by the
LND node's outbound channel capacity, reported separately at `/v1/status`.

## Credit

`POST /v1/agents/{agent_id}/credit` — requires `admin`

Operator-initiated deposit. In a fully-automated deployment this also fires
when an inbound Lightning invoice settles (the [InvoiceWatcher] credits the
agent automatically). The manual endpoint is for top-ups and reconciliation.

```json
{ "sats": 100000, "reason": "monthly allowance", "metadata": {"period": "2026-05"} }
```

Response (status 201):

```json
{
  "agent_id": "agt_…",
  "transaction_id": "tx_…",
  "delta_sats": 100000,
  "balance_sats": 100000
}
```

## Debit

`POST /v1/agents/{agent_id}/debit` — requires `admin`

Operator-initiated withdrawal. Sweeps funds out of the agent's virtual
balance without going through the Lightning payment path — useful for
treasury moves that shouldn't burn an HTLC.

```json
{ "sats": 5000, "reason": "month-end sweep" }
```

Response (status 201):

```json
{
  "agent_id": "agt_…",
  "transaction_id": "tx_…",
  "delta_sats": -5000,
  "balance_sats": 95000
}
```

Returns 402 `INSUFFICIENT_BALANCE` if the agent doesn't have enough sats.

[InvoiceWatcher]: ../concepts/payments.md
