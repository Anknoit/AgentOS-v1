"""Application settings (pydantic-settings).

All settings are read from the environment with the ``AGENTOS_`` prefix (plus a few standard
names like ``OPENAI_API_KEY``). Every value has a default that boots the zero-dependency dev
profile: SQLite, in-process runtime, in-process bus, console trace exporter, mock LLM.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- environment / server ---
    env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8787
    api_prefix: str = "/v1"

    # --- database ---
    # Empty => SQLite dev-fallback (ADR-0006). Postgres: postgresql+asyncpg://...
    database_url: str = "sqlite+aiosqlite:///./agentos.db"

    # --- redis / workers ---
    # Empty => agent runs execute in-process; set => enqueue to Arq workers.
    redis_url: str | None = None

    # --- event bus (ADR-0002) ---
    bus: Literal["inprocess", "nats"] = "inprocess"
    nats_url: str = "nats://localhost:4222"

    # --- llm provider (Phase 0 spike) ---
    llm_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    llm_model: str = "gpt-4o-mini"

    # --- payments / settlement (Phase 4) ---
    # "mock" => an in-process gateway that signs with `razorpay_key_secret` so the full
    # order→verify→webhook path is exercised with no network (like the mock LLM). "razorpay"
    # => the live Razorpay Orders API. Secrets live only in env; never logged or returned.
    payment_provider: Literal["mock", "razorpay"] = "mock"
    razorpay_key_id: str = "rzp_test_dev"
    razorpay_key_secret: str = "rzp-dev-secret-change-me"
    razorpay_webhook_secret: str = "rzp-dev-webhook-secret-change-me"
    # The currency Razorpay charges in and its minor-unit scale (USD→cents=100, INR→paise=100).
    # The ledger stays in USD nanodollars; `razorpay_fx_usd_to_gateway` converts a USD amount to
    # the gateway currency so what the gateway charged is recorded exactly for reconciliation.
    razorpay_currency: str = "USD"
    razorpay_minor_per_unit: int = 100
    razorpay_fx_usd_to_gateway: str = "1"
    # Entering the payment path flips prepaid credit control on after the first successful top-up.
    enforce_balance_on_topup: bool = True

    # --- observability ---
    otel_exporter: Literal["console", "otlp", "none"] = "console"
    otlp_endpoint: str = "http://localhost:4318"
    service_name: str = "agentos-backend"
    log_level: str = "INFO"
    log_json: bool = False  # human-readable in dev; set true for prod

    # --- auth / bootstrap (ADR-0004) ---
    seed_dev_tenant: bool = True
    dev_api_key: str = "dev-local-key"
    dev_tenant_slug: str = "dev"
    dev_user_email: str = "dev@agentos.local"
    # Pepper mixed into api-key hashes. Override in prod.
    api_key_pepper: str = "agentos-dev-pepper-change-me"
    # Master secret for the per-tenant credential vault (ADR-0008). A per-tenant encryption key
    # is derived from this via HKDF, so tenant secrets are isolated at the cryptographic layer.
    # MUST be overridden in prod (rotating it makes existing ciphertext undecryptable).
    secret_key: str = "agentos-dev-secret-change-me-0123456789"

    # --- cors (the UI / Electron renderer talk to this) ---
    cors_origins: list[str] = ["*"]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def use_inprocess_runtime(self) -> bool:
        return self.redis_url is None


@lru_cache
def get_settings() -> Settings:
    return Settings()
