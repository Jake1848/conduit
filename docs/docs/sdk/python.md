# Python SDK

```bash
pip install conduit-btc
```

## Configure

```bash
export CONDUIT_API_KEY=ck_live_xxxxxxxxxxxx
export CONDUIT_API_URL=https://api.conduit.energy   # optional
```

or in code:

```python
import conduit
conduit.api_key = "ck_live_..."
conduit.base_url = "https://api.conduit.energy"
```

For full control (custom timeout, retry budget, or a shared client), build
one explicitly and install it as the default:

```python
from conduit import Conduit, set_default_client

set_default_client(
    Conduit(
        api_key="ck_live_...",
        base_url="https://api.conduit.energy",
        timeout=30.0,
        max_retries=3,
    )
)
```

## Agent

```python
from conduit import Agent

# Create
agent = Agent.create(name="compute-router-7", daily_limit=50_000)

# Fetch by id
agent = Agent.get("agt_…")

# List
agents = Agent.list()
```

## Policy

```python
agent.policy.attach(
    max_per_transaction=200,
    max_per_hour=2_000,
    max_per_day=10_000,
    allowlist=["02beef..."],
    require_memo=True,
)
agent.policy.fetch()    # refresh from server
agent.policy.remove()   # detach
```

After `attach()` or `fetch()`, fields are accessible:

```python
agent.policy.max_per_day        # 10000
agent.policy.allowlist          # ['02beef...']
```

## Pay / receive

```python
# Lightning address or BOLT11:
r = agent.pay(to="alice@strike.me", sats=500, memo="lunch")

# Explicit BOLT11:
r = agent.send_invoice("lnbc500u1p...")

# Keysend (push to a pubkey):
r = agent.keysend("03abcdef...", sats=120)

# Create an invoice to receive:
inv = agent.receive(amount=5_000, memo="data feed")
print(inv.payment_request)
```

## Balance & transactions

```python
b = agent.balance
print(b.available, b.pending, b.total)

txns = agent.transactions(limit=50, direction="send")
```

## Retries

The client retries transient failures automatically:

- Retries on **HTTP 429**, **5xx**, and **network/timeout** errors.
- **Exponential backoff** — 1s, 2s, 4s.
- Honors the server's `Retry-After` header when present (capped at 60s); any
  empty / non-numeric / negative value falls back to exponential backoff.
- **Never** retries other 4xx (a `PolicyViolation`, `InsufficientBalance`,
  etc. fails fast).
- Up to `max_retries` retries (default **3** → 4 total attempts).

```python
from conduit import Conduit, set_default_client

set_default_client(Conduit(max_retries=5))   # or 0 to disable retries
```

## Idempotency

Every payment method (`pay`, `send_invoice`, `keysend`) sends an
`Idempotency-Key` header automatically — a fresh UUID4 per call, **reused
across the SDK's own retries** — so a retried payment can never settle
twice. Pass an explicit key to make a *manual* retry idempotent too:

```python
key = "order-12345"
agent.pay(to="alice@strike.me", sats=500, idempotency_key=key)
# If this raises a network error and you retry with the SAME key,
# the server returns the original result instead of paying again.
agent.pay(to="alice@strike.me", sats=500, idempotency_key=key)
```

Reusing a key with a **different** body raises a `ConduitError`
(`code == "IDEMPOTENCY_CONFLICT"`). See the
[Payments API → Idempotency](../api/payments.md#idempotency) for the full
server-side semantics.

## Webhook verification

Verify the `X-Conduit-Signature` header on incoming webhooks before trusting
the payload. `verify_webhook` returns a bool; `parse_webhook` verifies and
returns the decoded event, raising `WebhookVerificationError` on a bad
signature.

```python
from conduit import parse_webhook, WebhookVerificationError
from conduit.webhook import verify_webhook  # also exported from conduit

# FastAPI
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
WEBHOOK_SECRET = "whsec_..."   # the secret returned when you created the webhook

@app.post("/conduit/events")
async def conduit_events(request: Request):
    body = await request.body()                       # RAW bytes — do not re-encode
    signature = request.headers.get("X-Conduit-Signature", "")
    try:
        event = parse_webhook(body, signature, WEBHOOK_SECRET)
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="bad signature")
    # event == {"event": "payment.settled", "data": {...}, "ts": 1748140800}
    return {"ok": True}
```

Flask is the same shape — use `request.get_data()` for the raw body and
`request.headers["X-Conduit-Signature"]`.

> Always verify against the **raw request bytes**. Re-serializing the JSON
> (even with the same fields) changes the bytes and the signature won't match.

## Errors

```python
from conduit import (
    ConduitError,
    AuthenticationError,
    PermissionDenied,
    PolicyViolation,
    InsufficientBalance,
    PaymentFailed,
    AgentNotFound,
    RateLimited,
    WebhookVerificationError,
)

try:
    agent.pay(...)
except PolicyViolation as e:
    print(e.code, e.message)
    # 'DAILY_LIMIT_EXCEEDED', 'Payment of 5000 sats would exceed daily limit of 50000…'
```

All Conduit exceptions inherit from `ConduitError`. Every one carries
`.code` (machine-readable) and `.message` (human-readable).
