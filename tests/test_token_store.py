"""Tests for the SQLAlchemy token store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.storage.token_store import TokenStore


@pytest.mark.asyncio
async def test_pending_session_roundtrip():
    store = TokenStore("sqlite+pysqlite:///:memory:")
    await store.save_pending_session("abc", telegram_user_id=1, code_verifier="verifier")

    session = await store.pop_pending_session("abc")
    assert session
    assert session.telegram_user_id == 1
    assert session.code_verifier == "verifier"

    assert await store.pop_pending_session("abc") is None
    await store.close()


@pytest.mark.asyncio
async def test_token_upsert_get_delete():
    store = TokenStore("sqlite+pysqlite:///:memory:")
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await store.upsert_token(
        telegram_user_id=42,
        access_token="access",
        refresh_token="refresh",
        expires_at=expires,
        scope="checkout",
        token_type="Bearer",
        customer_profile={"email": "user@example.com"},
    )

    token = await store.get_token(42)
    assert token
    assert token.access_token == "access"
    assert token.customer_profile == {"email": "user@example.com"}

    await store.delete_token(42)
    assert await store.get_token(42) is None
    await store.close()
