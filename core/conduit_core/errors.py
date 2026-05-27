from typing import Any

from fastapi import HTTPException, status


class ConduitError(HTTPException):
    code: str = "conduit_error"
    http_status: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str, **extra: Any) -> None:
        body = {"error": self.code, "code": self.code.upper(), "detail": detail, **extra}
        super().__init__(status_code=self.http_status, detail=body)


class AuthenticationError(ConduitError):
    code = "authentication_error"
    http_status = status.HTTP_401_UNAUTHORIZED


class PermissionError_(ConduitError):
    code = "permission_denied"
    http_status = status.HTTP_403_FORBIDDEN


class AgentNotFound(ConduitError):
    code = "agent_not_found"
    http_status = status.HTTP_404_NOT_FOUND


class PolicyViolation(ConduitError):
    code = "policy_violation"
    http_status = status.HTTP_403_FORBIDDEN


class InsufficientBalance(ConduitError):
    code = "insufficient_balance"
    http_status = status.HTTP_402_PAYMENT_REQUIRED


class PaymentFailed(ConduitError):
    code = "payment_failed"
    http_status = status.HTTP_502_BAD_GATEWAY


class InvalidInput(ConduitError):
    code = "invalid_input"
    http_status = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class RateLimited(ConduitError):
    code = "rate_limited"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS


class NotFound(ConduitError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class LNDError(ConduitError):
    code = "lnd_error"
    http_status = status.HTTP_502_BAD_GATEWAY


class IdempotencyConflict(ConduitError):
    """Same Idempotency-Key reused with a different request body."""

    code = "idempotency_conflict"
    http_status = status.HTTP_409_CONFLICT
