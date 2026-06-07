# Mainnet Readiness Runbook

A staged, executable go-live checklist for taking Conduit from **testnet** to
**mainnet** without losing real sats. Conduit is self-hosted Bitcoin/Lightning
payment infrastructure: a FastAPI app (`core/`) sits in front of **one** LND node
and maintains a virtual, integer-sats ledger of per-agent balances. It is
**custodial at the agent layer** — agent `balance_sats` are claims against the
operator's single node's liquidity. On mainnet, a bug, a key leak, or an
insolvency event is real, irreversible money. Treat every box below as load-bearing.

> **Status today (v0.8.1):** live on **testnet + regtest only**. No external
> security audit. No legal opinion. No mainnet run. No Postgres replica. Wallet
> unlock is a plaintext password file. **Conduit is NOT mainnet-ready as shipped.**
> This document is the gap list and the order to close it in. Sections flagged
> **NOT READY TODAY** require new work before any mainnet sats move.

## How to use this document

- Work the sections **top to bottom**. Section 1 (prerequisites) gates everything;
  do not provision a mainnet wallet until it is green.
- Every checklist item is either **operator action** (you execute it) or a
  **Conduit gap** (the software does not do this yet — build/buy/document it first).
- The final **Go / No-Go gate** (Section 8) is a single page you sign off on. If
  any line there is unchecked, you do not go live.

Cross-references:

- Operator runbook & security checklist: [`infra/README.md`](../infra/README.md)
- Production env + startup validator: [`docs/docs/production.md`](docs/production.md)
- Security policy / threat model: [`SECURITY.md`](../SECURITY.md)
- Deploy/rollback automation: [`infra/scripts/deploy.sh`](../infra/scripts/deploy.sh)
- Solvency monitor: [`core/conduit_core/services/solvency.py`](../core/conduit_core/services/solvency.py)
- Reconciler: [`core/conduit_core/services/reconciler.py`](../core/conduit_core/services/reconciler.py)
- Fee engine: [`core/conduit_core/services/fees.py`](../core/conduit_core/services/fees.py)

---

## 1. Hard prerequisites — BEFORE any mainnet sats

These are blocking. None of the application controls below matter if the code has
an unaudited custody bug or the operator is running an unlicensed money-transmission
business. **All four must be DONE, with artifacts, before a mainnet wallet is even
created.**

