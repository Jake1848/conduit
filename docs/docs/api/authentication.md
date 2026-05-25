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
