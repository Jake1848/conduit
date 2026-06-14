# Quickstart

Five minutes to your first Lightning payment from an AI agent. You run Conduit
yourself — this quickstart runs entirely against a local mock-LND, so no real
Bitcoin moves until you point Conduit at an LND node of your own.

## 1. Run the Core API locally

```bash
git clone https://github.com/Jake1848/conduit.git
cd conduit
docker compose -f docker-compose.dev.yml up --build
```

Verify it's up:

```bash
curl http://localhost:8000/v1/health
# {"ok":true,"version":"0.8.4","network":"testnet"}
```

The dev container ships with `LND_MOCK=true` and a bootstrap admin key
`ck_test_dev_root`. That bootstrap key is **your** master key to **your own**
system — it's how you mint the scoped keys you hand to agents. In production you
set your own via `BOOTSTRAP_API_KEY`.

## 2. Install the SDK

=== "Python"
    ```bash
    pip install conduit-btc
    ```
=== "TypeScript"
    ```bash
    npm i @conduit-btc/sdk
    ```

## 3. Make a payment

=== "Python"
    ```python
    import os
    os.environ["CONDUIT_API_KEY"] = "ck_test_dev_root"
    os.environ["CONDUIT_API_URL"] = "http://localhost:8000"

    from conduit import Agent

    agent = Agent.create(name="hello-world", daily_limit=10_000)
    receipt = agent.keysend(dest_pubkey="02" + "aa" * 32, sats=100, memo="hi")
    print(receipt.hash, "settled in", receipt.settled_in_ms, "ms")
    ```
=== "TypeScript"
    ```ts
    process.env.CONDUIT_API_KEY = "ck_test_dev_root";
    process.env.CONDUIT_API_URL = "http://localhost:8000";

    import { Agent } from '@conduit-btc/sdk';

    const agent = await Agent.create({ name: 'hello-world', dailyLimit: 10_000 });
    const r = await agent.keysend('02' + 'aa'.repeat(32), 100, 'hi');
    console.log(r.hash, 'settled in', r.settledInMs, 'ms');
    ```

## 4. Attach a policy

```python
agent.policy.attach(
    max_per_transaction=200,
    max_per_hour=2_000,
    allowlist=["02beef..."],
    require_memo=True,
)
```

Now any payment over 200 sats, or to a non-allowlisted destination, or
without a memo, will be rejected by the policy engine — before it ever
reaches the Lightning Network.

## 5. (Optional) Set your platform fee

Conduit's built-in revenue is a per-transaction **platform fee in sats** that
**you** configure as the operator. Add it on top of every payment and keep it on
settle (refunded in full on failure):

```bash
PLATFORM_FEE_PERCENT=0.5   # 0.5% of the payment amount (default)
PLATFORM_FEE_MIN_SATS=1    # never less than 1 sat
PLATFORM_FEE_MAX_SATS=1000 # never more than 1000 sats
```

Each payment receipt then reports a `platform_fee_sats` (your revenue) separate
from `fee_sats` (the LND routing fee). Set `PLATFORM_FEE_PERCENT=0` to disable.

## Next

- [Concepts → Policies](concepts/policies.md) — what the engine actually checks
- [Concepts → Security](concepts/security.md) — the self-hosted trust model (and what's operator-custodied)
- [Platform fees](api/fees.md) — your configurable per-transaction revenue
- [SDKs → MCP](sdk/mcp.md) — plug into Claude Desktop or any MCP client
- [Going to production](https://github.com/Jake1848/conduit/blob/main/infra/README.md) — the runbook for your own node
