"""Unit tests for the Brevard BCPAO Property Appraiser adapter.

Mocked sessions — no live BCPAO traffic (bcpao.us is Cloudflare-blocked; see
phase0_probe_pa.md in the Brevard_LEWIS_v1 case dir). Fixtures reflect the
documented BCPAO REST v1 JSON contract (clean top-level JSON, no {"d":...}).

Staged in the case dir because Write to tests/unit was permission-denied this
session; copy to tests/unit/test_brevard_bcpao.py to run alongside the suite.
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

from titlepro.property_appraiser.counties.brevard_bcpao import BrevardBCPAO  # noqa: E402


@pytest.fixture
def bcpao_config() -> Dict[str, Any]:
    return {
        "platform": "bcpao_http",
        "base_url": "https://www.bcpao.us/api/v1/",
        "warmup_url": "https://www.bcpao.us/PropertySearch/",
        "endpoints": {
            "search": "https://www.bcpao.us/api/v1/search",
            "account": "https://www.bcpao.us/api/v1/account",
        },
        "captcha": False,
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


# --- BCPAO-shaped canned responses (LEWIS subject) ----------------------------

LEWIS_SEARCH = [
    {
        "account": "2840928",
        "parcelID": "29-36-12-KK-1633-16",
        "siteAddress": "977 HAMMACHER AVE SW",
        "owners": [{"name": "LEWIS, ANGELA D"}],
    },
    {
        "account": "9999999",
        "parcelID": "29-36-12-KK-9999-99",
        "siteAddress": "979 HAMMACHER AVE SW",
        "owners": [{"name": "SOMEONE ELSE"}],
    },
]

LEWIS_ACCOUNT = {
    "account": "2840928",
    "parcelID": "29-36-12-KK-1633-16",
    "owners": [{"name": "LEWIS, ANGELA D"}],
    "siteAddress": "977 HAMMACHER AVE SW",
    "mailingAddress": {
        "addressLine1": "977 HAMMACHER AVE SW",
        "cityStateZip": "PALM BAY, FL 32908",
    },
    "legalDescription": "PORT MALABAR UNIT 32 LOT 16 BLK 1633",
    "yearBuilt": "2004",
    "totalLivingArea": "1850",
    "valueSummary": [
        {"marketValue": "$285,400", "assessedValue": "$210,330"},
        {"marketValue": "$250,000", "assessedValue": "$200,000"},
    ],
    "exemptions": [{"description": "HOMESTEAD EXEMPTION", "amount": "$25,000"}],
    "salesList": [
        {
            "saleDate": "12/26/1995",
            "price": "$66,500",
            "deedType": "WD",
            "book": "3563",
            "page": "2270",
            "orInstrument": "1996067410",
            "qualification": "Qualified",
        },
        {
            "saleDate": "05/10/1990",
            "price": "$12,000",
            "deedType": "WD",
            "book": "3100",
            "page": "0455",
            "orInstrument": "",
            "qualification": "Unqualified",
        },
    ],
}


# --- address normalization ----------------------------------------------------


@pytest.mark.parametrize(
    "input_addr,expected",
    [
        ("977 Hammacher Avenue SW, Palm Bay, FL 32908", "977 HAMMACHER AVE SW"),
        ("  977  Hammacher  Ave  SW  ", "977 HAMMACHER AVE SW"),
        ("123 Main Street, Melbourne, FL", "123 MAIN ST"),
    ],
)
def test_normalize_address(input_addr, expected):
    assert BrevardBCPAO._normalize_address_for_lookup(input_addr) == expected


@pytest.mark.parametrize(
    "input_apn,expected",
    [
        ("2840928", "2840928"),
        ("28-40-928", "2840928"),
        ("  2840928  ", "2840928"),
        ("29-36-12-KK-1633-16", "29-36-12-KK-1633-16"),  # parcel-id form passes through
        ("", ""),
    ],
)
def test_normalize_apn(input_apn, expected):
    assert BrevardBCPAO._normalize_apn(input_apn) == expected


# --- happy path ---------------------------------------------------------------


def test_lookup_by_apn_parses_parcel_with_sale_history(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),            # warmup
        _make_response(200, LEWIS_ACCOUNT),  # account
    ]
    result = adapter.lookup_by_apn("2840928")

    assert result.status == "PA_SUCCESS"
    assert result.folio == "2840928"
    assert result.apn == "29-36-12-KK-1633-16"
    assert result.owner_of_record == "LEWIS, ANGELA D"
    assert "PORT MALABAR" in result.legal_description
    assert result.just_value == 285_400
    assert result.assessed_value == 210_330
    assert result.year_built == 2004
    assert result.living_area_sqft == 1850
    assert result.homestead_active is True
    assert result.homestead_amount == 25_000
    assert result.source_url.endswith("/2840928")
    assert len(result.sale_history) == 2


def test_sale_history_newest_first_with_instrument_and_bookpage(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(200, LEWIS_ACCOUNT),
    ]
    result = adapter.lookup_by_apn("2840928")
    s1, s2 = result.sale_history
    assert s1.sale_date == "12/26/1995"
    assert s1.deed_doc_number == "1996067410"
    assert s1.deed_book_page == "3563/2270"
    assert s1.deed_type == "WD"
    assert s1.sale_price == 66_500
    assert s1.qualified is True
    assert s2.sale_date == "05/10/1990"
    assert s2.qualified is False


def test_deed_identifiers_prefers_instrument(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(200, LEWIS_ACCOUNT),
    ]
    result = adapter.lookup_by_apn("2840928")
    ids = result.deed_identifiers()
    assert ids[0] == "1996067410"     # instrument wins
    assert ids[1] == "3100/0455"       # falls back to book/page when no instrument


def test_lookup_by_address_full_flow(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),            # warmup
        _make_response(200, LEWIS_SEARCH),  # search
        _make_response(200, LEWIS_ACCOUNT),  # account (chosen)
    ]
    result = adapter.lookup_by_address("977 Hammacher Avenue SW, Palm Bay, FL 32908")
    assert result.status == "PA_SUCCESS"
    assert result.folio == "2840928"
    got_urls = [c.args[0] for c in adapter.session.get.call_args_list]
    assert any(u.endswith("/search") for u in got_urls)
    assert any(u.endswith("/account/2840928") for u in got_urls)


def test_lookup_by_address_exact_match_chosen_over_others(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(200, LEWIS_SEARCH),  # two rows, 977 first
        _make_response(200, LEWIS_ACCOUNT),
    ]
    result = adapter.lookup_by_address("977 HAMMACHER AVE SW")
    assert result.status == "PA_SUCCESS"
    assert result.folio == "2840928"


# --- failure modes ------------------------------------------------------------


def test_lookup_by_address_no_results(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(200, []),
    ]
    result = adapter.lookup_by_address("999 NOWHERE LN")
    assert result.status == "PA_NO_RESULTS"


def test_lookup_by_address_ambiguous(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(200, [
            {"account": "111", "siteAddress": "200 OAK ST"},
            {"account": "222", "siteAddress": "201 OAK ST"},
        ]),
    ]
    result = adapter.lookup_by_address("100 PINE AVE")
    assert result.status == "PA_AMBIGUOUS"
    assert "candidates" in result.notes.lower()


def test_lookup_by_apn_cloudflare_403_returns_pa_failed_with_hint(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _make_response(200, ""),
        _make_response(403, "<html>Sorry, you have been blocked | Cloudflare</html>"),
    ]
    result = adapter.lookup_by_apn("2840928")
    assert result.status == "PA_FAILED"
    assert "cf_clearance" in result.notes.lower() or "cloudflare" in result.notes.lower()


def test_lookup_by_apn_empty_input(bcpao_config):
    adapter = BrevardBCPAO(bcpao_config)
    result = adapter.lookup_by_apn("---")
    assert result.status == "PA_FAILED"
    assert "empty/invalid APN" in result.notes


def test_cf_cookies_injected_into_session():
    cfg = {
        "base_url": "https://www.bcpao.us/api/v1/",
        "cf_cookies": {"cf_clearance": "abc123"},
    }
    adapter = BrevardBCPAO(cfg)
    sess = adapter.session
    assert adapter._cf_cookies.get("cf_clearance") == "abc123"
    assert sess is adapter.session  # cached
