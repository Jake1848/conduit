# Rate limits

There are three layers to be aware of.

## 1. Per-agent payment rate (policy engine)

Enforced by Conduit inside the policy engine. Default is **60 payments per
minute** per agent. Tunable per-agent:

```python
agent.policy.attach(max_per_minute_count=10)
```

Exceeding it returns 403 with code `RATE_LIMIT_EXCEEDED` (yes, 403 not 429 —
this is a *policy* decision, distinct from HTTP-layer throttling).

## 2. Per-API-key request rate (HTTP layer)

Conduit ships an in-process token-bucket rate limiter. Per API key when the
request is authenticated, per client IP otherwise. Defaults:

| env var                  | default | meaning |
| ------------------------ | ------- | ------- |
| `RATE_LIMIT_PER_MINUTE`  | 300     | sustained rate per identity. 0 disables. |
| `RATE_LIMIT_BURST`       | 60      | bucket size — max in-flight allowed at once |

When violated, returns **429** with:

```json
{
  "error": "rate_limited",
  "code": "RATE_LIMITED",
  "detail": "Too many requests. Slow down and retry after N seconds.",
  "retry_after": N
}
```

The response also carries a `Retry-After: N` header.

`/v1/health` bypasses the limiter so liveness probes never get 429'd.

### Multi-worker caveat

The token bucket is **per uvicorn worker**. With N workers, a smart attacker
hashing onto different workers can land N × `RATE_LIMIT_PER_MINUTE`
requests/minute. The recommended deployment runs one uvicorn worker behind
nginx with `limit_req` providing a cross-worker safety net (the production
nginx config in `infra/nginx/conduit.prod.conf` includes this).

## 3. Lightning-layer back-pressure

Some failures look like rate limits but aren't: if your node lacks outbound
channel capacity, payments will fail with `PAYMENT_FAILED` regardless of how
slowly you send them. Open more channels rather than slowing down.
