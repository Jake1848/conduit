# Changelog

All notable changes to Conduit are documented here. Conduit is a self-hosted,
non-custodial Bitcoin/Lightning payment SDK: the operator runs it on their own
infrastructure, in front of their own LND node, paying out their own funds.
See `SECURITY.md` for the threat model and reporting.

## [0.8.4] — Full audit pass, real console pages, agent demo

A comprehensive audit/red-team pass over the whole codebase (money path hardest),
the five placeholder console pages built for real, and a polished
agent-pays-over-Lightning demo. No schema changes; api-container-only deploy.

### Security / correctness
- **Treasury double-spend closed.** A prior "retryable failed send" path reset an
  ambiguous withdrawal back to `pending`, so a same-key retry after a timeout
  could broadcast a second on-chain transaction. An ambiguous `send_coins` now
  resolves to `unknown` and a retry with the same idempotency key 409s — the
  irreversible broadcast is never re-attempted. Regression test added.
- **Refunds only on explicit failure.** A payment is refunded (Phase 3a) only when
  LND reports an explicit `FAILED`; a non-terminal/`UNKNOWN` lookup now raises a
  generic `LNDError` instead of being mis-classified as failed, so an in-flight or
  unknown payment is never double-spent by a premature refund.
- **Treasury liabilities are conservative everywhere.** `pending_outbound` is now
  included in the liability figure used by the overview, the withdrawable-headroom
  calc, and the withdrawal solvency guard (previously only some paths).
- **`/v1/metrics` no longer leaks liquidity to read keys.** Treasury balance,
  fee revenue, assets/liabilities and the solvency ratio are zeroed/nulled for
  non-admin scopes; full figures require `admin`.
- **LND errors no longer leak internals.** Upstream LND failures log a warning and
  surface a single generic "node is unavailable" message instead of echoing the
  raw error to the caller.
- **Input hardening, round two.** Deeply-nested JSON returns `422` (not a `500`);
  webhook URL + payload-field lengths are bounded; the SSRF guard additionally
  rejects multicast / reserved / unspecified destination IPs.
- **SDK replay-safety.** `sdk-js` retries network errors only for replay-safe
  requests (GET/DELETE or an explicit idempotency key); both SDKs' `Agent.list()`
  now page the entire fleet instead of the first page.
- **Ops.** Postgres backups verify their gzip integrity and set S3 SSE; the
  idempotency pruner never deletes an in-flight (`pending`) record; the reconciler
  is idempotent (no double refund on a second pass).

### Console
- The five remaining placeholder pages are now real, admin-gated, and match the
  existing design system: **Policies** (per-agent limit/allowlist/memo editor),
  **Webhooks** (CRUD with one-time signing-secret reveal), **Network** (live node
  health, liquidity breakdown, solvency), **Sandbox** (read-only GET API explorer
  with an equivalent `curl`), and **Docs** (in-app links to the repo/SDKs/demo).
- The console disconnects cleanly on `401/403` and surfaces API errors as a toast.

### Docs / demo
- **`DEMO.md`**: an AI agent that autonomously pays over Lightning and is stopped
  by its own server-side policy — via MCP + Claude Desktop, or a raw-SDK fallback.
- `sdk-python/examples/ai_agent_pays_api.py` rewritten as a self-contained,
  runnable lifecycle; `mcp-server/scripts/smoke_test.py` drives all eight MCP
  tools through the real stdio protocol and asserts policy enforcement.

## [0.8.3] — Treasury (owner withdrawals), operator-wide idempotency, input hardening

Owner/admin treasury feature plus a red-team-driven hardening pass. The new
withdrawal path moves real on-chain funds, so it was adversarially reviewed and
the confirmed findings fixed before release.

### Added
- **Treasury (owner/admin).** `GET /v1/treasury/overview` (accrued platform-fee
  revenue + node liquidity + solvency ratio + withdrawable headroom + recent
  withdrawals) and `POST /v1/treasury/withdraw` to move accrued on-chain funds to
  an operator address. Admin scope only. A new owner page in the console shows
  revenue, liquidity/solvency, a withdraw form (with live headroom + confirm),
  revenue-by-day, and the Bitcoin-transfer history.
- **On-chain `send_coins`** on the LND client (protocol/mock/REST → LND
  `SendCoins`), and a durable `treasury_withdrawals` table (migration `0008`):
  each withdrawal is recorded `pending` before the irreversible broadcast and
  `broadcast`/`failed` after, so a crash mid-broadcast leaves a reconcilable
  record. Doubles as the operator's BTC-transfer history.
- **`has_more`** on `GET /v1/agents` so clients can page the whole fleet.

### Security / correctness
- **Solvency guard on withdrawals is race-safe.** The withdraw holds a
  transaction-scoped advisory ledger lock (`pg_advisory_xact_lock`) across the
  solvency read AND the on-chain broadcast; the operator-credit path takes the
  same lock. So neither a concurrent withdrawal nor a concurrent credit can raise
  liabilities inside the read→send window and breach solvency (a TOCTOU the
  red-team found). The fee reserve scales with the requested fee rate (was a flat
  1000 sats). An empty/missing `txid` from LND is now a hard error, never a
  cached "successful" withdrawal.
- **Idempotency keys are now operator-wide** (unique on `key` alone, was
  `(api_key_id, key)`; migration `0007`). A retried request that goes out under a
  different API key (rotation, a second worker) now dedupes instead of
  double-charging. A key reused with a different body still 409s.
