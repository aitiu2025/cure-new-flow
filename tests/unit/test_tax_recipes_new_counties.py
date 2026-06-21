"""Replay-mode + recipe-load tests for the four 2026-05-13 county recipes.

These mirror the pattern from `tests/unit/test_tax_runner.py` (the Fresno
fixture sanity checks + a `_classify()` call against the canonical extract).

Live live-browser tests are out of CI scope; the live behaviour is verified
by hand and frozen here as a fixture pair.

San Bernardino's recipe is deferred (see DEFERRED marker) because its bill
data lives inside an iframe the current runner cannot reach. The fixture
pair is captured by the discovery probe and stored for future use once
runner iframe support lands.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.tax.playwright_runner import _classify
from titlepro.tax.recipe_schema import load_recipe, validate_recipe


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "tax"
RECIPE_DIR = Path(__file__).resolve().parents[2] / "config" / "tax_recipes"


# ---------------------------------------------------------------------------
# Recipe load + validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "county",
    [
        "contra_costa",
        "riverside",
        "san_diego",
        "san_bernardino",
        "alameda",
        "sacramento",
        "santa_clara",
    ],
)
def test_recipe_loads_and_validates(county):
    recipe = load_recipe(county, recipes_dir=RECIPE_DIR)
    assert recipe is not None, f"recipe file missing for {county}"
    assert recipe["county"] == county
    assert recipe["platform"] == "playwright_form"
    assert recipe["authoritative_source_hosts"], "must declare at least one host"
    # Validator passes (also enforced by load_recipe internally)
    errors = validate_recipe(recipe, source_label=f"{county}.json")
    assert errors == [], f"schema errors: {errors}"


# ---------------------------------------------------------------------------
# Per-county: fixture pair sanity (HTML contains canonical values)
# ---------------------------------------------------------------------------


# Contra Costa: 502-153-010 / 1724 WESLEY AVE / EL CERRITO
def test_contra_costa_fixture_present():
    html = FIXTURE_ROOT / "contra_costa" / "captured_apn_502-153-010.html"
    expected = FIXTURE_ROOT / "contra_costa" / "expected_apn_502-153-010.json"
    assert html.exists(), f"missing: {html}"
    assert expected.exists(), f"missing: {expected}"
    text = html.read_text(encoding="utf-8")
    # Canonical values from live run
    assert "502-153-010-9" in text
    assert "1724 WESLEY AVE" in text
    assert "03000" in text  # TRA
    assert "269,406" in text or "269406" in text  # net taxable
    assert "2,363.01" in text or "2363.01" in text  # installment
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "502-153-010"
    assert exp["tra"] == "03000"
    assert exp["assessed_value"]["net_taxable"] == 269406.0
    assert exp["installments"][0]["amount"] == 2363.01
    assert exp["installments"][1]["amount"] == 2363.01


def test_contra_costa_classify_canonical():
    recipe = load_recipe("contra_costa", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "502-153-010",
        "tax_year": "2025",
        "tra": "03000",
        "property_address": "1724 WESLEY AVE, EL CERRITO CA",
        "assessed_value": {
            "land": 192517.0,
            "improvements": 76889.0,
            "net_taxable": 269406.0,
        },
        "installments": [
            {"label": "First installment", "amount": 2363.01, "status": "PAID", "paid_date": "12/08/2025"},
            {"label": "Second installment", "amount": 2363.01, "status": "PAID", "paid_date": "04/08/2026"},
        ],
        "annual_total": 3459.98,
    }
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="502-153-010",
        source_url="https://taxcolp.cccttc.us/PTS_TaxbillsHtmlCY?APN=502-153-010",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "assessed_value.net_taxable" in verified
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified
    assert missing == []


def test_contra_costa_classify_off_whitelist_rejected():
    """Codex finding 2 reinforcement: zillow.com payload must fail."""
    recipe = load_recipe("contra_costa", recipes_dir=RECIPE_DIR)
    extracted = {
        "assessed_value": {"net_taxable": 269406.0},
        "installments": [{"amount": 2363.01}, {"amount": 2363.01}],
    }
    status, _, _, _, error = _classify(
        recipe,
        extracted,
        input_apn="502-153-010",
        source_url="https://zillow.com/some-property",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert "source host" in error.lower()


# Riverside: 291583025 / 22264 SUMMER HOLLY AVE / MORENO VALLEY
def test_riverside_fixture_present():
    html = FIXTURE_ROOT / "riverside" / "captured_apn_291583025.html"
    expected = FIXTURE_ROOT / "riverside" / "expected_apn_291583025.json"
    assert html.exists()
    assert expected.exists()
    text = html.read_text(encoding="utf-8")
    assert "291583025" in text
    assert "Net Taxable Value" in text or "Net Taxable" in text
    assert "442,436" in text or "442436" in text  # net taxable
    assert "7,183.14" in text or "7183.14" in text  # annual total
    assert "3,591.57" in text or "3591.57" in text  # installment
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "291583025"
    assert exp["assessed_value"]["net_taxable"] == 442436.0
    assert exp["annual_total"] == 7183.14


def test_riverside_classify_canonical():
    recipe = load_recipe("riverside", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "291583025",
        "tax_year": "2025",
        "assessed_value": {"net_taxable": 442436.0, "exemption": 7000.0},
        "annual_total": 7183.14,
        "installments": [
            {"label": "Payment", "amount": 3591.57, "paid_date": "12/9/2025"},
            {"label": "Payment", "amount": 3591.57},
        ],
    }
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="291583025",
        source_url="https://ca-riverside-ttc.publicaccessnow.com/AccountSearch/AccountSummary/BillDetail.aspx?p=291583025&a=291583025&b=50741593&y=2025&x=50741593&t=Real",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "assessed_value.net_taxable" in verified
    assert "annual_total" in verified


# San Diego: 452-292-23-00 / 3670 8TH AVE / SAN DIEGO
def test_san_diego_fixture_present():
    html = FIXTURE_ROOT / "san_diego" / "captured_apn_452-292-23-00.html"
    expected = FIXTURE_ROOT / "san_diego" / "expected_apn_452-292-23-00.json"
    assert html.exists()
    assert expected.exists()
    text = html.read_text(encoding="utf-8")
    assert "4522922300" in text  # APN echoed in table
    assert "11541.45" in text  # installment amount
    assert "ttc-prior-year" in text  # results table id
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "4522922300"
    assert exp["tax_year"] == "2024-2025"
    assert exp["installments"][0]["amount"] == 11541.45
    assert exp["installments"][1]["amount"] == 11541.45
    assert exp["annual_total"] == 23082.90


def test_san_diego_classify_canonical():
    recipe = load_recipe("san_diego", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "4522922300",
        "tax_year": "2024-2025",
        "installments": [
            {"label": "1st Installment", "amount": 11541.45, "paid_date": "2024-12-07", "status": "PAID ON 12/07"},
            {"label": "2nd Installment", "amount": 11541.45, "paid_date": "2025-04-09", "status": "PAID ON 04/09"},
        ],
    }
    # SD recipe extracts apn as "4522922300" (no hyphens) and we feed input as 452-292-23-00.
    # apn_matches() strips non-alnum -> "4522922300" == "4522922300".
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="452-292-23-00",
        source_url="https://www.sdttc.com/content/ttc/en/tax-collection/prior-year-tax-records.html?fiscal_year=2024-07-01%7C2025-06-30&q=452-292-23-00&x=12&y=12",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified


def test_san_diego_no_results_pattern():
    """A 'Record not found' body must produce TAX_NO_RESULTS."""
    recipe = load_recipe("san_diego", recipes_dir=RECIPE_DIR)
    extracted = {}
    status, _, _, notes, _ = _classify(
        recipe,
        extracted,
        input_apn="999-999-99-99",
        source_url="https://www.sdttc.com/content/ttc/en/tax-collection/prior-year-tax-records.html?fiscal_year=2024-07-01%7C2025-06-30&q=999-999-99-99",
        body_text="Record not found or not valid data",
    )
    assert status == "TAX_NO_RESULTS"
    assert "999-999-99-99" in notes


# San Bernardino: nested-iframe portal. The recipe uses `enter_frame`
# (added 2026-05-13) to descend two iframes deep before extracting. The
# authoritative source host is the innermost iframe (county-taxes.com),
# NOT the outer www.sbcountyatc.gov page.
def test_san_bernardino_recipe_uses_iframe_actions():
    recipe = load_recipe("san_bernardino", recipes_dir=RECIPE_DIR)
    actions = [s.get("action") for s in recipe.get("navigation_steps", [])]
    # Must descend into iframes at least twice (outer + inner) before extracting.
    assert actions.count("enter_frame") >= 2, (
        f"SBD recipe must enter both iframes (got actions: {actions})"
    )
    # Innermost frame's host. The bill data is served under the
    # gsgprod.sbcountyatc.gov host (the "sanbernardino-ca.county-taxes.com"
    # segment lives in the PATH of the iframe URL, not the hostname).
    assert "gsgprod.sbcountyatc.gov" in recipe["authoritative_source_hosts"], (
        "SBD whitelist must point at the innermost iframe host (gsgprod.sbcountyatc.gov)"
    )
    # Topology note should still be present for future debuggers.
    assert recipe.get("_iframe_topology"), (
        "Document the iframe nesting so the next dev understands the recipe"
    )


def test_san_bernardino_fixture_present_for_future_runner():
    html = FIXTURE_ROOT / "san_bernardino" / "captured_apn_0298501220000.html"
    expected = FIXTURE_ROOT / "san_bernardino" / "expected_apn_0298501220000.json"
    assert html.exists(), "discovery-probe HTML fixture should be archived"
    assert expected.exists()
    text = html.read_text(encoding="utf-8")
    # Canonical fields from the discovery probe
    assert "0298501220000" in text
    assert "104-101" in text  # TRA
    assert "490,523" in text  # net taxable
    assert "3,336.98" in text  # installment
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["assessed_value"]["net_taxable"] == 490523.0
    assert exp["annual_total"] == 6673.96
    assert exp["installments"][0]["amount"] == 3336.98
    assert exp["installments"][1]["amount"] == 3336.98


# ---------------------------------------------------------------------------
# Alameda — Astro/Parcel-tab portal. APN 74-1335-45 / 164 PURCELL DR.
# No assessed value on the summary page (lives in View Bill PDF only).
# ---------------------------------------------------------------------------


def test_alameda_fixture_present():
    html = FIXTURE_ROOT / "alameda" / "captured_apn_74-1335-45.html"
    expected = FIXTURE_ROOT / "alameda" / "expected_apn_74-1335-45.json"
    assert html.exists(), f"missing: {html}"
    assert expected.exists(), f"missing: {expected}"
    text = html.read_text(encoding="utf-8")
    assert "74-1335-45" in text
    assert "164 PURCELL DR" in text
    assert "13,350.64" in text or "13350.64" in text  # total
    assert "6,675.32" in text or "6675.32" in text  # installment
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "74-1335-45"
    assert exp["annual_total"] == 13350.64
    assert exp["installments"][0]["amount"] == 6675.32
    assert exp["installments"][1]["amount"] == 6675.32


def test_alameda_classify_canonical():
    recipe = load_recipe("alameda", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "74-1335-45",
        "tax_year": "2025-2026",
        "property_address": "164 PURCELL DR, ALAMEDA 94502-6550",
        "annual_total": 13350.64,
        "installments": [
            {"label": "1st installment", "amount": 6675.32, "status": "Paid", "paid_date": "Dec 10, 2025"},
            {"label": "2nd installment", "amount": 6675.32, "status": "Paid", "paid_date": "Apr 10, 2026"},
        ],
    }
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="74-1335-45",
        source_url="https://propertytax.alamedacountyca.gov/account-summary",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "apn" in verified
    assert "annual_total" in verified
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified
    assert missing == []


def test_alameda_off_whitelist_rejected():
    """Strict-mode whitelist must reject zillow / other hosts."""
    recipe = load_recipe("alameda", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "74-1335-45",
        "annual_total": 13350.64,
        "installments": [{"amount": 6675.32}, {"amount": 6675.32}],
    }
    status, _, _, _, error = _classify(
        recipe,
        extracted,
        input_apn="74-1335-45",
        source_url="https://zillow.com/alameda/74-1335-45",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert "source host" in error.lower()


# ---------------------------------------------------------------------------
# Sacramento — iframe portal (county-taxes.net GovHub).
# APN 261-0550-040-0000 / 8244 NORTHWIND WAY, ORANGEVALE.
# ---------------------------------------------------------------------------


def test_sacramento_recipe_uses_iframe_actions():
    recipe = load_recipe("sacramento", recipes_dir=RECIPE_DIR)
    actions = [s.get("action") for s in recipe.get("navigation_steps", [])]
    # The bill detail is in a sub-iframe that re-attaches after the bill
    # click — so we expect enter_frame >= 2 (summary frame + post-click bill frame).
    assert actions.count("enter_frame") >= 2, (
        f"Sacramento recipe must enter the iframe before AND after the bill click (got {actions})"
    )
    assert "county-taxes.net" in recipe["authoritative_source_hosts"]
    assert recipe.get("_portal_topology")


def test_sacramento_fixture_present():
    html = FIXTURE_ROOT / "sacramento" / "captured_apn_261-0550-040-0000.html"
    expected = FIXTURE_ROOT / "sacramento" / "expected_apn_261-0550-040-0000.json"
    assert html.exists()
    assert expected.exists()
    text = html.read_text(encoding="utf-8")
    assert "261-0550-040-0000" in text
    assert "490,605" in text or "490605" in text  # net taxable
    assert "5,895.50" in text or "5895.50" in text  # annual total
    assert "2,947.75" in text  # installment
    assert "054-476" in text  # TRA
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "261-0550-040-0000"
    assert exp["tax_year"] == "2025-26"
    assert exp["tra"] == "054-476"
    assert exp["assessed_value"]["net_taxable"] == 490605.0
    assert exp["annual_total"] == 5895.50
    assert exp["installments"][0]["amount"] == 2947.75
    assert exp["installments"][1]["amount"] == 2947.75


def test_sacramento_classify_canonical():
    recipe = load_recipe("sacramento", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "261-0550-040-0000",
        "tax_year": "2025-26",
        "tra": "054-476",
        "property_address": "8244 NORTHWIND WAY UNINCORPORATED - ORANGEVALE",
        "assessed_value": {
            "land": 98426.0,
            "improvements": 399179.0,
            "exemptions": 7000.0,
            "net_taxable": 490605.0,
        },
        "annual_total": 5895.50,
        "installments": [
            {"label": "1st Installment", "amount": 2947.75, "status": "PAID"},
            {"label": "2nd Installment", "amount": 2947.75, "status": "PAID"},
        ],
    }
    # Source URL is the iframe-taxsys URL — host is county-taxes.net.
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="261-0550-040-0000",
        source_url="https://county-taxes.net/iframe-taxsys/sacramento-ca.county-taxes.com/govhub/property-tax/c2FjcmFtZW50by1jYTpnc2d4X3Byb3BlcnR5X3RheDpwYXJlbnRzOmIxMTRlNWJlLThiNWUtMTFmMC04MTZjLWYzNDZkN2NkYmY0Yg==/bills/B13513AC-8B5E-11F0-BD01-9A0E618C113D",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "assessed_value.net_taxable" in verified
    assert "annual_total" in verified
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified


# ---------------------------------------------------------------------------
# Santa Clara — Teller Online (santaclaracounty.telleronline.net).
# ACTIVE (no longer deferred — 2026-05-13): runner gained `press_key` so the
# Material autocomplete form can be submitted via Enter on #mat-input-1.
# ---------------------------------------------------------------------------


def test_santa_clara_recipe_uses_press_key_action():
    """The active recipe MUST submit via press_key (no submit button in form)."""
    recipe = load_recipe("santa_clara", recipes_dir=RECIPE_DIR)
    # No longer deferred — `_known_limitation` should be gone.
    assert not recipe.get("_known_limitation"), (
        "Santa Clara recipe should no longer be deferred; remove `_known_limitation`."
    )
    # Topology note is still useful for debugging.
    assert recipe.get("_portal_topology")
    actions = [s.get("action") for s in recipe.get("navigation_steps", [])]
    # Exactly one press_key step is expected (Enter on the autocomplete input).
    assert actions.count("press_key") == 1, (
        f"Santa Clara recipe must have exactly one press_key step (got actions: {actions})"
    )
    press_step = next(s for s in recipe["navigation_steps"] if s.get("action") == "press_key")
    # The recipes agent verified the selector + key combination live.
    assert press_step.get("selector") == "#mat-input-1"
    assert (press_step.get("key") or "Enter") == "Enter"


def test_santa_clara_fixture_present():
    html = FIXTURE_ROOT / "santa_clara" / "captured_apn_259-34-015.html"
    expected = FIXTURE_ROOT / "santa_clara" / "expected_apn_259-34-015.json"
    assert html.exists(), f"missing: {html}"
    assert expected.exists()
    text = html.read_text(encoding="utf-8")
    assert "259-34-015" in text
    assert "017-108" in text  # TRA
    assert "155,306.44" in text  # installment amount
    exp = json.loads(expected.read_text(encoding="utf-8"))
    assert exp["apn"] == "259-34-015"
    assert exp["tra"] == "017-108"
    assert exp["installments"][0]["amount"] == 155306.44
    assert exp["installments"][1]["amount"] == 155306.44
    assert exp.get("status") == "TAX_SUCCESS"
    # Should no longer carry the _DEFERRED marker.
    assert "_DEFERRED" not in exp


def test_santa_clara_classify_canonical():
    """Feed the runner's classifier the canonical extraction it would produce
    against the captured Santa Clara HTML. Must classify as TAX_SUCCESS."""
    recipe = load_recipe("santa_clara", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "259-34-015",
        "tax_year": "2025/2026",
        "tra": "017-108",
        "property_address": "1 W SANTA CLARA ST SAN JOSE CA 95113",
        "annual_total": 155306.44,
        "installments": [
            {"label": "Installment 1", "amount": 155306.44, "status": "PAID", "paid_date": "12/09/2025"},
            {"label": "Installment 2", "amount": 155306.44, "status": "PAID", "paid_date": "04/09/2026"},
        ],
    }
    status, verified, missing, _, error = _classify(
        recipe,
        extracted,
        input_apn="259-34-015",
        source_url="https://santaclaracounty.telleronline.net/search/1/details?BsiKey=S_abc123",
        body_text="",
    )
    assert status == "TAX_SUCCESS", f"got {status}: {error}"
    assert "apn" in verified
    assert "installments[0].amount" in verified
    assert "installments[1].amount" in verified
    assert missing == []


def test_santa_clara_off_whitelist_rejected():
    """Strict-mode whitelist must reject non-Teller-Online hosts."""
    recipe = load_recipe("santa_clara", recipes_dir=RECIPE_DIR)
    extracted = {
        "apn": "259-34-015",
        "installments": [{"amount": 155306.44}, {"amount": 155306.44}],
    }
    status, _, _, _, error = _classify(
        recipe,
        extracted,
        input_apn="259-34-015",
        source_url="https://zillow.com/santa-clara/259-34-015",
        body_text="",
    )
    assert status == "TAX_FAILED"
    assert "source host" in error.lower()


# ---------------------------------------------------------------------------
# Adversarial test: estimated/_estimated keys never count toward verified
# ---------------------------------------------------------------------------


def test_estimated_field_does_not_satisfy_verification():
    """Codex finding 2: keys ending in `_estimated` must never count."""
    recipe = load_recipe("san_diego", recipes_dir=RECIPE_DIR)
    extracted = {
        "installments": [
            {"label": "1st", "amount_estimated": 11541.45},
            {"label": "2nd", "amount_estimated": 11541.45},
        ],
    }
    status, _, missing, _, _ = _classify(
        recipe,
        extracted,
        input_apn="452-292-23-00",
        source_url="https://www.sdttc.com/some-path",
        body_text="",
    )
    # Real `installments[0].amount` is None -> missing -> not SUCCESS
    assert status != "TAX_SUCCESS"
    assert "installments[0].amount" in missing
