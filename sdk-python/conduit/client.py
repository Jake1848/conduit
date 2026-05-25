"""HTTP client used by every SDK object."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .errors import AuthenticationError, ConduitError, raise_for_error

DEFAULT_BASE_URL = "https://api.conduit.energy"


class Conduit:
    """Low-level client. Use the higher-level `Agent` / `Policy` classes for most work."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        import conduit as _module

        key = api_key or _module.api_key or os.environ.get("CONDUIT_API_KEY")
        if not key:
            raise AuthenticationError(
                "No API key. Set CONDUIT_API_KEY env var, conduit.api_key, "
                "or pass api_key= to the Agent/Conduit constructor.",
                code="AUTHENTICATION_ERROR",
            )
        self.api_key = key
        self.base_url = (
            base_url
            or _module.base_url
            or os.environ.get("CONDUIT_API_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"conduit-python/{_version()}",
            },
        )

    # --- low-level HTTP ---

    def get(self, path: str, **kw: Any) -> Any:
        return self._request("GET", path, **kw)

    def post(self, path: str, json: dict | None = None, **kw: Any) -> Any:
        return self._request("POST", path, json=json, **kw)

    def put(self, path: str, json: dict | None = None, **kw: Any) -> Any:
        return self._request("PUT", path, json=json, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self._request("DELETE", path, **kw)

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ConduitError(f"Network error contacting {self.base_url}: {e}") from e
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {"detail": r.text or f"HTTP {r.status_code}"}
            raise_for_error(r.status_code, body)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Conduit":
        return self

    def __exit__(self, *_) -> None:
        self.close()


_default: Conduit | None = None


def default_client() -> Conduit:
    global _default
    if _default is None:
        _default = Conduit()
    return _default


def _version() -> str:
    try:
        from . import __version__ as v
        return v
    except Exception:
        return "0.0.0"
