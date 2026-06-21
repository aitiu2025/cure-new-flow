"""Scaffold tests for AcclaimWebHTTPAdapter.

These tests verify:
  1. The adapter imports cleanly with no Selenium / Playwright module pulls.
  2. The adapter constructs from the Broward JSON config.
  3. The public API surface exists (warm_session, perform_search, pull_detail,
     extract_results, return_to_search, plus the ABC no-ops).
  4. extract_results() correctly parses a Kendo/Telerik grid HTML fixture
     into DocumentRecord instances.
  5. pull_detail()'s static HTML parser returns the expected dict shape.

The tests intentionally do NOT hit the live Broward portal — end-to-end
validation is a downstream step.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
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
    / "broward.json"
)


@pytest.fixture(scope="module")
def broward_config() -> dict:
    with CONFIG_PATH.open("r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1) No browser-driver leakage at import time
# ---------------------------------------------------------------------------

def test_adapter_module_does_not_import_selenium_or_playwright():
    """The HTTP adapter module itself must not pull in any browser-automation libs.

    NOTE: ``counties/adapters/__init__.py`` eagerly imports the Selenium-based
    sibling adapters (tyler, recorderworks), so importing via the package is
    guaranteed to leak. We isolate the HTTP adapter by loading it directly
    from its file via ``importlib.util.spec_from_file_location`` in a clean
    subprocess-equivalent sys.modules state.
    """
    import importlib.util

    adapter_path = (
        SRC
        / "titlepro"
        / "search"
        / "recorder"
        / "counties"
        / "adapters"
        / "acclaimweb_http_adapter.py"
    )

    # Snapshot which modules are present BEFORE direct file-level import.
    before = set(sys.modules.keys())

    spec = importlib.util.spec_from_file_location(
        "_isolated_acclaimweb_http_adapter", adapter_path
    )
    module = importlib.util.module_from_spec(spec)
    # Run the module body. This is what would have side effects.
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
    # Filter out modules that were ALREADY loaded by other tests via the
    # package __init__. We only care about NEW leaks attributable to the
    # HTTP adapter's own ``import`` lines.
    truly_new_leaks = [m for m in leaked if m not in before]
    # But `before` already contains any selenium modules loaded prior, so
    # `truly_new_leaks` == [] guarantees the HTTP adapter file added none.
    # The interesting assertion is on truly_new_leaks:
    assert (
        not truly_new_leaks
    ), f"HTTP adapter source file leaked browser modules: {truly_new_leaks}"

    # Independent sanity check: source-level — no selenium/playwright import
    # statements appear in the adapter file.
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
        ), f"HTTP adapter source contains forbidden import: {needle}"


# ---------------------------------------------------------------------------
# 2) Construction + 3) public API surface
# ---------------------------------------------------------------------------

def test_adapter_constructs_from_broward_config(broward_config):
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    adapter = AcclaimWebHTTPAdapter(broward_config)
    assert adapter.county_name == "Broward"
    assert adapter.base_url.startswith("https://officialrecords.broward.org/")
    # State indicators initialized
    assert adapter._session_warmed is False
    assert adapter.last_failure is None
    # Driver attribute must exist (ABC contract) but be None.
    assert adapter.driver is None
    # Field-name mapping applied from config
    assert adapter._field_name == "SearchOnName"
    assert adapter._field_date_from == "RecordDateFrom"
    assert adapter._field_date_to == "RecordDateTo"
    assert adapter._field_doc_type == "DocTypes"
    assert adapter._cloudflare_required is True


def test_adapter_has_full_api_surface(broward_config):
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    adapter = AcclaimWebHTTPAdapter(broward_config)

    # Required public methods
    for method in (
        "warm_session",
        "setup_driver",
        "navigate_to_search",
        "perform_search",
        "pull_detail",
        "extract_results",
        "return_to_search",
    ):
        assert hasattr(adapter, method), f"missing method: {method}"
        assert callable(getattr(adapter, method)), f"not callable: {method}"

    # ABC no-ops must return None (and not blow up)
    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


# ---------------------------------------------------------------------------
# 4) extract_results() parses Kendo/Telerik grid HTML
# ---------------------------------------------------------------------------

TELERIK_GRID_FIXTURE = """
<html><body>
<div class="t-grid">
  <table>
    <thead>
      <tr>
        <th>Doc #</th><th>Type</th><th>Date</th>
        <th>Grantor</th><th>Grantee</th><th>Pages</th>
      </tr>
    </thead>
    <tbody>
      <tr class="t-row">
        <td><a href="/AcclaimWeb/details/120826721">120826721</a></td>
        <td>DEED</td>
        <td>03/15/2022</td>
        <td>ANAND RISHI G</td>
        <td>SMITH JANE</td>
        <td>3</td>
      </tr>
      <tr class="t-alt">
        <td>120228315</td>
        <td>MTG</td>
        <td>06/22/2020</td>
        <td>ANAND RISHI G</td>
        <td>WELLS FARGO BANK</td>
        <td>15</td>
      </tr>
    </tbody>
  </table>
