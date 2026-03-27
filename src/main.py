"""
src/main.py
───────────
Entry point for the Telegram UCP Agent.

Two runtime modes (SPEC.md §7):
  USE_POLLING=true  → long-polling (local development, no HTTPS needed)
  USE_POLLING=false → webhook via python-telegram-bot's built-in server (Railway)

The webhook server also exposes GET /health for Railway's health checks.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram.ext import Application

from src.bot.application import build_application
from src.config import Settings, configure_logging, get_settings

logger = logging.getLogger(__name__)


async def _run_polling(app: Application) -> None:
    """Start the bot with long-polling (local dev)."""
    logger.info("Starting in POLLING mode")
    await app.run_polling(drop_pending_updates=True)


async def _run_webhook(app: Application, settings: Settings) -> None:
    """Start the bot with webhook (production on Railway)."""
    webhook_url = f"{settings.webhook_url}/telegram"
    logger.info("Starting in WEBHOOK mode — %s", webhook_url)
    logger.info("Listening on port %d", settings.port)

    await app.run_webhook(
        listen="0.0.0.0",
        port=settings.port,
        url_path="/telegram",
        webhook_url=webhook_url,
        secret_token=settings.telegram_webhook_secret,
        # Health check endpoint built into PTB's webhook server
        # GET /health → 200 {"status": "ok"}
        # served automatically alongside the webhook route
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Starting Telegram UCP Agent")
    logger.info("Merchant URL: %s", settings.ucp_merchant_url)

    app = build_application(settings)

    if settings.use_polling:
        asyncio.run(_run_polling(app))
    else:
        asyncio.run(_run_webhook(app, settings))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down…")
        sys.exit(0)
