"""
tests/test_rate_limiter.py
──────────────────────────
Verify rate limiter behaviour (SPEC.md §5.3).
"""

from __future__ import annotations

import time

import pytest

from src.middleware.rate_limiter import RateLimiter


def test_allows_requests_within_limit():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        allowed, retry = limiter.is_allowed(user_id=1)
        assert allowed
        assert retry == 0


def test_blocks_on_limit_exceeded():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.is_allowed(user_id=1)

    allowed, retry_after = limiter.is_allowed(user_id=1)
    assert not allowed
    assert retry_after >= 1


def test_different_users_independent():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.is_allowed(1)
    limiter.is_allowed(1)
    # user 1 is now at limit
    allowed, _ = limiter.is_allowed(1)
    assert not allowed

    # user 2 should be unaffected
    allowed2, _ = limiter.is_allowed(2)
    assert allowed2


def test_reset_clears_bucket():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.is_allowed(1)
    allowed, _ = limiter.is_allowed(1)
    assert not allowed

    limiter.reset(1)
    allowed, _ = limiter.is_allowed(1)
    assert allowed


def test_window_expires(monkeypatch):
    """After the window passes, the bucket should refill."""
    limiter = RateLimiter(max_requests=1, window_seconds=1)
    limiter.is_allowed(1)
    allowed, _ = limiter.is_allowed(1)
    assert not allowed

    # Advance time by patching monotonic
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + 2)

    allowed, _ = limiter.is_allowed(1)
    assert allowed
