"""An AI agent pays a metered API per request.

Useful pattern: an LLM has a daily budget; each tool call deducts a small
fee. Conduit enforces the budget — the agent can't go over even if its
planning loop tries to.
"""

import os

from conduit import Agent, PolicyViolation

agent = Agent.create(name="market-analyst", daily_limit=10_000)
agent.policy.attach(
    max_per_transaction=200,         # any single call ≤ 200 sats
    max_per_hour=2_000,              # ≤ 2000 sats/hour
    allowlist=[os.environ.get("VENDOR_LN_ADDRESS", "vendor@example.com")],
    require_memo=True,
)

# Each tool call:
try:
    receipt = agent.pay(
        to=os.environ["VENDOR_LN_ADDRESS"],
        sats=80,
        memo="news.fetch?ticker=AAPL",
    )
    print("paid:", receipt.hash, "in", receipt.settled_in_ms, "ms")
except PolicyViolation as e:
    print("denied by policy:", e.code, "—", e.message)
