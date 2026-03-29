"""Tests for checkout autofill helpers."""

from __future__ import annotations

from src.bot.handlers.checkout import _profile_to_address_input


def test_profile_to_address_input_success():
    profile = {
        "email": "user@example.com",
        "first_name": "First",
        "last_name": "Last",
        "shipping": {
            "address_1": "123 Main",
            "city": "Springfield",
            "state": "IL",
            "postcode": "62701",
            "country": "us",
        },
    }
    result = _profile_to_address_input(profile)
    assert result
    assert result["country"] == "US"


def test_profile_to_address_input_missing_field_returns_none():
    profile = {
        "email": "user@example.com",
        "first_name": "First",
        "last_name": "Last",
        "shipping": {
            "address_1": "",
            "city": "",
            "state": "",
            "postcode": "",
            "country": "",
        },
    }
    assert _profile_to_address_input(profile) is None
