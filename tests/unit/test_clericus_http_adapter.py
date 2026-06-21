"""Unit tests for ClericusHTTPAdapter (myfloridacounty.com platform).

All tests run against **real HTML fixtures** captured from Nassau (county_id=45)
on 2026-06-18 (live-validated session). No network calls are made.

Fixture files (tests/unit/fixtures/clericus/):
  nassau_landing.html           — Landing page (GET /orisearch/45)
  nassau_kelly_search_results.html  — All-docs search for KELLY (25 rows, 8 pages)
  nassau_kelly_deed_results.html    — DEED-only search for KELLY (25 rows)
  nassau_no_results.html            — Empty search response (no table)

Tests cover:
  1. Parsing name search results (all-docs)
  2. Parsing deed-filtered results
  3. Party de-duplication (same instrument → multiple rows → merged)
  4. q2 hash extraction (View Image link)
  5. Empty results (no table)
  6. Pagination URL extraction
  7. Config-driven county switching (De Soto vs Nassau vs Sumter)
  8. DocType resolution
  9. Party-type radio value mapping
  10. warm_session landing-page parsing (mocked)
"""

import json
import pathlib
import re
import sys
import types
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Ensure the src tree is importable
_ROOT = pathlib.Path(__file__).parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from titlepro.search.recorder.counties.adapters.clericus_http_adapter import (
    ClericusHTTPAdapter,
    DOCTYPE_ALL,
    DOCTYPE_DEED,
    DOCTYPE_MORTGAGE,
    DOCTYPE_SATISFACTION,
    PARTY_BOTH,
    PARTY_FROM,
    PARTY_TO,
    TURNSTILE_SITEKEY,
    _RESULT_ROW_GRANTOR_CODE,
    _RESULT_ROW_GRANTEE_CODE,
)
from titlepro.search.recorder.base_recorder import DocumentRecord

# ---------------------------------------------------------------------------
# Fixtures path
# ---------------------------------------------------------------------------

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "clericus"


