from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .client import Conduit, default_client

if TYPE_CHECKING:
    from .agent import Agent


@dataclass
class _PolicyState:
    max_per_transaction: int | None = None
    max_per_hour: int | None = None
    max_per_day: int | None = None
    max_per_minute_count: int = 60
    allowlist: list[str] | None = None
    blocklist: list[str] | None = None
    require_memo: bool = False
    enabled: bool = True


class Policy:
    """Spending policy bound to an Agent.

    Accessed via `agent.policy.attach(...)` matching the website snippet:

        agent.policy.attach(
            max_per_hour=10_000,
            allowlist=["02beef...", "02dead..."],
        )
    """

    def __init__(self, agent: "Agent", client: Conduit | None = None) -> None:
        self._agent = agent
        self._client = client or default_client()
        self._state = _PolicyState()

    def attach(
        self,
        *,
        max_per_transaction: int | None = None,
        max_per_hour: int | None = None,
        max_per_day: int | None = None,
        max_per_minute_count: int = 60,
        allowlist: list[str] | None = None,
        blocklist: list[str] | None = None,
        require_memo: bool = False,
        enabled: bool = True,
    ) -> "Policy":
        payload: dict[str, Any] = {
            "max_per_transaction": max_per_transaction,
            "max_per_hour": max_per_hour,
            "max_per_day": max_per_day,
            "max_per_minute_count": max_per_minute_count,
            "allowlist": list(allowlist) if allowlist else None,
            "blocklist": list(blocklist) if blocklist else None,
            "require_memo": require_memo,
            "enabled": enabled,
        }
        data = self._client.post(f"/v1/agents/{self._agent.id}/policy", json=payload)
        self._hydrate(data)
        return self

    def fetch(self) -> "Policy":
        data = self._client.get(f"/v1/agents/{self._agent.id}/policy")
        self._hydrate(data)
        return self

    def update(self, **kwargs: Any) -> "Policy":
        return self.attach(**kwargs)

    def remove(self) -> None:
        self._client.delete(f"/v1/agents/{self._agent.id}/policy")
        self._state = _PolicyState()

    def _hydrate(self, data: dict[str, Any]) -> None:
        self._state = _PolicyState(
            max_per_transaction=data.get("max_per_transaction"),
            max_per_hour=data.get("max_per_hour"),
            max_per_day=data.get("max_per_day"),
            max_per_minute_count=data.get("max_per_minute_count", 60),
            allowlist=data.get("allowlist") or None,
            blocklist=data.get("blocklist") or None,
            require_memo=bool(data.get("require_memo")),
            enabled=bool(data.get("enabled", True)),
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._state, name)
