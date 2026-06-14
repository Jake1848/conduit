# MCP server

The `conduit-mcp` server exposes Conduit as Model Context Protocol tools.
Any MCP-compatible client — Claude Desktop, Cursor, custom agents — can
make Lightning payments through an agent wallet on the **operator's own** node.
(The agent wallet is a virtual, operator-controlled sub-balance of the LND node
**you** run — the agent holds an API key, not a signing key.)

```bash
pip install conduit-btc-mcp
```

## Claude Desktop

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

Restart Claude. You'll see `conduit` tools in the tool picker.

## Tools

| tool | purpose |
| ---- | ------- |
| `conduit_create_wallet`  | provision a new agent wallet with a daily limit |
| `conduit_credit`         | fund an agent wallet from operator node liquidity |
| `conduit_attach_policy`  | configure spending controls |
| `conduit_balance`        | read current balance |
| `conduit_pay`            | send to a Lightning address or BOLT11 |
| `conduit_receive`        | generate an invoice for inbound funds |
| `conduit_transactions`   | list recent transactions |
| `conduit_fees`           | report the operator's platform-fee revenue |

## Why the AI can't escape the policy

The MCP server is just a translator — every tool call ultimately hits the
Conduit Core API, where the policy engine evaluates the request **before**
it touches Lightning. The model's input has no way to bypass that gate:
the wallet's `daily_limit`, `max_per_transaction`, and `allowlist` are
authoritative.

If you want belt-and-suspenders, give the MCP server a `write` (not
`admin`) API key. Then even a jailbroken prompt that asks the agent to
"raise its own limit" will fail at the auth layer.
