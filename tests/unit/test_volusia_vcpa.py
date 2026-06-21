"""Unit tests for the Volusia VCPA Property Appraiser adapter.

No live traffic — the parcel-summary fixture is the REAL HTML captured on the
2026-06-10 probe (GUILD subject, altkey 3470141), saved at
tests/fixtures/volusia/vcpa_parcel_summary_3470141.html. Search responses are
canned from the same probe (tests/fixtures/volusia/vcpa_search_435_elsie.json).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser import fetch_property_appraiser  # noqa: E402
from titlepro.property_appraiser.counties.volusia_vcpa import VolusiaVCPA  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "volusia"
SUMMARY_HTML = (FIXTURES / "vcpa_parcel_summary_3470141.html").read_text()
SEARCH_GUILD = json.loads((FIXTURES / "vcpa_search_435_elsie.json").read_text())


@pytest.fixture
def vcpa_config() -> Dict[str, Any]:
    return {
        "platform": "vcpa_http",
        "base_url": "https://vcpa.vcgov.org/",
        "endpoints": {
            "search_real_property": "https://vcpa.vcgov.org/api/search/real-property",
            "parcel_summary": "https://vcpa.vcgov.org/parcel/summary/?altkey={altkey}",
        },
        "captcha": False,
    }


def _make_response(status_code: int, payload: Any):
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(payload, (dict, list)):
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = str(payload)
    return resp


def _adapter_with_canned(vcpa_config, search_payload=None, summary_html=None):
    adapter = VolusiaVCPA(vcpa_config)
    adapter.session = MagicMock()
    adapter.session.post.return_value = _make_response(
        200, search_payload if search_payload is not None else SEARCH_GUILD
    )
    adapter.session.get.return_value = _make_response(
        200, summary_html if summary_html is not None else SUMMARY_HTML
    )
    return adapter


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("435 Elsie Avenue, Holly Hill, FL 32117", "435 ELSIE AVE"),
        ("435 ELSIE AVE", "435 ELSIE AVE"),
        ("11 Little Tomoka Way, Ormond Beach, FL", "11 LITTLE TOMOKA WAY"),
        ("100 W 27th Street, Daytona Beach", "100 W 27 ST"),
        ("  5 Oak  Drive ", "5 OAK DR"),
    ],
)
def test_normalize_address(input_addr, expected):
    assert VolusiaVCPA._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("533705070110", "533705070110"),
        ("5337-05-07-0110", "533705070110"),
        ("  53 37 05 07 0110  ", "533705070110"),
        ("3470141", "3470141"),  # altkey passthrough
        ("", ""),
    ],
)
def test_normalize_apn(input_apn, expected):
    assert VolusiaVCPA._normalize_apn(input_apn) == expected


# ---------------------------------------------------------------------------
# Summary parse — real captured HTML
# ---------------------------------------------------------------------------


def test_lookup_by_apn_guild_parses_full_parcel(vcpa_config):
    adapter = _adapter_with_canned(vcpa_config)
    result = adapter.lookup_by_apn("533705070110")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "533705070110"
    assert result.folio == "3470141"
    assert result.owner_of_record == "GUILD MARYKE Y"
    assert result.co_owners == ["GUILD JUSTIN P"]
    assert result.situs_address.startswith("435 ELSIE AVE")
    assert "CLIFTON PARK" in result.legal_description
    assert result.homestead_active is True
    assert result.just_value == 124_517  # 2026 Working column
    assert result.source_url.endswith("altkey=3470141")


def test_guild_sale_history_full_back_chain(vcpa_config):
    adapter = _adapter_with_canned(vcpa_config)
    result = adapter.lookup_by_apn("533705070110")

    sales = result.sale_history
    assert len(sales) == 6
    # Current vesting: 12/20/2016 WD (QUALIFIED, $60,000) + same-date PR deed.
    assert sales[0].sale_date == "12/20/2016"
    assert sales[0].deed_doc_number == "2016240820"
    assert sales[0].deed_book_page == "7343 / 1337"
    assert sales[0].deed_type.startswith("PR1")
    assert sales[0].qualified is False
    assert sales[1].sale_date == "12/20/2016"
    assert sales[1].deed_doc_number == "2016240819"
    assert sales[1].deed_book_page == "7343 / 1336"
    assert sales[1].deed_type == "WD-WARRANTY DEED"
    assert sales[1].qualified is True
    assert sales[1].sale_price == 60_000
    # Prior-owner acquisition (defines the two-owner window start):
    assert sales[2].sale_date == "12/15/1996"
    assert sales[2].deed_doc_number == "1996208337"
    assert sales[2].deed_book_page == "4160 / 2999"
    # Oldest row has NO instrument number (pre-CIN era) — book/page only.
    assert sales[5].sale_date == "09/15/1982"
    assert sales[5].deed_doc_number == ""
    assert sales[5].deed_book_page == "2391 / 0674"
    assert sales[5].sale_price == 35_000


def test_deed_identifiers_prefer_instrument_numbers(vcpa_config):
    adapter = _adapter_with_canned(vcpa_config)
    result = adapter.lookup_by_apn("533705070110")
    ids = result.deed_identifiers()
    assert ids[0] == "2016240820"
    assert ids[1] == "2016240819"
    assert "2391" in ids[-1]  # book/page fallback for the 1982 deed


# ---------------------------------------------------------------------------
# Address lookup — orchestration
# ---------------------------------------------------------------------------


def test_lookup_by_address_guild_collapses_owner_rows(vcpa_config):
    """The search API returns one row PER OWNER (2 rows, same altkey) —
    the adapter must collapse to a single parcel, not report ambiguity."""
    adapter = _adapter_with_canned(vcpa_config)
    result = adapter.lookup_by_address("435 Elsie Avenue, Holly Hill, FL 32117")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "3470141"
    # POST search once, GET summary once.
    assert adapter.session.post.call_count == 1
    assert adapter.session.get.call_count == 1
    sent = adapter.session.post.call_args.kwargs.get("data") or {}
    assert sent.get("search[value]") == "435 ELSIE AVE"


def test_lookup_by_address_no_results(vcpa_config):
    adapter = _adapter_with_canned(
        vcpa_config, search_payload={"data": [], "recordsTotal": "0"}
    )
    result = adapter.lookup_by_address("999 Nowhere Lane, Atlantis, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous_two_parcels(vcpa_config):
    """Same street prefix in two cities — adapter cannot pick, must surface."""
    payload = {
        "data": [
            {"altkey": "1111111", "parcel": "111", "owner": "A", "street": "435 ELSIE AVE HOLLY HILL", "pc": "0100"},
            {"altkey": "2222222", "parcel": "222", "owner": "B", "street": "435 ELSIE AVE DELAND", "pc": "0100"},
        ]
    }
    adapter = _adapter_with_canned(vcpa_config, search_payload=payload)
    result = adapter.lookup_by_address("435 Elsie Avenue")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidate" in result.notes.lower()


def test_lookup_by_address_two_parcels_one_exact_prefix(vcpa_config):
    payload = {
        "data": [
            {"altkey": "3470141", "parcel": "533705070110", "owner": "GUILD", "street": "435 ELSIE AVE HOLLY HILL", "pc": "0100"},
            {"altkey": "9999999", "parcel": "999", "owner": "X", "street": "4350 ELSIE AVE DELAND", "pc": "0100"},
        ]
    }
    adapter = _adapter_with_canned(vcpa_config, search_payload=payload)
    result = adapter.lookup_by_address("435 Elsie Avenue, Holly Hill, FL")
    assert result.status == "PA_SUCCESS"
    assert result.folio == "3470141"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_apn_no_match_in_rows(vcpa_config):
    adapter = _adapter_with_canned(vcpa_config)
    result = adapter.lookup_by_apn("000000000000")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_apn_http_500(vcpa_config):
    adapter = VolusiaVCPA(vcpa_config)
    adapter.session = MagicMock()
    adapter.session.post.return_value = _make_response(500, "boom")
    result = adapter.lookup_by_apn("533705070110")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_empty_input(vcpa_config):
    adapter = VolusiaVCPA(vcpa_config)
    result = adapter.lookup_by_apn("ABC---")
    assert result.status == "PA_FAILED"
    assert "empty/invalid APN" in result.notes


def test_summary_without_disclaimer_cookie_fields_returns_pa_failed(vcpa_config):
    """If the disclaimer shell is served (no parcel fields), fail loudly."""
    shell = "<html><body><h5>Parcel Summary for 3470141</h5><p>Disagree Agree</p></body></html>"
    adapter = _adapter_with_canned(vcpa_config, summary_html=shell)
    result = adapter.lookup_by_apn("533705070110")
    assert result.status == "PA_FAILED"
    assert "disclaimer" in result.notes.lower()


def test_owner_name_search_returns_preview_rows(vcpa_config):
    adapter = _adapter_with_canned(vcpa_config)
    out = adapter.lookup_by_owner_name("GUILD MARYKE")
    assert len(out) == 1  # two owner rows collapse to one parcel
    assert out[0].folio == "3470141"
    assert out[0].apn == "533705070110"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_fetch_property_appraiser_volusia_dispatch_safe():
    """fl_volusia may not yet be registered in county_property_appraiser_urls.json
    (shared-config snippet pending Wave-2 integration) — the dispatcher must
    return a result object either way, never raise."""
    result = fetch_property_appraiser(county_id="fl_volusia", apn="533705070110")
    assert result.status in ("PA_NO_RUNNER", "PA_SUCCESS", "PA_FAILED")
    if result.status != "PA_NO_RUNNER":
        assert result.fetched_at
