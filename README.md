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
#   UCP_MERCHANT_URL=https://your-woocommerce-store.example.com
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
| `WEBHOOK_URL` | Your Railway public URL (e.g. `https://your-app.up.railway.app`) |
| `UCP_MERCHANT_URL` | WooCommerce store base URL |
| `UCP_API_KEY` | UCP API key from plugin settings |
| `UCP_PAYMENT_TOKEN` | *(Optional)* Payment token for gateway; omit for COD |
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
| `POST` | `/wp-json/ucp/v1/checkout-sessions` | Yes | Create session |
| `GET` | `/wp-json/ucp/v1/checkout-sessions/{id}` | Yes | Get session |
| `PUT` | `/wp-json/ucp/v1/checkout-sessions/{id}` | Yes | Update session |
| `POST` | `/wp-json/ucp/v1/checkout-sessions/{id}/complete` | Yes | Place order |
| `POST` | `/wp-json/ucp/v1/checkout-sessions/{id}/cancel` | Yes | Cancel order |

Authentication: `X-API-Key: {UCP_API_KEY}` header.

---

## Spec-Kit Approach

This project follows spec-driven development. `SPEC.md` is the authoritative document:
- **§2** defines the conversation state machine
- **§3** specifies the UCP integration contract (exact request/response shapes)
- **§4** defines all Pydantic data models
- **§5** lists security requirements
- **§6** documents all configuration variables
- **§7** covers deployment
- **§8** defines the testing strategy

Code changes should start with a spec update when the behaviour changes.
