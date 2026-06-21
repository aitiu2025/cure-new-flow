"""QPublicSchneiderPA parser tests — validated against text captured live 2026-06-17.

The shared qPublic/Schneider adapter serves 9 FL Landmark counties off ONE
multi-tenant Schneider app. These tests drive the side-effect-free parsers
(parse_detail_html / parse_grid_html / discover_panels) against captured
fixtures so no network is touched.

Fixtures (tests/unit/fixtures/qpublic/):
  * clay_search_page.html      — Clay (AppID 830) search page (panel discovery)
  * clay_detail_schirbock.html — real Clay residential parcel, 3 sales
  * clay_grid_main_st.html     — real Clay address-search results grid (5 rows)
  * clay_noresults.html        — real Clay "No results match your search criteria"
  * walton_detail.html         — real Walton (beacon host) parcel — cross-tenant,
                                 "Primary Owner" sub-label + "Just (Market) Value"
                                 / "Assessed Value" label drift
  * synthetic_coowner_detail.html — co-owners + QCD + $0 sale (real layout)
  * malformed_detail.html      — truncated page (fail-soft check)
"""

from pathlib import Path

import pytest

from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import (
    QPublicSchneiderPA,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "qpublic"

CLAY_CFG = {"county_id": "fl_clay", "county_name": "Clay", "app_id": "830"}
WALTON_CFG = {"county_id": "fl_walton", "county_name": "Walton", "app_id": "835",
              "qpublic_host": "beacon.schneidercorp.com"}


def _clay():
    return QPublicSchneiderPA(CLAY_CFG)


def _walton():
    return QPublicSchneiderPA(WALTON_CFG)


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="ignore")


# --------------------------------------------------------------- config / wiring
def test_config_sets_appid_and_host():
    a = _clay()
    assert a.app_id == "830"
    assert a.host == "qpublic.schneidercorp.com"
    assert a.search_url == (
        "https://qpublic.schneidercorp.com/Application.aspx?AppID=830&PageType=Search"
    )


def test_beacon_host_is_config_driven():
    a = _walton()
    assert a.host == "beacon.schneidercorp.com"
    assert a.search_url.startswith("https://beacon.schneidercorp.com/Application.aspx")


def test_missing_appid_fails_soft():
    a = QPublicSchneiderPA({"county_id": "fl_x"})  # no app_id
    r = a.lookup_by_apn("123")
    assert r.status == "PA_FAILED"
    assert "missing app_id" in r.notes


# ------------------------------------------------------------- cf_clearance jar
def test_cookie_jar_present_applies_cookies(tmp_path):
    import json
    jar = {
        "minted_at": "2026-06-18T00:00:00",
        "landing": "https://qpublic.schneidercorp.com/",
        "cookies": [
            {"name": "cf_clearance", "value": "abc123",
             "domain": ".schneidercorp.com", "path": "/", "secure": True},
            {"name": "__cf_bm", "value": "xyz",
             "domain": ".schneidercorp.com", "path": "/"},
        ],
    }
    jar_path = tmp_path / "schneider_cookies.json"
    jar_path.write_text(json.dumps(jar), encoding="utf-8")
    a = QPublicSchneiderPA({**CLAY_CFG, "cookie_jar": str(jar_path)})
    session = a._session()
    names = [c.name for c in session.cookies.jar]
    assert "cf_clearance" in names
    assert "__cf_bm" in names


def test_cookie_jar_absent_is_noop(tmp_path):
    # A missing jar must not raise and must apply zero cookies (no regression
    # vs. having no jar at all) — keeps the default path a pure no-op.
    a = QPublicSchneiderPA({**CLAY_CFG, "cookie_jar": str(tmp_path / "nope.json")})
    session = a._session()
    assert a._load_cookie_jar(a._session()) == 0
    assert all(c.name not in ("cf_clearance", "__cf_bm")
               for c in session.cookies.jar)


def test_cookie_jar_malformed_fails_soft(tmp_path):
    jar_path = tmp_path / "bad.json"
    jar_path.write_text("{ this is not json", encoding="utf-8")
    a = QPublicSchneiderPA({**CLAY_CFG, "cookie_jar": str(jar_path)})
    # malformed jar -> 0 applied, never raises
    assert a._load_cookie_jar(a._session()) == 0


# ------------------------------------------------------------- panel discovery
def test_discover_panels_maps_search_intents():
    panels = QPublicSchneiderPA.discover_panels(_read("clay_search_page.html"))
    # Clay layout: Name=ctl00, Address=ctl01, ParcelID=ctl02
    assert panels["OwnerName"][0] == "ctlBodyPane$ctl00$ctl01$btnSearch"
    assert panels["Address"][0] == "ctlBodyPane$ctl01$ctl01$btnSearch"
    assert panels["ParcelID"][0] == "ctlBodyPane$ctl02$ctl01$btnSearch"
    # field prefix is the target minus $btnSearch
    assert panels["Address"][1] == "ctlBodyPane$ctl01$ctl01"


# ---------------------------------------------------------------- detail parse
def test_clay_detail_identity_and_situs():
    r = _clay().parse_detail_html(_read("clay_detail_schirbock.html"))
    assert r.status == "PA_SUCCESS"
    assert r.apn == "07-05-25-009080-001-00"
    assert r.folio == r.apn
    assert r.owner_of_record == "Schirbock Brian"
    assert "3713 MAIN St" in r.situs_address
    assert "Middleburg" in r.situs_address


