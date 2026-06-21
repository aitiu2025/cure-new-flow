"""Unit tests for the Polk County Property Appraiser adapter (CamaDisplay scrape).

No live traffic — polkpa.org is firewall/geo-fenced (unreachable Wave-1), so the
parser is exercised against a representative canned ASP.NET WebForms fixture (see
Polk_BUNKER_v1/phase0_probe_pa.md). The live HTTP flow is wired but probe-pending.
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

from titlepro.property_appraiser.result import PropertyAppraiserResult  # noqa: E402
from titlepro.property_appraiser.counties.polk_pa import PolkPA  # noqa: E402


def _cfg() -> Dict[str, Any]:
    return {
        "platform": "polk_pa",
        "base_url": "https://www.polkpa.org/",
        "endpoints": {
            "cama_display": "https://www.polkpa.org/CamaDisplay.aspx",
            "advanced_search": "https://www.polkpa.org/AdvancedQuerySearch.aspx",
        },
        "tax_year": "2025",
    }


CAMA_HTML = """
<html><body>
<table>
<tr><td class="label">Parcel ID</td><td class="value">24-29-12-000000-012345</td></tr>
<tr><td class="label">Owner</td><td class="value">BUNKER WILLIAM JOSEPH &amp; JULIE C</td></tr>
<tr><td class="label">Site Address</td><td class="value">6836 HAMPSHIRE BLVD, LAKELAND, FL 33813</td></tr>
<tr><td class="label">Mailing Address</td><td class="value">6836 HAMPSHIRE BLVD, LAKELAND FL 33813</td></tr>
<tr><td class="label">Legal Description</td><td class="value">HALLMARK HILLS PB 90 PG 12 LOT 5</td></tr>
<tr><td class="label">Just Value</td><td class="value">$345,210</td></tr>
<tr><td class="label">Assessed Value</td><td class="value">$298,400</td></tr>
</table>
<table>
<tr><th>Sale Date</th><th>Price</th><th>Deed Type</th><th>OR Book/Page</th><th>Grantor</th></tr>
<tr><td>05/14/2018</td><td>$310,000</td><td>WD</td><td>09876/1234</td><td>TOIVANEN PERTTU</td></tr>
<tr><td>03/02/2009</td><td>$0</td><td>QCD</td><td>07654/4321</td><td>SMITH JANE</td></tr>
</table>
</body></html>
"""


def test_parse_parcel_html_fields():
    pa = PolkPA(_cfg())
    res = pa.parse_parcel_html(CAMA_HTML, apn="24-29-12-000000-012345",
                               source_url="https://www.polkpa.org/CamaDisplay.aspx?ParcelID=x")
    assert isinstance(res, PropertyAppraiserResult)
    assert res.status == "PA_SUCCESS"
    assert res.apn == "24-29-12-000000-012345"
    assert res.owner_of_record.startswith("BUNKER WILLIAM JOSEPH")
    assert "6836 HAMPSHIRE BLVD" in res.situs_address
    assert res.legal_description.startswith("HALLMARK HILLS")
    assert res.just_value == 345210
    assert res.assessed_value == 298400


def test_parse_parcel_html_sale_history_newest_first():
    pa = PolkPA(_cfg())
    res = pa.parse_parcel_html(CAMA_HTML, apn="24-29-12-000000-012345")
    assert len(res.sale_history) == 2
    s0 = res.sale_history[0]
    assert s0.sale_date == "05/14/2018"
    assert s0.deed_type == "WD"
    assert s0.deed_book_page == "09876/1234"   # has '/', so classified as book/page
    assert s0.deed_doc_number == ""
    assert s0.sale_price == 310000
    assert s0.grantor == "TOIVANEN PERTTU"
    assert res.sale_history[1].sale_date == "03/02/2009"


def test_deed_identifiers_back_chain():
    pa = PolkPA(_cfg())
    res = pa.parse_parcel_html(CAMA_HTML)
    ids = res.deed_identifiers()
    assert "09876/1234" in ids


def test_normalize_apn_keeps_hyphens_strips_space():
    assert PolkPA._normalize_apn("  24-29-12-000000-012345 ") == "24-29-12-000000-012345"
    assert PolkPA._normalize_apn("24 29 12 000000 012345") == "242912000000012345"


def test_normalize_address_for_lookup():
    pa = PolkPA(_cfg())
    assert pa._normalize_address_for_lookup("6836 Hampshire Blvd, Lakeland, FL 33813") == "6836 HAMPSHIRE BLVD"
    assert pa._normalize_address_for_lookup("123 NW 27th St, X") == "123 NW 27 ST"


def test_lookup_by_apn_empty_is_pa_failed():
    res = PolkPA(_cfg()).lookup_by_apn("")
    assert res.status == "PA_FAILED"


def test_lookup_by_address_is_ambiguous_until_probe():
    res = PolkPA(_cfg()).lookup_by_address("6836 Hampshire Blvd, Lakeland, FL 33813")
    assert res.status == "PA_AMBIGUOUS"
    assert "AdvancedQuerySearch" in res.source_url


def test_lookup_by_apn_uses_cama_template_and_parses(monkeypatch):
    pa = PolkPA(_cfg())
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.text = CAMA_HTML
    sess.get.return_value = resp
    pa.session = sess
    res = pa.lookup_by_apn("24-29-12-000000-012345")
    assert res.status == "PA_SUCCESS"
    assert res.owner_of_record.startswith("BUNKER WILLIAM JOSEPH")
    # the GET hit CamaDisplay with the strap interpolated
    called_url = sess.get.call_args_list[-1][0][0]
    assert "CamaDisplay.aspx" in called_url and "24-29-12-000000-012345" in called_url


def test_lookup_by_apn_http_error_is_pa_failed():
    pa = PolkPA(_cfg())
    sess = MagicMock()
    sess.get.side_effect = RuntimeError("connection timed out")
    pa.session = sess
    res = pa.lookup_by_apn("24-29-12-000000-012345")
    assert res.status == "PA_FAILED"
    assert "timed out" in res.notes.lower() or "error" in res.notes.lower()


def test_lookup_by_owner_name_returns_empty():
    assert PolkPA(_cfg()).lookup_by_owner_name("BUNKER WILLIAM") == []
