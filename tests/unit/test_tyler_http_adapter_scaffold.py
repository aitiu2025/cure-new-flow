"""Scaffold tests for TylerHTTPAdapter.

These tests verify:
  1.  The adapter source file imports cleanly with no Selenium / Playwright
      / undetected-chromedriver module pulls (Tony directive #1).
  2.  The adapter constructs from the Orange FL JSON config.
  3.  The public API surface exists (warm_session, perform_search, pull_detail,
      extract_results, plus the ABC no-ops + set_captcha_solver hook).
  4.  extract_results() parses the canonical Tyler searchResults HTML fragment
      into DocumentRecord instances.
  5.  _scrape_sitekey() pulls the data-sitekey from the disclaimer page.
  6.  _solve_recaptcha() respects an injected CaptchaSolverBase and caches
      the token across calls.
  7.  warm_session() drives the full landing -> captcha -> disclaimer-accept
      flow via mocked sessions.
  8.  perform_search() builds the right url-encoded payload, sends the
      Accept:json + XHR headers, and parses the resulting JSON +
      paginated HTML fragments.
  9.  Registry routing: platform="tyler_http" -> TylerHTTPAdapter.
  10. validation messages in the JSON response surface via last_failure.

The tests intentionally do NOT hit the live Orange portal or 2Captcha — the
end-to-end validation is a downstream step.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (mirror other tests in this directory)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONFIG_PATH = (
    SRC
    / "titlepro"
    / "search"
    / "recorder"
    / "counties"
    / "config"
    / "fl"
    / "orange.json"
)


@pytest.fixture(scope="module")
def orange_config() -> dict:
    with CONFIG_PATH.open("r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Canonical fixtures
# ---------------------------------------------------------------------------

# Minimal HTML matching the live Orange searchResults fragment shape
# (1 doc; trimmed of irrelevant CSS).
TYLER_RESULTS_HTML = """
<div>
<ul class="ss-listview ss-utility-box" data-role="listview">
  <li class="ss-search-row" data-documentid="DOC3379S37800"
      data-href="/ssweb/document/DOC3379S37800?search=DOCSEARCH2950S1"
      id="searchRowDOC3379S37800">
    <div class="selfServiceSearchRowLeft">
      <input class="ss-facet-select" type="checkbox"/>
    </div>
    <div class="selfServiceSearchRowRight">
      <h1>20220421546 Satisfaction 07/11/2022 10:57 AM</h1>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn">
          <li>Grantor (2)</li>
          <li class="selfServiceSearchResultCollapsed"><b>TRUIST BANK</b></li>
          <li class="selfServiceSearchFullResult"><b>SUNTRUST BANK</b></li>
        </ul>
      </div>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn">
          <li>Grantee (2)</li>
          <li class="selfServiceSearchResultCollapsed"><b>GREER DIANA V</b></li>
          <li class="selfServiceSearchFullResult"><b>GREER BRETT B</b></li>
        </ul>
      </div>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn"><li>Legal</li></ul>
      </div>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn"><li>BookPage</li></ul>
      </div>
    </div>
  </li>
  <li class="ss-search-row" data-documentid="DOC9999X11111"
      data-href="/ssweb/document/DOC9999X11111?search=DOCSEARCH2950S1">
    <div class="selfServiceSearchRowRight">
      <h1>20210123456 Deed 05/04/2021 02:30 PM</h1>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn">
          <li>Grantor (1)</li>
          <li class="selfServiceSearchResultCollapsed"><b>SMITH JOHN</b></li>
        </ul>
      </div>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn">
          <li>Grantee (1)</li>
          <li class="selfServiceSearchResultCollapsed"><b>GREER DIANA V</b></li>
        </ul>
      </div>
      <div class="searchResultFourColumn">
        <ul class="selfServiceSearchResultColumn"><li>BookPage</li><li>1234/567</li></ul>
      </div>
    </div>
  </li>
</ul>
</div>
"""

# Minimal disclaimer page (real Orange FL has the same data-sitekey location).
TYLER_DISCLAIMER_HTML = """
<html>
<body>
  <form class="center" method="POST">
    <div class="g-recaptcha center"
         data-sitekey="6LemVGAUAAAAAB_iW1wbaE4_s0Z5SoSakm6GI8St"
         data-callback="onReturnRecaptchaCallback"></div>
  </form>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 1) No browser-driver leakage at import time
