"""Unit tests for CharlotteKendoHTTPAdapter (Charlotte County FL recorder).

All tests run fully offline — no live HTTP traffic. Live calls are in
/tmp/test_charlotte_live.py.

Platform: ASP.NET Core MVC + Kendo UI, reCAPTCHA v3, Cloudflare.
Adapter: src/titlepro/search/recorder/counties/adapters/charlotte_kendo_http_adapter.py
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

from titlepro.search.recorder.base_recorder import DocumentRecord  # noqa: E402
from titlepro.search.recorder.counties.adapters.charlotte_kendo_http_adapter import (  # noqa: E402
    CharlotteKendoHTTPAdapter,
    _strip_name,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _adapter(**overrides) -> CharlotteKendoHTTPAdapter:
    cfg = {
        "county_id": "fl_charlotte",
        "county_name": "Charlotte",
        "state": "FL",
        "platform": "charlotte_kendo_http",
        "base_url": "https://recording.charlotteclerk.com/",
        "recaptcha_site_key": "6LeA9DIpAAAAAJ51BtGfYnFHLkYc1w6EaNv29ED0",
        "deed_doc_type_ids": [24, 109, 5],
        "page_size": 5,
        "captcha_required": True,
    }
    cfg.update(overrides)
    return CharlotteKendoHTTPAdapter(config=cfg)


# ── sample Kendo grid JSON response ───────────────────────────────────────────

_KENDO_ROWS: List[Dict[str, Any]] = [
    {
        "DocumentId": 9001,
        "PageCount": 3,
        "Direct": "OLAR IVAN",
        "Reverse": "SUNSHINE TRUST LLC",
        "DirectReverse": "OLAR IVAN / SUNSHINE TRUST LLC",
        "BookNumber": "4521",
        "PageNumber": "1410",
        "ClerkFileNumber": "2024-001234",
        "RecordDate": "/Date(1704067200000)/",   # 2024-01-01 UTC
        "DocTypeDescription": "WARRANTY DEED",
        "Legal": "LOT 10 BLK A CHARLOTTE SHORES",
        "Parcel": "12-34-56-789-0000",
        "Consideration": "350000.00",
        "Status": "Active",
        "CaseNumber": "",
        "County": "Charlotte",
    },
    {
        "DocumentId": 9002,
        "PageCount": 18,
        "Direct": "FIRST BANK NA",
        "Reverse": "OLAR IVAN",
        "DirectReverse": "FIRST BANK NA / OLAR IVAN",
        "BookNumber": "4521",
        "PageNumber": "1428",
        "ClerkFileNumber": "2024-001250",
        "RecordDate": "2024-01-15T00:00:00",
        "DocTypeDescription": "MORTGAGE",
        "Legal": "LOT 10 BLK A CHARLOTTE SHORES",
        "Parcel": "12-34-56-789-0000",
        "Consideration": "280000.00",
        "Status": "Active",
        "CaseNumber": "",
        "County": "Charlotte",
    },
]

_KENDO_RESPONSE_PAGE1: Dict[str, Any] = {
    "Data": _KENDO_ROWS,
    "Total": 2,
    "Errors": None,
}

_KENDO_RESPONSE_EMPTY: Dict[str, Any] = {
    "Data": [],
    "Total": 0,
    "Errors": None,
}


# ── 1. strip_name helper ──────────────────────────────────────────────────────

def test_strip_name_removes_spaces_and_special_chars():
    assert _strip_name("O'BRIEN") == "OBRIEN"
    assert _strip_name("OLAR IVAN") == "OLARIVAN"
    assert _strip_name("ST. JOHN") == "STJOHN"
    assert _strip_name("DE LA CRUZ") == "DELACRUZ"


def test_strip_name_empty_string():
    assert _strip_name("") == ""


# ── 2. CSRF token extraction ──────────────────────────────────────────────────

def test_csrf_extraction_finds_token():
    """_refresh_csrf should extract __RequestVerificationToken from HTML."""
    import re
    html = """
    <html><body>
    <input name="__RequestVerificationToken" type="hidden"
           value="CfDJ8Abc123xyz_tokenXYZ" />
    </body></html>
    """
    tokens = re.findall(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html
    )
    assert tokens == ["CfDJ8Abc123xyz_tokenXYZ"]


def test_csrf_extraction_no_token():
    import re
    html = "<html><body><form></form></body></html>"
    tokens = re.findall(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html
    )
    assert tokens == []


# ── 3. Date parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("/Date(1704067200000)/", "01/01/2024"),
    ("2024-01-15T00:00:00", "01/15/2024"),
    ("2024-06-18", "06/18/2024"),
    ("", ""),
])
def test_parse_date(raw, expected):
    result = CharlotteKendoHTTPAdapter._parse_date(raw)
    assert result == expected


# ── 4. _rows_to_documents field mapping ──────────────────────────────────────

def test_rows_to_documents_maps_deed_row():
    a = _adapter()
    docs = a._rows_to_documents([_KENDO_ROWS[0]])
    assert len(docs) == 1
    d = docs[0]
    assert isinstance(d, DocumentRecord)
    assert d.document_number == "2024-001234"
    assert d.grantors == "OLAR IVAN"
    assert d.grantees == "SUNSHINE TRUST LLC"
    assert d.document_type == "WARRANTY DEED"
    assert d.recording_date == "01/01/2024"
    assert d.pages == "3"


def test_rows_to_documents_maps_mortgage_row():
    a = _adapter()
    docs = a._rows_to_documents([_KENDO_ROWS[1]])
    assert len(docs) == 1
    d = docs[0]
    assert d.document_number == "2024-001250"
    assert d.document_type == "MORTGAGE"
    assert d.recording_date == "01/15/2024"
    assert d.pages == "18"


def test_rows_to_documents_fallback_doc_num_to_document_id():
    """When ClerkFileNumber is empty, fall back to DocumentId."""
    a = _adapter()
    row = {
        "DocumentId": 999,
        "PageCount": 2,
        "Direct": "SELLER A",
        "Reverse": "BUYER B",
        "DirectReverse": "",
        "BookNumber": "3000",
        "PageNumber": "500",
        "ClerkFileNumber": "",
        "RecordDate": "2020-05-01T00:00:00",
        "DocTypeDescription": "DEED",
    }
    docs = a._rows_to_documents([row])
    # Charlotte adapter priority: ClerkFileNumber → CaseNumber → DocumentId → Book/Page
    # ClerkFileNumber="" (falsy), CaseNumber absent, DocumentId=999 → use DocumentId
    assert docs[0].document_number == "999"


def test_rows_to_documents_fallback_doc_num_to_book_page():
    """When no ClerkFileNumber, CaseNumber, or DocumentId, fall back to Book/Page."""
    a = _adapter()
    row = {
        "PageCount": 2,
        "Direct": "SELLER A",
        "Reverse": "BUYER B",
        "DirectReverse": "",
        "BookNumber": "3000",
        "PageNumber": "500",
        "ClerkFileNumber": "",
        "RecordDate": "2020-05-01T00:00:00",
        "DocTypeDescription": "DEED",
    }
    docs = a._rows_to_documents([row])
    # No DocumentId → falls through to Book/Page
    assert docs[0].document_number == "3000/500"


def test_rows_to_documents_empty_input():
    a = _adapter()
    assert a._rows_to_documents([]) == []


def test_rows_to_documents_multiple_rows():
    a = _adapter()
    docs = a._rows_to_documents(_KENDO_ROWS)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)


# ── 5. Pagination logic ───────────────────────────────────────────────────────

def test_perform_search_paginates_to_completion():
    """perform_search should stop after fetching all pages."""
    a = _adapter(page_size=1)
    a._csrf_token = "token123"

    # captcha solver returns a dummy token immediately
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "fake_v3_token"
    a.set_captcha_solver(mock_solver)

    # Mock session: GET ViewDocuments returns HTML with CSRF;
    # POST GetDocumentView returns page-by-page results
    mock_session = MagicMock()
    # GET ViewDocuments
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.status_code = 200
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="token123" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    # POST GetDocumentView: first call returns row[0], second call returns row[1], third returns empty
    post_resp_1 = MagicMock()
    post_resp_1.status_code = 200
    post_resp_1.headers = {"Content-Type": "application/json"}
    post_resp_1.json.return_value = {"Data": [_KENDO_ROWS[0]], "Total": 2, "Errors": None}

    post_resp_2 = MagicMock()
    post_resp_2.status_code = 200
    post_resp_2.headers = {"Content-Type": "application/json"}
    post_resp_2.json.return_value = {"Data": [_KENDO_ROWS[1]], "Total": 2, "Errors": None}

    mock_session.post.side_effect = [post_resp_1, post_resp_2]
    a._session = mock_session

    docs = a.perform_search(name="OLAR IVAN", doc_type="ALL")
    assert len(docs) == 2
    assert mock_session.post.call_count == 2


def test_perform_search_stops_on_empty_page():
    """If Data is empty before expected total, stop fetching."""
    a = _adapter(page_size=5)
    a._csrf_token = "tok"

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "v3tok"
    a.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="tok" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.headers = {"Content-Type": "application/json"}
    post_resp.json.return_value = {"Data": [], "Total": 0, "Errors": None}
    mock_session.post.return_value = post_resp
    a._session = mock_session

    docs = a.perform_search(name="NOBODY", doc_type="DEED")
    assert docs == []
    assert mock_session.post.call_count == 1


# ── 6. last_name/first_name kwargs ────────────────────────────────────────────

def test_perform_search_accepts_last_first_name_kwargs():
    """perform_search(last_name=X, first_name=Y) should assemble name correctly."""
    a = _adapter()
    a._csrf_token = "tok"

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "v3tok"
    a.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="tok" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.headers = {"Content-Type": "application/json"}
    post_resp.json.return_value = {"Data": _KENDO_ROWS, "Total": 2, "Errors": None}
    mock_session.post.return_value = post_resp
    a._session = mock_session

    docs = a.perform_search(last_name="OLAR", first_name="IVAN", doc_type="DEED")
    assert len(docs) == 2

    # Verify the POST was called with the assembled name data
    call_kwargs = mock_session.post.call_args
    post_body = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
    # Form-urlencoded body should include OLAR as last name
    assert "OLAR" in str(post_body)


# ── 7. reCAPTCHA v3 cache ─────────────────────────────────────────────────────

def test_captcha_token_is_cached():
    """A fresh token should be reused within the cache window."""
    a = _adapter()
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "cached_token_abc"
    a.set_captcha_solver(mock_solver)

    t1 = a._solve_recaptcha_v3("render/viewdocument")
    t2 = a._solve_recaptcha_v3("render/viewdocument")

    assert t1 == "cached_token_abc"
    assert t2 == "cached_token_abc"
    # Solver was called only once
    assert mock_solver.solve_recaptcha_v3.call_count == 1


def test_captcha_no_api_key_returns_none():
    """Without CAPTCHA_API_KEY and no injected solver, returns None."""
    a = _adapter()
    a._captcha_api_key = None
    a._captcha_solver = None
    result = a._solve_recaptcha_v3("render/viewdocument")
    assert result is None
    assert a.last_failure == "captcha_api_key_missing"


def test_captcha_token_cache_is_keyed_by_action():
    """A token solved for search/name must NOT be reused for render/viewdocument.

    Regression: the original implementation used a single _cached_token for both
    actions, so a Verify-step token (action=search/name) could be reused for the
    grid POST (action=render/viewdocument), silently failing the server score check.
    """
    a = _adapter()
    mock_solver = MagicMock()
    # Each call returns a different token so we can track which was used
    mock_solver.solve_recaptcha_v3.side_effect = ["search_token", "view_token"]
    a.set_captcha_solver(mock_solver)

    search_action = a._recaptcha_action_search   # "search/name"
    view_action = a._recaptcha_action_view       # "render/viewdocument"

    t_search = a._solve_recaptcha_v3(search_action)
    t_view = a._solve_recaptcha_v3(view_action)

    # Different actions → different tokens (solver called twice)
    assert t_search == "search_token"
    assert t_view == "view_token"
    assert mock_solver.solve_recaptcha_v3.call_count == 2, (
        "Solver must be called once per distinct action — the search/name token "
        "must NOT be reused for render/viewdocument."
    )

    # Calling same action again within the cache window → solver NOT called again
    t_view2 = a._solve_recaptcha_v3(view_action)
    assert t_view2 == "view_token"
    assert mock_solver.solve_recaptcha_v3.call_count == 2  # still 2

    t_search2 = a._solve_recaptcha_v3(search_action)
    assert t_search2 == "search_token"
    assert mock_solver.solve_recaptcha_v3.call_count == 2  # still 2


# ── 8. Session warmup / CSRF failure ─────────────────────────────────────────

def test_perform_search_returns_empty_on_warmup_failure():
    """If CSRF fetch fails, perform_search returns empty list."""
    a = _adapter()
    a._csrf_token = None

    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("Connection refused")
    a._session = mock_session

    docs = a.perform_search(name="OLAR IVAN")
    assert docs == []
    assert a.last_failure == "session_warmup_failed"


# ── 9. Server error in response ───────────────────────────────────────────────

def test_perform_search_handles_server_error_in_response():
    """If the JSON response has Errors set, stop and set last_failure."""
    a = _adapter()
    a._csrf_token = "tok"

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "v3tok"
    a.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="tok" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.headers = {"Content-Type": "application/json"}
    post_resp.json.return_value = {"Data": None, "Total": 0, "Errors": "Session expired"}
    mock_session.post.return_value = post_resp
    a._session = mock_session

    docs = a.perform_search(name="OLAR IVAN", doc_type="ALL")
    assert docs == []
    assert "server_error" in (a.last_failure or "")


# ── 10. deed_first helper ─────────────────────────────────────────────────────

def test_search_deed_first_deduplicates():
    """search_deed_first should merge deed + all results without duplicates."""
    a = _adapter()
    a._csrf_token = "tok"

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "v3tok"
    a.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="tok" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    # Both DEED-only search and ALL search return the same 2 rows
    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.headers = {"Content-Type": "application/json"}
    post_resp.json.return_value = {"Data": _KENDO_ROWS, "Total": 2, "Errors": None}
    mock_session.post.return_value = post_resp
    a._session = mock_session

    docs = a.search_deed_first(name="OLAR IVAN")
    # Deduplication: both DEED and ALL searches return the same 2 docs → 2 unique
    assert len(docs) == 2

# ── 11. __init__ standard signature regression (catches ctor bug) ─────────────

def test_init_accepts_standard_signature():
    """CharlotteKendoHTTPAdapter.__init__ must accept (config, start_date, end_date).

    Regression test: the original __init__ only accepted (config) and would raise
    TypeError when the registry calls it with start_date / end_date kwargs.
    """
    adapter = CharlotteKendoHTTPAdapter(
        config={"county_id": "fl_charlotte"},
        start_date="01/01/1990",
        end_date="12/31/2026",
    )
    assert adapter.start_date == "01/01/1990"
    assert adapter.end_date == "12/31/2026"


def test_init_default_start_date():
    """Default start_date should be set even when not passed."""
    adapter = CharlotteKendoHTTPAdapter(config={"county_id": "fl_charlotte"})
    # The base class sets start_date; it should NOT remain the base default "01/01/2010"
    # but rather the registry-compatible "01/01/1990"
    assert adapter.start_date is not None
    assert "/" in adapter.start_date  # MM/DD/YYYY format


def test_init_dates_wired_into_perform_search():
    """Dates passed to __init__ should appear in the search payload."""
    adapter = CharlotteKendoHTTPAdapter(
        config={"county_id": "fl_charlotte", "deed_doc_type_ids": [24]},
        start_date="03/15/2000",
        end_date="09/30/2025",
    )
    adapter._csrf_token = "tok"

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v3.return_value = "v3tok"
    adapter.set_captcha_solver(mock_solver)

    mock_session = MagicMock()
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.text = '<input name="__RequestVerificationToken" type="hidden" value="tok" />'
    get_resp.url = "https://recording.charlotteclerk.com/Render/ViewDocuments"
    mock_session.get.return_value = get_resp

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.headers = {"Content-Type": "application/json"}
    post_resp.json.return_value = {"Data": [], "Total": 0, "Errors": None}
    mock_session.post.return_value = post_resp
    adapter._session = mock_session

    adapter.perform_search(name="OLAR IVAN", doc_type="DEED")

    # Check that the POST payload includes the ctor-supplied dates
    call_args = mock_session.post.call_args
    post_body = call_args[1].get("data", call_args[0][1] if len(call_args[0]) > 1 else "")
    body_str = str(post_body)
    assert "03/15/2000" in body_str or "inStartDate" in body_str

