# Conduit

**Self-hosted Bitcoin Lightning payment infrastructure for autonomous AI agents.**

Conduit is software tooling you run on **your own** infrastructure, in front of
**your own** LND node, with **your own** keys. It gives any AI agent a virtual
Lightning wallet, a spending policy, and an API to send, receive, and account
for Bitcoin payments — programmatically, with hard guardrails the agent cannot
override.

There is no Conduit SaaS: you host it, Conduit never holds your funds and never
phones home. At the operator level it's self-hosted — your node, your keys, your
rules. The agents you create are **virtual sub-balances** in a ledger that you,
the operator, control: they hold a scoped API key, not a signing key, and you
can credit, debit, or sweep them at any time.

Status: **v0.8.4 — running live on testnet and mainnet** (testnet/regtest plus
a live mainnet node; the first real mainnet payment has settled end-to-end —
still early and small, single-operator, not production-at-scale). The operator
treasury (added in 0.8.3) lets you see accrued platform-fee revenue and withdraw
accrued BTC on-chain, gated by a solvency guard (node assets can never drop below
what you owe agents). 0.8.4 adds a full audit/red-team pass, the complete
operator console, and an agent-pays-over-Lightning demo (see `DEMO.md`).

- Website: https://conduit.energy
- Hosted demo API: https://api.conduit.energy (testnet) · https://api-mainnet.conduit.energy (mainnet)
- Docs: https://docs.conduit.energy

---

## How it works

You deploy Conduit (a 5-minute Docker bring-up) against your LND node. Conduit
sits in front of LND as a policy + accounting layer:

- **You** hold the LND seed and macaroon. Conduit only ever talks to LND over
  the macaroon **you** mount into it.
- **You** are the operator. The bootstrap API key is **your** master key to
  **your own** system — it mints the scoped keys you hand to your agents.
- **You** credit and debit the virtual sub-balances of the agents running on
  **your** node — Conduit is custodial *for the agents by construction*: the
  agent balances are operator-controlled IOUs in Conduit's ledger, and the
  underlying sats stay in your channels under your keys.
- **You** set a per-transaction **platform fee** (in sats) that Conduit adds on
  top of each payment and keeps on settlement — that fee is **your** revenue,
  configured by you, never a Conduit cut.

## Revenue model

Conduit's built-in monetization is a small, usage-based **platform fee in
satoshis** that the operator who deploys Conduit configures. It is charged on
top of each payment, kept when the payment settles, and refunded in full if the
payment fails. Sats only — no fiat, no cards, no subscription.

| env var | default | meaning |
| ------- | ------- | ------- |
| `PLATFORM_FEE_PERCENT`  | `0.5`  | platform fee, as a percent of the payment amount (0.5 = 0.5%) |
| `PLATFORM_FEE_MIN_SATS` | `1`    | floor for the per-transaction platform fee |
| `PLATFORM_FEE_MAX_SATS` | `1000` | ceiling for the per-transaction platform fee |

Collected fees are reported at `GET /v1/fees` (admin) and surfaced in
`GET /v1/metrics`. Set `PLATFORM_FEE_PERCENT=0` to run Conduit with no fee.

## Repository layout

```
.
├── website/         Landing page (deployed to conduit.energy)
├── core/            Conduit Core API — FastAPI server you run in front of your LND
├── sdk-python/      Python SDK (`conduit-btc` on PyPI; import `conduit`)
├── sdk-js/          TypeScript SDK (`@conduit-btc/sdk` on npm)
├── mcp-server/      MCP server (`conduit-btc-mcp` on PyPI; `conduit-mcp` command)
├── infra/           Bitcoin Core / LND configs, systemd units, install scripts
├── docs/            MkDocs documentation site
├── docker-compose.yml
└── Conduit_Whitepaper_v1.pdf
```

## The five components

| # | Component | Status | Path |
| - | --------- | ------ | ---- |
| 1 | Bitcoin Core + LND nodes | install scripts — you run them on your own host | `infra/` |
| 2 | Conduit Core API | FastAPI app, runs with mock-LND for local dev | `core/` |
| 3 | Python SDK | matches the website code panel | `sdk-python/` |
| 4 | TypeScript SDK | mirrors the Python interface | `sdk-js/` |
| 5 | MCP server | exposes Conduit as MCP tools | `mcp-server/` |

## Quickstart (local, mock LND)

