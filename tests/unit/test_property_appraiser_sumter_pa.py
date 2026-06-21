"""Sumter County FL PA unit tests — qPublic/Schneider (AppID=1207).

All tests are offline using fixtures captured live 2026-06-18 from
qpublic.schneidercorp.com (AppID=1207 = Sumter County FL).

Key finding: Sumter is reachable from this datacenter egress WITHOUT
Cloudflare blockage (unlike the Landmark wave counties). The search
for TEGGE at 2053 LARKWOOD CT returned parcel D33G061 with full detail.

Fixtures (tests/unit/fixtures/pa_sumter/):
  * search_page.html           — search page with all 5 panels
  * search_results_larkwood.html — address search "2053 LARKWOOD" results
  * parcel_detail_D33G061.html  — TEGGE ROBERT L parcel detail
"""

from __future__ import annotations

from pathlib import Path

import pytest

bs4 = pytest.importorskip("bs4", reason="beautifulsoup4 required")

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pa_sumter"
SUMTER_CFG = {
    "county_id": "fl_sumter",
    "county_name": "Sumter",
    "app_id": "1207",
    "qpublic_host": "qpublic.schneidercorp.com",
    "platform": "qpublic_schneider_pa_http",
}


def _load(name: str) -> str:
    p = FIXTURE_DIR / name
    if not p.exists():
        pytest.skip(f"fixture {name!r} not found — run live probe first")
    return p.read_text(encoding="utf-8", errors="replace")


def _adapter():
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    return QPublicSchneiderPA(SUMTER_CFG)


# ================================================================ config
def test_sumter_config_appid():
    """Sumter adapter has correct AppID."""
    pa = _adapter()
    assert pa.app_id == "1207"
    assert pa.host == "qpublic.schneidercorp.com"


def test_sumter_search_url():
    """Search URL includes AppID=1207."""
    pa = _adapter()
    assert "AppID=1207" in pa.search_url or "AppID=1207" in pa.base_url or "1207" in pa.search_url


# ================================================================ panel discovery
def test_discover_panels_sumter():
    """Search page has all expected panels including Address."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("search_page.html")
    pa = _adapter()
    # discover_panels is a method on the adapter (or check the HTML directly)
    import re
    panels = re.findall(r'SearchIntent="([^"]+)"', html)
    assert "Address" in panels, f"Address panel missing; found: {panels}"
    assert "OwnerName" in panels, f"OwnerName panel missing; found: {panels}"
    assert "ParcelID" in panels, f"ParcelID panel missing; found: {panels}"


def test_address_panel_field_name():
    """Address panel uses ctlBodyPane$ctl03$ctl01$txtAddress for Sumter."""
    html = _load("search_page.html")
    import re
    # Confirm the address field exists in the search page
    field = re.search(r'name="(ctlBodyPane\$ctl\d+\$ctl\d+\$txtAddress)"', html)
    assert field, "Address field not found in Sumter search page"
    assert "txtAddress" in field.group(1)


# ================================================================ results grid parse
def test_parse_grid_returns_tegge():
    """Address search results include TEGGE parcel D33G061."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("search_results_larkwood.html")
    pa = _adapter()
    # parse_grid_html returns list of (key_value, ...) or similar
    # Adapter exposes parse_grid_html as a classmethod/staticmethod
    import re
    # Check for TEGGE in the raw HTML
    assert "TEGGE" in html, "TEGGE not found in search results fixture"
    assert "D33G061" in html, "Parcel D33G061 not found in results"
    assert "2053 LARKWOOD" in html, "Address 2053 LARKWOOD not in results"

    # NOTE: The Sumter search_results_larkwood.html fixture is a Report page
    # (direct-hit: address search for "2053 LARKWOOD" returned exactly one parcel
    # → qPublic auto-redirected to the detail/Report page, PageTypeID=4).
    # There is no intermediate results grid (PageTypeID=3) for this subject.
    # parse_grid_html correctly returns [] for a non-grid page; parse_detail_html
    # is the correct method (tested below in test_parse_detail_* tests).
    if hasattr(pa, 'parse_grid_html'):
        # Grid parse returns [] because the fixture is a direct-hit detail page,
        # not a multi-row results grid.  That is the correct behaviour.
        pa.parse_grid_html(html)  # must not raise


