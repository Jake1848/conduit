# Metrics API

Server-aggregated fleet metrics, computed in a single query so a dashboard does
not have to fan out across every agent. Added in 0.6.0.

## Fleet metrics

`GET /v1/metrics` — requires `read`

Returns treasury + activity aggregates, a 24-hour hourly series (for charts), and
the most active agents today.

```json
{
  "treasury_sats": 898937404,
  "active_agents": 958,
  "total_agents": 968,
  "tx_per_min": 90,
  "avg_settlement_ms": 142,
  "p99_settlement_ms": 460,
  "hourly": [
    { "hour": "2026-06-01T00:00:00Z", "count": 1842, "volume_sats": 5120334 }
    // … 24 buckets, oldest → newest (last entry = current hour)
  ],
  "top_agents": [
    { "agent_id": "agt_…", "name": "rpc-gateway-397320", "tx_today": 121, "balance_sats": 449160, "active": true }
    // … up to 20, ordered by transactions today (desc)
  ]
}
```

| field | meaning |
| ----- | ------- |
| `treasury_sats` | Σ `balance_sats` across all agents |
| `active_agents` / `total_agents` | agents where `active=true` / all agents |
| `tx_per_min` | transactions created in the last 60s |
| `avg_settlement_ms` / `p99_settlement_ms` | over the last 500 settled sends with a recorded latency (`null` if none) |
| `hourly[]` | 24 hourly buckets over the last 24h: `count` (tx) + `volume_sats` (Σ `amount_sats`) |
| `top_agents[]` | up to 20 agents with the most transactions today |

This endpoint is consumed by the [Conduit Console](../index.md) dashboard for its
stat cards, charts, and "most active" wallet list.
