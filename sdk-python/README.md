# conduit-sdk

Python SDK for **Conduit** — Bitcoin Lightning payment infrastructure for
autonomous AI agents.

```bash
pip install conduit-sdk
```

```python
from conduit import Agent

agent = Agent.create(name="compute-router-7", daily_limit=50_000)

agent.policy.attach(
    max_per_hour=10_000,
    allowlist=["02beef..."],
)

receipt = agent.pay(
    to="compute-node-7@lnd.conduit.energy",
    sats=150,
    memo="dataset query",
)

print(receipt.hash, receipt.settled_in_ms)
```

## Configuration

The SDK reads `CONDUIT_API_KEY` and `CONDUIT_API_URL` (default
`https://api.conduit.energy`) from the environment.

```bash
export CONDUIT_API_KEY=ck_live_xxxxxxxxxxxxx
```

or explicitly:

```python
import conduit
conduit.api_key = "ck_live_..."
conduit.base_url = "https://api.conduit.energy"
```

## Errors

```python
from conduit import PolicyViolation, InsufficientBalance, PaymentFailed

try:
    agent.pay(to=..., sats=...)
except PolicyViolation as e:
    print(e.code, e.message)  # e.g. "DAILY_LIMIT_EXCEEDED"
```

See the full error code list in the API docs.
