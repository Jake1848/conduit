# Conduit

**Self-hosted, non-custodial Bitcoin payment infrastructure for autonomous AI agents.**

Conduit is software tooling you run on **your own** infrastructure, in front of
**your own** LND node, signed by **your own** keys. It gives any AI agent a
Lightning wallet, a spending policy, and an API to send, receive, and account
for Bitcoin payments — programmatically, with hard guardrails the agent cannot
override.

Conduit **never touches your funds**. There is no Conduit-operated wallet, no
hosted custody, no third party in the payment path. Your node, your keys, your
rules.

- Website: https://conduit.energy
- Hosted demo API: https://api.conduit.energy
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
  **your** node. Conduit tracks the ledger; the sats stay in your channels.
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
├── sdk-python/      Python SDK (`conduit-sdk` on PyPI)
├── sdk-js/          TypeScript SDK (`@conduit/sdk` on npm)
├── mcp-server/      MCP server exposing Conduit as tools to AI agents
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

## Going to production

Production runs against **your own** Lightning infrastructure. The order of
operations:

1. Install Bitcoin Core (pruned) on your host — `infra/scripts/install_bitcoind.sh`
2. Install LND (mainnet + testnet) — `infra/scripts/install_lnd.sh`
3. Configure UFW — `infra/scripts/setup_firewall.sh`
4. Wait for chain sync (1–3 days)
5. Open channels — `infra/scripts/setup_channels.sh`
6. Point the Core API at **your** LND macaroon and TLS cert (`LND_MOCK=false`)
7. Set your `PLATFORM_FEE_*` values to whatever revenue you want to charge
8. Deploy with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

Full runbook: `infra/README.md`.

## Self-custody & trust model

Conduit is **non-custodial by construction** — it is software you operate, not
a service that holds your money:

- The LND seed phrase is **yours** and is **never** stored on the VPS by Conduit
- LND gRPC / REST is **never** exposed publicly — only your Conduit API is
- The Conduit policy engine evaluates every payment **before** it reaches your
  LND and **fails closed** on any error
- API keys are bcrypt-hashed at rest and shown to you, the operator, exactly once
- The bootstrap API key is your master key — guard it like the macaroon
- All transit is HTTPS; webhook deliveries are HMAC-signed

Conduit is just the policy + accounting layer in front of a node you control. If
you turn Conduit off, your sats are still in your channels.

See `infra/README.md` → "Security checklist".

## License

MIT.
