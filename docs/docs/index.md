# Conduit

**Self-hosted, non-custodial Bitcoin payment infrastructure for autonomous AI agents.**

Conduit is software tooling you run on **your own** infrastructure, in front of
**your own** LND node, signed by **your own** keys. It gives any AI agent a
Lightning wallet, a spending policy, and an API to send, receive, and account
for Bitcoin payments programmatically — with hard guardrails the agent cannot
override. Conduit **never touches your funds**: there is no Conduit-operated
wallet and no third party in the payment path. Your node, your keys, your rules.

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
- **Self-custodial** — you run it; your LND node, your keys, your channels.

## Self-hosted & non-custodial

You deploy Conduit (a 5-minute Docker bring-up) against your own LND node.
Conduit is the policy + accounting layer in front of a node **you** control — it
never holds your money. The bootstrap API key is **your** master key to **your
own** system, and the agents you create are virtual sub-balances on **your**
node, credited and debited by **you**. See
[Concepts → Security](concepts/security.md) for the full trust model.

## Built-in revenue

Conduit's monetization is a small, usage-based **platform fee in satoshis** that
**you**, the operator, configure (`PLATFORM_FEE_PERCENT`, `PLATFORM_FEE_MIN_SATS`,
`PLATFORM_FEE_MAX_SATS`). It is charged on top of each payment, kept on settle,
and refunded in full on failure — and it is **your** revenue, not a Conduit cut.
Set the percent to `0` to disable it. Collected fees are reported at
[`GET /v1/fees`](api/fees.md).

## What's in this docs site

- **Quickstart** — five-minute first payment, all mock-LND.
- **Concepts** — how Agents, Policies, and the policy engine fit together.
- **SDKs** — Python, TypeScript, and the MCP server for Claude/GPT/etc.
- **API** — the full REST reference.
- **Reference** — error codes, rate limits, changelog.
