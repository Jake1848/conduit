from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_API_SECRET = "dev-secret-change-me"
DEFAULT_BOOTSTRAP_KEY_DEV = "ck_test_dev_root"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "staging", "production"] = Field("development", alias="CONDUIT_ENV")
    network: Literal["mainnet", "testnet", "signet", "regtest"] = Field(
        "testnet", alias="CONDUIT_NETWORK"
    )

    database_url: str = Field("sqlite+aiosqlite:///./data/conduit.db", alias="DATABASE_URL")
    # Postgres connection pool (ignored for SQLite). Sized for a single API worker;
    # multiply by the worker count when capacity-planning against Postgres max_connections.
    db_pool_size: int = Field(10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(20, alias="DB_MAX_OVERFLOW")
    # Server-wide HMAC pepper used (a) as a sentinel ("don't ship the dev value to prod")
    # and (b) as the key for X-Conduit-Server-Signature on outbound webhook deliveries.
    api_secret_key: str = Field(DEFAULT_API_SECRET, alias="API_SECRET_KEY")
    log_level: str = Field("info", alias="LOG_LEVEL")

    lnd_mock: bool = Field(True, alias="LND_MOCK")
    lnd_rest_url: str = Field("https://127.0.0.1:8080", alias="LND_REST_URL")
    lnd_macaroon_path: str = Field("/root/.lnd/admin.macaroon", alias="LND_MACAROON_PATH")
    lnd_tls_cert_path: str = Field("/root/.lnd/tls.cert", alias="LND_TLS_CERT_PATH")

    bootstrap_api_key: str | None = Field(None, alias="BOOTSTRAP_API_KEY")

    # CORS — comma-separated list, e.g. "https://conduit.energy,https://app.conduit.energy".
    # Empty means cross-origin requests are not permitted (Same-Origin only).
    allowed_origins_raw: str = Field("", alias="ALLOWED_ORIGINS")

    # HTTP-layer rate limiting (token bucket, in-process).
    # Set to 0 to disable.
    rate_limit_per_minute: int = Field(300, alias="RATE_LIMIT_PER_MINUTE")
    rate_limit_burst: int = Field(60, alias="RATE_LIMIT_BURST")

    webhook_max_retries: int = 6
    webhook_timeout_seconds: int = 10

    # Idempotency records are retained this long, then pruned by a background task
    # so the table can't grow unbounded. 72h comfortably covers any sane client
    # retry window while keeping the table small.
    idempotency_retention_hours: int = Field(72, alias="IDEMPOTENCY_RETENTION_HOURS")
    idempotency_prune_interval_seconds: int = Field(
        3600, alias="IDEMPOTENCY_PRUNE_INTERVAL_SECONDS"
    )

    @field_validator("env", mode="after")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        return v.lower()

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def api_key_prefix(self) -> str:
        return "ck_live_" if self.network == "mainnet" else "ck_test_"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins_raw.split(",") if o.strip()]

    def validate_for_runtime(self) -> list[str]:
        """Return a list of fatal errors. Empty list means OK to start.

        Called from main.py during lifespan startup. In production we refuse
        to boot with insecure defaults — better a loud failure than a quiet
        deployment that leaks the dev bootstrap key onto mainnet.
        """
        errors: list[str] = []
        if self.is_production:
            if self.api_secret_key == DEFAULT_API_SECRET:
                errors.append(
                    "API_SECRET_KEY must be set to a non-default value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            if not self.bootstrap_api_key:
                errors.append(
                    "BOOTSTRAP_API_KEY must be set in production. The startup process "
                    "uses this to install the first admin API key in a fresh DB."
                )
            elif self.bootstrap_api_key == DEFAULT_BOOTSTRAP_KEY_DEV:
                errors.append(
                    f"BOOTSTRAP_API_KEY is set to the dev default ({DEFAULT_BOOTSTRAP_KEY_DEV!r}). "
                    "Generate a fresh value before deploying to production."
                )
            elif not self.bootstrap_api_key.startswith(self.api_key_prefix):
                errors.append(
                    f"BOOTSTRAP_API_KEY must start with {self.api_key_prefix!r} on "
                    f"the {self.network} network."
                )
            if self.network == "mainnet" and not self.bootstrap_api_key.startswith("ck_live_"):
                errors.append(
                    "Mainnet network requires a BOOTSTRAP_API_KEY with prefix ck_live_."
                )
            if self.database_url.startswith("sqlite"):
                # SQLite does not support concurrent writes from multiple processes
                # and lacks row-level locking. Refuse to start in production.
                errors.append(
                    "SQLite is not supported in production. Use Postgres: "
                    "DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/conduit"
                )
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test helper — clears the lru_cache so test envvars are re-read."""
    get_settings.cache_clear()
