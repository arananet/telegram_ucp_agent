# Telegram UCP Agent — Specification

> **Spec-Kit document.** This file is the single source of truth for the project.
> All implementation decisions are traceable to sections below.
> When in doubt, the spec wins over the code.

**Version:** 1.0.0
**Date:** 2026-03-27
**Authors:** Eduardo Arana and Soda
**License:** MIT
**Repository:** [arananet/telegram_ucp_agent](https://github.com/arananet/telegram_ucp_agent)

---

## 1. Overview

### 1.1 Purpose

`telegram_ucp_agent` is a Telegram bot that enables users to browse a product catalog, manage a shopping cart, and complete a purchase — all within a Telegram conversation — by communicating with a [Universal Commerce Protocol (UCP)](https://ucp.dev) compliant merchant.

Its primary goal is **integration testing** of the [arananet/woocommerce_ucp_plugin](https://github.com/arananet/woocommerce_ucp_plugin), which exposes a WooCommerce store as a UCP merchant.

### 1.2 Scope

**In scope:**
- Product discovery and browsing (paginated catalog)
- Cart management (add/remove items, view cart)
- Full checkout flow (shipping address → shipping method → confirmation → order placed)
- Customer OAuth linking + profile autofill
- UCP session lifecycle management (create → update → complete / cancel)
- Railway-hosted webhook deployment

**Out of scope:**
- Real-time order tracking (webhooks from merchant → user)
- Multi-merchant discovery
- Admin commands

### 1.3 Hosting

The bot runs on [Railway](https://railway.app) in **webhook mode** (production) or **long-polling mode** (local development, controlled by `USE_POLLING=true`).

---

## 2. Conversation Flow

### 2.1 State Machine

```
/start
  └─→ [BROWSING]
        ├─ product selected          → [PRODUCT_DETAIL]
        │     ├─ "Add to cart"       → [CART]
        │     └─ "Back"              → [BROWSING]
        ├─ "View Cart" (if non-empty)→ [CART]
        └─ /cancel                   → END

[CART]
  ├─ "Checkout"                      → [CHECKOUT_ADDRESS]
  ├─ "Remove item" button            → [CART] (refreshed)
  ├─ "Continue Shopping"             → [BROWSING]
  └─ /cancel                         → END

[CHECKOUT_ADDRESS]  ← text input
  ├─ valid address                   → [CHECKOUT_SHIPPING]
  └─ invalid input                   → re-prompt with validation error

[CHECKOUT_SHIPPING]  ← inline keyboard
  ├─ shipping method selected        → [CHECKOUT_CONFIRM]
  └─ "Back"                          → [CHECKOUT_ADDRESS]

[CHECKOUT_CONFIRM]  ← inline keyboard
  ├─ "Confirm & Place Order"         → call complete_checkout_session
  │     ├─ success                   → [ORDER_DONE]
  │     └─ error (payment/stock)     → show error, stay in [CHECKOUT_CONFIRM]
  ├─ "Edit Cart"                     → [CART]
  └─ /cancel                         → call cancel_checkout_session → END

[ORDER_DONE]
  └─ "Start Over"                    → [BROWSING]

Standalone commands:
- `/link` → Initiates OAuth PKCE flow in DM; not part of ConversationHandler
- `/unlink` → Revokes stored OAuth tokens and clears linked profile
- `/start` double-checks whether the user has a stored OAuth token whenever the OAuth
  service is configured. If not, it immediately sends the same linking prompt as `/link`
  right after the welcome message so shoppers can authorize their store accounts before
  proceeding.
```

### 2.2 State Definitions

| State | Integer | Entry Trigger | Exit Triggers |
|---|---|---|---|
| `BROWSING` | 0 | `/start` or "Start Over" | Product tap, "View Cart" |
| `PRODUCT_DETAIL` | 1 | Product tap from catalog | "Add to cart", "Back" |
| `CART` | 2 | "Add to cart", "View Cart", "Edit Cart" | "Checkout", "Continue", /cancel |
| `CHECKOUT_ADDRESS` | 3 | "Checkout" from cart | Valid text input, /cancel |
| `CHECKOUT_SHIPPING` | 4 | Valid address submitted | Shipping selection, "Back" |
| `CHECKOUT_CONFIRM` | 5 | Shipping method selected | "Confirm", "Edit Cart", /cancel |
| `ORDER_DONE` | 6 | Successful `complete_checkout_session` | "Start Over" |

### 2.3 Timeout Behavior

- Conversations time out after **30 minutes** of inactivity.
- On timeout: if a checkout session is open (`session_id` in `user_data`), call `cancel_checkout_session`; then send a "Session expired" message.
- `context.user_data` is cleared on timeout and on `END`.

### 2.4 Cart Data Model (context.user_data)

```python
context.user_data = {
    "cart": [                          # list of {product_id, title, price, quantity}
        {"product_id": 42, "title": "Widget", "price": 9.99, "quantity": 2}
    ],
    "checkout_session_id": "chk_abc",  # set after create_checkout_session
    "shipping_address": {...},         # Address dict after CHECKOUT_ADDRESS
    "selected_shipping_id": "flat_1",  # fulfillment method ID
    "products_page": 1,                # current page in catalog
}
```

---

## 3. UCP Integration Contract

### 3.1 Merchant Discovery

**Endpoint:** `GET {UCP_BASE_URL}/../.well-known/ucp` (auto-derived `UCP_DISCOVERY_URL`)
**Auth:** None
**When called:** Once on startup; result cached for 1 hour (in-memory).
**Required capability:** `"checkout"` must appear in `services[0].capabilities`.
**Failure behaviour:** Log warning and continue; individual endpoint calls may still succeed.

### 3.2 Product Catalog

**Endpoint:** `GET {UCP_BASE_URL}/products`
**Auth:** None
**Parameters used:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | int | 1 | From `user_data["products_page"]` |
| `per_page` | int | 8 | Fits cleanly in inline keyboard |
| `search` | string | — | User text search (future) |

**Response fields consumed:** `products[].id`, `.title`, `.price`, `.stock_status`, `.images.featured`, `.categories`, `pagination.total`, `.pages`, `.current_page`.

### 3.3 Checkout Session Create

**Endpoint:** `POST {UCP_CHECKOUT_URL}`
**Auth:** `X-API-Key: {UCP_API_KEY}`
**Triggered:** When user taps "Checkout" from CART.
**Request body (§ CheckoutRequest):**

```json
{
  "checkout": {
    "line_items": [{"id": 42, "quantity": 2}],
    "buyer": null,
    "currency": null,
    "discount_codes": []
  }
}
```

**On `201`:** Store `session.id` in `user_data["checkout_session_id"]`.
**On `4xx`:** Show error message, stay in CART.

### 3.4 Checkout Session Update

**Endpoint:** `PUT {UCP_CHECKOUT_URL}/{id}`
**Auth:** `X-API-Key: {UCP_API_KEY}`
**Note:** Full replacement — send complete checkout object including all previously set fields.
**Triggered:** After shipping address is collected (CHECKOUT_ADDRESS → CHECKOUT_SHIPPING).
**Request body:** Full `CheckoutRequest` with buyer + shipping_address populated.

### 3.5 Checkout Session Complete

**Endpoint:** `POST {UCP_CHECKOUT_URL}/{id}/complete`
**Auth:** `X-API-Key: {UCP_API_KEY}`
**Triggered:** "Confirm & Place Order" in CHECKOUT_CONFIRM.
**Request body:**

```json
{
  "payment": {
    "payment_token": "<UCP_PAYMENT_TOKEN if set, else omitted>"
  }
}
```

If `UCP_PAYMENT_TOKEN` is not configured, the body is `{}` (relies on COD/manual gateway).
**On `200` + `status == "completed"`:** Proceed to ORDER_DONE.
**On `402`:** Payment failed — show error, stay in CHECKOUT_CONFIRM.
**On `409`:** Session not in `ready_for_complete` — re-fetch session and re-render.

### 3.6 Checkout Session Cancel

**Endpoint:** `POST {UCP_CHECKOUT_URL}/{id}/cancel`
**Auth:** `X-API-Key: {UCP_API_KEY}`
**Triggered:** User sends `/cancel` while in CHECKOUT_* states, or conversation timeout.
**Errors are swallowed** (best-effort cancel); always clear `user_data`.

### 3.7 HTTP Error Handling

| HTTP status | Action |
|---|---|
| `400` | Show first `messages[].content` or generic "Invalid request" |
| `401` | Log error + show "Authentication error — contact admin" |
| `402` | Show "Payment failed: {details}" |
| `404` | Session expired — clear `user_data`, restart |
| `409` | Re-fetch session, re-render current state |
| `429` | Show "Too many requests, please wait {retry_after}s" |
| `5xx` | Show "The store is temporarily unavailable, please try again" |
| Network error | Show "Could not reach the store, please try again" |

---

## 4. Data Models

All models live in `src/ucp/models.py` and use **Pydantic v2**.
Field names match the WooCommerce UCP plugin API exactly.

### 4.1 Address

```python
class Address(BaseModel):
    first_name: str
    last_name: str
    street_address: str
    city: str
    state: str
    postal_code: str
    country: str        # ISO 3166-1 alpha-2 (e.g. "US", "MX")
```

### 4.2 Buyer

```python
class Buyer(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    shipping_address: Address | None = None
    billing_address: Address | None = None
```

### 4.3 Line Items

```python
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
```

### 4.4 Checkout Request / Response

```python
class CheckoutRequest(BaseModel):
    line_items: list[LineItemRequest] = Field(min_length=1)
    buyer: Buyer | None = None
    currency: str | None = None
    discount_codes: list[str] = []

class SessionStatus(str, Enum):
    incomplete            = "incomplete"
    requires_escalation   = "requires_escalation"
    ready_for_complete    = "ready_for_complete"
    completed             = "completed"
    canceled              = "canceled"

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
    severity: str         # "recoverable" | "fatal"

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
```

### 4.5 Payment

```python
class PaymentRequest(BaseModel):
    mandate: str | None = None          # AP2 mandate
    payment_token: str | None = None    # Stripe or other gateway token
    # Both fields are optional; omit entirely for COD/manual payment
```

### 4.6 Product Catalog

```python
class ProductVariation(BaseModel):
    id: int
    attributes: list[str]
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
    stock_status: str       # "instock" | "outofstock" | "onbackorder"
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
```

### 4.7 Discovery Manifest

```python
class UCPAuthMethod(BaseModel):
    type: str                           # "api_key" | "oauth2"
    header: str | None = None          # e.g. "X-API-Key"
    authorization_url: str | None = None
    token_url: str | None = None

class UCPServiceEndpoints(BaseModel):
    rest: str
    mcp: str | None = None

class UCPService(BaseModel):
    id: str                            # e.g. "dev.ucp.shopping.v2026-01-23"
    endpoints: UCPServiceEndpoints
    capabilities: list[str]            # e.g. ["checkout"]
    extensions: list[str] = []
    payment_handlers: list[str] = []

class UCPBusiness(BaseModel):
    name: str
    homepage: str | None = None

class UCPManifest(BaseModel):
    business: UCPBusiness
    services: list[UCPService]
    authentication: dict = {}
```

---

## 5. Security Requirements

### 5.1 Secrets

- All secrets are loaded from environment variables only.
- `.env` is in `.gitignore` — never committed.
- Railway environment variables are set via the Railway dashboard.
- Required at startup (pydantic-settings raises `ValidationError` if missing):
  `TELEGRAM_BOT_TOKEN`, `UCP_BASE_URL`, `UCP_API_KEY`.
- OAuth linking additionally requires `UCP_CLIENT_ID`, `UCP_OAUTH_AUTHORIZE`, `UCP_OAUTH_TOKEN`,
  `UCP_REDIRECT_URI`, and `DB_URL` (token store). `TELEGRAM_WEBHOOK_SECRET` is required when
  `USE_POLLING=false`.

### 5.2 Webhook Verification

- Every incoming webhook POST must carry `X-Telegram-Bot-API-Secret-Token: {TELEGRAM_WEBHOOK_SECRET}`.
- python-telegram-bot's built-in `run_webhook()` handles this validation automatically.
- Requests without the correct token return HTTP 403.

### 5.3 Rate Limiting

- **Per `user_id`, in-memory**, implemented in `src/middleware/rate_limiter.py`.
- Default: **10 requests per 60 seconds**.
- On breach: reply with "Too many requests, please wait Xs" and return without processing.
- State is reset on bot restart (acceptable for this use case).

### 5.4 Input Validation

All user-provided text is validated before use. Rules (`src/middleware/validators.py`):

| Field | Rule |
|---|---|
| Product ID (from callback_data) | Positive integer, `1 ≤ id ≤ 9_999_999` |
| Quantity | Integer, `1 ≤ qty ≤ 99` |
| First / last name | Non-empty string, max 100 chars, `[A-Za-z \-']+` |
| Street address | Non-empty, max 200 chars |
| City | Non-empty, max 100 chars, `[A-Za-z \-']+` |
| State / province | Non-empty, max 100 chars |
| Postal code | Non-empty, max 20 chars, `[A-Z0-9 \-]+` |
| Country | Exactly 2 uppercase letters (ISO 3166-1 alpha-2) |

### 5.5 Logging

- Log level controlled by `LOG_LEVEL` env var.
- **Never log** full names, email addresses, phone numbers, or street addresses — log `user_id` and session IDs only.
- Pydantic validation errors on UCP responses are logged at `WARNING` level with the endpoint URL but not the full response body.

---

## 6. Configuration

All settings are defined in `src/config.py` using `pydantic-settings`.
Values are read from environment variables (case-insensitive); `.env` file is auto-loaded in dev.

| Variable | Type | Required | Default | Description |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | str | Yes | — | BotFather token |
| `TELEGRAM_WEBHOOK_SECRET` | str | If not polling | — | Webhook verification token |
| `TELEGRAM_WEBHOOK_URL` | str | If not polling | — | Public HTTPS base URL (no trailing slash) |
| `UCP_BASE_URL` | str | Yes | — | `https://retrohardware.arananet.net/wp-json/ucp/v1` |
| `UCP_CHECKOUT_URL` | str | No | derived | Override for checkout sessions endpoint |
| `UCP_CUSTOMER_PROFILE_URL` | str | No | derived | `.../customers/me` endpoint |
| `UCP_DISCOVERY_URL` | str | No | derived | `.../.well-known/ucp` endpoint |
| `UCP_API_KEY` | str | Yes | — | X-API-Key for UCP authenticated endpoints |
| `UCP_CLIENT_ID` | str | If OAuth | — | OAuth client ID from WooCommerce |
| `UCP_CLIENT_SECRET` | str | Optional | — | OAuth client secret (blank when PKCE only) |
| `UCP_REDIRECT_URI` | str | If OAuth | — | HTTPS callback URL handled by this bot |
| `UCP_OAUTH_SCOPE` | str | If OAuth | `checkout` | Scope parameter for authorize/token |
| `UCP_OAUTH_AUTHORIZE` | str | If OAuth | — | `.../oauth/authorize` endpoint |
| `UCP_OAUTH_TOKEN` | str | If OAuth | — | `.../oauth/token` endpoint |
| `UCP_OAUTH_REVOKE` | str | If OAuth | — | `.../oauth/revoke` endpoint |
| `UCP_PAYMENT_TOKEN` | str | No | None | Payment token for complete endpoint |
| `DB_URL` | str | If OAuth | — | Database DSN for storing OAuth tokens/sessions |
| `STRIPE_SECRET_KEY` | str | Optional | — | PSP secret used to mint payment tokens |
| `STRIPE_WEBHOOK_SECRET` | str | Optional | — | Stripe webhook signature |
| `AP2_CREDENTIALS_JSON` | str | Optional | — | Wallet/AP2 credential blob |
| `PORT` | int | No | 8080 | HTTP server port (Railway sets this) |
| `USE_POLLING` | bool | No | false | Use long-polling instead of webhook |
| `LOG_LEVEL` | str | No | INFO | Python logging level |
| `RATE_LIMIT_REQUESTS` | int | No | 10 | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | int | No | 60 | Rate limit window in seconds |

---

## 7. Deployment

### 7.1 Railway (Production)

1. Push to GitHub → Railway auto-deploys from main branch.
2. Set all required env vars in Railway dashboard (Settings → Variables).
3. `TELEGRAM_WEBHOOK_URL` = Railway's public domain, e.g. `https://telegram-ucp-agent.up.railway.app`.
4. `USE_POLLING=false` (default).
5. Health check: `GET /health` → `200 {"status": "ok"}`.
6. Bot registers its webhook URL on startup via `run_webhook()`.

### 7.2 Local Development (Polling)

```bash
cp .env.example .env
# Edit .env: set TELEGRAM_BOT_TOKEN, UCP_BASE_URL, UCP_API_KEY, USE_POLLING=true

pip install -e ".[dev]"
python -m src.main
```

No HTTPS or ngrok required in polling mode.

### 7.3 railway.toml

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "python -m src.main"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 5
```

---

## 8. Testing Strategy

Tests live in `tests/` and use **pytest + pytest-asyncio**.
Tests are the machine-readable proof that the implementation conforms to this spec.

| Test file | What it proves |
|---|---|
| `test_ucp_models.py` | Every Pydantic model correctly parses the shapes defined in §4 |
| `test_ucp_client.py` | Client sends correct HTTP requests and handles all error codes from §3.7 |
| `test_validators.py` | All validation rules from §5.4 pass valid input and reject invalid input |
| `test_handlers.py` | State transitions match the state machine in §2 |

### 8.1 Running Tests

```bash
pytest tests/ -v
```

### 8.2 Spec Compliance Checklist

Before each release, verify:

- [ ] `GET /.well-known/ucp` returns a valid `UCPManifest` with `"checkout"` capability
- [ ] `GET /wp-json/ucp/v1/products` returns products parseable by `ProductsResponse`
- [ ] Full happy-path flow works end-to-end (see §1 Integration Test)
- [ ] All validator rules from §5.4 enforced
- [ ] No secrets appear in logs
- [ ] `/health` returns `200`
- [ ] Webhook secret verified (test with wrong token → 403)
### 2.5 OAuth Linking Flow

1. User sends `/link`.
2. Bot generates a PKCE code-verifier, persists a pending OAuth session (state, verifier, user_id),
   and replies with a button linking to `UCP_OAUTH_AUTHORIZE` with the configured scope and redirect_uri.
3. Merchant redirects back to `UCP_REDIRECT_URI` → handled by `GET /oauth/callback` on the bot.
4. Callback exchanges the authorization code for access/refresh tokens at `UCP_OAUTH_TOKEN`, stores
   them alongside their expiry and scope, fetches `UCP_CUSTOMER_PROFILE_URL` using the access token,
   and notifies the Telegram user.
5. During `/link`, if tokens already exist they are overwritten.
6. `/unlink` deletes any stored token + cached profile and (best-effort) calls
   `UCP_OAUTH_REVOKE` with the refresh token. Response errors are logged but not shown to the user.

Autofill rules:
- When a user with a linked profile starts checkout, address collection is skipped and the stored
  profile populates `Buyer` and `Address` fields automatically.
- If the stored profile is missing required fields, the bot falls back to manual prompts.
- Access tokens are refreshed automatically using the stored refresh token when they expire.
### 3.8 OAuth + Customer Profiles

- **Authorize endpoint:** `GET {UCP_OAUTH_AUTHORIZE}` (external browser). Parameters: `response_type=code`,
  `client_id={UCP_CLIENT_ID}`, `redirect_uri={UCP_REDIRECT_URI}`, `scope={UCP_OAUTH_SCOPE}`,
  `code_challenge`, `code_challenge_method=S256`, `state` (opaque string tying to Telegram user).
- **Token exchange:** `POST {UCP_OAUTH_TOKEN}` with `application/x-www-form-urlencoded` payload:

  | Field | Value |
  |---|---|
  | `grant_type` | `authorization_code` |
  | `client_id` | `UCP_CLIENT_ID` |
  | `client_secret` | optional; include if `UCP_CLIENT_SECRET` set |
  | `redirect_uri` | `UCP_REDIRECT_URI` |
  | `code` | value received at callback |
  | `code_verifier` | stored PKCE verifier |

  Response shape:

  ```json
  {
    "access_token": "ucp_access_...",
    "refresh_token": "ucp_refresh_...",
    "expires_in": 3600,
    "token_type": "Bearer",
    "scope": "checkout"
  }
  ```

- **Refresh:** `POST {UCP_OAUTH_TOKEN}` with `grant_type=refresh_token`, `refresh_token`, `scope`, and
  optional `client_secret`. Triggered automatically when cached access tokens expire.
- **Revoke:** `POST {UCP_OAUTH_REVOKE}` with `token={refresh_token}` and `client_id` (and
  `client_secret` when provided). Errors are logged but do not block unlinking.
- **Customer profile:** `GET {UCP_CUSTOMER_PROFILE_URL}` with
  `Authorization: Bearer {access_token}`. Expected fields:

  ```json
  {
    "id": 123,
    "email": "buyer@example.com",
    "first_name": "Buyer",
    "last_name": "Example",
    "shipping": {
      "address_1": "123 Main",
      "city": "Springfield",
      "state": "IL",
      "postcode": "62701",
      "country": "US"
    }
  }
  ```

  Missing fields result in a fallback to manual address prompts (SPEC §2.5).
