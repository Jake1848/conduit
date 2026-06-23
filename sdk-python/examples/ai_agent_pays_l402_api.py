"""An AI agent pays for an L402-gated API, end to end.

The agent hits a paywalled endpoint, Conduit auto-pays the Lightning toll from
the agent's policy-capped wallet, and the agent gets the response body back —
no Lightning keys, no manual invoice handling.

Run against the mock-LND dev container:

    docker compose -f docker-compose.dev.yml up --build   # in the repo root
    export CONDUIT_API_KEY=ck_test_dev_root
    export CONDUIT_API_URL=http://localhost:8000
    python examples/ai_agent_pays_l402_api.py https://some-l402-api.example/resource
"""

import sys

from conduit import Agent
from conduit.l402 import L402Config
from conduit.l402_fetch import L402Client


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://api.example.com/paid-resource"

    # A budgeted agent. The cap below is a second, client-side guard on top of
    # the agent's server-side spending policy.
    agent = Agent.create(name="l402-research-bot", daily_limit=50_000)
    agent.credit(20_000, reason="L402 browsing budget")

    config = L402Config(
        max_auto_pay_sats=2_000,           # refuse any single toll over 2k sats
        denied_domains=["sketchy.example"],  # never pay these hosts
    )

    # A reused client so a service-wide token is bought once and reused.
    with L402Client(agent, config=config) as http:
        result = http.fetch(url, sats=210)

        print(f"status      : {result.status}")
        print(f"paid (sats) : {result.paid_sats}")
        print(f"from cache  : {result.cached}")
        print(f"body        : {result.body[:280]}")


if __name__ == "__main__":
    main()
