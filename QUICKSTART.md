# Conduit Quickstart — 5 minutes to your first Lightning payment

**Your node, your keys, your rules.** Conduit is self-hosted, non-custodial software:
it runs on *your* infrastructure and pays out from *your own* LND node with *your own*
keys. Conduit never touches your funds. It adds programmable agents, spend policies,
an atomic ledger, and a small per-transaction platform fee that goes straight to *you*,
the operator.

## Requirements

- **Docker** (with Compose v2 — `docker compose`, not `docker-compose`)
- **An LND node, v0.18+**, with its **REST** interface enabled and reachable
- Your node's **`admin.macaroon`** and **`tls.cert`**

That's it. No cloud account, no custody hand-off, no fiat rails.

## 1. Clone

```bash
git clone https://github.com/Jake1848/conduit.git
cd conduit
```

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

- Set `LND_REST_URL` to your node's REST endpoint (e.g. `https://host.docker.internal:8080`
  for LND on the same host, or `https://<your-node-ip>:8080` for a remote node).
- Generate fresh secrets:

  ```bash
  # BOOTSTRAP_API_KEY  (must start with ck_live_ on mainnet)
  echo "ck_live_$(openssl rand -hex 20)"
  # API_SECRET_KEY
  openssl rand -hex 32
  # POSTGRES_PASSWORD
  openssl rand -hex 24
  ```

Paste each value into the matching line in `.env`.

## 3. Add your node's credentials

Conduit reads these read-only from `./secrets/` — they never leave your machine.

```bash
mkdir -p secrets
cp /path/to/your/lnd/admin.macaroon secrets/admin.macaroon
cp /path/to/your/lnd/tls.cert       secrets/tls.cert
```

(On a standard LND install the macaroon lives at
`~/.lnd/data/chain/bitcoin/mainnet/admin.macaroon` and the cert at `~/.lnd/tls.cert`.)

## 4. Launch

```bash
docker compose up -d
```

This starts Postgres (the ledger) and the Conduit API on **http://localhost:8000**.
Database migrations run automatically on first boot.

## 5. Verify it's healthy

```bash
curl http://localhost:8000/v1/health
```

You should get a `200` with a JSON status payload.

## 6. Create your first agent

Authenticate with the `BOOTSTRAP_API_KEY` you generated above. Agents are spending
identities with their own balance and policies.

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "Authorization: Bearer ck_live_your_bootstrap_key" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-first-agent", "daily_limit": 100000}'
```

The response includes the new `agent_id`. Credit it, attach policies, and start
sending payments — every successful outbound payment settles on **your** node.

## Install an SDK

```bash
# Python
pip install conduit-lightning

# Node / TypeScript
npm install @conduit-btc/sdk
```

Point the SDK at your API base URL (`http://localhost:8000`) and the API key.

## Your revenue: the platform fee

Conduit charges a small **per-transaction platform fee in satoshis** on top of each
outbound payment — this is **your** usage-based revenue as the operator, kept on settle
and refunded in full if the payment fails. It's fully configurable in `.env`:

- `PLATFORM_FEE_PERCENT` (default `0.5` = 0.5%)
- `PLATFORM_FEE_MIN_SATS` (default `1`)
- `PLATFORM_FEE_MAX_SATS` (default `1000`)

Set `PLATFORM_FEE_PERCENT=0` to disable it. Track what you've earned with
`GET /v1/fees` (admin key) or the `fee_revenue_total_sats` field on `GET /v1/metrics`.
Payment receipts report it as `platform_fee_sats`, separate from `fee_sats` (the LND
routing fee).

## Dashboard & docs

- **Operator console:** https://console.conduit.energy — point it at your API base URL
  and key to watch agents, payments, and fee revenue in real time.
- **Full docs:** https://docs.conduit.energy
