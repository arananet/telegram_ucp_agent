"""
src/middleware/validators.py
────────────────────────────
Input validation rules as defined in SPEC.md §5.4.

All functions return (is_valid: bool, error_message: str).
An empty error_message means the input is valid.
"""

from __future__ import annotations

import re

# ── Compiled patterns (compiled once at import time) ──────────────────────────

_NAME_RE = re.compile(r"^[A-Za-z\s\-']{1,100}$")
_POSTAL_RE = re.compile(r"^[A-Z0-9\s\-]{1,20}$", re.IGNORECASE)
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


# ── Validators ────────────────────────────────────────────────────────────────

def validate_product_id(value: str) -> tuple[bool, str]:
    """Positive integer, 1 ≤ id ≤ 9_999_999."""
    try:
        pid = int(value)
    except (ValueError, TypeError):
        return False, "Product ID must be a number."
    if not (1 <= pid <= 9_999_999):
        return False, "Product ID out of range."
    return True, ""


def validate_quantity(value: str) -> tuple[bool, str]:
    """Integer, 1 ≤ qty ≤ 99."""
    try:
        qty = int(value)
    except (ValueError, TypeError):
        return False, "Quantity must be a whole number."
    if not (1 <= qty <= 99):
        return False, "Quantity must be between 1 and 99."
    return True, ""


def validate_name(value: str, field: str = "Name") -> tuple[bool, str]:
    """Non-empty string, max 100 chars, letters/spaces/hyphens/apostrophes."""
    if not value or not value.strip():
        return False, f"{field} cannot be empty."
    if not _NAME_RE.match(value.strip()):
        return False, f"{field} may only contain letters, spaces, hyphens, and apostrophes (max 100 chars)."
    return True, ""


def validate_street(value: str) -> tuple[bool, str]:
    """Non-empty, max 200 chars."""
    stripped = value.strip() if value else ""
    if not stripped:
        return False, "Street address cannot be empty."
    if len(stripped) > 200:
        return False, "Street address is too long (max 200 characters)."
    return True, ""


def validate_city(value: str) -> tuple[bool, str]:
    """Non-empty, max 100 chars, letters/spaces/hyphens/apostrophes."""
    return validate_name(value, field="City")


def validate_state(value: str) -> tuple[bool, str]:
    """Non-empty, max 100 chars."""
    stripped = value.strip() if value else ""
    if not stripped:
        return False, "State/province cannot be empty."
    if len(stripped) > 100:
        return False, "State/province is too long (max 100 characters)."
    return True, ""


def validate_postal_code(value: str) -> tuple[bool, str]:
    """Non-empty, max 20 chars, alphanumeric/spaces/hyphens."""
    stripped = value.strip() if value else ""
    if not stripped:
        return False, "Postal code cannot be empty."
    if not _POSTAL_RE.match(stripped):
        return False, "Postal code may only contain letters, numbers, spaces, and hyphens (max 20 chars)."
    return True, ""


def validate_country(value: str) -> tuple[bool, str]:
    """Exactly 2 uppercase letters (ISO 3166-1 alpha-2)."""
    stripped = value.strip().upper() if value else ""
    if not _COUNTRY_RE.match(stripped):
        return False, "Country must be a 2-letter ISO code (e.g. US, MX, GB)."
    return True, ""
