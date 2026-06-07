# Changelog

All notable changes to Conduit are documented here. Conduit is a self-hosted,
non-custodial Bitcoin/Lightning payment SDK: the operator runs it on their own
infrastructure, in front of their own LND node, paying out their own funds.
See `SECURITY.md` for the threat model and reporting.

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