def test_clay_detail_legal_and_values_and_homestead():
    r = _clay().parse_detail_html(_read("clay_detail_schirbock.html"))
    assert r.legal_description.startswith("PT OF LOT 5")
    assert r.just_value == 275407       # current-year Just Market Value
    assert r.assessed_value == 152525   # current-year Total Assessed Value
    assert r.homestead_active is True
    assert r.year_built == 1962
    assert r.source_url.endswith("KeyValue=07-05-25-009080-001-00")


def test_clay_detail_sales_newest_first_and_columns_aligned():
    r = _clay().parse_detail_html(_read("clay_detail_schirbock.html"))
    assert len(r.sale_history) == 3
    s0 = r.sale_history[0]
    assert s0.sale_date == "11/8/2019"
    assert s0.sale_price == 210000        # was the bug: th+td column shift
    assert s0.deed_book_page == "4251/597"
    assert s0.deed_type == "WD"
    assert s0.grantor == "HEBDEN BONNIE L"
    assert s0.grantee == "Schirbock Brian"
    assert s0.qualified is True
    # newest-first ordering: 2019 -> 2008 -> 1983
    assert r.sale_history[1].sale_date == "12/18/2008"
    assert r.sale_history[1].deed_type == "TXD"   # Tax Deed normalized
    assert r.sale_history[2].sale_date == "12/1/1983"


def test_walton_cross_tenant_owner_sublabel_and_value_label_drift():
    # Walton (beacon host) renders a "Primary Owner" sub-label AND uses
    # "Just (Market) Value" / "Assessed Value" — different from Clay's labels.
    r = _walton().parse_detail_html(_read("walton_detail.html"))
    assert r.status == "PA_SUCCESS"
    assert r.apn  # parcel id captured
    # the "Primary Owner" sub-label must be skipped, real owner captured
    assert r.owner_of_record
    assert "Primary Owner" not in r.owner_of_record
    # flexible value-label matching still pulled a number
    assert r.just_value > 0
    assert r.assessed_value > 0


def test_coowner_and_qcd_and_zero_price_sale():
    r = QPublicSchneiderPA({"county_id": "fl_sample", "app_id": "999"}).parse_detail_html(
        _read("synthetic_coowner_detail.html"))
    assert r.owner_of_record == "DOE JOHN A"
    assert r.co_owners == ["DOE JANE B"]
    assert "ANYTOWN FL 30000" in r.mailing_address
    assert r.just_value == 300000
    assert r.assessed_value == 210000
    # newest-first; QCD with $0 price + unqualified flag
    assert r.sale_history[0].deed_type == "WD"
    qcd = r.sale_history[1]
    assert qcd.deed_type == "QCD"
    assert qcd.sale_price == 0
    assert qcd.qualified is False


# ----------------------------------------------------------------- grid parse
def test_grid_parses_multiple_rows_with_keyvalues():
    rows = _clay().parse_grid_html(_read("clay_grid_main_st.html"))
    assert len(rows) == 5
    first = rows[0]
    assert first["parcel_id"] == "07-05-25-009080-001-00"
    assert first["key_value"] == "07-05-25-009080-001-00"
    assert first["owner"] == "Schirbock Brian"
    assert "MAIN St" in first["address"]
    # every row carries a usable KeyValue for the detail follow-up
    assert all(r["key_value"] for r in rows)


def test_grid_distinct_parcels_for_ambiguity():
    rows = _clay().parse_grid_html(_read("clay_grid_main_st.html"))
    parcels = {r["parcel_id"] for r in rows}
    assert len(parcels) == 5  # genuinely distinct -> ambiguous multi-match


# ----------------------------------------------------------------- no results
def test_noresults_grid_is_empty():
    rows = _clay().parse_grid_html(_read("clay_noresults.html"))
    assert rows == []


def test_noresults_detail_status():
    r = _clay().parse_detail_html(_read("clay_noresults.html"))
    assert r.status == "PA_NO_RESULTS"


# ------------------------------------------------------------------- fail-soft
def test_malformed_detail_fails_soft_no_raise():
    r = _clay().parse_detail_html(_read("malformed_detail.html"))
    assert r.status == "PA_NO_RESULTS"   # never raises
    assert r.apn == ""


def test_deed_type_normalization():
    norm = QPublicSchneiderPA._deed_type_code
    assert norm("Warranty Deed") == "WD"
    assert norm("Quit Claim Deed") == "QCD"
    assert norm("Tax Deed") == "TXD"
    assert norm("Certificate of Title") == "CT"
    assert norm("Personal Representative Deed") == "PRD"
    assert norm("Something Else") == "Something Else"


# ------------------------------------------------------------------- factory
def test_factory_routes_qpublic_county(monkeypatch):
    import titlepro.property_appraiser as pa
    from titlepro.property_appraiser.result import PropertyAppraiserResult

    captured = {}

    def fake_apn(self, apn):
        captured["apn"] = apn
        captured["app_id"] = self.app_id
        return PropertyAppraiserResult(status="PA_SUCCESS", apn=apn)

    monkeypatch.setattr(QPublicSchneiderPA, "lookup_by_apn", fake_apn)
    res = pa.fetch_property_appraiser("fl_clay", apn="07-05-25-009080-001-00")
    assert res.status == "PA_SUCCESS"
    assert captured["apn"] == "07-05-25-009080-001-00"
    assert captured["app_id"] == "830"
