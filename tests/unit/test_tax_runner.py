"""Unit tests for the generic Playwright recipe runner.

These do NOT spin up a real browser. They exercise the runner's
pure-logic helpers (`_split_apn`, `_set_field_path`, `_get_field_path`,
`_parse_currency`, `_classify`) and the Fresno fixture pair, asserting
the captured-HTML fixture contains the expected canonical values.

Live integration (live browser against fcacttcptr.fresnocountyca.gov)
is covered by the manual A9 step in the implementation plan, not by CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.tax.playwright_runner import (
    _classify,
    _coerce,
    _get_field_path,
    _parse_currency,
    _set_field_path,
    _split_apn,
)
from titlepro.tax.recipe_schema import load_recipe


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tax" / "fresno"
RECIPE_DIR = Path(__file__).resolve().parents[2] / "config" / "tax_recipes"


# ---- pure helpers ----------------------------------------------------


def test_parse_currency_simple():
    assert _parse_currency("$1,492.75") == 1492.75
    assert _parse_currency("2,985.50") == 2985.50
    assert _parse_currency("$0.00") == 0.0
    assert _parse_currency("") is None
    assert _parse_currency("PAID") is None


def test_coerce_dispatch():
    assert _coerce("$1,492.75", "currency") == 1492.75
    assert _coerce("  abc  ", "string") == "abc"
    assert _coerce("228569", "int") == 228569
    assert _coerce("", "currency") == ""


def test_split_apn_with_hyphen():
    parts = _split_apn("455-113-24", "XXX-XXX-XX")
    assert parts == ["455", "113", "24"]


def test_split_apn_without_hyphen():
    parts = _split_apn("45511324", "XXX-XXX-XX")
    assert parts == ["455", "113", "24"]


def test_field_path_setter_dotted():
    target: dict = {}
    _set_field_path(target, "assessed_value.net_taxable", 228569)
    assert target == {"assessed_value": {"net_taxable": 228569}}


def test_field_path_setter_indexed():
    target: dict = {}
    _set_field_path(target, "installments[0].amount", 1492.75)
    _set_field_path(target, "installments[0].status", "PAID")
    _set_field_path(target, "installments[1].amount", 1492.75)
    assert target == {
        "installments": [
            {"amount": 1492.75, "status": "PAID"},
            {"amount": 1492.75},
        ]
    }


def test_field_path_getter_round_trip():
    src: dict = {}
    _set_field_path(src, "a.b[2].c", "X")
    assert _get_field_path(src, "a.b[2].c") == "X"
    assert _get_field_path(src, "a.b[0].c") is None or _get_field_path(src, "a.b[0].c") == {}


# ---- fixture sanity --------------------------------------------------


def test_fresno_fixture_present():
    html = FIXTURE_DIR / "captured_apn_455-113-24.html"
    body = FIXTURE_DIR / "captured_apn_455-113-24.body.txt"
    assert html.exists(), f"Fixture missing: {html}"
    assert body.exists(), f"Fixture missing: {body}"
    body_text = body.read_text(encoding="utf-8")
    # The fixture must contain the canonical values we expect from the
    # AMAYA / 455-113-24 tax bill.
    assert "455-113-24" in body_text
    assert "64,524" in body_text
    assert "164,045" in body_text
    assert "228,569" in body_text
    assert "1,492.75" in body_text
    assert "2,985.50" in body_text
    assert "005-427" in body_text  # TRA
    assert "2025-26" in body_text


def test_fresno_recipe_loads():
    recipe = load_recipe("fresno", recipes_dir=RECIPE_DIR)
    assert recipe is not None
    assert recipe["county"] == "fresno"
    assert "fcacttcptr.fresnocountyca.gov" in recipe["authoritative_source_hosts"]
    # Recipe must use the discovered selector IDs.
    apn_field_step = next(s for s in recipe["navigation_steps"] if s.get("action") == "split_apn")
    assert apn_field_step["fields"] == ["#APNField1", "#APNField2", "#APNField3"]


# ---- _classify end-to-end on fresno fixture --------------------------


def test_classify_on_canonical_fresno_data():
    """Feed the runner's classifier the canonical extraction it WOULD
    produce against the captured Fresno HTML. Status MUST be TAX_SUCCESS."""
    recipe = load_recipe("fresno", recipes_dir=RECIPE_DIR)
    assert recipe is not None
    extracted = {
        "apn": "455-113-24",
        "tax_year": "2025-26",
        "tra": "005-427",
        "property_address": "5041 E HEDGES FR",
        "assessed_value": {
            "land": 64524.0,
            "improvements": 164045.0,
            "subtotal": 228569.0,
            "net_taxable": 228569.0,
        },
        "installments": [
            {"label": "Installment 1", "amount": 1492.75, "paid_date": "12/08/2025"},
            {"label": "Installment 2", "amount": 1492.75, "paid_date": "04/08/2026"},
        ],
        "annual_total": 2985.50,
    }
    status, verified, missing, notes, error = _classify(
        recipe,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
        body_text="(stub body)",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error or notes}"
    assert not missing
    assert "assessed_value.net_taxable" in verified
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified
    assert "annual_total" in verified


def test_classify_partial_when_only_some_fields_present():
    recipe = load_recipe("fresno", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "455-113-24",
        "assessed_value": {"net_taxable": 228569.0},
        # installments missing
    }
    status, verified, missing, _, _ = _classify(
        recipe,
        extracted,
        input_apn="455-113-24",
        source_url="https://fcacttcptr.fresnocountyca.gov/",
        body_text="",
    )
    assert status == "TAX_PARTIAL"
    assert "assessed_value.net_taxable" in verified
    assert "installments[0].amount" in missing
