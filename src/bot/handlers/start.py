"""
src/bot/handlers/start.py
─────────────────────────
/start, /help, /cancel and the global fallback handler.
Entry point of the conversation (SPEC.md §2.1).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.bot.states import State
from src.ucp.client import UCPClient, UCPError
from src.ucp.discovery import fetch_manifest

logger = logging.getLogger(__name__)

_HELP_TEXT = (
    "I can help you browse and buy products from our store.\n\n"
    "Commands:\n"
    "/start — Open the product catalog\n"
    "/cancel — Cancel the current operation\n"
    "/help — Show this message"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — greet user and show catalog (→ BROWSING)."""
    user = update.effective_user
    logger.info("user_id=%s started a session", user.id)

    # Attempt manifest discovery (non-fatal)
    ucp: UCPClient = context.bot_data["ucp_client"]
    await fetch_manifest(ucp)

    await update.message.reply_text(
        f"Welcome{', ' + user.first_name if user.first_name else ''}! 🛍\n"
        "Let me fetch the product catalog for you…"
    )

    # Delegate to catalog to render products
    from src.bot.handlers.catalog import show_catalog
    return await show_catalog(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /help — show help text without changing state."""
    await update.message.reply_text(_HELP_TEXT)
    return ConversationHandler.END  # no active conversation; handled outside handler


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle /cancel — best-effort cancel any open UCP session, clear user_data.
    (SPEC.md §2.1, §3.6)
    """
    user = update.effective_user
    logger.info("user_id=%s cancelled session", user.id)

    session_id: str | None = context.user_data.get("checkout_session_id")
    if session_id:
        ucp: UCPClient = context.bot_data["ucp_client"]
        try:
            await ucp.cancel_checkout_session(session_id)
        except UCPError:
            pass  # best-effort

    context.user_data.clear()
    await update.message.reply_text(
        "Operation cancelled. Send /start to begin again."
    )
    return ConversationHandler.END


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Called when the conversation times out (SPEC.md §2.3).
    Cancel any open session and clear state.
    """
    if not update or not update.effective_user:
        return ConversationHandler.END

    logger.info("user_id=%s conversation timed out", update.effective_user.id)

    session_id: str | None = context.user_data.get("checkout_session_id")
    if session_id:
        ucp: UCPClient = context.bot_data["ucp_client"]
        try:
            await ucp.cancel_checkout_session(session_id)
        except UCPError:
            pass

    context.user_data.clear()

    try:
        await update.effective_chat.send_message(
            "Your session has expired. Send /start to begin again."
        )
    except Exception:
        pass

    return ConversationHandler.END
