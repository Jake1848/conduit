# conduit-btc

Python SDK for **Conduit** — self-hosted, non-custodial Bitcoin Lightning
payment infrastructure for autonomous AI agents.

**Your node, your keys, your rules.** Conduit is software tooling that you run
on your own infrastructure, against your own LND node, with your own keys. It
never touches your funds — it's a thin client for *your* Conduit instance.

```bash
pip install conduit-btc
```

> The importable package is `conduit`:
>
> ```python
> from conduit import Agent
> ```

## Quickstart

Point the SDK at the Conduit instance you deployed (a 5-minute Docker deploy
against your own LND node), create an agent, and send a payment:

```python
import conduit
from conduit import Agent

# Connect to YOUR self-hosted Conduit instance
conduit.api_key = "ck_live_..."              # an API key from your instance
conduit.base_url = "https://conduit.example.com"  # your Conduit URL

# Create an autonomous wallet with an optional spending policy
agent = Agent.create(name="compute-router-7", daily_limit=50_000)

agent.policy.attach(
    max_per_hour=10_000,
    allowlist=["02beef..."],
)

# Send a Lightning payment
receipt = agent.pay(
    to="compute-node-7@lnd.example.com",
    sats=150,
    memo="dataset query",
)

print(receipt.hash, receipt.settled_in_ms)
print(receipt.fee_sats, receipt.platform_fee_sats)
```

## Client-centric API (`ConduitClient`)

Prefer a single client object with explicit methods over the `Agent`
active-record style? `ConduitClient` wraps the same retrying, idempotent HTTP
client and adds operator funding (`credit_agent`) — from `pip install` to a
settled payment in a few lines:

```python
from conduit import ConduitClient

client = ConduitClient(base_url="https://conduit.example.com", api_key="ck_live_...")

agent = client.create_agent("compute-router-7")
client.credit_agent(agent.id, sats=10_000)            # operator funds the agent

receipt = client.send_payment(agent.id, dest_pubkey="02beef...", sats=500)
print(receipt.status, receipt.platform_fee_sats)      # 'settled', 2

print(client.get_balance(agent.id).available)         # spendable sats
for tx in client.list_transactions(agent.id):
    print(tx.direction, tx.amount_sats, tx.status)
```

Both styles talk to the same instance — use whichever you prefer.

## Platform fee on receipts

Every payment receipt includes a **`platform_fee_sats`** field — the per-transaction
platform fee in satoshis configured by the operator who deployed the instance.
It is **separate** from `fee_sats` (the LND routing fee):

- `fee_sats` — the Lightning Network routing fee paid to route the payment.
- `platform_fee_sats` — the operator's usage-based revenue, charged on top, kept
  on settle, and refunded in full if the payment fails.

The fee is configured on your instance via `PLATFORM_FEE_PERCENT` (default `0.5`%),
`PLATFORM_FEE_MIN_SATS` (default `1`), and `PLATFORM_FEE_MAX_SATS` (default `1000`).

```python
receipt = agent.pay(to="...", sats=10_000)
print(receipt.amount_sats)        # 10000
print(receipt.fee_sats)           # LND routing fee
print(receipt.platform_fee_sats)  # your platform's per-tx revenue
```

## Configuration

The SDK reads `CONDUIT_API_KEY` and `CONDUIT_API_URL` (default
`https://api.conduit.energy`, the hosted demo console) from the environment.
Set `CONDUIT_API_URL` to the URL of your own Conduit deployment.

```bash
export CONDUIT_API_KEY=ck_live_xxxxxxxxxxxxx
export CONDUIT_API_URL=https://conduit.example.com
```

or explicitly in code:

```python
import conduit
conduit.api_key = "ck_live_..."
conduit.base_url = "https://conduit.example.com"
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

## Links

- Repository: <https://github.com/Jake1848/conduit>
- License: MIT
