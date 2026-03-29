"""
tests/conftest.py
─────────────────
Shared pytest fixtures for the test suite.
"""

from __future__ import annotations

import pytest


# ── Sample UCP API payloads (match WooCommerce UCP plugin spec exactly) ────────

@pytest.fixture
def sample_product_dict() -> dict:
    return {
        "id": 42,
        "title": "Widget Pro",
        "description": "A high quality widget.",
        "sku": "WGT-PRO-001",
        "price": 29.99,
        "stock_status": "instock",
        "images": {
            "featured": "https://example.com/widget.jpg",
            "gallery": [],
        },
        "categories": [{"id": 5, "name": "Widgets", "slug": "widgets"}],
        "variations": [],
    }


@pytest.fixture
def sample_products_response(sample_product_dict) -> dict:
    return {
        "products": [sample_product_dict],
        "pagination": {
            "total": 1,
            "pages": 1,
            "current_page": 1,
            "per_page": 8,
        },
    }


@pytest.fixture
def sample_checkout_session() -> dict:
    return {
        "id": "chk_abc123",
        "status": "incomplete",
        "currency": "USD",
        "buyer": None,
        "line_items": [
            {
                "id": 1,
                "product_id": 42,
                "sku": "WGT-PRO-001",
                "title": "Widget Pro",
                "quantity": 2,
                "unit_price": 29.99,
                "total_price": 59.98,
                "image": None,
                "stock_status": "instock",
            }
        ],
        "fulfillment": [
            {
                "id": "block_1",
                "methods": [
                    {
                        "id": "shipping_1",
                        "line_item_ids": ["li_1"],
                        "groups": [
                            {
                                "id": "package_1",
                                "options": [
                                    {
                                        "id": "flat_rate_1",
                                        "label": "Flat Rate",
                                        "amount": "5.00",
                                    }
                                ],
                                "selected_option_id": "flat_rate_1",
                            }
                        ],
                    }
                ],
            }
        ],
        "discounts": [],
        "totals": {
            "subtotal": 59.98,
            "shipping": 5.00,
            "tax": 4.80,
            "discount": 0.00,
            "total": 69.78,
        },
        "messages": [],
        "links": {
            "self": "https://example.com/wp-json/ucp/v1/checkout-sessions/chk_abc123",
            "update": "https://example.com/wp-json/ucp/v1/checkout-sessions/chk_abc123",
            "complete": "https://example.com/wp-json/ucp/v1/checkout-sessions/chk_abc123/complete",
            "cancel": "https://example.com/wp-json/ucp/v1/checkout-sessions/chk_abc123/cancel",
        },
    }


@pytest.fixture
def sample_manifest() -> dict:
    return {
        "business": {"name": "Test Store", "homepage": "https://example.com"},
        "services": [
            {
                "id": "dev.ucp.shopping.v2026-01-23",
                "endpoints": {
                    "rest": "https://example.com/wp-json/ucp/v1",
                    "mcp": "https://example.com/wp-json/ucp/v1/mcp",
                },
                "capabilities": ["checkout"],
                "extensions": ["fulfillment", "discount", "order"],
                "payment_handlers": [],
            }
        ],
        "authentication": {
            "methods": [{"type": "api_key", "header": "X-API-Key"}]
        },
    }
