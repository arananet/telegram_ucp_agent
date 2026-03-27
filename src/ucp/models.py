"""
src/ucp/models.py
─────────────────
Pydantic v2 models for the Universal Commerce Protocol (UCP).

Field names match the WooCommerce UCP plugin API exactly (SPEC.md §4).
These models are the canonical data types for the entire application.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── §4.1  Address ─────────────────────────────────────────────────────────────

class Address(BaseModel):
    first_name: str
    last_name: str
    street_address: str
    city: str
    state: str
    postal_code: str
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

class LineItemRequest(BaseModel):
    id: int
    quantity: int = Field(gt=0)


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


class FulfillmentMethod(BaseModel):
    id: str
    label: str
    cost: float
    selected: bool


class Fulfillment(BaseModel):
    id: str
    type: str
    label: str
    cost: float
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


# ── §4.5  Payment ─────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    """
    Placeholder payment request.
    Both fields are optional — omit entirely for COD/manual payment.
    Set UCP_PAYMENT_TOKEN env var to activate payment token flow.
    See SPEC.md §3.5.
    """
    mandate: str | None = None       # AP2 mandate
    payment_token: str | None = None  # Stripe or other gateway token


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


class Pagination(BaseModel):
    total: int
    pages: int
    current_page: int
    per_page: int


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
