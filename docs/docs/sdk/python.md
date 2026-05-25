# Python SDK

```bash
pip install conduit-sdk
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

## Errors

```python
from conduit import (
    ConduitError,
    AuthenticationError,
    PolicyViolation,
    InsufficientBalance,
    PaymentFailed,
    AgentNotFound,
    RateLimited,
)

try:
    agent.pay(...)
except PolicyViolation as e:
    print(e.code, e.message)
    # 'DAILY_LIMIT_EXCEEDED', 'Payment of 5000 sats would exceed daily limit of 50000…'
```

All Conduit exceptions inherit from `ConduitError`. Every one carries
`.code` (machine-readable) and `.message` (human-readable).
