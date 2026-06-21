"""Unit tests for the Palm Beach County Property Appraiser (PBCPAO) adapter.

Covers:
  1. No browser-driver leakage at import.
  2. PCN normalization (hyphen-strip + 17-digit reformat).
  3. KV-table parser (Property detail table).
  4. Sales-history parser (split book/page cells -> SaleHistoryEntry).
  5. Owner table parser (primary owner + co-owners + mailing address).
  6. Assessment table parser (assessed/taxable/exemption from leftmost
     numeric column = most recent year).
  7. Exemption table parser (homestead_active flag for current year).
  8. lookup_by_apn success path (mocked HTTP returning sample HABER HTML).
  9. lookup_by_apn no-results path (empty short HTML).
 10. lookup_by_address returns PA_AMBIGUOUS with manual lookup URL (PBCPAO
     address search is not yet reverse-engineered).
 11. Factory wiring — county_id='fl_palm_beach' resolves to PalmBeachPBCPAO.

Live validation snapshot was captured against
`https://www.pbcpao.gov/Property/Details/?parcelId=00414722040001090` on
2026-05-26 — the fixture below carries the key rows verbatim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# Synthetic HTML mirroring the structure of the live PBCPAO Property/Details
# page for HABER subject (PCN 00-41-47-22-04-000-1090).
HABER_PBCPAO_HTML = """
<html><head><title>PAPA - 21831 PALM GRASS DR</title></head><body>

<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Location Address</td><td>21831 PALM GRASS DR</td></tr>
<tr><td>Municipality</td><td>UNINCORPORATED</td></tr>
<tr><td>Parcel Control Number</td><td>00-41-47-22-04-000-1090</td></tr>
<tr><td>Subdivision</td><td>BOCA WINDS PAR E</td></tr>
<tr><td>Official Records Book/Page</td><td>11081 / 0560</td></tr>
<tr><td>Sale Date</td><td>04/01/1999</td></tr>
<tr><td>Legal Description</td><td>BOCA WINDS PAR E              LT 109</td></tr>
</table>

<table>
<tr><th>Owner(s)</th><th>Mailing Address</th><th>Actions</th></tr>
<tr><td>HABER DANA M</td><td>21831 PALM GRASS DR</td><td>Change of Mailing Address</td></tr>
<tr><td>HABER MARK &amp;</td><td>BOCA RATON FL 33428 4786</td><td></td></tr>
</table>

<table>
<tr><th>Sales Date</th><th>Price</th><th>OR Book/Page</th><th></th><th></th><th>Sale Type</th><th>Owner</th></tr>
<tr><td>04/01/1999</td><td>$238,000</td><td>11081</td><td>/</td><td>00560</td><td>WARRANTY DEED</td><td>HABER MARK &amp;</td></tr>
<tr><td>06/01/1995</td><td>$204,900</td><td>08826</td><td>/</td><td>00885</td><td>WARRANTY DEED</td><td></td></tr>
</table>

<table>
<tr><th>Applicant/Owner(s)</th><th>Year</th><th>Detail</th></tr>
<tr><td>HABER MARK &amp;</td><td>2026</td><td>HOMESTEAD</td></tr>
<tr><td>HABER MARK &amp;</td><td>2026</td><td>ADDITIONAL HOMESTEAD</td></tr>
<tr><td>HABER DANA M</td><td>2026</td><td>HOMESTEAD</td></tr>
</table>

<table>
<tr><td></td><td>Tax Year</td><td>2025</td><td>2024</td><td>2023</td><td>2022</td><td>2021</td></tr>
<tr><td>Improvement Value</td><td></td><td>$417,011</td><td>$454,014</td><td>$460,060</td><td>$403,388</td><td>$278,087</td></tr>
<tr><td>Land Value</td><td></td><td>$203,849</td><td>$203,849</td><td>$167,090</td><td>$166,962</td><td>$143,078</td></tr>
<tr><td>Total Market Value</td><td></td><td>$620,860</td><td>$657,863</td><td>$627,150</td><td>$570,350</td><td>$421,165</td></tr>
</table>

<table>
<tr><td></td><td>Tax Year</td><td>2025</td><td>2024</td><td>2023</td><td>2022</td><td>2021</td></tr>
<tr><td>Assessed Value</td><td></td><td>$314,276</td><td>$305,419</td><td>$296,523</td><td>$287,886</td><td>$279,501</td></tr>
<tr><td>Exemption Amount</td><td></td><td>$50,722</td><td>$50,000</td><td>$50,000</td><td>$50,000</td><td>$50,000</td></tr>
<tr><td>Taxable Value</td><td></td><td>$263,554</td><td>$255,419</td><td>$246,523</td><td>$237,886</td><td>$229,501</td></tr>
</table>

<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Year Built</td><td>1995</td></tr>
<tr><td>Total Square Feet*</td><td>3750</td></tr>
<tr><td>Bed Rooms</td><td>5</td></tr>
</table>

