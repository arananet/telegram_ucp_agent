"""
src/ucp/models.py
─────────────────
Pydantic v2 models for the Universal Commerce Protocol (UCP).

Field names match the WooCommerce UCP plugin API exactly (SPEC.md §4).
These models are the canonical data types for the entire application.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── §4.1  Address ─────────────────────────────────────────────────────────────

class Address(BaseModel):
    address_1: str
    address_2: str | None = None
    city: str
    state: str
    postcode: str
    country: str  # ISO 3166-1 alpha-2 (e.g. "US", "MX")


# ── §4.2  Buyer ───────────────────────────────────────────────────────────────

class Buyer(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    shipping_address: Address | None = None
    billing_address: Address | None = None


# ── §4.3  Line Items ──────────────────────────────────────────────────────────

class LineItemItem(BaseModel):
    id: str

    @model_validator(mode="before")
    @classmethod
    def _coerce_id(cls, value: Any):
        if isinstance(value, dict) and "id" in value:
            coerced = dict(value)
            coerced["id"] = str(coerced["id"])
            return coerced
        if isinstance(value, (int, str)):
            return {"id": str(value)}
        return value


class LineItemRequest(BaseModel):
    item: LineItemItem
    quantity: int = Field(gt=0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_item(cls, data: Any):
        if isinstance(data, dict) and "item" not in data and "id" in data:
            normalized = dict(data)
            normalized["item"] = {"id": normalized.pop("id")}
            return normalized
        return data


class LineItemResponse(BaseModel):
    id: int
    product_id: int
    sku: str
    title: str
    quantity: int
    unit_price: float
    total_price: float
    image: str | None = None
    stock_status: str


# ── §4.4  Checkout Request / Session ─────────────────────────────────────────

class CheckoutRequest(BaseModel):
    line_items: list[LineItemRequest] = Field(min_length=1)
    buyer: Buyer | None = None
    currency: str | None = None
    discount_codes: list[str] = []


class SessionStatus(str, Enum):
    incomplete = "incomplete"
    requires_escalation = "requires_escalation"
    ready_for_complete = "ready_for_complete"
    completed = "completed"
    canceled = "canceled"


class Totals(BaseModel):
    subtotal: float
    shipping: float
    tax: float
    discount: float
    total: float


class FulfillmentOption(BaseModel):
    id: str
    label: str
    amount: float


class FulfillmentGroup(BaseModel):
    id: str
    options: list[FulfillmentOption] = []
    selected_option_id: str | None = None


class FulfillmentMethod(BaseModel):
    id: str
    line_item_ids: list[str] = []
    groups: list[FulfillmentGroup] = []


class Fulfillment(BaseModel):
    id: str
    methods: list[FulfillmentMethod] = []


class UCPMessage(BaseModel):
    type: str
    code: str
    path: str | None = None
    content: str
    severity: str  # "recoverable" | "fatal"


class CheckoutSession(BaseModel):
    id: str
    status: SessionStatus
    currency: str
    buyer: Buyer | None = None
    line_items: list[LineItemResponse] = []
    fulfillment: list[Fulfillment] = []
    discounts: list[dict] = []
    totals: Totals
    messages: list[UCPMessage] = []
    links: dict[str, str]

    @model_validator(mode="before")
    @classmethod
    def _normalize_session(cls, data: Any):
        if not isinstance(data, dict):
            return data

        payload = data.get("checkout_session") or data.get("session")
        if isinstance(payload, dict):
            data = payload

        buyer = data.get("buyer")
        if isinstance(buyer, list):
            data["buyer"] = None

        line_items = data.get("line_items")
        if isinstance(line_items, list):
            data["line_items"] = [cls._normalize_line_item(item) for item in line_items if isinstance(item, dict)]

        fulfillment = data.get("fulfillment")
        data["fulfillment"] = cls._normalize_fulfillment(fulfillment)

        totals = data.get("totals")
        if isinstance(totals, dict):
            data["totals"] = cls._normalize_totals(totals)

        return data

    @staticmethod
    def _to_float(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    @classmethod
    def _normalize_line_item(cls, item: dict) -> dict:
        entry = dict(item)

        raw_id = entry.get("id")
        if isinstance(raw_id, str):
            digits = "".join(ch for ch in raw_id if ch.isdigit())
            if digits:
                try:
                    entry["id"] = int(digits)
                except ValueError:
                    pass

        details = entry.get("item")
        if isinstance(details, dict):
            entry.setdefault("product_id", details.get("product_id") or details.get("id"))
            entry.setdefault("sku", details.get("sku") or details.get("code") or "")
            entry.setdefault("title", details.get("title") or details.get("name") or "")
            entry.setdefault("stock_status", details.get("stock_status"))
            entry.setdefault("image", details.get("image"))

        entry["product_id"] = entry.get("product_id") or 0
        entry["sku"] = entry.get("sku") or ""
        entry["title"] = entry.get("title") or ""

        unit_price = entry.get("unit_price") or entry.get("price") or entry.get("subtotal")
        if isinstance(unit_price, dict):
            unit_price = unit_price.get("amount")
        entry["unit_price"] = cls._to_float(unit_price)

        total_price = entry.get("total_price") or entry.get("total") or entry.get("subtotal")
        if isinstance(total_price, dict):
            total_price = total_price.get("amount")
        entry["total_price"] = cls._to_float(total_price)

        entry["stock_status"] = cls._normalize_stock(entry.get("stock_status"))
        return entry

    @staticmethod
    def _normalize_stock(value: Any) -> str:
        if isinstance(value, bool):
            return "instock" if value else "outofstock"
        if isinstance(value, str):
            trimmed = value.strip().lower().replace(" ", "")
            if trimmed in {"instock", "in_stock"}:
                return "instock"
            if trimmed in {"outofstock", "out_of_stock"}:
                return "outofstock"
            return value
        return "instock"

    @classmethod
    def _normalize_fulfillment(cls, fulfillment: Any) -> list[dict]:
        if isinstance(fulfillment, list):
            return [cls._normalize_fulfillment_group(group) for group in fulfillment if isinstance(group, dict)]

        if isinstance(fulfillment, dict):
            groups = fulfillment.get("groups")
            if isinstance(groups, list) and groups:
                return [cls._normalize_fulfillment_group(group) for group in groups if isinstance(group, dict)]

            methods = fulfillment.get("methods")
            if isinstance(methods, list) and methods:
                normalized_methods = [cls._normalize_fulfillment_method(m) for m in methods if isinstance(m, dict)]
                return [
                    {
                        "id": fulfillment.get("id") or "shipping",
                        "type": fulfillment.get("type") or "shipping",
                        "label": fulfillment.get("label") or "Shipping",
                        "cost": cls._to_float(fulfillment.get("cost", 0)),
                        "methods": normalized_methods,
                    }
                ]

            return []

        return []

    @classmethod
    def _normalize_fulfillment_group(cls, group: dict) -> dict:
        normalized = dict(group)
        methods = normalized.get("methods")
        if isinstance(methods, list):
            normalized["methods"] = [cls._normalize_fulfillment_method(m) for m in methods if isinstance(m, dict)]
        else:
            normalized["methods"] = []
        return normalized

    @classmethod
    def _normalize_fulfillment_method(cls, method: dict) -> dict:
        normalized = dict(method)
        groups = normalized.get("groups")
        if isinstance(groups, list):
            normalized["groups"] = [cls._normalize_fulfillment_group_entry(g) for g in groups if isinstance(g, dict)]
        else:
            normalized["groups"] = []
        return normalized

    @classmethod
    def _normalize_fulfillment_group_entry(cls, group: dict) -> dict:
        normalized = dict(group)
        options = normalized.get("options")
        if isinstance(options, list):
            normalized["options"] = [cls._normalize_fulfillment_option(o) for o in options if isinstance(o, dict)]
        else:
            normalized["options"] = []
        return normalized

    @classmethod
    def _normalize_fulfillment_option(cls, option: dict) -> dict:
        normalized = dict(option)
        amount = normalized.get("amount") or normalized.get("price") or normalized.get("total")
        normalized["amount"] = cls._to_float(amount)
        normalized["label"] = normalized.get("label") or normalized.get("name") or "Shipping option"
        return normalized

    @classmethod
    def _normalize_totals(cls, totals: dict) -> dict:
        normalized = dict(totals)
        for key in ("subtotal", "shipping", "tax", "discount", "total"):
            value = normalized.get(key)
            if isinstance(value, dict):
                value = value.get("amount")
            normalized[key] = cls._to_float(value)
        return normalized


# ── §4.5  Payment ─────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    """
    Placeholder payment request.
    Both fields are optional — omit entirely for COD/manual payment.
    Set UCP_PAYMENT_TOKEN env var to activate payment token flow.
    See SPEC.md §3.5.
    """
    mandate: str | None = None       # AP2 mandate
    payment_token: str | dict[str, Any] | None = None  # PSP token or delegated intent


# ── §4.6  Product Catalog ─────────────────────────────────────────────────────

class ProductVariation(BaseModel):
    id: int
    attributes: list[str] = []
    sku: str
    price: float


class ProductCategory(BaseModel):
    id: int
    name: str
    slug: str


class ProductImages(BaseModel):
    featured: str | None = None
    gallery: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any):
        if isinstance(value, list):
            if not value:
                return {"featured": None, "gallery": []}
            # Deduplicate while preserving order
            seen = set()
            gallery = []
            for url in value:
                if url not in seen:
                    seen.add(url)
                    gallery.append(url)
            return {"featured": gallery[0], "gallery": gallery}
        return value


class Product(BaseModel):
    id: int
    title: str
    description: str
    sku: str
    price: float
    stock_status: str  # "instock" | "outofstock" | "onbackorder"
    images: ProductImages
    categories: list[ProductCategory] = []
    variations: list[ProductVariation] = []

    @model_validator(mode="before")
    @classmethod
    def _normalize_price(cls, data: Any):
        if not isinstance(data, dict):
            return data

        price = data.get("price")
        if isinstance(price, dict):
            amount = price.get("amount")
            try:
                data["price"] = float(amount)
            except (TypeError, ValueError):
                pass
        elif isinstance(price, str):
            try:
                data["price"] = float(price)
            except ValueError:
                pass

        status = data.get("stock_status")
        if isinstance(status, bool):
            data["stock_status"] = "instock" if status else "outofstock"
        elif isinstance(status, str):
            normalized = status.strip().lower().replace("_", "")
            if normalized in {"instock", "in stock"}:
                data["stock_status"] = "instock"
            elif normalized in {"outofstock", "outof stock"}:
                data["stock_status"] = "outofstock"

        return data


class Pagination(BaseModel):
    total: int
    pages: int
    current_page: int
    per_page: int

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: Any):
        if isinstance(data, dict):
            needs_copy = False
            updated = data

            if "pages" not in data and "page" in data:
                updated = dict(updated)
                updated.setdefault("pages", updated.get("total", 0))
                updated.setdefault("current_page", updated.get("page"))
                needs_copy = True

            if needs_copy:
                return updated

        return data


class ProductsResponse(BaseModel):
    products: list[Product]
    pagination: Pagination


# ── §4.7  Discovery Manifest ──────────────────────────────────────────────────

class UCPAuthMethod(BaseModel):
    type: str
    header: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None


class UCPServiceEndpoints(BaseModel):
    rest: str
    mcp: str | None = None


class UCPService(BaseModel):
    id: str
    endpoints: UCPServiceEndpoints
    capabilities: list[str]
    extensions: list[str] = []
    payment_handlers: list[str] = []


class UCPBusiness(BaseModel):
    name: str
    homepage: str | None = None


class UCPManifest(BaseModel):
    business: UCPBusiness
    services: list[UCPService]
    authentication: dict = {}

    @model_validator(mode="before")
    @classmethod
    def _normalize_manifest(cls, data: Any):
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        payload = normalized.pop("ucp", None)
        if isinstance(payload, dict):
            merged = dict(payload)
            merged.update(normalized)
            normalized = merged

        if "business" not in normalized and "merchant" in normalized:
            normalized = dict(normalized)
            normalized["business"] = normalized.pop("merchant")

        services = normalized.get("services")
        if isinstance(services, dict):
            normalized_services: list[dict[str, Any]] = []
            for service_id, entries in services.items():
                if isinstance(entries, dict):
                    entry_dicts = [entries]
                elif isinstance(entries, list):
                    entry_dicts = [e for e in entries if isinstance(e, dict)]
                else:
                    continue

                for entry in entry_dicts:
                    entry_copy = dict(entry)
                    entry_copy.setdefault("id", service_id)
                    normalized_services.append(entry_copy)

            normalized["services"] = normalized_services

        return normalized
