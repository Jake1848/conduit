"""MCP server exposing a self-hosted Conduit instance as tools.

Any MCP-compatible client (Claude Desktop, Cursor, custom agents) can invoke
these tools to make Bitcoin Lightning payments through a Conduit agent wallet.
Conduit is self-hosted and non-custodial: this server talks to the CUSTOMER's
OWN Conduit deployment — the base URL and API key you configure point at the
instance you run against your own LND node, with your own keys. Conduit never
touches your funds. All payments are still gated by the spending policy attached
to the wallet — the AI cannot override it.

Tools and the API-key scope each one requires (scopes are enforced server-side):
  conduit_create_wallet   — provision a new agent wallet with a daily limit   [admin]
  conduit_credit          — fund an agent wallet from your node's liquidity    [admin]
  conduit_attach_policy   — configure spending controls on a wallet           [admin]
  conduit_balance         — check current balance                             [read]
  conduit_pay             — send a payment (Lightning address or BOLT11)       [write]
  conduit_receive         — generate an invoice for inbound funds             [write]
  conduit_transactions    — list recent transactions                          [read]
  conduit_fees            — report the operator's platform-fee revenue        [admin]

Run:
  conduit-mcp           # stdio transport (Claude Desktop, etc.)

Required env (point these at YOUR self-hosted Conduit instance):
  CONDUIT_API_KEY=ck_live_... or ck_test_...   (a key minted on your instance)
  CONDUIT_API_URL=https://conduit.your-domain.com   (optional; the hosted demo
                  defaults to https://api.conduit.energy if unset)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from conduit import (
    Agent,
    ConduitError,
    PolicyViolation,
    default_client,
)

server: Server = Server("conduit")


def _agent_for_name_or_id(name_or_id: str) -> Agent:
    if name_or_id.startswith("agt_"):
        return Agent.get(name_or_id)
    # search by name
    for a in Agent.list():
        if a.name == name_or_id:
            return a
    raise ConduitError(f"No agent matching {name_or_id!r}")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="conduit_create_wallet",
            description=(
                "Create a new Bitcoin Lightning wallet for this AI agent. "
                "The daily_limit (sats) is enforced by the Conduit policy engine — "
                "the agent CANNOT spend more than this in 24h. "
                "Requires an ADMIN-scope API key (creating agents is an admin action)."
            ),
            inputSchema={
                "type": "object",
                "required": ["name", "daily_limit"],
                "properties": {
                    "name": {"type": "string", "description": "Wallet name"},
                    "daily_limit": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Max sats per 24h",
                    },
                },
            },
        ),
        types.Tool(
            name="conduit_credit",
            description=(
                "Fund an agent wallet by crediting its virtual balance from the "
                "operator's own node liquidity (in sats). This is how you give an "
                "agent a spending budget before it can pay. Requires an ADMIN-scope key."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent", "sats"],
                "properties": {
                    "agent": {"type": "string", "description": "Agent name or ID"},
                    "sats": {"type": "integer", "minimum": 1, "description": "Amount to credit"},
                    "reason": {"type": "string", "description": "Optional ledger note"},
                },
            },
        ),
        types.Tool(
            name="conduit_attach_policy",
            description=(
                "Attach or replace the spending policy on an agent wallet. "
                "Any payment violating the policy is rejected before reaching Lightning. "
                "Requires an ADMIN-scope API key (setting policies is an admin action)."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent"],
                "properties": {
                    "agent": {"type": "string", "description": "Agent name or ID"},
                    "max_per_transaction": {"type": "integer", "minimum": 1},
                    "max_per_hour": {"type": "integer", "minimum": 1},
                    "max_per_day": {"type": "integer", "minimum": 1},
                    "allowlist": {"type": "array", "items": {"type": "string"}},
                    "blocklist": {"type": "array", "items": {"type": "string"}},
                    "require_memo": {"type": "boolean"},
                },
            },
        ),
        types.Tool(
            name="conduit_balance",
            description=(
                "Check the current balance of an agent wallet. "
                "Requires a READ-scope (or higher) API key."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent"],
                "properties": {"agent": {"type": "string"}},
            },
        ),
        types.Tool(
            name="conduit_pay",
            description=(
                "Send a Bitcoin Lightning payment from an agent wallet to a "
                "Lightning address (name@host) or a BOLT11 invoice. "
                "Requires a WRITE-scope (or higher) API key. "
                "Idempotent: a re-invoked call with the same agent, destination, "
                "amount and memo is deduplicated server-side and will NOT send "
                "twice, so a retried tool call is safe. Pass a distinct memo (or "
                "an explicit idempotency_key) for a genuinely separate payment."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent", "to", "sats"],
                "properties": {
                    "agent": {"type": "string"},
                    "to": {"type": "string"},
                    "sats": {"type": "integer", "minimum": 1},
                    "memo": {"type": "string"},
                    "idempotency_key": {
                        "type": "string",
                        "description": (
                            "Optional. If omitted, a stable key is derived from "
                            "(agent, to, sats, memo) so retries can't double-send."
                        ),
                    },
                },
            },
        ),
        types.Tool(
            name="conduit_receive",
            description=(
                "Generate a Lightning invoice for an agent wallet to receive funds. "
                "Requires a WRITE-scope (or higher) API key."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent", "amount"],
                "properties": {
                    "agent": {"type": "string"},
                    "amount": {"type": "integer", "minimum": 1},
                    "memo": {"type": "string"},
                    "expiry": {"type": "integer", "minimum": 60, "default": 3600},
                },
            },
        ),
        types.Tool(
            name="conduit_transactions",
            description=(
                "List recent transactions for an agent wallet. "
                "Requires a READ-scope (or higher) API key."
            ),
            inputSchema={
                "type": "object",
                "required": ["agent"],
                "properties": {
                    "agent": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                },
            },
        ),
        types.Tool(
            name="conduit_fees",
            description=(
                "Report the platform-fee revenue collected by this self-hosted "
                "Conduit operator — the per-payment fee (in sats) charged on top of "
                "each payment and kept on settle. Returns total_collected_sats, "
                "total_collected_btc, today_sats, and fees_by_day (most-recent-first). "
                "Requires an ADMIN-scope API key."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _pay_idempotency_key(agent_id: str, to: str, sats: int, memo: str | None) -> str:
    """Deterministic idempotency key for conduit_pay.

    An MCP tool call can be re-invoked when the model or transport retries after
    a dropped/slow response. Without a key, the SDK mints a fresh UUID4 per call,
    so a retry would send a SECOND real payment. Deriving the key from the
    payment's identity (agent + destination + amount + memo) makes a retry dedupe
    server-side, while a genuinely different payment (distinct memo) still goes
    through. Namespaced + versioned so it can't collide with caller keys.
    """
    raw = f"mcp:pay:v1:{agent_id}|{to}|{sats}|{memo or ''}"
    return "mcp-" + hashlib.sha256(raw.encode()).hexdigest()


def _ok(payload: dict[str, Any]) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, default=str, indent=2))]


def _err(e: Exception) -> list[types.TextContent]:
    body: dict[str, Any] = {"error": str(e)}
    if isinstance(e, ConduitError):
        body["code"] = e.code
        body["detail"] = e.detail
    if isinstance(e, PolicyViolation):
        body["policy_violation"] = True
    return [types.TextContent(type="text", text=json.dumps(body, default=str, indent=2))]


@server.call_tool()
async def call_tool(name: str, args: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "conduit_create_wallet":
            a = Agent.create(name=args["name"], daily_limit=int(args["daily_limit"]))
            return _ok({"id": a.id, "name": a.name, "active": a.active})

        if name == "conduit_credit":
            agent = _agent_for_name_or_id(args["agent"])
            adj = agent.credit(int(args["sats"]), reason=args.get("reason"))
            return _ok({
                "agent_id": adj.agent_id,
                "transaction_id": adj.transaction_id,
                "credited_sats": adj.delta_sats,
                "balance_sats": adj.balance_sats,
            })

        if name == "conduit_attach_policy":
            agent = _agent_for_name_or_id(args["agent"])
            agent.policy.attach(
                max_per_transaction=args.get("max_per_transaction"),
                max_per_hour=args.get("max_per_hour"),
                max_per_day=args.get("max_per_day"),
                allowlist=args.get("allowlist"),
                blocklist=args.get("blocklist"),
                require_memo=bool(args.get("require_memo", False)),
            )
            return _ok({"ok": True, "agent_id": agent.id})

        if name == "conduit_balance":
            agent = _agent_for_name_or_id(args["agent"])
            b = agent.balance
            return _ok({
                "agent_id": agent.id,
                "available_sats": b.available,
                "pending_sats": b.pending,
                "total_sats": b.total,
            })

        if name == "conduit_pay":
            agent = _agent_for_name_or_id(args["agent"])
            sats = int(args["sats"])
            memo = args.get("memo")
            # Make tool-call retries safe: derive a stable key unless the caller
            # gave one, so a re-invoked conduit_pay can't double-send.
            idem = args.get("idempotency_key") or _pay_idempotency_key(
                agent.id, args["to"], sats, memo
            )
            receipt = agent.pay(
                to=args["to"],
                sats=sats,
                memo=memo,
                idempotency_key=idem,
            )
            return _ok({
                "id": receipt.id,
                "status": receipt.status,
                "hash": receipt.hash,
                "amount_sats": receipt.amount_sats,
                "fee_sats": receipt.fee_sats,
                "platform_fee_sats": receipt.platform_fee_sats,
                "settled_in_ms": receipt.settled_in_ms,
            })

        if name == "conduit_receive":
            agent = _agent_for_name_or_id(args["agent"])
            inv = agent.receive(
                amount=int(args["amount"]),
                memo=args.get("memo"),
                expiry=int(args.get("expiry", 3600)),
            )
            return _ok({
                "id": inv.id,
                "payment_request": inv.payment_request,
                "payment_hash": inv.payment_hash,
                "amount_sats": inv.amount_sats,
                "expires_at": inv.expires_at.isoformat(),
            })

        if name == "conduit_transactions":
            agent = _agent_for_name_or_id(args["agent"])
            txns = agent.transactions(limit=int(args.get("limit", 25)))
            return _ok({
                "agent_id": agent.id,
                "transactions": [
                    {
                        "id": t.id,
                        "direction": t.direction,
                        "amount_sats": t.amount_sats,
                        "fee_sats": t.fee_sats,
                        "platform_fee_sats": t.platform_fee_sats,
                        "status": t.status,
                        "destination": t.destination,
                        "created_at": t.created_at.isoformat(),
                    }
                    for t in txns
                ],
            })

        if name == "conduit_fees":
            # No high-level SDK helper for fees; call the admin-scoped
            # GET /v1/fees endpoint directly via the low-level client, which
            # reuses the same CONDUIT_API_KEY / CONDUIT_API_URL configuration.
            data = default_client().get("/v1/fees")
            return _ok({
                "total_collected_sats": data["total_collected_sats"],
                "total_collected_btc": data["total_collected_btc"],
                "today_sats": data["today_sats"],
                "fees_by_day": data["fees_by_day"],
            })

        raise ConduitError(f"Unknown tool: {name}", code="UNKNOWN_TOOL")
    except Exception as e:  # noqa: BLE001
        return _err(e)


async def serve_stdio() -> None:
    if not os.environ.get("CONDUIT_API_KEY"):
        raise SystemExit(
            "CONDUIT_API_KEY not set. Get a key from your Conduit operator "
            "and export it before starting conduit-mcp."
        )
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="conduit",
                server_version="0.8.5",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(serve_stdio())
