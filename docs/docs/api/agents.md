# Agents API

## Create

`POST /v1/agents` — requires `admin`

```json
{ "name": "compute-router-7", "daily_limit": 50000 }
```

`daily_limit` is convenience: if provided, Conduit attaches a policy with
`max_per_day=<value>` in the same request.

## List

`GET /v1/agents` — requires `read`

```json
{ "data": [{"id": "agt_…", "name": "…", "active": true, ...}] }
```

## Get one

`GET /v1/agents/{agent_id}` — requires `read`

## Deactivate

`DELETE /v1/agents/{agent_id}` — requires `admin`. Soft-delete; the agent
remains visible but blocks all outbound payments.

## Balance

`GET /v1/agents/{agent_id}/balance` — requires `read`

```json
{
  "agent_id": "agt_…",
  "available_sats": 1234567,
  "pending_sats": 0,
  "total_sats": 1234567
}
```
