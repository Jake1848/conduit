from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .payment import _parse_dt


@dataclass
class Transaction:
    id: str
    agent_id: str
    direction: str  # 'send' | 'receive'
    amount_sats: int
    fee_sats: int
    destination: str | None
    payment_hash: str | None
    status: str
    memo: str | None
    settled_at: datetime | None
    latency_ms: int | None
    created_at: datetime

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Transaction":
        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            direction=data["direction"],
            amount_sats=int(data["amount_sats"]),
            fee_sats=int(data.get("fee_sats", 0)),
            destination=data.get("destination"),
            payment_hash=data.get("payment_hash"),
            status=data["status"],
            memo=data.get("memo"),
            settled_at=_parse_dt(data["settled_at"]) if data.get("settled_at") else None,
            latency_ms=data.get("latency_ms"),
            created_at=_parse_dt(data["created_at"]),
        )
