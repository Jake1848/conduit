# Demo — an AI agent that pays over Bitcoin Lightning

This is the five-minute "wow": you give an AI agent a budget and a policy, and it
**autonomously pays a Lightning invoice** — then gets **stopped by its own policy**
the moment it tries to overspend. Every limit is enforced **server-side**, on your
own node. The model never holds your node, your keys, or the ability to exceed the
budget you set.

You can run it two ways:

- **Path A — MCP + Claude Desktop:** Claude calls Conduit tools in plain English.
- **Path B — raw SDK (no MCP):** a single Python script. Same flow, no AI client.

Both drive the **same** Conduit instance and the **same** server-enforced policy.

---

## 1. Get a Conduit instance running

You need a Conduit Core API to talk to. Two options:

### Option A (recommended for the demo) — local, mock Lightning

Self-contained, settles instantly, no real funds, works offline. From the repo root:

```bash
docker compose -f docker-compose.dev.yml up --build
# API on http://127.0.0.1:8000, mock LND, bootstrap admin key = ck_test_dev_root
curl -s http://127.0.0.1:8000/v1/health      # -> {"ok":true,...}
```

The dev stack runs `LND_MOCK=true` with SQLite and auto-creates the schema on
first boot, simulating Lightning settlement in-memory — a payment settles in
~40 ms and you can pay an invoice the demo mints itself. Use:

- `CONDUIT_API_URL = http://127.0.0.1:8000`
- `CONDUIT_API_KEY = ck_test_dev_root`

### Option B — the public regtest instance (real Lightning, on regtest)

A hosted demo node on Bitcoin **regtest** (worthless test coins, real LN settlement):

- `CONDUIT_API_URL = https://api-test.conduit.energy`
- `CONDUIT_API_KEY = ck_test_regtest_root_key`  ← shared regtest demo key, **no real funds**

On a real node (regtest or mainnet) an agent must pay an **external** invoice — a
node can't pay an invoice it issued itself — so the self-contained "pay your own
vendor wallet" step only fully settles on the local mock instance (Option A). For
anything real, **mint your own key** on your own instance instead of using the
shared demo key.

---

## 2. Path A — MCP with Claude Desktop

### Install the server

```bash
pip install conduit-mcp
```

> Until `conduit-mcp 0.8.3` is published to PyPI you can install from this repo:
> `pip install ./sdk-python ./mcp-server` (installs the SDK it depends on too).

### Configure Claude Desktop

Add this to your `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`), then **restart Claude Desktop**:

```json
{
  "mcpServers": {
    "conduit": {
      "command": "conduit-mcp",
      "env": {
        "CONDUIT_API_KEY": "ck_test_dev_root",
        "CONDUIT_API_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

(Use the Option B values to point at the public regtest instead.)

After restarting, Claude Desktop shows a 🔌 tool indicator with eight `conduit_*`
tools available.

### Drive it in plain English

Type these to Claude, one at a time. Claude will call the matching tool and show
you the JSON it gets back.

1. **Provision + fund the agent**
   > Create a Lightning wallet called `demo-agent` with a daily limit of 50,000
   > sats, then credit it 20,000 sats.

   → `conduit_create_wallet` then `conduit_credit`. You'll see an `agt_…` id and a
   balance of `20000`.

2. **Set the guardrails**
   > Attach a policy to demo-agent: max 10,000 sats per transaction, max 50,000 per
   > day, and require a memo on every payment.

   → `conduit_attach_policy` → `{ "ok": true }`.

3. **Make a payable invoice** (the "vendor" the agent will pay)
   > Create a wallet called `news-vendor` and generate a 1,500-sat invoice on it
   > with the memo "AAPL headlines".

   → `conduit_create_wallet` + `conduit_receive`; you'll get a `lnbcrt…` invoice.

4. **The agent pays — within policy**
   > Pay that invoice from demo-agent with the memo "news.fetch".

   → `conduit_pay` → `{ "status": "settled", "fee_sats": 1, "platform_fee_sats": 8, … }`.
   The agent just moved money over Lightning on its own.

5. **The agent tries to overspend — and is stopped**
   > Now pay 20,000 sats from demo-agent to a new 20,000-sat invoice.

   → `conduit_pay` is **rejected server-side**:
   `PER_TRANSACTION_LIMIT_EXCEEDED — Payment of 20000 sats exceeds per-transaction
   limit of 10000 sats.` The model cannot talk its way past the policy.

6. **Show the receipts**
   > Show demo-agent's recent transactions and the operator's fee revenue.

   → `conduit_transactions` (the settled `send` + the `receive` credit) and
   `conduit_fees` (the platform fee the operator kept).

That's the whole story: **autonomy with a hard, server-side leash.**

### The eight tools

| Tool | Purpose | Scope |
| ---- | ------- | ----- |
| `conduit_create_wallet` | Create an agent wallet with a daily limit | `admin` |
| `conduit_credit` | Fund a wallet from operator node liquidity | `admin` |
| `conduit_attach_policy` | Set per-tx / hourly / daily / allow- / blocklist / memo rules | `admin` |
| `conduit_balance` | Read a wallet's balance | `read` |
| `conduit_pay` | Pay a Lightning address or BOLT11 invoice | `write` |
| `conduit_receive` | Mint an invoice to receive | `write` |
| `conduit_transactions` | List recent transactions | `read` |
| `conduit_fees` | Operator's platform-fee revenue | `admin` |

Give a spending agent a **`write`** key: it can `pay`/`receive` but cannot create
wallets, change policies, or read fee revenue.

---

## 3. Path B — raw SDK, no MCP

Same flow as a single script — the non-MCP fallback. Against the local mock
instance (Option A) it settles a real (simulated) payment and demonstrates the
policy block:

```bash
export CONDUIT_API_KEY=ck_test_dev_root
export CONDUIT_API_URL=http://127.0.0.1:8000
python sdk-python/examples/ai_agent_pays_api.py
```

Expected output:

```
created wallet agt_… (daily limit 50,000 sats)
funded     balance = 20,000 sats
policy     <= 10,000/tx, <= 50,000/day, memo required

PAID       1,500 sats  status=settled  fee=1  platform_fee=8  in 44 ms
BLOCKED    over-limit payment rejected: PER_TRANSACTION_LIMIT_EXCEEDED — Payment of 20000 sats exceeds per-transaction limit of 10000 sats.

remaining  balance = 18,491 sats
```

The full source is
[`sdk-python/examples/ai_agent_pays_api.py`](sdk-python/examples/ai_agent_pays_api.py).
For the framework-integration shape (a `pay_lightning` tool an LLM calls — LangChain,
CrewAI, OpenAI/Anthropic function-calling), see
[`sdk-python/examples/ai_agent_tool.py`](sdk-python/examples/ai_agent_tool.py).

---

## What the demo proves

- An AI agent can **hold a budget and spend it autonomously** over Bitcoin Lightning.
- The operator's **policy is enforced on the server**, before anything reaches the
  Lightning Network — the agent cannot exceed it no matter what the model decides.
- Conduit is **self-hosted and non-custodial**: it runs against **your** LND node
  with **your** keys; the AI never touches the node or the funds directly.

> Status: early, single-operator, mainnet-validated. The demo runs on mock-LND
> locally or on regtest — use your own node and your own keys for anything real.
