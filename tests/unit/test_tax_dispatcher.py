"""Tests for the v2 tax dispatcher (titlepro.tax.fetch_tax)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.tax import fetch_tax
from titlepro.tax.result import TaxLookupResult


def test_unknown_county_returns_tax_no_runner(tmp_path):
    result = fetch_tax(
        county_id="totally_unknown_county",
        apn="123-456-78",
        owner_name="OWNER",
        property_address="addr",
        case_dir=tmp_path,
    )
    assert isinstance(result, TaxLookupResult)
    assert result.status == "TAX_NO_RUNNER"


def test_county_with_direct_platform_no_recipe_returns_tax_no_runner(tmp_path):
    # kern is still platform='direct' in the config; no recipe file -> TAX_NO_RUNNER
    # (alameda was flipped to playwright_form when its recipe landed 2026-05-13).
    result = fetch_tax(
        county_id="kern",
        apn="123-456-78",
        owner_name="OWNER",
        property_address="addr",
        case_dir=tmp_path,
    )
    assert result.status == "TAX_NO_RUNNER"


def test_fresno_routes_to_playwright_form_when_recipe_present(tmp_path, monkeypatch):
    """If a `playwright_form` platform is configured and a recipe exists,
    the dispatcher MUST call into the playwright_runner. We stub the
    runner so the test doesn't hit a real browser."""
    from titlepro.tax import playwright_runner as runner_mod

    called = {"n": 0}

    def _stub_run(recipe, apn, case_dir, safe_owner="tax", **kwargs):
        called["n"] += 1
        called["recipe_county"] = recipe.get("county")
        called["apn"] = apn
        return TaxLookupResult(
            apn=apn,
            tax_year="2025-26",
            property_address="",
            source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
            status="TAX_SUCCESS",
            verified_fields=["annual_total"],
            annual_total=2985.50,
        )

    monkeypatch.setattr(runner_mod, "run", _stub_run, raising=True)

    result = fetch_tax(
        county_id="fresno",
        apn="455-113-24",
        owner_name="AMAYA JANINE",
        property_address="5041 E HEDGES",
        case_dir=tmp_path,
    )
    assert called["n"] == 1
    assert called["recipe_county"] == "fresno"
    assert called["apn"] == "455-113-24"
    assert result.status == "TAX_SUCCESS"


def test_recipe_loads_and_validates(tmp_path):
    """The shipped fresno.json recipe must pass schema validation."""
    from titlepro.tax.recipe_schema import load_recipe

    repo_recipes = Path(__file__).resolve().parents[2] / "config" / "tax_recipes"
    recipe = load_recipe("fresno", recipes_dir=repo_recipes)
    assert recipe is not None
    assert recipe["county"] == "fresno"
    assert recipe["platform"] == "playwright_form"
    assert "fcacttcptr.fresnocountyca.gov" in recipe["authoritative_source_hosts"]
    # Verification list must include the big-three monetary fields.
    vr = recipe.get("verification_required") or []
    assert "assessed_value.net_taxable" in vr
    assert "annual_total" in vr


def test_recipe_validator_catches_missing_authoritative_hosts():
    from titlepro.tax.recipe_schema import validate_recipe

    bad = {
        "county": "test",
        "platform": "playwright_form",
        "base_url": "https://example.com",
        # missing authoritative_source_hosts
        "navigation_steps": [{"action": "goto", "url": "https://example.com"}],
    }
    errors = validate_recipe(bad, source_label="bad.json")
    assert any("authoritative_source_hosts" in e for e in errors)


def test_recipe_validator_catches_unknown_action():
    from titlepro.tax.recipe_schema import validate_recipe

    bad = {
        "county": "test",
        "platform": "playwright_form",
        "base_url": "https://example.com",
        "authoritative_source_hosts": ["example.com"],
        "navigation_steps": [{"action": "FROBNICATE"}],
    }
    errors = validate_recipe(bad, source_label="bad.json")
    assert any("unknown action" in e.lower() for e in errors)


def test_mbc_wrapper_promotes_to_tax_success(tmp_path, monkeypatch):
    """A successful MBC scraper dict (with mptsweb.com source) is converted
    to TaxLookupResult(status=TAX_SUCCESS)."""
    from titlepro.tax import mbc_tax_scraper as mbc_mod

    def _fake_mbc(apn, county, headless=True):
        return {
            "success": True,
            "apn": "015-520-016-000",
            "tax_year": "2024-2025",
            "assessed_value_total": 350000,
            "first_installment_amount": 1234.56,
            "second_installment_amount": 1234.56,
            "annual_tax": 2469.12,
            "verification_url": "https://common1.mptsweb.com/MBC/amador/tax/search?apn=015520016000",
        }

    monkeypatch.setattr(mbc_mod, "lookup_mbc_tax", _fake_mbc, raising=True)
    result = fetch_tax(
        county_id="amador",
        apn="015-520-016-000",
        owner_name="MBC OWNER",
        property_address="",
        case_dir=tmp_path,
    )
    assert result.status == "TAX_SUCCESS"
    assert result.annual_total == 2469.12


def test_mbc_wrapper_rejects_offshore_source(tmp_path, monkeypatch):
    """An MBC dict that somehow carries a non-mptsweb source URL MUST NOT
    promote to TAX_SUCCESS (Codex finding 2 hardening on legacy path)."""
    from titlepro.tax import mbc_tax_scraper as mbc_mod

    def _fake_mbc(apn, county, headless=True):
        return {
            "success": True,
            "apn": "015-520-016-000",
            "tax_year": "2024-2025",
            "annual_tax": 2469.12,
            "verification_url": "https://www.zillow.com/CA/Amador/foo",  # spoofed
        }

    monkeypatch.setattr(mbc_mod, "lookup_mbc_tax", _fake_mbc, raising=True)
    result = fetch_tax(
        county_id="amador",
        apn="015-520-016-000",
        owner_name="MBC OWNER",
        property_address="",
        case_dir=tmp_path,
    )
    assert result.status == "TAX_FAILED"
    assert "authoritative" in (result.error or "").lower()
