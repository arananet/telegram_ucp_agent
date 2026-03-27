"""
src/bot/keyboards.py
────────────────────
InlineKeyboardMarkup factory functions.

Each function returns a ready-to-use InlineKeyboardMarkup.
Callback data prefixes:
  prod_    — select product by ID
  page_    — catalog pagination
  add_     — add product to cart (product_id)
  rm_      — remove item from cart (index)
  ship_    — select shipping method
  action_  — named action (back, cart, menu, checkout, confirm, cancel, restart)
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.ucp.models import Fulfillment, Product


def catalog_keyboard(
    products: list[Product],
    current_page: int,
    total_pages: int,
    cart_count: int = 0,
) -> InlineKeyboardMarkup:
    """One button per product + pagination row + cart shortcut."""
    rows: list[list[InlineKeyboardButton]] = []

    for p in products:
        stock = "" if p.stock_status == "instock" else " (out of stock)"
        rows.append([
            InlineKeyboardButton(
                f"{p.title} — ${p.price:.2f}{stock}",
                callback_data=f"prod_{p.id}",
            )
        ])

    # Pagination row
    nav: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"page_{current_page - 1}"))
    if current_page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"page_{current_page + 1}"))
    if nav:
        rows.append(nav)

    # Cart shortcut
    cart_label = f"🛒 Cart ({cart_count})" if cart_count else "🛒 Cart (empty)"
    rows.append([InlineKeyboardButton(cart_label, callback_data="action_cart")])

    return InlineKeyboardMarkup(rows)


def product_detail_keyboard(product_id: int, in_stock: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if in_stock:
        rows.append([InlineKeyboardButton("Add to cart ➕", callback_data=f"add_{product_id}")])
    rows.append([InlineKeyboardButton("◀ Back to catalog", callback_data="action_back")])
    return InlineKeyboardMarkup(rows)


def cart_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    """Item list with remove buttons + action row."""
    rows: list[list[InlineKeyboardButton]] = []

    for i, item in enumerate(items):
        rows.append([
            InlineKeyboardButton(
                f"❌ Remove — {item['title']} x{item['quantity']}",
                callback_data=f"rm_{i}",
            )
        ])

    action_row = [InlineKeyboardButton("🛍 Continue shopping", callback_data="action_back")]
    if items:
        action_row.insert(0, InlineKeyboardButton("✅ Checkout", callback_data="action_checkout"))
    rows.append(action_row)

    return InlineKeyboardMarkup(rows)


def shipping_keyboard(fulfillment_groups: list[Fulfillment]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for group in fulfillment_groups:
        for method in group.methods:
            label = f"{method.label} — ${method.cost:.2f}"
            rows.append([
                InlineKeyboardButton(label, callback_data=f"ship_{method.id}")
            ])

    rows.append([InlineKeyboardButton("◀ Edit address", callback_data="action_back")])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Place Order", callback_data="action_confirm")],
        [InlineKeyboardButton("✏️ Edit cart", callback_data="action_cart")],
        [InlineKeyboardButton("❌ Cancel order", callback_data="action_cancel")],
    ])


def order_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Shop again", callback_data="action_restart")]
    ])
