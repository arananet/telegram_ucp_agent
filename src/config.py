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
    webhook_url: str = ""

    # ── UCP Merchant ──────────────────────────────────────────────────────────
    ucp_merchant_url: str
    ucp_api_key: str
    ucp_payment_token: str | None = None

    # ── Runtime ───────────────────────────────────────────────────────────────
    port: int = 8080
    use_polling: bool = False
    log_level: str = "INFO"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("ucp_merchant_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("webhook_url", mode="before")
    @classmethod
    def strip_webhook_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v

    @model_validator(mode="after")
    def _check_webhook_fields(self) -> "Settings":
        if not self.use_polling:
            if not self.telegram_webhook_secret:
                raise ValueError(
                    "TELEGRAM_WEBHOOK_SECRET is required when USE_POLLING=false"
                )
            if not self.webhook_url:
                raise ValueError("WEBHOOK_URL is required when USE_POLLING=false")
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
