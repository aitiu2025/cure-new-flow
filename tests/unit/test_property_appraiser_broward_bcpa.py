"""Unit tests for the Broward BCPA Property Appraiser adapter.

Tests use mocked sessions — no live BCPA traffic. Live shape is captured in
/tmp/bcpa_probe.md (probed 2026-05-26) and reflected in the fixture JSON below.
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

from titlepro.property_appraiser import (  # noqa: E402
    PropertyAppraiserResult,
    SaleHistoryEntry,
    fetch_property_appraiser,
)
from titlepro.property_appraiser.counties.broward_bcpa import BrowardBCPA  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bcpa_config() -> Dict[str, Any]:
    return {
        "platform": "bcpa_http",
        "base_url": "https://web.bcpa.net/bcpaclient/",
        "warmup_url": "https://web.bcpa.net/bcpaclient/searchsub.aspx",
        "endpoints": {
            "autocomplete_address": "https://web.bcpa.net/bcpaclient/search.aspx/GetAutoCompleteDataBySiteAddress",
            "search_by_address": "https://web.bcpa.net/bcpaclient/search.aspx/GetDataBySiteAddress",
            "parcel_info": "https://web.bcpa.net/bcpaclient/search.aspx/getParcelInformationData",
        },
        "captcha": False,
        "tax_year": "2025",
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


# BCPA-shape canned responses captured from the probe (slimmed).

ANAND_AUTOCOMPLETE = {"d": ["2856 NE 27 ST, FORT LAUDERDALE"]}
ANAND_ADDR_SEARCH = {
    "d": [
        {
            "folioNumber": "494225040800",
            "ownerName1": "ANAND,RISHI & PAYAL",
            "ownerName2": "",
            "siteAddress1": "2856 NE 27 ST",
            "siteAddress2": "FORT LAUDERDALE, FL 33306",
        },
        {"folioNumber": "1", "ownerName1": "", "siteAddress1": ""},  # sentinel
    ]
}
ANAND_PARCEL = {
    "d": [
        {
            "folioNumber": "494225040800",
            "ownerName1": "ANAND,RISHI & PAYAL",
            "ownerName2": "",
            "mailingAddress1": "2856 NE 27 ST",
            "mailingAddress2": "FORT LAUDERDALE, FL 33306",
            "legal": "CORAL RIDGE GALT ADD NO 1 31-37 B LOT 8 BLK 38",
            "justValue": "$3,925,750",
            "assessedLastYearValue": "$48,722.21",
            "he1Amount": "$25,000",
            "homesteadFlag": ", N",
            "actualAge": "2008",
            "bldgUnderAirFootage": "5975",
            # Sale history newest-first
            "saleDate1": "01/17/2012",
            "deedType1": "Special Warranty Deed",
            "bookAndPageOrCin1": "48462 / 1410",
            "saleVerification1": "Disqualified Sale",
            "saleDate2": "03/16/2011",
            "deedType2": "Certificate of Title",
            "bookAndPageOrCin2": "47826 / 836",
            "saleVerification2": "Disqualified Sale",
            "saleDate3": "12/30/2003",
            "deedType3": "Warranty Deed",
            "bookAndPageOrCin3": "36701 / 1744",
            "saleVerification3": "",
            "saleDate4": "",
            "deedType4": "",
            "bookAndPageOrCin4": "",
            "saleVerification4": "",
            "saleDate5": "",
            "deedType5": "",
            "bookAndPageOrCin5": "",
            "saleVerification5": "",
        }
    ]
}

SIMMONS_PARCEL = {
    "d": [
        {
            "folioNumber": "514108031810",
            "ownerName1": "BARKER,SHANTELL",
            "mailingAddress1": "2151 NW 93 AVE",
            "mailingAddress2": "PEMBROKE PINES, FL 33024-3137",
            "legal": "RAINBOW LAKES 77-28 B LOT 17 BLK 6",
            "justValue": "$612,510",
            "homesteadFlag": ", N",
            "saleDate1": "10/03/2014",
            "deedType1": "Warranty Deed",
            "bookAndPageOrCin1": "112573689",
            "saleVerification1": "Qualified Sale",
            "saleDate2": "07/07/2014",
            "deedType2": "Warranty Deed",
            "bookAndPageOrCin2": "112404453",
            "saleVerification2": "Excluded Sale",
            "saleDate3": "02/03/2006",
            "deedType3": "Warranty Deed",
            "bookAndPageOrCin3": "41813 / 1427",
            "saleVerification3": "",
        }
    ]
}


# ---------------------------------------------------------------------------
# Address normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("2856 NE 27TH ST, FORT LAUDERDALE, FL 33306", "2856 NE 27 ST"),
        ("2151 NW 93rd Ave, Pembroke Pines, FL", "2151 NW 93 AVE"),
        ("100 1ST STREET", "100 1 STREET"),
        ("  5 NW  2nd  Ave  ", "5 NW 2 AVE"),
    ],
)
def test_normalize_address_strips_suffixes_and_city(input_addr, expected):
    assert BrowardBCPA._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("49-42-25-04-0800", "494225040800"),
        ("494225040800", "494225040800"),
        ("5141-08-03-1810", "514108031810"),
        ("  514108-03-1810  ", "514108031810"),
        ("", ""),
    ],
)
def test_normalize_apn(input_apn, expected):
    assert BrowardBCPA._normalize_apn(input_apn) == expected


# ---------------------------------------------------------------------------
# Parse parcel — happy path
# ---------------------------------------------------------------------------


def test_lookup_by_apn_anand_parses_parcel_with_sale_history(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")  # warmup
    adapter.session.post.return_value = _make_response(200, ANAND_PARCEL)

    result = adapter.lookup_by_apn("49-42-25-04-0800")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "494225040800"
    assert result.folio == "494225040800"
    assert "ANAND" in result.owner_of_record
    assert "CORAL RIDGE" in result.legal_description
    assert result.just_value == 3_925_750
    assert result.year_built == 2008
    assert result.living_area_sqft == 5975
    assert result.source_url.endswith("=494225040800")
    # Sale history: 3 entries present (4/5 blank), newest-first.
    assert len(result.sale_history) == 3
    s1, s2, s3 = result.sale_history
    assert s1.sale_date == "01/17/2012"
    assert s1.deed_book_page == "48462 / 1410"
    assert s1.deed_doc_number == ""
    assert s1.deed_type == "Special Warranty Deed"
    # The MISSING-from-0522 prior owner deed (Regent Bank acquisition):
    assert s2.sale_date == "03/16/2011"
    assert s2.deed_type == "Certificate of Title"
    assert s2.deed_book_page == "47826 / 836"


def test_lookup_by_apn_simmons_parses_simmons_priors(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.return_value = _make_response(200, SIMMONS_PARCEL)

    result = adapter.lookup_by_apn("5141-08-03-1810")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "514108031810"
    assert result.owner_of_record == "BARKER,SHANTELL"
    assert len(result.sale_history) == 3
    s1, s2, _ = result.sale_history
    # Modern Broward — instrument numbers, no '/' delimiter, so deed_doc_number used.
    assert s1.deed_doc_number == "112573689"
    assert s1.deed_book_page == ""
    # The MISSING-from-0522 prior (Sai Chhaya acquisition):
    assert s2.deed_doc_number == "112404453"
    assert s2.sale_date == "07/07/2014"


def test_deed_identifiers_returns_mix_of_cin_and_bookpage(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.return_value = _make_response(200, SIMMONS_PARCEL)

    result = adapter.lookup_by_apn("514108031810")
    ids = result.deed_identifiers()
    assert ids[0] == "112573689"        # CIN
    assert ids[1] == "112404453"        # CIN
    assert "41813" in ids[2]            # book/page form, whitespace-stripped


# ---------------------------------------------------------------------------
# Address lookup — orchestrates autocomplete + search + parcel
# ---------------------------------------------------------------------------


def test_lookup_by_address_anand_full_three_call_flow(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.side_effect = [
        _make_response(200, ANAND_AUTOCOMPLETE),
        _make_response(200, ANAND_ADDR_SEARCH),
        _make_response(200, ANAND_PARCEL),
    ]

    result = adapter.lookup_by_address("2856 NE 27TH ST, FORT LAUDERDALE, FL 33306")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "494225040800"
    assert adapter.session.post.call_count == 3
    # Confirm we hit the three expected endpoints in order.
    posted_urls = [c.args[0] for c in adapter.session.post.call_args_list]
    assert posted_urls[0].endswith("GetAutoCompleteDataBySiteAddress")
    assert posted_urls[1].endswith("GetDataBySiteAddress")
    assert posted_urls[2].endswith("getParcelInformationData")


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_address_no_results_returns_pa_no_results(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.side_effect = [
        _make_response(200, {"d": []}),                                 # autocomplete miss
        _make_response(200, {"d": [{"folioNumber": "1"}]}),             # only sentinel
    ]
    result = adapter.lookup_by_address("999 NOWHERE LN, ATLANTIS, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_apn_500_returns_pa_failed(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.return_value = _make_response(500, {"Message": "boom"})
    result = adapter.lookup_by_apn("494225040800")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_empty_input_returns_pa_failed(bcpa_config):
    adapter = BrowardBCPA(bcpa_config)
    result = adapter.lookup_by_apn("ABC---")
    assert result.status == "PA_FAILED"
    assert "empty/invalid APN" in result.notes


def test_lookup_by_address_ambiguous_returns_pa_ambiguous(bcpa_config):
    """Two candidates, neither an exact siteAddress1 match against canonical."""
    adapter = BrowardBCPA(bcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "")
    adapter.session.post.side_effect = [
        _make_response(200, {"d": ["100 MAIN AVE, CITY-A", "100 MAIN ST, CITY-B"]}),
        _make_response(
            200,
            {
                "d": [
                    # canonical from autocomplete is "100 MAIN AVE" — neither siteAddress1
                    # is exactly that, so no exact match → ambiguous.
                    {"folioNumber": "111", "siteAddress1": "100 MAIN PLAZA"},
                    {"folioNumber": "222", "siteAddress1": "100 MAIN ROAD"},
                    {"folioNumber": "1"},
                ]
            },
        ),
    ]
    result = adapter.lookup_by_address("100 MAIN STREET")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


# ---------------------------------------------------------------------------
# Dispatcher / factory
# ---------------------------------------------------------------------------


def test_fetch_property_appraiser_no_inputs_returns_pa_failed():
    result = fetch_property_appraiser(county_id="fl_broward")
    assert result.status == "PA_FAILED"
    assert "at least one" in result.notes.lower()


def test_fetch_property_appraiser_unknown_county_returns_pa_no_runner():
    result = fetch_property_appraiser(county_id="zz_mars", apn="123")
    assert result.status == "PA_NO_RUNNER"


def test_propertyappraiserresult_to_dict_roundtrip():
    r = PropertyAppraiserResult(
        apn="494225040800",
        folio="494225040800",
        owner_of_record="ANAND,RISHI & PAYAL",
        sale_history=[SaleHistoryEntry(sale_date="01/17/2012", deed_book_page="48462 / 1410")],
        status="PA_SUCCESS",
    )
    d = r.to_dict()
    assert d["apn"] == "494225040800"
    assert d["sale_history"][0]["deed_book_page"] == "48462 / 1410"
