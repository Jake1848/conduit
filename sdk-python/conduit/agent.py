from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .client import Conduit, default_client
from .invoice import Invoice
from .payment import Receipt, _parse_dt
from .policy import Policy
from .transaction import Transaction


def _new_idempotency_key() -> str:
    return str(uuid.uuid4())


@dataclass
class Balance:
    available: int
    pending: int
    total: int


class Agent:
    """An autonomous wallet with optional spending policy.

    Mirrors the website code panel:

        agent = Agent.create(name="compute-router-7", daily_limit=50_000)
        agent.policy.attach(max_per_hour=10_000, allowlist=["02beef..."])
        receipt = agent.pay(to="compute-node-7@lnd.conduit.energy",
                            sats=150, memo="dataset query")
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
        pubkey: str | None,
        active: bool,
        created_at: datetime,
        client: Conduit | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.pubkey = pubkey
        self.active = active
        self.created_at = created_at
        self._client = client or default_client()
        self.policy = Policy(self, client=self._client)

    # --- factory methods ---

    @classmethod
    def create(
        cls,
        name: str,
        daily_limit: int | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        client: Conduit | None = None,
    ) -> "Agent":
        c = client or default_client()
        payload: dict[str, Any] = {"name": name}
        if daily_limit is not None:
            payload["daily_limit"] = daily_limit
        if metadata is not None:
            payload["metadata"] = metadata
        data = c.post("/v1/agents", json=payload)
        return cls._from_api(data, client=c)

    @classmethod
    def get(cls, agent_id: str, *, client: Conduit | None = None) -> "Agent":
        c = client or default_client()
        data = c.get(f"/v1/agents/{agent_id}")
        return cls._from_api(data, client=c)

    @classmethod
    def list(cls, *, client: Conduit | None = None) -> list["Agent"]:
        c = client or default_client()
        data = c.get("/v1/agents")
        return [cls._from_api(item, client=c) for item in data.get("data", [])]

    @classmethod
    def _from_api(cls, data: dict[str, Any], client: Conduit) -> "Agent":
        return cls(
            id=data["id"],
            name=data["name"],
            pubkey=data.get("pubkey"),
            active=bool(data.get("active", True)),
            created_at=_parse_dt(data["created_at"]),
            client=client,
        )

    # --- actions ---

    def pay(
        self,
        *,
        to: str,
        sats: int,
        memo: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Receipt:
        """Pay a Lightning address (`name@host`) or a BOLT11 invoice.

        An `Idempotency-Key` is sent automatically (a fresh UUID4 if you don't
        provide one) so an automatic retry can never double-pay. Pass an
        explicit `idempotency_key` to make a manual retry idempotent too.
        """
        data = self._client.post(
            "/v1/payments/pay",
            json={
                "agent_id": self.id,
                "to": to,
                "sats": sats,
                "memo": memo,
                "metadata": metadata,
            },
            idempotency_key=idempotency_key or _new_idempotency_key(),
        )
        return Receipt.from_api(data)

    def send_invoice(
        self,
        payment_request: str,
        *,
        sats: int | None = None,
        memo: str | None = None,
        idempotency_key: str | None = None,
    ) -> Receipt:
        """Pay a BOLT11 invoice (or zero-amount invoice with explicit sats)."""
        data = self._client.post(
            "/v1/payments/send",
            json={
                "agent_id": self.id,
                "payment_request": payment_request,
                "sats": sats,
                "memo": memo,
            },
            idempotency_key=idempotency_key or _new_idempotency_key(),
        )
        return Receipt.from_api(data)

    def keysend(
        self,
        dest_pubkey: str,
        sats: int,
        *,
        memo: str | None = None,
        idempotency_key: str | None = None,
    ) -> Receipt:
        data = self._client.post(
            "/v1/payments/send",
            json={
                "agent_id": self.id,
                "dest_pubkey": dest_pubkey,
                "sats": sats,
                "memo": memo,
            },
            idempotency_key=idempotency_key or _new_idempotency_key(),
        )
        return Receipt.from_api(data)

    def receive(
        self, amount: int, *, memo: str | None = None, expiry: int = 3600
    ) -> Invoice:
        """Create a Lightning invoice that other agents/services can pay."""
        data = self._client.post(
            "/v1/invoices",
            json={"agent_id": self.id, "amount": amount, "memo": memo, "expiry": expiry},
        )
        return Invoice.from_api(data)

    @property
    def balance(self) -> Balance:
        data = self._client.get(f"/v1/agents/{self.id}/balance")
        return Balance(
            available=int(data["available_sats"]),
            pending=int(data["pending_sats"]),
            total=int(data["total_sats"]),
        )

    def transactions(self, *, limit: int = 50, direction: str | None = None) -> list[Transaction]:
        params: dict[str, Any] = {"limit": limit}
        if direction:
            params["direction"] = direction
        data = self._client.get(f"/v1/agents/{self.id}/transactions", params=params)
        return [Transaction.from_api(item) for item in data.get("data", [])]

    def deactivate(self) -> None:
        self._client.delete(f"/v1/agents/{self.id}")
        self.active = False

    def __repr__(self) -> str:
        return f"<Agent id={self.id!r} name={self.name!r} active={self.active}>"
