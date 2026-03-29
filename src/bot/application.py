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
    on_payment_token_input,
    on_restart,
    on_shipping_selected,
    on_start_checkout,
)
from src.bot.handlers.oauth import cmd_link, cmd_unlink
from src.bot.handlers.start import cmd_cancel, cmd_help, cmd_start, handle_timeout
from src.bot.states import State
from src.config import Settings
from src.middleware.rate_limiter import RateLimiter
from src.oauth.service import OAuthService
from src.server.webhook import install_oauth_callback
from src.storage.token_store import TokenStore
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
        merchant_url=settings.ucp_base_url,
        api_key=settings.ucp_api_key,
        discovery_url=settings.ucp_discovery_url,
        checkout_url=settings.ucp_checkout_url,
        customer_profile_url=settings.ucp_customer_profile_url,
    )

    # ── Optional OAuth service ────────────────────────────────────────────────
    token_store: TokenStore | None = None
    oauth_service: OAuthService | None = None
    oauth_requirements = (
        settings.db_url,
        settings.ucp_client_id,
        settings.ucp_oauth_authorize,
        settings.ucp_oauth_token,
        settings.ucp_redirect_uri,
    )
    if all(oauth_requirements):
        token_store = TokenStore(settings.db_url)  # type: ignore[arg-type]
        oauth_service = OAuthService(settings, token_store, ucp_client)
        if not oauth_service.enabled:
            oauth_service = None

    if oauth_service and not settings.use_polling:
        install_oauth_callback(oauth_service)

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
            State.CHECKOUT_PAYMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rl(on_payment_token_input)),
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
    async def _on_shutdown(app: Application) -> None:
        await ucp_client.close()
        if oauth_service:
            await oauth_service.close()
        if token_store:
            await token_store.close()

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(False)  # required for ConversationHandler correctness
        .post_shutdown(_on_shutdown)
        .build()
    )

    app.add_handler(conv_handler)
    # Standalone /help outside an active conversation
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("link",  rl(cmd_link)))
    app.add_handler(CommandHandler("unlink", rl(cmd_unlink)))

    # ── Inject shared resources into bot_data ─────────────────────────────────
    app.bot_data["ucp_client"] = ucp_client
    app.bot_data["settings"] = settings
    app.bot_data["rate_limiter"] = limiter
    if oauth_service:
        app.bot_data["oauth_service"] = oauth_service
    if token_store:
        app.bot_data["token_store"] = token_store

    logger.info(
        "Application built. Merchant: %s | Polling: %s",
        settings.ucp_base_url,
        settings.use_polling,
    )
    return app