</div>
</body></html>
"""


def test_extract_results_parses_telerik_grid(broward_config):
    from titlepro.search.recorder.base_recorder import DocumentRecord
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    adapter = AcclaimWebHTTPAdapter(broward_config)
    docs = adapter.extract_results(TELERIK_GRID_FIXTURE)

    assert isinstance(docs, list)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)

    by_num = {d.document_number: d for d in docs}
    assert "120826721" in by_num
    assert "120228315" in by_num

    d1 = by_num["120826721"]
    assert d1.recording_date == "03/15/2022"
    assert d1.document_type == "DEED"
    assert d1.pages == "3"
    # Heuristic name-detection grabs first long string as grantors,
    # second as grantees.
    assert "ANAND" in d1.grantors
    assert "SMITH" in d1.grantees


def test_extract_results_empty_html_returns_empty(broward_config):
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    adapter = AcclaimWebHTTPAdapter(broward_config)
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body>nothing</body></html>") == []


# ---------------------------------------------------------------------------
# 5) pull_detail() static HTML parser
# ---------------------------------------------------------------------------

DETAIL_HTML_FIXTURE = """
<html><body>
<table class="details">
  <tr><td>Document Number</td><td>120826721</td></tr>
  <tr><td>Recording Date</td><td>03/15/2022</td></tr>
  <tr><td>Doc Type</td><td>DEED</td></tr>
  <tr><td>Parcel ID</td><td>5142 16 04 0010</td></tr>
  <tr><td>Book/Page</td><td>12345 / 678</td></tr>
</table>
<table class="parties">
  <tr><th>Role</th><th>Party Name</th></tr>
  <tr><td>Grantor</td><td>ANAND RISHI G</td></tr>
  <tr><td>Grantee</td><td>SMITH JANE</td></tr>
</table>
</body></html>
"""


def test_pull_detail_parser_returns_indexed_apn_and_parties():
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    detail = AcclaimWebHTTPAdapter._parse_detail_html(DETAIL_HTML_FIXTURE, "120826721")

    assert isinstance(detail, dict)
    assert detail["document_number"] == "120826721"
    assert detail["recording_date"] == "03/15/2022"
    assert detail["doc_type"] == "DEED"
    assert detail["indexed_apn"] == "5142 16 04 0010"
    assert detail["book_page"].startswith("12345")

    parties = detail["parties"]
    assert isinstance(parties, list)
    roles = {p["role"] for p in parties}
    assert "Grantor" in roles and "Grantee" in roles


# ---------------------------------------------------------------------------
# 6) Failure mode contract
# ---------------------------------------------------------------------------

def test_warm_session_sets_failure_flag_when_handshake_fails(monkeypatch, broward_config, tmp_path):
    """When the pure-HTTP disclaimer handshake fails (network outage, CF
    upgrade, etc.), warm_session must set last_failure='needs_session_token'
    and return False.
    """
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    cfg["cookie_jar_path"] = str(tmp_path / "does_not_exist.json")
    adapter = AcclaimWebHTTPAdapter(cfg)

    # Force the disclaimer handshake to fail.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr(adapter, "_handshake_disclaimer", boom)

    ok = adapter.warm_session()
    assert ok is False
    assert adapter.last_failure == "needs_session_token"


def test_perform_search_returns_empty_when_session_unwarmed(monkeypatch, broward_config, tmp_path):
    """If warm_session can't acquire cookies, perform_search must return []
    rather than crashing — pipeline branches on adapter.last_failure.
    """
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    cfg["cookie_jar_path"] = str(tmp_path / "missing.json")
    adapter = AcclaimWebHTTPAdapter(cfg)

    # Block the handshake so the session can never warm.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr(adapter, "_handshake_disclaimer", boom)

    result = adapter.perform_search("DOE JANE", party_type="All")
    assert result == []
    assert adapter.last_failure == "needs_session_token"


# ---------------------------------------------------------------------------
# 7) download_pdf() — recipe-driven multi-step Broward flow
# ---------------------------------------------------------------------------

JUMP_HTML_FIXTURE = """
<html><body>
<form>
  <input type="hidden" id="hdnTransactionItemId" value="TXN_ABCDEFGHIJK_42" />
  <input type="hidden" name="otherField" value="ignored" />
