# Production deployment

Conduit is self-hosted: in production you run it against **your own** LND node,
with **your own** keys. The dev path (`docker compose up` with SQLite + mock
LND) is for local work only. Production has a few hard requirements enforced at
startup — if any is missing, the app refuses to boot rather than running
insecurely.

!!! warning "Network status"
    Conduit runs **live on testnet** (testnet/regtest is what's been exercised).
    `CONDUIT_NETWORK=mainnet` is a supported setting and the software is built
    for it, but a mainnet deployment has **not yet been run in production** and
    there is no external security audit yet. Bring it up on testnet first and
    treat your first mainnet run as new territory.

## Required env vars

| var | purpose |
| --- | ------- |
| `CONDUIT_ENV=production` | turns on the strict startup validator |
| `CONDUIT_NETWORK=mainnet` | also `testnet`, `signet`, `regtest` |
| `DATABASE_URL=postgresql+asyncpg://…` | SQLite is rejected in production |
| `API_SECRET_KEY` | 64+ random hex chars (`openssl rand -hex 32`); used as the HMAC pepper for `X-Conduit-Server-Signature` |
| `BOOTSTRAP_API_KEY` | **your master key** — the first admin key for your own instance; **shown once** at boot, must match the network prefix (`ck_live_…` on mainnet). Guard it like the LND macaroon. |
| `ALLOWED_ORIGINS` | comma-separated CORS allowlist; empty means no cross-origin |
| `LND_MOCK=false` | required to reach **your** real LND |
| `LND_REST_URL`, `LND_MACAROON_PATH`, `LND_TLS_CERT_PATH` | reach **your own** LND |

Optional rate-limit tuning: `RATE_LIMIT_PER_MINUTE` (default 300),
`RATE_LIMIT_BURST` (default 60).

## Platform fee (your revenue)

Conduit's built-in monetization is a per-transaction **platform fee in sats**
that **you**, the operator, configure. It is added on top of each payment, kept
when the payment settles, and refunded in full if the payment fails — it is your
revenue, not a Conduit cut.

| var | default | meaning |
| --- | ------- | ------- |
| `PLATFORM_FEE_PERCENT`  | `0.5`  | fee as a percent of the payment amount (0.5 = 0.5%); set `0` to disable |
| `PLATFORM_FEE_MIN_SATS` | `1`    | floor for the per-transaction fee |
| `PLATFORM_FEE_MAX_SATS` | `1000` | ceiling for the per-transaction fee |

Collected fees are reported at `GET /v1/fees` (admin) and surfaced in
`GET /v1/metrics`. See the [Platform fees API](api/fees.md).

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

There is no Conduit SaaS holding your funds — these steps keep the node and keys
**you** own under your control.

- [ ] **Your** LND seed phrase stored on paper, off the VPS
- [ ] LND gRPC (`10009`) and REST (`8080`) **never** exposed by UFW
- [ ] `secrets/admin.macaroon` is mode 600 and owned by the deploy user
- [ ] `API_SECRET_KEY` and `BOOTSTRAP_API_KEY` (your master key) are unique to this deployment
- [ ] `ALLOWED_ORIGINS` lists only your own domains (or is empty)
- [ ] HTTPS-only — certbot renewal cron is in place
- [ ] Postgres password is in `.env.prod` only, not in compose YAML or git
- [ ] `fail2ban` watching `sshd` and `nginx` access logs
- [ ] Channel SCB backups replicated off-box (`infra/scripts/backup_channels.sh`)
