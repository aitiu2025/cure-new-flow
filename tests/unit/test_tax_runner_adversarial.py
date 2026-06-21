"""Codex finding 2 — adversarial tests for TaxLookupResult classification.

These exercise the runner's `_classify()` directly with synthetic
extraction payloads to confirm:

  * A zillow.com source URL is rejected even when fields are populated.
  * An estimated-only payload (keys ending in `_estimated`) cannot reach
    TAX_SUCCESS.
  * An APN echo mismatch is rejected.
"""
from __future__ import annotations

from titlepro.tax.playwright_runner import _classify
from titlepro.tax.result import (
    TaxLookupResult,
    apn_matches,
    host_in_whitelist,
    is_estimated_key,
    normalize_apn,
)


FRESNO_RECIPE = {
    "county": "fresno",
    "platform": "playwright_form",
    "authoritative_source_hosts": ["fcacttcptr.fresnocountyca.gov"],
    "verification_required": [
        "assessed_value.net_taxable",
        "installments[0].amount",
        "installments[1].amount",
    ],
}


def test_source_url_mismatch_returns_tax_failed():
    """A payload sourced from zillow.com MUST NOT be TAX_SUCCESS."""
    extracted = {
        "apn": "455-113-24",
        "tax_year": "2025-26",
        "assessed_value": {"net_taxable": 228569},
        "installments": [
            {"amount": 1492.75, "status": "PAID"},
            {"amount": 1492.75, "status": "PAID"},
        ],
    }
    status, _, _, _, error = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="https://www.zillow.com/homedetails/foo/123_zpid/",
        body_text="",
    )
    assert status == "TAX_FAILED", f"expected TAX_FAILED, got {status}"
    assert "source host" in error.lower()


def test_redfin_source_rejected():
    extracted = {"apn": "455-113-24", "assessed_value": {"net_taxable": 228569}}
    status, _, _, _, error = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="https://www.redfin.com/CA/Fresno/5041-E-Hedges-Ave-93727/",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert "source host" in error.lower()


def test_claude_websearch_source_rejected():
    """`data_source: "claude_web_search"` must NOT count as a verified source."""
    extracted = {"apn": "455-113-24", "assessed_value": {"net_taxable": 228569}}
    status, _, _, _, _ = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="claude_web_search",  # not a real URL
        body_text="",
    )
    assert status == "TAX_FAILED"


def test_apn_echo_mismatch_returns_tax_failed():
    """When the recipe extracts an APN that differs from the input, fail."""
    extracted = {
        "apn": "999-999-99",  # different parcel!
        "assessed_value": {"net_taxable": 228569},
        "installments": [{"amount": 1492.75}, {"amount": 1492.75}],
    }
    status, _, _, _, error = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert "apn echo mismatch" in error.lower()


def test_estimated_field_does_not_count_as_verified():
    """`assessed_value.net_taxable_estimated` cannot satisfy a verification slot."""
    recipe = {
        "county": "fresno",
        "authoritative_source_hosts": ["fcacttcptr.fresnocountyca.gov"],
        "verification_required": ["assessed_value.net_taxable_estimated"],
    }
    extracted = {
        "apn": "455-113-24",
        "assessed_value": {"net_taxable_estimated": 228569},
    }
    status, verified, _, _, _ = _classify(
        recipe,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/",
        body_text="",
    )
    # `_estimated` key never enters verified_fields, so status cannot be TAX_SUCCESS.
    assert status != "TAX_SUCCESS"
    assert all(not is_estimated_key(k) for k in verified)


