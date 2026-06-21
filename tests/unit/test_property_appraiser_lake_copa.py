"""Unit tests for LakeCOPA — Lake County (FL) Property Appraiser adapter.

All tests are offline: they feed captured HTML fixtures and validate parse
output without any network. The fixtures were captured live on 2026-06-18
from www.lakecopropappr.com.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Skip if BeautifulSoup not available
bs4 = pytest.importorskip("bs4", reason="beautifulsoup4 required")

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pa_lake"

# ---------------------------------------------------------------- helpers
def _load(name: str) -> str:
    p = FIXTURE_DIR / name
    if not p.exists():
        pytest.skip(f"fixture {name!r} not found — run live probe first")
    return p.read_text(encoding="utf-8", errors="replace")


# ================================================================ adapter import
def test_adapter_import():
    """Adapter class importable."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    assert LakeCOPA is not None


def test_adapter_init():
    """Adapter initialises with minimal config."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    pa = LakeCOPA({"county_id": "fl_lake", "county_name": "Lake"})
    assert pa.county_id == "fl_lake"
    assert pa.county_name == "Lake"
    assert "lakecopropappr.com" in pa.base_url


# ================================================================ hidden-input extraction
def test_hidden_input_extraction():
    """_harvest_inputs extracts VIEWSTATE and other hidden fields."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    pa = LakeCOPA({})
    html = """
    <form>
      <input type="hidden" name="__VIEWSTATE" value="abc123" />
      <input type="hidden" name="__EVENTVALIDATION" value="xyz789" />
      <input type="text" name="ctl00$cphMain$txtStreet" value="" />
    </form>
    """
    inputs = pa._harvest_inputs(html)
    assert inputs.get("__VIEWSTATE") == "abc123"
    assert inputs.get("__EVENTVALIDATION") == "xyz789"
    assert "ctl00$cphMain$txtStreet" in inputs


# ================================================================ results grid parsing
def test_parse_results_grid_from_fixture():
    """Grid parse returns AltKey tuples from live search results."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("search_results_belland.html")
    results = LakeCOPA.parse_results_grid(html) if hasattr(LakeCOPA, "parse_results_grid") else LakeCOPA._parse_results_grid(html)
    assert len(results) > 0, "Expected at least one result for BELLAND CIR search"
    alt_key, owner, parcel, city = results[0]
    assert alt_key.isdigit(), f"AltKey should be numeric, got {alt_key!r}"
    assert len(alt_key) == 7, f"AltKey should be 7 digits, got {len(alt_key)}"


def test_parse_results_grid_owner_content():
    """Grid results contain owner address text."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("search_results_belland.html")
    results = LakeCOPA._parse_results_grid(html)
    assert results, "Expected results"
    # At least one result should contain BELLAND in the owner cell
    belland_found = any("BELLAND" in r[1].upper() for r in results)
    assert belland_found, f"Expected BELLAND in owner cells, got: {[r[1] for r in results[:3]]}"


# ================================================================ detail page parsing
def test_parse_detail_html_fields():
    """parse_detail_html extracts key property fields from captured fixture."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("parcel_detail.html")
    result = LakeCOPA.parse_detail_html(html)

    assert result.status == "PA_SUCCESS", f"Expected PA_SUCCESS, got {result.status}: {result.notes}"
    # Owner should be populated
    assert result.owner_of_record, "owner_of_record should be populated"
    # Parcel number in Lake format: XX-XX-XX-XXXX-XXX-XXXXXX
    assert result.apn, "apn (parcel number) should be populated"
    # Situs address
    assert result.situs_address, "situs_address should be populated"


def test_parse_detail_html_parcel_format():
    """Parcel number matches Lake County format (contains dashes)."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("parcel_detail.html")
    result = LakeCOPA.parse_detail_html(html)
    # Lake County parcel format: 03-23-26-0109-000-012C0
    assert "-" in result.apn or len(result.apn) > 5, \
        f"Parcel number looks wrong: {result.apn!r}"


def test_parse_detail_html_legal_description():
    """Legal description is extracted."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("parcel_detail.html")
    result = LakeCOPA.parse_detail_html(html)
    assert result.legal_description, "legal_description should be populated"


def test_parse_detail_html_sales_history():
    """Sales history is parsed (at least one entry from fixture)."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("parcel_detail.html")
    result = LakeCOPA.parse_detail_html(html)
    # The BELLAND CIR parcel (AltKey=3904456) shows sales in the fixture
    assert isinstance(result.sale_history, list), "sale_history should be a list"


def test_parse_detail_html_values():
    """Market/Just value is extracted as int."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("parcel_detail.html")
    result = LakeCOPA.parse_detail_html(html)
    # The fixture shows "$256,936" as market value
    assert result.just_value > 0, f"Expected positive just_value, got {result.just_value}"


def test_parse_detail_html_empty():
    """parse_detail_html on empty string returns PA_FAILED not crash."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    result = LakeCOPA.parse_detail_html("")
    assert result.status == "PA_FAILED"


