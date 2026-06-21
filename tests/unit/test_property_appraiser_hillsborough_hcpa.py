"""Unit tests for the Hillsborough HCPA Property Appraiser adapter.

Tests use mocked sessions — no live HCPA traffic. Live shapes captured in
docs/FL/source/hillsborough_probe/ (probed 2026-05-26 against real FROMER +
DEL MONTE parcels) — the fixtures below mirror those payloads exactly so
parser changes are testable against the wire contract.

Endpoints probed:
  GET https://gis.hcpafl.org/CommonServices/property/search/BasicSearch
    ?address=4004 W NORTH B ST
    → list[parcel-summary]
  GET https://gis.hcpafl.org/CommonServices/property/search/ParcelData
    ?pin=1829213LS000012000040A
    → full parcel JSON with salesHistory[]
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
from titlepro.property_appraiser.counties.hillsborough_hcpa import (  # noqa: E402
    HillsboroughHCPA,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hcpa_config() -> Dict[str, Any]:
    return {
        "platform": "hcpa_http",
        "base_url": "https://gis.hcpafl.org/CommonServices/property/search/",
        "warmup_url": "https://gis.hcpafl.org/propertysearch/",
        "endpoints": {
            "autocomplete": "https://gis.hcpafl.org/CommonServices/property/search/Autocomplete",
            "basic_search": "https://gis.hcpafl.org/CommonServices/property/search/BasicSearch",
            "parcel_data": "https://gis.hcpafl.org/CommonServices/property/search/ParcelData",
        },
        "captcha": False,
        "impersonate": "chrome120",
    }


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


# Canned HCPA-shape responses captured byte-for-byte from
# docs/FL/source/hillsborough_probe/{08,10,09,11}_hcpa_*.json

FROMER_ADDRESS_SEARCH = [
    {
        "address": "4004 W NORTH B ST, TAMPA",
        "displayFolio": "115146-0000",
        "displayPin": "A-21-29-18-3LS-000012-00004.0",
        "folio": "1151460000",
        "homestead": "YES",
        "landUse": "0100",
        "owner": "FROMER MICHAEL A; FROMER ALANA; ",
        "pin": "1829213LS000012000040A",
        "saleDate": "2025-05-15",
        "salePrice": 100,
        "totalCount": 1,
    }
]

FROMER_PARCEL = {
    "pin": "1829213LS000012000040A",
    "owner": "FROMER MICHAEL A; FROMER ALANA; ",
    "siteAddress": "4004 W NORTH B ST, TAMPA",
    "fullLegal": ["ROSEDALE NORTH E 10 FT OF LOT 4 AND LOT 5 LESS E 10 FT BLOCK 12"],
    "mailingAddress": {
        "addr1": "4004 W NORTH B ST",
        "addr2": "",
        "city": "TAMPA",
        "country": "",
        "state": "FL",
        "zip": "33609-2736",
    },
    "buildings": [
        {
            "yearBuilt": 1954,
            "grossArea": 1307,
            "heatedArea": 1209,
            "bathrooms": 1.00,
            "bedrooms": 2.00,
        }
    ],
    "propertyCard": {
        "displayFolio": "115146-0000",
        "displayStrap": "A-21-29-18-3LS-000012-00004.0",
        "folio": "1151460000",
        "homestead": 46444,
        "legalDescription": "ROSEDALE NORTH E 10 FT OF LOT 4 AND LOT 5 LESS E 10 FT BLOCK 12",
    },
    "valueSummary": [
        {
            "assessedVal": 71444,
            "exemptions": 46444,
            "marketVal": 230679,
            "sequence": 4,
            "taxDist": "Other Districts",
            "taxableVal": 25000,
        },
        {
            "assessedVal": 71444,
            "exemptions": 46444,
            "marketVal": 230679,
            "sequence": 1,
            "taxDist": "County",
            "taxableVal": 25000,
        },
    ],
    "salesHistory": [
        {
            "book": None,
            "deedType": "QC  ",
            "docnum": "2025214758",
            "isConfidential": False,
            "page": None,
            "qualified": "Unqualified",
            "saleDate": "2025-05-15",
            "salePrice": 100,
            "sequence": 1,
            "vacOrImp": "Improved",
        },
        {
            "book": "2411",
            "deedType": "    ",
            "docnum": None,
            "isConfidential": False,
            "page": "0752",
            "qualified": "Unqualified",
            "saleDate": "1971-01-01",
            "salePrice": 100,
            "sequence": 2,
            "vacOrImp": None,
        },
    ],
}

DELMONTE_PARCEL = {
    "pin": "1828030UD000000000210U",
    "owner": "DEL MONTE ANGEL; DEL MONTE CHRISTINE; ",
    "siteAddress": "13519 WESTSHIRE DR, TAMPA",
    "fullLegal": ["TREVI AT BAY LAKE LOT 21"],
    "mailingAddress": {
        "addr1": "13519 WESTSHIRE DR",
        "city": "TAMPA",
        "state": "FL",
        "zip": "33618-2500",
    },
    "buildings": [{"yearBuilt": 1996, "heatedArea": 3068}],
    "propertyCard": {
        "displayFolio": "018884-0142",
        "displayStrap": "U-03-28-18-0UD-000000-00021.0",
        "folio": "0188840142",
        "homestead": 51411,
        "legalDescription": "TREVI AT BAY LAKE LOT 21",
    },
    "valueSummary": [
        {
            "assessedVal": 415526,
            "exemptions": 51411,
            "marketVal": 753750,
            "sequence": 1,
            "taxDist": "County",
            "taxableVal": 364115,
        }
    ],
    "salesHistory": [
        {
            "book": "7666",
            "deedType": "WD  ",
            "docnum": "95030837",
            "isConfidential": False,
            "page": "0358",
            "qualified": "Qualified",
            "saleDate": "1995-02-01",
            "salePrice": 50000,
            "sequence": 1,
            "vacOrImp": "Vacant",
        },
        {
            "book": "7450",
            "deedType": "WD  ",
            "docnum": "94171445",
            "isConfidential": False,
            "page": "1900",
            "qualified": "Unqualified",
            "saleDate": "1994-11-01",
            "salePrice": 410000,
            "sequence": 2,
            "vacOrImp": "Vacant",
        },
    ],
}


# ---------------------------------------------------------------------------
# Address + folio normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("4004 W North B St, Tampa, FL 33609", "4004 W NORTH B ST"),
        ("13519 Westshire Dr, Tampa, FL 33618-2500", "13519 WESTSHIRE DR"),
        ("100 1st Avenue, Tampa", "100 1 AVENUE"),
        ("  5 NW  2nd  Ave  ", "5 NW 2 AVE"),
        ("", ""),
    ],
)
def test_normalize_address_strips_suffixes_and_city(input_addr, expected):
    assert HillsboroughHCPA._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("115146-0000", "1151460000"),
        ("1151460000", "1151460000"),
        ("  018884-0142  ", "0188840142"),
        ("", ""),
        ("ABC---", ""),
    ],
)
def test_normalize_folio_strips_hyphens_and_whitespace(input_apn, expected):
    assert HillsboroughHCPA._normalize_folio(input_apn) == expected


def test_is_pin_detects_alphanumeric_strap():
    assert HillsboroughHCPA._is_pin("A-21-29-18-3LS-000012-00004.0") is True
    assert HillsboroughHCPA._is_pin("1829213LS000012000040A") is True


def test_is_pin_returns_false_for_pure_digits():
    assert HillsboroughHCPA._is_pin("1151460000") is False
    assert HillsboroughHCPA._is_pin("") is False


def test_normalize_pin_strips_dashes_and_dots():
    # Display PIN "A-21-29-18-3LS-000012-00004.0" → strip dashes + dots only.
    # Note: wire-format PIN per HCPA is "1829213LS000012000040A" (digits
    # rearranged); this normalizer is for display→submit conversion, not a
    # canonical mapping. Real lookups should use the PIN from BasicSearch
    # results directly.
    assert (
        HillsboroughHCPA._normalize_pin("A-21-29-18-3LS-000012-00004.0")
        == "A2129183LS000012000040"
    )


# ---------------------------------------------------------------------------
# Parse parcel — happy path (FROMER)
# ---------------------------------------------------------------------------


def test_lookup_by_address_fromer_full_two_call_flow(hcpa_config):
    """Address → BasicSearch?address → grab pin → ParcelData?pin."""
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up GET
        _make_response(200, FROMER_ADDRESS_SEARCH),  # BasicSearch
        _make_response(200, FROMER_PARCEL),  # ParcelData
    ]

    result = adapter.lookup_by_address("4004 W North B St, Tampa, FL 33609")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "1151460000"
    assert result.pin == "1829213LS000012000040A"
    assert result.owner_of_record == "FROMER MICHAEL A"
    assert result.co_owners == ["FROMER ALANA"]
    assert "ROSEDALE NORTH" in result.legal_description
    assert "BLOCK 12" in result.legal_description
    assert result.homestead_active is True
    assert result.homestead_amount == 46444
    assert result.year_built == 1954
    assert result.living_area_sqft == 1209
    assert result.just_value == 230679
    assert result.source_url.endswith("/Folio/1151460000")
    # Sale history: vesting QCD + 1971 WD chain root (the back-chain that
    # the recorder's 01/01/2010 digital-index window cannot reach).
    assert len(result.sale_history) == 2
    s_qcd, s_wd = result.sale_history
    assert s_qcd.sale_date == "05/15/2025"
    assert s_qcd.deed_doc_number == "2025214758"
    assert s_qcd.deed_book_page == ""
    assert s_qcd.deed_type == "QC"
    assert s_wd.sale_date == "01/01/1971"
    assert s_wd.deed_book_page == "2411 / 0752"  # chain-root BACK-CHAIN
    assert s_wd.deed_doc_number == ""


def test_lookup_by_apn_folio_round_trip(hcpa_config):
    """Folio (numeric) → BasicSearch?folio → grab pin → ParcelData."""
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(200, FROMER_ADDRESS_SEARCH),  # BasicSearch by folio
        _make_response(200, FROMER_PARCEL),  # ParcelData
    ]

    result = adapter.lookup_by_apn("115146-0000")

    assert result.status == "PA_SUCCESS"
    assert result.apn == "1151460000"
    assert result.pin == "1829213LS000012000040A"
    # Confirm the folio normalization happened — BasicSearch hit with bare digits.
    calls = adapter.session.get.call_args_list
    # First call is warmup; second is BasicSearch
    bs_call = calls[1]
    assert bs_call.args[0].endswith("BasicSearch")
    assert bs_call.kwargs["params"]["folio"] == "1151460000"


def test_lookup_by_apn_pin_bypasses_basic_search(hcpa_config):
    """PIN (alphanumeric) → ParcelData directly, no BasicSearch round-trip."""
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(200, FROMER_PARCEL),  # ParcelData
    ]

    result = adapter.lookup_by_apn("1829213LS000012000040A")

    assert result.status == "PA_SUCCESS"
    assert result.pin == "1829213LS000012000040A"
    # Confirm only one substantive API call (ParcelData), not BasicSearch.
    parcel_calls = [
        c for c in adapter.session.get.call_args_list if "ParcelData" in c.args[0]
    ]
    assert len(parcel_calls) == 1
    bs_calls = [
        c for c in adapter.session.get.call_args_list if "BasicSearch" in c.args[0]
    ]
    assert len(bs_calls) == 0


def test_delmonte_parcel_parses_two_sale_history_entries(hcpa_config):
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(200, DELMONTE_PARCEL),  # ParcelData
    ]

    result = adapter.lookup_by_apn("1828030UD000000000210U")  # PIN form

    assert result.status == "PA_SUCCESS"
    assert result.folio == "0188840142"
    assert result.owner_of_record == "DEL MONTE ANGEL"
    assert result.co_owners == ["DEL MONTE CHRISTINE"]
    assert "TREVI AT BAY LAKE" in result.legal_description
    assert len(result.sale_history) == 2
    s1, s2 = result.sale_history
    assert s1.deed_doc_number == "95030837"
    assert s1.deed_book_page == "7666 / 0358"
    assert s1.deed_type == "WD"
    assert s1.qualified is True
    assert s1.sale_price == 50000


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_address_no_results_returns_pa_no_results(hcpa_config):
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(200, []),  # empty BasicSearch
    ]
    result = adapter.lookup_by_address("999 NOWHERE LN, TAMPA")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_apn_500_returns_pa_failed(hcpa_config):
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(500, {"Message": "boom"}),
    ]
    result = adapter.lookup_by_apn("1151460000")
    assert result.status == "PA_FAILED"
    assert "HTTP 500" in result.notes


def test_lookup_by_apn_empty_input_returns_pa_failed(hcpa_config):
    adapter = HillsboroughHCPA(hcpa_config)
    result = adapter.lookup_by_apn("")
    assert result.status == "PA_FAILED"
    assert "empty/invalid APN" in result.notes


def test_lookup_by_address_ambiguous_returns_pa_ambiguous(hcpa_config):
    """Two candidates, neither an exact match against the normalized form."""
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(
            200,
            [
                {
                    "address": "100 MAIN PLAZA, TAMPA",
                    "folio": "111",
                    "pin": "PIN111",
                },
                {
                    "address": "100 MAIN COURT, TAMPA",
                    "folio": "222",
                    "pin": "PIN222",
                },
            ],
        ),
    ]
    result = adapter.lookup_by_address("100 MAIN STREET")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


def test_lookup_by_owner_name_empty_returns_empty_list(hcpa_config):
    adapter = HillsboroughHCPA(hcpa_config)
    assert adapter.lookup_by_owner_name("") == []
    assert adapter.lookup_by_owner_name("   ") == []


def test_deed_identifiers_returns_mix_of_docnum_and_bookpage(hcpa_config):
    """Ensures the back-chain Book/Page form (1971 WD) is recoverable from
    deed_identifiers() — the key cross-ref hook for reconciliation."""
    adapter = HillsboroughHCPA(hcpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),  # warm-up
        _make_response(200, FROMER_PARCEL),  # direct PIN lookup
    ]

    result = adapter.lookup_by_apn("1829213LS000012000040A")
    ids = result.deed_identifiers()
    assert ids[0] == "2025214758"  # modern docnum
    assert "2411" in ids[1] and "0752" in ids[1]  # 1971 book/page back-chain


# ---------------------------------------------------------------------------
# Dispatcher / factory
# ---------------------------------------------------------------------------


def test_fetch_property_appraiser_fl_hillsborough_route(monkeypatch):
    """The factory must route fl_hillsborough → HillsboroughHCPA."""
    captured = {}

    class _StubAdapter:
        def __init__(self, cfg):
            captured["cfg"] = cfg

        def lookup_by_apn(self, apn):
            captured["apn"] = apn
            return PropertyAppraiserResult(
                apn=apn, status="PA_SUCCESS", fetched_at="X"
            )

        def lookup_by_address(self, addr):
            captured["addr"] = addr
            return PropertyAppraiserResult(status="PA_SUCCESS", fetched_at="X")

    import titlepro.property_appraiser as pa_mod
    import titlepro.property_appraiser.counties.hillsborough_hcpa as hcpa_mod

    monkeypatch.setattr(hcpa_mod, "HillsboroughHCPA", _StubAdapter)

    result = fetch_property_appraiser(county_id="fl_hillsborough", apn="1151460000")
    assert result.status == "PA_SUCCESS"
    assert captured["apn"] == "1151460000"
    assert captured["cfg"]["platform"] == "hcpa_http"
