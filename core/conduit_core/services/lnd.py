"""LND access layer.

Two implementations:
  * MockLNDClient — used when LND_MOCK=true. In-memory; simulates payments
    instantly so the API can run on any dev machine without a real node.
  * LNDRestClient — talks to LND's REST API (port 8080 by default), which is
    simpler to set up than gRPC because no .proto generation is needed.

The Conduit API only depends on the abstract LNDClient interface — callers
should never branch on which implementation is active.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import secrets
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog

from ..config import Settings, get_settings
from ..errors import LNDError, PaymentFailed

log = structlog.get_logger(__name__)


# ---------- Domain objects ----------

@dataclass
class NodeInfo:
    pubkey: str
    alias: str
    network: str
    block_height: int
    synced_to_chain: bool
    num_active_channels: int


@dataclass
class Balance:
    confirmed_sats: int
    unconfirmed_sats: int
    channel_local_sats: int
    channel_remote_sats: int

    @property
    def available_sats(self) -> int:
        return self.channel_local_sats

    @property
    def pending_sats(self) -> int:
        return self.unconfirmed_sats

    @property
    def total_sats(self) -> int:
        return self.confirmed_sats + self.unconfirmed_sats + self.channel_local_sats


@dataclass
class Invoice:
    payment_request: str
    payment_hash: str
    amount_sats: int
    memo: str
    expires_at: datetime
    settled: bool = False


@dataclass
class PaymentResult:
    payment_hash: str
    payment_preimage: str
    amount_sats: int
    fee_sats: int
    latency_ms: int
    status: str  # 'settled' | 'failed'
    failure_reason: str | None = None


@dataclass
class DecodedInvoice:
    payment_hash: str
    amount_sats: int
    destination: str
    description: str
    expiry: int


# ---------- Protocol ----------

class LNDClient(Protocol):
    async def get_info(self) -> NodeInfo: ...
    async def get_balance(self) -> Balance: ...
    async def create_invoice(self, amount_sats: int, memo: str, expiry: int) -> Invoice: ...
    async def decode_invoice(self, payment_request: str) -> DecodedInvoice: ...
    async def pay_invoice(self, payment_request: str, max_fee_sats: int) -> PaymentResult: ...
    async def keysend(self, dest_pubkey: str, amount_sats: int, memo: str) -> PaymentResult: ...
    async def close(self) -> None: ...


# ---------- Mock implementation ----------

@dataclass
class _MockInvoice:
    payment_request: str
    payment_hash: str
    preimage: str
    amount_sats: int
    memo: str
    expires_at: datetime
    settled: bool = False


@dataclass
class _MockState:
    invoices: dict[str, _MockInvoice] = field(default_factory=dict)
    payments: list[PaymentResult] = field(default_factory=list)
    confirmed_sats: int = 5_000_000
    channel_local_sats: int = 5_000_000
    channel_remote_sats: int = 5_000_000


class MockLNDClient:
    """Drop-in LND substitute for local development."""

    def __init__(self, network: str = "testnet") -> None:
        self._network = network
        self._state = _MockState()
        self._pubkey = "02" + secrets.token_hex(32)
        self._lock = asyncio.Lock()

    async def get_info(self) -> NodeInfo:
        return NodeInfo(
            pubkey=self._pubkey,
            alias="Conduit (mock)",
            network=self._network,
            block_height=900_000,
            synced_to_chain=True,
            num_active_channels=4,
        )

    async def get_balance(self) -> Balance:
        return Balance(
            confirmed_sats=self._state.confirmed_sats,
            unconfirmed_sats=0,
            channel_local_sats=self._state.channel_local_sats,
            channel_remote_sats=self._state.channel_remote_sats,
        )

    async def create_invoice(self, amount_sats: int, memo: str, expiry: int) -> Invoice:
        async with self._lock:
            preimage = secrets.token_hex(32)
            payment_hash = binascii.hexlify(_sha256(bytes.fromhex(preimage))).decode()
            payment_request = _fake_bolt11(self._network, amount_sats, payment_hash)
            expires_at = datetime.now(UTC) + timedelta(seconds=expiry)
            inv = _MockInvoice(
                payment_request=payment_request,
                payment_hash=payment_hash,
                preimage=preimage,
                amount_sats=amount_sats,
                memo=memo,
                expires_at=expires_at,
            )
            self._state.invoices[payment_hash] = inv
            return Invoice(
                payment_request=payment_request,
                payment_hash=payment_hash,
                amount_sats=amount_sats,
                memo=memo,
                expires_at=expires_at,
            )

    async def decode_invoice(self, payment_request: str) -> DecodedInvoice:
        inv = next(
            (i for i in self._state.invoices.values() if i.payment_request == payment_request),
            None,
        )
        if inv is None:
            # Synthesize a decode for foreign invoices in mock mode.
            return DecodedInvoice(
                payment_hash=binascii.hexlify(_sha256(payment_request.encode())).decode(),
                amount_sats=0,
                destination="02" + "00" * 32,
                description="mock-decoded invoice",
                expiry=3600,
            )
        return DecodedInvoice(
            payment_hash=inv.payment_hash,
            amount_sats=inv.amount_sats,
            destination=self._pubkey,
            description=inv.memo,
            expiry=int((inv.expires_at - datetime.now(UTC)).total_seconds()),
        )

    async def pay_invoice(self, payment_request: str, max_fee_sats: int) -> PaymentResult:
        decoded = await self.decode_invoice(payment_request)
        amount = decoded.amount_sats or 1
        return await self._simulate_payment(decoded.payment_hash, amount)

    async def keysend(self, dest_pubkey: str, amount_sats: int, memo: str) -> PaymentResult:
        payment_hash = binascii.hexlify(_sha256(secrets.token_bytes(32))).decode()
        return await self._simulate_payment(payment_hash, amount_sats)

    async def _simulate_payment(self, payment_hash: str, amount_sats: int) -> PaymentResult:
        start = time.perf_counter()
        # Simulate ~30–80ms Lightning settlement.
        await asyncio.sleep(0.03 + secrets.randbelow(50) / 1000)
        fee = max(1, amount_sats // 1000)
        async with self._lock:
            if amount_sats + fee > self._state.channel_local_sats:
                raise PaymentFailed(
                    "Insufficient outbound channel capacity "
                    f"({self._state.channel_local_sats} sats)"
                )
            self._state.channel_local_sats -= amount_sats + fee
            self._state.channel_remote_sats += amount_sats
            result = PaymentResult(
                payment_hash=payment_hash,
                payment_preimage=secrets.token_hex(32),
                amount_sats=amount_sats,
                fee_sats=fee,
                latency_ms=int((time.perf_counter() - start) * 1000),
                status="settled",
            )
            self._state.payments.append(result)
            return result

    async def close(self) -> None:
        return None


# ---------- Real REST implementation ----------

class LNDRestClient:
    """Talks to LND's REST API on port 8080. Macaroon auth via header."""

    def __init__(
        self,
        base_url: str,
        macaroon_path: str,
        tls_cert_path: str,
        network: str = "mainnet",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._network = network
        self._macaroon_hex = _load_macaroon_hex(macaroon_path)
        self._ssl_ctx = _load_tls_context(tls_cert_path)
        self._client = httpx.AsyncClient(
            verify=self._ssl_ctx,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"Grpc-Metadata-macaroon": self._macaroon_hex},
        )

    async def get_info(self) -> NodeInfo:
        data = await self._get("/v1/getinfo")
        return NodeInfo(
            pubkey=data["identity_pubkey"],
            alias=data.get("alias", ""),
            network=self._network,
            block_height=int(data.get("block_height", 0)),
            synced_to_chain=bool(data.get("synced_to_chain", False)),
            num_active_channels=int(data.get("num_active_channels", 0)),
        )

    async def get_balance(self) -> Balance:
        wallet = await self._get("/v1/balance/blockchain")
        channels = await self._get("/v1/balance/channels")
        return Balance(
            confirmed_sats=int(wallet.get("confirmed_balance", 0)),
            unconfirmed_sats=int(wallet.get("unconfirmed_balance", 0)),
            channel_local_sats=int(channels.get("local_balance", {}).get("sat", 0)),
            channel_remote_sats=int(channels.get("remote_balance", {}).get("sat", 0)),
        )

    async def create_invoice(self, amount_sats: int, memo: str, expiry: int) -> Invoice:
        data = await self._post(
            "/v1/invoices",
            {"value": amount_sats, "memo": memo, "expiry": expiry},
        )
        payment_hash = _b64_to_hex(data["r_hash"])
        return Invoice(
            payment_request=data["payment_request"],
            payment_hash=payment_hash,
            amount_sats=amount_sats,
            memo=memo,
            expires_at=datetime.now(UTC) + timedelta(seconds=expiry),
        )

    async def decode_invoice(self, payment_request: str) -> DecodedInvoice:
        data = await self._get(f"/v1/payreq/{payment_request}")
        return DecodedInvoice(
            payment_hash=data["payment_hash"],
            amount_sats=int(data.get("num_satoshis", 0)),
            destination=data["destination"],
            description=data.get("description", ""),
            expiry=int(data.get("expiry", 3600)),
        )

    async def pay_invoice(self, payment_request: str, max_fee_sats: int) -> PaymentResult:
        start = time.perf_counter()
        data = await self._post(
            "/v2/router/send",
            {
                "payment_request": payment_request,
                "timeout_seconds": 60,
                "fee_limit_sat": max_fee_sats,
                "no_inflight_updates": True,
            },
            stream=True,
        )
        return self._parse_payment(data, start)

    async def keysend(self, dest_pubkey: str, amount_sats: int, memo: str) -> PaymentResult:
        preimage = secrets.token_bytes(32)
        payment_hash = _sha256(preimage)
        start = time.perf_counter()
        dest_custom_records = {"5482373484": _b64(preimage)}
        if memo:
            # Custom record 34349334 is used by some wallets for keysend messages.
            dest_custom_records["34349334"] = _b64(memo.encode())
        data = await self._post(
            "/v2/router/send",
            {
                "dest": _b64(bytes.fromhex(dest_pubkey)),
                "amt": amount_sats,
                "payment_hash": _b64(payment_hash),
                "timeout_seconds": 60,
                "fee_limit_sat": max(1, amount_sats // 100),
                "dest_custom_records": dest_custom_records,
                "no_inflight_updates": True,
            },
            stream=True,
        )
        return self._parse_payment(data, start)

    def _parse_payment(self, data: dict[str, Any], start: float) -> PaymentResult:
        status = data.get("status", "UNKNOWN")
        if status != "SUCCEEDED":
            raise PaymentFailed(
                f"Lightning payment failed: {data.get('failure_reason', status)}",
                lnd_status=status,
            )
        return PaymentResult(
            payment_hash=data["payment_hash"],
            payment_preimage=data["payment_preimage"],
            amount_sats=int(data.get("value_sat", 0)),
            fee_sats=int(data.get("fee_sat", 0)),
            latency_ms=int((time.perf_counter() - start) * 1000),
            status="settled",
        )

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            r = await self._client.get(self._base + path)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise LNDError(f"LND GET {path} failed: {e}") from e

    async def _post(
        self, path: str, body: dict[str, Any], *, stream: bool = False
    ) -> dict[str, Any]:
        import json as _json

        try:
            r = await self._client.post(self._base + path, json=body)
            r.raise_for_status()
            if stream:
                # Router streaming endpoints return ndjson; take the final event.
                last: dict[str, Any] = {}
                for line in r.text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parsed = _json.loads(line)
                    last = parsed.get("result", parsed)
                return last or {}
            return r.json()
        except httpx.HTTPError as e:
            raise LNDError(f"LND POST {path} failed: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()


# ---------- helpers ----------

def _sha256(data: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(data).digest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _b64_to_hex(s: str) -> str:
    return binascii.hexlify(base64.b64decode(s)).decode()


def _load_macaroon_hex(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise LNDError(f"Macaroon not found at {path}")
    return p.read_bytes().hex()


def _load_tls_context(path: str) -> ssl.SSLContext:
    p = Path(path)
    if not p.exists():
        raise LNDError(f"TLS cert not found at {path}")
    ctx = ssl.create_default_context(cafile=str(p))
    ctx.check_hostname = False
    return ctx


def _fake_bolt11(network: str, amount_sats: int, payment_hash: str) -> str:
    prefix = {"mainnet": "lnbc", "testnet": "lntb", "signet": "lntbs", "regtest": "lnbcrt"}[network]
    return f"{prefix}{amount_sats}u1mock{payment_hash[:48]}"


# ---------- Factory ----------

_singleton: LNDClient | None = None


def build_lnd_client(settings: Settings | None = None) -> LNDClient:
    settings = settings or get_settings()
    if settings.lnd_mock:
        log.info("lnd_client_mode", mode="mock", network=settings.network)
        return MockLNDClient(network=settings.network)
    log.info("lnd_client_mode", mode="rest", url=settings.lnd_rest_url)
    return LNDRestClient(
        base_url=settings.lnd_rest_url,
        macaroon_path=settings.lnd_macaroon_path,
        tls_cert_path=settings.lnd_tls_cert_path,
        network=settings.network,
    )


def get_lnd() -> LNDClient:
    global _singleton
    if _singleton is None:
        _singleton = build_lnd_client()
    return _singleton


async def shutdown_lnd() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.close()
        _singleton = None
