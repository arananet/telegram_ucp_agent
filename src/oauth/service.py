"""OAuth orchestration: PKCE linking, token refresh, and profile fetch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from src.config import Settings
from src.oauth import pkce
from src.storage.token_store import PendingSession, StoredToken, TokenStore
from src.ucp.client import UCPClient, UCPError


@dataclass
class CallbackResult:
    success: bool
    message: str
    status_code: int
    telegram_user_id: int | None = None
    telegram_message: str | None = None


class OAuthService:
    def __init__(self, settings: Settings, store: TokenStore, ucp_client: UCPClient) -> None:
        self._settings = settings
        self._store = store
        self._ucp = ucp_client
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    @property
    def enabled(self) -> bool:
        required = (
            self._settings.ucp_client_id,
            self._settings.ucp_oauth_authorize,
            self._settings.ucp_oauth_token,
            self._settings.ucp_redirect_uri,
            self._settings.db_url,
        )
        return all(required)

    async def start_link(self, telegram_user_id: int) -> str:
        if not self.enabled:
            raise RuntimeError("OAuth is not configured")

        state = pkce.generate_state()
        verifier = pkce.generate_code_verifier()
        challenge = pkce.generate_code_challenge(verifier)
        await self._store.save_pending_session(state, telegram_user_id, verifier)

        params = {
            "response_type": "code",
            "client_id": self._settings.ucp_client_id,
            "redirect_uri": self._settings.ucp_redirect_uri,
            "scope": self._settings.ucp_oauth_scope or "checkout",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{self._settings.ucp_oauth_authorize}?{urlencode(params)}"

    async def handle_callback(
        self,
        *,
        state: str | None,
        code: str | None,
        error: str | None,
    ) -> CallbackResult:
        if error:
            return CallbackResult(False, f"Authorization failed: {error}", 400)
        if not state or not code:
            return CallbackResult(False, "Missing OAuth parameters.", 400)

        session = await self._store.pop_pending_session(state)
        if not session:
            return CallbackResult(False, "Invalid or expired OAuth state.", 400)

        try:
            token_data = await self._exchange_code(session, code)
        except httpx.HTTPError:
            return CallbackResult(False, "Could not reach OAuth token endpoint.", 502)
        except Exception as exc:  # noqa: BLE001 - bubble message to user
            return CallbackResult(False, f"Token exchange failed: {exc}", 400)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token_data.get("expires_in", 3600)))

        profile = await self._fetch_profile(token_data["access_token"])
        await self._store.upsert_token(
            session.telegram_user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", self._settings.ucp_oauth_scope or "checkout"),
            token_type=token_data.get("token_type", "Bearer"),
            customer_profile=profile,
        )

        msg = "Your store account is now linked. Start checkout again to autofill your address."
        return CallbackResult(True, "Link successful — you can close this page.", 200, session.telegram_user_id, msg)

    async def unlink(self, telegram_user_id: int) -> bool:
        token = await self._store.get_token(telegram_user_id)
        if not token:
            return False

        await self._store.delete_token(telegram_user_id)
        if token.refresh_token and self._settings.ucp_oauth_revoke:
            data = {
                "token": token.refresh_token,
                "client_id": self._settings.ucp_client_id,
            }
            if self._settings.ucp_client_secret:
                data["client_secret"] = self._settings.ucp_client_secret
            try:
                await self._http.post(self._settings.ucp_oauth_revoke, data=data, timeout=10)
            except httpx.HTTPError:
                pass
        return True

    async def get_profile(self, telegram_user_id: int) -> dict | None:
        token = await self.ensure_token(telegram_user_id)
        if not token:
            return None
        if token.customer_profile:
            return token.customer_profile
        profile = await self._fetch_profile(token.access_token)
        await self._store.upsert_token(
            telegram_user_id,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
            expires_at=token.expires_at,
            scope=token.scope,
            token_type=token.token_type,
            customer_profile=profile,
        )
        return profile

    async def ensure_token(self, telegram_user_id: int) -> StoredToken | None:
        token = await self._store.get_token(telegram_user_id)
        if not token:
            return None

        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            refreshed = await self._refresh_token(token)
            if refreshed:
                token = refreshed
        return token

    async def close(self) -> None:
        await self._http.aclose()

    async def _exchange_code(self, session: PendingSession, code: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "client_id": self._settings.ucp_client_id,
            "redirect_uri": self._settings.ucp_redirect_uri,
            "code": code,
            "code_verifier": session.code_verifier,
        }
        if self._settings.ucp_client_secret:
            data["client_secret"] = self._settings.ucp_client_secret

        resp = await self._http.post(self._settings.ucp_oauth_token, data=data)
        resp.raise_for_status()
        payload = resp.json()
        if "access_token" not in payload:
            raise ValueError("Token endpoint missing access_token")
        return payload

    async def _refresh_token(self, token: StoredToken) -> StoredToken | None:
        if not token.refresh_token:
            return None
        data = {
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": self._settings.ucp_client_id,
            "scope": token.scope,
        }
        if self._settings.ucp_client_secret:
            data["client_secret"] = self._settings.ucp_client_secret
        try:
            resp = await self._http.post(self._settings.ucp_oauth_token, data=data)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None

        payload = resp.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        new_token = StoredToken(
            telegram_user_id=token.telegram_user_id,
            access_token=payload.get("access_token", token.access_token),
            refresh_token=payload.get("refresh_token", token.refresh_token),
            expires_at=expires_at,
            scope=payload.get("scope", token.scope),
            token_type=payload.get("token_type", token.token_type),
            customer_profile=token.customer_profile,
        )
        await self._store.upsert_token(
            token.telegram_user_id,
            new_token.access_token,
            new_token.refresh_token,
            new_token.expires_at,
            new_token.scope,
            new_token.token_type,
            customer_profile=new_token.customer_profile,
        )
        return new_token

    async def _fetch_profile(self, access_token: str) -> dict | None:
        try:
            profile = await self._ucp.get_customer_profile(access_token)
        except (AttributeError, UCPError):
            return None
        return profile
