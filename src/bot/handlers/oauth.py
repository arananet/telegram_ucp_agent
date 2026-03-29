"""Handlers for /link and /unlink commands."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.oauth.service import OAuthService


def _get_service(context: ContextTypes.DEFAULT_TYPE) -> OAuthService | None:
    service = context.bot_data.get("oauth_service")
    if isinstance(service, OAuthService) and service.enabled:
        return service
    return None


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    service = _get_service(context)
    if not service or not message:
        if message:
            await message.reply_text(
                "Account linking is not available right now. Please try again later."
            )
        return

    user = update.effective_user
    link_url = await service.start_link(user.id)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Link store account", url=link_url)]]
    )
    await message.reply_text(
        "Tap the button below to open the store and authorize access.",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    service = _get_service(context)
    if not message:
        return

    if not service:
        await message.reply_text("There is no linked account to remove.")
        return

    user = update.effective_user
    removed = await service.unlink(user.id)
    if removed:
        await message.reply_text("Your store account has been unlinked.")
    else:
        await message.reply_text("No linked account was found for you.")
