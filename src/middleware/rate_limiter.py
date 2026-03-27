"""
src/middleware/rate_limiter.py
──────────────────────────────
In-memory per-user rate limiter (SPEC.md §5.3).

Default: 10 requests per 60-second sliding window, per Telegram user_id.
State is reset on bot restart (acceptable for this use case).
"""

from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    """Sliding-window rate limiter keyed by integer user_id."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: dict[int, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: int) -> tuple[bool, int]:
        """
        Check whether *user_id* is within the rate limit.

        Returns:
            (True, 0)            — request allowed.
            (False, retry_after) — request denied; retry_after is seconds to wait.
        """
        now = time.monotonic()
        window_start = now - self._window
        bucket = self._timestamps[user_id]

        # Evict timestamps outside the window
        bucket[:] = [t for t in bucket if t >= window_start]

        if len(bucket) >= self._max:
            oldest = bucket[0]
            retry_after = int(oldest + self._window - now) + 1
            return False, max(retry_after, 1)

        bucket.append(now)
        return True, 0

    def reset(self, user_id: int) -> None:
        """Clear the bucket for a user (e.g. after a ban is lifted)."""
        self._timestamps.pop(user_id, None)
