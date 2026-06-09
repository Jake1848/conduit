"""Client-centric facade over the Conduit API.

The `Agent` active-record API (`Agent.create(...)`, `agent.pay(...)`) is the
idiomatic way to use this SDK, but many developers expect a single client object
with `create_agent` / `credit_agent` / `send_payment` style methods. `ConduitClient`
provides exactly that — a thin, explicit wrapper over the same HTTP client.

    from conduit import ConduitClient

    client = ConduitClient(base_url="http://127.0.0.1:8002", api_key="ck_test_...")
    agent = client.create_agent("sdk-test-agent")
    client.credit_agent(agent.id, sats=10_000, reason="top-up")
    receipt = client.send_payment(agent.id, dest_pubkey="02ab...", sats=500)
    print(receipt.status, receipt.platform_fee_sats)
    print(client.get_balance(agent.id).available)
"""

from __future__ import annotations

from typing import Any

from .agent import Agent, Balance, LedgerAdjustment, _new_idempotency_key
from .client import Conduit
from .invoice import Invoice
from .payment import Receipt
from .transaction import Transaction


class ConduitClient:
    """A high-level, client-centric handle on a Conduit instance.

    Wraps the low-level :class:`Conduit` HTTP client (retries + idempotency) and
    exposes the common operations as plain methods. Use it as a context manager
    to close the underlying connection pool, or call :meth:`close` yourself.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._client = Conduit(api_key=api_key, base_url=base_url, **kwargs)

    @property
    def http(self) -> Conduit:
        """The underlying low-level client, for endpoints not wrapped here."""
        return self._client

    # ---- agents ----

    def create_agent(
        self,
        name: str,
        *,
        daily_limit: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Agent:
        return Agent.create(
            name, daily_limit=daily_limit, metadata=metadata, client=self._client
        )

    def get_agent(self, agent_id: str) -> Agent:
        return Agent.get(agent_id, client=self._client)

    def list_agents(self) -> list[Agent]:
        return Agent.list(client=self._client)

    def deactivate_agent(self, agent_id: str) -> None:
        self._client.delete(f"/v1/agents/{agent_id}")

    # ---- funding (operator / admin scope) ----

    def credit_agent(
        self,
        agent_id: str,
        sats: int,
        *,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerAdjustment:
        payload: dict[str, Any] = {"sats": sats}
        if reason is not None:
            payload["reason"] = reason
        if metadata is not None:
            payload["metadata"] = metadata
        data = self._client.post(f"/v1/agents/{agent_id}/credit", json=payload)
        return LedgerAdjustment.from_api(data)

    def debit_agent(
        self,
        agent_id: str,
        sats: int,
        *,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LedgerAdjustment:
        payload: dict[str, Any] = {"sats": sats}
        if reason is not None:
            payload["reason"] = reason
        if metadata is not None:
            payload["metadata"] = metadata
        data = self._client.post(f"/v1/agents/{agent_id}/debit", json=payload)
        return LedgerAdjustment.from_api(data)

    # ---- balance / ledger ----

    def get_balance(self, agent_id: str) -> Balance:
        data = self._client.get(f"/v1/agents/{agent_id}/balance")
        return Balance(
            available=int(data["available_sats"]),
            pending=int(data["pending_sats"]),
            total=int(data["total_sats"]),
        )

    def list_transactions(
        self, agent_id: str, *, limit: int = 50, direction: str | None = None
    ) -> list[Transaction]:
        params: dict[str, Any] = {"limit": limit}
        if direction:
            params["direction"] = direction
        data = self._client.get(f"/v1/agents/{agent_id}/transactions", params=params)
        return [Transaction.from_api(item) for item in data.get("data", [])]

    # ---- payments ----

    def send_payment(
        self,
        agent_id: str,
        *,
        dest_pubkey: str | None = None,
        payment_request: str | None = None,
        sats: int | None = None,
        memo: str | None = None,
        idempotency_key: str | None = None,
    ) -> Receipt:
        """Send a payment: keysend (`dest_pubkey` + `sats`) or pay a BOLT11
        invoice (`payment_request`). An Idempotency-Key is always sent."""
        if not dest_pubkey and not payment_request:
            raise ValueError("send_payment requires dest_pubkey or payment_request")
        payload: dict[str, Any] = {"agent_id": agent_id, "memo": memo}
        if dest_pubkey is not None:
            payload["dest_pubkey"] = dest_pubkey
        if payment_request is not None:
            payload["payment_request"] = payment_request
        if sats is not None:
            payload["sats"] = sats
        data = self._client.post(
            "/v1/payments/send",
            json=payload,
            idempotency_key=idempotency_key or _new_idempotency_key(),
        )
        return Receipt.from_api(data)

    def pay(
        self,
        agent_id: str,
        *,
        to: str,
        sats: int,
        memo: str | None = None,
        idempotency_key: str | None = None,
    ) -> Receipt:
        """Pay a Lightning address (`name@host`) or a BOLT11 invoice string."""
        data = self._client.post(
            "/v1/payments/pay",
            json={"agent_id": agent_id, "to": to, "sats": sats, "memo": memo},
            idempotency_key=idempotency_key or _new_idempotency_key(),
        )
        return Receipt.from_api(data)

    def create_invoice(
        self,
        agent_id: str,
        *,
        amount: int,
        memo: str | None = None,
        expiry: int = 3600,
    ) -> Invoice:
        data = self._client.post(
            "/v1/invoices",
            json={"agent_id": agent_id, "amount": amount, "memo": memo, "expiry": expiry},
        )
        return Invoice.from_api(data)

    # ---- operator revenue / metrics ----

    def get_fees(self) -> dict[str, Any]:
        """Platform-fee revenue collected by this self-hosted operator (admin)."""
        return self._client.get("/v1/fees")

    def get_metrics(self) -> dict[str, Any]:
        return self._client.get("/v1/metrics")

    # ---- lifecycle ----

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConduitClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
