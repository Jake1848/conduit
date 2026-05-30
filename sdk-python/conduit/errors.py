"""SDK-side error hierarchy mirroring the API's error codes."""

from typing import Any


class ConduitError(Exception):
    """Base error. All Conduit errors inherit from this."""

    code: str = "conduit_error"

    def __init__(self, message: str, *, code: str | None = None, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r}, {self.message!r})"


class AuthenticationError(ConduitError):
    code = "AUTHENTICATION_ERROR"


class PermissionDenied(ConduitError):
    code = "PERMISSION_DENIED"


class AgentNotFound(ConduitError):
    code = "AGENT_NOT_FOUND"


class PolicyViolation(ConduitError):
    code = "POLICY_VIOLATION"


class InsufficientBalance(ConduitError):
    code = "INSUFFICIENT_BALANCE"


class PaymentFailed(ConduitError):
    code = "PAYMENT_FAILED"


class RateLimited(ConduitError):
    code = "RATE_LIMITED"


class WebhookVerificationError(ConduitError):
    """Raised by parse_webhook when a payload's signature doesn't verify."""

    code = "WEBHOOK_VERIFICATION_ERROR"


_CODE_MAP = {
    "AUTHENTICATION_ERROR": AuthenticationError,
    "PERMISSION_DENIED": PermissionDenied,
    "AGENT_NOT_FOUND": AgentNotFound,
    "POLICY_VIOLATION": PolicyViolation,
    "INSUFFICIENT_BALANCE": InsufficientBalance,
    "PAYMENT_FAILED": PaymentFailed,
    "RATE_LIMITED": RateLimited,
}

# Policy engine codes all map to PolicyViolation.
for _c in (
    "DAILY_LIMIT_EXCEEDED",
    "HOURLY_LIMIT_EXCEEDED",
    "PER_TRANSACTION_LIMIT_EXCEEDED",
    "RATE_LIMIT_EXCEEDED",
    "DESTINATION_BLOCKLISTED",
    "DESTINATION_NOT_ALLOWLISTED",
    "POLICY_DISABLED",
    "MEMO_REQUIRED",
    "AGENT_INACTIVE",
):
    _CODE_MAP[_c] = PolicyViolation


def raise_for_error(status_code: int, body: dict[str, Any]) -> None:
    """Translate a non-2xx API response into the right exception type."""
    detail = body.get("detail", body) if isinstance(body, dict) else {"raw": body}
    if not isinstance(detail, dict):
        detail = {"raw": detail}
    code = detail.get("code") or detail.get("error") or "CONDUIT_ERROR"
    message = detail.get("detail") or detail.get("message") or f"HTTP {status_code}"
    cls = _CODE_MAP.get(str(code).upper(), ConduitError)
    raise cls(message, code=str(code).upper(), **{k: v for k, v in detail.items() if k not in ("code", "detail", "error")})
