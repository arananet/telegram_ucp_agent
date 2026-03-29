"""Token storage and OAuth session persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)
from sqlalchemy.pool import StaticPool


@dataclass
class StoredToken:
    telegram_user_id: int
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scope: str
    token_type: str
    customer_profile: dict | None


@dataclass
class PendingSession:
    state: str
    telegram_user_id: int
    code_verifier: str
    created_at: datetime


class TokenStore:
    """SQLAlchemy-backed persistence for OAuth tokens and pending PKCE sessions."""

    def __init__(self, db_url: str) -> None:
        engine_kwargs = {"future": True}
        if db_url.startswith("sqlite") and ":memory:" in db_url:
            engine_kwargs.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool,
                }
            )
        self._engine = create_engine(db_url, **engine_kwargs)
        self._metadata = MetaData()

        self._tokens = Table(
            "oauth_tokens",
            self._metadata,
            Column("telegram_user_id", Integer, primary_key=True),
            Column("access_token", Text, nullable=False),
            Column("refresh_token", Text, nullable=True),
            Column("expires_at", DateTime(timezone=True), nullable=False),
            Column("scope", String(255), nullable=False),
            Column("token_type", String(50), nullable=False, default="Bearer"),
            Column("customer_profile", Text, nullable=True),
            Column("updated_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        )

        self._sessions = Table(
            "oauth_sessions",
            self._metadata,
            Column("state", String(128), primary_key=True),
            Column("telegram_user_id", Integer, nullable=False),
            Column("code_verifier", String(256), nullable=False),
            Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
        )

        self._metadata.create_all(self._engine)

    async def save_pending_session(self, state: str, telegram_user_id: int, code_verifier: str) -> None:
        def _op() -> None:
            with self._engine.begin() as conn:
                conn.execute(self._sessions.delete().where(self._sessions.c.state == state))
                conn.execute(
                    self._sessions.insert().values(
                        state=state,
                        telegram_user_id=telegram_user_id,
                        code_verifier=code_verifier,
                        created_at=datetime.now(timezone.utc),
                    )
                )

        await asyncio.to_thread(_op)

    async def pop_pending_session(self, state: str) -> PendingSession | None:
        def _op() -> PendingSession | None:
            with self._engine.begin() as conn:
                row = conn.execute(select(self._sessions).where(self._sessions.c.state == state)).fetchone()
                conn.execute(self._sessions.delete().where(self._sessions.c.state == state))
                if not row:
                    return None
                return PendingSession(
                    state=row.state,
                    telegram_user_id=row.telegram_user_id,
                    code_verifier=row.code_verifier,
                    created_at=row.created_at,
                )

        return await asyncio.to_thread(_op)

    async def upsert_token(
        self,
        telegram_user_id: int,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime,
        scope: str,
        token_type: str,
        customer_profile: dict | None = None,
    ) -> None:
        profile_json = json.dumps(customer_profile) if customer_profile else None

        def _op() -> None:
            with self._engine.begin() as conn:
                conn.execute(
                    self._tokens.delete().where(self._tokens.c.telegram_user_id == telegram_user_id)
                )
                conn.execute(
                    self._tokens.insert().values(
                        telegram_user_id=telegram_user_id,
                        access_token=access_token,
                        refresh_token=refresh_token,
                        expires_at=expires_at,
                        scope=scope,
                        token_type=token_type,
                        customer_profile=profile_json,
                        updated_at=datetime.now(timezone.utc),
                    )
                )

        await asyncio.to_thread(_op)

    async def get_token(self, telegram_user_id: int) -> StoredToken | None:
        def _op() -> StoredToken | None:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(self._tokens).where(self._tokens.c.telegram_user_id == telegram_user_id)
                ).fetchone()
                if not row:
                    return None
                profile = json.loads(row.customer_profile) if row.customer_profile else None
                return StoredToken(
                    telegram_user_id=row.telegram_user_id,
                    access_token=row.access_token,
                    refresh_token=row.refresh_token,
                    expires_at=row.expires_at,
                    scope=row.scope,
                    token_type=row.token_type,
                    customer_profile=profile,
                )

        return await asyncio.to_thread(_op)

    async def delete_token(self, telegram_user_id: int) -> None:
        def _op() -> None:
            with self._engine.begin() as conn:
                conn.execute(
                    self._tokens.delete().where(self._tokens.c.telegram_user_id == telegram_user_id)
                )

        await asyncio.to_thread(_op)

    async def purge_expired_sessions(self, max_age_minutes: int = 15) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

        def _op() -> None:
            with self._engine.begin() as conn:
                conn.execute(self._sessions.delete().where(self._sessions.c.created_at < cutoff))

        await asyncio.to_thread(_op)

    async def close(self) -> None:
        await asyncio.to_thread(self._engine.dispose)
