"""Unit tests for PascoPA (Pasco County FL Property Appraiser).

Fixtures are LIVE-DERIVED (2026-06-10, subject parcel 04-24-21-0000-00200-0050,
36700 Christian Rd, Dade City — the RILEY case). All HTTP is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_here = Path(__file__).resolve()
REPO_ROOT = next(p for p in _here.parents if (p / "src" / "titlepro").is_dir())
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser.counties.pasco_pa import PascoPA  # noqa: E402


CONFIG = {
    "platform": "pascopa_http",
    "base_url": "https://search.pascopa.com/",
    "warmup_url": "https://search.pascopa.com/",
    "description": "Pasco County Property Appraiser",
}


# Faithful slice of the live parcel.aspx page (flatten-and-regex parser target).
PARCEL_PAGE = """
<html><body>
<div>Parcel ID <span>04-24-21-0000-00200-0050</span> &nbsp;(Card: 1 of 1)</div>
<div>Owner: <span>RILEY LYN M &amp; ROBERT S</span></div>
<div>Previous Owner: <span>RILEY LYN M &amp; ROBERT S</span></div>
<div>Mailing Address <span>RILEY TRUST</span><span>RILEY ROBERT S &amp; LYN M TTEES</span>
  <span>36700 CHRISTIAN RD</span><span>DADE CITY, FL 33523-1215</span></div>
<div>Physical Address <span>36700&nbsp;CHRISTIAN&nbsp;ROAD, DADE CITY,&nbsp;FL&nbsp;33523</span></div>
<div>Legal Description (First 200 characters)
  <span>THE NORTH 220 FT OF WEST 150 FT OF EAST 1/2 OF NORTH 1/2 OF EAST 1/2 OF NW1/4 OF NE1/4 LESS NORTH 25 FT</span>
  <div>Land Lines</div></div>
<div>Just Value <span>$299,201</span> Ag Land $0 Land $113,792 Building $162,447</div>
<table><tr><td>Assessed</td><td>$213,850</td><td>$213,850</td></tr>
<tr><td>Homestead Exemption</td><td>- $51,411</td><td>- $25,000</td></tr>
<tr><td>Taxable Value</td><td>$162,439</td><td>$188,850</td></tr></table>
<h3>Sales History</h3>
<table>
<tr><th>Month/Year</th><th>Book/Page</th><th>Type</th><th>DOR Code</th><th>Conditions</th><th>Amount</th></tr>
<tr><td>12/2020</td><td>View the official records for Book 10347 / and Page 1784</td><td>Quit Claim Deed</td><td>11</td><td>- Opens PDF in a new tab [PDF]</td><td>I $0</td></tr>
<tr><td>3/2014</td><td>View the official records for Book 9005 / and Page 2851</td><td>Warranty Deed</td><td>14</td><td>- Opens PDF in a new tab [PDF]</td><td>I $0</td></tr>
<tr><td>10/2012</td><td>View the official records for Book 8780 / and Page 0049</td><td>Warranty Deed</td><td>01</td><td>- Opens PDF in a new tab [PDF]</td><td>I $130,000</td></tr>
<tr><td>12/2011</td><td>View the official records for Book 8634 / and Page 2048</td><td>Certificate of Title</td><td>12</td><td>- Opens PDF in a new tab [PDF]</td><td>I $0</td></tr>
<tr><td>6/1993</td><td>View the official records for Book 3165 / and Page 1437</td><td>Warranty Deed</td><td></td><td></td><td>I $0</td></tr>
</table>
<script>function myFunction(){ } // When the user clicks</script>
</body></html>
"""

# Address-results page: single hit linking to parcel.aspx?parcel=<19 digits>.
HIT_LIST_ONE = """
<html><body>
<div>View Parcel Card For 04-24-21-0000-00200-0050
  <a href="parcel.aspx?parcel=2124040000002000050">RILEY TRUST RILEY ROBERT S &amp; LYN M TTEES 36700 CHRISTIAN ROAD</a>
</div>
</body></html>
"""

HIT_LIST_TWO = HIT_LIST_ONE.replace(
    "</div>\n</body>",
    """  <a href="parcel.aspx?parcel=2124040000002000051">OTHER PARCEL</a>
