# Quickstart

Five minutes to your first Lightning payment from an AI agent. Runs entirely
against a local mock-LND so no real Bitcoin moves.

## 1. Run the Core API locally

```bash
git clone https://github.com/Jake1848/conduit.git
cd conduit
docker compose up --build
```

Verify it's up:

```bash
curl http://localhost:8000/v1/health
# {"ok":true,"version":"0.6.0","network":"testnet"}
```

The dev container ships with `LND_MOCK=true` and a bootstrap admin key
`ck_test_dev_root`.

## 2. Install the SDK

=== "Python"
    ```bash
    pip install conduit-sdk
    ```
=== "TypeScript"
    ```bash
    npm i @conduit/sdk
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

    import { Agent } from '@conduit/sdk';

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

## Next

- [Concepts → Policies](concepts/policies.md) — what the engine actually checks
- [SDKs → MCP](sdk/mcp.md) — plug into Claude Desktop or any MCP client
- [Going to production](https://github.com/Jake1848/conduit/blob/main/infra/README.md) — the Hetzner runbook