| # | Prerequisite | What "done" means | Status today |
|---|---|---|---|
| 1.1 | **External security audit completed** | An independent firm has reviewed `core/` — the money path (`routes/payments.py`), auth/scope model (`auth.py`), idempotency/double-spend (`services/idempotency.py`), SSRF (`services/safe_http.py`), solvency (`services/solvency.py`), reconciler — and issued a written report. | **NOT READY** — `SECURITY.md` states no audit has been done. Self red-team (42/42) is not a substitute. |
| 1.2 | **All audit findings remediated or risk-accepted in writing** | Every High/Critical finding is fixed and re-tested; each accepted Medium/Low has a documented, signed rationale. | **NOT READY** — depends on 1.1. |
| 1.3 | **Written legal / money-transmission opinion** | Counsel has confirmed, in writing, the custody posture (Conduit is **custodial at the agent layer**: operator holds the real sats, agent balances are operator-controlled IOUs the operator can credit/debit/sweep) and whether the operator's specific deployment + jurisdiction triggers money-transmitter / MSB / VASP registration, KYC/AML, or BSA obligations. | **NOT READY** — no legal opinion exists. The README/SECURITY framing is engineering language, **not** a legal conclusion. |
| 1.4 | **Incident-response runbook written and rehearsed** | A documented IR plan: who is paged, severity tiers, the kill switch (set every agent's policy `enabled=false` or revoke the bootstrap key), how to force-close channels, contact for LND/host provider, comms plan. Rehearsed at least once on testnet. | **NOT READY** — no IR runbook in repo. |
| 1.5 | **Restore-from-backup drill PASSED** | A Postgres dump restored into a throwaway DB **and** an SCB (static channel backup) recovery dry-run, both verified, both timed, within the last 30 days. | **NOT READY** — backup scripts exist (`backup_postgres.sh`, `backup_channels.sh`) but no evidence of a passing restore drill. `infra/README.md` only *recommends* periodic restore tests. |
| 1.6 | **Threat model reviewed against single-operator limitation** | Confirm you are the **only** trusted party. Conduit's authorization is **scope-based, not per-agent** (`read` < `write` < `admin`); a `write` key can act on **any** agent. Hand keys only to agents you run. If you need tenant isolation, run a separate Conduit instance + node per tenant. | Operator decision — documented in `README.md` ("Authorization model"). Confirm it fits your use case. |

**Gate 1 exit criteria:** 1.1–1.5 all `DONE` with artifacts on file. Do not proceed.

---

## 2. Node & custody (mainnet LND)

The reference testnet deploy runs LND with **neutrino** (light client). **Neutrino
is not acceptable for a custodial mainnet node** — you must run a full
`bitcoind` backend so the node validates the chain itself.

### 2.1 Sizing — full bitcoind backend + mainnet LND

The shipped `infra/bitcoind/bitcoin.conf.example` is a **pruned** node
(`prune=50000`, ~50 GB, `txindex=0`, `dbcache=2048`). Pruned is acceptable for an
LND backend (LND only needs ZMQ block/tx streams + RPC). Size the box accordingly:

| Resource | Minimum (pruned bitcoind + 1 LND) | Comfortable | Notes |
|---|---|---|---|
| CPU | 2 vCPU | 4 vCPU | Initial Block Download (IBD) is CPU/IO bound for 1–3 days. |
| RAM | 4 GB | 8 GB+ | `dbcache=2048` already reserves ~2 GB for bitcoind; leave headroom for LND + Postgres + API. |
| Disk | ~80 GB SSD (pruned ~50 GB + LND channel.db growth + Postgres) | 150–250 GB NVMe | LND `channel.db`/`bbolt` grows; do **not** run out of disk — a full disk corrupts the channel DB. |
| Network | unmetered or generous cap | — | P2P + gossip is chatty; IBD pulls the full chain once. |

- [ ] Provision a box that meets at least the **Comfortable** column. The current
      reference box (Hetzner, single VPS) co-locates bitcoind + LND + Postgres + API.
      For mainnet at non-trivial value, consider isolating Postgres/HA onto a
      separate host (see Section 3).
- [ ] Run `infra/scripts/install_bitcoind.sh`, copy `bitcoin.conf.example`, set
      `rpcpassword` (`openssl rand -hex 32`) and prune size, restart.
- [ ] Run `infra/scripts/install_lnd.sh`, copy `lnd.conf.example` (it already sets
      `bitcoin.mainnet=true`, `bitcoin.node=bitcoind`, ZMQ endpoints). **Confirm
      `bitcoin.node=bitcoind`, not `neutrino`.**
- [ ] Wait for full chain sync (1–3 days). Verify with `infra/scripts/verify_node.sh`
      and confirm `synced_to_chain=true` (the API boot probe in `main.py` logs
      `lnd_not_synced_to_chain` and `/v1/health/ready` reports it).

### 2.2 Channel liquidity & inbound capacity planning

Conduit's solvency depends on **outbound** channel liquidity: an agent's balance is
only spendable if the node can route it out. The solvency monitor computes
`assets = channel_local_sats + onchain_confirmed_sats`.

| # | Item | Status |
|---|---|---|
| 2.2.1 | Decide total mainnet float (sum of all agent balances you intend to credit). This is your **maximum liability**. | Operator |
| 2.2.2 | Open channels with **outbound** capacity ≥ your maximum liability **plus margin** (channel reserves, in-flight HTLCs, routing fees are not spendable). Use `infra/scripts/setup_channels.sh`. | Operator |
| 2.2.3 | Plan **inbound** capacity for receive flows (invoices credit agents). Without inbound, `invoice.settled` events that credit balances cannot occur. Acquire inbound via inbound-liquidity services, loop-in, or peer agreements. | Operator |
| 2.2.4 | Keep an on-chain buffer for fee bumps, channel opens, and force-close fees. | Operator |
| 2.2.5 | Set conservative `wumbo`/`maxpendingchannels` and `minchansize` (already `100000` in the example conf) per your float. | Operator |

### 2.3 Watchtower

A mainnet routing/custody node must be protected against a counterparty
broadcasting a revoked channel state while your node is offline.

- [ ] **NOT READY (operator gap):** configure an LND **watchtower client**
      (`wtclient.active=true`) pointing at a watchtower you trust (run your own
      altruist tower or use a reputable public one). The shipped `lnd.conf.example`
      does **not** enable it. Conduit docs reference watchtowers as a value-at-rest
      hardening step (`docs/docs/concepts/security.md`) but do not configure one.

### 2.4 Static channel backups (SCB) + off-box storage

Losing LND data **without** an SCB means losing the channels' funds.

| # | Item | Status |
|---|---|---|
| 2.4.1 | `infra/scripts/backup_channels.sh` exports the SCB (`lncli exportchanbackup`), `chmod 600`, keeps last 24 locally. | Provided |
| 2.4.2 | **Uncomment and configure one off-box replication target** in `backup_channels.sh` (SCP to a backup host, `aws s3 cp --sse aws:kms`, or rclone to an encrypted remote). Shipped with **all three commented out**. | **NOT DONE until you configure it** |
| 2.4.3 | Schedule it: `*/15 * * * * bash …/backup_channels.sh` (per `infra/README.md`). | Operator |
| 2.4.4 | **An SCB after every channel open/close.** SCBs are only valid for the current channel set. Re-export immediately after any channel topology change. | Operator |
| 2.4.5 | Test SCB recovery into a throwaway LND before go-live (part of drill 1.5). | Operator |

### 2.5 Wallet unlock — replace the plaintext password file

**This is the single biggest custody weakness today.** Auto-unlock writes the
wallet password to disk (`/home/conduit/.lnd/wallet_password`, `0600`). Per
`setup_wallet_unlock.sh` and `lnd.conf.example`: **root on the box = wallet access.**

| # | Item | Status |
|---|---|---|
| 2.5.1 | **NOT READY (required for mainnet):** replace `wallet-unlock-password-file` with a **KMS/HSM-backed unlock** — fetch the unlock password from a KMS/secrets manager (AWS KMS, HashiCorp Vault, GCP KMS) at boot, or use LND remote-signer / hardware-backed signing so the seed never sits decrypted on the box. | **Gap** |
| 2.5.2 | If KMS/HSM is genuinely not yet available, the *only* acceptable interim for mainnet is **manual `lncli unlock` after each (rare) reboot** — accept the unattended-restart cost. Do **not** ship the plaintext file on a high-value mainnet node. | Operator decision (documented) |
| 2.5.3 | Confirm full-disk encryption is enabled regardless. | Operator |

### 2.6 Macaroon scoping & rotation

Conduit talks to LND with a single macaroon mounted read-only into the api
container (`./secrets/admin.macaroon` → `/lnd/admin.macaroon`, see
`docker-compose.prod.yml`).

| # | Item | Status |
|---|---|---|
| 2.6.1 | **Do not mount `admin.macaroon`.** Bake a **scoped macaroon** with only the permissions Conduit's `LNDClient` uses (get_info, balances, pay invoice, lookup payment, subscribe invoices, decode). Use `lncli bakemacaroon`. The shipped prod docs/compose use `admin.macaroon` — narrow it. | **Gap (hardening)** |
| 2.6.2 | `secrets/*.macaroon` and `tls.cert` are mode `600`, owned by the deploy user (per `infra/README.md` checklist). | Provided |
| 2.6.3 | Document a macaroon **rotation** procedure (re-bake, swap file, restart api). No rotation tooling ships today. | **Gap** |

### 2.7 Firewalling LND

- [ ] Run `infra/scripts/setup_firewall.sh`. Confirm with `ufw status verbose` that
      **LND gRPC (10009/10010) and REST (8080/8081), bitcoind RPC (8332), and ZMQ
      (28332/28333) NEVER appear as ALLOW.** Only SSH, Lightning P2P (9735/9736),
      Bitcoin P2P (8333), and 80/443 (nginx) are open.
- [ ] LND REST is reached by the api container only via `host.docker.internal`
      (host gateway), never the public interface. Verify it is bound to `127.0.0.1`
      in `lnd.conf` (`restlisten=127.0.0.1:8080` — already set in the example).

---

## 3. Data durability (Postgres)

The ledger **is** the liability record. If Postgres is lost without a restorable
backup, you cannot prove what you owe each agent. Production refuses SQLite
(`config.py` `validate_for_runtime()` rejects `sqlite` when `CONDUIT_ENV=production`).

| # | Item | Status |
|---|---|---|
| 3.1 | **Postgres HA: primary + replica, or managed Postgres.** Today the prod stack runs a **single** `postgres:16-alpine` container in `docker-compose.prod.yml` with a named volume and **no replica**. For mainnet, run streaming replication (primary + hot standby) or move to managed Postgres with automated failover. | **NOT READY** — single instance only. |
| 3.2 | **PITR / WAL archiving.** Configure continuous WAL archiving so you can point-in-time-restore to just before an incident — `pg_dump` snapshots alone lose everything since the last dump. | **NOT READY** — only `pg_dump` (`backup_postgres.sh`) ships. |
| 3.3 | **Off-box backups with dead-man's switch.** `conduit-backup.timer` runs `conduit-backup.service` every 6h, which calls `backup_postgres_to_s3.sh` (local `pg_dump` + `aws s3 cp` upload) and, on a clean exit, pings a healthchecks.io-style dead-man's switch (`/start` at begin, success ping on OK, `/fail` on error) via `BACKUP_HEALTHCHECK_URL`. The ping logic lives in the **systemd unit**, not the script. Configure `/etc/conduit/backup.env` (`0600`). | Provided — **must be configured** |
| 3.4 | **Backup encryption.** The shipped `backup_postgres_to_s3.sh` runs a plain `aws s3 cp` with **no** encryption flag — dumps upload unencrypted unless you add it. Add `--sse aws:kms` (or client-side GPG before upload) and confirm the bucket is private + encrypted by default. | **NOT wired — operator must add** |
| 3.5 | **Tested restore.** A `pg_dump` restored into a throwaway DB within the last 30 days (drill 1.5). Automate a periodic restore-verify. | Operator |
| 3.6 | **Connection pool sanity.** `DB_POOL_SIZE` (5) + `DB_MAX_OVERFLOW` (10) is **per worker**. Confirm `worker_count * (size + overflow) < Postgres max_connections (100)`. The single-api-container topology runs one container; if you raise uvicorn workers, recheck this (`config.py` comment). | Operator |

---

## 4. Application controls for real money

These are Conduit-native controls. They exist in code today but several default to
**off / permissive** — flip them to conservative settings for mainnet.

### 4.1 Solvency enforcement

| # | Item | Status |
|---|---|---|
| 4.1.1 | **Set `SOLVENCY_ENFORCE=true`.** Default is `false` (observe-and-warn). When on, `enforce_solvent()` makes the **credit path fail closed (503)** when the last snapshot shows `liabilities > assets` (`services/solvency.py`). On mainnet you do **not** want to credit new IOUs you can't back. | Default OFF — **flip ON** |
| 4.1.2 | Understand the model: `liabilities = Σ Agent.balance_sats`; `assets = channel_local + onchain_confirmed`. Pending outbound is **not** added to liabilities (already debited up-front). Enforcement gates **money-IN (credit)**, not outbound sends. | Documented |
| 4.1.3 | Tune `SOLVENCY_CHECK_INTERVAL_SECONDS` (default 300). Tighter interval = fresher enforcement decision, at a small LND-balance-query cost. | Operator |

### 4.2 Per-agent & global send caps (policy engine)

Caps are enforced per agent by `services/policy_engine.py` (per-tx, per-hour,
per-day sats; per-minute count). The engine **fails closed** on any error.

| # | Item | Status |
|---|---|---|
| 4.2.1 | Attach a conservative `Policy` to **every** agent: low `max_per_transaction`, `max_per_hour`, `max_per_day`, sane `max_per_minute_count` (default 60). An agent with **no policy** falls back to *default-allow with a 60/min rate limit only* — unacceptable for mainnet. | **Operator must set per-agent policies** |
| 4.2.2 | Use `require_memo` and `allowlist`/`blocklist` destinations where the agent's spend is meant to be narrow. | Operator |
| 4.2.3 | **Global send ceiling: GAP.** There is **no instance-wide global send cap** in code — caps are per-agent. For mainnet, bound the **total** float by limiting how much you credit across all agents, and keep per-agent caps × agent count below your channel outbound. | **Gap — compensate operationally** |

### 4.3 Withdrawal velocity limits / circuit breakers

| # | Item | Status |
|---|---|---|
| 4.3.1 | Per-agent velocity is covered by hourly/daily caps + per-minute count (4.2). The HTTP layer also has an in-process token-bucket rate limiter (`RATE_LIMIT_PER_MINUTE`/`RATE_LIMIT_BURST`) and an nginx `limit_req` floor (20 r/s, burst 80). | Provided |
| 4.3.2 | **Instance-wide circuit breaker: GAP.** No automatic "halt all sends if X fails in Y minutes" exists. The available kill switch is manual: set policies `enabled=false` (master kill per agent), revoke keys, or stop the api container. Document this in the IR runbook (1.4). | **Gap — manual only** |

### 4.4 Reconciliation must be green

| # | Item | Status |
|---|---|---|
| 4.4.1 | The `PaymentReconciler` (`services/reconciler.py`) sweeps `pending` sends older than 90s, asks LND the real outcome, and settles/refunds. It runs **only with real LND** (`LND_MOCK=false`). Confirm it started (`payment_reconciler_started` log). | Provided |
| 4.4.2 | Before lifting caps (Section 6), require **zero stuck rows**: no `send`/`pending` transactions older than a few minutes, and no `needs_reconciliation` markers. Rows with no `payment_hash` are skipped by the reconciler and must be resolved **manually**. | Operator gate |
| 4.4.3 | The `InvoiceWatcher` settles inbound invoices and credits balances; confirm it is connected and not backing off repeatedly. | Operator |

### 4.5 Alerting (wire these before go-live)

| Alert | Source signal | Condition |
|---|---|---|
| Solvency ratio low | `conduit_solvency_ratio` gauge / `solvency_snapshot` log | `< 1.1` warn, `< 1.0` page (insolvent) |
| Insolvent flag | `conduit_solvent` gauge | `== 0` → page |
| Worker liveness | `conduit_worker_seconds_since_last_run{worker="solvency_monitor"}` | exceeds ~3× interval → worker stalled |
| Reconciler lag | count of `send`/`pending` rows older than N min (query DB) | non-zero and rising → page |
| Failed payments | `payment.failed` webhooks / `reconciled_failed` logs | spike vs baseline |
| LND not synced | `conduit_lnd_synced_to_chain` gauge / `lnd_not_synced_to_chain` log | `== 0` |
| Liquidity floor | `conduit_lnd_channel_local_sats` gauge | below your float threshold |
| API errors | `conduit_http_requests_total{status=~"5.."}` | error-rate threshold |
| DB down | `/v1/health/ready` → 503 | any |
| Backup missed | healthchecks.io dead-man's switch | missed ping |

> Note: only `solvency_monitor` currently feeds the worker-liveness gauge; the
> reconciler/invoice-watcher liveness must be inferred from logs + the stuck-row
> query until they are wired to gauges (**minor gap**).

---

## 5. Observability & on-call

| # | Item | Status |
|---|---|---|
| 5.1 | **Prometheus scrape — INTERNAL ONLY.** `/metrics` (root path, `observability.py`) is **unauthenticated by design** and exposes node liquidity + ledger liabilities. nginx returns **404** for `/metrics` at the public edge (`conduit.prod.conf`, v0.8.1). Scrape it on the internal network (`http://api:8000/metrics`) or via an SSH tunnel — **never** open it publicly. | Provided |
| 5.2 | Stand up Prometheus + Grafana (or hosted equivalent) reachable only on the private network. Build dashboards for the gauges in 4.5 (solvency ratio, assets/liabilities, channel-local sats, request latency histogram `conduit_http_request_duration_seconds`, worker liveness). | Operator |
| 5.3 | Ship structured logs (`structlog` JSON) to a log store; index the money-path events: `solvency_snapshot`, `solvency_enforced_reject`, `reconciled_settled`/`reconciled_failed`, `policy_evaluation_error`, `unhandled_exception`, `lnd_unreachable`. | Operator |
| 5.4 | **Sentry (optional):** set `SENTRY_DSN` to capture unhandled exceptions (errors-only, no perf sampling by default — `init_sentry`). No DSN = complete no-op. | Operator |
| 5.5 | Define **SLOs**: e.g. API availability, payment settlement p99 (`p99_settlement_ms` on `/v1/metrics`), solvency-ratio floor. Alert on SLO burn. | Operator |
| 5.6 | **On-call / paging:** name the human(s) paged for each Section 4.5 alert, the escalation path, and response-time targets. Tie into the IR runbook (1.4). | Operator |

---

## 6. Staged rollout

Roll out in checkpointed stages. Do not skip a stage. The single-api-container
topology + `deploy.sh` rollback convention make each stage reversible.

| Stage | Network | Caps | Exit criteria to advance |
|---|---|---|---|
| **S0 — Testnet baseline** | testnet | normal | Already live. All Section 1 prerequisites DONE. `SOLVENCY_ENFORCE=true` exercised on testnet. Restore drill passed. |
| **S1 — Mainnet canary (dust)** | mainnet | Per-agent caps at **dust level** (e.g. `max_per_transaction` a few hundred sats); **global float a low ceiling** (e.g. tens of thousands of sats total across all agents). 1–2 internal agents only. | 24–72h with: solvency ratio stable ≥ 1.0, reconciler green (zero stuck rows), no `unhandled_exception`, real settle + real refund both observed end-to-end. |
| **S2 — Limited mainnet** | mainnet | Raise per-agent and float ceilings ~10×. Add a handful of real agents. | 1–2 weeks clean: alerts quiet, settlement p99 within SLO, channel liquidity holding, no manual reconciliation needed. |
| **S3 — General mainnet** | mainnet | Lift to target caps, still bounded by channel outbound and your risk appetite. | Sustained clean operation; backups + restore re-verified; on-call rota staffed. |

**Cross-cutting rollout controls:**

- [ ] **Mainnet config gate.** Set `CONDUIT_NETWORK=mainnet`. The startup validator
      (`config.py`) **refuses to boot** unless `BOOTSTRAP_API_KEY` starts with
      `ck_live_`, `API_SECRET_KEY` is non-default, and `DATABASE_URL` is Postgres.
      Generate fresh `ck_live_…` and `API_SECRET_KEY` (`openssl rand -hex 32`).
- [ ] **Canary checkpoint between every stage.** Hold at the stage's dwell time;
      review the dashboards and the stuck-row query before lifting caps.
- [ ] **Rollback plan (code):** `bash infra/scripts/deploy.sh rollback` promotes
      `conduit/core:prod-rollback` back to `:prod`, recreates only the api, and
      health-gates on `/v1/health/ready`. A failed deploy **auto-rolls-back**.
      Per-version archive tags (`conduit/core:prod-vX.Y.Z`) allow targeted reverts.
- [ ] **Rollback plan (money):** caps reduction and the policy `enabled=false` kill
      switch are your immediate brakes — they take effect without a redeploy.
- [ ] **Migrations are forward-applied on boot** (`entrypoint.sh` runs
      `alembic upgrade head`). A schema change has no automatic down-migration in
      the deploy flow; rehearse migrations on a copy of prod data first.

---

## 7. Security hardening of the box

From `infra/README.md` and `docs/docs/production.md` security checklists, with the
mainnet-specific deltas called out.

| # | Item | Status |
|---|---|---|
| 7.1 | **SSH:** `PasswordAuthentication no`, key-only, non-root deploy user (`conduit`). | Operator |
| 7.2 | **fail2ban** installed and watching `sshd` (and nginx access logs). Installed by `setup_firewall.sh`. | Provided |
| 7.3 | **unattended-upgrades** enabled for security patches. | Operator |
| 7.4 | **Firewall** (`setup_firewall.sh`) — LND/bitcoind RPC/ZMQ never exposed (see 2.7). | Provided |
| 7.5 | **Secret management — minimize plaintext env.** Today `.env.prod` holds `POSTGRES_PASSWORD`, `API_SECRET_KEY`, `BOOTSTRAP_API_KEY` in plaintext on disk, and compose injects them as env. For mainnet, move these to a secrets manager / Docker secrets and inject at runtime where possible. The LND wallet password must come from KMS/HSM (2.5), not a plaintext file. | **Partial — harden** |
| 7.6 | **Least privilege:** scoped LND macaroon (2.6), `secrets/*` mode 600 owned by deploy user, api container mounts secrets read-only, Postgres has no published port (compose). | Mostly provided |
| 7.7 | **No plaintext secrets in git:** `.gitleaks.toml` + secret-scanning CI; `.env.prod` and `/etc/conduit/backup.env` are gitignored and `0600`. | Provided |
| 7.8 | **TLS:** certbot-managed certs, HSTS + security headers set in nginx (`conduit.prod.conf`); HTTP→HTTPS redirect; `server_tokens off`. Confirm renewal cron. | Provided |
| 7.9 | **CORS:** `ALLOWED_ORIGINS` lists only your own domains (empty = no cross-origin). Credentials only allowed when an explicit allowlist is set (`main.py`). | Operator |
| 7.10 | **Bootstrap/admin key** stored in a secret manager, never committed, rotated if leaked. It is your master key — guard it like the macaroon. | Operator |

---

## 8. Final Go / No-Go gate

Sign off on **every** line. **Any** unchecked box is a **No-Go**. Date and initial.

### Prerequisites (Section 1)
- [ ] External security audit complete; report on file
- [ ] All High/Critical findings remediated; Mediums/Lows risk-accepted in writing
- [ ] Written legal / money-transmission opinion obtained
- [ ] Incident-response runbook written **and** rehearsed on testnet
- [ ] Restore-from-backup drill (Postgres **and** SCB) passed within 30 days

### Node & custody (Section 2)
- [ ] LND backed by **full bitcoind** (NOT neutrino); fully synced (`synced_to_chain=true`)
- [ ] Box meets sizing; disk headroom monitored
- [ ] Channel outbound ≥ planned float + margin; inbound capacity planned
- [ ] Watchtower client configured
- [ ] SCB exported on a schedule **and** replicated off-box; recovery tested
- [ ] Wallet unlock is KMS/HSM-backed **or** manual `lncli unlock` (NOT the plaintext file on a high-value node)
- [ ] LND macaroon scoped (not `admin`); secrets mode 600; rotation procedure documented
- [ ] Firewall verified: LND/bitcoind RPC/ZMQ never ALLOW

### Data durability (Section 3)
- [ ] Postgres HA (primary + replica) or managed Postgres
- [ ] PITR / WAL archiving configured
- [ ] Off-box encrypted backups running with dead-man's switch
- [ ] Restore verified within 30 days
- [ ] Connection-pool math checked against `max_connections`

### Application controls (Section 4)
- [ ] `SOLVENCY_ENFORCE=true`
- [ ] Conservative `Policy` attached to **every** agent (no agent on default-allow)
- [ ] Total float bounded below channel outbound; global cap compensated operationally
- [ ] Reconciler green — **zero** stuck `pending` sends; no unresolved `needs_reconciliation`
- [ ] All Section 4.5 alerts wired and tested (fired at least once)

### Observability & on-call (Section 5)
- [ ] `/metrics` confirmed **404 at the public edge**; scraped internally only
- [ ] Prometheus + dashboards live; logs shipped; SLOs defined
- [ ] On-call rota named; paging tested

### Rollout & box (Sections 6–7)
- [ ] `CONDUIT_NETWORK=mainnet`; fresh `ck_live_…` bootstrap key + `API_SECRET_KEY`; startup validator passes
- [ ] `deploy.sh` rollback verified (you have rolled back at least once in a drill)
- [ ] SSH hardened, fail2ban + unattended-upgrades on, secrets minimized, TLS + CORS correct

---

**Go decision:** _________________________  **Date:** ____________  **Signed:** ____________

> Reminder of what is **NOT shipped today** and must be built/configured before
> mainnet: external audit (1.1), legal opinion (1.3), IR runbook (1.4), Postgres
> HA + PITR (3.1–3.2), watchtower (2.3), KMS/HSM wallet unlock (2.5), scoped
> macaroon + rotation (2.6), instance-wide global cap + circuit breaker (4.3),
> reconciler/invoice-watcher liveness gauges (4.5). Everything else is in the
> codebase and needs only correct configuration.