</div>
</body>""",
)

NO_RESULTS = "<html><body><p>No records matched your search.</p></body></html>"


def _resp(status=200, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _adapter(responses):
    a = PascoPA(CONFIG)
    a.session = MagicMock()
    a.session.get.side_effect = list(responses)
    return a


# --------------------------------------------------------------- normalize

def test_split_address_strips_city_and_suffix():
    assert PascoPA._split_address("36700 Christian Road, Dade City, FL 33523") == (
        "36700", "CHRISTIAN",
    )
    assert PascoPA._split_address("12345 Example Rd") == ("12345", "EXAMPLE")


def test_split_address_keeps_non_suffix_and_handles_missing_number():
    num, street = PascoPA._split_address("100 Palm Grass Dr, Boca")
    assert (num, street) == ("100", "PALM GRASS")
    num2, street2 = PascoPA._split_address("Christian Road")
    assert num2 == "" and "CHRISTIAN" in street2


def test_normalize_apn_formats():
    canonical = "04-24-21-0000-00200-0050"
    assert PascoPA._normalize_apn(canonical) == canonical
    assert PascoPA._normalize_apn("0424210000002000050") == canonical
    assert PascoPA._normalize_apn("12345") == ""
    assert PascoPA._normalize_apn("") == ""


def test_apn_param_reorder_roundtrip():
    canonical = "04-24-21-0000-00200-0050"
    param = PascoPA._apn_to_parcel_param(canonical)
    assert param == "2124040000002000050"  # RNG TWN SEC SUB BLK LOT
    assert PascoPA._parcel_param_to_apn(param) == canonical


# --------------------------------------------------------------- invalid APN

def test_lookup_by_apn_invalid_is_failed_soft():
    a = _adapter([])
    result = a.lookup_by_apn("not-a-parcel")
    assert result.status == "PA_FAILED"
    assert "SS-TT-RR-SSSS-BBBBB-LLLL" in result.notes


# --------------------------------------------------------------- parcel parse

def test_lookup_by_apn_parses_parcel_page():
    a = _adapter([_resp(200, "warm"), _resp(200, PARCEL_PAGE)])
    result = a.lookup_by_apn("04-24-21-0000-00200-0050")
    assert result.status == "PA_SUCCESS"
    assert result.apn == "04-24-21-0000-00200-0050"
    assert result.owner_of_record == "RILEY LYN M & ROBERT S"
    assert "CHRISTIAN ROAD" in result.situs_address
    assert "RILEY TRUST" in result.mailing_address
    assert result.legal_description.startswith("THE NORTH 220 FT")
    assert result.just_value == 299201
    assert result.assessed_value == 213850
    assert result.homestead_active is True
    assert result.homestead_amount == 51411

    # GET went to parcel.aspx with the single reordered parcel= param.
    call = a.session.get.call_args
    assert call[0][0].endswith("/parcel.aspx")
    assert call[1]["params"]["parcel"] == "2124040000002000050"


def test_sale_history_newest_first_dor_qualified():
    a = _adapter([_resp(200, "warm"), _resp(200, PARCEL_PAGE)])
    result = a.lookup_by_apn("04-24-21-0000-00200-0050")
    assert len(result.sale_history) == 5
    s0 = result.sale_history[0]
    assert s0.sale_date == "12/2020"            # newest first
    assert s0.deed_book_page == "10347 / 1784"
    assert s0.deed_type == "QCD"
    assert s0.sale_price == 0
    # The 10/2012 arm's-length acquisition: DOR 01 qualified, $130k.
    acq = next(s for s in result.sale_history if s.deed_book_page == "8780 / 0049")
    assert acq.deed_type == "WD"
    assert acq.sale_price == 130000
    assert acq.qualified is True
    # Certificate of Title mapped to CT.
    ct = next(s for s in result.sale_history if s.deed_book_page == "8634 / 2048")
    assert ct.deed_type == "CT"


# --------------------------------------------------------------- address paths

def test_lookup_by_address_single_hit_follows_to_parcel():
    a = _adapter([
        _resp(200, "warm"),
        _resp(200, HIT_LIST_ONE),   # address search
        _resp(200, PARCEL_PAGE),    # parcel fetch
    ])
    result = a.lookup_by_address("36700 Christian Road, Dade City, FL 33523")
    assert result.status == "PA_SUCCESS"
    assert result.apn == "04-24-21-0000-00200-0050"

    addr_call = a.session.get.call_args_list[1]
    params = addr_call[1]["params"]
    assert params == {
        "pid": "add", "key": "GLI", "add1": "36700", "add2": "CHRISTIAN",
        "add": "Submit",
    }


def test_lookup_by_address_ambiguous():
    a = _adapter([_resp(200, "warm"), _resp(200, HIT_LIST_TWO)])
    result = a.lookup_by_address("36700 Christian Road, Dade City, FL")
    assert result.status == "PA_AMBIGUOUS"
    assert "2 candidates" in result.notes


def test_lookup_by_address_no_results():
    a = _adapter([_resp(200, "warm"), _resp(200, NO_RESULTS)])
    result = a.lookup_by_address("99999 Nowhere St, Dade City, FL")
    assert result.status == "PA_NO_RESULTS"


# --------------------------------------------------------------- owner search

def test_lookup_by_owner_name_shallow_results_and_truncation():
    a = _adapter([_resp(200, "warm"), _resp(200, HIT_LIST_ONE)])
    results = a.lookup_by_owner_name("RILEY ROBERT S TRUSTEE OF THE RILEY TRUST")
    assert len(results) == 1
    assert results[0].apn == "04-24-21-0000-00200-0050"
    params = a.session.get.call_args_list[1][1]["params"]
    assert len(params["nam"]) <= 20
    assert params["pid"] == "nam" and params["key"] == "GLI"


# --------------------------------------------------------------- fail soft

def test_http_error_is_fail_soft_not_raise():
    a = _adapter([_resp(200, "warm"), _resp(500, "server error")])
    result = a.lookup_by_apn("04-24-21-0000-00200-0050")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_network_exception_is_fail_soft():
    a = PascoPA(CONFIG)
    a.session = MagicMock()
    a.session.get.side_effect = RuntimeError("connection reset")
    result = a.lookup_by_address("36700 Christian Road, Dade City, FL")
    assert result.status == "PA_FAILED"
    assert "RuntimeError" in result.notes or "connection reset" in result.notes
