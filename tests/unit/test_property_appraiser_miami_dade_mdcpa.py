"""Unit tests for the Miami-Dade MDCPA Property Appraiser adapter.

LIVE-VALIDATED 2026-06-17 (US egress). Fixtures in
``tests/unit/fixtures/miami_dade/`` are REAL captured responses from the public
MDCPA proxy at ``apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx``
(see ``docs/FL/source/miami_dade_pa_probe.md``):

  * govctr      — 111 NW 1 ST, folio 01-4137-023-0020 (Stephen P. Clark Govt
                  Center — county-owned, multi-building, no sales)
  * residential — 7500 SW 82 ST G105, folio 30-4035-047-2550 (Village at
                  Dadeland condo — Rodriguez homestead, 2 qualified sales)

All tests are parse-only — no live HTTP (sessions are mocked). This mirrors the
BCPA test style; the proxy itself has no anti-bot, but tests must stay offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.property_appraiser import (  # noqa: E402
    PropertyAppraiserResult,
    SaleHistoryEntry,
    fetch_property_appraiser,
)
from titlepro.property_appraiser.counties.miami_dade_mdcpa import (  # noqa: E402
    MiamiDadeMDCPA,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "miami_dade"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mdcpa_config() -> Dict[str, Any]:
    return {
        "platform": "mdcpa_http",
        "base_url": "https://apps.miamidadepa.gov/",
        "county_id": "fl_miami_dade",
        "county_name": "Miami-Dade",
        "referer": "https://apps.miamidadepa.gov/PropertySearch/",
        "impersonate": "chrome120",
        "captcha": False,
    }


def _load(name: str) -> Any:
    return json.loads((FIX / name).read_text())


def _make_response(status_code: int, payload: Any):
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(payload, (dict, list)):
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = str(payload)
    return resp


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("10630 SW 128TH TERRACE, MIAMI, FL", "10630 SW 128 TERRACE"),
        ("111 NW 1st St, Miami", "111 NW 1 ST"),
        ("7500 SW 82 ST G105", "7500 SW 82 ST G105"),
        ("  5 NW  2nd  Ave  ", "5 NW 2 AVE"),
    ],
)
def test_normalize_address_strips_suffixes_and_city(input_addr, expected):
    assert MiamiDadeMDCPA._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("30-4035-047-2550", "3040350472550"),
        ("3040350472550", "3040350472550"),
        ("01-4137-023-0020", "0141370230020"),
        ("  01 4137 023 0020  ", "0141370230020"),
        ("", ""),
    ],
)
def test_normalize_folio(input_apn, expected):
    assert MiamiDadeMDCPA._normalize_folio(input_apn) == expected


@pytest.mark.parametrize(
    "digits,expected",
    [
        ("3040350472550", "30-4035-047-2550"),
        ("0141370230020", "01-4137-023-0020"),
        ("123", "123"),  # not 13 digits → returned as-is
    ],
)
def test_format_folio_display(digits, expected):
    assert MiamiDadeMDCPA._format_folio_display(digits) == expected


# ---------------------------------------------------------------------------
# Parse parcel — REAL residential fixture (two owners, two sales, homestead)
# ---------------------------------------------------------------------------


def test_lookup_by_apn_residential_parses_real_parcel(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("folio_residential_condo.json")
    )

    result = adapter.lookup_by_apn("30-4035-047-2550")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "3040350472550"
    assert result.apn == "30-4035-047-2550"
    assert result.owner_of_record == "AGATONIA RODRIGUEZ &H"
    assert result.co_owners == ["LUIS CANRE"]
    assert result.situs_address.startswith("7500 SW 82 ST G105")
    assert "VILLAGE AT DADELAND CONDO" in result.legal_description
    assert result.just_value == 158223       # Assessment.TotalValue (2025)
    assert result.assessed_value == 59181     # Assessment.AssessedValue
    assert result.year_built == 1968
    assert result.living_area_sqft == 730
    assert result.homestead_active is True    # Benefit: Exemption/Homestead
    assert result.source_url.endswith("3040350472550")


def test_residential_sale_history_is_newest_first(mdcpa_config):
    """SalesInfos arrives oldest-first (SaleId 1 == newest); adapter flips it."""
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("folio_residential_condo.json")
    )

    result = adapter.lookup_by_apn("3040350472550")

    assert len(result.sale_history) == 2
    s0, s1 = result.sale_history
    # Newest (SaleId 1) first:
    assert s0.sale_date == "5/1/2005"
    assert s0.sale_price == 187900
    assert s0.deed_book_page == "23430 / 4362"
    assert s0.deed_doc_number == ""          # SaleInstrument empty for this sale
    assert s0.qualified is True              # QualifiedFlag "Q"
    assert s0.deed_type == ""                # MDCPA never supplies deed type
    # Older (SaleId 2):
    assert s1.sale_date == "5/1/2004"
    assert s1.deed_book_page == "22346 / 1245"


def test_deed_identifiers_from_real_book_pages(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("folio_residential_condo.json")
    )
    result = adapter.lookup_by_apn("3040350472550")
    ids = result.deed_identifiers()
    assert ids[0] == "23430/4362"   # newest book/page, whitespace-stripped
    assert ids[1] == "22346/1245"


# ---------------------------------------------------------------------------
# Parse parcel — REAL county-owned fixture (multi-building, no sales)
# ---------------------------------------------------------------------------


def test_lookup_by_apn_govctr_county_owned_no_sales(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("folio_govctr.json")
    )

    result = adapter.lookup_by_apn("01-4137-023-0020")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "0141370230020"
    assert result.owner_of_record == "MIAMI-DADE COUNTY"
    assert result.co_owners == ["GSA R/E MGMT-DGC"]
    assert result.situs_address.startswith("111 NW 1 ST")
    assert "DOWNTOWN GOVERNMENT CENTER" in result.legal_description
    assert result.just_value == 102900000
    assert result.homestead_active is False
    # Non-numeric YearBuilt ("Multiple (See Building Info.)") + (-1 heated area)
    # both map cleanly to 0 rather than crashing/garbage:
    assert result.year_built == 0
    assert result.living_area_sqft == 0
    assert result.sale_history == []


# ---------------------------------------------------------------------------
# Address lookup — REAL GetAddress fixtures
# ---------------------------------------------------------------------------


def test_lookup_by_address_govctr_full_two_call_flow(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, _load("getaddress_govctr.json")),  # GetAddress (1 row)
        _make_response(200, _load("folio_govctr.json")),       # GetPropertySearchByFolio
    ]

    result = adapter.lookup_by_address("111 NW 1 ST, Miami, FL")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "0141370230020"
    assert adapter.session.get.call_count == 2
    # Confirm the two calls used the right Operation param against the proxy.
    ops = [c.kwargs["params"]["Operation"] for c in adapter.session.get.call_args_list]
    assert ops == ["GetAddress", "GetPropertySearchByFolio"]


def test_extract_address_candidates_real_govctr_single_row():
    cands = MiamiDadeMDCPA._extract_address_candidates(_load("getaddress_govctr.json"))
    assert len(cands) == 1
    assert cands[0]["folio"] == "0141370230020"   # from Strap, hyphens stripped
    assert cands[0]["address"] == "111 NW 1 ST"


def test_lookup_by_address_multiunit_building_is_ambiguous(mdcpa_config):
    """The residential GetAddress fixture is a 12-unit condo building — a bare
    street query (no unit) must surface PA_AMBIGUOUS, not silently pick a unit."""
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("getaddress_residential.json")
    )
    result = adapter.lookup_by_address("7500 SW 82 ST, Miami, FL")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()
    # only the GetAddress call happened — no folio fetch on an ambiguous match.
    assert adapter.session.get.call_count == 1


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_address_no_results_returns_pa_no_results(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, {"Completed": True, "MinimumPropertyInfos": [], "Total": 0}
    )
    result = adapter.lookup_by_address("999 NOWHERE LN, MIAMI, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_apn_500_returns_pa_failed(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(500, {"Message": "boom"})
    result = adapter.lookup_by_apn("3040350472550")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_empty_input_returns_pa_failed(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    result = adapter.lookup_by_apn("ABC---")
    assert result.status == "PA_FAILED"
    assert "empty/invalid folio" in result.notes


def test_parse_parcel_empty_payload_returns_no_results(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    result = adapter.parse_parcel(
        {"Completed": True, "PropertyInfo": None, "OwnerInfos": []},
        folio_hint="3040350472550",
    )
    assert result.status == "PA_NO_RESULTS"
    assert result.folio == "3040350472550"
    assert result.apn == "30-4035-047-2550"


def test_lookup_by_apn_malformed_non_json_returns_pa_failed(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, "<html>not json</html>")
    result = adapter.lookup_by_apn("3040350472550")
    assert result.status == "PA_FAILED"


def test_lookup_by_owner_name_returns_empty_list(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    assert adapter.lookup_by_owner_name("NAVAS, LUIS H") == []


# ---------------------------------------------------------------------------
# Dispatcher / factory + serialization
# ---------------------------------------------------------------------------


def test_fetch_property_appraiser_routes_miami_dade(monkeypatch):
    """The factory should dispatch fl_miami_dade to MiamiDadeMDCPA."""
    captured: Dict[str, Any] = {}

    def fake_apn(self, apn):
        captured["apn"] = apn
        return PropertyAppraiserResult(status="PA_SUCCESS", apn=apn)

    monkeypatch.setattr(MiamiDadeMDCPA, "lookup_by_apn", fake_apn)
    res = fetch_property_appraiser("fl_miami_dade", apn="3040350472550")
    assert res.status == "PA_SUCCESS"
    assert captured["apn"] == "3040350472550"


def test_to_dict_roundtrip_preserves_real_sale_history(mdcpa_config):
    adapter = MiamiDadeMDCPA(mdcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(
        200, _load("folio_residential_condo.json")
    )
    result = adapter.lookup_by_apn("3040350472550")
    d = result.to_dict()
    assert d["folio"] == "3040350472550"
    assert d["sale_history"][0]["deed_book_page"] == "23430 / 4362"
    assert isinstance(result.sale_history[0], SaleHistoryEntry)
