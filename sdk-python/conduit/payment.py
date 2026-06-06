from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Receipt:
    """The result of a settled (or attempted) payment.

    Matches the website snippet:
        receipt = agent.pay(...)
        print(receipt.hash, receipt.settled_in_ms)
    """

    id: str
    agent_id: str
    status: str  # 'pending' | 'settled' | 'failed'
    hash: str | None
    amount_sats: int
    fee_sats: int  # LND routing fee
    platform_fee_sats: int  # Conduit operator platform fee (revenue), separate from fee_sats
    settled_in_ms: int | None
    destination: str | None
    memo: str | None
    created_at: datetime

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Receipt":
        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            status=data["status"],
            hash=data.get("hash"),
            amount_sats=int(data["amount_sats"]),
            fee_sats=int(data.get("fee_sats", 0)),
            platform_fee_sats=int(data.get("platform_fee_sats", 0)),
            settled_in_ms=data.get("settled_in_ms"),
            destination=data.get("destination"),
            memo=data.get("memo"),
            created_at=_parse_dt(data["created_at"]),
        )


def _parse_dt(s: str | datetime) -> datetime:
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
