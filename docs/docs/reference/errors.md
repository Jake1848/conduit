# Errors

Every Conduit error response has this shape:

```json
{
  "error": "policy_violation",
  "code": "DAILY_LIMIT_EXCEEDED",
  "detail": "Payment of 5000 sats would exceed daily limit of 50000 sats (current: 47200 sats used)",
  "agent_id": "agt_…"
}
```

| code | HTTP | meaning |
| ---- | ---- | ------- |
| `AUTHENTICATION_ERROR`           | 401 | missing or invalid API key |
| `PERMISSION_DENIED`              | 403 | API key scope is below what the endpoint requires |
| `AGENT_NOT_FOUND`                | 404 | the requested `agent_id` does not exist |
| `NOT_FOUND`                      | 404 | generic 404 (transaction, invoice, etc.) |
| `INVALID_INPUT`                  | 422 | request body failed validation |
| `POLICY_VIOLATION`               | 403 | parent code for any policy denial |
| `POLICY_DISABLED`                | 403 | the agent's policy has `enabled=false` |
| `AGENT_INACTIVE`                 | 403 | the agent has been deactivated |
| `AMOUNT_INVALID`                 | 403 | payment amount ≤ 0 |
| `PER_TRANSACTION_LIMIT_EXCEEDED` | 403 | single payment too large |
| `HOURLY_LIMIT_EXCEEDED`          | 403 | rolling-hour cap exceeded |
| `DAILY_LIMIT_EXCEEDED`           | 403 | rolling-day cap exceeded |
| `RATE_LIMIT_EXCEEDED`            | 403 | per-minute payment count exceeded |
| `DESTINATION_BLOCKLISTED`        | 403 | destination on `blocklist` |
| `DESTINATION_NOT_ALLOWLISTED`    | 403 | `allowlist` non-empty and destination not in it |
| `MEMO_REQUIRED`                  | 403 | `require_memo=true` and memo missing/blank |
| `POLICY_EVALUATION_ERROR`        | 403 | engine could not evaluate the rules; **fail-closed** denial |
| `INSUFFICIENT_BALANCE`           | 402 | wallet balance too low for the payment |
| `PAYMENT_FAILED`                 | 502 | Lightning Network rejected the payment (no route, htlc expired, etc.) |
| `LND_ERROR`                      | 502 | the upstream LND node failed |
| `RATE_LIMITED`                   | 429 | too many requests to the API itself |
