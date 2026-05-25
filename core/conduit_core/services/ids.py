import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def _rand(n: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def agent_id() -> str:
    return f"agt_{_rand(20)}"


def policy_id() -> str:
    return f"pol_{_rand(20)}"


def tx_id() -> str:
    return f"tx_{_rand(24)}"


def invoice_id() -> str:
    return f"inv_{_rand(24)}"


def webhook_id() -> str:
    return f"wh_{_rand(20)}"


def api_key_id() -> str:
    return f"key_{_rand(20)}"


def api_key_secret(prefix: str) -> str:
    """Return a fresh API key string. The full string is shown once to the operator."""
    return f"{prefix}{secrets.token_urlsafe(32).replace('-', '').replace('_', '')[:40]}"
