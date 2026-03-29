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
        address_1="123 Main St",
        city="Springfield",
        state="IL",
        postcode="62701",
        country="US",
    )
    assert a.country == "US"


# ── LineItemRequest ───────────────────────────────────────────────────────────

def test_line_item_request_valid():
    item = LineItemRequest(id=42, quantity=3)
    assert item.quantity == 3
    assert item.item.id == "42"


def test_line_item_request_accepts_item_dict():
    item = LineItemRequest(item={"id": "sku_123"}, quantity=1)
    assert item.item.id == "sku_123"


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
    assert len(session.fulfillment[0].methods[0].groups[0].options) == 1
    assert session.fulfillment[0].methods[0].groups[0].selected_option_id == "flat_rate_1"


def test_checkout_session_normalizes_wc_payload():
    payload = {
        "id": "chk_wc_1",
        "status": "incomplete",
        "currency": "EUR",
        "buyer": [],
        "line_items": [
            {
                "id": "li_11728",
                "item": {
                    "product_id": 15313,
                    "sku": "RETRO-BOB",
                    "title": "Retro Keyboard",
                    "stock_status": True,
                    "image": "https://example.com/img.jpg",
                },
                "quantity": 1,
                "price": {"amount": "25.00"},
                "subtotal": "25.00",
            }
        ],
        "fulfillment": {
            "methods": [
                {
                    "id": "shipping_1",
                    "line_item_ids": ["li_11728"],
                    "groups": [
                        {
                            "id": "package_1",
                            "options": [
                                {"id": "ship_flat", "label": "Flat Rate", "amount": "5.00"},
                                {"id": "ship_fast", "label": "Express", "amount": "10.00"},
                            ],
                            "selected_option_id": "ship_fast",
                        }
                    ],
                }
            ],
        },
        "totals": {
            "subtotal": "25.00",
            "shipping": "5.00",
            "tax": "0.00",
            "discount": "0.00",
            "total": "30.00",
        },
        "messages": [],
        "links": {"self": "https://example.com"},
    }

    session = CheckoutSession.model_validate(payload)

    assert session.line_items[0].product_id == 15313
    assert session.line_items[0].unit_price == pytest.approx(25.0)
    assert session.fulfillment[0].methods[0].groups[0].selected_option_id == "ship_fast"
    assert session.totals.total == pytest.approx(30.0)


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


def test_product_normalizes_price_and_images():
    raw = {
        "id": 1,
        "title": "Widget",
        "description": "Desc",
        "sku": "SKU-1",
        "price": {"amount": "25.00", "currency": "EUR"},
        "stock_status": "in_stock",
        "images": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        "categories": [],
        "variations": [],
    }
    product = Product.model_validate(raw)
    assert product.price == pytest.approx(25.0)
    assert product.images.featured == "https://example.com/a.jpg"
    assert len(product.images.gallery) == 2
    assert product.stock_status == "instock"


def test_product_stock_status_from_bool():
    raw = {
        "id": 2,
        "title": "Gadget",
        "description": "",
        "sku": "SKU-2",
        "price": "10.00",
        "stock_status": False,
        "images": [],
        "categories": [],
        "variations": [],
    }
    product = Product.model_validate(raw)
    assert product.stock_status == "outofstock"


def test_pagination_accepts_page_aliases():
    raw = {"page": 2, "per_page": 8, "total": 16}
    pagination = Pagination.model_validate(raw)
    assert pagination.current_page == 2
    assert pagination.pages == 16


# ── UCPManifest ───────────────────────────────────────────────────────────────

def test_manifest_parses(sample_manifest):
    manifest = UCPManifest.model_validate(sample_manifest)
    assert manifest.business.name == "Test Store"
    assert "checkout" in manifest.services[0].capabilities


def test_manifest_missing_business_raises():
    with pytest.raises(ValidationError):
        UCPManifest.model_validate({"services": [], "authentication": {}})


def test_manifest_accepts_nested_ucp_key(sample_manifest):
    nested = {
        "ucp": {
            "merchant": sample_manifest["business"],
        }
    }
    nested["services"] = sample_manifest["services"]
    nested["authentication"] = sample_manifest["authentication"]

    manifest = UCPManifest.model_validate(nested)
    assert manifest.business.name == "Test Store"


def test_manifest_accepts_service_dict(sample_manifest):
    service = dict(sample_manifest["services"][0])
    service.pop("id", None)
    manifest_dict = {
        "ucp": {
            "merchant": sample_manifest["business"],
            "authentication": sample_manifest["authentication"],
        },
        "services": {"dev.ucp.shopping": [service]},
    }
    manifest = UCPManifest.model_validate(manifest_dict)
    assert manifest.business.name == "Test Store"
    assert manifest.services[0].id == "dev.ucp.shopping"
