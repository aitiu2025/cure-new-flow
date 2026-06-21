"""Unit tests for the Lee County (FL) LeePA Property Appraiser adapter.

Tests use mocked sessions — no live LeePA traffic. The HTML fixtures below are
trimmed from the live 2026-06-10 OSTIGUY probe (FolioID 10176930, STRAP
29-44-24-C2-00101.0150). See the case folder phase0_probe_pa.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser import (  # noqa: E402
    fetch_property_appraiser,
)
from titlepro.property_appraiser.counties.lee_leepa import LeeLeePA  # noqa: E402


# ---------------------------------------------------------------------------
# Live-shape fixtures (trimmed from the OSTIGUY probe)
# ---------------------------------------------------------------------------

SEARCH_TOKENS_PAGE = (
    '<input type="hidden" id="__VIEWSTATE" value="VS123" />'
    '<input type="hidden" id="__VIEWSTATEGENERATOR" value="GEN1" />'
    '<input type="hidden" id="__EVENTVALIDATION" value="EV1" />'
)

SEARCH_RESULTS_ONE = """
<td class="boxRight boxTop boxBottom">
  <div class="parentContainer">
    <div class="item">29-44-24-C2-00101.0150</div>
    <div class="item">10176930</div>
  </div>
</td>
<td class="boxLeft boxTop boxBottom boxRight">
  <div class="bold">OSTIGUY STEVEN R & </div>
  <div class="bold">OSTIGUY CHRISTINA J</div>
  <div>2137 CORAL POINT DR</div>
  <div></div>
  <div>CAPE CORAL FL 33990</div>