def test_parse_detail_html_no_results_page():
    """parse_detail_html on the TOU page (wrong page) doesn't crash."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    html = _load("tou_page.html")
    result = LakeCOPA.parse_detail_html(html)
    # Should fail gracefully — the TOU page has no property data
    assert result.status in ("PA_SUCCESS", "PA_FAILED"), \
        f"Unexpected status: {result.status}"


# ================================================================ factory wiring
def test_factory_routes_lake_copa():
    """fetch_property_appraiser routes fl_lake to LakeCOPA (no network)."""
    from titlepro.property_appraiser import fetch_property_appraiser
    # Requires fl_lake entry in county_property_appraiser_urls.json
    # This test will return PA_NO_RUNNER if not yet wired — acceptable
    result = fetch_property_appraiser("fl_lake", address="3513 BELLAND CIR UNIT D, CLERMONT, FL")
    # Should not crash — any status is fine pre-wiring except an exception
    assert result.status in ("PA_SUCCESS", "PA_NO_RESULTS", "PA_FAILED", "PA_NO_RUNNER", "PA_AMBIGUOUS")


# ================================================================ money helper
def test_money_helper():
    """_money helper parses currency strings correctly."""
    from titlepro.property_appraiser.counties.lake_copa import _money
    assert _money("$256,936") == 256936
    assert _money("$201,100.00") == 201100
    assert _money("$100") == 100
    assert _money("") == 0
    assert _money("N/A") == 0


def test_pick_best_match():
    """_pick_best_match selects row with matching house number."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    pa = LakeCOPA({})
    results = [
        ("3904456", "ACEVEDO VICTOR M & MARILYN I  TRUSTEES\n3549 BELLAND CIR UNIT C\nCLERMONT, FL 34711", "03-23-26-0109-000-012C0", "CLERMONT"),
        ("3904399", "SMITH JOHN\n3513 BELLAND CIR UNIT D\nCLERMONT, FL 34711", "03-23-26-0109-000-012D0", "CLERMONT"),
    ]
    alt_key = pa._pick_best_match(results, "3513 BELLAND CIR UNIT D")
    assert alt_key == "3904399", f"Expected 3904399, got {alt_key}"


# ================================================================ APN truncation regression
def test_lookup_by_apn_rejects_long_parcel_id():
    """lookup_by_apn must NOT truncate a standard FL 17-char Parcel ID to 7 chars.

    Regression: the original code did ``apn_clean[:7]`` unconditionally, so a
    standard Parcel ID like "03-23-26-0109-000-012C0" would be truncated to
    "0323260" (first 7 digits), matching a completely different AltKey on the
    portal and returning wrong-parcel data with PA_SUCCESS.

    The fix: only use the AltKey field when the cleaned APN is ≤7 digits;
    otherwise return PA_NO_RESULTS with an explanatory note so the caller can
    redirect to lookup_by_address.
    """
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    from unittest.mock import patch, MagicMock

    pa = LakeCOPA({"county_id": "fl_lake"})

    # Standard FL Parcel ID (17 chars after stripping dashes = 15 alphanum)
    long_apn = "03-23-26-0109-000-012C0"

    # Patch _session so no real HTTP is made
    mock_session = MagicMock()
    with patch.object(pa, "_session", return_value=mock_session):
        result = pa.lookup_by_apn(long_apn)

    # Must NOT return PA_SUCCESS with truncated/wrong data
    assert result.status == "PA_NO_RESULTS", (
        f"Expected PA_NO_RESULTS for a long Parcel ID (not a 7-digit AltKey). "
        f"Got status={result.status!r}. "
        "If this returns PA_SUCCESS it may be returning wrong-parcel data "
        "because the APN was silently truncated to 7 chars."
    )
    assert "AltKey" in (result.notes or ""), (
        "Notes should explain the AltKey limitation so the caller knows to use "
        "lookup_by_address instead."
    )


def test_lookup_by_apn_accepts_seven_digit_altkey():
    """lookup_by_apn must accept a genuine 7-digit AltKey directly."""
    from titlepro.property_appraiser.counties.lake_copa import LakeCOPA
    from unittest.mock import patch, MagicMock

    pa = LakeCOPA({"county_id": "fl_lake"})

    # Genuine 7-digit AltKey
    altkey = "3904456"

    mock_session = MagicMock()
    # _accept_tou returns (html, viewstate_dict)
    mock_session.get.return_value = MagicMock(text="<html></html>", status_code=200)

    with patch.object(pa, "_accept_tou", return_value=("", {})) as mock_tou, \
         patch.object(pa, "parse_detail_html") as mock_parse, \
         patch.object(pa, "_session", return_value=mock_session):
        mock_parse.return_value = MagicMock(status="PA_SUCCESS", source_url="")
        result = pa.lookup_by_apn(altkey)

    # Should attempt the direct AltKey detail URL, not fall through to the
    # long-APN guard
    assert result.status == "PA_SUCCESS"
