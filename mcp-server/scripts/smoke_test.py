"""End-to-end smoke test for conduit-mcp: drives all 8 tools through the real
MCP stdio protocol against a running Conduit instance.

Spawns `conduit-mcp` as a subprocess (exactly as Claude Desktop would), speaks
MCP over stdio, and exercises a full agent lifecycle: create wallet -> credit ->
attach policy -> balance -> receive -> pay -> transactions -> fees. It also fires
one over-limit payment to prove the policy engine rejects it server-side.

Usage (point at any Conduit instance; defaults to a local dev server):
    CONDUIT_API_KEY=ck_test_dev_root \
    CONDUIT_API_URL=http://127.0.0.1:8099 \
    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

API_KEY = os.environ.get("CONDUIT_API_KEY", "ck_test_dev_root")
API_URL = os.environ.get("CONDUIT_API_URL", "http://127.0.0.1:8099")

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
failures: list[str] = []


def _body(result) -> dict:
    text = result.content[0].text if result.content else "{}"
    return json.loads(text)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


async def main() -> int:
    params = StdioServerParameters(
        command="conduit-mcp",
        env={**os.environ, "CONDUIT_API_KEY": API_KEY, "CONDUIT_API_URL": API_URL},
    )
    print(f"\nDriving conduit-mcp against {API_URL}\n" + "-" * 56)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 0. list_tools — expect exactly the 8 documented tools.
            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            expected = sorted([
                "conduit_create_wallet", "conduit_credit", "conduit_attach_policy",
                "conduit_balance", "conduit_pay", "conduit_receive",
                "conduit_transactions", "conduit_fees",
            ])
            check("list_tools returns the 8 tools", names == expected, str(names))

            # 1. create_wallet (payer + payee) — unique names so the test is re-runnable
            sfx = uuid.uuid4().hex[:8]
            r = _body(await session.call_tool(
                "conduit_create_wallet", {"name": f"mcp-demo-payer-{sfx}", "daily_limit": 100_000}))
            payer = r.get("id", "")
            check("conduit_create_wallet (payer)", payer.startswith("agt_"), payer or str(r))

            r = _body(await session.call_tool(
                "conduit_create_wallet", {"name": f"mcp-demo-payee-{sfx}", "daily_limit": 100_000}))
            payee = r.get("id", "")
            check("conduit_create_wallet (payee)", payee.startswith("agt_"), payee or str(r))

            # 2. credit the payer
            r = _body(await session.call_tool(
                "conduit_credit", {"agent": payer, "sats": 50_000, "reason": "demo float"}))
            check("conduit_credit funds the wallet", r.get("balance_sats") == 50_000,
                  f"balance={r.get('balance_sats')}")

            # 3. attach a spending policy
            r = _body(await session.call_tool("conduit_attach_policy", {
                "agent": payer, "max_per_transaction": 10_000,
                "max_per_day": 50_000, "require_memo": True}))
            check("conduit_attach_policy", r.get("ok") is True, str(r))

            # 4. balance reads 50_000
            r = _body(await session.call_tool("conduit_balance", {"agent": payer}))
            check("conduit_balance", r.get("available_sats") == 50_000,
                  f"available={r.get('available_sats')}")

            # 5. receive — payee mints an invoice
            r = _body(await session.call_tool(
                "conduit_receive", {"agent": payee, "amount": 1_000, "memo": "invoice for demo"}))
            invoice = r.get("payment_request", "")
            check("conduit_receive mints a BOLT11", invoice.startswith("ln"), invoice[:24] + "…")

            # 6. pay — payer settles the invoice (within policy)
            r = _body(await session.call_tool(
                "conduit_pay", {"agent": payer, "to": invoice, "sats": 1_000, "memo": "news.fetch"}))
            paid_ok = r.get("status") in ("settled", "succeeded", "SUCCEEDED")
            check("conduit_pay settles within policy", paid_ok,
                  f"status={r.get('status')} fee={r.get('fee_sats')} "
                  f"platform_fee={r.get('platform_fee_sats')}")

            # 6b. policy enforcement — an over-limit payment must be REJECTED
            # server-side. Mint a 20k-sat invoice (> the 10k per-tx cap) and pay it.
            big = _body(await session.call_tool(
                "conduit_receive", {"agent": payee, "amount": 20_000, "memo": "over the cap"}))
            r = _body(await session.call_tool(
                "conduit_pay", {"agent": payer, "to": big.get("payment_request", ""),
                                "sats": 20_000, "memo": "too big"}))
            rejected = bool(r.get("policy_violation")) or (
                r.get("code") or "").upper() in (
                "POLICY_VIOLATION", "MAX_PER_TRANSACTION_EXCEEDED", "MAX_PER_TRANSACTION")
            check("conduit_pay over-limit is rejected by policy", rejected,
                  f"code={r.get('code')} err={r.get('error')}")

            # 7. transactions — the settled payment shows up (direction='send')
            r = _body(await session.call_tool("conduit_transactions", {"agent": payer, "limit": 10}))
            txns = r.get("transactions", [])
            has_send = any(t.get("direction") == "send" for t in txns)
            check("conduit_transactions lists the payment", has_send,
                  f"{len(txns)} txns, directions={[t.get('direction') for t in txns]}")

            # 8. fees — operator platform-fee revenue (admin)
            r = _body(await session.call_tool("conduit_fees", {}))
            has_fee_fields = "total_collected_sats" in r and "today_sats" in r
            check("conduit_fees reports revenue", has_fee_fields,
                  f"total={r.get('total_collected_sats')} today={r.get('today_sats')}")

    print("-" * 56)
    if failures:
        print(f"\n{FAIL}: {len(failures)} check(s) failed: {failures}\n")
        return 1
    print(f"\n{PASS}: all 8 tools + policy enforcement verified end-to-end.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
