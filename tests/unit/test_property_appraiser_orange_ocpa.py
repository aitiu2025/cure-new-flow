"""Unit tests for the Orange County FL OCPA Property Appraiser adapter.

Tests use mocked sessions — no live OCPA traffic. Live shape is captured in
/tmp/ocpa_probe.md (probed 2026-05-26) and reflected in the fixture JSON below.

Live GREER subject:
  - subject: 17748 DEER ISLE CIR, WINTER GARDEN, FL 34787
  - pid: 272230202900330
  - canonical APN display: 27-22-30-2029-00-330
  - owner: GREER BRETT B / GREER DIANA V
  - vesting deed (pre-window): inst 20040398268 (QCD VALDIVIA → GREER, 06/09/2004)
  - prior deeds: inst 20020539736 (WD EVANS → VALDIVIA, 10/14/2002)
                 inst 19965559399 (WD IRRGANG → EVANS, 03/22/1996)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
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
from titlepro.property_appraiser.counties.orange_ocpa import OrangeOCPA  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ocpa_config() -> Dict[str, Any]:
    return {
        "platform": "ocpa_http",
        "base_url": "https://ocpa-mainsite-afd-standard.azurefd.net",
        "origin_url": "https://ocpaweb.ocpafl.org",
        "user_key": "a5250bb5-c321-4926-a966-9e907f560f31",
        "endpoints": {
            "search_by_address": "api/QuickSearch/GetSearchInfoByAddress",
            "search_by_parcel": "api/QuickSearch/GetSearchInfoByParcel",
            "general_info": "api/PRC/GetPRCGeneralInfo",
            "legal": "api/PRC/GetPRCPropFeatLegal",
            "sales": "api/PRC/GetPRCSales",
            "total_taxes": "api/PRC/GetPRCTotalTaxes",
            "certified_taxes": "api/PRC/GetPRCCertifiedTaxes",
            "non_ad_valorem": "api/PRC/GetPRCNonAdValorem",
            "property_values": "api/PRC/GetPRCPropertyValues",
            "location": "api/PRCLocation/GetPRCLocationInfo",
        },
        "impersonate": "chrome120",
    }


def _make_response(status_code: int, payload: Any):
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(payload, (dict, list)):
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    elif payload is None:
        resp.json.return_value = None
        resp.text = ""
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = str(payload)
    return resp


# OCPA-shape canned responses from the 2026-05-26 GREER live probe.

GREER_ADDR_SEARCH = [
    {
        "ownerName": " GREER BRETT B, GREER DIANA V",
        "propertyAddress": "17748 DEER ISLE CIR ",
        "isHomestead": "True",
        "parcelId": "272230202900330",
        "totalCount": 1,
    }
]

GREER_GENERAL = {
    "taxYear": 2026,
    "prcTaxYear": 2025,
    "trimYear": 2025,
    "showFlag": False,
    "parcelId": "272230202900330",
    "ownerName": " GREER BRETT B, GREER DIANA V",
    "propertyName": None,
    "propertyAddress": "17748 DEER ISLE CIR ",
    "mailAddress": "17748 Deer Isle Cir",
    "mailCity": "Winter Garden",
    "mailState": "FL",
    "mailZip": "34787-9421",
    "country": None,
    "propertyCity": "Winter Garden",
    "propertyState": "FL",
    "propertyZip": "34787",
    "dorCode": "0103",
    "dorDescription": "SINGLE FAM CLASS III",
    "cityDescription": "UN-INCORPORATED",
    "streetNumber": 17748,
    "streetName": "DEER ISLE",
    "instNum": "1992P029136",
}

GREER_LEGAL = {"propertyDescription": "DEER ISLAND PHASE 2 29/136 LOT 33"}

GREER_SALES = [
    {
        "saleDate": "2004-06-09T00:00:00",
        "saleAmt": 100,
        "instrNum": "20040398268",
        "book": "07497",
        "page": "1631",
        "seller": "VALDIVIA PEDRO, VALDIVIA MARTHA 1/2 INT",
        "buyer": "GREER BRETT B, GREER DIANA V",
        "deedDesc": "QUIT CLAIM DEED",
        "vacImpCode": "Vacant",
        "totalCount": 3,
    },
    {
        "saleDate": "2002-10-14T00:00:00",
        "saleAmt": 80000,
        "instrNum": "20020539736",
        "book": "06659",
        "page": "6126",
        "seller": "EVANS ROBERT, EVANS JULIE",
        "buyer": "VALDIVIA PEDRO, VALDIVIA MARTHA 1/2 INT",
        "deedDesc": "WARRANTY DEED",
        "vacImpCode": "Vacant",
        "totalCount": 3,
    },
    {
        "saleDate": "1996-03-22T00:00:00",
        "saleAmt": 59900,
        "instrNum": "19965559399",
        "book": "05032",
        "page": "4962",
        "seller": "IRRGANG PARTNERSHIP, ",
        "buyer": "EVANS ROBERT H, EVANS JULIE S",
        "deedDesc": "WARRANTY DEED",
        "vacImpCode": "Vacant",
        "totalCount": 3,
    },
]

GREER_TOTAL_TAXES = {
    "parcelId": "272230202900330",
    "taxYear": 2025,
    "totalMillageRate": "16.0858",
    "adValoremTaxes": "12653.37",
    "nonAdValoremTaxes": 400.0,
    "grossTaxes": 13053.37,
    "nonExemptTaxes": 19331.75,
}

GREER_CERTIFIED_TAXES = [
    {
        "parcelId": "272230202900330",
        "taxYear": 2025,
        "taxingAuthority": "General County",
        "assessedValue": 827027,
        "exemption": 50722,
        "taxValue": 776305,
        "millageRate": 4.4347,
        "isHomestead": "True",
        "taxes": 3442.6797,
        "taxType": "CTY",
    }
]

GREER_NON_AD_VALOREM = [
    {
        "parcelId": "272230202900330",
        "description": "WASTE PRO OF FL - GARBGE - (407)836-6601",
        "rate": 0,
        "assessment": 400.0,
        "levyingAuthority": "Orange County",
    }
]

GREER_PROPERTY_VALUES = [
    {
        "parcelId": "272230202900330",
        "taxYear": 2026,
        "landValue": -1,
        "buildingValue": -1,
        "featuresValue": 0,
        "marketValue": -1,
        "assessedValue": -1,
        "isCertified": False,
        "isHomestead": "True",
        "originalHx": -1,
        "additionalHx": -1,
        "otherExemptions": -1,
        "sohCap": -1,
        "hasBenefits": "1",
    }
]

GREER_LOCATION = {
    "community": {
        "parcelId": "272230202900330",
        "communityName": "Deer Island Homeowners' Association of Killarney, Inc.",
        "isGated": "Yes",
        "isMandatory": "True",
        "householdsCount": 109,
    }
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("17748 DEER ISLE CIR, WINTER GARDEN, FL 34787", "17748 DEER ISLE CIR"),
        ("7313 Twilight Bay Dr, Winter Garden, FL", "7313 TWILIGHT BAY DR"),
        ("1234 W 5TH ST", "1234 W 5 ST"),
        ("  100 1st Ave  ", "100 1 AVE"),
    ],
)
def test_normalize_address_strips_suffixes_and_city(input_addr, expected):
    assert OrangeOCPA._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("27-22-30-2029-00-330", "272230202900330"),
        ("272230202900330", "272230202900330"),
        ("  272230-202900-330  ", "272230202900330"),
        ("", ""),
        ("non-numeric-junk", ""),
    ],
)
def test_normalize_apn(input_apn, expected):
    assert OrangeOCPA._normalize_apn(input_apn) == expected


def test_format_canonical_apn_round_trips():
    pid = "272230202900330"
    display = OrangeOCPA._format_canonical_apn(pid)
    assert display == "27-22-30-2029-00-330"
    # Non-15-digit returns input unchanged
    assert OrangeOCPA._format_canonical_apn("abc") == "abc"
    assert OrangeOCPA._format_canonical_apn("1234") == "1234"


# ---------------------------------------------------------------------------
# Parse parcel — GREER happy path (all 7 endpoint fetches mocked)
# ---------------------------------------------------------------------------


def _setup_greer_apn_mocks(adapter: OrangeOCPA):
    """Wire the session.get to return the 7 PRC blocks in the order the
    adapter requests them: general, legal, sales, total_taxes, certified,
    non_ad_valorem, property_values, location.
    """
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, GREER_GENERAL),
        _make_response(200, GREER_LEGAL),
        _make_response(200, GREER_SALES),
        _make_response(200, GREER_TOTAL_TAXES),
        _make_response(200, GREER_CERTIFIED_TAXES),
        _make_response(200, GREER_NON_AD_VALOREM),
        _make_response(200, GREER_PROPERTY_VALUES),
        _make_response(200, GREER_LOCATION),
    ]


def test_lookup_by_apn_greer_returns_full_parcel_with_sale_history(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    _setup_greer_apn_mocks(adapter)

    result = adapter.lookup_by_apn("27-22-30-2029-00-330")

    assert result.status == "PA_SUCCESS"
    # Canonical APN format (hyphenated)
    assert result.apn == "27-22-30-2029-00-330"
    # Folio + PIN both carry the 15-digit numeric form
    assert result.folio == "272230202900330"
    assert result.pin == "272230202900330"
    # Owner of record + co-owner split
    assert result.owner_of_record == "GREER BRETT B"
    assert "GREER DIANA V" in result.co_owners
    # Situs (no leading/trailing whitespace, city/state/zip joined)
    assert result.situs_address.startswith("17748 DEER ISLE CIR")
    assert "Winter Garden" in result.situs_address
    assert "FL" in result.situs_address
    assert "34787" in result.situs_address
    # Legal description
    assert result.legal_description == "DEER ISLAND PHASE 2 29/136 LOT 33"
    # Homestead flag derived from certified taxes
    assert result.homestead_active is True
    # Source URL deep-links to the PRC tab
    assert "272230202900330" in result.source_url
    # Notes carry HOA + tax + non-ad-valorem summary
    assert "Deer Island Homeowners" in result.notes
    assert "gross=$13,053.37" in result.notes
    assert "WASTE PRO" in result.notes


def test_greer_sale_history_back_chain_is_three_deep_newest_first(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    _setup_greer_apn_mocks(adapter)

    result = adapter.lookup_by_apn("272230202900330")
    sh = result.sale_history
    assert len(sh) == 3

    # Newest entry = the vesting deed INTO GREER
    vesting = sh[0]
    assert vesting.sale_date == "06/09/2004"
    assert vesting.deed_doc_number == "20040398268"
    assert vesting.deed_book_page == "07497/1631"
    assert vesting.deed_type == "QUIT CLAIM DEED"
    assert "VALDIVIA" in vesting.grantor
    assert "GREER BRETT B" in vesting.grantee

    # Prior owner (Evans → Valdivia)
    prior = sh[1]
    assert prior.deed_doc_number == "20020539736"
    assert prior.sale_price == 80000
    assert "EVANS" in prior.grantor
    assert "VALDIVIA" in prior.grantee

    # Originating developer-out (Irrgang → Evans)
    original = sh[2]
    assert original.deed_doc_number == "19965559399"
    assert original.sale_date == "03/22/1996"


def test_greer_deed_identifiers_for_recorder_cross_check(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    _setup_greer_apn_mocks(adapter)

    result = adapter.lookup_by_apn("272230202900330")
    ids = result.deed_identifiers()
    # Should return the 3 instrument numbers (each entry has both
    # deed_doc_number and deed_book_page, doc_number wins per result.py).
    assert "20040398268" in ids
    assert "20020539736" in ids
    assert "19965559399" in ids


# ---------------------------------------------------------------------------
# Address lookup — orchestrates address-search + APN lookup
# ---------------------------------------------------------------------------


def test_lookup_by_address_greer_full_flow(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        # Step 1: address search returns the GREER row
        _make_response(200, GREER_ADDR_SEARCH),
        # Step 2: the 8 PRC blocks
        _make_response(200, GREER_GENERAL),
        _make_response(200, GREER_LEGAL),
        _make_response(200, GREER_SALES),
        _make_response(200, GREER_TOTAL_TAXES),
        _make_response(200, GREER_CERTIFIED_TAXES),
        _make_response(200, GREER_NON_AD_VALOREM),
        _make_response(200, GREER_PROPERTY_VALUES),
        _make_response(200, GREER_LOCATION),
    ]

    result = adapter.lookup_by_address(
        "17748 DEER ISLE CIR, WINTER GARDEN, FL 34787"
    )
    assert result.status == "PA_SUCCESS"
    assert result.folio == "272230202900330"
    # Both hit the address search and PRC stack
    assert adapter.session.get.call_count == 9


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_lookup_by_address_no_results_returns_pa_no_results(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, [])

    result = adapter.lookup_by_address("999 NOWHERE LN, ORLANDO, FL")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous_returns_pa_ambiguous(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    # Two candidates, neither matching the "100 MAIN" prefix exactly
    adapter.session = MagicMock()
    adapter.session.get.return_value = _make_response(200, [
        {"parcelId": "111111111111111", "propertyAddress": "200 OTHER ST"},
        {"parcelId": "222222222222222", "propertyAddress": "300 OTHER ST"},
    ])

    result = adapter.lookup_by_address("100 MAIN ST, ORLANDO, FL")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


def test_lookup_by_apn_empty_returns_pa_failed(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    adapter.session = MagicMock()

    result = adapter.lookup_by_apn("")
    assert result.status == "PA_FAILED"
    assert "invalid APN" in result.notes


def test_lookup_by_apn_general_500_returns_pa_failed(ocpa_config):
    adapter = OrangeOCPA(ocpa_config)
    adapter.session = MagicMock()
    err_resp = _make_response(500, "")
    err_resp.text = "Internal Server Error"
    adapter.session.get.return_value = err_resp

    result = adapter.lookup_by_apn("272230202900330")
    assert result.status == "PA_FAILED"
    assert "fetch error" in result.notes


# ---------------------------------------------------------------------------
# Factory integration — fl_orange routes to OrangeOCPA
# ---------------------------------------------------------------------------


def test_factory_fl_orange_returns_ocpa_adapter_no_runner_message_absent(monkeypatch):
    """Ensure config-driven routing picks the OCPA adapter for fl_orange and
    does NOT return PA_NO_RUNNER. We patch the adapter's constructor so we
    can detect that the OrangeOCPA path was selected without actually
    hitting the network.
    """
    from titlepro.property_appraiser import counties
    from titlepro.property_appraiser.counties import orange_ocpa as ocpa_mod

    sentinel = {"called_with": None}
    orig_cls = ocpa_mod.OrangeOCPA

    class _SentinelOCPA(orig_cls):
        def __init__(self, config):
            sentinel["called_with"] = config
            super().__init__(config)

        def lookup_by_apn(self, apn):
            return PropertyAppraiserResult(
                status="PA_SUCCESS",
                apn=apn,
                folio=OrangeOCPA._normalize_apn(apn),
                owner_of_record="(test owner)",
                legal_description="(test legal)",
                source_url="https://ocpaweb.ocpafl.org/test",
                fetched_at="2026-05-26T00:00:00",
            )

        def lookup_by_address(self, address):
            return self.lookup_by_apn("272230202900330")

    monkeypatch.setattr(ocpa_mod, "OrangeOCPA", _SentinelOCPA)

    result = fetch_property_appraiser(
        county_id="fl_orange",
        address="17748 DEER ISLE CIR, WINTER GARDEN, FL",
    )
    assert result.status == "PA_SUCCESS"
    assert result.status != "PA_NO_RUNNER"
    assert sentinel["called_with"] is not None
    assert sentinel["called_with"].get("platform") == "ocpa_http"


def test_owner_name_lookup_returns_empty_list_diagnostic_only(ocpa_config):
    """lookup_by_owner_name is documented as diagnostic-only; returns []."""
    adapter = OrangeOCPA(ocpa_config)
    assert adapter.lookup_by_owner_name("GREER BRETT") == []
    assert adapter.lookup_by_owner_name("") == []
