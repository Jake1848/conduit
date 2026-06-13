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
| `conduit_pay`           | Send to a Lightning address (`name@host`) or BOLT11 invoice | `write` |
| `conduit_receive`       | Generate an invoice for inbound payment | `write` |
| `conduit_transactions`  | List recent transactions | `read` |
| `conduit_fees`          | Report this operator's platform-fee revenue (sats) | `admin` |

> **Scopes, accurately.** Creating agents (`conduit_create_wallet`) and setting
> policies (`conduit_attach_policy`) are **admin** operations — an `admin`-scope
> key is required, not merely `write`. Sending payments and generating invoices
> require `write`. Reading balances and transactions require `read`. The
> platform-fee report (`conduit_fees`) requires `admin`. If you want an agent to
> *spend* but never *reconfigure* itself, give it a `write` key — it can `pay`
> and `receive`, but not create wallets, change policies, or read fee revenue.

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
