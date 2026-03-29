"""Extend PTB's webhook Tornado app with extra routes."""

from __future__ import annotations

import telegram.ext._updater as updater_mod
from telegram.ext._utils.webhookhandler import TelegramHandler
import tornado.web

from src.oauth.handlers import OAuthCallbackHandler
from src.oauth.service import OAuthService


def install_oauth_callback(oauth_service: OAuthService) -> None:
    """Monkey-patch PTB's WebhookAppClass to expose /oauth/callback."""

    class _WebhookApp(tornado.web.Application):
        def __init__(self, webhook_path, bot, update_queue, secret_token):
            self.shared_objects = {
                "bot": bot,
                "update_queue": update_queue,
                "secret_token": secret_token,
            }
            handlers = [(rf"{webhook_path}/?", TelegramHandler, self.shared_objects)]
            handlers.append(
                (
                    r"/oauth/callback/?",
                    OAuthCallbackHandler,
                    {"oauth_service": oauth_service, "bot": bot},
                )
            )
            super().__init__(handlers)

        def log_request(self, handler):  # pragma: no cover - same as PTB default
            return super().log_request(handler)

    updater_mod.WebhookAppClass = _WebhookApp
