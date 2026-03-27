"""
tests/test_ucp_models.py
────────────────────────
Verify that Pydantic models correctly parse UCP API payloads (SPEC.md §4).
These tests prove that the model definitions match the WooCommerce UCP plugin contract.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.ucp.models import (
    Address,
    Buyer,
    CheckoutRequest,
    CheckoutSession,
    LineItemRequest,
    Pagination,
    PaymentRequest,
    Product,
    ProductImages,
    ProductsResponse,
    SessionStatus,
    Totals,
    UCPManifest,
)


# ── Address ───────────────────────────────────────────────────────────────────

def test_address_parses_valid():
    a = Address(
        first_name="John", last_name="Doe",
        street_address="123 Main St", city="Springfield",
        state="IL", postal_code="62701", country="US",
    )
    assert a.country == "US"


# ── LineItemRequest ───────────────────────────────────────────────────────────

def test_line_item_request_valid():
    item = LineItemRequest(id=42, quantity=3)
    assert item.quantity == 3


def test_line_item_request_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        LineItemRequest(id=42, quantity=0)


def test_line_item_request_rejects_negative_quantity():
    with pytest.raises(ValidationError):
        LineItemRequest(id=42, quantity=-1)


# ── CheckoutRequest ───────────────────────────────────────────────────────────

def test_checkout_request_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        CheckoutRequest(line_items=[])


def test_checkout_request_valid():
    req = CheckoutRequest(line_items=[LineItemRequest(id=1, quantity=2)])
    assert len(req.line_items) == 1
    assert req.buyer is None
    assert req.discount_codes == []


# ── CheckoutSession ───────────────────────────────────────────────────────────

def test_checkout_session_parses(sample_checkout_session):
    session = CheckoutSession.model_validate(sample_checkout_session)
    assert session.id == "chk_abc123"
    assert session.status == SessionStatus.incomplete
    assert session.totals.total == pytest.approx(69.78)
    assert len(session.line_items) == 1
    assert session.line_items[0].title == "Widget Pro"


def test_checkout_session_status_enum():
    for status in ("incomplete", "requires_escalation", "ready_for_complete", "completed", "canceled"):
        assert SessionStatus(status).value == status


def test_checkout_session_fulfillment_methods(sample_checkout_session):
    session = CheckoutSession.model_validate(sample_checkout_session)
    assert len(session.fulfillment) == 1
    assert session.fulfillment[0].methods[0].id == "flat_rate_1"


# ── PaymentRequest ────────────────────────────────────────────────────────────

def test_payment_request_all_optional():
    p = PaymentRequest()
    assert p.mandate is None
    assert p.payment_token is None


def test_payment_request_with_token():
    p = PaymentRequest(payment_token="tok_stripe_abc")
    assert p.payment_token == "tok_stripe_abc"


# ── ProductsResponse ──────────────────────────────────────────────────────────

def test_products_response_parses(sample_products_response):
    result = ProductsResponse.model_validate(sample_products_response)
    assert len(result.products) == 1
    assert result.products[0].id == 42
    assert result.products[0].title == "Widget Pro"
    assert result.pagination.total == 1


def test_product_images_optional_featured():
    img = ProductImages(featured=None, gallery=[])
    assert img.featured is None


# ── UCPManifest ───────────────────────────────────────────────────────────────

def test_manifest_parses(sample_manifest):
    manifest = UCPManifest.model_validate(sample_manifest)
    assert manifest.business.name == "Test Store"
    assert "checkout" in manifest.services[0].capabilities


def test_manifest_missing_business_raises():
    with pytest.raises(ValidationError):
        UCPManifest.model_validate({"services": [], "authentication": {}})
