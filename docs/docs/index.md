# Conduit

**Bitcoin payment infrastructure for autonomous AI agents.**

Conduit gives any AI agent a Lightning wallet, a spending policy, and an API
to send, receive, and account for Bitcoin payments programmatically — with
hard guardrails the agent cannot override.

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

## Why Conduit

LLM agents are starting to do real work: book travel, query metered data,
buy compute, settle with each other. Every one of those flows needs a
payment rail that is:

- **Instant** — Lightning settles in milliseconds.
- **Programmable** — every action is an API call, not a UI flow.
- **Bounded** — the operator sets a budget; the agent stays inside it.
- **Auditable** — every payment is a row in the ledger with a memo.

## What's in this docs site

- **Quickstart** — five-minute first payment, all mock-LND.
- **Concepts** — how Agents, Policies, and the policy engine fit together.
- **SDKs** — Python, TypeScript, and the MCP server for Claude/GPT/etc.
- **API** — the full REST reference.
- **Reference** — error codes, rate limits, changelog.