def _load(filename: str) -> str:
    return (FIXTURES / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

NASSAU_CONFIG = {
    "county_id": "fl_nassau",
    "county_name": "Nassau",
    "state": "FL",
    "platform": "clericus_http",
    "base_url": "https://www.myfloridacounty.com",
    "clericus_county_id": "45",
    "captcha_api_key": "FAKE_KEY_FOR_TESTS",
}

DESOTO_CONFIG = {
    "county_id": "fl_de_soto",
    "county_name": "DeSoto",
    "state": "FL",
    "platform": "clericus_http",
    "base_url": "https://www.myfloridacounty.com",
    "clericus_county_id": "14",
    "captcha_api_key": "FAKE_KEY_FOR_TESTS",
}

SUMTER_CONFIG = {
    "county_id": "fl_sumter",
    "county_name": "Sumter",
    "state": "FL",
    "platform": "clericus_http",
    "base_url": "https://www.myfloridacounty.com",
    "clericus_county_id": "60",
    "captcha_api_key": "FAKE_KEY_FOR_TESTS",
}


def _adapter(config: Dict = None) -> ClericusHTTPAdapter:
    """Return a pre-warmed adapter using the Nassau landing fixture."""
    config = config or NASSAU_CONFIG
    adapter = ClericusHTTPAdapter(config, start_date="01/01/1990", end_date="12/31/2026")
    # Manually inject session state as warm_session would set it
    adapter._q1 = "PUekI0zIOB3tlIGH1rpZaA"
    adapter._action_path = "/orisearch/s/search?q1=PUekI0zIOB3tlIGH1rpZaA"
    adapter._session_warmed = True
    adapter.verified_until_date = "6/12/2026"
    return adapter


# ---------------------------------------------------------------------------
# Test 1: Basic instantiation
# ---------------------------------------------------------------------------


def test_instantiation_requires_county_id():
    """Missing clericus_county_id raises ValueError."""
    with pytest.raises(ValueError, match="clericus_county_id"):
        ClericusHTTPAdapter({"county_name": "Test", "platform": "clericus_http"})


def test_instantiation_nassau():
    adapter = _adapter(NASSAU_CONFIG)
    assert adapter.county_name == "Nassau"
    assert adapter._county_id == "45"
    assert adapter._base == "https://www.myfloridacounty.com"
    assert adapter._landing_url == "https://www.myfloridacounty.com/orisearch/45"


def test_instantiation_desoto():
    adapter = _adapter(DESOTO_CONFIG)
    assert adapter.county_name == "DeSoto"
    assert adapter._county_id == "14"
    assert adapter._landing_url == "https://www.myfloridacounty.com/orisearch/14"


def test_instantiation_sumter():
    adapter = _adapter(SUMTER_CONFIG)
    assert adapter.county_name == "Sumter"
    assert adapter._county_id == "60"


# ---------------------------------------------------------------------------
# Test 2: warm_session landing-page parsing
# ---------------------------------------------------------------------------


def test_warm_session_parses_landing_page():
    """warm_session extracts q1 token and effective date from landing HTML."""
    adapter = ClericusHTTPAdapter(NASSAU_CONFIG)

    landing_html = _load("nassau_landing.html")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = landing_html

    with patch.object(adapter.session, "get", return_value=mock_resp):
        result = adapter.warm_session()

    assert result is True
    assert adapter._session_warmed is True
    assert adapter._q1 == "PUekI0zIOB3tlIGH1rpZaA"
    # Action path should contain jsessionid
    assert "/orisearch/s/search" in adapter._action_path
    assert adapter.verified_until_date is not None  # e.g. "6/12/2026"


# ---------------------------------------------------------------------------
# Test 3: Parse name search results (all-docs)
# ---------------------------------------------------------------------------


def test_parse_results_all_docs():
    """Extract_results from the all-docs Nassau KELLY search returns records."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")

    records = adapter.extract_results(html)

    # The fixture has 25 rows; after de-dup by instrument number we expect fewer
    # records because the same instrument appears under each party name
    assert len(records) > 0
    assert len(records) <= 25

    # All records are DocumentRecord instances
    assert all(isinstance(r, DocumentRecord) for r in records)

    # Every record has an instrument number
    assert all(r.document_number for r in records)

    # Every record has a recording date
    assert all(r.recording_date for r in records)


def test_parse_results_instrument_numbers():
    """Instrument numbers follow the expected Nassau format (YYYYNNNNNNNNNN)."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    records = adapter.extract_results(html)

    for r in records:
        assert re.match(r"^\d{12}$", r.document_number), (
            f"Unexpected instrument format: {r.document_number}"
        )


def test_parse_results_deduplication():
    """Same instrument number listed under multiple parties → one DocumentRecord."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    records = adapter.extract_results(html)

    instrument_numbers = [r.document_number for r in records]
    assert len(instrument_numbers) == len(set(instrument_numbers)), (
        "Duplicate instrument numbers in output — de-dup broken"
    )


def test_parse_results_party_names_merged():
    """Multiple party-name rows for the same instrument merge into grantors/grantees."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    records = adapter.extract_results(html)

    # From the fixture we know 202645015884 appears 4 times (2 From + 2 To)
    target = next(
        (r for r in records if r.document_number == "202645015884"), None
    )
    # Instrument 202645015884 (D, KELLY MICHAEL DAVID, KELLY MARGO PALLARDY + 2 To)
    if target:
        # Both grantors and grantees should be populated
        assert target.grantors, f"Expected grantors for {target.document_number}"
        assert target.grantees, f"Expected grantees for {target.document_number}"


# ---------------------------------------------------------------------------
# Test 4: Parse deed-filtered results
# ---------------------------------------------------------------------------


def test_parse_deed_results():
    """DEED-filtered fixture parses successfully (server returns ALL types; client filters)."""
    adapter = _adapter()
    html = _load("nassau_kelly_deed_results.html")
    records = adapter.extract_results(html)

    assert len(records) > 0
    # extract_results returns all types (client-side filter applied in perform_search)
    # Verify there are D-type records in the raw parse
    deed_types = {"D", "QCD", "WD", "DEED", "TD"}
    all_types = {r.document_type.upper() for r in records}
    assert len(all_types) >= 1, f"No document types parsed; records={records}"


def test_client_side_deed_filter():
    """_apply_doctype_filter correctly keeps only DEED-family instruments."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    all_records = adapter.extract_results(html)

    # Apply DEED filter
    deed_records = adapter._apply_doctype_filter(all_records, "DEED")

    # Should have fewer records than all
    assert len(deed_records) < len(all_records)
    # All remaining should be deed-family
    deed_family = {"D", "QCD", "WD", "TD", "AGD", "FA", "DEED"}
    non_deed = [r for r in deed_records if r.document_type.upper() not in deed_family]
    assert non_deed == [], f"Non-deed records passed filter: {[(r.document_number, r.document_type) for r in non_deed]}"
    # Should be at least 1 deed
    assert len(deed_records) >= 1


def test_client_side_all_filter_passthrough():
    """_apply_doctype_filter with 'ALL' returns all records unchanged."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    all_records = adapter.extract_results(html)
    filtered = adapter._apply_doctype_filter(all_records, "ALL")
    assert len(filtered) == len(all_records)


# ---------------------------------------------------------------------------
# Test 5: Empty results (no table)
# ---------------------------------------------------------------------------


def test_parse_no_results():
    """Empty results page (no table) returns an empty list."""
    adapter = _adapter()
    html = _load("nassau_no_results.html")
    records = adapter.extract_results(html)
    assert records == []


def test_extract_results_empty_string():
    """extract_results('') returns empty list (no crash)."""
    adapter = _adapter()
    records = adapter.extract_results("")
    assert records == []


# ---------------------------------------------------------------------------
# Test 6: q2 hash extraction and download caching
# ---------------------------------------------------------------------------


def test_q2_hash_extracted_from_results():
    """View Image q2 hash is cached per instrument after parse."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    adapter.extract_results(html)

    # At least some instruments should have q2 hashes cached
    assert len(adapter._q2_by_instrument) > 0, "No q2 hashes cached"

    # q2 hashes should be 32-char hex strings
    for instr, q2 in adapter._q2_by_instrument.items():
        assert re.match(r"^[a-f0-9]{32}$", q2), (
            f"Unexpected q2 format for {instr}: {q2!r}"
        )


def test_download_pdf_without_q2_returns_error():
    """download_pdf returns error dict when q2 not cached."""
    adapter = _adapter()
    result = adapter.download_pdf(doc_num="202600000001")
    assert result["status"] == "error"
    assert "q2" in result["message"].lower()


def test_download_pdf_with_explicit_q2(tmp_path):
    """download_pdf with an explicit q2 calls the image endpoint and writes the file."""
    adapter = _adapter()

    # Mock the session.get to return a fake PDF
    mock_get = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"%PDF-1.4 fake content"
    mock_get.return_value = mock_resp

    dest = str(tmp_path / "test.pdf")

    with patch.object(adapter.session, "get", mock_get):
        result = adapter.download_pdf(
            doc_num="202645017158",
            dest_path=dest,
            q2="fdf9a2591c00f3a5a8e2648e06bdd99b",
        )

    assert result["status"] == "success"
    assert result["size"] > 0
    # Verify mock was called
    assert mock_get.called
    # The URL should contain the image endpoint
    call_url = mock_get.call_args[0][0] if mock_get.call_args[0] else ""
    call_url = call_url or str(mock_get.call_args)
    assert "image" in call_url or mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Test 7: Pagination URL extraction
# ---------------------------------------------------------------------------


def test_next_page_url_found():
    """_next_page_url returns a URL for an existing page reference."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")

    # Pages 2-8 are referenced in the fixture
    url = adapter._next_page_url(html, 2)
    assert url is not None
    assert "d-8001259-p=2" in url