- **Input hardening** (earlier red-team 500s → clean 422s): `MAX_SATS` upper
  bound on every sats/amount field, null-byte rejection (`SafeStr`) on names /
  reasons / memos / API-key labels, and a per-agent balance ceiling on credit.
- **Webhook URLs are validated at creation** (https-only, reject literal
  internal/metadata IPs) without a DNS lookup, so a transient resolver failure
  can't block a valid endpoint; delivery still does the authoritative,
  DNS-rebind-safe resolve+pin.
- **`/v1/status` requires admin scope** (it exposes node liquidity), and
  `GET /v1/agents` is paginated (`limit`/`offset`, default 50, max 500) instead
  of streaming the whole table.

## [0.8.2] — Concurrency ledger fix

### Fixed
- **Lost-update race on `balance_sats` under concurrent payments to the same
  agent.** The settle (Phase 3b) and failure-refund (Phase 3a) paths re-`SELECT
  ... FOR UPDATE`-ed the agent but, because the session is `expire_on_commit=False`,
  got the stale identity-map object holding the pre-concurrency balance and wrote
  it back — clobbering other in-flight payments' updates, so the denormalized
  balance drifted (in either direction) from the transaction ledger. Adds
  `populate_existing=True` to both locked re-selects so the current row value is
  read under the lock. Found by the Phase-4 real-LND stress test (distinct
  concurrent payments to one agent); earlier concurrency tests missed it because
  they reused one idempotency key, so only a single payment executed. Postgres
  only (the lock is a no-op on SQLite, which is unsupported in production); covered
  by a new `core-postgres` regression test (`test_concurrency_ledger.py`).

## [0.8.1] — Security hardening

Security and reliability patch on top of 0.8.0. No API or schema breaking changes.

### Security
- **nginx: block `/metrics` at the public edge.** The Prometheus exposition
  endpoint is unauthenticated by design (an internal ops scrape) and reveals
  node liquidity + ledger liabilities. Both `infra/nginx/conduit.prod.conf` and
  `conduit.conf` now return 404 for `/metrics` so it is never reachable from the
  internet; scrape it on the internal network (`http://api:8000/metrics`) or via
  an SSH tunnel. Without this, deploying the observability endpoint would have
  exposed treasury/liquidity figures publicly.
- **SSRF: IP-pinned, DNS-rebind-safe outbound HTTP** for LNURL-pay and webhook
  delivery (`services/safe_http.py`). Resolution + validation + connect happen in
  one pinned transport (no TOCTOU window), redirects are disabled, and the IP
  classifier is an **allowlist** (`is_global` only) — closing the CGNAT/RFC6598
  `100.64.0.0/10` gap a denylist leaves open. IPv4-mapped IPv6 is unwrapped
  before classification.

### Added
- **Solvency monitor** (`services/solvency.py`): periodically reconciles Σ agent
  balances (liabilities) against the node's channel-local + on-chain liquidity
  (assets), surfaces the ratio on `/v1/metrics` and `/v1/health/ready`, and logs a
  structured snapshot. Opt-in fail-closed enforcement (`SOLVENCY_ENFORCE=true`)
  pauses credits when the ledger is unbacked. Off by default (observe-and-warn).
- **Observability** (`observability.py`): Prometheus exporter (`/metrics`, root,
  internal) with request counters/latency, LND/liquidity/solvency gauges, and a
  worker-liveness gauge; optional Sentry init only when `SENTRY_DSN` is set.
- **DB invariant**: `CHECK (balance_sats >= 0)` on `agents` (alembic `0006`) — a
  last-line guard so the ledger can never be driven negative even by a direct
  write or a missed application check.
- Ops/DR: codified deploy/rollback script (`infra/scripts/deploy.sh`) with image
  snapshot, migrate-on-boot, `/v1/health/ready` health-gate and auto-rollback;
  backup timer + dead-man's switch.

### Fixed
- Solvency liabilities no longer double-count pending outbound sats (they are
  already debited from `balance_sats` up-front), so the ratio is correct under
  load.

## [0.8.0] — Self-hosted SDK + platform-fee model

- Per-transaction **platform fee** engine (operator revenue): charged on top of a
  payment, kept on settle, refunded with the rest on failure (`services/fees.py`,
  alembic `0005`, `GET /v1/fees`). `PLATFORM_FEE_PERCENT=0` disables it.
- Self-hosted packaging (docker-compose), SDK publishing prep, dashboard API-URL
  field, marketing copy corrected for accuracy (self-hosted/testnet; dropped
  non-custodial/mainnet/"100% production-ready" claims), `SECURITY.md`, gitleaks
  secret-scanning CI, `.gitignore` hardening.

## [0.7.0] — Hardening

- Idempotency reservation that closes the concurrent double-spend window: a
  pending sentinel row under the `(api_key_id, key)` unique constraint blocks a
  second in-flight request (returns 409) instead of firing a duplicate payment.
- Atomic debit-before-pending money path under a row lock; reconciler and
  idempotency-record pruner background workers.

[0.8.1]: https://github.com/Jake1848/conduit/releases/tag/v0.8.1
[0.8.0]: https://github.com/Jake1848/conduit/releases/tag/v0.8.0
[0.7.0]: https://github.com/Jake1848/conduit/releases/tag/v0.7.0
