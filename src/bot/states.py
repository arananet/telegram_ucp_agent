"""
src/bot/states.py
─────────────────
ConversationHandler state constants (SPEC.md §2.2).

Using plain integers so they work directly with PTB's ConversationHandler.
"""

from enum import IntEnum


class State(IntEnum):
    BROWSING = 0
    PRODUCT_DETAIL = 1
    CART = 2
    CHECKOUT_ADDRESS = 3
    CHECKOUT_SHIPPING = 4
    CHECKOUT_CONFIRM = 5
    ORDER_DONE = 6
