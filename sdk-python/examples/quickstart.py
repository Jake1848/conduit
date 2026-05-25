"""Quickstart — matches the snippet on https://conduit.energy

Run against a local Core API (`docker compose up` from the repo root):

    export CONDUIT_API_KEY=ck_test_dev_root
    export CONDUIT_API_URL=http://127.0.0.1:8000
    python examples/quickstart.py
"""

from conduit import Agent

agent = Agent.create(
    name="compute-router-7",
    daily_limit=50_000,  # sats
)

agent.policy.attach(
    max_per_hour=10_000,
    allowlist=["02beef" + "00" * 31],  # destination pubkeys
)

receipt = agent.keysend(
    dest_pubkey="02beef" + "00" * 31,
    sats=150,
    memo="dataset query",
)

print(f"hash         = {receipt.hash}")
print(f"settled_in   = {receipt.settled_in_ms} ms")
print(f"fee          = {receipt.fee_sats} sats")
print(f"status       = {receipt.status}")
print(f"balance      = {agent.balance}")
