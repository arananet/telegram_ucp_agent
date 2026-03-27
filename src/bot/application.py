"""
src/bot/application.py
──────────────────────
Build and wire the python-telegram-bot Application.

This module:
- Creates the UCPClient and injects it into bot_data
- Wires all handlers and the ConversationHandler
- Applies rate limiting as a middleware check
- Sets a 30-minute conversation timeout (SPEC.md §2.3)
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from src.bot.handlers.cart import on_add_to_cart, on_remove_from_cart, show_cart
from src.bot.handlers.catalog import (
    on_back_to_catalog,
    on_page_selected,
    on_product_selected,
    show_catalog,
)
from src.bot.handlers.checkout import (
    on_address_input,
    on_back_to_address,
    on_cancel_order,
    on_confirm_order,
    on_restart,
    on_shipping_selected,
    on_start_checkout,
)
from src.bot.handlers.start import cmd_cancel, cmd_help, cmd_start, handle_timeout
from src.bot.states import State
from src.config import Settings
from src.middleware.rate_limiter import RateLimiter
from src.ucp.client import UCPClient

logger = logging.getLogger(__name__)

_CONVERSATION_TIMEOUT = 30 * 60  # 30 minutes in seconds


def _make_rate_limited(handler_fn, limiter: RateLimiter):
    """Wrap a handler to enforce per-user rate limiting."""

    async def wrapper(update: Update, context):
        user = update.effective_user
        if not user:
            return await handler_fn(update, context)

        allowed, retry_after = limiter.is_allowed(user.id)
        if not allowed:
            msg = f"Too many requests — please wait {retry_after}s."
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            elif update.message:
                await update.message.reply_text(msg)
            return None  # stay in current state (ConversationHandler ignores None)

        return await handler_fn(update, context)

    return wrapper


def build_application(settings: Settings) -> Application:
    """Construct the fully configured telegram Application."""

    # ── UCP client ────────────────────────────────────────────────────────────
    ucp_client = UCPClient(
        merchant_url=settings.ucp_merchant_url,
        api_key=settings.ucp_api_key,
    )

    # ── Rate limiter ──────────────────────────────────────────────────────────
    limiter = RateLimiter(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    def rl(fn):
        return _make_rate_limited(fn, limiter)

    # ── Conversation handler ──────────────────────────────────────────────────
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", rl(cmd_start)),
            CommandHandler("help", cmd_help),
        ],
        states={
            State.BROWSING: [
                CallbackQueryHandler(rl(on_product_selected), pattern=r"^prod_\d+$"),
                CallbackQueryHandler(rl(on_page_selected),    pattern=r"^page_\d+$"),
                CallbackQueryHandler(rl(show_cart),           pattern=r"^action_cart$"),
            ],
            State.PRODUCT_DETAIL: [
                CallbackQueryHandler(rl(on_add_to_cart),      pattern=r"^add_\d+$"),
                CallbackQueryHandler(rl(on_back_to_catalog),  pattern=r"^action_back$"),
                CallbackQueryHandler(rl(show_cart),           pattern=r"^action_cart$"),
            ],
            State.CART: [
                CallbackQueryHandler(rl(on_remove_from_cart), pattern=r"^rm_\d+$"),
                CallbackQueryHandler(rl(on_start_checkout),   pattern=r"^action_checkout$"),
                CallbackQueryHandler(rl(on_back_to_catalog),  pattern=r"^action_back$"),
            ],
            State.CHECKOUT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rl(on_address_input)),
            ],
            State.CHECKOUT_SHIPPING: [
                CallbackQueryHandler(rl(on_shipping_selected), pattern=r"^ship_.+$"),
                CallbackQueryHandler(rl(on_back_to_address),   pattern=r"^action_back$"),
            ],
            State.CHECKOUT_CONFIRM: [
                CallbackQueryHandler(rl(on_confirm_order),    pattern=r"^action_confirm$"),
                CallbackQueryHandler(rl(show_cart),           pattern=r"^action_cart$"),
                CallbackQueryHandler(rl(on_cancel_order),     pattern=r"^action_cancel$"),
            ],
            State.ORDER_DONE: [
                CallbackQueryHandler(rl(on_restart), pattern=r"^action_restart$"),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, handle_timeout),
                CallbackQueryHandler(handle_timeout),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", rl(cmd_cancel)),
            CommandHandler("start",  rl(cmd_start)),
        ],
        conversation_timeout=_CONVERSATION_TIMEOUT,
        name="shopping_conversation",
        persistent=False,
    )

    # ── Build Application ─────────────────────────────────────────────────────
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(False)  # required for ConversationHandler correctness
        .build()
    )

    app.add_handler(conv_handler)
    # Standalone /help outside an active conversation
    app.add_handler(CommandHandler("help", cmd_help))

    # ── Inject shared resources into bot_data ─────────────────────────────────
    app.bot_data["ucp_client"] = ucp_client
    app.bot_data["settings"] = settings
    app.bot_data["rate_limiter"] = limiter

    # Close the HTTP client when the application shuts down
    async def _on_shutdown(app: Application) -> None:
        await ucp_client.close()

    app.post_shutdown(_on_shutdown)

    logger.info(
        "Application built. Merchant: %s | Polling: %s",
        settings.ucp_merchant_url,
        settings.use_polling,
    )
    return app
