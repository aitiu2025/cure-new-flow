"""Unit tests for the Orange County FL OCPA tax adapter.

Pure-HTTP adapter at src/titlepro/tax/orange_ocpa_http.py. Mocks the
curl_cffi Session; live shape captured in /tmp/ocpa_probe.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.tax.orange_ocpa_http import (  # noqa: E402
    lookup_orange_ocpa_tax,
    _format_canonical_apn,
    _clean_apn,
    AUTHORITATIVE_HOSTS,
)
from titlepro.tax.result import TaxLookupResult  # noqa: E402


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


# Live GREER captures
GREER_PID = "272230202900330"
GREER_GENERAL = {
    "parcelId": GREER_PID,
    "ownerName": " GREER BRETT B, GREER DIANA V",
    "propertyAddress": "17748 DEER ISLE CIR ",
    "propertyCity": "Winter Garden",
    "propertyState": "FL",
    "propertyZip": "34787",
}
GREER_TOTAL = {
    "parcelId": GREER_PID,
    "taxYear": 2025,
    "totalMillageRate": "16.0858",
    "adValoremTaxes": "12653.37",
    "nonAdValoremTaxes": 400.0,
    "grossTaxes": 13053.37,
}
GREER_CERTIFIED = [
    {
        "parcelId": GREER_PID, "taxYear": 2025,
        "taxingAuthority": "General County",
        "assessedValue": 827027, "exemption": 50722, "taxValue": 776305,
        "millageRate": 4.4347, "isHomestead": "True", "taxes": 3442.6797,
        "taxType": "CTY",
    }
]
GREER_NON_AD_VAL = [
    {"parcelId": GREER_PID, "description": "WASTE PRO OF FL - GARBGE",
     "rate": 0, "assessment": 400.0, "levyingAuthority": "Orange County"}
]
GREER_PROPERTY_VALUES = [
    {"parcelId": GREER_PID, "taxYear": 2026,
     "marketValue": -1, "assessedValue": -1, "isHomestead": "True"}
]


def _setup_apn_session_mock(mock_cffi):
    """Configure cffi.Session to return GREER's 5 blocks for the APN path."""
    session = MagicMock()
    session.headers.update = MagicMock()
    session.get.side_effect = [
        _make_response(200, GREER_GENERAL),
        _make_response(200, GREER_TOTAL),
        _make_response(200, GREER_CERTIFIED),
        _make_response(200, GREER_NON_AD_VAL),
        _make_response(200, GREER_PROPERTY_VALUES),
    ]
    mock_cffi.Session.return_value = session
    return session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_clean_apn_strips_non_numeric():
    assert _clean_apn("27-22-30-2029-00-330") == "272230202900330"
    assert _clean_apn("  abc 272230 def 202900 330  ") == "272230202900330"
    assert _clean_apn("") == ""


def test_format_canonical_apn_15_digits():
    assert _format_canonical_apn("272230202900330") == "27-22-30-2029-00-330"


def test_format_canonical_apn_non_15_returns_input():
    assert _format_canonical_apn("1234") == "1234"
    assert _format_canonical_apn("abc") == ""  # _clean_apn first strips alpha
    # Note: _format_canonical_apn re-cleans then checks len == 15. "abc" -> ""


# ---------------------------------------------------------------------------
# Happy path: TAX_SUCCESS for GREER
# ---------------------------------------------------------------------------


def test_greer_apn_lookup_returns_tax_success(tmp_path):
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        _setup_apn_session_mock(mock_cffi)
        result = lookup_orange_ocpa_tax(
            apn="27-22-30-2029-00-330",
            county_id="fl_orange",
            case_dir=tmp_path,
            safe_owner="greer_test",
            property_address="17748 DEER ISLE CIR, WINTER GARDEN, FL",
        )
    assert result.status == "TAX_SUCCESS"
    assert result.apn == "27-22-30-2029-00-330"
    assert result.tax_year == "2025"
    assert result.annual_total == 13053.37
    assert result.installments[0]["amount"] == 13053.37
    assert result.installments[0]["label"] == "annual"
    # Payment status NOT verified (Wave-2 follow-up)
    assert result.installments[0]["status"] == "UNVERIFIED"
    # Non-ad-valorem surfaced
    assert len(result.special_assessments) == 1
    assert result.special_assessments[0]["amount"] == 400.0
    assert "WASTE PRO" in result.special_assessments[0]["description"]
    # Source URL points to OCPA, on authoritative whitelist
    assert "ocpa-mainsite-afd-standard.azurefd.net" in result.source_url
    # Source artifact written
    assert Path(result.source_artifact).exists()
    capture = json.loads(Path(result.source_artifact).read_text())
    assert capture["pid"] == GREER_PID
    assert "total_taxes" in capture["blocks"]
    # Verified fields include apn + tax_year + annual_total
    assert "apn" in result.verified_fields
    assert "tax_year" in result.verified_fields
    assert "annual_total" in result.verified_fields
    # Missing list is empty
    assert result.missing_fields == []
    # Notes mention closing-prep estoppel
    assert "estoppel" in result.notes.lower() or "tax collector" in result.notes.lower()


