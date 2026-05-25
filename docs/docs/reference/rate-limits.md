# Rate limits

There are two independent rate limits to be aware of.

## Per-agent payment rate (policy engine)

Enforced by Conduit. Default is **60 payments per minute** per agent, even
if no policy is attached. Customize per-agent:

```python
agent.policy.attach(max_per_minute_count=10)
```

Exceeding it returns 403 with code `RATE_LIMIT_EXCEEDED`.

## Per-API-key request rate (planned)

A global request limit on the HTTP layer, independent of payment volume.
Not currently enforced; will be added in a future release. When violated,
the response will be 429 with code `RATE_LIMITED` and a `Retry-After`
header.

## Lightning-layer back-pressure

Some failures look like rate limits but aren't: if your node lacks
outbound channel capacity, payments will fail with `PAYMENT_FAILED`
regardless of how slowly you send them. Open more channels rather than
slowing down.
