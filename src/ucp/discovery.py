"""
src/ucp/discovery.py
────────────────────
Fetch and cache the /.well-known/ucp manifest (SPEC.md §3.1).

The manifest is cached in memory for 1 hour; the cache is cleared on restart.
A warning is logged if the merchant does not advertise the "checkout" capability,
but the bot continues operating (individual endpoint calls may still succeed).
"""

from __future__ import annotations

import logging
import time

from src.ucp.client import UCPClient, UCPError
from src.ucp.models import UCPManifest

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600  # 1 hour

_cached_manifest: UCPManifest | None = None
_cache_timestamp: float = 0.0


async def fetch_manifest(client: UCPClient, *, force_refresh: bool = False) -> UCPManifest | None:
    """
    Return the cached UCPManifest, refreshing if older than TTL.
    Returns None if the manifest cannot be fetched (non-fatal).
    """
    global _cached_manifest, _cache_timestamp

    now = time.monotonic()
    if not force_refresh and _cached_manifest and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        return _cached_manifest

    try:
        manifest = await client.discover()
    except UCPError as exc:
        logger.warning("Could not fetch UCP manifest: %s", exc.message)
        return _cached_manifest  # return stale cache if available

    _cached_manifest = manifest
    _cache_timestamp = now

    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest: UCPManifest) -> None:
    """Log a warning if the merchant is missing expected capabilities."""
    for service in manifest.services:
        if "checkout" in service.capabilities:
            logger.info(
                "UCP merchant '%s' supports checkout via %s",
                manifest.business.name,
                service.endpoints.rest,
            )
            return

    logger.warning(
        "UCP merchant '%s' does not advertise 'checkout' capability. "
        "Checkout calls may fail.",
        manifest.business.name,
    )
