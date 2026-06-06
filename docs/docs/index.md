# Conduit

**Self-hosted Bitcoin Lightning payment infrastructure for autonomous AI agents.**

Conduit is software tooling you run on **your own** infrastructure, in front of
**your own** LND node, with **your own** keys. It gives any AI agent a virtual
Lightning wallet, a spending policy, and an API to send, receive, and account
for Bitcoin payments programmatically — with hard guardrails the agent cannot
override. There is no Conduit SaaS: you host it, Conduit never holds your funds
and never phones home. The agents you create are **virtual sub-balances** in a
ledger you, the operator, control — they hold a scoped API key, not a signing
key. Your node, your keys, your rules.

!!! info "Status — v0.8.0"
    Conduit runs **live on testnet** (testnet/regtest today). Mainnet is a
    supported target the software is built for but has not yet been exercised in
    production. There is no external security audit yet — test on testnet first.

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
- **Self-hosted** — you run it; your LND node, your keys, your channels.

## Self-hosted

You deploy Conduit (a 5-minute Docker bring-up) against your own LND node.
Conduit is the policy + accounting layer in front of a node **you** control —
there is no Conduit SaaS, it never holds your money and never phones home. The
bootstrap API key is **your** master key to **your own** system. The agents you
create are virtual sub-balances in Conduit's ledger — operator-controlled IOUs
that **you** credit, debit, and can sweep; an agent holds a scoped API key, not
a signing key, so Conduit is custodial *at the agent layer by construction*
while the sats stay in **your** channels under **your** keys. See
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
