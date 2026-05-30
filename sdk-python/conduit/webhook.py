"""Verify and parse Conduit webhook deliveries.

Every webhook Conduit sends carries an `X-Conduit-Signature` header of the
form ``sha256=<hexdigest>`` where the digest is HMAC-SHA256 over the RAW
request body bytes, keyed by the per-subscription secret you received when
you created the webhook.

    from conduit.webhook import parse_webhook

    @app.post("/conduit/events")
    async def handler(request):
        body = await request.body()                      # raw bytes
        sig = request.headers["X-Conduit-Signature"]
        event = parse_webhook(body, sig, MY_WEBHOOK_SECRET)
        # event == {"event": "payment.settled", "data": {...}, "ts": ...}

ALWAYS verify on the raw body bytes, before any JSON re-serialization — a
re-encoded body will not match the signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .errors import WebhookVerificationError

__all__ = ["verify_webhook", "parse_webhook", "WebhookVerificationError"]


def _to_bytes(payload: bytes | bytearray | str) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return bytes(payload)


def verify_webhook(payload: bytes | bytearray | str, signature: str, secret: str) -> bool:
    """Return True iff `signature` is a valid Conduit signature for `payload`.

    `signature` is the raw `X-Conduit-Signature` header value
    (``sha256=<hex>``). Comparison is constant-time.
    """
    if not signature or not secret:
        return False
    body = _to_bytes(payload)
    expected_mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={expected_mac}"
    return hmac.compare_digest(expected, signature)


def parse_webhook(
    payload: bytes | bytearray | str, signature: str, secret: str
) -> dict[str, Any]:
    """Verify the signature, then return the decoded JSON body.

    Raises `WebhookVerificationError` if the signature is invalid, so an
    unverified payload can never reach your handler logic.
    """
    if not verify_webhook(payload, signature, secret):
        raise WebhookVerificationError(
            "Webhook signature verification failed — signature did not match the "
            "payload under the provided secret.",
            code="WEBHOOK_VERIFICATION_ERROR",
        )
    return json.loads(_to_bytes(payload))
