"""Unit tests for Charlotte County (FL) Property Appraiser (CCPA) adapter.

Uses real fixtures captured from ccappraiser.com on 2026-06-19 (OLAR IVAN,
100 Long Meadow Ln, Rotonda West — subject for batch OLAR / fl_charlotte).

Offline: no live CCPA traffic. parse_parcel_html and _parse_select_page are
pure HTML-in → result-out, so no mocking is needed for the parse layer.
Network tests (lookup_by_address, lookup_by_apn) use MagicMock sessions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser.counties.charlotte_ccpa import CharlotteCCPA  # noqa: E402

_FIXTURES = Path(__file__).parent / "fixtures" / "charlotte"


@pytest.fixture
def ccpa_config() -> Dict[str, Any]:
    return {
        "platform": "charlotte_ccpa_http",
        "county_id": "fl_charlotte",
        "county_name": "Charlotte",
        "base_url": "https://www.ccappraiser.com",
        "status": "live",
    }


@pytest.fixture
def adapter(ccpa_config) -> CharlotteCCPA:
    return CharlotteCCPA(ccpa_config)


# --------------------------------------------------------------------------- #
#  Fixture loading helpers                                                      #
# --------------------------------------------------------------------------- #

def _read_fixture(name: str) -> str:
    path = _FIXTURES / name
    return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
#  parse_parcel_html — real OLAR fixture                                        #
# --------------------------------------------------------------------------- #

def test_parse_parcel_apn_extracted(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.apn == "412024203012", f"Expected APN 412024203012, got {result.apn!r}"


def test_parse_parcel_owner_name(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert "OLAR" in result.owner_of_record.upper(), (
        f"Expected OLAR in owner_of_record, got {result.owner_of_record!r}"
    )


def test_parse_parcel_situs_address(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert "100" in result.situs_address, (
        f"Expected '100' in situs_address, got {result.situs_address!r}"
    )
    assert "LONG MEADOW" in result.situs_address.upper(), (
        f"Expected 'LONG MEADOW' in situs_address, got {result.situs_address!r}"
    )


def test_parse_parcel_just_value(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.just_value == 499242, (
        f"Expected just_value=499242, got {result.just_value}"
    )


def test_parse_parcel_homestead_active(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.homestead_active is True, "Expected homestead_active=True"


def test_parse_parcel_legal_description_present(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.legal_description, "legal_description should be non-empty"
    assert "ROTONDA" in result.legal_description.upper() or "RLM" in result.legal_description.upper(), (
        f"Expected ROTONDA/RLM in legal, got {result.legal_description!r}"
    )


def test_parse_parcel_sales_history_populated(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert len(result.sale_history) >= 1, "Expected at least 1 sale history entry"


def test_parse_parcel_most_recent_sale(adapter):
    """Most recent sale for OLAR: 9/3/2021, $47,000, instrument 2993739."""
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.sale_history, "No sales found"
    most_recent = result.sale_history[0]
    assert "2021" in most_recent.sale_date, (
        f"Most recent sale should be 2021, got {most_recent.sale_date!r}"
    )
    assert most_recent.sale_price == 47000, (
        f"Most recent sale price should be 47000, got {most_recent.sale_price}"
    )
    # Instrument number (recorder cross-ref)
    assert most_recent.deed_doc_number == "2993739", (
        f"Expected deed_doc_number=2993739, got {most_recent.deed_doc_number!r}"
    )
    # Book/Page
    assert "4835" in most_recent.deed_book_page, (
        f"Expected 4835 in deed_book_page, got {most_recent.deed_book_page!r}"
    )


def test_parse_parcel_status_success(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.status == "PA_SUCCESS", f"Expected PA_SUCCESS, got {result.status}"


def test_parse_parcel_fetched_at_set(adapter):
    html = _read_fixture("parcel_detail_olar.html")
    result = adapter.parse_parcel_html(html)
    assert result.fetched_at, "fetched_at should be populated"


def test_parse_parcel_empty_html(adapter):
    result = adapter.parse_parcel_html("")
    assert result.status == "PA_FAILED"


def test_parse_parcel_short_html(adapter):
    result = adapter.parse_parcel_html("<html><body>short</body></html>")
    assert result.status == "PA_FAILED"


# --------------------------------------------------------------------------- #
#  _parse_select_page — real search results fixture                             #
# --------------------------------------------------------------------------- #

def test_parse_select_page_finds_olar(adapter):
    html = _read_fixture("search_select_long_meadow.html")
    results = adapter._parse_select_page(html)
    assert len(results) >= 1, "Expected at least 1 result from search select page"
    # First result should be OLAR / 412024203012
    apn, owner, addr, legal = results[0]
    assert apn, "APN should be non-empty"
    # OLAR should be in the first result
    owners_text = " ".join(r[1] for r in results).upper()
    assert "OLAR" in owners_text, f"OLAR not found in results: {results}"


def test_parse_select_page_apn_format(adapter):
    html = _read_fixture("search_select_long_meadow.html")
    results = adapter._parse_select_page(html)
    for apn, *_ in results:
        assert re.search(r"\d{6,}", apn), f"APN {apn!r} should be numeric"


def test_parse_select_page_empty_html(adapter):
    results = adapter._parse_select_page("<html><body>no results</body></html>")
    assert results == []


# --------------------------------------------------------------------------- #
#  lookup_by_apn — mocked session                                               #
# --------------------------------------------------------------------------- #

def _mock_session(parcel_html: str):
    """Return a mock curl_cffi session that yields parcel HTML on GET."""
    session = MagicMock()
    get_response = MagicMock()
    get_response.text = parcel_html
    get_response.url = "https://www.ccappraiser.com/Show_Parcel.asp"
    session.get.return_value = get_response
    return session


def test_lookup_by_apn_success(adapter, monkeypatch):
    html = _read_fixture("parcel_detail_olar.html")
    mock_sess = _mock_session(html)

    with patch.object(adapter, "_session", return_value=mock_sess):
        result = adapter.lookup_by_apn("412024203012")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "412024203012"
    assert "OLAR" in result.owner_of_record.upper()


def test_lookup_by_apn_strips_hyphens(adapter, monkeypatch):
    """APN with dashes should be normalised before lookup."""
    html = _read_fixture("parcel_detail_olar.html")
    mock_sess = _mock_session(html)

    with patch.object(adapter, "_session", return_value=mock_sess):
        result = adapter.lookup_by_apn("412-024-203-012")

    assert result.status == "PA_SUCCESS"


def test_lookup_by_apn_returns_pa_failed_on_exception(adapter, monkeypatch):
    mock_sess = MagicMock()
    mock_sess.get.side_effect = RuntimeError("network error")

    with patch.object(adapter, "_session", return_value=mock_sess):
        result = adapter.lookup_by_apn("412024203012")

    assert result.status == "PA_FAILED"
    assert "lookup_by_apn error" in result.notes


# --------------------------------------------------------------------------- #
#  lookup_by_address — mocked session                                           #
# --------------------------------------------------------------------------- #

def _mock_address_session(select_html: str, parcel_html: str):
    """Mock session for address lookup: returns select HTML then parcel HTML.

    Call sequence in lookup_by_address:
      GET /RPSearchEnter.asp?   → seed session (returns empty page)
      POST /RPSearchQuery.asp   → returns select_html with url=RPSearchSelect
      GET /Show_Parcel.asp?acct=<APN> → returns parcel_html
    """
    session = MagicMock()

    # POST (RPSearchQuery) returns the select page directly (url contains RPSearchSelect)
    post_resp = MagicMock()
    post_resp.text = select_html
    post_resp.url = "https://www.ccappraiser.com/RPSearchSelect.asp"
    session.post.return_value = post_resp

    # GET calls: (1) seed RPSearchEnter, (2) Show_Parcel.asp detail
    seed_resp = MagicMock()
    seed_resp.text = ""
    seed_resp.url = "https://www.ccappraiser.com/RPSearchEnter.asp?"

    parcel_resp = MagicMock()
    parcel_resp.text = parcel_html
    parcel_resp.url = "https://www.ccappraiser.com/Show_Parcel.asp"

    session.get.side_effect = [seed_resp, parcel_resp]
    return session


# Use the module-level re for the test
import re  # noqa: E402

def test_lookup_by_address_success(adapter, monkeypatch):
    select_html = _read_fixture("search_select_long_meadow.html")
    parcel_html = _read_fixture("parcel_detail_olar.html")
    mock_sess = _mock_address_session(select_html, parcel_html)

    with patch.object(adapter, "_session", return_value=mock_sess):
        result = adapter.lookup_by_address("100 Long Meadow Ln, Rotonda West, FL 33947")

    assert result.status == "PA_SUCCESS"
    assert "OLAR" in result.owner_of_record.upper()


def test_lookup_by_address_no_results(adapter, monkeypatch):
    session = MagicMock()
    empty_resp = MagicMock()
    empty_resp.text = "<html><body>No results found</body></html>"
    empty_resp.url = "https://www.ccappraiser.com/RPSearchSelect.asp"
    session.get.return_value = MagicMock(text="", url="")
    session.post.return_value = empty_resp

    with patch.object(adapter, "_session", return_value=session):
        result = adapter.lookup_by_address("999 Fake St, Punta Gorda, FL 33950")

    assert result.status in ("PA_NO_RESULTS", "PA_FAILED")


def test_lookup_by_address_exception_returns_pa_failed(adapter, monkeypatch):
    session = MagicMock()
    session.get.side_effect = RuntimeError("timeout")

    with patch.object(adapter, "_session", return_value=session):
        result = adapter.lookup_by_address("100 Long Meadow Ln, Rotonda West, FL 33947")

    assert result.status == "PA_FAILED"
    assert "lookup_by_address error" in result.notes


# --------------------------------------------------------------------------- #
#  adapter construction + factory compatibility                                  #
# --------------------------------------------------------------------------- #

def test_adapter_default_county_id(ccpa_config):
    adapter = CharlotteCCPA(ccpa_config)
    assert adapter.county_id == "fl_charlotte"


def test_adapter_county_name(ccpa_config):
    adapter = CharlotteCCPA(ccpa_config)
    assert adapter.county_name == "Charlotte"


def test_adapter_empty_config():
    adapter = CharlotteCCPA({})
    assert adapter.county_id == "fl_charlotte"  # default
    assert "ccappraiser" in adapter.base_url
