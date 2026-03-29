"""Tests for OAuthService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from httpx import Response

from src.oauth.service import OAuthService
from src.storage.token_store import TokenStore


class DummyUCPClient:
    def __init__(self):
        self.calls = []

    async def get_customer_profile(self, access_token: str) -> dict:
        self.calls.append(access_token)
        return {
            "email": "linked@example.com",
            "first_name": "Linked",
            "last_name": "User",
            "shipping": {
                "address_1": "123 Main",
                "city": "Springfield",
                "state": "IL",
                "postcode": "62701",
                "country": "US",
            },
        }


def make_settings(**overrides):
    base = dict(
        ucp_client_id="client",
        ucp_client_secret="",
        ucp_oauth_authorize="https://retrohardware.arananet.net/oauth/authorize",
        ucp_oauth_token="https://retrohardware.arananet.net/oauth/token",
        ucp_oauth_revoke="https://retrohardware.arananet.net/oauth/revoke",
        ucp_redirect_uri="https://bot.example.com/oauth/callback",
        ucp_oauth_scope="checkout",
        db_url="sqlite:///:memory:",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
@respx.mock
async def test_link_and_callback_flow():
    settings = make_settings()
    store = TokenStore("sqlite+pysqlite:///:memory:")
    ucp = DummyUCPClient()
    service = OAuthService(settings, store, ucp)

    url = await service.start_link(telegram_user_id=99)
    params = parse_qs(urlsplit(url).query)
    state = params["state"][0]

    respx.post(settings.ucp_oauth_token).mock(
        return_value=Response(200, json={
            "access_token": "token123",
            "refresh_token": "refresh123",
            "token_type": "Bearer",
            "scope": "checkout",
            "expires_in": 3600,
        })
    )

    result = await service.handle_callback(state=state, code="abc", error=None)
    assert result.success
    assert result.telegram_user_id == 99

    stored = await store.get_token(99)
    assert stored
    assert stored.access_token == "token123"
    assert stored.customer_profile["email"] == "linked@example.com"

    await service.close()


@pytest.mark.asyncio
@respx.mock
async def test_refresh_token_when_expired():
    settings = make_settings()
    store = TokenStore("sqlite+pysqlite:///:memory:")
    ucp = DummyUCPClient()
    service = OAuthService(settings, store, ucp)

    expires = datetime.now(timezone.utc) - timedelta(seconds=5)
    await store.upsert_token(
        telegram_user_id=1,
        access_token="stale",
        refresh_token="refresh",
        expires_at=expires,
        scope="checkout",
        token_type="Bearer",
        customer_profile=None,
    )

    respx.post(settings.ucp_oauth_token).mock(
        return_value=Response(200, json={
            "access_token": "fresh",
            "refresh_token": "refresh",
            "scope": "checkout",
            "expires_in": 7200,
            "token_type": "Bearer",
        })
    )

    token = await service.ensure_token(1)
    assert token
    assert token.access_token == "fresh"

    await service.close()
