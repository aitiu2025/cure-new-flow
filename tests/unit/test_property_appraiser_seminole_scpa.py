"""Unit tests for the Seminole County SCPA Property Appraiser adapter.

Mocked sessions only -- no live SCPA traffic. Live data API unreachable during the
2026-06-10 Wave-1 probe (scpafl.org geo-blocks the build env); canned ArcGIS fixtures
mirror the confirmed SCPA parcel-detail field set + a typical FL parcel FeatureServer.
See src/titlepro/api/downloaded_doc/0610/Seminole_PORTILLA_v1/phase0_probe_pa.md.
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

from titlepro.property_appraiser.result import (  # noqa: E402
    PropertyAppraiserResult,
    SaleHistoryEntry,
)
from titlepro.property_appraiser.counties.seminole_scpa import (  # noqa: E402
    SeminoleSCPA,
    _homestead_active,
)

NORM_APN = "0121295LM00000510"


@pytest.fixture
def scpa_config() -> Dict[str, Any]:
    return {
        "county_id": "fl_seminole",
        "county_name": "Seminole",
        "description": "Seminole County Property Appraiser",
        "arcgis_query_url": "https://services.arcgis.com/EXAMPLE/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "impersonate": "safari17_2_ios",
    }


def _resp(status_code: int, payload: Any):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload
    r.text = str(payload)
    return r


PORTILLA_FEATURE = {
    "features": [
        {
            "attributes": {
                "PARCEL": "01-21-29-5LM-0000-0510",
                "OWNER": "PORTILLA MARK J & ANGELA M",
                "OWNER2": "",
                "SITE_ADDR": "3136 SPLENDID STOWE LANE",
                "SITE_CITY": "LONGWOOD",
                "SITE_ZIP": "32779",
                "MAIL_ADDR": "3136 SPLENDID STOWE LANE",
                "MAIL_ADDR2": "LONGWOOD, FL 32779",
                "LEGAL": "LOT 51 RESERVE AT ALAQUA PB 62 PGS 1-5",
                "JUST": 845000,
                "ASSESSED": 612300,
                "HOMESTEAD": "Y",
                "YEAR_BUILT": 2001,
                "LIVING_AREA": 4123,
                "DOR_UC": "0100",
                "SALE_DATE1": "06/15/2018",
                "SALE_PRICE1": 720000,
                "OR_BOOK1": "09112",
                "OR_PAGE1": "0455",
                "DEED_TYPE1": "WD",
                "QUAL1": "Q",
                "SALE_DATE2": "03/02/2009",
                "SALE_PRICE2": 540000,
                "OR_BOOK2": "07154",
                "OR_PAGE2": "1330",
                "DEED_TYPE2": "WD",
                "QUAL2": "U",
            }
        }
    ]
}

AMBIGUOUS = {
    "features": [
        {"attributes": {"PARCEL": "AAA", "SITE_ADDR": "100 MAIN ST"}},
        {"attributes": {"PARCEL": "BBB", "SITE_ADDR": "100 MAIN ST APT 2"}},
    ]
}

EMPTY = {"features": []}


def test_normalize_apn_preserves_letters(scpa_config):
    a = SeminoleSCPA(scpa_config)
    assert a.normalize_apn("34-21-32-300-0050-0000") == "34213230000500000"
    assert a.normalize_apn("26 2030 5AR0D 00003A") == "2620305AR0D00003A"
    assert a.normalize_apn("") == ""


def test_normalize_address_strips_city_and_ordinals(scpa_config):
    a = SeminoleSCPA(scpa_config)
    assert (
        a.normalize_address_for_lookup("3136 Splendid Stowe Lane, Longwood, FL 32779")
        == "3136 SPLENDID STOWE LN"
    )
    assert a.normalize_address_for_lookup("215 NE 27th St, Sanford") == "215 NE 27 ST"


def test_lookup_by_address_success_parses_parcel(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, PORTILLA_FEATURE)
    res = a.lookup_by_address("3136 Splendid Stowe Lane, Longwood, FL 32779")
    assert isinstance(res, PropertyAppraiserResult)
    assert res.status == "PA_SUCCESS"
    assert res.apn == NORM_APN
    assert res.owner_of_record == "PORTILLA MARK J & ANGELA M"
    assert "3136 SPLENDID STOWE LANE" in res.situs_address
    assert "LONGWOOD" in res.situs_address
    assert res.just_value == 845000
    assert res.assessed_value == 612300
    assert res.homestead_active is True
    assert res.year_built == 2001
    assert res.living_area_sqft == 4123
    assert "RESERVE AT ALAQUA" in res.legal_description
    assert res.source_url.endswith("?PID=" + NORM_APN)


def test_apn_normalized_on_parse(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, PORTILLA_FEATURE)
    res = a.lookup_by_address("3136 Splendid Stowe Lane")
    assert res.apn == NORM_APN


def test_sale_history_newest_first_and_book_page(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, PORTILLA_FEATURE)
    res = a.lookup_by_address("3136 Splendid Stowe Lane")
    assert len(res.sale_history) == 2
    s0 = res.sale_history[0]
    assert isinstance(s0, SaleHistoryEntry)
    assert s0.sale_date == "06/15/2018"
    assert s0.sale_price == 720000
    assert s0.deed_type == "WD"
    assert s0.deed_book_page == "09112 / 0455"
    assert s0.qualified is True
    assert res.sale_history[1].sale_date == "03/02/2009"
    assert res.sale_history[1].qualified is False
    assert "09112/0455" in res.deed_identifiers()


def test_lookup_by_apn_uses_equality_clause(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, PORTILLA_FEATURE)
    res = a.lookup_by_apn("01-21-29-5LM-0000-0510")
    assert res.status == "PA_SUCCESS"
    where = a.session.get.call_args.kwargs["params"]["where"]
    assert "=" in where
    assert NORM_APN in where


def test_no_results_returns_pa_no_results(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, EMPTY)
    res = a.lookup_by_address("9999 Nowhere Rd")
    assert res.status == "PA_NO_RESULTS"


def test_ambiguous_returns_pa_ambiguous(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, AMBIGUOUS)
    res = a.lookup_by_address("100 Main St")
    assert res.status == "PA_AMBIGUOUS"
    assert "AAA" in res.notes and "BBB" in res.notes


def test_http_error_fails_soft(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    a.session.get.return_value = _resp(500, "boom")
    res = a.lookup_by_apn("01-21-29-5LM-0000-0510")
    assert res.status == "PA_FAILED"
    assert "500" in res.notes


def test_missing_arcgis_url_fails_soft(scpa_config):
    cfg = dict(scpa_config)
    cfg["arcgis_query_url"] = ""
    a = SeminoleSCPA(cfg)
    res = a.lookup_by_address("3136 Splendid Stowe Lane")
    assert res.status == "PA_FAILED"
    assert "arcgis_query_url not configured" in res.notes


def test_epoch_ms_sale_date_normalized(scpa_config):
    a = SeminoleSCPA(scpa_config)
    a.session = MagicMock()
    feature = {
        "features": [
            {
                "attributes": {
                    "PARCEL": "X1",
                    "OWNER": "DOE JOHN",
                    "SITE_ADDR": "1 A ST",
                    "SALE_DATE1": 1529020800000,
                    "SALE_PRICE1": 100,
                    "OR_BOOK1": "1",
                    "OR_PAGE1": "2",
                }
            }
        ]
    }
    a.session.get.return_value = _resp(200, feature)
    res = a.lookup_by_apn("X1")
    assert res.sale_history[0].sale_date == "06/15/2018"


def test_field_map_alias_normalization(scpa_config):
    a = SeminoleSCPA(dict(scpa_config))
    a.session = MagicMock()
    feature = {
        "features": [
            {
                "attributes": {
                    "Parcel_Id": "55-66",
                    "owner_name": "SMITH JANE",
                    "Situs": "42 ELM AVE",
                    "Just_Value": "$1,250,000",
                }
            }
        ]
    }
    a.session.get.return_value = _resp(200, feature)
    res = a.lookup_by_apn("5566")
    assert res.owner_of_record == "SMITH JANE"
    assert res.situs_address.startswith("42 ELM AVE")
    assert res.just_value == 1250000


def test_homestead_flag_variants(scpa_config):
    assert _homestead_active("Y") is True
    assert _homestead_active("YES") is True
    assert _homestead_active(50000) is True
    assert _homestead_active("N") is False
    assert _homestead_active("No Homestead") is False
    assert _homestead_active(None) is False
