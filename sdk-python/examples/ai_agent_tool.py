"""Expose Conduit as a payment TOOL for an AI agent.

This is THE integration pattern, identical across frameworks (LangChain `@tool`,
CrewAI, OpenAI / Anthropic function-calling): you define a plain function the
model can call, backed by a ConduitClient. The operator provisions and funds the
agent once; the model only ever gets the agent_id and the tool — never a key to
the node, and never the ability to exceed the budget/policy you set.

Run (uses the live regtest API by default):

    python examples/ai_agent_tool.py

    # or point at your own instance:
    CONDUIT_API_URL=https://api-mainnet.conduit.energy \
    CONDUIT_API_KEY=ck_live_... python examples/ai_agent_tool.py

LangChain users: wrap `pay_lightning` directly —

    from langchain_core.tools import tool
    pay = tool(pay_lightning)        # now a LangChain Tool the agent can call
"""

import os

from conduit import ConduitClient

client = ConduitClient(
    base_url=os.environ.get("CONDUIT_API_URL", "https://api-test.conduit.energy"),
    api_key=os.environ.get("CONDUIT_API_KEY", "ck_test_regtest_root_key"),
)

# The operator provisions + funds the agent ONCE, out of band. The model never
# does this — it only receives AGENT_ID and the tools below.
_agent = client.create_agent("ai-tool-demo")
client.credit_agent(_agent.id, sats=5_000, reason="agent budget")
AGENT_ID = _agent.id


def pay_lightning(dest_pubkey: str, amount_sats: int, memo: str = "") -> str:
    """Send `amount_sats` over Bitcoin Lightning to a node pubkey (keysend).

    This is the function the LLM calls. Returns a short, model-readable summary.
    """
    try:
        receipt = client.send_payment(
            AGENT_ID, dest_pubkey=dest_pubkey, sats=amount_sats, memo=memo
        )
    except Exception as e:  # noqa: BLE001 - surface a readable message to the model
        return f"Payment failed: {e}"
    remaining = client.get_balance(AGENT_ID).available
    return (
        f"Paid {receipt.amount_sats} sats (status={receipt.status}, "
        f"platform fee {receipt.platform_fee_sats} sats, hash {(receipt.hash or '')[:12]}). "
        f"Remaining budget: {remaining} sats."
    )


def check_budget() -> str:
    """Return the agent's spendable balance in sats."""
    return f"{client.get_balance(AGENT_ID).available} sats available"


if __name__ == "__main__":
    # Simulate the loop your agent framework runs: the model inspects state, then
    # emits a tool call. Here we call the tools directly to prove they work.
    print("AGENT  > what's my budget?")
    print("BUDGET >", check_budget())

    print("\nAGENT  > pay 250 sats to the data provider")
    print(
        "TOOL   >",
        pay_lightning(
            dest_pubkey="02001bbe134990961c76e0d31386b3db6253f299da17bc53ffde2f9ac10214c0c0",
            amount_sats=250,
            memo="agent-initiated payment",
        ),
    )

    print("\nAGENT  > budget now?")
    print("BUDGET >", check_budget())
    client.close()