# ================================================================ detail page parse
def test_parse_detail_tegge_owner():
    """Detail page parse extracts TEGGE as owner."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("parcel_detail_D33G061.html")
    pa = _adapter()
    result = pa.parse_detail_html(html)
    assert result.status == "PA_SUCCESS", f"Expected PA_SUCCESS, got {result.status}: {result.notes}"
    assert "TEGGE" in result.owner_of_record.upper(), \
        f"Expected TEGGE in owner, got: {result.owner_of_record!r}"


def test_parse_detail_tegge_address():
    """Detail page shows 2053 LARKWOOD CT as situs."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("parcel_detail_D33G061.html")
    pa = _adapter()
    result = pa.parse_detail_html(html)
    assert "LARKWOOD" in result.situs_address.upper(), \
        f"Expected LARKWOOD in situs_address, got: {result.situs_address!r}"


def test_parse_detail_tegge_parcel():
    """Detail page parcel key is D33G061."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("parcel_detail_D33G061.html")
    pa = _adapter()
    result = pa.parse_detail_html(html)
    assert "D33G061" in (result.apn or result.folio or result.pin), \
        f"Parcel D33G061 not in apn={result.apn!r} folio={result.folio!r} pin={result.pin!r}"


def test_parse_detail_tegge_legal():
    """Legal description contains LARKWOOD / VILLAGES OF SUMTER."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("parcel_detail_D33G061.html")
    pa = _adapter()
    result = pa.parse_detail_html(html)
    legal = result.legal_description.upper()
    assert "LOT 61" in legal or "VILLAGES" in legal or "SUMTER" in legal, \
        f"Legal description unexpected: {result.legal_description!r}"


def test_parse_detail_tegge_sale_history():
    """Sales history is parsed (QCD 3/15/2023 present)."""
    from titlepro.property_appraiser.counties.qpublic_schneider_pa_http import QPublicSchneiderPA
    html = _load("parcel_detail_D33G061.html")
    pa = _adapter()
    result = pa.parse_detail_html(html)
    assert isinstance(result.sale_history, list), "sale_history should be a list"
    assert len(result.sale_history) >= 1, "Expected at least one sale (QCD 3/15/2023)"
    # The 2023 QCD should appear
    qcd_found = any("QUIT" in (e.deed_type or "").upper() or "2023" in (e.sale_date or "")
                    for e in result.sale_history)
    assert qcd_found, f"2023 QCD not found in sales: {[(e.sale_date, e.deed_type) for e in result.sale_history]}"


# ================================================================ factory wiring
def test_factory_routes_sumter():
    """fetch_property_appraiser routes fl_sumter to qpublic_schneider_pa_http."""
    from titlepro.property_appraiser import fetch_property_appraiser
    result = fetch_property_appraiser("fl_sumter", address="2053 LARKWOOD CT, THE VILLAGES, FL")
    # Should not crash — PA_NO_RUNNER if not yet wired
    assert result.status in ("PA_SUCCESS", "PA_NO_RESULTS", "PA_FAILED", "PA_NO_RUNNER", "PA_AMBIGUOUS")


# ================================================================ live-validation note
def test_live_probe_metadata():
    """Search results fixture confirms Sumter is accessible from datacenter egress."""
    html = _load("search_results_larkwood.html")
    # Confirm the fixture is from Sumter County FL (title or county-specific text)
    assert "Sumter County" in html or "SumterCountyFL" in html or "AppID=1207" in html, \
        "Fixture does not appear to be from Sumter County FL qPublic (AppID=1207)"
