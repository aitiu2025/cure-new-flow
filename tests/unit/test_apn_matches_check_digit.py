"""Unit tests for `tax/result.py:apn_matches` check-digit tolerance.

Closes the audit defect where Contra Costa's recipe truncated the check
digit ("-9" in "502-153-010-9") because the previous strict equality
treated the 10-digit and 9-digit forms as different APNs.

See docs/audits/legal_description_ordering_audit_2026-05-18.md.
"""
from __future__ import annotations

import pytest

from titlepro.tax.result import apn_matches, normalize_apn


# ---------------------------------------------------------------------------
# Exact match — preserved behavior.
# ---------------------------------------------------------------------------


def test_exact_match_hyphenated():
    assert apn_matches("502-153-010-9", "502-153-010-9") is True


def test_exact_match_unhyphenated():
    assert apn_matches("5021530109", "5021530109") is True


def test_exact_match_mixed_hyphenation():
    # Both forms normalize identically.
    assert apn_matches("502-153-010-9", "5021530109") is True


def test_exact_match_case_insensitive_alphanumeric():
    # APNs can contain letters in some counties (e.g. OH variants).
    assert apn_matches("APN-AB12", "apn-ab12") is True


# ---------------------------------------------------------------------------
# Check-digit suffix tolerance (the audit's primary failure mode).
# ---------------------------------------------------------------------------


def test_check_digit_suffix_long_input_short_scraped():
    """Input has check digit, scraped does not — should match."""
    assert apn_matches("502-153-010-9", "502-153-010") is True


def test_check_digit_suffix_short_input_long_scraped():
    """Scraped has check digit, input does not — should match (symmetric)."""
    assert apn_matches("502-153-010", "502-153-010-9") is True


def test_check_digit_suffix_unhyphenated():
    assert apn_matches("5021530109", "502153010") is True
    assert apn_matches("502153010", "5021530109") is True


def test_check_digit_suffix_two_digits_max():
    """Two-trailing-digit suffix is the max tolerance (covers some
    counties that store a 2-digit check sequence)."""
    assert apn_matches("12345678", "1234567812") is True


def test_three_trailing_digits_not_tolerated():
    """A 3+ digit suffix is NOT a check-digit case; reject."""
    assert apn_matches("12345678", "12345678123") is False


# ---------------------------------------------------------------------------
# Negative cases — totally different APNs must NOT match.
# ---------------------------------------------------------------------------


def test_different_apns_do_not_match():
    assert apn_matches("502-153-010", "999-999-999") is False


def test_substring_in_middle_does_not_match():
    """Prefix tolerance ONLY — middle substrings must not match."""
    assert apn_matches("123-456", "X-123-456-7") is False


def test_empty_strings_do_not_match():
    assert apn_matches("", "") is False
    assert apn_matches("502-153-010", "") is False
    assert apn_matches("", "502-153-010") is False


def test_none_inputs_do_not_match():
    """`apn_matches` should be defensive against None-ish inputs."""
    assert apn_matches(None, "502-153-010-9") is False  # type: ignore[arg-type]
    assert apn_matches("502-153-010-9", None) is False  # type: ignore[arg-type]


def test_only_check_digit_difference_with_letter_suffix_rejected():
    """Trailing alphabetic suffix is NOT a check digit; reject."""
    assert apn_matches("123456", "123456A") is False


# ---------------------------------------------------------------------------
# normalize_apn invariants (sanity).
# ---------------------------------------------------------------------------


def test_normalize_strips_hyphens_and_lowercases():
    assert normalize_apn("502-153-010-9") == "5021530109"
    assert normalize_apn("APN-AB12") == "apnab12"


def test_normalize_empty_returns_empty():
    assert normalize_apn("") == ""
    assert normalize_apn(None) == ""  # type: ignore[arg-type]
