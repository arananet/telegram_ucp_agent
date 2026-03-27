"""
src/bot/handlers/checkout.py
─────────────────────────────
Full checkout flow (SPEC.md §2.1 — CHECKOUT_* and ORDER_DONE states).

Flow:
  CART → action_checkout
    → create_checkout_session
    → prompt for address (CHECKOUT_ADDRESS)
    → text input → validate → update_checkout_session
    → show shipping options (CHECKOUT_SHIPPING)
    → ship_{id} → CHECKOUT_CONFIRM
    → action_confirm → complete_checkout_session → ORDER_DONE

Address is collected as a multi-step guided text flow.
Each address field is prompted one at a time, stored in
context.user_data["address_input"], then assembled into an Address.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.bot.keyboards import confirm_keyboard, order_done_keyboard, shipping_keyboard
from src.bot.states import State
from src.ucp.client import UCPClient, UCPError
from src.ucp.models import Address, Buyer, CheckoutRequest, LineItemRequest, PaymentRequest, SessionStatus

logger = logging.getLogger(__name__)

# Address field collection order
_ADDRESS_FIELDS = [
    ("first_name",     "your first name"),
    ("last_name",      "your last name"),
    ("street_address", "your street address"),
    ("city",           "your city"),
    ("state",          "your state or province"),
    ("postal_code",    "your postal / ZIP code"),
    ("country",        "your country (2-letter code, e.g. US, MX, GB)"),
]

_VALIDATORS = {
    "first_name":     ("validate_name",        {"field": "First name"}),
    "last_name":      ("validate_name",        {"field": "Last name"}),
    "street_address": ("validate_street",      {}),
    "city":           ("validate_city",        {}),
    "state":          ("validate_state",       {}),
    "postal_code":    ("validate_postal_code", {}),
    "country":        ("validate_country",     {}),
}


def _next_address_field(address_input: dict) -> str | None:
    """Return the name of the next missing address field, or None if complete."""
    for field, _ in _ADDRESS_FIELDS:
        if field not in address_input:
            return field
    return None


def _format_session_summary(session, cart: list[dict]) -> str:
    lines = ["*Order Summary*\n"]
    for item in session.line_items:
        lines.append(f"• {item.title} x{item.quantity} — ${item.total_price:.2f}")

    if session.fulfillment:
        for group in session.fulfillment:
            for method in group.methods:
                if method.selected:
                    lines.append(f"\nShipping: {method.label} — ${method.cost:.2f}")
                    break

    t = session.totals
    lines.append(f"\nSubtotal: ${t.subtotal:.2f}")
    if t.discount:
        lines.append(f"Discount: -${t.discount:.2f}")
    lines.append(f"Shipping: ${t.shipping:.2f}")
    lines.append(f"Tax: ${t.tax:.2f}")
    lines.append(f"*Total: ${t.total:.2f} {session.currency}*")
    return "\n".join(lines)


# ── Step 1: Initiate checkout ─────────────────────────────────────────────────

async def on_start_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_checkout — create UCP session and start address collection."""
    query = update.callback_query
    await query.answer()

    cart: list[dict] = context.user_data.get("cart", [])
    if not cart:
        await query.answer("Your cart is empty.", show_alert=True)
        return State.CART

    ucp: UCPClient = context.bot_data["ucp_client"]
    line_items = [LineItemRequest(id=item["product_id"], quantity=item["quantity"]) for item in cart]
    checkout_req = CheckoutRequest(line_items=line_items)

    try:
        session = await ucp.create_checkout_session(checkout_req)
    except UCPError as exc:
        await query.edit_message_text(f"Could not start checkout: {exc.message}\n\nPlease try again.")
        return State.CART

    context.user_data["checkout_session_id"] = session.id
    context.user_data["address_input"] = {}
    logger.info("user_id=%s created session_id=%s", query.from_user.id, session.id)

    return await _prompt_next_address_field(update, context)


# ── Step 2: Collect address fields ───────────────────────────────────────────

async def _prompt_next_address_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user for the next missing address field."""
    address_input: dict = context.user_data.get("address_input", {})
    field = _next_address_field(address_input)

    if field is None:
        return await _submit_address(update, context)

    _, label = next(f for f in _ADDRESS_FIELDS if f[0] == field)
    text = f"Please enter {label}:"

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    elif update.message:
        await update.message.reply_text(text)

    return State.CHECKOUT_ADDRESS


async def on_address_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input during address collection."""
    text = update.message.text.strip()
    address_input: dict = context.user_data.setdefault("address_input", {})
    field = _next_address_field(address_input)

    if not field:
        return await _submit_address(update, context)

    # Validate
    validator_name, validator_kwargs = _VALIDATORS[field]
    from src.middleware import validators as v_module
    validator = getattr(v_module, validator_name)
    ok, err = validator(text, **validator_kwargs)

    if not ok:
        await update.message.reply_text(f"{err}\n\nPlease try again:")
        return State.CHECKOUT_ADDRESS

    # Normalise country to uppercase
    if field == "country":
        text = text.upper()

    address_input[field] = text
    return await _prompt_next_address_field(update, context)


