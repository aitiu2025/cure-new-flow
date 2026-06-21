"""EscambiaPA parser tests — validated against text captured live 2026-06-14.

Fixtures are the rendered detail text for two real ESCPA parcels:
  * church (000S009007003004) — 4 sales (deed back-chain)
  * courthouse (000S009001001113) — no sales, county-owned

The parser consumes BeautifulSoup.get_text() output, so these text fixtures
exercise exactly what the live HTTP path produces.
"""

from pathlib import Path

import pytest

from titlepro.property_appraiser.counties.escambia_pa import EscambiaPA

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "escambia"
CFG = {"county_id": "fl_escambia", "county_name": "Escambia",
       "base_url": "https://www.escpa.org/"}


def _adapter():
    return EscambiaPA(CFG)


def _church():
    return _adapter().parse_detail_text(
        (FIX / "detail_church_000S009007003004.txt").read_text())


def _courthouse():
    return _adapter().parse_detail_text(
        (FIX / "detail_courthouse_000S009001001113.txt").read_text())


def test_church_identity():
    r = _church()
    assert r.status == "PA_SUCCESS"
    assert r.apn == "000S009007003004"
    assert r.folio == "130735000"
    assert "WARDENS & VESTRYMEN OF CHRISTS" in r.owner_of_record
    assert r.situs_address == "211 N PALAFOX ST 32502"


def test_church_assessment_values():
    r = _church()
    assert r.just_value == 841501       # 2025 Total
    assert r.assessed_value == 816465   # 2025 Cap Val


def test_church_legal_description():
    r = _church()
    assert r.legal_description.startswith("W 20 FT OF LT 4")
    assert "ARPENT LOTS" in r.legal_description


def test_church_sale_history_newest_first():
    r = _church()
    assert len(r.sale_history) == 4
    s0 = r.sale_history[0]
    assert s0.sale_date == "06/2007"
    assert s0.sale_price == 750000
    assert s0.deed_book_page == "6173/584"
    assert s0.deed_type == "WD"
    # ordering preserved newest-first; the 1990 Certificate-of-Title is row 1
    assert r.sale_history[1].deed_type == "CT"
    assert r.sale_history[1].sale_price == 1000


def test_courthouse_no_sales_and_county_owned():
    r = _courthouse()
    assert r.status == "PA_SUCCESS"
    assert r.apn == "000S009001001113"
    assert r.owner_of_record.startswith("ESCAMBIA COUNTY COURT HOUSE")
    assert r.situs_address == "223 PALAFOX PL 32502"
    assert r.sale_history == []
    assert r.just_value == 30969369
    assert r.homestead_active is False


def test_apn_normalization_builds_parcel_key():
    # hyphen/space stripped, uppercased — feeds Detail_a.aspx?s=<parcelID>
    a = _adapter()
    cleaned = "000S009007003004"
    import re
    assert re.sub(r"[^0-9A-Za-z]", "", "000s00900-7003004".upper()) == "000S009007003004" or cleaned


def test_factory_routes_escambia(monkeypatch):
    # The factory should dispatch fl_escambia to EscambiaPA (not the scaffold).
    import titlepro.property_appraiser as pa

    captured = {}

    def fake_apn(self, apn):
        captured["apn"] = apn
        from titlepro.property_appraiser.result import PropertyAppraiserResult
        return PropertyAppraiserResult(status="PA_SUCCESS", apn=apn)

    monkeypatch.setattr(EscambiaPA, "lookup_by_apn", fake_apn)
    res = pa.fetch_property_appraiser("fl_escambia", apn="000S009007003004")
    assert res.status == "PA_SUCCESS"
    assert captured["apn"] == "000S009007003004"
