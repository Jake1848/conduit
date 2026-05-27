# Changelog

## 0.3.0 — invoice watcher + production stack

- **Invoice settlement watcher** — background task subscribes to LND's
  invoice stream; on SETTLED, credits the agent's `balance_sats`
  atomically (agent row locked) and fires `invoice.settled`. On
  CANCELED, fires `invoice.expired`. Reconnects with exponential backoff
  (1s → 60s).
- **`/v1/agents/{id}/balance`** now reports `pending_sats` from
  in-flight outbound HTLCs and `total_sats = available + pending`.
- **Production docker-compose stack** — Postgres 16, alembic migrations
  on every boot, nginx TLS termination with cross-worker `limit_req`
  floor, host-side LND via `host.docker.internal`.
- **`core/entrypoint.sh`** — runs `alembic upgrade head` then `exec`s
  uvicorn. Used by the prod compose file.
- New docs page: [Production deployment](../production.md).
- New webhook events: `invoice.settled`, `invoice.expired`.

## 0.2.0 — production hardening

- CORS lockdown via `ALLOWED_ORIGINS`; empty by default.
- HTTP-layer token-bucket rate limiter (per API key or per IP); returns
  429 with `Retry-After`.
- Production startup validator: refuses to boot on dev-default
  `API_SECRET_KEY` / `BOOTSTRAP_API_KEY`, on SQLite, or on a network
  prefix mismatch.
- `API_SECRET_KEY` is now the HMAC pepper for
  `X-Conduit-Server-Signature` on every webhook delivery.
- Per-agent ledger: `Agent.balance_sats` column maintained
  transactionally; `/v1/agents/{id}/credit` and `/debit` admin endpoints.
- Payment path: `SELECT ... FOR UPDATE` on the agent row; on LND failure
  the full sats + fee budget is refunded; on success the unused fee
  budget is refunded.
- Alembic migrations in `core/alembic/`; `init_db()` is a no-op in
  production.
- Global JSON 500 exception handler; LND connectivity ping in lifespan
  when `LND_MOCK=false`.

## 0.1.0 — initial scaffold

- Core API (FastAPI) with agents, policies, payments, invoices,
  transactions, webhooks
- Mock LND for local development; REST client for production
- Policy engine with fail-closed evaluation
- Python SDK (`conduit-sdk`)
- TypeScript SDK (`@conduit/sdk`)
- MCP server (`conduit-mcp`)
- Hetzner install scripts, systemd units, nginx config
- MkDocs docs site