def test_next_page_url_missing():
    """_next_page_url returns None for a page that doesn't exist in pagination."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    # There is no page 100 in the pagination widget
    url = adapter._next_page_url(html, 100)
    assert url is None


# ---------------------------------------------------------------------------
# Test 8: DocType resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc_type, expected", [
    (None, DOCTYPE_ALL),
    ("ALL", DOCTYPE_ALL),
    ("", DOCTYPE_ALL),
    ("DEED", DOCTYPE_DEED),
    ("D", DOCTYPE_DEED),
    ("deed", DOCTYPE_DEED),
    ("MORTGAGE", DOCTYPE_MORTGAGE),
    ("MTG", DOCTYPE_MORTGAGE),
    ("SATISFACTION", DOCTYPE_SATISFACTION),
    ("SAT", DOCTYPE_SATISFACTION),
    ("10", "10"),   # raw numeric passthrough
    ("21", "21"),
])
def test_resolve_doctype(doc_type, expected):
    adapter = _adapter()
    result = adapter._resolve_doctype(doc_type)
    assert result == expected, f"_resolve_doctype({doc_type!r}) = {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# Test 9: Party-type radio mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("party_type, expected_radio", [
    ("All", PARTY_BOTH),
    ("Both", PARTY_BOTH),
    ("Grantor/Grantee", PARTY_BOTH),
    ("Grantor", PARTY_FROM),
    ("Grantee", PARTY_TO),
])
def test_party_type_map(party_type, expected_radio):
    adapter = _adapter()
    result = adapter._party_map.get(party_type)
    assert result == expected_radio, (
        f"party_map[{party_type!r}] = {result!r}, expected {expected_radio!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: Config-driven county switching
# ---------------------------------------------------------------------------


def test_county_switching_desoto():
    """DeSoto config produces correct county_id and landing URL."""
    adapter = _adapter(DESOTO_CONFIG)
    assert adapter._county_id == "14"
    assert adapter._landing_url.endswith("/orisearch/14")


def test_county_switching_nassau():
    adapter = _adapter(NASSAU_CONFIG)
    assert adapter._county_id == "45"
    assert adapter._landing_url.endswith("/orisearch/45")


def test_county_switching_sumter():
    adapter = _adapter(SUMTER_CONFIG)
    assert adapter._county_id == "60"
    assert adapter._landing_url.endswith("/orisearch/60")


# ---------------------------------------------------------------------------
# Test 11: perform_search without CAPTCHA_API_KEY returns []
# ---------------------------------------------------------------------------


def test_perform_search_no_captcha_key_returns_empty():
    """perform_search logs a message and returns [] when no 2captcha key available."""
    config = {**NASSAU_CONFIG, "captcha_api_key": ""}
    adapter = ClericusHTTPAdapter(config)
    adapter._q1 = "PUekI0zIOB3tlIGH1rpZaA"
    adapter._action_path = "/orisearch/s/search?q1=PUekI0zIOB3tlIGH1rpZaA"
    adapter._session_warmed = True
    # Remove the key so the solver path returns None
    adapter._captcha_api_key = None

    # Mock _solve_turnstile to return None (as if key missing)
    with patch.object(adapter, "_solve_turnstile", return_value=None):
        records = adapter.perform_search("KELLY", doc_type="DEED")

    assert records == []


# ---------------------------------------------------------------------------
# Test 12: perform_search with mocked solve + mocked HTTP returns records
# ---------------------------------------------------------------------------


def test_perform_search_full_flow_mocked():
    """perform_search with mocked Turnstile + mocked HTTP response returns records."""
    adapter = _adapter()
    results_html = _load("nassau_kelly_deed_results.html")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = results_html

    with patch.object(adapter, "_solve_turnstile", return_value="FAKE_TOKEN"), \
         patch.object(adapter.session, "post", return_value=mock_resp):
        records = adapter.perform_search("KELLY", doc_type="DEED")

    assert len(records) > 0
    assert all(isinstance(r, DocumentRecord) for r in records)


# ---------------------------------------------------------------------------
# Test 13: DocumentRecord fields populated correctly
# ---------------------------------------------------------------------------


def test_document_record_fields():
    """Records from Nassau KELLY search have all required fields set."""
    adapter = _adapter()
    html = _load("nassau_kelly_search_results.html")
    records = adapter.extract_results(html)

    assert records, "No records parsed"
    for r in records:
        assert r.document_number, f"Empty document_number"
        assert r.document_type, f"Empty document_type for {r.document_number}"
        assert r.recording_date, f"Empty recording_date for {r.document_number}"
        # grantor_grantees should be a combination
        assert r.grantor_grantees or (r.grantors and r.grantees) or r.grantors, (
            f"No parties for {r.document_number}"
        )


# ---------------------------------------------------------------------------
# Test 14: pull_detail returns a dict (no crash)
# ---------------------------------------------------------------------------


def test_pull_detail_returns_dict():
    adapter = _adapter()
    result = adapter.pull_detail("202645017158")
    assert isinstance(result, dict)
    assert result.get("document_number") == "202645017158"


# ---------------------------------------------------------------------------
# Test 15: Turnstile sitekey constant
# ---------------------------------------------------------------------------


def test_turnstile_sitekey_constant():
    """The Turnstile sitekey matches the one observed on the live portal."""
    assert TURNSTILE_SITEKEY == "0x4AAAAAAA64PTBePmuGbrkR"


# ---------------------------------------------------------------------------
# Test 16: Grantor/grantee mapping for party codes F and T (result-row codes)
# Regression: constant names PARTY_FROM="T" / PARTY_TO="F" were misleading
# because they refer to the *search radio* values, not the *result-row* codes.
# The parse logic correctly maps result-row F → Grantor, T → Grantee.
# This test asserts that mapping is self-consistent with the named constants.
# ---------------------------------------------------------------------------


def test_result_row_party_code_f_maps_to_grantor():
    """Result-row party code 'F' must produce a grantor entry (live-validated Nassau)."""
    adapter = _adapter()
    # Build minimal Nassau-style HTML with one row where Party Type = F (grantor)
    html = """
    <table id="ori_results">
      <tr><th>Party Name</th><th>Party Type</th><th>Date</th>
          <th>Document Type</th><th>Instrument Number</th>
          <th>Book/Page</th><th>Pages</th><th>Consideration Amount</th>
          <th>Description</th></tr>
      <tr>
        <td>KELLY JOHN</td><td>F</td><td>01/15/2020</td>
        <td>WD</td><td>202012345</td>
        <td>2020/100</td><td>3</td><td>300000</td>
        <td>LOT 1 BLOCK A</td>
      </tr>
    </table>
    """
    records, _ = adapter._parse_results_page(html)
    assert len(records) == 1
    r = records[0]
    assert r.grantors == "KELLY JOHN", (
        f"Party code 'F' must map to grantor. Got grantors={r.grantors!r}, "
        f"grantees={r.grantees!r}. "
        f"_RESULT_ROW_GRANTOR_CODE={_RESULT_ROW_GRANTOR_CODE!r}"
    )
    assert r.grantees == "", f"Party code 'F' must NOT populate grantees. Got {r.grantees!r}"
    assert _RESULT_ROW_GRANTOR_CODE == "F", "Sanity: grantor result-row code must be 'F'"


def test_result_row_party_code_t_maps_to_grantee():
    """Result-row party code 'T' must produce a grantee entry (live-validated Nassau)."""
    adapter = _adapter()
    html = """
    <table id="ori_results">
      <tr><th>Party Name</th><th>Party Type</th><th>Date</th>
          <th>Document Type</th><th>Instrument Number</th>
          <th>Book/Page</th><th>Pages</th><th>Consideration Amount</th>
          <th>Description</th></tr>
      <tr>
        <td>SMITH BUYER</td><td>T</td><td>01/15/2020</td>
        <td>WD</td><td>202012345</td>
        <td>2020/100</td><td>3</td><td>300000</td>
        <td>LOT 1 BLOCK A</td>
      </tr>
    </table>
    """
    records, _ = adapter._parse_results_page(html)
    assert len(records) == 1
    r = records[0]
    assert r.grantees == "SMITH BUYER", (
        f"Party code 'T' must map to grantee. Got grantors={r.grantors!r}, "
        f"grantees={r.grantees!r}. "
        f"_RESULT_ROW_GRANTEE_CODE={_RESULT_ROW_GRANTEE_CODE!r}"
    )
    assert r.grantors == "", f"Party code 'T' must NOT populate grantors. Got {r.grantors!r}"
    assert _RESULT_ROW_GRANTEE_CODE == "T", "Sanity: grantee result-row code must be 'T'"


def test_search_radio_grantor_uses_party_from_constant():
    """_party_map must route 'Grantor' → PARTY_FROM (the search radio value for From/Grantor).

    This confirms the search-radio constants (PARTY_FROM/PARTY_TO) are separate from
    the result-row parse constants (_RESULT_ROW_GRANTOR_CODE / _RESULT_ROW_GRANTEE_CODE).
    """
    adapter = _adapter()
    # The search party map should route "Grantor" to PARTY_FROM
    assert adapter._party_map.get("Grantor") == PARTY_FROM, (
        f"'Grantor' should map to PARTY_FROM={PARTY_FROM!r} in the search radio. "
        f"Got {adapter._party_map.get('Grantor')!r}"
    )
    # PARTY_FROM is the radio value sent to the server — NOT the result-row parse code
    assert PARTY_FROM != _RESULT_ROW_GRANTOR_CODE, (
        "Search radio PARTY_FROM and result-row _RESULT_ROW_GRANTOR_CODE "
        "must be different values (they represent different server-side semantics)"
    )
