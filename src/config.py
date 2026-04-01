"""
src/config.py
─────────────
Application settings loaded from environment variables.
See SPEC.md §6 for the full configuration reference.

All secrets must be supplied via env vars — never hardcoded.
pydantic-settings raises ValidationError on startup if required fields are missing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urljoin

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""

    # ── UCP Merchant ──────────────────────────────────────────────────────────
    ucp_base_url: str
    ucp_checkout_url: str | None = None
    ucp_customer_profile_url: str | None = None
    ucp_discovery_url: str | None = None
    ucp_api_key: str
    ucp_client_id: str | None = None
    ucp_client_secret: str | None = None
    ucp_redirect_uri: str | None = None
    ucp_oauth_scope: str | None = None
    ucp_oauth_authorize: str | None = None
    ucp_oauth_token: str | None = None
    ucp_oauth_revoke: str | None = None
    ucp_payment_token: str | None = None
    ucp_payment_gateway: str | None = None

    # ── Persistence ───────────────────────────────────────────────────────────
    db_url: str | None = None

    # ── PSP / payment providers ───────────────────────────────────────────────
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    ap2_credentials_json: str | None = None

    # ── Runtime ───────────────────────────────────────────────────────────────
    port: int = 8080
    use_polling: bool = False
    log_level: str = "INFO"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator(
        "ucp_base_url",
        "ucp_checkout_url",
        "ucp_customer_profile_url",
        "ucp_discovery_url",
        "ucp_redirect_uri",
        "ucp_oauth_authorize",
        "ucp_oauth_token",
        "ucp_oauth_revoke",
        "telegram_webhook_url",
        mode="before",
    )
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        if isinstance(v, str):
            return v.rstrip("/")
        return v

    @model_validator(mode="after")
    def _check_webhook_fields(self) -> "Settings":
        if not self.use_polling:
            if not self.telegram_webhook_secret:
                raise ValueError(
                    "TELEGRAM_WEBHOOK_SECRET is required when USE_POLLING=false"
                )
            if not self.telegram_webhook_url:
                raise ValueError("TELEGRAM_WEBHOOK_URL is required when USE_POLLING=false")

        base = self.ucp_base_url.rstrip("/")
        if not self.ucp_discovery_url:
            self.ucp_discovery_url = urljoin(base + "/", "/.well-known/ucp")
        if not self.ucp_checkout_url:
            self.ucp_checkout_url = f"{base}/checkout-sessions"
        if not self.ucp_customer_profile_url:
            self.ucp_customer_profile_url = f"{base}/customers/me"
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()  # type: ignore[call-arg]


def configure_logging(level: str = "INFO") -> None:
    """Set up root logger with the given level string."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=numeric,
    )
    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
