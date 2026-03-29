"""PKCE helper functions."""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier(length: int = 64) -> str:
    """Return a URL-safe random code verifier (RFC 7636)."""
    # 32 bytes → 43 chars, 96 bytes → 128 chars. Keep inside spec bounds.
    raw = secrets.token_bytes(max(32, min(length, 96)))
    return _urlsafe_b64(raw)


def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _urlsafe_b64(digest)


def generate_state() -> str:
    """Opaque state string used to correlate OAuth callbacks."""
    return _urlsafe_b64(secrets.token_bytes(32))


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")
