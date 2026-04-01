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

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from src.bot.keyboards import confirm_keyboard, order_done_keyboard, shipping_keyboard
from src.bot.states import State
from src.oauth.service import OAuthService
from src.ucp.client import UCPClient, UCPError
from src.ucp.models import (
    Address,
    Buyer,
    CheckoutRequest,
    CheckoutSession,
    LineItemRequest,
    PaymentRequest,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# Address field collection order: (field, prompt text, display label)
_ADDRESS_FIELDS = [
    ("email", "your email address", "Email"),
    ("first_name", "your first name", "First name"),
    ("last_name", "your last name", "Last name"),
    ("address_1", "your street address", "Street address"),
    ("city", "your city", "City"),
    ("state", "your state or province", "State / Province"),
    ("postcode", "your postal / ZIP code", "Postal code"),
    ("country", "your country (2-letter code, e.g. US, MX, GB)", "Country"),
]

_VALIDATORS = {
    "email":          ("validate_email",       {}),
    "first_name":     ("validate_name",        {"field": "First name"}),
    "last_name":      ("validate_name",        {"field": "Last name"}),
    "address_1":      ("validate_street",      {}),
    "city":           ("validate_city",        {}),
    "state":          ("validate_state",       {}),
    "postcode":       ("validate_postal_code", {}),
    "country":        ("validate_country",     {}),
}


def _next_address_field(address_input: dict) -> str | None:
    """Return the name of the next missing address field, or None if complete."""
    for field, _, _ in _ADDRESS_FIELDS:
        if field not in address_input:
            return field
    return None


def _address_field_index(field_name: str) -> int:
    for idx, (field, _, _) in enumerate(_ADDRESS_FIELDS):
        if field == field_name:
            return idx
    return -1


async def _auto_provision_payment_token(
    session: CheckoutSession,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Attempt to create a delegated PSP token via /payments/intent."""
    settings = context.bot_data["settings"]
    if settings.ucp_payment_token:
        return

    if context.user_data.get("payment_token"):
        return

    totals = session.totals
    if not totals or totals.total <= 0:
        return

    ucp: UCPClient = context.bot_data["ucp_client"]
    try:
        intent = await ucp.create_payment_intent(
            amount=totals.total,
            currency=session.currency,
            gateway=settings.ucp_payment_gateway,
        )
    except UCPError as exc:
        logger.info("Delegated payment intent failed: %s", exc.message)
        return

    intent_status = intent.get("status")
    ready_statuses = {"requires_capture", "requires_confirmation", "processing", "succeeded"}
    if intent_status and intent_status not in ready_statuses:
        logger.info("Delegated intent not ready (status=%s); falling back to manual token.", intent_status)
        return

    token_payload = intent.get("payment_token")
    if token_payload:
        context.user_data["payment_token"] = token_payload
        context.user_data["auto_payment_intent"] = intent


def _format_address_progress(address_input: dict) -> str:
    lines: list[str] = []
    for field, _, display in _ADDRESS_FIELDS:
        value = address_input.get(field)
        if value:
            lines.append(f"✅ {display}: {value}")
        else:
            lines.append(f"⬜ {display}: pending")
    return "\n".join(lines)


def _format_session_summary(session, cart: list[dict]) -> str:
    lines = ["*Order Summary*\n"]
    curr = session.currency
    for item in session.line_items:
        lines.append(f"• {item.title} x{item.quantity} — {curr} {item.total_price:.2f}")

    if session.fulfillment:
        for block in session.fulfillment:
            for method in block.methods:
                for group in method.groups:
                    selected = group.selected_option_id
                    if not selected:
                        continue
                    option = next((opt for opt in group.options if opt.id == selected), None)
                    if option:
                        lines.append(
                            f"\nShipping: {option.label} — {session.currency} {option.amount:.2f}"
                        )
                        break

    t = session.totals
    lines.append(f"\nSubtotal: {curr} {t.subtotal:.2f}")
    if t.discount:
        lines.append(f"Discount: -{curr} {t.discount:.2f}")
    lines.append(f"Shipping: {curr} {t.shipping:.2f}")
    lines.append(f"Tax: {curr} {t.tax:.2f}")
    lines.append(f"*Total: {curr} {t.total:.2f} {session.currency}*")
    return "\n".join(lines)


def _profile_to_address_input(profile: dict | None) -> dict[str, str] | None:
    if not profile:
        return None

    shipping = profile.get("shipping") or profile.get("shipping_address") or {}
    billing = profile.get("billing") or profile.get("billing_address") or {}
    source = shipping or billing
    if not source:
        return None

    address = {
        "email": profile.get("email"),
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "address_1": source.get("address_1"),
        "city": source.get("city"),
        "state": source.get("state"),
        "postcode": source.get("postcode"),
        "country": (source.get("country") or "").upper(),
    }

    if any(not address.get(field) for field, *_ in _ADDRESS_FIELDS if field != "country"):
        return None
    if not address["country"]:
        return None
    return address


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

    oauth_service: OAuthService | None = context.bot_data.get("oauth_service")
    if oauth_service:
        profile = await oauth_service.get_profile(query.from_user.id)
        autofill = _profile_to_address_input(profile)
        if autofill:
            context.user_data["address_input"] = autofill
            logger.info(
                "user_id=%s autofilled checkout session %s from profile",
                query.from_user.id,
                session.id,
            )
            return await _submit_address(update, context)

    return await _prompt_next_address_field(update, context)


# ── Step 2: Collect address fields ───────────────────────────────────────────

async def _prompt_next_address_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the user for the next missing address field."""
    address_input: dict = context.user_data.get("address_input", {})
    field = _next_address_field(address_input)

    if field is None:
        return await _submit_address(update, context)

    idx = _address_field_index(field)
    prompt_field = _ADDRESS_FIELDS[idx]
    _, prompt_text, display_label = prompt_field
    step = idx + 1
    total = len(_ADDRESS_FIELDS)

    progress = _format_address_progress(address_input)
    text = (
        f"Step {step}/{total} — {display_label}\n"
        f"Please enter {prompt_text}."
    )
    if any(address_input.values()):
        text += f"\n\nCurrent info:\n{progress}"

    await _send_new_prompt_text(update, text)

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

    shipping_address = Address(
        address_1=address_input["address_1"],
        city=address_input["city"],
        state=address_input["state"],
        postcode=address_input["postcode"],
        country=address_input["country"],
    )

    cart: list[dict] = context.user_data.get("cart", [])
    line_items = [LineItemRequest(id=i["product_id"], quantity=i["quantity"]) for i in cart]
    buyer = Buyer(
        email=address_input.get("email"),
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

    summary = _format_address_progress(address_input)
    await _send_new_prompt_text(
        update,
        "Thanks! Here's the address we captured:\n"
        f"{summary}\n\nFetching shipping options…",
    )

    return await _show_shipping(update, context, session)


# ── Step 3: Select shipping method ────────────────────────────────────────────

async def _show_shipping(update, context, session) -> int:
    if not session.fulfillment:
        await _send_new_prompt_text(update, "No shipping options available. Please contact the store.")
        return State.CHECKOUT_ADDRESS

    kb = shipping_keyboard(session.fulfillment, currency=session.currency)
    text = "Please select a shipping method:"
    await _send_new_prompt_text(update, text, reply_markup=kb)
    return State.CHECKOUT_SHIPPING


async def on_shipping_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: ship_{id} — store selected shipping method and show summary."""
    query = update.callback_query
    await query.answer()

    try:
        payload = query.data.split("_", 1)[1]
        method_id, group_id, option_id = payload.split("|")
    except (IndexError, ValueError):
        await query.answer("Invalid selection", show_alert=True)
        return State.CHECKOUT_SHIPPING

    context.user_data["selected_shipping"] = {
        "method_id": method_id,
        "group_id": group_id,
        "option_id": option_id,
    }

    # Re-fetch session to get accurate totals with the selected method
    session_id: str = context.user_data["checkout_session_id"]
    ucp: UCPClient = context.bot_data["ucp_client"]

    try:
        session = await ucp.select_fulfillment_option(
            session_id=session_id,
            method_id=method_id,
            group_id=group_id,
            option_id=option_id,
        )
    except UCPError as exc:
        await query.edit_message_text(f"Could not apply shipping: {exc.message}")
        return State.CHECKOUT_SHIPPING

    context.user_data["checkout_session"] = session.model_dump()
    cart: list[dict] = context.user_data.get("cart", [])
    summary = _format_session_summary(session, cart)
    settings = context.bot_data["settings"]
    configured_token = settings.ucp_payment_token
    stored_token = context.user_data.get("payment_token")

    if not configured_token and not stored_token:
        await _auto_provision_payment_token(session, context)
        stored_token = context.user_data.get("payment_token")

    if configured_token or stored_token:
        await query.edit_message_text(summary, reply_markup=confirm_keyboard(), parse_mode="Markdown")
        return State.CHECKOUT_CONFIRM

    await query.edit_message_text("Shipping option applied. A payment method is required to continue.")
    return await _prompt_payment_token(update, context)


async def on_payment_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token_text = update.message.text.strip() if update.message else ""
    if not token_text:
        await update.message.reply_text("Payment token cannot be empty. Please enter a valid token:")
        return State.CHECKOUT_PAYMENT

    token: str | dict
    if token_text.startswith("{"):
        try:
            parsed = json.loads(token_text)
            if isinstance(parsed, dict):
                token = parsed
            else:
                token = token_text
        except json.JSONDecodeError:
            token = token_text
    else:
        token = token_text

    context.user_data["payment_token"] = token

    session_data = context.user_data.get("checkout_session")
    if not session_data:
        await update.message.reply_text("Session expired. Send /start to begin again.")
        return ConversationHandler.END

    session = CheckoutSession.model_validate(session_data)
    cart: list[dict] = context.user_data.get("cart", [])
    summary = _format_session_summary(session, cart)

    await update.message.reply_text(summary, reply_markup=confirm_keyboard(), parse_mode="Markdown")
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
    payment_token = context.user_data.get("payment_token") or settings.ucp_payment_token
    if payment_token:
        payment = PaymentRequest(payment_token=payment_token)

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


async def _send_new_prompt_text(update: Update, text: str, **kwargs) -> None:
    chat = update.effective_chat
    if chat:
        await chat.send_message(text, **kwargs)


async def _prompt_payment_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _send_new_prompt_text(
        update,
        "Please enter a payment token or mandate ID so we can complete the checkout (e.g. pm_1234).",
    )
    return State.CHECKOUT_PAYMENT
