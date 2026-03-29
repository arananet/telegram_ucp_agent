"""
tests/test_validators.py
────────────────────────
Verify input validation rules from SPEC.md §5.4.
"""

from __future__ import annotations

import pytest

from src.middleware.validators import (
    validate_city,
    validate_country,
    validate_email,
    validate_name,
    validate_postal_code,
    validate_product_id,
    validate_quantity,
    validate_state,
    validate_street,
)


# ── Product ID ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "42", "9999999"])
def test_product_id_valid(value):
    ok, _ = validate_product_id(value)
    assert ok


@pytest.mark.parametrize("value", ["0", "-1", "10000000", "abc", "", "3.5"])
def test_product_id_invalid(value):
    ok, err = validate_product_id(value)
    assert not ok
    assert err


# ── Quantity ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "50", "99"])
def test_quantity_valid(value):
    ok, _ = validate_quantity(value)
    assert ok


@pytest.mark.parametrize("value", ["0", "100", "-5", "abc", ""])
def test_quantity_invalid(value):
    ok, err = validate_quantity(value)
    assert not ok
    assert err


# ── Name (first/last) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["John", "Mary-Jane", "O'Brien", "Eduardo"])
def test_name_valid(value):
    ok, _ = validate_name(value)
    assert ok


@pytest.mark.parametrize("value", ["", "   ", "John123", "A" * 101])
def test_name_invalid(value):
    ok, err = validate_name(value)
    assert not ok
    assert err


# ── Street Address ────────────────────────────────────────────────────────────

def test_street_valid():
    ok, _ = validate_street("123 Main Street, Apt 4B")
    assert ok


@pytest.mark.parametrize("value", ["", "   ", "A" * 201])
def test_street_invalid(value):
    ok, err = validate_street(value)
    assert not ok
    assert err


# ── City ──────────────────────────────────────────────────────────────────────

def test_city_valid():
    ok, _ = validate_city("Springfield")
    assert ok


def test_city_invalid():
    ok, err = validate_city("")
    assert not ok
    assert err


# ── State ─────────────────────────────────────────────────────────────────────

def test_state_valid():
    ok, _ = validate_state("Illinois")
    assert ok


def test_state_empty_invalid():
    ok, err = validate_state("")
    assert not ok
    assert err


# ── Postal Code ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["62701", "SW1A 1AA", "10001-1234"])
def test_postal_valid(value):
    ok, _ = validate_postal_code(value)
    assert ok


@pytest.mark.parametrize("value", ["", "A" * 21, "!@#$%"])
def test_postal_invalid(value):
    ok, err = validate_postal_code(value)
    assert not ok
    assert err


# ── Country ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["US", "MX", "GB", "us", "mx"])
def test_country_valid(value):
    ok, _ = validate_country(value)
    assert ok


@pytest.mark.parametrize("value", ["", "USA", "1", "U", "u1"])
def test_country_invalid(value):
    ok, err = validate_country(value)
    assert not ok
    assert err


# ── Email ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "user@example.com",
    "first.last+tag@example.co.uk",
    "name123@test.io",
])
def test_email_valid(value):
    ok, _ = validate_email(value)
    assert ok


@pytest.mark.parametrize("value", ["", "   ", "invalid", "foo@bar", "user@", "@example.com"])
def test_email_invalid(value):
    ok, err = validate_email(value)
    assert not ok
    assert err
