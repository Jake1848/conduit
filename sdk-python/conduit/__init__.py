"""Conduit — Bitcoin Lightning payments for autonomous AI agents.

    from conduit import Agent, Policy

    agent = Agent.create(name="compute-router-7", daily_limit=50_000)
    agent.policy.attach(max_per_hour=10_000, allowlist=["02beef..."])
    receipt = agent.pay(to="compute-node-7@lnd.conduit.energy", sats=150, memo="dataset")
    print(receipt.hash, receipt.settled_in_ms)
"""

from .agent import Agent
from .client import Conduit
from .errors import (
    AgentNotFound,
    AuthenticationError,
    ConduitError,
    InsufficientBalance,
    PaymentFailed,
    PolicyViolation,
    RateLimited,
)
from .invoice import Invoice
from .payment import Receipt
from .policy import Policy
from .transaction import Transaction

# Module-level config — populated from CONDUIT_API_KEY / CONDUIT_API_URL env vars
# lazily on first use. See client.py.
api_key: str | None = None
base_url: str | None = None

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "Conduit",
    "Policy",
    "Receipt",
    "Invoice",
    "Transaction",
    "ConduitError",
    "AuthenticationError",
    "PolicyViolation",
    "InsufficientBalance",
    "PaymentFailed",
    "AgentNotFound",
    "RateLimited",
    "api_key",
    "base_url",
    "__version__",
]
