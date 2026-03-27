"""
src/bot/handlers/cart.py
────────────────────────
Cart management (SPEC.md §2.1 — CART state).

Cart is stored in context.user_data["cart"] as a list of dicts:
  {"product_id": int, "title": str, "price": float, "quantity": int}

Callback data handled:
  add_{product_id}  — add product to cart (from PRODUCT_DETAIL)
  rm_{index}        — remove item at index
  action_cart       — show cart
  action_checkout   — start checkout flow
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.keyboards import cart_keyboard
from src.bot.states import State

logger = logging.getLogger(__name__)


def _get_cart(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    return context.user_data.setdefault("cart", [])


def _format_cart(cart: list[dict], currency: str = "USD") -> str:
    if not cart:
        return "Your cart is empty."

    lines = ["*Your Cart*\n"]
    total = 0.0
    for i, item in enumerate(cart, 1):
        subtotal = item["price"] * item["quantity"]
        total += subtotal
        lines.append(f"{i}. {item['title']} x{item['quantity']} — ${subtotal:.2f}")

    lines.append(f"\n*Total: ${total:.2f}*")
    return "\n".join(lines)


async def on_add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: add_{product_id} — add the current product to cart."""
    query = update.callback_query
    await query.answer()

    raw_id = query.data.split("_", 1)[1]

    from src.middleware.validators import validate_product_id
    ok, err = validate_product_id(raw_id)
    if not ok:
        await query.answer(err, show_alert=True)
        return State.PRODUCT_DETAIL

    product_id = int(raw_id)
    catalog_cache: dict = context.user_data.get("catalog_cache", {})
    product = catalog_cache.get(product_id)

    if not product:
        await query.answer("Product not found — please go back and try again.", show_alert=True)
        return State.PRODUCT_DETAIL

    cart = _get_cart(context)

    # Increment quantity if already in cart
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] += 1
            logger.info("user_id=%s incremented product_id=%s in cart", query.from_user.id, product_id)
            await query.answer(f"Added another {product.title} to cart.")
            return await show_cart(update, context)

    cart.append({
        "product_id": product_id,
        "title": product.title,
        "price": product.price,
        "quantity": 1,
    })
    logger.info("user_id=%s added product_id=%s to cart", query.from_user.id, product_id)
    await query.answer(f"{product.title} added to cart!")
    return await show_cart(update, context)


async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display the cart with remove buttons and checkout option."""
    cart = _get_cart(context)
    text = _format_cart(cart)
    kb = cart_keyboard(cart)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    return State.CART


async def on_remove_from_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: rm_{index} — remove item at the given index."""
    query = update.callback_query
    await query.answer()

    try:
        idx = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        return State.CART

    cart = _get_cart(context)
    if 0 <= idx < len(cart):
        removed = cart.pop(idx)
        logger.info(
            "user_id=%s removed product_id=%s from cart",
            query.from_user.id,
            removed["product_id"],
        )

    return await show_cart(update, context)
