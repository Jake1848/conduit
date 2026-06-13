"""Conduit — Bitcoin Lightning payments for autonomous AI agents.

    from conduit import Agent, Policy

    agent = Agent.create(name="compute-router-7", daily_limit=50_000)
    agent.policy.attach(max_per_hour=10_000, allowlist=["02beef..."])
    receipt = agent.pay(to="compute-node-7@lnd.conduit.energy", sats=150, memo="dataset")
    print(receipt.hash, receipt.settled_in_ms)
"""

from .agent import Agent, Balance, LedgerAdjustment
from .client import Conduit, default_client, set_default_client
from .conduit_client import ConduitClient
from .errors import (
    AgentNotFound,
    AuthenticationError,
    ConduitError,
    InsufficientBalance,
    PaymentFailed,
    PermissionDenied,
    PolicyViolation,
    RateLimited,
    WebhookVerificationError,
)
from .invoice import Invoice
from .payment import Receipt
from .policy import Policy
from .transaction import Transaction
from .webhook import parse_webhook, verify_webhook

# Module-level config — populated from CONDUIT_API_KEY / CONDUIT_API_URL env vars
# lazily on first use. See client.py.
api_key: str | None = None
base_url: str | None = None

__version__ = "0.8.3"

__all__ = [
    "Agent",
    "ConduitClient",
    "Conduit",
    "Balance",
    "LedgerAdjustment",
    "default_client",
    "set_default_client",
    "Policy",
    "Receipt",
    "Invoice",
    "Transaction",
    "ConduitError",
    "AuthenticationError",
    "PermissionDenied",
    "PolicyViolation",
    "InsufficientBalance",
    "PaymentFailed",
    "AgentNotFound",
    "RateLimited",
    "WebhookVerificationError",
    "verify_webhook",
    "parse_webhook",
    "api_key",
    "base_url",
    "__version__",
]
