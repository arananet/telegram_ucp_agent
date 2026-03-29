"""Tornado handler that receives the OAuth redirect."""

from __future__ import annotations

from html import escape

import tornado.web
from telegram import Bot

from src.oauth.service import OAuthService


class OAuthCallbackHandler(tornado.web.RequestHandler):
    def initialize(self, oauth_service: OAuthService, bot: Bot) -> None:  # type: ignore[override]
        self.oauth_service = oauth_service
        self.bot = bot

    async def get(self) -> None:  # noqa: D401
        result = await self.oauth_service.handle_callback(
            state=self.get_query_argument("state", default=None),
            code=self.get_query_argument("code", default=None),
            error=self.get_query_argument("error", default=None),
        )

        self.set_status(result.status_code)
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.finish(_render_html(result.message))

        if result.success and result.telegram_user_id and result.telegram_message:
            try:
                await self.bot.send_message(result.telegram_user_id, result.telegram_message)
            except Exception:
                pass


def _render_html(message: str) -> str:
    safe = escape(message)
    return f"""
<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>Telegram UCP Agent</title>
    <style>
      body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 2rem; }}
    </style>
  </head>
  <body>
    <h2>{safe}</h2>
    <p>You can close this window and return to Telegram.</p>
  </body>
</html>
"""
