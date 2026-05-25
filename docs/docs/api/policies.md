# Policies API

## Attach (or replace)

`POST /v1/agents/{agent_id}/policy` — requires `admin`

```json
{
  "max_per_transaction": 1000,
  "max_per_hour": 10000,
  "max_per_day": 50000,
  "max_per_minute_count": 60,
  "allowlist": ["02beef..."],
  "blocklist": [],
  "require_memo": true,
  "enabled": true
}
```

Idempotent: a second call replaces the policy in place.

## Get

`GET /v1/agents/{agent_id}/policy` — requires `read`

## Update

`PUT /v1/agents/{agent_id}/policy` — same body as POST. Requires `admin`.

## Remove

`DELETE /v1/agents/{agent_id}/policy` — requires `admin`. Removing a
policy leaves only the default 60-payments-per-minute rate limit.
