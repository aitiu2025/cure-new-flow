"""Unit tests for the Duval County PAO Property Appraiser adapter.

Fixtures mirror the LIVE Duval PAO structure captured 2026-06-10 (Wave 2,
SKINNER, RE# 167730-6710 / 4409 CROOKED BROOK CT). Layout verified against
live_captures/pa_detail_RE_1677306710.html + pa_search_page.html +
pa_address_search_response.html:
  - owners in an ASP.NET repeater (spans id ...repeaterOwnerInformation...lblOwnerName)
  - situs in a 'Building 1 Site Address' cell
  - legal in an 'LN | Legal Description' table (header field is a placeholder)
  - sales table renders deed as 'WD - Warranty Deed'
  - address search posts street number/name/suffix to Results.aspx (cross-page)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser.counties.duval_pao import DuvalPAO  # noqa: E402


@pytest.fixture
def pao_config() -> Dict[str, Any]:
    return {
        "platform": "duval_pao",
        "base_url": "https://paopropertysearch.coj.net/",
        "endpoints": {
            "basic_search": "https://paopropertysearch.coj.net/Basic/Search.aspx",
            "basic_results": "https://paopropertysearch.coj.net/Basic/Results.aspx",
            "detail": "https://paopropertysearch.coj.net/Basic/Detail.aspx",
        },
        "captcha": False,
        "impersonate": "safari17_2_ios",
    }


def _resp(status_code: int, text: str):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


# --- Live-faithful detail fixture (compact, structurally identical) --------
SKINNER_DETAIL_HTML = """
<html><body>
<h2><span id="ctl00_cphBody_repeaterOwnerInformation_ctl00_lblOwnerName">SKINNER MICHAEL W</span></h2>
<h2><span id="ctl00_cphBody_repeaterOwnerInformation_ctl01_lblOwnerName">SKINNER SALLY JANE</span></h2>
<table><tr>
  <td><span id="ctl00_cphBody_lblHeaderPrimarySiteAddress">Primary Site Address</span></td>
  <td>167730-6710</td>
</tr></table>
<table><tr>
  <td><span id="ctl00_cphBody_lblHeaderLegalDescription">Legal Desc.</span></td>
  <td>For full legal description see Land &amp; Legal section below</td>
</tr></table>
<table>
  <tr><th>Value Description</th><th>2025 Certified</th><th>2026 In Progress</th></tr>
  <tr><td>Just (Market) Value</td><td>$417,764.00</td><td>$423,473.00</td></tr>
  <tr><td>Assessed Value</td><td>$260,224.00</td><td>$267,250.00</td></tr>
  <tr><td>Year Built</td><td>1998</td><td></td></tr>
</table>
<table>
  <tr><td>Homestead (HX)</td><td>- $25,000.00</td></tr>
</table>
<h3>Land &amp; Legal</h3>
<table>
  <tr><th>LN</th><th>Legal Description</th></tr>
  <tr><td>1</td><td>51-27    10-3S-28E              .180</td></tr>
  <tr><td>2</td><td>RIVERBROOK AT GLEN KERNAN UNIT 4</td></tr>
  <tr><td>3</td><td>LOT 325</td></tr>
</table>
<table>
  <tr><td>Building 1 Site Address</td><td>4409 CROOKED BROOK CT Unit</td></tr>
</table>
<table>
  <tr>
    <th>Book/Page</th><th>Sale Date</th><th>Sale Price</th>
    <th>Deed Instrument Type Code</th><th>Qualified/Unqualified</th><th>Vacant/Improved</th>
  </tr>
  <tr><td>15319-01154</td><td>7/15/2010</td><td>$224,000.00</td><td>WD - Warranty Deed</td><td>Qualified</td><td>Improved</td></tr>
  <tr><td>12667-00943</td><td>6/24/2005</td><td>$294,000.00</td><td>WD - Warranty Deed</td><td>Qualified</td><td>Improved</td></tr>
  <tr><td>00051-00027</td><td>4/29/1997</td><td>$100.00</td><td>PB - Plat Book</td><td>Unqualified</td><td>Vacant</td></tr>