</form>
</body></html>
"""

VIEWER_HTML_FIXTURE = """
<html><body>
<script>
  var pdfSrc = "/WebAtalaCache/a1b2c3d4e5_42_docPdf.pdf";
</script>
</body></html>
"""


def _make_resp(status_code=200, text="", content=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    return resp


def test_download_pdf_method_exists(broward_config):
    """The recipe-config-driven download_pdf() method must be present + callable."""
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    adapter = AcclaimWebHTTPAdapter(broward_config)
    assert hasattr(adapter, "download_pdf")
    assert callable(adapter.download_pdf)
    # Recipe-config values loaded from broward.json
    assert adapter._dip_record_type == 27
    assert len(adapter._dip_token_regex_options) >= 2
    assert "JumpToInstrumentNumber" in adapter._dip_jump_url


def test_download_pdf_happy_path(monkeypatch, broward_config, tmp_path):
    """Successful flow: jump → start_image_retrieval → viewer → fetch PDF.

    Mocks the session's GET to walk through the four stages. Verifies the
    function writes the PDF to dest_path and returns the canonical success
    dict shape.
    """
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    # Speed up the test: no delays / retries
    cfg["doc_image_url_pattern"] = {
        **broward_config.get("doc_image_url_pattern", {}),
        "pre_pdf_delay_seconds": 0,
        "pdf_fetch_retries": 1,
        "pdf_retry_delay_seconds": 0,
    }
    adapter = AcclaimWebHTTPAdapter(cfg)
    adapter._session_warmed = True

    pdf_bytes = b"%PDF-1.7\nmock-broward-deed\n%%EOF"
    captured_urls: list[str] = []

    def fake_get(url, headers=None, timeout=None, **kw):
        captured_urls.append(url)
        if "JumpToInstrumentNumber" in url:
            return _make_resp(200, text=JUMP_HTML_FIXTURE)
        if "StartImageRetrieval" in url:
            return _make_resp(200)
        if "DocumentImage1" in url:
            return _make_resp(200, text=VIEWER_HTML_FIXTURE)
        if "WebAtalaCache" in url:
            return _make_resp(200, content=pdf_bytes)
        return _make_resp(404)

    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "120826721.pdf"
    result = adapter.download_pdf("120826721", dest)

    assert result["status"] == "success", result
    assert result["size"] == len(pdf_bytes)
    assert result["src_via"] == "jump_response"
    assert "WebAtalaCache" in result["pdf_url"]
    assert result["token"] == "TXN_ABCDEFGHIJK_42"
    assert dest.exists() and dest.read_bytes()[:4] == b"%PDF"
    # All four stage URLs were hit (in order).
    assert any("JumpToInstrumentNumber/27/120826721" in u for u in captured_urls)
    assert any("StartImageRetrieval/TXN_ABCDEFGHIJK_42" in u for u in captured_urls)
    assert any("DocumentImage1/TXN_ABCDEFGHIJK_42" in u for u in captured_urls)
    assert any("WebAtalaCache/a1b2c3d4e5_42_docPdf.pdf" in u for u in captured_urls)


def test_download_pdf_returns_error_when_token_missing(monkeypatch, broward_config, tmp_path):
    """If the jump response has no hdnTransactionItemId, return status=error."""
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    cfg["doc_image_url_pattern"] = {
        **broward_config.get("doc_image_url_pattern", {}),
        "pre_pdf_delay_seconds": 0,
        "pdf_fetch_retries": 1,
        "pdf_retry_delay_seconds": 0,
    }
    adapter = AcclaimWebHTTPAdapter(cfg)
    adapter._session_warmed = True

    def fake_get(url, headers=None, timeout=None, **kw):
        return _make_resp(200, text="<html><body>no token here</body></html>")

    monkeypatch.setattr(adapter.session, "get", fake_get)

    result = adapter.download_pdf("120826721", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert result["phase"] == "token_extract"


def test_download_pdf_returns_error_on_non_pdf_response(monkeypatch, broward_config, tmp_path):
    """If the final PDF GET returns HTML instead of %PDF bytes, surface error."""
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    cfg["doc_image_url_pattern"] = {
        **broward_config.get("doc_image_url_pattern", {}),
        "pre_pdf_delay_seconds": 0,
        "pdf_fetch_retries": 1,
        "pdf_retry_delay_seconds": 0,
    }
    adapter = AcclaimWebHTTPAdapter(cfg)
    adapter._session_warmed = True

    def fake_get(url, headers=None, timeout=None, **kw):
        if "JumpToInstrumentNumber" in url:
            return _make_resp(200, text=JUMP_HTML_FIXTURE)
        if "StartImageRetrieval" in url:
            return _make_resp(200)
        if "DocumentImage1" in url:
            return _make_resp(200, text=VIEWER_HTML_FIXTURE)
        if "WebAtalaCache" in url:
            return _make_resp(200, content=b"<html>not a pdf</html>")
        return _make_resp(404)

    monkeypatch.setattr(adapter.session, "get", fake_get)

    result = adapter.download_pdf("120826721", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert result["phase"] == "fetch_pdf"


def test_download_pdf_returns_error_when_viewer_missing_pdf_href(monkeypatch, broward_config, tmp_path):
    """When the viewer HTML lacks a WebAtalaCache href, surface a phased error."""
    from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
        AcclaimWebHTTPAdapter,
    )

    cfg = dict(broward_config)
    cfg["doc_image_url_pattern"] = {
        **broward_config.get("doc_image_url_pattern", {}),
        "pre_pdf_delay_seconds": 0,
        "pdf_fetch_retries": 1,
        "pdf_retry_delay_seconds": 0,
    }
    adapter = AcclaimWebHTTPAdapter(cfg)
    adapter._session_warmed = True

    def fake_get(url, headers=None, timeout=None, **kw):
        if "JumpToInstrumentNumber" in url:
            return _make_resp(200, text=JUMP_HTML_FIXTURE)
        if "StartImageRetrieval" in url:
            return _make_resp(200)
        if "DocumentImage1" in url:
            return _make_resp(200, text="<html><body>no pdf href</body></html>")
        return _make_resp(404)

    monkeypatch.setattr(adapter.session, "get", fake_get)

    result = adapter.download_pdf("120826721", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert result["phase"] == "extract_pdf_url"
    assert result["token"] == "TXN_ABCDEFGHIJK_42"


# ---------------------------------------------------------------------------
# 8) Registry wiring sanity check
# ---------------------------------------------------------------------------

def test_registry_acclaimweb_http_platform_resolves(broward_config, monkeypatch):
    """The registry must route platform='acclaimweb_http' to the new adapter.

    We monkey-patch the registry entry for fl_broward temporarily so we don't
    have to flip the production wiring (the comment in registry.py asks us to
    keep that on 'acclaimweb' until live validation).
    """
    from titlepro.search.recorder.counties import registry

    original = dict(registry.COUNTY_REGISTRY["fl_broward"])
    try:
        registry.COUNTY_REGISTRY["fl_broward"] = {
            **original,
            "platform": "acclaimweb_http",
        }
        adapter = registry.get_recorder("fl_broward")
        from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (
            AcclaimWebHTTPAdapter,
        )
        assert isinstance(adapter, AcclaimWebHTTPAdapter)
    finally:
        registry.COUNTY_REGISTRY["fl_broward"] = original
