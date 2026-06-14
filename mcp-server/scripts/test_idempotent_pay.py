"""Regression: conduit_pay must be idempotent — a re-invoked tool call (model or
transport retry) must NOT double-send. Drives the real MCP stdio protocol.

    CONDUIT_API_KEY=ck_test_dev_root CONDUIT_API_URL=http://127.0.0.1:8000 \
    python scripts/test_idempotent_pay.py
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
API_URL = os.environ.get("CONDUIT_API_URL", "http://127.0.0.1:8000")
PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
fails: list[str] = []


def body(r):
    return json.loads(r.content[0].text)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


async def main() -> int:
    params = StdioServerParameters(
        command="conduit-mcp",
        env={**os.environ, "CONDUIT_API_KEY": API_KEY, "CONDUIT_API_URL": API_URL},
    )
    print(f"\nProving conduit_pay idempotency against {API_URL}\n" + "-" * 56)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            sfx = uuid.uuid4().hex[:8]
            payer = body(await s.call_tool(
                "conduit_create_wallet", {"name": f"dup-payer-{sfx}", "daily_limit": 1_000_000}))["id"]
            vendor = body(await s.call_tool(
                "conduit_create_wallet", {"name": f"dup-vendor-{sfx}", "daily_limit": 1_000_000}))["id"]
            await s.call_tool("conduit_credit", {"agent": payer, "sats": 50_000})
            bal0 = body(await s.call_tool("conduit_balance", {"agent": payer}))["available_sats"]
            inv = body(await s.call_tool(
                "conduit_receive", {"agent": vendor, "amount": 1_000, "memo": "inv"}))["payment_request"]

            # The retry scenario: call conduit_pay TWICE with identical args.
            pay_args = {"agent": payer, "to": inv, "sats": 1_000, "memo": "news.fetch"}
            r1 = body(await s.call_tool("conduit_pay", dict(pay_args)))   # original
            r2 = body(await s.call_tool("conduit_pay", dict(pay_args)))   # retry
            bal1 = body(await s.call_tool("conduit_balance", {"agent": payer}))["available_sats"]

            print(f"  balance {bal0} -> {bal1} after two identical conduit_pay calls")
            print(f"  pay#1 tx={r1.get('id')}  pay#2 tx={r2.get('id')} (same => deduped)")

            debit = bal0 - bal1
            check("both calls returned a settled receipt",
                  r1.get("status") in ("settled", "succeeded") and r2.get("status") in ("settled", "succeeded"))
            check("retry returned the SAME transaction id (deduped, not re-sent)",
                  bool(r1.get("id")) and r1.get("id") == r2.get("id"), f"{r1.get('id')} == {r2.get('id')}")
            check("agent debited for ONLY ONE payment (~1006, not ~2012)",
                  1000 <= debit <= 1100, f"debit={debit}")

            txns = body(await s.call_tool("conduit_transactions", {"agent": payer, "limit": 20}))["transactions"]
            sends = [t for t in txns if t.get("direction") == "send"]
            check("exactly ONE outbound send recorded", len(sends) == 1, f"{len(sends)} send(s)")

            # Control: a genuinely distinct payment (different memo) still goes through.
            inv2 = body(await s.call_tool(
                "conduit_receive", {"agent": vendor, "amount": 1_000, "memo": "inv2"}))["payment_request"]
            r3 = body(await s.call_tool(
                "conduit_pay", {"agent": payer, "to": inv2, "sats": 1_000, "memo": "DIFFERENT"}))
            bal2 = body(await s.call_tool("conduit_balance", {"agent": payer}))["available_sats"]
            check("a distinct payment is NOT blocked (debits again)",
                  bal2 < bal1 and r3.get("id") != r1.get("id"), f"bal {bal1}->{bal2}")

    print("-" * 56)
    if fails:
        print(f"\n{FAIL}: {fails}\n")
        return 1
    print(f"\n{PASS}: conduit_pay retry does NOT double-send; distinct payments work.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
