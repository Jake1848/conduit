# conduit-btc-mcp

Model Context Protocol server that exposes Conduit Lightning payments as tools
to any MCP-compatible AI agent (Claude Desktop, Cursor, custom agents).

> Installs as the PyPI package **`conduit-btc-mcp`**; the console command it
> provides is **`conduit-mcp`** (that's what you put in `claude_desktop_config.json`).

Conduit is **self-hosted and non-custodial**. This MCP server connects to **your
own** Conduit instance — the one you run against **your own** LND node, with
**your own** keys. It is *not* a hosted Conduit service and never touches your
funds. You point it at your deployment with two environment variables:

- `CONDUIT_API_KEY` — an API key you minted on **your** Conduit instance.
- `CONDUIT_API_URL` — the base URL of **your** instance (e.g.
  `https://conduit.your-domain.com`). Optional; if unset it defaults to the
  hosted demo at `https://api.conduit.energy`. Set it to your own URL in
  production.

Your node, your keys, your rules.

## Install

```bash
pip install conduit-btc-mcp
```

## Configure (Claude Desktop)

Add to `claude_desktop_config.json`, pointing `CONDUIT_API_URL` at **your**
self-hosted Conduit instance:

```json
{
  "mcpServers": {
    "conduit": {
      "command": "conduit-mcp",
      "env": {
        "CONDUIT_API_KEY": "ck_live_xxxxxxxxxxxx",
        "CONDUIT_API_URL": "https://conduit.your-domain.com"
      }
    }
  }
}
```

## Tools exposed

Each tool requires a particular API-key **scope**. Conduit enforces these scopes
server-side: a key with an insufficient scope is rejected. Mint a key with the
right scope on your instance (`read` < `write` < `admin`; higher scopes include
lower ones).

| Tool | Purpose | Required scope |
| ---- | ------- | -------------- |
| `conduit_create_wallet` | Create an agent wallet with a daily limit (sats) | `admin` |
| `conduit_credit`        | Fund an agent wallet from operator node liquidity (sats) | `admin` |
| `conduit_attach_policy` | Set spending controls: per-tx, hourly, daily, allow/blocklist | `admin` |
| `conduit_balance`       | Read current balance | `read` |
| `conduit_pay`           | Send to a Lightning address (`name@host`), BOLT11 invoice, or raw node pubkey (keysend) | `write` |
| `conduit_receive`       | Generate an invoice for inbound payment | `write` |
| `conduit_transactions`  | List recent transactions | `read` |
| `conduit_decisions`     | Inspect policy-engine decisions + the margin to each limit (why a payment was blocked / how close it came) | `read` |
| `conduit_fees`          | Report this operator's platform-fee revenue (sats) | `admin` |

> **Scopes, accurately.** Creating agents (`conduit_create_wallet`) and setting
> policies (`conduit_attach_policy`) are **admin** operations — an `admin`-scope
> key is required, not merely `write`. Sending payments and generating invoices
> require `write`. Reading balances, transactions, and decisions require `read`. The
> platform-fee report (`conduit_fees`) requires `admin`. If you want an agent to
> *spend* but never *reconfigure* itself, give it a `write` key — it can `pay`
> and `receive`, but not create wallets, change policies, or read fee revenue.

### `conduit_decisions`

Read-only inspection of the policy engine's **Decision Record**. Every payment
attempt — `settled`, `failed`, **and** policy/balance/destination-`rejected` — is
recorded with the **margin to each threshold**, so you can ask *why was this
blocked* and *how close was it to the limit*. Routing by input:

- `decision_id` given → `GET /v1/decisions/{id}` (one decision)
- else `agent` given → `GET /v1/agents/{agent}/decisions` (one wallet, newest first)
- else → `GET /v1/decisions/recent` (the whole fleet)

Filter a list with `outcome` (`settled` | `failed` | `rejected`) to surface only
the rejected attempts. Each decision carries `thresholds[]` with `margin_abs`
(`= limit − (current + attempted)`; **negative = violated**) and `binding_rule` —
present even when the payment was **allowed** (a near-miss-that-passed). No
secret/preimage is ever returned. Example (single decision):

```json
{
  "decision": {
    "id": "dec_9f3c...",
    "agent_id": "agt_abc...",
    "outcome": "rejected",
    "reason_code": "PER_TRANSACTION_LIMIT_EXCEEDED",
    "requested_sats": 5000,
    "thresholds": [
      { "rule": "per_transaction", "unit": "sats", "limit": 1000,
        "attempted": 5000, "current": 0, "margin_abs": -4000,
        "margin_pct": -400.0, "violated": true }
    ],
    "binding_rule": "per_transaction",
    "min_margin_pct": -400.0,
    "created_at": "2026-06-27T00:00:00Z"
  }
}
```

A list call returns `{ "decisions": [ ... ], "has_more": false }`.

### `conduit_fees`

Calls `GET /v1/fees` on your instance (admin scope) and returns the operator's
accumulated platform-fee revenue — the small per-payment fee (in sats) Conduit
charges on top of each payment and keeps on settle (refunded in full on
failure). The fee is configured by you, the operator, via `PLATFORM_FEE_PERCENT`
/ `PLATFORM_FEE_MIN_SATS` / `PLATFORM_FEE_MAX_SATS` on your deployment. Returns:

```json
{
  "total_collected_sats": 12345,
  "total_collected_btc": 0.00012345,
  "today_sats": 678,
  "fees_by_day": [
    { "date": "2026-06-06", "sats": 678, "tx_count": 9 }
  ]
}
```

`fees_by_day` is ordered most-recent-first.

## Policy enforcement

The Conduit policy engine enforces every payment **before** it reaches the
Lightning Network. An AI cannot exceed the limits attached to its wallet.
