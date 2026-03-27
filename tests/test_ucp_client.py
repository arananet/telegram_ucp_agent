"""
tests/test_ucp_client.py
────────────────────────
Test the UCPClient HTTP layer using respx (httpx mock).
Verifies correct request shapes and error handling (SPEC.md §3, §3.7).
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.ucp.client import UCPClient, UCPError
from src.ucp.models import CheckoutRequest, LineItemRequest


BASE = "https://example.com"


@pytest.fixture
def client():
    return UCPClient(merchant_url=BASE, api_key="test_key")


# ── Discovery ─────────────────────────────────────────────────────────────────

@respx.mock
async def test_discover_success(client, sample_manifest):
    respx.get(f"{BASE}/.well-known/ucp").mock(return_value=Response(200, json=sample_manifest))
    manifest = await client.discover()
    assert manifest.business.name == "Test Store"


@respx.mock
async def test_discover_no_auth_header(client, sample_manifest):
    route = respx.get(f"{BASE}/.well-known/ucp").mock(return_value=Response(200, json=sample_manifest))
    await client.discover()
    assert "X-API-Key" not in route.calls[0].request.headers


# ── List Products ─────────────────────────────────────────────────────────────

@respx.mock
async def test_list_products_success(client, sample_products_response):
    respx.get(f"{BASE}/wp-json/ucp/v1/products").mock(
        return_value=Response(200, json=sample_products_response)
    )
    result = await client.list_products()
    assert len(result.products) == 1
    assert result.products[0].price == pytest.approx(29.99)


@respx.mock
async def test_list_products_passes_params(client, sample_products_response):
    route = respx.get(f"{BASE}/wp-json/ucp/v1/products").mock(
        return_value=Response(200, json=sample_products_response)
    )
    await client.list_products(page=2, per_page=5, search="widget")
    params = route.calls[0].request.url.params
    assert params["page"] == "2"
    assert params["per_page"] == "5"
    assert params["search"] == "widget"


# ── Create Checkout Session ───────────────────────────────────────────────────

@respx.mock
async def test_create_checkout_session_sends_api_key(client, sample_checkout_session):
    route = respx.post(f"{BASE}/wp-json/ucp/v1/checkout-sessions").mock(
        return_value=Response(201, json=sample_checkout_session)
    )
    req = CheckoutRequest(line_items=[LineItemRequest(id=42, quantity=1)])
    await client.create_checkout_session(req)
    assert route.calls[0].request.headers["X-API-Key"] == "test_key"


@respx.mock
async def test_create_checkout_session_body_shape(client, sample_checkout_session):
    route = respx.post(f"{BASE}/wp-json/ucp/v1/checkout-sessions").mock(
        return_value=Response(201, json=sample_checkout_session)
    )
    req = CheckoutRequest(line_items=[LineItemRequest(id=42, quantity=2)])
    await client.create_checkout_session(req)

    body = route.calls[0].request.read()
    import json
    payload = json.loads(body)
    assert "checkout" in payload
    assert payload["checkout"]["line_items"][0]["id"] == 42
    assert payload["checkout"]["line_items"][0]["quantity"] == 2


# ── Complete Checkout Session ─────────────────────────────────────────────────

@respx.mock
async def test_complete_sends_empty_body_for_cod(client, sample_checkout_session):
    completed = dict(sample_checkout_session, status="completed")
    route = respx.post(f"{BASE}/wp-json/ucp/v1/checkout-sessions/chk_abc123/complete").mock(
        return_value=Response(200, json=completed)
    )
    session = await client.complete_checkout_session("chk_abc123")
    body = route.calls[0].request.read()
    import json
    assert json.loads(body) == {}
    assert session.status.value == "completed"


# ── Error Handling (SPEC.md §3.7) ─────────────────────────────────────────────

@respx.mock
async def test_error_400_raises_ucp_error(client):
    respx.get(f"{BASE}/wp-json/ucp/v1/products").mock(
        return_value=Response(400, json={"messages": [{"content": "bad request", "type": "validation", "code": "err", "severity": "fatal"}]})
    )
    with pytest.raises(UCPError) as exc_info:
        await client.list_products()
    assert exc_info.value.status_code == 400
    assert "bad request" in exc_info.value.message


@respx.mock
async def test_error_401_raises_ucp_error(client):
    respx.post(f"{BASE}/wp-json/ucp/v1/checkout-sessions").mock(
        return_value=Response(401, json={"error": "Invalid API key"})
    )
    req = CheckoutRequest(line_items=[LineItemRequest(id=1, quantity=1)])
    with pytest.raises(UCPError) as exc_info:
        await client.create_checkout_session(req)
    assert exc_info.value.status_code == 401


@respx.mock
async def test_error_429_includes_retry_after(client):
    respx.get(f"{BASE}/wp-json/ucp/v1/products").mock(
        return_value=Response(429, json={"error": "rate limited"}, headers={"Retry-After": "30"})
    )
    with pytest.raises(UCPError) as exc_info:
        await client.list_products()
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 30


@respx.mock
async def test_error_500_raises_ucp_error(client):
    respx.get(f"{BASE}/wp-json/ucp/v1/products").mock(
        return_value=Response(500, json={})
    )
    with pytest.raises(UCPError) as exc_info:
        await client.list_products()
    assert exc_info.value.status_code == 500
    assert "unavailable" in exc_info.value.message.lower()
