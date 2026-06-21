"""Unit tests for the Manatee MCPAO Property Appraiser adapter.

Tests use mocked sessions — no live MCPAO traffic. The fixture payloads
mirror the live shapes captured during the 2026-05-27 probe (see
``/tmp/manateepao_probe.md``) — FERNANDEZ subject PARID 1697719559.
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
from titlepro.property_appraiser.counties.manatee_pao import ManateePAO  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcpao_config() -> Dict[str, Any]:
    return {
        "platform": "manatee_pao",
        "base_url": "https://www.manateepao.gov/",
        "warmup_url": "https://www.manateepao.gov/search/",
        "parcel_referer_tmpl": "https://www.manateepao.gov/prg/parcel/?parid={parid}",
        "endpoints": {
            "search_results": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-parcel-search-results.php",
            "owner": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-owner.php",
            "sales": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-sales.php",
            "addresses": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-addresses.php",
            "value_history": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-value-history.php",
            "exemptions": "https://www.manateepao.gov/wp-content/themes/frontier-child/models/pao-model-exemptions.php",
        },
        "captcha": False,
    }


def _make_response(status_code: int, payload: Any, content_type: str = "application/json"):
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(payload, (dict, list)):
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = str(payload) if payload is not None else ""
    resp.headers = {"content-type": content_type}
    return resp


# --- FERNANDEZ live-shape fixtures ----------------------------------------

# Owner HTML — stacked label/value layout per pao-model-owner.php live capture.
FERNANDEZ_OWNER_HTML = """
<div>
Parcel ID:
1697719559
Ownership:
FERNANDEZ, PABLO;  ROZANES, DANIELA
Owner Type:
HUSBAND OR WIFE & MARRIED CP DIFF NAMES;  SPOUSE & MARRIED CP DIFF NAMES
Mailing Address:
FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR, BRADENTON FL 34203-3144
Situs Address:
4837 SABAL HARBOUR DR, BRADENTON, FL 34203-3144
Go to Situs Address details on www.google.com in a new tab
Jurisdiction:
UNINCORPORATED MANATEE COUNTY
Tax District:
0303;  SOUTHERN MANATEE FIRE & RESCUE DISTRICT
Sec/Twp/Rge:
09-35S-18E
Neighborhood:
4275;  SABAL HARBOUR
Subdivision:
1697704;  SABAL HARBOUR PHASE V;  LOT 141;
PB 35/56
Short Description:
LOT 141 SABAL HARBOUR PHASE V PI#16977.1955/9
FEMA Value:
$405,789 as of January 1, 2025
Land Use:
0100;  SINGLE FAMILY RESIDENTIAL
Land Size:
0.1752 Acres or 7,632 Square Feet
Building Area:
2,381 SqFt Under Roof / 1,873 SqFt Living or Business Area
Living Units:
1
</div>
"""

FERNANDEZ_SALES = {
    "cols": [
        {"title": "Sale Date", "type": "date"},
        {"title": "BOOK", "type": "text"},
        {"title": "PAGE", "type": "text"},
        {"title": "Instrument Type", "type": "text"},
        {"title": "Vacant / Improved", "type": "text"},
        {"title": "Qualification Code", "type": "text"},
        {"title": "Sale Price", "type": "num"},
        {"title": "Grantee", "type": "text"},
        {"title": "qual_desc", "type": "text"},
        {"title": "instr_desc", "type": "text"},
        {"title": "InstrNo", "type": "text"},
    ],
    "rows": [
        ["2018-02-28 00:00:00", "2716", "2565", "WD", "I", "01", "272000",
         "FERNANDEZ, PABLO", "Qualified arms length transfer",
         "WARRANTY DEED", "201841020434"],
        ["2002-10-31 00:00:00", "1781", "4691", "WD", "I", "01", "187000",
         "TOIVANEN, REIJO", "Qualified arms length transfer",
         "WARRANTY DEED", ""],
        ["2000-11-15 00:00:00", "1657", "4044", "SW", "I", "01", "149000",
         "CIRRITO, ANGELA L", "Qualified arms length transfer",
         "SPECIAL WARRANTY DEED", ""],
    ],
}

FERNANDEZ_ADDRESSES = {
    "cols": [{"title": "situs_address", "type": "text"}],
    "rows": [["4837 SABAL HARBOUR DR, BRADENTON, FL 34203-3144"]],
}

FERNANDEZ_VALUE_HISTORY = {
    "cols": [
        {"title": "January&nbsp;1 Tax Year", "type": "num"},
        {"title": "Homestead Exemption", "type": "text"},
        {"title": "Land Value", "type": "num"},
        {"title": "Improvements Value", "type": "num"},
        {"title": "Just/Market Value", "type": "num"},
        {"title": "Non-School Assessed Value", "type": "num"},
        {"title": "School Assessed Value", "type": "num"},
        {"title": "County Taxable Value", "type": "num"},
        {"title": "School Taxable Value", "type": "num"},
        {"title": "Municipality Taxable Value", "type": "num"},
        {"title": "Ind. Spc. Dist Taxable Value", "type": "num"},
        {"title": "Ad Valorem Taxes", "type": "num"},
        {"title": "Non-Ad Valorem Taxes", "type": "num"},
    ],
    "rows": [
        ["2025", "Yes", "48450", "364735", "413185", "263099", "263099",
         "212377", "238099", None, "212377", "3245.05", "321.24"],
        ["2024", "Yes", "48450", "370234", "418684", "255684", "255684",
         "205684", "230684", None, "205684", "3155.75", "298.83"],
    ],
}

FERNANDEZ_EXEMPTIONS = {
    "cols": [
        {"title": "taxyr", "type": "num"},
        {"title": "Description", "type": "text"},
        {"title": "type", "type": "text"},
        {"title": "yrbeg", "type": "text"},
        {"title": "cty", "type": "text"},
        {"title": "sch", "type": "text"},
        {"title": "isd", "type": "text"},
        {"title": "mun", "type": "text"},
    ],
    "rows": [
        ["2026", "1010 HOMESTEAD", "PERSONAL", "2019",
         "25,000", "25,000", "25,000", "0"],
        ["2026", "1110 ADDITIONAL HOMESTEAD", "PERSONAL", "2019",
         "26,411", "0", "26,411", "0"],
    ],
}

FERNANDEZ_SEARCH_RESULT = {
    "cols": [
        {"title": "Parcel ID"}, {"title": "Property Type"},
        {"title": "Owner(s)"}, {"title": "Situs Address"},
        {"title": "Postal City"},
    ],
    "rows": [
        ["1697719559", "REAL PROPERTY",
         ";FERNANDEZ, PABLO;ROZANES, DANIELA;",
         ";4837 SABAL HARBOUR DR;", "BRADENTON"],
    ],
}


def _wire_apn_responses(adapter: ManateePAO,
                        owner_html: str = FERNANDEZ_OWNER_HTML,
                        sales: dict = FERNANDEZ_SALES,
                        addresses: dict = FERNANDEZ_ADDRESSES,
                        value_history: dict = FERNANDEZ_VALUE_HISTORY,
                        exemptions: dict = FERNANDEZ_EXEMPTIONS) -> None:
    """Helper to wire a MagicMock session for the 5-call apn flow.

    The adapter's lookup_by_apn does NOT invoke warm-up (only search-by-address
    does); the order of GETs is: sales -> addresses -> value_history -> exemptions.
    """
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, sales),                          # GET sales
        _make_response(200, addresses),                      # GET addresses
        _make_response(200, value_history),                  # GET value-history
        _make_response(200, exemptions),                     # GET exemptions
    ]
    adapter.session.post.return_value = _make_response(200, owner_html, "text/html")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("1697719559", "1697719559"),
        ("169-77-19-559", "1697719559"),
        ("  1697-7195-59 ", "1697719559"),
        ("", ""),
        ("abc", ""),
    ],
)
def test_normalize_apn(input_apn, expected):
    assert ManateePAO._normalize_apn(input_apn) == expected


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("4837 SABAL HARBOUR DR, BRADENTON, FL 34203", "4837 SABAL HARBOUR DR"),
        ("4837 Sabal Harbour Dr", "4837 SABAL HARBOUR DR"),
        ("100 1st St", "100 1 ST"),
        ("  77  NE  2ND  AVE  ", "77 NE 2 AVE"),
    ],
)
def test_normalize_address_for_search(input_addr, expected):
    assert ManateePAO._normalize_address_for_search(input_addr) == expected


# ---------------------------------------------------------------------------
# lookup_by_apn — happy path against FERNANDEZ live fixtures
# ---------------------------------------------------------------------------


def test_lookup_by_apn_fernandez_full_six_call_flow(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    _wire_apn_responses(adapter)

    result = adapter.lookup_by_apn("1697719559")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "1697719559"
    assert result.folio == "1697719559"
    assert result.owner_of_record == "FERNANDEZ, PABLO"
    assert "ROZANES, DANIELA" in result.co_owners
    assert "4837 SABAL HARBOUR DR" in result.situs_address
    assert "BRADENTON" in result.situs_address
    assert "FERNANDEZ" in result.mailing_address
    assert "LOT 141" in result.legal_description
    assert "SABAL HARBOUR" in result.legal_description
    assert result.just_value == 413_185
    assert result.assessed_value == 263_099
    assert result.homestead_active is True
    assert result.living_area_sqft == 1873
    assert result.source_url.endswith("=1697719559")

    # Confirm session traffic
    assert adapter.session.post.call_count == 1   # owner POST
    assert adapter.session.get.call_count == 4    # 4 data GETs (no warm-up on apn path)


def test_lookup_by_apn_returns_full_sale_history_newest_first(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    _wire_apn_responses(adapter)

    result = adapter.lookup_by_apn("1697719559")

    assert len(result.sale_history) == 3
    s_2018, s_2002, s_2000 = result.sale_history

    # 2018 vesting deed — recorded with both Book/Page AND instrument number
    assert s_2018.sale_date == "02/28/2018"
    assert s_2018.deed_book_page == "2716 / 2565"
    assert s_2018.deed_doc_number == "201841020434"
    assert s_2018.deed_type == "Warranty Deed"
    assert s_2018.sale_price == 272_000
    assert s_2018.qualified is True

    # 2002 + 2000 priors — Book/Page only (older deeds had no CIN)
    assert s_2002.sale_date == "10/31/2002"
    assert s_2002.deed_book_page == "1781 / 4691"
    assert s_2002.deed_doc_number == ""
    assert s_2002.deed_type == "Warranty Deed"

    assert s_2000.sale_date == "11/15/2000"
    assert s_2000.deed_book_page == "1657 / 4044"
    assert s_2000.deed_type == "Special Warranty Deed"
    assert s_2000.sale_price == 149_000


def test_deed_identifiers_mix_of_cin_and_bookpage(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    _wire_apn_responses(adapter)
    result = adapter.lookup_by_apn("1697719559")

    ids = result.deed_identifiers()
    # 2018 has instr no, 2002/2000 use book/page (whitespace-stripped).
    assert ids[0] == "201841020434"
    assert "1781" in ids[1] and "4691" in ids[1]
    assert "1657" in ids[2] and "4044" in ids[2]


# ---------------------------------------------------------------------------
# lookup_by_address — orchestrates search → lookup_by_apn
# ---------------------------------------------------------------------------


def test_lookup_by_address_fernandez_full_flow(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    adapter.session = MagicMock()
    # The address path calls warm-up first (via _post_search -> _warm), then
    # 4 data GETs from lookup_by_apn.
    adapter.session.get.side_effect = [
        _make_response(200, "", "text/html"),                # warm-up GET
        _make_response(200, FERNANDEZ_SALES),                # GET sales
        _make_response(200, FERNANDEZ_ADDRESSES),            # GET addresses
        _make_response(200, FERNANDEZ_VALUE_HISTORY),        # GET value-history
        _make_response(200, FERNANDEZ_EXEMPTIONS),           # GET exemptions
    ]
    adapter.session.post.side_effect = [
        _make_response(200, FERNANDEZ_SEARCH_RESULT),        # search POST
        _make_response(200, FERNANDEZ_OWNER_HTML, "text/html"),  # owner POST
    ]

    result = adapter.lookup_by_address("4837 SABAL HARBOUR DR, BRADENTON, FL 34203")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "1697719559"
    assert adapter.session.post.call_count == 2


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_apn_empty_input_returns_pa_failed(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    result = adapter.lookup_by_apn("xyz---")
    assert result.status == "PA_FAILED"
    assert "empty/invalid PARID" in result.notes


def test_lookup_by_apn_500_returns_pa_failed(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "", "text/html")
    adapter.session.post.return_value = _make_response(500, "boom", "text/html")
    result = adapter.lookup_by_apn("1697719559")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_empty_owner_html_returns_no_results(mcpao_config):
    """MCPAO returns 200 + empty body for unknown parids."""
    adapter = ManateePAO(mcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, "", "text/html"),
        _make_response(200, {"cols": [], "rows": []}),
        _make_response(200, {"cols": [], "rows": []}),
        _make_response(200, {"cols": [], "rows": []}),
        _make_response(200, {"cols": [], "rows": []}),
    ]
    adapter.session.post.return_value = _make_response(200, "", "text/html")
    result = adapter.lookup_by_apn("9999999999")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_no_results(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "", "text/html")
    adapter.session.post.return_value = _make_response(200, {"cols": [], "rows": []})
    result = adapter.lookup_by_address("999 NOWHERE LN, NOWHERE, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous(mcpao_config):
    adapter = ManateePAO(mcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "", "text/html")
    adapter.session.post.return_value = _make_response(
        200,
        {
            "cols": [{"title": "Parcel ID"}, {"title": "Property Type"},
                     {"title": "Owner(s)"}, {"title": "Situs Address"},
                     {"title": "Postal City"}],
            "rows": [
                ["111", "REAL PROPERTY", ";A;", ";100 ELSEWHERE DR;", "X"],
                ["222", "REAL PROPERTY", ";B;", ";100 ALSO-ELSEWHERE DR;", "Y"],
            ],
        },
    )
    result = adapter.lookup_by_address("100 NOPE")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def test_fetch_property_appraiser_unknown_county_returns_no_runner():
    result = fetch_property_appraiser(county_id="zz_mars", apn="123")
    assert result.status == "PA_NO_RUNNER"


def test_propertyappraiserresult_to_dict_roundtrip_with_manatee_sale():
    r = PropertyAppraiserResult(
        apn="1697719559",
        folio="1697719559",
        owner_of_record="FERNANDEZ, PABLO",
        co_owners=["ROZANES, DANIELA"],
        sale_history=[
            SaleHistoryEntry(
                sale_date="02/28/2018",
                deed_book_page="2716 / 2565",
                deed_doc_number="201841020434",
                deed_type="Warranty Deed",
                sale_price=272_000,
                qualified=True,
            )
        ],
        status="PA_SUCCESS",
    )
    d = r.to_dict()
    assert d["apn"] == "1697719559"
    assert d["sale_history"][0]["deed_doc_number"] == "201841020434"
    assert d["co_owners"] == ["ROZANES, DANIELA"]
