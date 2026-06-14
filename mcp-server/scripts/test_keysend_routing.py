"""Regression: conduit_pay routes a raw node pubkey to keysend, so a policy-
limited payment to a pubkey reaches the POLICY engine (not input validation) —
while a malformed destination is still rejected at the edge before any debit.

    CONDUIT_API_KEY=ck_test_regtest_root_key CONDUIT_API_URL=http://127.0.0.1:8000 \
    python scripts/test_keysend_routing.py
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
# A reachable keysend destination. Defaults to the public regtest peer.
PEER = os.environ.get("CONDUIT_PEER_PUBKEY",
                      "02001bbe134990961c76e0d31386b3db6253f299da17bc53ffde2f9ac10214c0c0")
PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
fails: list[str] = []


def body(r):
    return json.loads(r.content[0].text)


def ck(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


async def main() -> int:
    params = StdioServerParameters(
        command="conduit-mcp",
        env={**os.environ, "CONDUIT_API_KEY": API_KEY, "CONDUIT_API_URL": API_URL},
    )
    print(f"\nconduit_pay keysend routing against {API_URL}\n" + "-" * 56)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            sfx = uuid.uuid4().hex[:6]
            payer = body(await s.call_tool(
                "conduit_create_wallet", {"name": f"ks-{sfx}", "daily_limit": 10_000_000}))["id"]
            await s.call_tool("conduit_credit", {"agent": payer, "sats": 50_000})
            await s.call_tool("conduit_attach_policy", {"agent": payer, "max_per_transaction": 1_000})

            async def bal():
                return body(await s.call_tool("conduit_balance", {"agent": payer}))["available_sats"]

            b0 = await bal()
            # Raw pubkey OVER the per-tx limit -> must be rejected by the POLICY engine.
            over = body(await s.call_tool(
                "conduit_pay", {"agent": payer, "to": PEER, "sats": 2_000, "memo": "over"}))
            b1 = await bal()
            ck("raw pubkey reaches the policy engine (PER_TRANSACTION_LIMIT_EXCEEDED)",
               (over.get("code") or "").upper() == "PER_TRANSACTION_LIMIT_EXCEEDED" or bool(over.get("policy_violation")),
               f"code={over.get('code')}")
            ck("not rejected as 'Unsupported destination format' anymore",
               "unsupported destination" not in (over.get("error") or "").lower())
            ck("over-limit pay moved no money", b1 == b0, f"{b0} -> {b1}")

            # Raw pubkey WITHIN the limit -> keysend settles.
            ok = body(await s.call_tool(
                "conduit_pay", {"agent": payer, "to": PEER, "sats": 500, "memo": "within"}))
            b2 = await bal()
            ck("valid pubkey within policy -> keysend settles via MCP",
               ok.get("status") in ("settled", "succeeded"), f"status={ok.get('status')}")
            ck("keysend debited once (~500+fee)", 500 <= (b1 - b2) <= 600, f"debit={b1 - b2}")

            # Malformed destination -> still INVALID_INPUT before any debit.
            bad = body(await s.call_tool(
                "conduit_pay", {"agent": payer, "to": "deadbeef", "sats": 100, "memo": "bad"}))
            b3 = await bal()
            ck("malformed destination rejected at the edge (no settle)",
               bad.get("status") not in ("settled", "succeeded") and bool(bad.get("error")),
               f"code={bad.get('code')}")
            ck("malformed destination stranded no funds", b3 == b2, f"{b2} -> {b3}")

    print("-" * 56)
    if fails:
        print(f"\n{FAIL}: {fails}\n")
        return 1
    print(f"\n{PASS}: pubkey->keysend reaches policy; malformed still rejected pre-debit.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
