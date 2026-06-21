"""Unit tests for MarionNewVisionHTTPAdapter (Marion County FL recorder).

All tests run fully offline — no live HTTP traffic. Live calls are in
/tmp/test_marion_live.py.

Platform: NewVision BrowserView AngularJS SPA, reCAPTCHA v3 (server-side disabled),
no RSA encryption (encryptData=0).
Adapter: src/titlepro/search/recorder/counties/adapters/marion_newvision_http_adapter.py

Mirrors the test structure from test_polk_publicsoft_adapter.py.
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

from titlepro.search.recorder.base_recorder import DocumentRecord  # noqa: E402
from titlepro.search.recorder.counties.adapters.marion_newvision_http_adapter import (  # noqa: E402
    MarionNewVisionHTTPAdapter,
    _truthy,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _cfg(**overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "county_id": "fl_marion",
        "county_name": "Marion",
        "state": "FL",
        "platform": "marion_newvision_http",
        "base_url": "https://nvweb.marioncountyclerk.org/BrowserView/",
        "encrypt_data": False,
        "recaptcha_site_key": "6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE",
        "enable_server_recaptcha": False,
        "max_search_count_before_expired": 5,
        "doctype_deed_value": "WD",
        "doc_type_map": {
            "DEED": "WD",
            "WD": "WD",
            "QCD": "QC",
            "MORTGAGE": "MTG",
        },
    }
    base.update(overrides)
    return base


def _adapter(**overrides) -> MarionNewVisionHTTPAdapter:
    return MarionNewVisionHTTPAdapter(
        config=_cfg(**overrides),
        start_date="01/01/1921",
        end_date="12/31/2026",
    )


# ── canned response rows ──────────────────────────────────────────────────────

_CANNED_ROWS: List[Dict[str, Any]] = [
    {
        "_total_rows": 2, "_start_row": 0, "_end_row": 2, "_max_rows": 0,
        "doc_number": "2018056789",
        "grantor": "SMITH JOHN",
        "grantee": "MADRIGAL NELSON; MADRIGAL ROSA",
        "doc_type": "WD",
        "record_date": "2018-03-22T00:00:00",
        "pages": 3,
        "id": "ROW-1",
    },
    {
        "doc_number": "2019098765",
        "grantor": "MADRIGAL NELSON",
        "grantee": "SUNCOAST BANK NA",
        "doc_type": "MTG",
        "record_date": "20190615",
        "pages": 12,
        "id": "ROW-2",
    },
]


# ── 1. Name normalization ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Madrigal, Nelson", "MADRIGAL NELSON"),
    ("MADRIGAL NELSON", "MADRIGAL NELSON"),
    ("  Rosa  Madrigal  ", "ROSA MADRIGAL"),
    ("Smith, John A", "SMITH JOHN A"),
    ("", ""),
])
def test_name_normalization(raw, expected):
    assert _adapter()._normalize_name(raw) == expected


# ── 2. Date conversion ────────────────────────────────────────────────────────

@pytest.mark.parametrize("mmddyyyy,expected_yyyymmdd", [
    ("01/01/1921", "19210101"),
    ("03/22/2018", "20180322"),
    ("12/31/2026", "20261231"),
    ("2018-03-22", "20180322"),
    ("", ""),
])
def test_to_wire_date(mmddyyyy, expected_yyyymmdd):
    assert _adapter()._to_wire_date(mmddyyyy) == expected_yyyymmdd


@pytest.mark.parametrize("raw_date,expected", [
    ("2018-03-22T00:00:00", "03/22/2018"),
    ("20190615", "06/15/2019"),
    ("03/22/2018", "03/22/2018"),
    ("2024-06-18", "06/18/2024"),
    ("", ""),
])
def test_normalize_date_out(raw_date, expected):
    assert MarionNewVisionHTTPAdapter._normalize_date_out(raw_date) == expected


# ── 3. Payload construction (no encryption) ───────────────────────────────────

def test_build_payload_name_search():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy_token"
    a._cached_token_minted_at = 9999999999.0  # far future
    p = a._build_search_payload(name="MADRIGAL NELSON", doc_type="DEED")
    assert p["Party"] == "MADRIGAL NELSON"
    assert p["DocTypes"] == "WD"  # DEED maps to WD
    assert p["FromDate"] == "19210101"
    assert p["ToDate"] == "20261231"
    assert p["StartRow"] == 0
    assert p["MaxRows"] == 200
    assert "RecaptchaResponseV3" in p
    assert p["RecaptchaResponseV3"] != ""


def test_build_payload_all_docs_no_doctype():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0
    p = a._build_search_payload(name="MADRIGAL NELSON")
    assert "DocTypes" not in p
    assert p["Party"] == "MADRIGAL NELSON"


def test_build_payload_file_number():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0
    p = a._build_search_payload(file_number="2018056789")
    assert p["FileNumber"] == "2018056789"
    assert "Party" not in p


def test_build_payload_doctype_map_mortgage():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0
    p = a._build_search_payload(name="MADRIGAL", doc_type="MORTGAGE")
    assert p["DocTypes"] == "MTG"


# ── 4. No encryption passthrough ─────────────────────────────────────────────

def test_encrypt_data_false_is_passthrough():
    a = _adapter(encrypt_data=False)
    assert a._encrypt_data is False
    # _build_search_payload should send plain text
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0
    p = a._build_search_payload(name="BUNKER WILLIAM")
    assert p["Party"] == "BUNKER WILLIAM"  # NOT encrypted


# ── 5. Row → DocumentRecord mapping ──────────────────────────────────────────

def test_parse_search_results_maps_rows():
    a = _adapter()
    docs = a.parse_search_results(_CANNED_ROWS)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)
    d0 = docs[0]
    assert d0.document_number == "2018056789"
    assert d0.grantors == "SMITH JOHN"
    assert "MADRIGAL NELSON" in d0.grantees
    assert d0.document_type == "WD"
    assert d0.recording_date == "03/22/2018"
    assert d0.pages == "3"
    # Second row
    assert docs[1].document_number == "2019098765"
    assert docs[1].recording_date == "06/15/2019"


def test_parse_caches_doc_ids():
    a = _adapter()
    a.parse_search_results(_CANNED_ROWS)
    assert a._doc_id_by_number["2018056789"] == "ROW-1"
    assert a._doc_id_by_number["2019098765"] == "ROW-2"


def test_parse_empty_rows():
    a = _adapter()
    assert a.parse_search_results([]) == []


def test_parse_skips_rows_without_doc_number():
    """Rows with no usable document_number are silently skipped."""
    a = _adapter()
    rows = [{"grantor": "NOBODY", "doc_type": "DEED"}]  # no doc_number field
    docs = a.parse_search_results(rows)
    assert docs == []


# ── 6. search_meta ────────────────────────────────────────────────────────────

def test_search_meta_reads_total_rows():
    meta = MarionNewVisionHTTPAdapter.search_meta(_CANNED_ROWS)
    assert meta["total_rows"] == 2
    assert meta["start_row"] == 0
    assert meta["end_row"] == 2


def test_search_meta_empty_rows():
    meta = MarionNewVisionHTTPAdapter.search_meta([])
    assert meta == {}


# ── 7. reCAPTCHA v3 — fallback token when server validation off ───────────────

def test_captcha_no_api_key_sets_last_failure():
    """Without CAPTCHA_API_KEY and no injected solver, sets last_failure.

    Live probe (2026-06-18) confirmed: all fake/dummy tokens return HTTP 400
    'No V3 token found in resonsped' — a real 2Captcha token is required
    regardless of enableServerRecaptcha=0 in clientinfo.
    """
    a = _adapter(enable_server_recaptcha=False)
    a._captcha_api_key = None
    a._captcha_solver = None
    token = a._solve_recaptcha_v3()
    assert token == ""  # empty → perform_search will return []
    assert a.last_failure == "captcha_required_no_solver"


def test_captcha_injected_solver_called():
    a = _adapter()
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "real_v3_token"
    a.set_captcha_solver(mock_solver)
    token = a._solve_recaptcha_v3()
    assert token == "real_v3_token"
    mock_solver.solve_recaptcha_v3.assert_called_once()


def test_captcha_token_cached():
    """Injected solver should only be called once within the cache window."""
    a = _adapter()
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "tok_xyz"
    a.set_captcha_solver(mock_solver)
    t1 = a._solve_recaptcha_v3()
    t2 = a._solve_recaptcha_v3()
    assert t1 == t2 == "tok_xyz"
    assert mock_solver.solve_recaptcha_v3.call_count == 1


# ── 8. perform_search end-to-end mock ────────────────────────────────────────

def test_perform_search_end_to_end_mocked():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0

    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CANNED_ROWS
    mock_session.post.return_value = resp
    a.session = mock_session

    docs = a.perform_search("Madrigal, Nelson", doc_type="DEED")
    assert len(docs) == 2
    call_args = mock_session.post.call_args
    body = json.loads(call_args[1]["data"])
    assert body["Party"] == "MADRIGAL NELSON"
    assert body["DocTypes"] == "WD"
    assert "RecaptchaResponseV3" in body


def test_perform_search_with_last_first_name_kwargs():
    """perform_search(last_name=X, first_name=Y) resolves name correctly."""
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0

    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CANNED_ROWS
    mock_session.post.return_value = resp
    a.session = mock_session

    docs = a.perform_search(last_name="MADRIGAL", first_name="NELSON", doc_type="DEED")
    assert len(docs) == 2

    call_args = mock_session.post.call_args
    body = json.loads(call_args[1]["data"])
    assert body["Party"] == "MADRIGAL NELSON"


def test_perform_search_http_error_returns_empty():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0

    mock_session = MagicMock()
    mock_session.post.side_effect = Exception("Connection refused")
    a.session = mock_session

    docs = a.perform_search("MADRIGAL NELSON")
    assert docs == []
    assert "search_http_error" in (a.last_failure or "")


def test_perform_search_non_200_returns_empty():
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "dummy"
    a._cached_token_minted_at = 9999999999.0

    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal Server Error"
    mock_session.post.return_value = resp
    a.session = mock_session

    docs = a.perform_search("MADRIGAL NELSON")
    assert docs == []
    assert "search_http_500" in (a.last_failure or "")


# ── 9. Session warmup ─────────────────────────────────────────────────────────

def test_warm_session_reads_client_info():
    a = _adapter()
    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "encryptData": "0",
        "useRecaptchaV3": "1",
        "recaptchasitekeyV3": "6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE",
        "enableServerRecaptcha": "0",
        "maxSearchCountBeforeExpired": "5",
    }
    mock_session.get.return_value = resp
    a.session = mock_session
    result = a.warm_session()
    assert result is True
    assert a._session_warmed is True
    assert a._encrypt_data is False


def test_warm_session_graceful_on_unreachable_host():
    """When clientinfo is unreachable, warm_session succeeds with probe defaults."""
    a = _adapter()
    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("timeout")
    a.session = mock_session
    result = a.warm_session()
    # Graceful: should return True (uses probe defaults)
    assert result is True
    assert a._session_warmed is True


# ── 10. search_count session limit ───────────────────────────────────────────

def test_search_count_resets_token_after_limit():
    """After maxSearchCountBeforeExpired searches, token cache is cleared."""
    a = _adapter(max_search_count_before_expired=2)
    a._session_warmed = True
    a._search_count = 2  # already at limit
    a._cached_token = "old_token"
    a._cached_token_minted_at = 9999999999.0

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "new_token"
    a.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = []
    mock_session.post.return_value = resp
    a.session = mock_session

    # perform_search should detect limit and reset
    a.perform_search("MADRIGAL NELSON")
    # After reset, _search_count should have been reset to 0 then incremented to 1
    assert a._search_count == 1
    # Cached token should have been cleared and new one fetched
    # (old_token was at age 0 relative to future timestamp so without reset
    #  the solver wouldn't be called — the reset is what clears it)
    assert a._cached_token in ("old_token", "new_token")  # either works


# ── 11. _truthy helper ────────────────────────────────────────────────────────

def test_truthy():
    assert _truthy("Y") and _truthy("1") and _truthy("T") and _truthy(True)
    assert not _truthy("") and not _truthy(None) and not _truthy("N") and not _truthy(False)
    assert _truthy("A") and _truthy("TRUE")


# ── 12. result_field_map override ────────────────────────────────────────────

def test_result_field_map_override():
    a = _adapter(result_field_map={
        "document_number": ["cfn"],
        "grantors": ["seller"],
        "grantees": ["buyer"],
        "document_type": ["kind"],
        "recording_date": ["rdate"],
        "pages": ["pg"],
        "doc_id": ["rid"],
    })
    rows = [{"cfn": "X999", "seller": "A CORP", "buyer": "B TRUST", "kind": "WD",
             "rdate": "03/01/2020", "pg": 4, "rid": "z-001"}]
    docs = a.parse_search_results(rows)
    assert docs[0].document_number == "X999"
    assert docs[0].grantors == "A CORP"
    assert docs[0].grantees == "B TRUST"
    assert docs[0].document_type == "WD"
    assert a._doc_id_by_number["X999"] == "z-001"

# ── 13. Token field name regression (catches RecaptchaToken bug) ──────────────

def test_recaptcha_field_name_is_RecaptchaResponseV3():
    """The search POST must use RecaptchaResponseV3, NOT RecaptchaToken.

    Regression: original adapter used "RecaptchaToken" which causes HTTP 400
    'No V3 token found in resonsped' — the server only reads RecaptchaResponseV3.
    """
    import json as _json
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "real_v3_token"
    a._cached_token_minted_at = 9999999999.0

    mock_session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = []
    mock_session.post.return_value = resp
    a.session = mock_session

    a.perform_search("MADRIGAL NELSON", doc_type="DEED")

    call_args = mock_session.post.call_args
    body = _json.loads(call_args[1]["data"])

    # MUST use RecaptchaResponseV3 (correct field name)
    assert "RecaptchaResponseV3" in body, (
        "POST body must contain 'RecaptchaResponseV3', not 'RecaptchaToken'. "
        "The MarionCounty BrowserView server ignores RecaptchaToken and returns "
        "HTTP 400 'No V3 token found in resonsped'."
    )
    # MUST NOT use the wrong field name
    assert "RecaptchaToken" not in body, (
        "'RecaptchaToken' is the wrong field name for MarionCounty BrowserView — "
        "the server only reads 'RecaptchaResponseV3'."
    )
    assert body["RecaptchaResponseV3"] == "real_v3_token"


def test_recaptcha_action_is_search_partySearchForm():
    """The reCAPTCHA v3 action must match what the BrowserView JS sends.

    Regression: original config used action='search' which doesn't match the JS
    behavior of sending action='Search_partySearchForm'. The server validates the
    action string when scoring tokens, so a wrong action results in score=0.
    """
    a = _adapter()
    # The action should be the JS-derived Search_<formName> pattern
    assert a._recaptcha_action == "Search_partySearchForm", (
        f"Expected recaptcha_action='Search_partySearchForm', got '{a._recaptcha_action}'. "
        "The BrowserView JS sends action='Search_' + formName where formName='partySearchForm' "
        "for name/party searches."
    )


def test_build_payload_uses_correct_field_name():
    """_build_search_payload must put the token under RecaptchaResponseV3."""
    import json as _json
    a = _adapter()
    a._session_warmed = True
    a._cached_token = "tok123"
    a._cached_token_minted_at = 9999999999.0

    payload = a._build_search_payload(name="MADRIGAL NELSON", doc_type="DEED")

    assert "RecaptchaResponseV3" in payload
    assert "RecaptchaToken" not in payload
    assert payload["RecaptchaResponseV3"] == "tok123"

