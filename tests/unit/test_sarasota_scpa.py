"""STAGED unit tests for the Sarasota SC-PA Property Appraiser adapter.

OPERATOR ACTION REQUIRED: direct Write to tests/unit/ (and /tmp staging) was
permission-denied during the Wave-1 session (2026-06-10) — same friction the
2026-06-09 session logged for test files. To install:

    cp "src/titlepro/api/downloaded_doc/0610/Sarasota_BRUNO_v1/staged_tests_test_sarasota_scpa.py" \
       "tests/unit/test_sarasota_scpa.py"

Mocked sessions — no live SC-PA traffic. The SEARCH-FORM shape mirrors the
live capture from the 2026-06-10 Wave-1 probe (phase0_probe_pa.md). The
RESULT-LIST and DETAIL-PAGE fixtures are SYNTHETIC (live query operator-
denied in Wave 1) and define the parser contract Wave 2 must re-validate
against captured fixtures.
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

from titlepro.property_appraiser.counties.sarasota_scpa import (  # noqa: E402
    SarasotaSCPA,
    _safe_money,
)


@pytest.fixture
def scpa_config() -> Dict[str, Any]:
    return {
        "platform": "scpa_http",
        "base_url": "https://www.sc-pa.com/propertysearch/",
        "warmup_url": "https://www.sc-pa.com/propertysearch/",
        "endpoints": {
            "search_result": "https://www.sc-pa.com/propertysearch/Result",
        },
        "captcha": False,
    }


def _resp(status_code: int, text: str, url: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.url = url
    return r


# Synthetic result-list page: two anchors to the SAME parcel (one strap).
RESULT_LIST_ONE_PARCEL = """
<html><body>
<table class="results">
 <tr><td><a href="/propertysearch/parcel/details/0142150010">0142-15-0010</a></td>
     <td>1016 SCHERER WAY OSPREY, FL 34229</td></tr>
 <tr><td><a href="/propertysearch/parcel/details/0142150010">view</a></td><td></td></tr>
</table>
</body></html>
"""

# Synthetic result-list with two DIFFERENT parcels → ambiguous.
RESULT_LIST_TWO_PARCELS = """
<html><body>
<a href="/propertysearch/parcel/details/0142150010">0142-15-0010</a>
<a href="/propertysearch/parcel/details/0142150020">0142-15-0020</a>
</body></html>
"""

RESULT_LIST_EMPTY = "<html><body><p>No records matched your search.</p></body></html>"

# LIVE-SHAPED detail page (mirrors the 2026-06-10 capture of parcel
# 0150010019 — w2_capture_scpa_result.html in this case dir): page title
# carries the strap, owners on separate lines under "Ownership:",
# "Parcel&nbsp;Description" label, Values table, numeric qualification codes.
DETAIL_PAGE = """
<html><body>
<h2>Property Record Information for 0142150010</h2>
<div id="parcelDetail">
<p>Ownership:<br>BRUNO EMELIA M TRUSTEE<br>SHOLA THOMAS P TRUSTEE</p>
<p>PO BOX 915, OSPREY, FL, 34229-0915</p>
<p>Situs Address:<br>1016 SCHERER WAY OSPREY, FL, 34229</p>
<p>Parcel&nbsp;Description: LOT 22 RIVENDELL UNIT 1</p>
<p>Homestead Property: Yes</p>
</div>
<table id="values">
 <tr><th>Year</th><th>Land</th><th>Building</th><th>Just</th><th>Assessed</th></tr>
 <tr><td>2025</td><td>$178,200</td><td>$434,200</td><td>$612,400</td><td>$401,210</td></tr>
</table>
<table id="salesTransfers">
 <tr><th>Transfer Date</th><th>Recorded Consideration</th><th>Instrument Number</th>
     <th>Qualification Code</th><th>Grantor/Seller</th><th>Instrument Type</th></tr>
 <tr><td>2/25/2013</td><td>$100</td><td><a href="#">2013021460</a></td>
     <td>11</td><td>SHOLA THOMAS P &amp; BRUNO EMELIA M</td><td>QC</td></tr>
 <tr><td>6/15/2001</td><td>$285,000</td><td>OR BK 3547 / PG 1201</td>
     <td>01</td><td>RIVENDELL HOMES INC</td><td>WD</td></tr>
