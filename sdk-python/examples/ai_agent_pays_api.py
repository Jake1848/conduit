"""An AI agent autonomously pays over Lightning — the non-MCP demo.

This is the raw-SDK equivalent of the MCP demo in DEMO.md: it walks the full
agent lifecycle end to end so you can watch an autonomous agent earn the right
to spend and then get stopped by its own policy.

  1. provision a budgeted agent wallet              (operator, admin scope)
  2. fund it from the operator's node liquidity      (operator, admin scope)
  3. attach a spending policy                         (operator, admin scope)
  4. the agent pays an invoice within policy          -> settles
  5. the agent tries to overspend                     -> rejected BEFORE Lightning

The policy is enforced server-side. The agent (the LLM, in a real app) only ever
holds the agent_id and a write-scoped key — never the node, never the ability to
exceed the budget you set.

Run it against a local mock-LND instance (no real funds, settles instantly):

    docker compose -f docker-compose.dev.yml up --build   # from the repo root
    export CONDUIT_API_KEY=ck_test_dev_root
    export CONDUIT_API_URL=http://127.0.0.1:8000
    python examples/ai_agent_pays_api.py

Against a real instance, point `to=` at an EXTERNAL Lightning invoice/address —
a node can't pay an invoice it issued itself.
"""

import os

from conduit import Agent, ConduitError, PolicyViolation

DAILY_LIMIT = 50_000
PER_TX_LIMIT = 10_000


def main() -> None:
    # 1. Provision a budgeted wallet for the agent. The daily limit is a hard
    #    ceiling the policy engine enforces — the agent can't exceed it in 24h.
    agent = Agent.create(name="market-analyst", daily_limit=DAILY_LIMIT)
    print(f"created wallet {agent.id} (daily limit {DAILY_LIMIT:,} sats)")

    # 2. Fund it from the operator's node liquidity.
    agent.credit(20_000, reason="research budget")
    print(f"funded     balance = {agent.balance.available:,} sats")

    # 3. Attach a spending policy: cap per-transaction + per-day, require a memo.
    agent.policy.attach(
        max_per_transaction=PER_TX_LIMIT,
        max_per_day=DAILY_LIMIT,
        require_memo=True,
    )
    print(f"policy     <= {PER_TX_LIMIT:,}/tx, <= {DAILY_LIMIT:,}/day, memo required")

    # A vendor the agent will pay. For a self-contained demo we mint the invoice
    # on a second wallet; against a real node use an external invoice/address.
    vendor = Agent.create(name="data-vendor", daily_limit=DAILY_LIMIT)
    invoice = vendor.receive(amount=1_500, memo="news.fetch?ticker=AAPL")

    # 4. The agent pays within policy -> settles over Lightning.
    try:
        receipt = agent.pay(to=invoice.payment_request, sats=1_500, memo="news.fetch")
        print(
            f"\nPAID       {receipt.amount_sats:,} sats  "
            f"status={receipt.status}  fee={receipt.fee_sats}  "
            f"platform_fee={receipt.platform_fee_sats}  in {receipt.settled_in_ms} ms"
        )
    except (PolicyViolation, ConduitError) as e:
        print(f"unexpected denial: {getattr(e, 'code', '')} — {e}")
        return

    # 5. The agent tries to overspend -> the policy stops it before Lightning.
    over = vendor.receive(amount=PER_TX_LIMIT * 2, memo="too big")
    try:
        agent.pay(to=over.payment_request, sats=PER_TX_LIMIT * 2, memo="overspend")
        print("BUG: over-limit payment was NOT blocked")
    except PolicyViolation as e:
        print(f"BLOCKED    over-limit payment rejected: {e.code} — {e.message}")

    print(f"\nremaining  balance = {agent.balance.available:,} sats")


if __name__ == "__main__":
    # Sensible defaults so `python examples/ai_agent_pays_api.py` just works
    # against a local dev instance; override with your own env.
    os.environ.setdefault("CONDUIT_API_KEY", "ck_test_dev_root")
    os.environ.setdefault("CONDUIT_API_URL", "http://127.0.0.1:8000")
    main()
