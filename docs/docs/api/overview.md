# API overview

Base URL: `https://api.conduit.energy`

All requests use TLS. All bodies are JSON. All times are ISO-8601 UTC.

## Conventions

- IDs are prefixed: `agt_…`, `pol_…`, `tx_…`, `inv_…`, `wh_…`, `key_…`.
- Errors return a non-2xx status with a body of:
  ```json
  {
    "error": "policy_violation",
    "code": "DAILY_LIMIT_EXCEEDED",
    "detail": "Payment of 5000 sats would exceed daily limit of 50000 sats (current: 47200 sats used)",
    "agent_id": "agt_…"
  }
  ```
- Pagination, when present, returns `{"data": [...], "has_more": bool}`.

## Versioning

The current API version is `v1`. Breaking changes will live under `/v2/…`;
`/v1/…` will be supported for at least 12 months after a `/v2/…` GA.

## Endpoints

| group | path | docs |
| ----- | ---- | ---- |
| Agents       | `/v1/agents`                       | [agents.md](agents.md) |
| Policies     | `/v1/agents/{id}/policy`           | [policies.md](policies.md) |
| Payments     | `/v1/payments/*`                   | [payments.md](payments.md) |
| Invoices     | `/v1/invoices/*`                   | [invoices.md](invoices.md) |
| Transactions | `/v1/agents/{id}/transactions`, `/v1/transactions/recent` | [transactions.md](transactions.md) |
| Metrics      | `/v1/metrics`                      | [metrics.md](metrics.md) |
| Webhooks     | `/v1/webhooks`                     | [webhooks.md](webhooks.md) |
| System       | `/v1/health`, `/v1/status`         | — |