def test_combined_adversarial_payload_rejected():
    """The full Codex scenario: zillow source + estimated amount + APN mismatch."""
    recipe = {
        "county": "fresno",
        "authoritative_source_hosts": ["fcacttcptr.fresnocountyca.gov"],
        "verification_required": ["annual_tax_estimated"],
    }
    extracted = {
        "apn": "999-999-99",
        "annual_tax_estimated": 5000,
    }
    status, verified, _, _, _ = _classify(
        recipe,
        extracted,
        input_apn="455-113-24",
        source_url="https://www.zillow.com/",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert verified == []


def test_no_results_pattern_triggers_tax_no_results():
    extracted = {}
    status, _, _, notes, _ = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
        body_text="APN is inactive for roll year 2025-26, no tax bill to display.",
    )
    assert status == "TAX_NO_RESULTS"


def test_success_path_with_proper_data():
    """Sanity: a valid payload from the whitelisted source DOES reach TAX_SUCCESS."""
    extracted = {
        "apn": "455-113-24",
        "tax_year": "2025-26",
        "assessed_value": {"net_taxable": 228569},
        "installments": [{"amount": 1492.75}, {"amount": 1492.75}],
        "annual_total": 2985.50,
    }
    status, verified, missing, _, _ = _classify(
        FRESNO_RECIPE,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
        body_text="",
    )
    assert status == "TAX_SUCCESS"
    assert "assessed_value.net_taxable" in verified
    assert not missing


def test_apn_normalization_helpers():
    """Sanity-test the helpers underpinning the APN-echo check."""
    assert apn_matches("455-113-24", "455-113-24")
    assert apn_matches("455-113-24", "45511324")
    assert apn_matches("455-113-24", " 455 - 113 - 24 ")
    assert not apn_matches("455-113-24", "999-999-99")
    assert normalize_apn("455-113-24") == "45511324"


def test_host_whitelist_helpers():
    """Sanity-test the host whitelist matcher in strict (default) mode."""
    wl = ["fcacttcptr.fresnocountyca.gov"]
    assert host_in_whitelist("https://fcacttcptr.fresnocountyca.gov/Home/Index", wl)
    assert not host_in_whitelist("https://www.zillow.com/", wl)
    # Strict (default) mode: a sub-domain of a whitelisted parent does NOT
    # match. This is the post-2026-05-13 hardening (Codex follow-up).
    assert not host_in_whitelist("https://common2.mptsweb.com/foo", ["mptsweb.com"])
    assert not host_in_whitelist("https://fake-mptsweb.com.evil.com/", ["mptsweb.com"])
    # Subdomain takeover attempt: even in strict mode, the attacker subdomain
    # of a whitelisted exact host must be rejected.
    assert not host_in_whitelist(
        "https://attacker.fcacttcptr.fresnocountyca.gov/", wl
    )


def test_host_whitelist_suffix_mode_opts_in():
    """Suffix mode is opt-in via `host_whitelist_mode: "suffix"` on the recipe.

    Used by legitimate portals that rotate sub-domains (e.g. MBC's
    common1/common2/common3.mptsweb.com)."""
    assert host_in_whitelist(
        "https://common2.mptsweb.com/foo", ["mptsweb.com"], mode="suffix"
    )
    assert host_in_whitelist(
        "https://common1.mptsweb.com/foo", ["mptsweb.com"], mode="suffix"
    )
    # Suffix mode must still reject confusable hostnames that only share
    # the literal characters but are NOT a true subdomain.
    assert not host_in_whitelist(
        "https://fake-mptsweb.com.evil.com/", ["mptsweb.com"], mode="suffix"
    )
    # And exact matches still work under suffix mode.
    assert host_in_whitelist(
        "https://taxbill.octreasurer.gov/",
        ["taxbill.octreasurer.gov", "octreasurer.gov"],
        mode="suffix",
    )


def test_host_whitelist_strict_mode_explicit():
    """Passing mode='strict' explicitly behaves the same as the default."""
    wl = ["fcacttcptr.fresnocountyca.gov"]
    assert host_in_whitelist(
        "https://fcacttcptr.fresnocountyca.gov/Home/Index", wl, mode="strict"
    )
    assert not host_in_whitelist(
        "https://sub.fcacttcptr.fresnocountyca.gov/", wl, mode="strict"
    )
