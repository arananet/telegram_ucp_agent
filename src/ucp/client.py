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
from urllib.parse import urljoin

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

    def __init__(
        self,
        merchant_url: str,
        api_key: str,
        *,
        discovery_url: str | None = None,
        checkout_url: str | None = None,
        customer_profile_url: str | None = None,
    ) -> None:
        self._base = merchant_url.rstrip("/")
        self._api_key = api_key
        self._products_url = f"{self._base}/products"
        self._checkout_url = (checkout_url or f"{self._base}/checkout-sessions").rstrip("/")
        self._discovery_url = discovery_url or urljoin(self._base + "/", "/.well-known/ucp")
        self._customer_profile_url = customer_profile_url
        self._payments_url = f"{self._base}/payments"
        self._client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "telegram-ucp-agent/1.0"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key}

    async def _get(self, url: str, params: dict | None = None, auth: bool = False) -> Any:
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)

    async def _post(self, url: str, body: dict | None = None, auth: bool = True) -> Any:
        headers = self._auth_headers() if auth else {}
        try:
            resp = await self._client.post(url, json=body or {}, headers=headers)
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)

    async def _put(self, url: str, body: dict) -> Any:
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
        data = await self._get(self._discovery_url, auth=False)
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

        data = await self._get(self._products_url, params=params, auth=False)
        return ProductsResponse.model_validate(data)

    # ── §3.3  Create Checkout Session ─────────────────────────────────────────

    async def create_checkout_session(self, checkout: CheckoutRequest) -> CheckoutSession:
        """POST /wp-json/ucp/v1/checkout-sessions — auth required."""
        body = {"checkout": checkout.model_dump(exclude_none=True)}
        data = await self._post(self._checkout_url, body=body)
        return CheckoutSession.model_validate(data)

    # ── §3.4  Get Checkout Session ────────────────────────────────────────────

    async def get_checkout_session(self, session_id: str) -> CheckoutSession:
        """GET /wp-json/ucp/v1/checkout-sessions/{id} — auth required."""
        session_url = f"{self._checkout_url}/{session_id}"
        data = await self._get(session_url, auth=True)
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
        session_url = f"{self._checkout_url}/{session_id}"
        data = await self._put(session_url, body=body)
        return CheckoutSession.model_validate(data)

    async def select_fulfillment_option(
        self,
        session_id: str,
        method_id: str,
        group_id: str,
        option_id: str,
    ) -> CheckoutSession:
        body = {
            "fulfillment": {
                "methods": [
                    {
                        "id": method_id,
                        "groups": [
                            {
                                "id": group_id,
                                "selected_option_id": option_id,
                            }
                        ],
                    }
                ]
            }
        }

        session_url = f"{self._checkout_url}/{session_id}"
        data = await self._put(session_url, body=body)
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
        url = f"{self._checkout_url}/{session_id}/complete"
        data = await self._post(url, body=body)
        return CheckoutSession.model_validate(data)

    # ── §3.5a  Delegated Payments Helper ──────────────────────────────────────

    async def create_payment_intent(
        self,
        *,
        amount: float,
        currency: str,
        gateway: str | None = None,
    ) -> dict:
        """
        POST /wp-json/ucp/v1/payments/intent — auth required.
        Returns a PSP token/intention the agent can pass to /complete.
        """
        body: dict[str, Any] = {
            "amount": round(float(amount), 2),
            "currency": currency,
        }
        if gateway:
            body["gateway"] = gateway

        url = f"{self._payments_url}/intent"
        return await self._post(url, body=body)

    # ── §3.6  Cancel Checkout Session ─────────────────────────────────────────

    async def cancel_checkout_session(self, session_id: str) -> CheckoutSession:
        """
        POST /wp-json/ucp/v1/checkout-sessions/{id}/cancel — auth required.
        Best-effort; errors are swallowed by the caller (SPEC.md §3.6).
        """
        url = f"{self._checkout_url}/{session_id}/cancel"
        data = await self._post(url)
        return CheckoutSession.model_validate(data)

    # ── OAuth customer profile ────────────────────────────────────────────────

    async def get_customer_profile(self, access_token: str) -> dict:
        if not self._customer_profile_url:
            raise UCPError(0, "Customer profile URL is not configured.")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = await self._client.get(self._customer_profile_url, headers=headers)
        except httpx.RequestError as exc:
            raise UCPError(0, "Could not reach the store — please try again.") from exc
        return self._parse(resp)