</td>
"""

SEARCH_RESULTS_TWO = """
<div class="item">11-11-11-A1-00001.0010</div>
<div class="item">20000001</div>
<div class="bold">SMITH JOHN</div><div>100 MAIN ST</div><div>CAPE CORAL FL 33990</div>
<div class="item">22-22-22-B2-00002.0020</div>
<div class="item">20000002</div>
<div class="bold">SMITH JANE</div><div>200 MAIN ST</div><div>CAPE CORAL FL 33990</div>
"""

SEARCH_RESULTS_NONE = "<div>No matching records were found.</div>"

PARCEL_NAL_HTML = (
    "<div>Record Created: 10/4/2025<br/><br/>"
    "F01:  46<br/>F02:  294424C2001010150<br/>F03:  R<br/>F04:  2025<br/>"
    "F08:  372167<br/>F11:  241219<br/>F12:  241219<br/>F13:  216219<br/>"
    "F14:  190497<br/>F15:  372167<br/>F44:  2005<br/>F45:  2004<br/>"
    "F46:  1019<br/>F47:  3128<br/>F51:  OSTIGUY STEVEN R & <br/>"
    "F52:  2137 CORAL POINT DR<br/>F54:  CAPE CORAL<br/>F55:  FL<br/>"
    "F56:  33990<br/>F65:  SHOREHAVEN ESTATES UNIT 1<br/>"
    "F79:  2137 CORAL POINT DR<br/>F81:  CAPE CORAL<br/>F82:  33990<br/>"
    "F90:  01;25000;02;25722<br/>F92:  161755</div>"
    '<div class="box" id="SalesDetails">'
    "Images for this record are not viewable by the general public."
    "</div>"
)

PARCEL_WITH_SALES_HTML = (
    "<div>F01:  46<br/>F02:  111111A100001.0010<br/>F08:  300000<br/>F11:  250000<br/>"
    "F44:  1998<br/>F51:  DOE JOHN<br/>F52:  9 OAK ST<br/>F54:  CAPE CORAL<br/>"
    "F55:  FL<br/>F56:  33990<br/>F65:  SOME SUBDIVISION<br/>F79:  9 OAK ST<br/>"
    "F81:  CAPE CORAL<br/>F82:  33990<br/>F90:  <br/>F92:  1</div>"
    '<div class="box" id="SalesDetails"><table>'
    "<tr><td>03/15/2015</td><td>$285,000</td><td>2015000123456</td><td>DOE JOHN</td></tr>"
    "<tr><td>06/01/2004</td><td>$120,000</td><td>2004000098765</td><td>ROE JANE</td></tr>"
    "</table></div>"
)


def _resp(status_code: int, text: str):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


@pytest.fixture
def cfg() -> dict:
    return {
        "platform": "leepa_http",
        "endpoints": {
            "property_search": "https://www.leepa.org/Search/PropertySearch.aspx",
            "parcel_display": "https://www.leepa.org/Display/DisplayParcel.aspx",
        },
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2137 Coral Point Drive, Cape Coral, FL 33990", "2137 CORAL POINT DR"),
        ("100 Main Street", "100 MAIN ST"),
        ("55 NW 3rd Avenue", "55 NW 3 AVE"),
        ("9 Oak Boulevard, Fort Myers", "9 OAK BLVD"),
        ("2137 CORAL POINT DR", "2137 CORAL POINT DR"),
    ],
)
def test_normalize_address(raw, expected):
    assert LeeLeePA._normalize_address_for_search(raw) == expected


def test_strap_from_model_rehyphenates():
    assert LeeLeePA._strap_from_model("294424C2001010150") == "29-44-24-C2-00101.0150"
    assert LeeLeePA._strap_from_model("ABC") == "ABC"


@pytest.mark.parametrize(
    "f90,amount",
    [
        ("01;25000;02;25722", 25000),
        ("02;25722", 0),
        ("", 0),
        ("01;50000", 50000),
    ],
)
def test_homestead_amount(f90, amount):
    assert LeeLeePA._homestead_amount(f90) == amount


def test_is_folio():
    assert LeeLeePA._is_folio("10176930")
    assert not LeeLeePA._is_folio("29-44-24-C2-00101.0150")
    assert not LeeLeePA._is_folio("")


def test_parse_nal_model_extracts_fields():
    model = LeeLeePA._parse_nal_model(PARCEL_NAL_HTML)
    assert model["F02"] == "294424C2001010150"
    assert model["F08"] == "372167"
    assert model["F51"] == "OSTIGUY STEVEN R &"
    assert model["F65"] == "SHOREHAVEN ESTATES UNIT 1"
    assert model["F90"] == "01;25000;02;25722"


def test_parse_search_results_one_row():
    rows = LeeLeePA._parse_search_results(SEARCH_RESULTS_ONE)
    assert len(rows) == 1
    assert rows[0]["strap"] == "29-44-24-C2-00101.0150"
    assert rows[0]["folio"] == "10176930"
    assert rows[0]["owners"][0] == "OSTIGUY STEVEN R"
    assert "OSTIGUY CHRISTINA J" in rows[0]["owners"]


def test_lookup_by_apn_parses_ostiguy_parcel(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, PARCEL_NAL_HTML)

    result = adapter.lookup_by_apn("10176930")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "10176930"
    assert result.apn == "29-44-24-C2-00101.0150"
    assert result.owner_of_record == "OSTIGUY STEVEN R"
    assert result.legal_description == "SHOREHAVEN ESTATES UNIT 1"
    assert result.just_value == 372167
    assert result.assessed_value == 241219
    assert result.homestead_active is True
    assert result.homestead_amount == 25000
    assert result.year_built == 2005
    assert result.living_area_sqft == 3128
    assert result.situs_address == "2137 CORAL POINT DR, CAPE CORAL 33990"
    assert "2137 CORAL POINT DR" in result.mailing_address
    assert result.sale_history == []
    assert "not viewable" in result.notes


def test_lookup_by_apn_with_public_sales(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, PARCEL_WITH_SALES_HTML)

    result = adapter.lookup_by_apn("20000099")
    assert result.status == "PA_SUCCESS"
    assert len(result.sale_history) == 2
    s1, s2 = result.sale_history
    assert s1.sale_date == "03/15/2015"
    assert s1.sale_price == 285000
    assert s1.deed_doc_number == "2015000123456"
    assert s2.sale_date == "06/01/2004"


def test_lookup_by_apn_empty_input(cfg):
    adapter = LeeLeePA(cfg)
    result = adapter.lookup_by_apn("   ")
    assert result.status == "PA_FAILED"


def test_lookup_by_apn_http_error(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(500, "boom")
    result = adapter.lookup_by_apn("10176930")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_no_model(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, "<div>nothing here</div>")
    result = adapter.lookup_by_apn("10176930")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_full_flow(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _resp(200, SEARCH_TOKENS_PAGE),
        _resp(200, PARCEL_NAL_HTML),
    ]
    adapter.session.post.return_value = _resp(200, SEARCH_RESULTS_ONE)

    result = adapter.lookup_by_address("2137 Coral Point Drive, Cape Coral, FL 33990")
    assert result.status == "PA_SUCCESS"
    assert result.folio == "10176930"
    assert result.owner_of_record == "OSTIGUY STEVEN R"
    assert "OSTIGUY CHRISTINA J" in result.co_owners
    posted = adapter.session.post.call_args.kwargs["data"]
    assert posted["__EVENTTARGET"].endswith("SubmitPropertySearch")
    assert posted["ctl00$BodyContentPlaceHolder$WebTab1$tmpl0$AddressTextBox"] == "2137 CORAL POINT DR"


def test_lookup_by_address_no_results(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, SEARCH_TOKENS_PAGE)
    adapter.session.post.return_value = _resp(200, SEARCH_RESULTS_NONE)
    result = adapter.lookup_by_address("999 Nowhere Ln, Cape Coral, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, SEARCH_TOKENS_PAGE)
    adapter.session.post.return_value = _resp(200, SEARCH_RESULTS_TWO)
    result = adapter.lookup_by_address("Main St, Cape Coral, FL")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


def test_fetch_property_appraiser_unknown_county_no_runner():
    result = fetch_property_appraiser(county_id="zz_mars", apn="123")
    assert result.status == "PA_NO_RUNNER"


def test_lookup_by_owner_name_returns_empty(cfg):
    adapter = LeeLeePA(cfg)
    assert adapter.lookup_by_owner_name("OSTIGUY") == []


def test_result_to_dict_roundtrip(cfg):
    adapter = LeeLeePA(cfg)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _resp(200, PARCEL_NAL_HTML)
    result = adapter.lookup_by_apn("10176930")
    d = result.to_dict()
    assert d["folio"] == "10176930"
    assert d["just_value"] == 372167
    assert isinstance(d["sale_history"], list)
