# conduit-mcp

Model Context Protocol server that exposes Conduit Lightning payments as tools
to any MCP-compatible AI agent (Claude Desktop, Cursor, custom agents).

## Install

```bash
pip install conduit-mcp
```

## Configure (Claude Desktop)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "conduit": {
      "command": "conduit-mcp",
      "env": {
        "CONDUIT_API_KEY": "ck_live_xxxxxxxxxxxx",
        "CONDUIT_API_URL": "https://api.conduit.energy"
      }
    }
  }
}
```

## Tools exposed

| Tool | Purpose |
| ---- | ------- |
| `conduit_create_wallet` | Create an agent wallet with a daily limit (sats) |
| `conduit_attach_policy` | Set spending controls: per-tx, hourly, daily, allow/blocklist |
| `conduit_balance`       | Read current balance |
| `conduit_pay`           | Send to a Lightning address (`name@host`) or BOLT11 invoice |
| `conduit_receive`       | Generate an invoice for inbound payment |
| `conduit_transactions`  | List recent transactions |

The Conduit policy engine enforces every payment **before** it reaches the
Lightning Network. An AI cannot exceed the limits attached to its wallet.
