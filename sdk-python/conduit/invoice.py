from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .payment import _parse_dt


@dataclass
class Invoice:
    id: str
    agent_id: str
    payment_request: str
    payment_hash: str
    amount_sats: int
    memo: str | None
    status: str
    expires_at: datetime
    created_at: datetime

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Invoice":
        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            payment_request=data["payment_request"],
            payment_hash=data["payment_hash"],
            amount_sats=int(data["amount_sats"]),
            memo=data.get("memo"),
            status=data["status"],
            expires_at=_parse_dt(data["expires_at"]),
            created_at=_parse_dt(data["created_at"]),
        )