async def _submit_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """All address fields collected — update the checkout session."""
    address_input: dict = context.user_data["address_input"]
    shipping_address = Address(**address_input)

    cart: list[dict] = context.user_data.get("cart", [])
    line_items = [LineItemRequest(id=i["product_id"], quantity=i["quantity"]) for i in cart]
    buyer = Buyer(
        first_name=address_input["first_name"],
        last_name=address_input["last_name"],
        shipping_address=shipping_address,
        billing_address=shipping_address,
    )
    checkout_req = CheckoutRequest(line_items=line_items, buyer=buyer)

    session_id: str = context.user_data["checkout_session_id"]
    ucp: UCPClient = context.bot_data["ucp_client"]

    try:
        session = await ucp.update_checkout_session(session_id, checkout_req)
    except UCPError as exc:
        msg = f"Could not save address: {exc.message}"
        if update.message:
            await update.message.reply_text(msg)
        return State.CHECKOUT_ADDRESS

    context.user_data["checkout_session"] = session.model_dump()
    logger.info("user_id=%s updated session_id=%s with address", update.effective_user.id, session_id)

    return await _show_shipping(update, context, session)


# ── Step 3: Select shipping method ────────────────────────────────────────────

async def _show_shipping(update, context, session) -> int:
    if not session.fulfillment:
        await _reply_text(update, "No shipping options available. Please contact the store.")
        return State.CHECKOUT_ADDRESS

    kb = shipping_keyboard(session.fulfillment)
    text = "Please select a shipping method:"
    await _reply_text(update, text, reply_markup=kb)
    return State.CHECKOUT_SHIPPING


async def on_shipping_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: ship_{id} — store selected shipping method and show summary."""
    query = update.callback_query
    await query.answer()

    method_id = query.data.split("_", 1)[1]
    context.user_data["selected_shipping_id"] = method_id

    # Re-fetch session to get accurate totals with the selected method
    session_id: str = context.user_data["checkout_session_id"]
    ucp: UCPClient = context.bot_data["ucp_client"]

    try:
        session = await ucp.get_checkout_session(session_id)
    except UCPError as exc:
        await query.edit_message_text(f"Could not load order summary: {exc.message}")
        return State.CHECKOUT_SHIPPING

    context.user_data["checkout_session"] = session.model_dump()
    cart: list[dict] = context.user_data.get("cart", [])
    summary = _format_session_summary(session, cart)

    await query.edit_message_text(summary, reply_markup=confirm_keyboard(), parse_mode="Markdown")
    return State.CHECKOUT_CONFIRM


async def on_back_to_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_back from shipping → re-collect address."""
    query = update.callback_query
    await query.answer()
    context.user_data["address_input"] = {}
    return await _prompt_next_address_field(update, context)


# ── Step 4: Confirm & place order ─────────────────────────────────────────────

async def on_confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_confirm — complete the checkout session."""
    query = update.callback_query
    await query.answer("Placing your order…")

    session_id: str = context.user_data["checkout_session_id"]
    ucp: UCPClient = context.bot_data["ucp_client"]

    # Build payment request from config (placeholder / COD)
    settings = context.bot_data["settings"]
    payment: PaymentRequest | None = None
    if settings.ucp_payment_token:
        payment = PaymentRequest(payment_token=settings.ucp_payment_token)

    try:
        session = await ucp.complete_checkout_session(session_id, payment)
    except UCPError as exc:
        if exc.status_code == 409:
            # Session state changed — re-fetch and re-render
            try:
                session = await ucp.get_checkout_session(session_id)
                cart = context.user_data.get("cart", [])
                summary = _format_session_summary(session, cart)
                await query.edit_message_text(
                    f"Order state changed. Current summary:\n\n{summary}",
                    reply_markup=confirm_keyboard(),
                    parse_mode="Markdown",
                )
            except UCPError:
                await query.edit_message_text("Could not retrieve order status. Please try again.")
        else:
            await query.edit_message_text(
                f"Could not place order: {exc.message}\n\nTap Confirm to retry or Cancel to abort.",
                reply_markup=confirm_keyboard(),
            )
        return State.CHECKOUT_CONFIRM

    if session.status != SessionStatus.completed:
        await query.edit_message_text(
            f"Unexpected session status: {session.status}. Please contact support.",
        )
        return State.CHECKOUT_CONFIRM

    logger.info(
        "user_id=%s completed session_id=%s total=%.2f %s",
        query.from_user.id, session_id, session.totals.total, session.currency,
    )

    context.user_data.clear()
    context.user_data["last_order_id"] = session.id

    text = (
        f"*Order placed successfully!*\n\n"
        f"Order reference: `{session.id}`\n"
        f"Total paid: *${session.totals.total:.2f} {session.currency}*\n\n"
        "Thank you for your purchase!"
    )
    await query.edit_message_text(text, reply_markup=order_done_keyboard(), parse_mode="Markdown")
    return State.ORDER_DONE


async def on_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_cancel — cancel checkout session and end conversation."""
    query = update.callback_query
    await query.answer()

    session_id: str | None = context.user_data.get("checkout_session_id")
    if session_id:
        ucp: UCPClient = context.bot_data["ucp_client"]
        try:
            await ucp.cancel_checkout_session(session_id)
        except UCPError:
            pass

    context.user_data.clear()
    await query.edit_message_text("Order cancelled. Send /start to shop again.")
    return ConversationHandler.END


async def on_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_restart — start a new shopping session from ORDER_DONE."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    from src.bot.handlers.catalog import show_catalog
    return await show_catalog(update, context)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _reply_text(update: Update, text: str, **kwargs) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(text, **kwargs)
    elif update.message:
        await update.message.reply_text(text, **kwargs)