</table>
</body></html>
"""


def _wire_session(adapter, post_pages, detail_page=DETAIL_PAGE):
    """Mock session: GETs to a parcel-detail href return `detail_page`;
    other GETs (warmup) return a blank page; POSTs return `post_pages`."""
    session = MagicMock()
    posts = list(post_pages) if isinstance(post_pages, (list, tuple)) else [post_pages]

    def fake_get(url, **kw):
        if "parcel/details" in url:
            return _resp(200, detail_page, url=url)
        return _resp(200, "<html></html>", url=url)

    def fake_post(url, **kw):
        return posts.pop(0) if len(posts) > 1 else posts[0]

    session.get.side_effect = fake_get
    session.post.side_effect = fake_post
    adapter.session = session
    return session


def test_normalize_address_strips_city_and_ordinals(scpa_config):
    a = SarasotaSCPA(scpa_config)
    assert (
        a._normalize_address_for_lookup("1016 Scherer Way, Osprey, FL 34229")
        == "1016 SCHERER WAY"
    )
    assert a._normalize_address_for_lookup("2856 NE 27th St, Sarasota") == "2856 NE 27 ST"


def test_normalize_apn_digits_only(scpa_config):
    a = SarasotaSCPA(scpa_config)
    assert a._normalize_apn("0142-15-0010") == "0142150010"
    assert a._normalize_apn("0142.15.0010 ") == "0142150010"
    assert a._normalize_apn("") == ""


def test_lookup_by_address_result_list_then_detail(scpa_config):
    a = SarasotaSCPA(scpa_config)
    session = _wire_session(a, _resp(200, RESULT_LIST_ONE_PARCEL))
    r = a.lookup_by_address("1016 Scherer Way, Osprey, FL 34229")
    assert r.status == "PA_SUCCESS"
    assert r.apn == "0142150010"
    assert r.owner_of_record == "BRUNO EMELIA M TRUSTEE"
    assert r.co_owners == ["SHOLA THOMAS P TRUSTEE"]
    assert "1016 SCHERER WAY" in r.situs_address.upper()
    assert "RIVENDELL" in r.legal_description.upper()
    _, kwargs = session.post.call_args
    assert kwargs["data"]["AddressKeywords"] == "1016 SCHERER WAY"
    assert kwargs["data"]["Strap"] == ""


def test_lookup_by_address_unique_hit_renders_detail_directly(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(200, DETAIL_PAGE, url="https://www.sc-pa.com/propertysearch/Result"))
    r = a.lookup_by_address("1016 Scherer Way, Osprey, FL 34229")
    assert r.status == "PA_SUCCESS"
    assert r.apn == "0142150010"


def test_lookup_by_address_no_results(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(200, RESULT_LIST_EMPTY))
    r = a.lookup_by_address("999 NOWHERE LN, OSPREY, FL")
    assert r.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous_two_parcels(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(200, RESULT_LIST_TWO_PARCELS))
    r = a.lookup_by_address("SCHERER WAY")
    assert r.status == "PA_AMBIGUOUS"
    assert "0142150010" in r.notes and "0142150020" in r.notes


def test_lookup_by_address_http_error_fails_soft(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(500, "Server Error"))
    r = a.lookup_by_address("1016 SCHERER WAY")
    assert r.status == "PA_FAILED"
    assert "500" in r.notes


def test_lookup_by_apn_normalizes_strap_in_payload(scpa_config):
    a = SarasotaSCPA(scpa_config)
    session = _wire_session(a, _resp(200, RESULT_LIST_ONE_PARCEL))
    r = a.lookup_by_apn("0142-15-0010")
    assert r.status == "PA_SUCCESS"
    _, kwargs = session.post.call_args
    assert kwargs["data"]["Strap"] == "0142150010"
    assert kwargs["data"]["AddressKeywords"] == ""


def test_lookup_by_apn_empty_fails(scpa_config):
    a = SarasotaSCPA(scpa_config)
    r = a.lookup_by_apn("---")
    assert r.status == "PA_FAILED"


def test_sale_history_newest_first_with_instrument_and_bookpage(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(200, RESULT_LIST_ONE_PARCEL))
    r = a.lookup_by_address("1016 SCHERER WAY, OSPREY, FL")
    assert len(r.sale_history) == 2
    newest, oldest = r.sale_history
    assert newest.sale_date == "2/25/2013"
    assert newest.deed_doc_number == "2013021460"
    assert newest.deed_type == "QC"
    assert newest.qualified is False
    assert oldest.sale_date == "6/15/2001"
    assert oldest.deed_book_page == "3547/1201"
    assert oldest.deed_doc_number == ""
    assert oldest.sale_price == 285000
    assert oldest.qualified is True
    assert "RIVENDELL HOMES" in oldest.grantor


def test_lookup_by_owner_name_returns_list(scpa_config):
    a = SarasotaSCPA(scpa_config)
    _wire_session(a, _resp(200, RESULT_LIST_ONE_PARCEL))
    out = a.lookup_by_owner_name("BRUNO EMELIA")
    assert len(out) >= 1
    assert out[0].apn == "0142150010"


def test_lookup_by_owner_name_blank_returns_empty(scpa_config):
    a = SarasotaSCPA(scpa_config)
    assert a.lookup_by_owner_name("  ") == []


def test_safe_money():
    assert _safe_money("$612,400") == 612400
    assert _safe_money("285000") == 285000
    assert _safe_money("") == 0
    assert _safe_money(None) == 0