def test_greer_carries_assessed_value_from_certified_taxes(tmp_path):
    """OCPA returns assessedValue=-1 in PropertyValues until the new roll is
    certified; the adapter should fall back to GetPRCCertifiedTaxes."""
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        _setup_apn_session_mock(mock_cffi)
        result = lookup_orange_ocpa_tax(
            apn=GREER_PID, county_id="fl_orange", case_dir=tmp_path,
            safe_owner="greer", property_address="",
        )
    assert result.assessed_value.get("assessed") == 827027
    assert result.assessed_value.get("net_taxable") == 776305
    assert result.assessed_value.get("exemptions") == 50722


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_address_resolves_to_pid_then_fetches_taxes(tmp_path):
    """When apn is empty but property_address is given, the adapter resolves
    via QuickSearch and then fetches the PRC blocks."""
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        session = MagicMock()
        session.headers.update = MagicMock()
        # First call: address search returns one row; then 5 PRC blocks
        session.get.side_effect = [
            _make_response(200, [{"parcelId": GREER_PID,
                                   "propertyAddress": "17748 DEER ISLE CIR "}]),
            _make_response(200, GREER_GENERAL),
            _make_response(200, GREER_TOTAL),
            _make_response(200, GREER_CERTIFIED),
            _make_response(200, GREER_NON_AD_VAL),
            _make_response(200, GREER_PROPERTY_VALUES),
        ]
        mock_cffi.Session.return_value = session
        result = lookup_orange_ocpa_tax(
            apn="", county_id="fl_orange", case_dir=tmp_path,
            safe_owner="greer",
            property_address="17748 DEER ISLE CIR, WINTER GARDEN, FL",
        )
    assert result.status == "TAX_SUCCESS"
    assert result.apn == "27-22-30-2029-00-330"


def test_no_apn_no_address_returns_no_results(tmp_path):
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        session = MagicMock()
        session.headers.update = MagicMock()
        session.get.return_value = _make_response(200, [])
        mock_cffi.Session.return_value = session
        result = lookup_orange_ocpa_tax(
            apn="", county_id="fl_orange", case_dir=tmp_path,
            safe_owner="x", property_address="999 NOWHERE LN",
        )
    assert result.status == "TAX_NO_RESULTS"


def test_apn_echo_mismatch_returns_tax_failed(tmp_path):
    """When the input APN doesn't match what OCPA echoes back, fail loud."""
    bogus_general = dict(GREER_GENERAL)
    bogus_general["parcelId"] = "999999999999999"
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        session = MagicMock()
        session.headers.update = MagicMock()
        session.get.side_effect = [
            _make_response(200, bogus_general),
            _make_response(200, GREER_TOTAL),
            _make_response(200, GREER_CERTIFIED),
            _make_response(200, GREER_NON_AD_VAL),
            _make_response(200, GREER_PROPERTY_VALUES),
        ]
        mock_cffi.Session.return_value = session
        # Pass the WRONG APN (doesn't match echoed back PID)
        # The adapter cleans the apn input to use as PID — there's no echo
        # mismatch path through the PRC fetch, so we use the apn input
        # match against pid round-trip. Since clean(apn)==pid==input, this
        # test simulates the echo path which lives in the apn_matches call.
        # We instead test by NOT supplying apn to allow address-search to
        # pick the bogus PID and then confirming echo logic:
        result = lookup_orange_ocpa_tax(
            apn="27-22-30-2029-00-330",  # input
            county_id="fl_orange", case_dir=tmp_path,
            safe_owner="x", property_address="",
        )
    # adapter cleans "27-22-30-2029-00-330" to "272230202900330" and uses
    # that as PID directly. OCPA echoes back 999... which fails apn_matches.
    assert result.status == "TAX_FAILED"
    assert "echo mismatch" in result.error.lower()


def test_http_500_returns_tax_failed(tmp_path):
    with patch("titlepro.tax.orange_ocpa_http.cffi") as mock_cffi:
        session = MagicMock()
        session.headers.update = MagicMock()
        # Even the first call (general) returns 500
        err = _make_response(500, "")
        err.text = "Internal Server Error"
        session.get.return_value = err
        mock_cffi.Session.return_value = session
        result = lookup_orange_ocpa_tax(
            apn=GREER_PID, county_id="fl_orange", case_dir=tmp_path,
            safe_owner="x", property_address="",
        )
    assert result.status == "TAX_FAILED"
    assert "PRC fetch raised" in result.error or "HTTP 500" in result.error
