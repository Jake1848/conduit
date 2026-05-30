# Authentication

Every request requires an API key sent as a Bearer token:

```
Authorization: Bearer ck_live_xxxxxxxxxxxxxxxxxxxxx
```

## Key formats

| prefix | meaning |
| ------ | ------- |
| `ck_live_…` | Mainnet keys — talk to real Lightning |
| `ck_test_…` | Testnet / development keys |

## Scopes

| scope | can do |
| ----- | ------ |
| `read`  | list and inspect agents, balances, transactions |
| `write` | everything `read` can + send payments, create invoices |
| `admin` | everything `write` can + create/delete agents, manage policies, manage webhooks, mint new API keys |

A key with a lower scope is **denied with 403** if it tries to do
something above its level. Operationally, give your agents `write` keys
and keep `admin` for human operators only.

## Minting

```bash
curl -X POST https://api.conduit.energy/v1/api-keys \
  -H "Authorization: Bearer ck_live_admin..." \
  -H "Content-Type: application/json" \
  -d '{"scope": "write", "label": "compute-router-7"}'
```

The response includes the raw secret **exactly once**. Save it
immediately — it cannot be retrieved later.

```json
{
  "id": "key_…",
  "label": "compute-router-7",
  "scope": "write",
  "secret": "ck_live_xxxxxxxxxxxxxxxxxxxx",
  "created_at": "2026-05-25T00:00:00Z"
}
```

## Listing keys

`GET /v1/api-keys` — requires `admin`

Returns metadata for every key. The raw secret is **never** included — it
only ever appears in the one-time creation response above.

```json
{
  "data": [
    {
      "id": "key_…",
      "label": "compute-router-7",
      "scope": "write",
      "prefix": "ck_live_",
      "created_at": "2026-05-25T00:00:00Z",
      "last_used_at": "2026-05-27T12:00:00Z",
      "revoked": false
    }
  ]
}
```

## Revoking a key

`DELETE /v1/api-keys/{key_id}` — requires `admin`

Marks the key revoked and returns `204 No Content`. The **next request** that
authenticates with that key gets `401`. Revocation is **idempotent** —
revoking an already-revoked key also returns `204`. An unknown `key_id`
returns `404`.

```bash
curl -X DELETE https://api.conduit.energy/v1/api-keys/key_abc123 \
  -H "Authorization: Bearer ck_live_admin..."
```

If a key leaks, revoke it here — there is no other way to invalidate a key
short of operator DB access.
