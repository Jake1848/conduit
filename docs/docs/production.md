# Production deployment

The dev path (`docker compose up` with SQLite + mock LND) is for local work
only. Production has a few hard requirements enforced at startup — if any
is missing, the app refuses to boot rather than running insecurely.

## Required env vars

| var | purpose |
| --- | ------- |
| `CONDUIT_ENV=production` | turns on the strict startup validator |
| `CONDUIT_NETWORK=mainnet` | also `testnet`, `signet`, `regtest` |
| `DATABASE_URL=postgresql+asyncpg://…` | SQLite is rejected in production |
| `API_SECRET_KEY` | 64+ random hex chars (`openssl rand -hex 32`); used as the HMAC pepper for `X-Conduit-Server-Signature` |
| `BOOTSTRAP_API_KEY` | the first admin key; **shown once** at boot, must match the network prefix (`ck_live_…` on mainnet) |
| `ALLOWED_ORIGINS` | comma-separated CORS allowlist; empty means no cross-origin |
| `LND_MOCK=false` | required for real Lightning |
| `LND_REST_URL`, `LND_MACAROON_PATH`, `LND_TLS_CERT_PATH` | reach a real LND |

Optional rate-limit tuning: `RATE_LIMIT_PER_MINUTE` (default 300),
`RATE_LIMIT_BURST` (default 60).

## Migrations

The schema is managed by Alembic. The production container runs
`alembic upgrade head` automatically before starting uvicorn (see
`core/entrypoint.sh`), so on every deploy the schema is brought current.

For a manual run:

```bash
cd core
DATABASE_URL=postgresql+asyncpg://… alembic upgrade head
```

To generate a new migration after a model change:

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

`init_db()` is intentionally a no-op in production — `create_all` would
diverge from migration history.

## Provided stack (docker-compose.prod.yml)

The repo includes a production compose file with:

- **postgres** — 16-alpine, named volume, healthcheck, no published port
- **api** — built from `core/`, mounts `./secrets/admin.macaroon` and
  `./secrets/tls.cert` read-only, reaches the host's LND via
  `host.docker.internal`, runs migrations on boot
- **nginx** — terminates TLS, proxies to the api service, applies a
  cross-worker `limit_req` floor, serves the certbot ACME challenge path

LND is **not** in the compose stack — it runs separately on the host (or in
a different compose project) so its lifecycle is independent of the API.

```bash
cp .env.prod.example .env.prod
# fill in real values
mkdir -p secrets/
cp /home/conduit/.lnd/data/chain/bitcoin/mainnet/admin.macaroon secrets/
cp /home/conduit/.lnd/tls.cert secrets/
chmod 600 secrets/*

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

## Invoice settlement watcher

When `LND_MOCK=false`, the API starts a background task
(`InvoiceWatcher`) that subscribes to LND's invoice stream. On any settled
invoice, it finds the matching pending Transaction by `payment_hash`,
credits the agent's `balance_sats` atomically, and fires an
`invoice.settled` webhook. On canceled / expired invoices it fires
`invoice.expired` and marks the transaction failed (no balance change).

Disconnects are handled with exponential backoff (1s → 60s cap), and
per-invoice errors are logged but never crash the loop.

## Security checklist

- [ ] LND seed phrase stored on paper, off the VPS
- [ ] LND gRPC (`10009`) and REST (`8080`) **never** exposed by UFW
- [ ] `secrets/admin.macaroon` is mode 600 and owned by the deploy user
- [ ] `API_SECRET_KEY` and `BOOTSTRAP_API_KEY` are unique to this deployment
- [ ] `ALLOWED_ORIGINS` lists only your own domains (or is empty)
- [ ] HTTPS-only — certbot renewal cron is in place
- [ ] Postgres password is in `.env.prod` only, not in compose YAML or git
- [ ] `fail2ban` watching `sshd` and `nginx` access logs
- [ ] Channel SCB backups replicated off-box (`infra/scripts/backup_channels.sh`)
