# Production Readiness

The single-page status index for taking Conduit from where it is today to a
real-money mainnet deployment. It states the **honest current status**, tracks
the three go-live **gates**, and links to the detailed runbook/brief behind each.

This page does not duplicate those documents — it tells you where Conduit stands
and what order to close the gaps in.

---

## Current status (honest)

| Property | Today |
| --- | --- |
| Version | **v0.8.1** (`core/conduit_core/__init__.py`) |
| Network | **testnet + regtest only** — mainnet has **never** been run in production |
| Hosting model | **Self-hosted.** No Conduit SaaS; a FastAPI app (`core/conduit_core`) in front of **one** operator-run LND node. Conduit never holds the seed and never phones home. |
| Custody | **Custodial at the agent layer.** Agent `balance_sats` are integer-sat IOUs/claims against the operator's single node; the operator can `credit`, `debit`/sweep, and pay out. The real sats stay in the operator's channels under the operator's keys. |
| Authorization | **Scope-based (`read` < `write` < `admin`), not per-agent.** Any valid key acts on the whole fleet. Single-operator tool by design — not a security boundary between distrusting tenants (`README.md` → "Authorization model"). |
| Security review | **In-house red-team only** (`core/tests/`, ~121 test functions, green in CI). **No independent external audit.** |
| Legal / regulatory | **No legal or money-transmission opinion.** No KYC/identity layer, no sanctions screening, no Travel Rule data path, no AML program, no ToS/Privacy Policy. |
| Wallet key protection | OS file perms + an **optional plaintext** unlock file. **No KMS/HSM.** Root on the box = wallet access (`infra/scripts/setup_wallet_unlock.sh`). |
| Data durability | **Single** `postgres:16-alpine` container, **no replica/HA**; `pg_dump` backups + optional off-box S3 copy with a dead-man's switch. No PITR/WAL archiving. |
| Solvency control | Monitor exists (`services/solvency.py`); enforcement is **opt-in** (`SOLVENCY_ENFORCE=false` by default — observe-and-warn). |

**Bottom line: Conduit is NOT mainnet-ready, NOT independently audited, and has NO
legal clearance as shipped.** It is testnet/regtest-grade self-hosted software with
a hardened money path and a documented gap list. Do not move real sats or onboard
third parties until the three gates below are met.

> What Conduit *does* have today are **operational-integrity** controls, not
> regulatory-compliance or assurance controls: an atomic per-agent ledger with a
> DB-level `CHECK(balance_sats >= 0)` (alembic `0006`), debit-before-pending under
> a row lock, idempotency reservations on a unique `(api_key_id, key)` against
> double-spend, SSRF-safe IP-pinned outbound HTTP (`services/safe_http.py`), an
> opt-in solvency monitor, and Prometheus/structlog observability (`/metrics` is
> 404 at the public nginx edge). These are necessary, not sufficient, for mainnet.

---

## The three gates

All three are **NOT MET**. Every gate must be MET before a real-money mainnet
launch. They are independent in content but ordered in practice (see the path
below).

| Gate | Status | What it needs (one line) | Document |
| --- | --- | --- | --- |
| **Mainnet Readiness** | ❌ **NOT MET** | Full-`bitcoind` mainnet node, KMS/HSM wallet unlock, watchtower, off-box SCB + Postgres HA/PITR, `SOLVENCY_ENFORCE=true`, per-agent policies, alerting/on-call, and a staged dust→limited→general rollout — then sign the Go/No-Go gate. | [`docs/MAINNET_READINESS.md`](MAINNET_READINESS.md) |
| **Legal & Compliance** | ❌ **NOT MET** | A jurisdiction-specific opinion from licensed counsel on custody / money-transmission / MSB / VASP status, OFAC screening, state MTL mapping, and the self-vs-third-party-funds line — plus ToS/Privacy if onboarding others. | [`LEGAL_COMPLIANCE_BRIEF.md`](../LEGAL_COMPLIANCE_BRIEF.md) |
| **External Security Audit** | ❌ **NOT MET** | An independent firm reviews the money-movement paths and LND-key custody, all High/Critical findings are remediated or risk-accepted in writing, and a fix-verification re-test is complete. | [`docs/SECURITY_AUDIT_PREP.md`](SECURITY_AUDIT_PREP.md) |

