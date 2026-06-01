# Changelog

## 0.6.0 — Dashboard support + audit fixes

- **`GET /v1/metrics`** — server-aggregated fleet metrics in one call: treasury,
  active/total agents, tx/min, avg/p99 settlement, a 24h hourly series
  (count + volume), and the 20 most active agents today. See
  [Metrics API](../api/metrics.md).
- **`GET /v1/transactions/recent?limit=N`** — the N most recent transactions
  across the whole fleet (one query), powering the dashboard live feed + audit
  log without polling every agent.
- **`balance_sats` on the agent list/get response** — the denormalized spendable
  balance is now returned inline on every agent object, so a dashboard can sum a
  fleet treasury without an `/balance` call per agent. Together these turn the
  Conduit Console Overview from ~900 requests per load into ~3.
- **Rate-limit (429) envelope** now nests under `detail` like every other error
  (`{"detail":{"code":"RATE_LIMITED",…}}`) so SDKs raise the typed `RateLimited`.
- **Zero-amount BOLT11 sends** now forward the resolved amount to LND
  (previously the amount was dropped and the payment failed on real LND).
- **Reconciler/route double-settle guard** — terminal transitions re-check the
  transaction status under the agent lock, so an overlapping reconciler sweep and
  payment-route finish can never double-apply a balance change.
- **Auth lookup is O(1)** — API keys now store a 16-char prefix discriminator, so
  authentication bcrypt-verifies one candidate instead of every active key.

## 0.5.0 — CI + SDK hardening

- **Automatic retries** in both SDKs — 429 / 5xx / network errors, with
  exponential backoff (1s, 2s, 4s), `Retry-After` honored and capped at
  60s, and no retries on other 4xx. Configurable `max_retries` /
  `maxRetries` (default 3).
- **Idempotency keys** in both SDKs — payment methods auto-generate a
  UUID4 `Idempotency-Key`, reused across the SDK's own retries so a
  retried payment can never settle twice. Override via `idempotency_key`
  / `idempotencyKey`.
- **Webhook verifiers** — `verify_webhook` / `parse_webhook` (Python) and
  `verifyWebhook` / `parseWebhook` (TypeScript), constant-time HMAC over
  the raw body, with a typed `WebhookVerificationError`.
- **`set_default_client`** added to the Python SDK for parity with the JS
  `setDefaultClient`; `PermissionDenied` is now exported from the Python
  package.
- **CI** (`.github/workflows/ci.yml`) — GitHub Actions runs three parallel
  jobs on every push and PR: **core** (ruff + pytest + `alembic check` on
  Python 3.12 and 3.13), **sdk-python** (ruff + pytest on 3.12 and 3.13),
  and **sdk-js** (`tsc` build + `node --test` on Node 20 and 22).

## 0.4.0 — financial correctness

- **BOLT11 / Lightning-address amount validation** — a payment's `sats`
  must match the invoice amount; a malicious LNURL-pay server or a
  mismatched BOLT11 can no longer cause an over-payment.
- **LND unknown-state handling** — if the call to LND ends ambiguously
  (timeout, 5xx, parse error), the payment is **not** refunded (it may
  have settled); the row is marked for reconciliation instead.
- **Payment reconciler** — a background sweep (every 60s, for pending
  sends older than 90s) calls LND `lookuppayment` and settles or refunds,
  so money is never permanently stranded by an ambiguous failure.
- **Server-side idempotency keys** — `Idempotency-Key` on the payment
  endpoints; same key + same body replays the cached response, same key +
  different body returns `409`.
- **API key revocation** — `GET /v1/api-keys` and
  `DELETE /v1/api-keys/{id}` (admin); revoked keys return `401`.
- **Fire-and-forget webhooks** — deliveries are scheduled in the
  background, so a slow or failing webhook receiver can no longer turn a
  successful payment into an error or trigger a double-charge on retry.
- **REST LND streaming** — router payments are streamed with a read
  timeout above LND's own payment timeout, so a slow payment no longer
  surfaces as a spurious error.

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
