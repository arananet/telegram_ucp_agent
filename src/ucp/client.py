"""
src/ucp/client.py
─────────────────
Async HTTP client for a UCP-compliant merchant.

Implements all endpoints used by the bot (SPEC.md §3).
All authenticated requests use the X-API-Key header.
Error handling follows the table in SPEC.md §3.7.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.ucp.models import (
    CheckoutRequest,
    CheckoutSession,
    PaymentRequest,
    ProductsResponse,
    UCPManifest,
)

logger = logging.getLogger(__name__)

# Timeout for all UCP HTTP calls
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class UCPError(Exception):
    """Raised when the UCP merchant returns an error response."""

    def __init__(self, status_code: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


def _user_message_for_status(status_code: int, body: dict) -> str:
    """Translate an HTTP error into a user-facing string (SPEC.md §3.7)."""
    if status_code == 400:
        msgs = body.get("messages") or body.get("errors") or []
        if msgs and isinstance(msgs, list) and msgs[0].get("content"):
            return msgs[0]["content"]
        return "Invalid request."
    if status_code == 401:
        return "Authentication error — please contact the admin."
    if status_code == 402:
        details = body.get("details", "")
        return f"Payment failed{': ' + details if details else ''}."
    if status_code == 404:
        return "Session not found."
    if status_code == 409:
        return "Action not allowed in the current session state."
    if status_code == 429:
        return "The store is rate-limiting requests — please wait a moment."
    if status_code >= 500:
        return "The store is temporarily unavailable, please try again."
    return f"Unexpected error ({status_code})."


class UCPClient:
    """Async client for a UCP-compliant merchant (SPEC.md §3)."""

    def __init__(self, merchant_url: str, api_key: str) -> None:
        self._base = merchant_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "telegram-ucp-agent/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    async def _get(self, path: str, params: dict | None = None, auth: bool = False) -> Any:
        url = f"{self._base}{path}"
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)

    async def _post(self, path: str, body: dict | None = None, auth: bool = True) -> Any:
        url = f"{self._base}{path}"
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.post(url, json=body or {}, headers=headers)
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)

    async def _put(self, path: str, body: dict) -> Any:
        url = f"{self._base}{path}"
        try:
            resp = await self._client.put(url, json=body, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)

    def _parse(self, resp: httpx.Response) -> Any:
        if resp.is_success:
            return resp.json()

        body: dict = {}
        try:
            body = resp.json()
        except Exception:
            pass

        retry_after: int | None = None
        if resp.status_code == 429:
            try:
                retry_after = int(resp.headers.get("Retry-After", 60))
            except (TypeError, ValueError):
                retry_after = 60

        msg = _user_message_for_status(resp.status_code, body)
        logger.warning("UCP error %s: %s", resp.status_code, msg)
        raise UCPError(resp.status_code, msg, retry_after=retry_after)

    # ── §3.1  Discovery ───────────────────────────────────────────────────────

    async def discover(self) -> UCPManifest:
        """GET /.well-known/ucp — no auth required."""
        data = await self._get("/.well-known/ucp", auth=False)
        return UCPManifest.model_validate(data)

    # ── §3.2  Product Catalog ─────────────────────────────────────────────────

    async def list_products(
        self,
        *,
        page: int = 1,
        per_page: int = 8,
        search: str | None = None,
        category: str | None = None,
        in_stock: bool | None = None,
    ) -> ProductsResponse:
        """GET /wp-json/ucp/v1/products — no auth required."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search:
            params["search"] = search
        if category:
            params["category"] = category
        if in_stock is not None:
            params["in_stock"] = str(in_stock).lower()

        data = await self._get("/wp-json/ucp/v1/products", params=params, auth=False)
        return ProductsResponse.model_validate(data)

    # ── §3.3  Create Checkout Session ─────────────────────────────────────────

    async def create_checkout_session(self, checkout: CheckoutRequest) -> CheckoutSession:
        """POST /wp-json/ucp/v1/checkout-sessions — auth required."""
        body = {"checkout": checkout.model_dump(exclude_none=True)}
        data = await self._post("/wp-json/ucp/v1/checkout-sessions", body=body)
        return CheckoutSession.model_validate(data)

    # ── §3.4  Get Checkout Session ────────────────────────────────────────────

    async def get_checkout_session(self, session_id: str) -> CheckoutSession:
        """GET /wp-json/ucp/v1/checkout-sessions/{id} — auth required."""
        data = await self._get(f"/wp-json/ucp/v1/checkout-sessions/{session_id}", auth=True)
        return CheckoutSession.model_validate(data)

    # ── §3.4  Update Checkout Session ─────────────────────────────────────────

    async def update_checkout_session(
        self, session_id: str, checkout: CheckoutRequest
    ) -> CheckoutSession:
        """
        PUT /wp-json/ucp/v1/checkout-sessions/{id} — full replacement.
        Must include ALL fields you want to keep (SPEC.md §3.4).
        """
        body = {"checkout": checkout.model_dump(exclude_none=True)}
        data = await self._put(f"/wp-json/ucp/v1/checkout-sessions/{session_id}", body=body)
        return CheckoutSession.model_validate(data)

    # ── §3.5  Complete Checkout Session ───────────────────────────────────────

    async def complete_checkout_session(
        self,
        session_id: str,
        payment: PaymentRequest | None = None,
    ) -> CheckoutSession:
        """
        POST /wp-json/ucp/v1/checkout-sessions/{id}/complete — auth required.
        payment=None → send empty body (COD / manual payment gateway).
        """
        if payment:
            body = {"payment": payment.model_dump(exclude_none=True)}
        else:
            body = {}
        data = await self._post(
            f"/wp-json/ucp/v1/checkout-sessions/{session_id}/complete",
            body=body,
        )
        return CheckoutSession.model_validate(data)

    # ── §3.6  Cancel Checkout Session ─────────────────────────────────────────

    async def cancel_checkout_session(self, session_id: str) -> CheckoutSession:
        """
        POST /wp-json/ucp/v1/checkout-sessions/{id}/cancel — auth required.
        Best-effort; errors are swallowed by the caller (SPEC.md §3.6).
        """
        data = await self._post(f"/wp-json/ucp/v1/checkout-sessions/{session_id}/cancel")
        return CheckoutSession.model_validate(data)
