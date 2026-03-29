# Telegram UCP Agent

A Telegram bot that acts as a shopping agent using the [Universal Commerce Protocol (UCP)](https://ucp.dev). Users can browse products, manage a cart, and complete purchases — all within a Telegram conversation — by communicating with a UCP-compliant WooCommerce store.

**Authors:** Eduardo Arana and Soda
**License:** MIT
**Protocol:** [UCP](https://ucp.dev)
**Merchant plugin:** [arananet/woocommerce_ucp_plugin](https://github.com/arananet/woocommerce_ucp_plugin)
**Hosting:** [Railway](https://railway.app)

> This project follows the **spec-kit approach** — see `SPEC.md` for the full specification that drives all implementation decisions.

---

## Features

- Product catalog browsing with pagination
- Add/remove items from cart
- Full checkout flow: shipping address → shipping method → confirmation
- Optional OAuth linking to autofill customer profiles
- UCP session lifecycle management (create → update → complete / cancel)
- Webhook mode for Railway, polling mode for local development
- Input validation and per-user rate limiting

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A WooCommerce store with [woocommerce_ucp_plugin](https://github.com/arananet/woocommerce_ucp_plugin) installed

### Setup

```bash
git clone https://github.com/arananet/telegram_ucp_agent
cd telegram_ucp_agent

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env and set:
#   TELEGRAM_BOT_TOKEN=...
#   UCP_BASE_URL=https://retrohardware.arananet.net/wp-json/ucp/v1
#   UCP_API_KEY=...
#   USE_POLLING=true

# Run
python -m src.main
```

### Run Tests

```bash
pytest tests/ -v
```

---

## Deployment on Railway

1. Fork/push this repo to GitHub.
2. Create a new Railway project and link the repo.
3. Set the following environment variables in Railway dashboard (Settings → Variables):

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Random secret string |
| `TELEGRAM_WEBHOOK_URL` | Your Railway public URL (e.g. `https://your-app.up.railway.app`) |
| `UCP_BASE_URL` | WooCommerce UCP REST base (e.g. `https://retrohardware.arananet.net/wp-json/ucp/v1`) |
| `UCP_API_KEY` | UCP API key from plugin settings |
| `UCP_PAYMENT_TOKEN` | *(Optional)* Payment token for gateway; omit for COD |
| `UCP_CLIENT_ID` | *(OAuth)* Client ID from WooCommerce UCP OAuth page |
| `UCP_CLIENT_SECRET` | *(OAuth, optional)* Only when WooCommerce requires a secret |
| `UCP_REDIRECT_URI` | *(OAuth)* HTTPS callback handled by this bot (e.g. `https://bot.example.com/oauth/callback`) |
| `UCP_OAUTH_SCOPE` | *(OAuth)* Typically `checkout` |
| `UCP_OAUTH_AUTHORIZE` | *(OAuth)* `https://retrohardware.arananet.net/wp-json/ucp/v1/oauth/authorize` |
| `UCP_OAUTH_TOKEN` | *(OAuth)* `https://retrohardware.arananet.net/wp-json/ucp/v1/oauth/token` |
| `UCP_OAUTH_REVOKE` | *(OAuth)* `https://retrohardware.arananet.net/wp-json/ucp/v1/oauth/revoke` |
| `DB_URL` | *(OAuth)* Database DSN for storing OAuth tokens (e.g. `sqlite:///tokens.db` or Postgres URL) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | *(Optional)* PSP credentials for generating `payment_token` values |
| `AP2_CREDENTIALS_JSON` | *(Optional)* JSON blob for wallet mandates |
| `LOG_LEVEL` | `INFO` (default) |

4. Railway auto-deploys from main branch. The bot registers its webhook on startup.
5. Health check: `GET /health` → `200 {"status": "ok"}`

---

## Project Structure

```
telegram_ucp_agent/
├── SPEC.md                      # Master specification (spec-kit)
├── src/
│   ├── main.py                  # Entry point
│   ├── config.py                # Environment settings (pydantic-settings)
│   ├── oauth/
│   │   ├── handlers.py          # Tornado callback handler
│   │   ├── pkce.py              # PKCE helpers
│   │   └── service.py           # OAuth orchestration + customer profiles
│   ├── bot/
│   │   ├── application.py       # Telegram Application wiring
│   │   ├── states.py            # ConversationHandler state constants
│   │   ├── keyboards.py         # InlineKeyboard factory functions
│   │   └── handlers/
│   │       ├── start.py         # /start, /help, /cancel
│   │       ├── catalog.py       # Product browsing
│   │       ├── cart.py          # Cart management
│   │       └── checkout.py      # Checkout flow
│   ├── ucp/
│   │   ├── client.py            # Async UCP HTTP client
│   │   ├── models.py            # Pydantic v2 UCP models
│   │   └── discovery.py         # /.well-known/ucp manifest cache
│   └── middleware/
│       ├── rate_limiter.py      # Per-user rate limiting
│       └── validators.py        # Input validation
│   └── storage/
│       └── token_store.py       # OAuth token + state persistence
└── tests/
    ├── test_ucp_models.py
    ├── test_ucp_client.py
    ├── test_validators.py
    └── test_rate_limiter.py
```

---

## UCP Endpoints Used

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/.well-known/ucp` | No | Merchant discovery |
| `GET` | `/wp-json/ucp/v1/products` | No | Product catalog |
| `POST` | `/wp-json/ucp/v1/checkout-sessions` | `X-API-Key` | Create session |
| `GET` | `/wp-json/ucp/v1/checkout-sessions/{id}` | `X-API-Key` | Get session |
| `PUT` | `/wp-json/ucp/v1/checkout-sessions/{id}` | `X-API-Key` | Update session |
| `POST` | `/wp-json/ucp/v1/checkout-sessions/{id}/complete` | `X-API-Key` | Place order |
| `POST` | `/wp-json/ucp/v1/checkout-sessions/{id}/cancel` | `X-API-Key` | Cancel order |
| `GET` | `/wp-json/ucp/v1/customers/me` | `Bearer {access_token}` | Fetch linked customer profile |
| `POST` | `/wp-json/ucp/v1/oauth/token` | — | Exchange / refresh OAuth tokens |
| `POST` | `/wp-json/ucp/v1/oauth/revoke` | — | Revoke refresh tokens |

Authentication: `X-API-Key: {UCP_API_KEY}` header.

---

## Spec-Kit Approach

This project follows spec-driven development. `SPEC.md` is the authoritative document:
- **§2** defines the conversation state machine
- **§3** specifies the UCP integration contract (exact request/response shapes + OAuth flow)
- **§4** defines all Pydantic data models
- **§5** lists security requirements
- **§6** documents all configuration variables
- **§7** covers deployment
- **§8** defines the testing strategy

Code changes should start with a spec update when the behaviour changes.