</table>
</body></html>
"""

# --- Live-faithful search page (street fields + WebForms hidden state) -----
SEARCH_PAGE_HTML = """
<html><body>
<form name="aspnetForm" method="post" action="./Search.aspx">
<input type="hidden" name="__VIEWSTATE" value="dDuvalVS123" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="ABCD1234" />
<input type="hidden" name="__EVENTVALIDATION" value="dEV456" />
<input name="ctl00$cphBody$tbStreetNumber" type="text" id="ctl00_cphBody_tbStreetNumber" />
<input name="ctl00$cphBody$tbStreetName" type="text" id="ctl00_cphBody_tbStreetName" />
<select name="ctl00$cphBody$ddStreetSuffix" id="ctl00_cphBody_ddStreetSuffix">
  <option value="">- </option><option value="CT">Court</option>
</select>
<input type="submit" name="ctl00$cphBody$bSearch" value="Search" />
</form>
</body></html>
"""

RESULTS_HTML = """
<html><body>
<table>
  <tr><th>RE #</th><th>Owner</th><th>Address</th></tr>
  <tr>
    <td><a href="Detail.aspx?RE=1677306710">167730-6710</a></td>
    <td>SKINNER MICHAEL W</td><td>4409 CROOKED BROOK CT Jacksonville 32224-</td>
  </tr>
</table>
</body></html>
"""

RESULTS_NO_EXACT_HTML = """
<html><body>
<table>
  <tr><th>RE #</th><th>Owner</th><th>Address</th></tr>
  <tr><td><a href="Detail.aspx?RE=1110001111">111000-1111</a></td><td>A</td><td>100 SOMEWHERE ELSE RD</td></tr>
  <tr><td><a href="Detail.aspx?RE=1110001112">111000-1112</a></td><td>B</td><td>102 SOMEWHERE ELSE RD</td></tr>
