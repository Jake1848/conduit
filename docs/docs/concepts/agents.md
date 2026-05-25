# Agents

An **agent** is a named wallet bound to one operator-issued API key, with an
optional spending policy attached.

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

In the default deployment Conduit runs **one** LND node, and each agent
gets a virtual sub-balance enforced by the policy engine. This is the
simplest model and works well up to mid-volume.

For multi-tenant or high-isolation use cases, you can run one LND per
agent and have Conduit point at the right node based on agent_id. That's
a deployment choice, not a SDK choice — the SDK contract is identical.

## Lifecycle

- **create** — `POST /v1/agents`
- **list**   — `GET /v1/agents`
- **get**    — `GET /v1/agents/{id}`
- **deactivate** — `DELETE /v1/agents/{id}` (soft; sets `active=false`)

Deactivating an agent immediately blocks all outbound payments, even ones
the policy would otherwise allow.