# ---------------------------------------------------------------------------

def test_adapter_module_does_not_import_selenium_or_playwright():
    """Tony directive #1: 100% HTTP. The Tyler HTTP adapter module file must
    not pull in any browser-automation library at import time.

    Same isolation strategy as the AcclaimWeb / Hillsborough scaffolds —
    importing via the package would leak because
    ``counties/adapters/__init__.py`` eagerly imports the Selenium siblings.
    """
    import importlib.util

    adapter_path = (
        SRC
        / "titlepro"
        / "search"
        / "recorder"
        / "counties"
        / "adapters"
        / "tyler_http_adapter.py"
    )

    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(
        "_isolated_tyler_http_adapter", adapter_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    after = set(sys.modules.keys())
    new_modules = after - before

    leaked = [
        m
        for m in new_modules
        if (
            m == "selenium"
            or m.startswith("selenium.")
            or m == "playwright"
            or m.startswith("playwright.")
            or m == "undetected_chromedriver"
            or m.startswith("undetected_chromedriver.")
        )
    ]
    truly_new_leaks = [m for m in leaked if m not in before]
    assert (
        not truly_new_leaks
    ), f"Tyler HTTP adapter source leaked browser modules: {truly_new_leaks}"

    # Source-level guard.
    src = adapter_path.read_text(encoding="utf-8")
    forbidden_substrings = (
        "import selenium",
        "from selenium",
        "import playwright",
        "from playwright",
        "import undetected_chromedriver",
        "from undetected_chromedriver",
    )
    for needle in forbidden_substrings:
        assert (
            needle not in src
        ), f"Tyler HTTP adapter source contains forbidden import: {needle}"


# ---------------------------------------------------------------------------
# 2) Construction + 3) public API surface
# ---------------------------------------------------------------------------

def test_adapter_constructs_from_orange_config(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    assert adapter.county_name == "Orange"
    assert adapter.base_url.startswith("https://selfservice.or.occompt.com/ssweb")
    # The configured sitekey is the live Orange FL one.
    assert adapter._recaptcha_sitekey == "6LemVGAUAAAAAB_iW1wbaE4_s0Z5SoSakm6GI8St"
    # Search path derived correctly.
    assert adapter._search_path == "DOCSEARCH2950S1"
    # Form-field map applied.
    assert adapter._field_both == "field_BothNamesID"
    assert adapter._field_start == "field_RecordingDateID_DOT_StartDate"
    assert adapter._field_doctype == "field_selfservice_documentTypes"
    # Tenant flags
    assert adapter._combined_name_search is True
    assert adapter._captcha_required is True
    assert adapter._max_date_range_years == 5
    # Initial state
    assert adapter._session_warmed is False
    assert adapter.last_failure is None
    assert adapter.driver is None


def test_adapter_has_full_api_surface(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    for method in (
        "warm_session",
        "setup_driver",
        "navigate_to_search",
        "perform_search",
        "pull_detail",
        "extract_results",
        "return_to_search",
        "set_captcha_solver",
    ):
        assert hasattr(adapter, method), f"missing method: {method}"
        assert callable(getattr(adapter, method)), f"not callable: {method}"

    # ABC no-ops
    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


# ---------------------------------------------------------------------------
# 4) extract_results() parses live-format HTML
# ---------------------------------------------------------------------------

def test_extract_results_parses_canonical_html(orange_config):
    from titlepro.search.recorder.base_recorder import DocumentRecord
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    docs = adapter.extract_results(TYLER_RESULTS_HTML)
    assert isinstance(docs, list)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)

    by_num = {d.document_number: d for d in docs}
    assert "20220421546" in by_num
    assert "20210123456" in by_num

    sat = by_num["20220421546"]
    assert sat.document_type == "Satisfaction"
    assert sat.recording_date == "07/11/2022"
    assert "TRUIST BANK" in sat.grantors
    assert "SUNTRUST BANK" in sat.grantors
    assert "GREER DIANA V" in sat.grantees
    assert "GREER BRETT B" in sat.grantees

    deed = by_num["20210123456"]
    assert deed.document_type == "Deed"
    assert deed.recording_date == "05/04/2021"
    assert deed.pages == "1234/567"


def test_extract_results_handles_empty_input(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body>no rows</body></html>") == []


# ---------------------------------------------------------------------------
# 5) _scrape_sitekey()
# ---------------------------------------------------------------------------

def test_scrape_sitekey(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    assert (
        adapter._scrape_sitekey(TYLER_DISCLAIMER_HTML)
        == "6LemVGAUAAAAAB_iW1wbaE4_s0Z5SoSakm6GI8St"
    )
    assert adapter._scrape_sitekey("<html>no captcha</html>") is None


# ---------------------------------------------------------------------------
# 6) _solve_recaptcha() via injected solver
# ---------------------------------------------------------------------------

def test_solve_recaptcha_uses_injected_solver(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2 = MagicMock(return_value="fake-recaptcha-token-XYZ")
    adapter.set_captcha_solver(mock_solver)

    tok = adapter._solve_recaptcha(page_url="https://selfservice.or.occompt.com/ssweb/user/disclaimer")
    assert tok == "fake-recaptcha-token-XYZ"
    mock_solver.solve_recaptcha_v2.assert_called_once_with(
        "6LemVGAUAAAAAB_iW1wbaE4_s0Z5SoSakm6GI8St",
        "https://selfservice.or.occompt.com/ssweb/user/disclaimer",
    )

    # Cached for second call (within TTL).
    tok2 = adapter._solve_recaptcha()
    assert tok2 == tok
    assert mock_solver.solve_recaptcha_v2.call_count == 1


def test_solve_recaptcha_failure_sets_last_failure(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2 = MagicMock(return_value=None)
    adapter.set_captcha_solver(mock_solver)

    assert adapter._solve_recaptcha() is None
    assert adapter.last_failure == "captcha_solver_failed"


# ---------------------------------------------------------------------------
# 7) warm_session() full flow with mocked session
# ---------------------------------------------------------------------------

def test_warm_session_end_to_end(orange_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2 = MagicMock(return_value="mock-token")
    adapter.set_captcha_solver(mock_solver)

    captured: dict[str, Any] = {"gets": [], "posts": []}

    def fake_get(url, timeout=None, allow_redirects=True, **kw):
        captured["gets"].append({"url": url, "allow_redirects": allow_redirects})
        resp = MagicMock()
        resp.status_code = 200
        resp.text = TYLER_DISCLAIMER_HTML
        resp.headers = {"Location": ""}
        return resp

    def fake_post(url, data=None, timeout=None, headers=None, **kw):
        captured["posts"].append({"url": url, "data": data})
        resp = MagicMock()
        resp.status_code = 200
        # Tyler returns literal "true" on disclaimer accept.
        resp.text = "true"
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)
    monkeypatch.setattr(adapter.session, "post", fake_post)

    assert adapter.warm_session() is True
    assert adapter._session_warmed is True
    # Disclaimer GET + verify GET
    assert any("disclaimer" in g["url"] for g in captured["gets"])
    assert any("search/DOCSEARCH" in g["url"] for g in captured["gets"])
    # Disclaimer POST with the token
    accept_posts = [p for p in captured["posts"] if "disclaimer" in p["url"]]
    assert accept_posts
    assert accept_posts[0]["data"]["g-recaptcha-response"] == "mock-token"


def test_warm_session_fails_when_disclaimer_rejected(orange_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2 = MagicMock(return_value="bad-token")
    adapter.set_captcha_solver(mock_solver)

    def fake_get(url, timeout=None, allow_redirects=True, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = TYLER_DISCLAIMER_HTML
        resp.headers = {}
        return resp

    def fake_post(url, data=None, timeout=None, headers=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        # Tyler returns "false" when the token is bad.
        resp.text = "false"
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)
    monkeypatch.setattr(adapter.session, "post", fake_post)

    assert adapter.warm_session() is False
    assert adapter.last_failure == "disclaimer_rejected"


# ---------------------------------------------------------------------------
# 8) perform_search() flow with mocked session
# ---------------------------------------------------------------------------

def test_perform_search_with_mocked_session(orange_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    adapter._session_warmed = True  # skip warm-up

    captured: dict[str, Any] = {"posts": [], "gets": []}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        captured["posts"].append({"url": url, "data": data, "headers": headers})
        resp = MagicMock()
        resp.status_code = 200
        resp.text = json.dumps(
            {"validationMessages": {}, "totalPages": 1, "currentPage": 1}
        )
        resp.json = lambda: json.loads(resp.text)
        return resp

    def fake_get(url, headers=None, timeout=None, allow_redirects=True, **kw):
        captured["gets"].append({"url": url, "headers": headers})
        resp = MagicMock()
        resp.status_code = 200
        resp.text = TYLER_RESULTS_HTML
        return resp

    monkeypatch.setattr(adapter.session, "post", fake_post)
    monkeypatch.setattr(adapter.session, "get", fake_get)

    docs = adapter.perform_search(
        "GREER DIANA",
        party_type="Both",
        date_from="01/01/2020",
        date_to="12/31/2024",
    )
    assert len(docs) == 2

    # POST was sent to searchPost endpoint
    sp_posts = [p for p in captured["posts"] if "searchPost" in p["url"]]
    assert sp_posts
    sp = sp_posts[0]
    # Headers requested JSON via XHR
    assert sp["headers"]["Accept"].startswith("application/json")
    assert sp["headers"]["X-Requested-With"] == "XMLHttpRequest"
    # Payload contains the combined-name field
    data_dict = dict(sp["data"])
    assert data_dict["field_BothNamesID"] == "GREER DIANA"
    assert data_dict["field_RecordingDateID_DOT_StartDate"] == "01/01/2020"
    assert data_dict["field_RecordingDateID_DOT_EndDate"] == "12/31/2024"

    # GET was made to searchResults?page=1
    sr_gets = [g for g in captured["gets"] if "searchResults" in g["url"]]
    assert sr_gets
    assert "page=1" in sr_gets[0]["url"]


def test_perform_search_surfaces_validation_messages(orange_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    adapter._session_warmed = True

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = json.dumps(
            {
                "validationMessages": {
                    "field_RecordingDateID_DOT_StartDate": "5 years is the maximum date range that can be searched over."
                },
                "totalPages": 0,
                "currentPage": 0,
            }
        )
        resp.json = lambda: json.loads(resp.text)
        return resp

    monkeypatch.setattr(adapter.session, "post", fake_post)

    docs = adapter.perform_search(
        "GREER DIANA",
        date_from="01/01/2010",
        date_to="12/31/2025",
    )
    assert docs == []
    assert adapter.last_failure is not None
    assert "validation" in adapter.last_failure
    assert "5 years" in adapter.last_failure


# ---------------------------------------------------------------------------
# 9) Registry routing
# ---------------------------------------------------------------------------

def test_registry_tyler_http_platform_resolves():
    from titlepro.search.recorder.counties import registry
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = registry.get_recorder("fl_orange")
    assert isinstance(adapter, TylerHTTPAdapter)
    assert adapter.county_name == "Orange"


# ---------------------------------------------------------------------------
# 10) Name-match helper used for party-type post-filtering
# ---------------------------------------------------------------------------

def test_name_in_field_matches_subset(orange_config):
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )

    adapter = TylerHTTPAdapter(orange_config)
    norm = adapter._normalize_name("GREER DIANA")
    assert adapter._name_in_field(norm, "GREER DIANA V; GREER BRETT B") is True
    assert adapter._name_in_field(norm, "TRUIST BANK; SUNTRUST BANK") is False
    assert adapter._name_in_field(norm, "") is False


# ---------------------------------------------------------------------------
# 11) download_pdf — Tyler binary-write path
# ---------------------------------------------------------------------------

def _build_warmed_adapter(orange_config, *, doc_id_cache=None):
    """Construct a TylerHTTPAdapter with warm_session bypassed and the
    doc_id cache pre-seeded so download_pdf tests can isolate the
    detail-page + PDF-GET flow."""
    from titlepro.search.recorder.counties.adapters.tyler_http_adapter import (
        TylerHTTPAdapter,
    )
    adapter = TylerHTTPAdapter(orange_config)
    adapter._session_warmed = True
    adapter._doc_id_by_number = dict(doc_id_cache or {})
    return adapter


def _fake_response(status_code, *, text=None, content=None):
    resp = MagicMock()
    resp.status_code = status_code
    if text is not None:
        resp.text = text
    if content is not None:
        resp.content = content
    return resp


def _wrapper_html_with_real_pdf(doc_id: str, doc_num: str) -> str:
    """Build a stub pdf.js wrapper response matching Tyler's live shape:
    a <button data-href=...> + <iframe data-href=...> both pointing at the
    real PDF endpoint (``/ssweb/document-image-pdf/<doc_id>//<doc_num>-1.pdf?index=1``).
    """
    return (
        f'<button id="printCustom" data-href="/ssweb/document-image-pdf/{doc_id}//{doc_num}-1.pdf?index=1" '
        f'title="Print"></button>'
        f'<iframe class="ss-pdfjs-lviewer" data-href="/ssweb/document-image-pdf/{doc_id}//{doc_num}-1.pdf?index=1" '
        f"src='/ssweb/resources/pdfjs/web/tylerPdfJsViewer.html?file=/ssweb/document/servepdf/SCALED-{doc_id}.1.pdf/{doc_num}.pdf?index=1'></iframe>"
    )


def test_download_pdf_happy_path_writes_file_with_pdf_magic(orange_config, tmp_path):
    """Happy path: detail page -> pdf.js wrapper -> real PDF endpoint.
    Per the live Orange FL protocol fixed 2026-05-26, the flow makes 3 GETs.
    The disclaimerAccepted cookie (stomped to false on every authenticated
    GET response) is flipped back via the client-side
    `_restore_disclaimer_cookie` jar repair — NOT via disclaimer-reaffirm
    POSTs. The POST path was removed because re-using the 2Captcha token is
    single-use-risky and amplifies rate-limit exposure; zero POSTs must fire
    during a download."""
    doc_id = "DOC4258S25549"
    doc_num = "20260199062"
    adapter = _build_warmed_adapter(orange_config, doc_id_cache={doc_num: doc_id})
    detail_html = (
        "<html><script>"
        "selfservice.document.pdfJsUrl = "
        f"'/ssweb/document-image-pdfjs/{doc_id}/uuid-abc-123/{doc_num}.pdf?allowDownload=true&index=1';"
        "</script></html>"
    )
    wrapper_html = _wrapper_html_with_real_pdf(doc_id, doc_num)
    pdf_bytes = b"%PDF-1.4\n%binary\nfake-content"
    adapter.session = MagicMock()
    # Three GETs: detail -> pdfjs wrapper -> real PDF
    adapter.session.get.side_effect = [
        _fake_response(200, text=detail_html),
        _fake_response(200, text=wrapper_html),
        _fake_response(200, content=pdf_bytes),
    ]
    # Defensive: if a POST ever fires it would succeed — the assertion
    # below still requires that none do.
    adapter.session.post.return_value = _fake_response(200, text="true")

    dest = tmp_path / "out" / f"{doc_num}.pdf"
    result = adapter.download_pdf(doc_num, dest)

    assert result["status"] == "success", result
    assert result["size"] == len(pdf_bytes)
    assert result.get("src_via") == "pdfjs_wrapper_data_href"
    assert dest.exists()
    assert dest.read_bytes() == pdf_bytes
    assert adapter.session.get.call_count == 3
    # 2026-05-26: disclaimer re-affirm became a local cookie-jar restore
    # (zero captcha cost); the download flow must NOT re-POST the disclaimer.
    assert adapter.session.post.call_count == 0
    # Detail GET first
    assert doc_id in adapter.session.get.call_args_list[0].args[0]
    # Real PDF GET last; uses /document-image-pdf/ (NOT -pdfjs)
    real_pdf_url = adapter.session.get.call_args_list[2].args[0]
    assert "document-image-pdf/" in real_pdf_url
    assert doc_num in real_pdf_url


def test_download_pdf_returns_error_when_doc_id_missing(orange_config, tmp_path):
    adapter = _build_warmed_adapter(orange_config, doc_id_cache={})
    adapter.session = MagicMock()
    result = adapter.download_pdf("99999999999", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert "no Tyler doc_id cached" in result["error"]
    assert adapter.session.get.call_count == 0


def test_download_pdf_returns_error_when_pdfjsurl_not_in_detail_html(orange_config, tmp_path):
    """If the detail page returns a stripped skeleton (e.g. disclaimer cookie
    got reset and the reaffirm didn't take), pdfJsUrl is absent → hard error
    BEFORE the wrapper GET fires."""
    adapter = _build_warmed_adapter(
        orange_config, doc_id_cache={"20240253555": "DOC3697S37268"}
    )
    detail_html = "<html><body>No PDF link here — restricted document.</body></html>"
    adapter.session = MagicMock()
    adapter.session.get.return_value = _fake_response(200, text=detail_html)
    adapter.session.post.return_value = _fake_response(200, text="true")

    result = adapter.download_pdf("20240253555", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert "pdfJsUrl" in result["error"]
    # Exactly one GET (detail); no wrapper, no PDF
    assert adapter.session.get.call_count == 1


def test_download_pdf_returns_error_when_wrapper_missing_real_pdf(orange_config, tmp_path):
    """If the pdf.js wrapper page doesn't contain a data-href or recognizable
    PDF URL, we surface a hard error and don't blindly write garbage."""
    doc_id = "DOC3697S37268"
    doc_num = "20240253555"
    adapter = _build_warmed_adapter(orange_config, doc_id_cache={doc_num: doc_id})
    detail_html = (
        f"<html><script>selfservice.document.pdfJsUrl = '/ssweb/document-image-pdfjs/{doc_id}/u/{doc_num}.pdf';</script></html>"
    )
    wrapper_html = "<html><body>No iframe/data-href here</body></html>"
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _fake_response(200, text=detail_html),
        _fake_response(200, text=wrapper_html),
    ]
    adapter.session.post.return_value = _fake_response(200, text="true")

    result = adapter.download_pdf(doc_num, tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert "real PDF URL not found" in result["error"]
    assert adapter.session.get.call_count == 2


def test_download_pdf_returns_error_when_response_is_html_not_pdf(orange_config, tmp_path):
    """If the real-PDF GET returns HTML (e.g. disclaimer-reset race), we
    refuse to persist the bytes and the dest file stays absent."""
    doc_id = "DOC3379S37800"
    doc_num = "20220421546"
    adapter = _build_warmed_adapter(orange_config, doc_id_cache={doc_num: doc_id})
    detail_html = (
        "<html><script>"
        f"selfservice.document.pdfJsUrl = '/ssweb/document-image-pdfjs/{doc_id}/uuid-xyz/{doc_num}.pdf';"
        "</script></html>"
    )
    wrapper_html = _wrapper_html_with_real_pdf(doc_id, doc_num)
    not_a_pdf = b"\n\n\n\n<html><body>Disclaimer redirect</body></html>"
    adapter.session = MagicMock()
    adapter.session.get.side_effect = [
        _fake_response(200, text=detail_html),
        _fake_response(200, text=wrapper_html),
        _fake_response(200, content=not_a_pdf),
    ]
    adapter.session.post.return_value = _fake_response(200, text="true")

    result = adapter.download_pdf(doc_num, tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert "not a PDF" in result["error"]
    assert "first 4 bytes" in result["error"]
    assert not (tmp_path / "x.pdf").exists()


def test_download_pdf_handles_relative_and_absolute_paths(orange_config, tmp_path):
    """Three URL shapes the wrapper data-href can take after _absolute_url
    normalization: leading-slash absolute path, schemed absolute URL, and bare
    relative path."""
    pdf_bytes = b"%PDF-1.4\nstub"
    cases = [
        ("/ssweb/document-image-pdf/A//1-1.pdf?index=1", lambda u: u.startswith("https://") and "/ssweb/" in u),
        ("https://other.example.com/foo.pdf", lambda u: u == "https://other.example.com/foo.pdf"),
        ("document-image-pdf/A//2-1.pdf?index=1", lambda u: "document-image-pdf" in u),
    ]
    for i, (real_pdf_path, url_check) in enumerate(cases):
        adapter = _build_warmed_adapter(
            orange_config, doc_id_cache={f"100000000{i}": "DOC_X"}
        )
        adapter.session = MagicMock()
        # 3 GETs: detail (with pdfJsUrl) -> wrapper (with data-href to the
        # cased real_pdf_path) -> real PDF
        detail_html = (
            f"<html><script>selfservice.document.pdfJsUrl = '/ssweb/document-image-pdfjs/DOC_X/u/{i}.pdf';</script></html>"
        )
        wrapper_html = f'<iframe class="ss-pdfjs-lviewer" data-href="{real_pdf_path}"></iframe>'
        adapter.session.get.side_effect = [
            _fake_response(200, text=detail_html),
            _fake_response(200, text=wrapper_html),
            _fake_response(200, content=pdf_bytes),
        ]
        adapter.session.post.return_value = _fake_response(200, text="true")

        result = adapter.download_pdf(f"100000000{i}", tmp_path / f"{i}.pdf")
        assert result["status"] == "success", f"case {i} ({real_pdf_path}) failed: {result}"
        called_pdf_url = adapter.session.get.call_args_list[2].args[0]
        assert url_check(called_pdf_url), f"case {i}: url {called_pdf_url} failed shape check"
