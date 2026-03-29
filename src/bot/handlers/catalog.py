"""
src/bot/handlers/catalog.py
────────────────────────────
Browse products (SPEC.md §2.1 — BROWSING and PRODUCT_DETAIL states).

Callback data handled:
  prod_{id}    — user tapped a product → show detail
  page_{n}     — paginate catalog
  action_back  — return to catalog from product detail
  action_cart  — shortcut to cart view
"""

from __future__ import annotations

import logging

import html
import re

from telegram import Update
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from src.bot.keyboards import catalog_keyboard, product_detail_keyboard
from src.bot.states import State
from src.ucp.client import UCPClient, UCPError

logger = logging.getLogger(__name__)

_PER_PAGE = 8  # SPEC.md §3.2


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fetch products for the current page and display the catalog inline keyboard."""
    page: int = context.user_data.get("products_page", 1)
    ucp: UCPClient = context.bot_data["ucp_client"]
    cart: list[dict] = context.user_data.get("cart", [])

    try:
        result = await ucp.list_products(page=page, per_page=_PER_PAGE)
    except UCPError as exc:
        msg = f"Could not load products: {exc.message}"
        await _reply(update, msg)
        return State.BROWSING

    if not result.products:
        await _reply(update, "No products found in the catalog.")
        return State.BROWSING

    kb = catalog_keyboard(
        products=result.products,
        current_page=result.pagination.current_page,
        total_pages=result.pagination.pages,
        cart_count=sum(i["quantity"] for i in cart),
    )

    text = (
        f"*Product Catalog* — Page {result.pagination.current_page}/{result.pagination.pages} "
        f"({result.pagination.total} products)\n\nTap a product to see details."
    )
    await _reply(update, text, reply_markup=kb)
    return State.BROWSING


async def on_product_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: prod_{id} — show product detail."""
    query = update.callback_query
    await query.answer()

    raw_id = query.data.split("_", 1)[1]

    # Validate product ID
    from src.middleware.validators import validate_product_id
    ok, err = validate_product_id(raw_id)
    if not ok:
        await query.answer(err, show_alert=True)
        return State.BROWSING

    product_id = int(raw_id)
    ucp: UCPClient = context.bot_data["ucp_client"]

    # Fetch the single product via list_products (no dedicated single-product endpoint in spec)
    # We re-use the cached result if it matches, otherwise search by page scan.
    product = context.user_data.get("catalog_cache", {}).get(product_id)

    if not product:
        try:
            result = await ucp.list_products(page=1, per_page=100)
            cache = {p.id: p for p in result.products}
            context.user_data["catalog_cache"] = cache
            product = cache.get(product_id)
        except UCPError as exc:
            await query.answer(exc.message, show_alert=True)
            return State.BROWSING

    if not product:
        await query.answer("Product not found.", show_alert=True)
        return State.BROWSING

    context.user_data["current_product_id"] = product_id

    in_stock = product.stock_status == "instock"
    kb = product_detail_keyboard(product_id, in_stock=in_stock)

    text = _format_product_text(product, in_stock)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    await _send_product_image(query, product)
    return State.PRODUCT_DETAIL


async def on_page_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: page_{n} — navigate catalog pages."""
    query = update.callback_query
    await query.answer()

    try:
        page = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        return State.BROWSING

    context.user_data["products_page"] = page
    return await show_catalog(update, context)


async def on_back_to_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback: action_back — go back to catalog from product detail."""
    query = update.callback_query
    await query.answer()
    return await show_catalog(update, context)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _reply(update: Update, text: str, **kwargs) -> None:
    """Send a message whether the update is a Message or a CallbackQuery."""
    if update.callback_query:
        await update.callback_query.edit_message_text(text, **kwargs)
    elif update.message:
        await update.message.reply_text(text, **kwargs)


def _format_product_text(product, in_stock: bool) -> str:
    title = escape_markdown(product.title, version=1)
    sku = escape_markdown(product.sku, version=1)

    description = product.description or ""
    description = _strip_html(description)
    description = escape_markdown(description, version=1)
    if not description:
        description = "No description available."
    if len(description) > 600:
        description = description[:597] + "…"

    stock_label = "In stock" if in_stock else "Out of stock"

    return (
        f"*{title}*\n"
        f"Price: *${product.price:.2f}*\n"
        f"SKU: `{sku}`\n"
        f"Status: {stock_label}\n\n"
        f"{description}"
    )


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean).strip()


async def _send_product_image(query, product) -> None:
    if not product.images or not product.images.featured:
        return

    try:
        await query.message.reply_photo(
            product.images.featured,
            caption=f"Image: {product.title}",
        )
    except Exception as exc:
        logger.warning("Failed to send product image %s: %s", product.images.featured, exc)
