from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "staging", "production"] = Field("development", alias="CONDUIT_ENV")
    network: Literal["mainnet", "testnet", "signet", "regtest"] = Field(
        "testnet", alias="CONDUIT_NETWORK"
    )

    database_url: str = Field("sqlite+aiosqlite:///./data/conduit.db", alias="DATABASE_URL")
    api_secret_key: str = Field("dev-secret-change-me", alias="API_SECRET_KEY")
    log_level: str = Field("info", alias="LOG_LEVEL")

    lnd_mock: bool = Field(True, alias="LND_MOCK")
    lnd_rest_url: str = Field("https://127.0.0.1:8080", alias="LND_REST_URL")
    lnd_macaroon_path: str = Field("/root/.lnd/admin.macaroon", alias="LND_MACAROON_PATH")
    lnd_tls_cert_path: str = Field("/root/.lnd/tls.cert", alias="LND_TLS_CERT_PATH")

    bootstrap_api_key: str | None = Field(None, alias="BOOTSTRAP_API_KEY")

    webhook_max_retries: int = 6
    webhook_timeout_seconds: int = 10

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def api_key_prefix(self) -> str:
        return "ck_live_" if self.network == "mainnet" else "ck_test_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