```bash
# 1. Bring up the API in mock mode
docker compose up --build

# 2. Hit the API
curl http://localhost:8000/v1/health

# 3. Use the Python SDK
cd sdk-python && pip install -e .
export CONDUIT_API_KEY=ck_test_dev_root
python examples/quickstart.py
```

The dev container ships with `LND_MOCK=true`, an auto-created `admin`-scoped
bootstrap key `ck_test_dev_root` (your master key in dev), and SQLite at
`/app/data/conduit.db`. No real Bitcoin moves until you point Conduit at a real
LND node of your own.

## Running against a real node

Conduit is self-hostable today on **testnet**, **regtest**, and **mainnet** —
all three run live. Mainnet is now real: a neutrino LND node with a real channel
is up and the first real-money payment has settled end-to-end. It is still
early and small, so treat a mainnet bring-up as new territory and test on
testnet first. The order of operations against your own Lightning
infrastructure:

1. Install Bitcoin Core (pruned) on your host — `infra/scripts/install_bitcoind.sh`
2. Install LND (testnet today; mainnet supported) — `infra/scripts/install_lnd.sh`
3. Configure UFW — `infra/scripts/setup_firewall.sh`
4. Wait for chain sync (1–3 days)
5. Open channels — `infra/scripts/setup_channels.sh`
6. Point the Core API at **your** LND macaroon and TLS cert (`LND_MOCK=false`)
7. Set your `PLATFORM_FEE_*` values to whatever revenue you want to charge
8. Deploy with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

### Mainnet (live)

Mainnet is live but early and small. The deployment today is a single neutrino
LND node with one ~20k-sat channel. The first real-money payment has settled
end-to-end: 2000 sats sent via Lightning keysend, a 10-sat platform fee (0.5%)
collected, 1-sat routing fee, settled in ~15s — with the full lifecycle
verified (debit → route → settle → platform-fee capture → refund-on-failure →
exact ledger reconciliation). This is a first real-money validation, **not**
production-at-scale; do not assume throughput or battle-testing. The live
mainnet API is at https://api-mainnet.conduit.energy.

Full runbook: `infra/README.md`.

## Self-hosted trust model

Conduit is **self-hosted by construction** — it is software you operate, not a
service that holds your money. Be clear about who custodies what:

- **At the operator level you are self-hosted.** There is no Conduit SaaS;
  Conduit never holds your funds and never phones home. The LND seed phrase is
  **yours** and is **never** stored on the VPS by Conduit; the sats stay in
  channels under your keys.
- **At the agent level Conduit is custodial.** Agent balances are virtual
  IOUs in Conduit's ledger that you, the operator, credit, debit, and can
  sweep. Agents hold a scoped API key, not a signing key — they never touch a
  Bitcoin private key.
- LND gRPC / REST is **never** exposed publicly — only your Conduit API is
- The Conduit policy engine evaluates every payment **before** it reaches your
  LND and **fails closed** on any error
- API keys are bcrypt-hashed at rest and shown to you, the operator, exactly once
- The bootstrap API key is your master key — guard it like the macaroon
- All transit is HTTPS; webhook deliveries are HMAC-signed

Conduit is the policy + accounting layer in front of a node you control. If you
turn Conduit off, your sats are still in your channels.

See `infra/README.md` → "Security checklist".

## Authorization model (single-operator today)

Authorization in Conduit is **scope-based, not per-agent**. An API key carries
one of three scopes — `read` < `write` < `admin` — and that scope is the *only*
boundary:

- A `read` key can read the **entire fleet** — every agent, balance, and
  transaction.
- A `write` key can act on **any agent** — send a payment from, or create an
  invoice for, any agent in the ledger.
- An `admin` key can create/delete agents, move balances, manage policies and
  webhooks, and mint keys across the whole instance.

There is **no per-agent boundary**: a key is not tied to a specific agent, and
no route filters by which key created or "owns" an agent. Agents are an
accounting and policy unit, **not a security boundary between mutually
distrusting parties**.

Concretely: **Conduit today is a single-operator tool.** Hand scoped keys to
agents *you* run, not to third parties you don't trust with each other. If you
need hard isolation between tenants, run a separate Conduit instance (and node)
per tenant.

> **Roadmap:** multi-tenant, per-agent scoping — where a key is bound to one
> agent (or set of agents) and cannot read or act on the rest of the fleet — is
> a planned enhancement. As a first step toward it, `create_agent` now records
> the minting key on `Agent.api_key_id` for provenance. This is **provenance
> only**: it does not yet change or enforce any authorization.

## License

MIT.