> The in-house red-team suite (42/42 security scenarios, ~121 tests in CI) proves
> the controls behave **as intended**. It is **not** a substitute for the external
> audit gate — the team that wrote the controls and their tests shares the same
> blind spots.

---

## Realistic ordered path to mainnet

The gates run partly in parallel, but there is a sensible critical path. Each step
references the gate doc that owns the detail.

1. **Founder decisions first (cheap, unblocks everything).** Decide custodial vs.
   non-custodial vs. strictly single-operator/own-funds; whether any deployment
   will ever hold value for **third parties**; and target jurisdictions /
   geofencing. These choices determine which legal obligations even apply.
   → [Legal Brief §8.2](../LEGAL_COMPLIANCE_BRIEF.md)
2. **Engage counsel (long lead time — start early, run in parallel).** Take the
   legal brief to a qualified attorney for a custody / money-transmission opinion,
   OFAC obligations, and (if serving the US public) state MTL mapping. Treat MTL as
   a major cost/timeline line item, not a checkbox.
   → [Legal Brief §1–§5, §8.1](../LEGAL_COMPLIANCE_BRIEF.md)
3. **Engage an external auditor (long lead time — start early, run in parallel).**
   Hand over the audit-prep package, scope the RFP to the money paths and LND
   custody, and reserve budget for a fix-verification re-test.
   → [Audit Prep §5–§8](SECURITY_AUDIT_PREP.md)
4. **Close the Section-1 hard prerequisites.** Audit complete + findings closed;
   written legal opinion on file; incident-response runbook written **and**
   rehearsed on testnet; a Postgres **and** SCB restore-from-backup drill **passed**
   within 30 days. These gate everything downstream.
   → [Mainnet Runbook §1](MAINNET_READINESS.md)
5. **Build the custody & durability infrastructure.** Full-`bitcoind` mainnet node
   (not neutrino) fully synced; KMS/HSM-backed wallet unlock (or manual `lncli
   unlock`) instead of the plaintext file; watchtower client; scoped (non-`admin`)
   LND macaroon; off-box SCB replication; Postgres HA/replica or managed Postgres
   with PITR/WAL archiving.
   → [Mainnet Runbook §2–§3](MAINNET_READINESS.md)
6. **Flip the application controls to conservative.** `SOLVENCY_ENFORCE=true`;
   a conservative `Policy` attached to **every** agent (no agent left on
   default-allow); float bounded below channel outbound; reconciler green with zero
   stuck `pending` rows; all alerts wired and on-call staffed.
   → [Mainnet Runbook §4–§5](MAINNET_READINESS.md)
7. **Staged rollout, then sign the gate.** `CONDUIT_NETWORK=mainnet` with a fresh
   `ck_live_…` bootstrap key; advance dust canary → limited → general only on clean
   dwell-time criteria; verify `deploy.sh rollback` in a drill; then sign the
   single-page **Go / No-Go gate** — any unchecked line is a No-Go.
   → [Mainnet Runbook §6, §8](MAINNET_READINESS.md)

Until all three gates are MET, Conduit stays on **testnet/regtest** and any hosted
demo (e.g. `api.conduit.energy`) must remain clearly **no-real-value**.

---

## Related references

- Operator runbook & security checklist — [`infra/README.md`](../infra/README.md)
- Production env + startup validator — [`docs/production.md`](production.md)
- Security policy / disclosure / threat-model scope — [`SECURITY.md`](../SECURITY.md)
- Self-hosted trust & authorization model — [`README.md`](../README.md)