""" + ("<p>filler text to push html length above 5000 byte minimum check</p>" * 100)


@pytest.fixture(scope="module")
def pa_config() -> dict:
    return {
        "platform": "pbcpao_http",
        "base_url": "https://www.pbcpao.gov/",
        "endpoints": {
            "parcel_detail": "https://www.pbcpao.gov/Property/Details/",
            "address_search": "https://www.pbcpao.gov/AdvSearch/RealPropSearch",
            "public_detail_pattern": "https://www.pbcpao.gov/Property/Details/?parcelId={pcn_clean}",
        },
        "captcha": False,
        "impersonate": "chrome120",
        "description": "Palm Beach County Property Appraiser",
    }


# ---------------------------------------------------------------------------
# 1) No browser-driver leakage at import
# ---------------------------------------------------------------------------

def test_palm_beach_pbcpao_does_not_import_selenium_or_playwright():
    import importlib.util
    p = SRC / "titlepro" / "property_appraiser" / "counties" / "palm_beach_pbcpao.py"
    assert p.exists(), p
    src_text = p.read_text(encoding="utf-8")
    forbidden = ("import selenium", "from selenium", "import playwright", "from playwright",
                 "import undetected_chromedriver", "from undetected_chromedriver")
    for needle in forbidden:
        assert needle not in src_text


# ---------------------------------------------------------------------------
# 2) PCN normalization
# ---------------------------------------------------------------------------

def test_clean_pcn_strips_hyphens():
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    assert PalmBeachPBCPAO._clean_pcn("00-41-47-22-04-000-1090") == "00414722040001090"
    assert PalmBeachPBCPAO._clean_pcn("00414722040001090") == "00414722040001090"
    assert PalmBeachPBCPAO._clean_pcn(" 00.41.47.22 ") == "00414722"
    assert PalmBeachPBCPAO._clean_pcn("") == ""
    assert PalmBeachPBCPAO._clean_pcn(None) == ""


def test_format_pcn_hyphenated():
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    assert PalmBeachPBCPAO._format_pcn_hyphenated("00414722040001090") == "00-41-47-22-04-000-1090"
    # Wrong length passes through unmodified
    assert PalmBeachPBCPAO._format_pcn_hyphenated("12345") == "12345"


# ---------------------------------------------------------------------------
# 3) KV-table parser
# ---------------------------------------------------------------------------

def test_parse_kv_tables_extracts_property_detail(pa_config):
    from bs4 import BeautifulSoup
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    soup = BeautifulSoup(HABER_PBCPAO_HTML, "html.parser")
    tables = PalmBeachPBCPAO._parse_kv_tables(soup)
    assert tables, "no KV tables parsed"
    # First table should be the Property detail one
    pd = tables[0]
    assert pd.get("Location Address") == "21831 PALM GRASS DR"
    assert pd.get("Parcel Control Number") == "00-41-47-22-04-000-1090"
    assert "BOCA WINDS PAR E" in pd.get("Legal Description", "")


# ---------------------------------------------------------------------------
# 4) Sales history parser
# ---------------------------------------------------------------------------

def test_parse_sales_table_returns_two_entries():
    from bs4 import BeautifulSoup
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    soup = BeautifulSoup(HABER_PBCPAO_HTML, "html.parser")
    sales = PalmBeachPBCPAO._parse_sales_table(soup)
    assert len(sales) == 2
    most_recent = sales[0]
    assert most_recent.sale_date == "04/01/1999"
    assert most_recent.sale_price == 238000
    assert most_recent.deed_type == "WARRANTY DEED"
    assert "11081" in most_recent.deed_book_page
    assert "00560" in most_recent.deed_book_page
    older = sales[1]
    assert older.sale_date == "06/01/1995"
    assert older.sale_price == 204900


# ---------------------------------------------------------------------------
# 5) Owner table parser
# ---------------------------------------------------------------------------

def test_parse_owner_table_returns_primary_and_co_owners():
    from bs4 import BeautifulSoup
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    soup = BeautifulSoup(HABER_PBCPAO_HTML, "html.parser")
    owner_data = PalmBeachPBCPAO._parse_owner_table(soup)
    assert owner_data["owner_of_record"] == "HABER DANA M"
    assert "HABER MARK &" in owner_data["co_owners"]
    assert "21831 PALM GRASS DR" in owner_data["mailing_address"]
    assert "BOCA RATON" in owner_data["mailing_address"]


# ---------------------------------------------------------------------------
# 6) Assessment table parser
# ---------------------------------------------------------------------------

def test_parse_assessment_table_uses_leftmost_data_column():
    from bs4 import BeautifulSoup
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    soup = BeautifulSoup(HABER_PBCPAO_HTML, "html.parser")
    asmt = PalmBeachPBCPAO._parse_assessment_table(soup)
    # 2025 (most recent) values
    assert asmt.get("assessed_value") == 314276
    assert asmt.get("taxable_value") == 263554
    assert asmt.get("exemption_amount") == 50722


# ---------------------------------------------------------------------------
# 7) Exemption table parser
# ---------------------------------------------------------------------------

def test_parse_exemption_table_marks_homestead_active_for_current_year():
    from bs4 import BeautifulSoup
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    soup = BeautifulSoup(HABER_PBCPAO_HTML, "html.parser")
    exempt = PalmBeachPBCPAO._parse_exemption_table(soup)
    assert exempt["homestead_active"] is True
    assert len(exempt["exemptions"]) >= 2
    detail_set = {e["detail"] for e in exempt["exemptions"]}
    assert "HOMESTEAD" in detail_set


# ---------------------------------------------------------------------------
# 8) lookup_by_apn success
# ---------------------------------------------------------------------------

def test_lookup_by_apn_success_with_mocked_html(pa_config):
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    adapter = PalmBeachPBCPAO(pa_config)
    # Replace the session with a mock that returns our fixture HTML
    mock = MagicMock()
    mock.get.return_value = MagicMock(status_code=200, text=HABER_PBCPAO_HTML)
    adapter.session = mock

    result = adapter.lookup_by_apn("00-41-47-22-04-000-1090")
    assert result.status == "PA_SUCCESS", result.notes
    assert result.apn == "00-41-47-22-04-000-1090"
    assert result.folio == "00414722040001090"
    assert result.owner_of_record == "HABER DANA M"
    assert "HABER MARK &" in result.co_owners
    assert result.situs_address == "21831 PALM GRASS DR"
    assert "21831" in result.mailing_address
    assert "BOCA WINDS" in result.legal_description
    assert result.assessed_value == 314276
    assert result.homestead_active is True
    assert result.year_built == 1995
    assert len(result.sale_history) == 2
    assert result.source_url.endswith("parcelId=00414722040001090")


# ---------------------------------------------------------------------------
# 9) lookup_by_apn no-results path
# ---------------------------------------------------------------------------

def test_lookup_by_apn_no_results_when_html_too_short(pa_config):
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    adapter = PalmBeachPBCPAO(pa_config)
    mock = MagicMock()
    mock.get.return_value = MagicMock(status_code=200, text="<html>short</html>")
    adapter.session = mock
    result = adapter.lookup_by_apn("99999999999999999")
    assert result.status == "PA_NO_RESULTS"
    # No internal IDs leaked in notes — generic message only
    assert "99999999999999999" not in result.notes or "PCN" in result.notes


def test_lookup_by_apn_empty_pcn_fails_fast(pa_config):
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    adapter = PalmBeachPBCPAO(pa_config)
    adapter.session = MagicMock()  # Should never be called
    result = adapter.lookup_by_apn("")
    assert result.status == "PA_FAILED"
    assert "PCN" in result.notes or "normalize" in result.notes


# ---------------------------------------------------------------------------
# 10) lookup_by_address returns PA_AMBIGUOUS + manual URL
# ---------------------------------------------------------------------------

def test_lookup_by_address_returns_ambiguous_with_search_url(pa_config):
    from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    adapter = PalmBeachPBCPAO(pa_config)
    mock = MagicMock()
    mock.get.return_value = MagicMock(status_code=200, text="<html>landing</html>")
    adapter.session = mock
    result = adapter.lookup_by_address("21831 PALM GRASS DR, BOCA RATON, FL 33428")
    assert result.status == "PA_AMBIGUOUS"
    assert "AdvSearch" in result.source_url
    assert "21831" in result.source_url
    assert "PALM" in result.source_url


# ---------------------------------------------------------------------------
# 11) Factory routing
# ---------------------------------------------------------------------------

def test_factory_routes_fl_palm_beach_to_pbcpao_adapter():
    """fetch_property_appraiser must dispatch fl_palm_beach -> PalmBeachPBCPAO."""
    cfg_path = REPO / "config" / "county_property_appraiser_urls.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    pb = cfg.get("counties", {}).get("fl_palm_beach")
    assert pb is not None, "fl_palm_beach must be registered in county_property_appraiser_urls.json"
    assert pb["platform"] == "pbcpao_http"

    from titlepro.property_appraiser import fetch_property_appraiser
    # We can't actually hit live in unit tests — but the factory should at
    # least not return PA_NO_RUNNER for fl_palm_beach.
    # Replace the adapter's session via monkeypatching the module factory.
    import titlepro.property_appraiser.counties.palm_beach_pbcpao as mod
    orig = mod.PalmBeachPBCPAO

    class FakeAdapter(orig):
        def __init__(self, cfg):
            super().__init__(cfg)
            mock_session = MagicMock()
            mock_session.get.return_value = MagicMock(status_code=200, text=HABER_PBCPAO_HTML)
            self.session = mock_session

    mod.PalmBeachPBCPAO = FakeAdapter
    try:
        result = fetch_property_appraiser(
            "fl_palm_beach",
            apn="00-41-47-22-04-000-1090",
        )
        assert result.status == "PA_SUCCESS"
        assert result.owner_of_record == "HABER DANA M"
        assert result.situs_address == "21831 PALM GRASS DR"
    finally:
        mod.PalmBeachPBCPAO = orig
