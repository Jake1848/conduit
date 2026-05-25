# Conduit

**Bitcoin payment infrastructure for autonomous AI agents.**

Conduit gives any AI agent a Lightning wallet, a spending policy, and an API to
send, receive, and account for Bitcoin payments — programmatically, with hard
guardrails the agent cannot override.

- Website: https://conduit.energy
- API: https://api.conduit.energy
- Docs: https://docs.conduit.energy

---

## Repository layout

```
.
├── website/         Landing page (deployed to conduit.energy)
├── core/            Conduit Core API — FastAPI server in front of LND
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
| 1 | Bitcoin Core + LND nodes | install scripts only — runs on Hetzner | `infra/` |
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
key `ck_test_dev_root`, and SQLite at `/app/data/conduit.db`.

## Going to production

Production requires real Lightning infrastructure. The order of operations:

1. Install Bitcoin Core (pruned) on Hetzner — `infra/scripts/install_bitcoind.sh`
2. Install LND (mainnet + testnet) — `infra/scripts/install_lnd.sh`
3. Configure UFW — `infra/scripts/setup_firewall.sh`
4. Wait for chain sync (1–3 days)
5. Open channels — `infra/scripts/setup_channels.sh`
6. Point the Core API at the real LND macaroon and TLS cert (`LND_MOCK=false`)
7. Deploy with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

Full runbook: `infra/README.md`.

## Security

- LND seed phrase is **never** stored on the VPS
- LND gRPC / REST is **never** exposed publicly
- The Conduit policy engine evaluates every payment **before** it reaches LND
  and **fails closed** on any error
- API keys are bcrypt-hashed at rest and shown to the operator exactly once
- All transit is HTTPS; webhook deliveries are HMAC-signed

See `infra/README.md` → "Security checklist".

## License

MIT.