</table>
</body></html>
"""

NO_RESULTS_DETAIL_HTML = """
<html><body><p>No information found for that RE number.</p></body></html>
"""


# --------------------------------------------------------- normalization


def test_normalize_apn_variants(pao_config):
    a = DuvalPAO(pao_config)
    assert a._normalize_apn("167730-6710") == "1677306710"
    assert a._normalize_apn("1677306710") == "1677306710"
    assert a._normalize_apn("167730 6710") == "1677306710"
    assert a._normalize_apn("12345") == ""
    assert a._normalize_apn("") == ""
    assert a._normalize_apn(None) == ""


def test_split_street(pao_config):
    a = DuvalPAO(pao_config)
    assert a._split_street("4409 Crooked Brook Court, Jacksonville, FL 32224") == (
        "4409", "CROOKED BROOK", "CT",
    )
    assert a._split_street("2856 NE 27TH ST, FORT LAUDERDALE")[0] == "2856"
    assert a._split_street("")[1] == ""


# --------------------------------------------------------- lookup_by_apn


def test_lookup_by_apn_happy_path(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, SKINNER_DETAIL_HTML)

    res = a.lookup_by_apn("167730-6710")

    assert res.status == "PA_SUCCESS"
    assert res.apn == "1677306710"
    assert res.owner_of_record == "SKINNER MICHAEL W"
    assert res.co_owners == ["SKINNER SALLY JANE"]
    assert res.situs_address == "4409 CROOKED BROOK CT"
    assert "RIVERBROOK AT GLEN KERNAN UNIT 4" in res.legal_description
    assert "LOT 325" in res.legal_description
    assert res.just_value == 417764
    assert res.assessed_value == 260224
    assert res.homestead_active is True
    assert res.homestead_amount == 25000
    assert res.year_built == 1998
    assert "Detail.aspx?RE=1677306710" in res.source_url
    _, kwargs = a.session.get.call_args
    assert kwargs["params"] == {"RE": "1677306710"}


def test_lookup_by_apn_sale_history(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, SKINNER_DETAIL_HTML)

    sales = a.lookup_by_apn("1677306710").sale_history
    assert len(sales) == 3
    # newest-first
    assert sales[0].sale_date == "7/15/2010"
    assert sales[-1].sale_date == "4/29/1997"
    # deed code split out of "WD - Warranty Deed"
    assert sales[0].deed_type == "WD"
    assert sales[0].notes == "Warranty Deed"
    assert sales[0].deed_book_page == "15319-01154"
    assert sales[0].sale_price == 224000
    assert sales[0].qualified is True
    assert sales[-1].deed_type == "PB"
    assert sales[-1].qualified is False


def test_lookup_by_apn_invalid_re_short_circuits(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    res = a.lookup_by_apn("12345")
    assert res.status == "PA_FAILED"
    assert "invalid Duval RE" in res.notes
    a.session.get.assert_not_called()


def test_lookup_by_apn_http_error(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(500, "boom")
    res = a.lookup_by_apn("1677306710")
    assert res.status == "PA_FAILED"
    assert "500" in res.notes


def test_lookup_by_apn_network_exception_fails_soft(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.side_effect = RuntimeError("connect timeout")
    res = a.lookup_by_apn("1677306710")
    assert res.status == "PA_FAILED"
    assert "connect timeout" in res.notes


def test_lookup_by_apn_no_results_page(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, NO_RESULTS_DETAIL_HTML)
    res = a.lookup_by_apn("1677306710")
    assert res.status == "PA_NO_RESULTS"


# --------------------------------------------------------- lookup_by_address


def test_lookup_by_address_happy_path(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.side_effect = [
        _resp(200, SEARCH_PAGE_HTML),     # GET Search.aspx (hidden harvest)
        _resp(200, SKINNER_DETAIL_HTML),  # GET Detail.aspx?RE=...
    ]
    a.session.post.return_value = _resp(200, RESULTS_HTML)

    res = a.lookup_by_address("4409 Crooked Brook Court, Jacksonville, FL 32224")

    assert res.status == "PA_SUCCESS"
    assert res.apn == "1677306710"
    assert res.owner_of_record == "SKINNER MICHAEL W"
    # POST went to Results.aspx with split street fields + WebForms hidden state
    args, post_kwargs = a.session.post.call_args
    assert args[0].endswith("Results.aspx")
    payload = post_kwargs["data"]
    assert payload["__VIEWSTATE"] == "dDuvalVS123"
    assert payload["__EVENTVALIDATION"] == "dEV456"
    assert payload["ctl00$cphBody$tbStreetNumber"] == "4409"
    assert payload["ctl00$cphBody$tbStreetName"] == "CROOKED BROOK"
    assert payload["ctl00$cphBody$ddStreetSuffix"] == "CT"


def test_lookup_by_address_ambiguous(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, SEARCH_PAGE_HTML)
    a.session.post.return_value = _resp(200, RESULTS_NO_EXACT_HTML)

    res = a.lookup_by_address("4409 Crooked Brook Court, Jacksonville, FL 32224")
    assert res.status == "PA_AMBIGUOUS"
    assert "2 candidates" in res.notes


def test_lookup_by_address_no_results(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, SEARCH_PAGE_HTML)
    a.session.post.return_value = _resp(200, "<html><body>nothing</body></html>")

    res = a.lookup_by_address("4409 Crooked Brook Court, Jacksonville, FL 32224")
    assert res.status == "PA_NO_RESULTS"


def test_lookup_by_address_search_page_http_error(pao_config):
    a = DuvalPAO(pao_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(403, "blocked")
    res = a.lookup_by_address("4409 Crooked Brook Court, Jacksonville, FL 32224")
    assert res.status == "PA_FAILED"
    assert "403" in res.notes


# --------------------------------------------------------- misc


def test_lookup_by_owner_name_diagnostics_only(pao_config):
    a = DuvalPAO(pao_config)
    assert a.lookup_by_owner_name("SKINNER MICHAEL") == []


def test_config_overrides_form_field(pao_config):
    cfg = dict(pao_config)
    cfg["form_fields"] = {"street_name": "ctl00$cphBody$customStreetName"}
    a = DuvalPAO(cfg)
    a.session = MagicMock()
    a.session.get.side_effect = [_resp(200, SEARCH_PAGE_HTML), _resp(200, SKINNER_DETAIL_HTML)]
    a.session.post.return_value = _resp(200, RESULTS_HTML)
    a.lookup_by_address("4409 Crooked Brook Ct, Jacksonville FL")
    _, post_kwargs = a.session.post.call_args
    assert "ctl00$cphBody$customStreetName" in post_kwargs["data"]
