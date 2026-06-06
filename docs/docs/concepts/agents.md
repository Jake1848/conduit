# Agents

An **agent** is a named virtual wallet on **your own** node, bound to one
operator-issued API key, with an optional spending policy attached. You — the
operator running Conduit — create agents and fund them; their balances are
sub-balances of your LND node, never held by Conduit.

```python
agent = Agent.create(name="compute-router-7", daily_limit=50_000)
```

You get back an opaque ID like `agt_8f3k…`. The agent has its own balance,
its own transaction history, and its own policy.

## Fields

| field | description |
| ----- | ----------- |
| `id`         | `agt_…` opaque identifier |
| `name`       | unique human-readable label |
| `pubkey`     | the Lightning node pubkey this agent uses for outbound keysends |
| `active`     | master on/off switch |
| `created_at` | ISO timestamp |

## Wallet model

In the default deployment **you** run **one** LND node, and each agent gets a
virtual sub-balance on that node, enforced by the policy engine. Conduit tracks
the ledger; the sats stay in **your** channels — Conduit never custodies them.
This is the simplest model and works well up to mid-volume.

For multi-tenant or high-isolation use cases, you can run one LND per agent and
have Conduit point at the right node based on agent_id. That's a deployment
choice you make, not a SDK choice — the SDK contract is identical.

## Funding an agent

A new agent starts at a balance of **0**. As the operator you credit it from
your node's liquidity with `POST /v1/agents/{id}/credit`, and you can sweep
funds back out with `POST /v1/agents/{id}/debit`. Both are `admin`-scope
operator actions on **your own** ledger — see the
[Agents API](../api/agents.md). The agent then spends its sub-balance subject to
its policy.

## Lifecycle

- **create** — `POST /v1/agents`
- **list**   — `GET /v1/agents`
- **get**    — `GET /v1/agents/{id}`
- **deactivate** — `DELETE /v1/agents/{id}` (soft; sets `active=false`)

Deactivating an agent immediately blocks all outbound payments, even ones
the policy would otherwise allow.
