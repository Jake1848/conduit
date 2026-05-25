# Conduit Core

The FastAPI service that sits in front of LND and serves the Conduit API.

## Local run (mock LND)

```bash
cd core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn conduit_core.main:app --reload
# → http://127.0.0.1:8000/docs
```

The default `.env` runs with `LND_MOCK=true` and a bootstrap admin key
(`ck_test_dev_root`). Real LND is only required when `LND_MOCK=false`.

```bash
curl -s http://127.0.0.1:8000/v1/health
curl -s -H 'Authorization: Bearer ck_test_dev_root' http://127.0.0.1:8000/v1/status
```

## Tests

```bash
pytest -v
```

## Layout

```
conduit_core/
├── main.py              FastAPI app
├── config.py            Settings (env-driven, pydantic-settings)
├── auth.py              API key auth (bcrypt, scoped)
├── errors.py            ConduitError hierarchy → HTTP responses
├── schemas.py           Pydantic request/response models
├── db/
│   ├── database.py      Async SQLAlchemy engine + session
│   └── models.py        agents, policies, transactions, api_keys, webhooks
├── routes/
│   ├── agents.py        /v1/agents
│   ├── policies.py      /v1/agents/{id}/policy
│   ├── payments.py      /v1/payments
│   ├── invoices.py      /v1/invoices
│   ├── transactions.py  /v1/agents/{id}/transactions and /v1/transactions/{id}
│   ├── webhooks.py      /v1/webhooks
│   ├── keys.py          /v1/api-keys
│   └── system.py        /v1/health, /v1/status
└── services/
    ├── lnd.py           MockLNDClient + LNDRestClient
    ├── policy_engine.py Spending policy enforcement (fail-closed)
    ├── wallet.py        Lightning Address resolution
    ├── webhook_sender.py HMAC-signed delivery with retries
    └── ids.py           Prefixed ID generation
```
