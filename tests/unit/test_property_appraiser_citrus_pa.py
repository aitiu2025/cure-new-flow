"""CitrusPA parser tests — validated against HTML captured live 2026-06-18.

Citrus runs the Tyler/TrueAutomation "EagleWeb" (ProVal Web) property-search
engine at www.citruspa.org/_web/ — plain IIS, no Cloudflare. Fixtures are the
real bytes pulled during the build probe (see
docs/FL/source/landmark_pa_probe/fl_citrus/probe_observed.md):

  * disclaimer.html              — the one-time VIEWSTATE Disclaimer gate
  * results_highland.html        — searchResults grid for "1015 S HIGHLANDS AVE"
  * noresults.html               — "did not find any records" page
  * detail_profileall_niculae.html — Datalet mode=profileall for parcel
                                     20E19S210020 (RAJAE NICULAE + co-owner)

These regression-guard the live-parse breaks that green-against-curated-fixtures
masks: EagleWeb's Datalet section tables are keyed by table id with <td> header
rows (NOT <th>), and the grid's detail link is &amp;-encoded in the row onclick.
"""

from pathlib import Path

import pytest

from titlepro.property_appraiser.counties.citrus_pa import CitrusPA

FIX = Path(__file__).resolve().parent / "fixtures" / "citrus"
CFG = {"county_id": "fl_citrus", "county_name": "Citrus",
       "base_url": "https://www.citruspa.org/"}


def _adapter():
    return CitrusPA(CFG)


def _read(name):
    return (FIX / name).read_text()


def _detail():
    return _adapter().parse_profileall_html(_read("detail_profileall_niculae.html"))


# --------------------------------------------------------------- disclaimer
def test_disclaimer_exposes_accept_form():
    a = _adapter()
    html = _read("disclaimer.html")
    assert "btAgree" in html
    # The VIEWSTATE engine fields the accept POST needs must be extractable.
    assert a._hidden(html, "__VIEWSTATE")
    assert a._hidden(html, "hdURL").endswith("commonsearch.aspx?mode=address")


# ------------------------------------------------------------- results grid
def test_results_grid_parses_rows():
    a = _adapter()
    rows = a.parse_results_grid(_read("results_highland.html"))
    # 15 SearchResults rows (one per owner; header + hidden spacer dropped).
    assert len(rows) == 15
    first = rows[0]
    assert first["parcel_id"].startswith("20E19S210020")
    assert first["owner"] == "NICULAE RAJAE"
    assert first["address"] == "1015 S HIGHLANDS AVE"
    assert first["city"] == "INVERNESS"
    # &amp;-encoded detail link must still yield the Datalet key.
    assert first["sIndex"] == "0" and first["idx"] == "1"


def test_results_grid_multi_owner_same_parcel():
    # EagleWeb emits one row per owner — the subject parcel surfaces twice.
    rows = _adapter().parse_results_grid(_read("results_highland.html"))
    subject = [r for r in rows if r["parcel_id"].startswith("20E19S210020  02280 0400")]
    owners = {r["owner"] for r in subject}
    assert owners == {"NICULAE RAJAE", "MONIODES PETER GEORGE"}


def test_no_results_returns_empty():
    rows = _adapter().parse_results_grid(_read("noresults.html"))
    assert rows == []


# ---------------------------------------------------------- profileall detail
def test_detail_identity():
    r = _detail()
    assert r.status == "PA_SUCCESS"
    assert r.apn == "20E19S210020"
    assert r.folio == "1772311"
    assert r.owner_of_record == "NICULAE RAJAE"
    assert r.situs_address == "1015 S HIGHLANDS AVE, INVERNESS, 34452"


def test_detail_co_owner_recovered():
    # All Owners table is <td>-headed + id="All Owners" — the co-owner was
    # silently dropped before the id-based parser.
    r = _detail()
    assert r.co_owners == ["MONIODES PETER GEORGE"]


def test_detail_legal_and_homestead():
    r = _detail()
    assert r.legal_description == "INVERNESS HGLDS SOUTH PB 3 PG 51 LOTS 40 & 41 BLK 228"
    assert r.homestead_active is True
    assert r.year_built == 1975


def test_detail_value_history():
    # Just Value + Non-Sch. Assessed off the newest (2025) Value History row.
    r = _detail()
    assert r.just_value == 174430
    assert r.assessed_value == 165140


def test_detail_sales_newest_first():
    r = _detail()
    assert len(r.sale_history) == 6
    s0 = r.sale_history[0]
    assert s0.sale_date == "06/15/2018"
    assert s0.sale_price == 134900
    assert s0.deed_book_page == "2907/1813"
    # newest-first ordering preserved; the 2016 row is a normalized warranty deed
    assert r.sale_history[2].sale_date == "04/15/2016"
    assert r.sale_history[2].deed_type == "WD"
    assert r.sale_history[2].sale_price == 100000


# ----------------------------------------------------------------- factory
def test_factory_routes_citrus(monkeypatch):
    # The factory must dispatch fl_citrus to CitrusPA, not the Landmark scaffold.
    import titlepro.property_appraiser as pa

    captured = {}

    def fake_apn(self, apn):
        captured["apn"] = apn
        from titlepro.property_appraiser.result import PropertyAppraiserResult
        return PropertyAppraiserResult(status="PA_SUCCESS", apn=apn)

    monkeypatch.setattr(CitrusPA, "lookup_by_apn", fake_apn)
    res = pa.fetch_property_appraiser("fl_citrus", apn="20E19S210020")
    assert res.status == "PA_SUCCESS"
    assert captured["apn"] == "20E19S210020"
