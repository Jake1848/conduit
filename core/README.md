# Conduit Core

The FastAPI service that sits in front of LND and serves the Conduit API.

## Local run (mock LND, SQLite)

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
# /v1/status exposes node liquidity, so it requires an ADMIN-scope key.
curl -s -H 'Authorization: Bearer ck_test_dev_root' http://127.0.0.1:8000/v1/status
```

## Tests

```bash
pytest -v
```

> **The default suite runs on SQLite, which has no row locking.** The authoritative
> money-path concurrency invariants (lost-update ledger drift, the overspend race,
> and the treasury withdraw-vs-credit solvency TOCTOU) are **skipped** on SQLite and
> only run against Postgres — the only supported production DB. Run the full money
> suite before shipping:
>
> ```bash
> DATABASE_URL=postgresql+asyncpg://conduit:PW@localhost:5432/conduit pytest -v \
>   tests/test_concurrency_ledger.py tests/test_treasury.py
> ```
>
> CI's `core-postgres` job runs these on every push.

## Production deployment

Production has a few hard requirements enforced at startup. If you forget
any of them, the app will refuse to boot:

1. `CONDUIT_ENV=production`
2. `API_SECRET_KEY` set to a non-default 64+ char value
   (used as the HMAC key for `X-Conduit-Server-Signature` on webhook deliveries)
3. `BOOTSTRAP_API_KEY` set to a non-default value with the correct prefix
   (`ck_live_…` on mainnet, `ck_test_…` elsewhere)
4. `DATABASE_URL` pointing at Postgres
   (SQLite is rejected — no concurrent writes, no row locks)

```bash
export CONDUIT_ENV=production
export CONDUIT_NETWORK=mainnet
export DATABASE_URL=postgresql+asyncpg://conduit:STRONG_PW@db.internal:5432/conduit
export API_SECRET_KEY=$(openssl rand -hex 32)
export BOOTSTRAP_API_KEY=ck_live_$(openssl rand -hex 20)
export ALLOWED_ORIGINS=https://app.conduit.energy
export LND_MOCK=false
export LND_REST_URL=https://lnd.internal:8080
export LND_MACAROON_PATH=/run/secrets/lnd.macaroon
export LND_TLS_CERT_PATH=/run/secrets/lnd.tls.cert
```

Save the `BOOTSTRAP_API_KEY` value — it's used to bootstrap the first admin
key and **cannot be recovered** later.

### Migrations

The schema is managed by Alembic. In production we do NOT auto-create tables.
Run migrations as part of your deploy step:

```bash
alembic upgrade head
```

To generate a new migration:

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### Postgres considerations

- Use the `postgresql+asyncpg://` URL scheme.
- `SELECT ... FOR UPDATE` row locking is real on Postgres; on SQLite it's a
  no-op SQL clause but `BEGIN IMMEDIATE` serializes writes globally so the
  payment path remains race-free.
- All `JSON`-shaped columns are stored as `TEXT` containing serialized JSON.
  This works identically on both engines and avoids dialect-specific JSON
  index requirements.

### Worker count

The in-process rate limiter and the in-memory ledger lock state are
per-worker. For a single Hetzner box with one uvicorn worker (which is the
recommended layout) this is fine. If you scale out:

- Front the API with nginx `limit_req` for cross-worker rate limiting.
- The DB row lock on Postgres still enforces per-agent payment serialization
  across workers, so financial correctness holds. Only the HTTP rate
  limiter is per-worker.

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
