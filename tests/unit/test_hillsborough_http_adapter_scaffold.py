"""Scaffold tests for HillsboroughHTTPAdapter.

These tests verify:
  1. The adapter imports cleanly with no Selenium / Playwright module pulls.
  2. The adapter constructs from the Hillsborough JSON config.
  3. The public API surface exists (warm_session, perform_search, pull_detail,
     pull_pdf, extract_results, return_to_search, plus the ABC no-ops).
  4. extract_results() correctly parses a JSON ResultList payload into
     DocumentRecord instances (the canonical Hillsborough shape).
  5. _normalize_name() canonicalizes "LAST, FIRST" -> "LAST FIRST".
  6. _epoch_to_mmddyyyy() converts Hillsborough's epoch RecordDate.
  7. Registry routing: platform="hillsborough_http" -> HillsboroughHTTPAdapter.
  8. perform_search() builds a JSON payload and parses a mocked response.
  9. pull_pdf() uses the cached opaque ID to fetch the watermark endpoint.

The tests intentionally do NOT hit the live Hillsborough portal — end-to-end
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
    / "hillsborough.json"
)


@pytest.fixture(scope="module")
def hillsborough_config() -> dict:
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
    sys.modules state.
    """
    import importlib.util

    adapter_path = (
        SRC
        / "titlepro"
        / "search"
        / "recorder"
        / "counties"
        / "adapters"
        / "hillsborough_http_adapter.py"
    )

    before = set(sys.modules.keys())

    spec = importlib.util.spec_from_file_location(
        "_isolated_hillsborough_http_adapter", adapter_path
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
    ), f"HTTP adapter source file leaked browser modules: {truly_new_leaks}"

    # Independent sanity check: source-level — no selenium/playwright imports.
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

def test_adapter_constructs_from_hillsborough_config(hillsborough_config):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    assert adapter.county_name == "Hillsborough"
    assert adapter.base_url.startswith("https://publicaccess.hillsclerk.com/")
    # State indicators initialized
    assert adapter._session_warmed is False
    assert adapter.last_failure is None
    assert adapter.driver is None
    # Field-name mapping applied from config
    assert adapter._field_name == "PartyName"
    assert adapter._field_doc_type == "DocType"
    assert adapter._field_date_from == "RecordDateFrom"
    assert adapter._field_date_to == "RecordDateTo"
    assert adapter._field_instrument == "Instrument"
    assert adapter._doctype_deed_value == "(D) DEED"
    assert adapter._http_search_endpoint.endswith("/api/Search")


def test_adapter_has_full_api_surface(hillsborough_config):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    for method in (
        "warm_session",
        "setup_driver",
        "navigate_to_search",
        "perform_search",
        "pull_detail",
        "pull_pdf",
        "extract_results",
        "return_to_search",
    ):
        assert hasattr(adapter, method), f"missing method: {method}"
        assert callable(getattr(adapter, method)), f"not callable: {method}"

    # ABC no-ops return None
    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


# ---------------------------------------------------------------------------
# 4) extract_results() parses Hillsborough JSON
# ---------------------------------------------------------------------------

HILLSBOROUGH_JSON_FIXTURE = {
    "Success": True,
    "ErrorMessage": None,
    "Truncated": None,
    "ResultList": [
        {
            "Instrument": 2025214758,
            "PartiesOne": ["FROMER ALANA", "FROMER MICHAEL A"],
            "PartiesTwo": ["FROMER ALANA", "FROMER MICHAEL A"],
            "RecordDate": 1747407459,
            "DocType": "(D) DEED",
            "BookType": None,
            "BookNum": None,
            "PageNum": None,
            "Legal": "PT L 4 & 5 B 12 NORTH ROSEDALE",
            "SalesPrice": 10.0,
            "ID": "OPAQUE_ID_AAAA",
            "PageCount": 1,
            "UUID": "5295E79E02E7CE1A39E9BD909FD3727E435E46794857EE8EA1007F5795860723",
        },
        {
            "Instrument": 2026161803,
            "PartiesOne": ["FROMER ALANA", "FROMER MICHAEL"],
            "PartiesTwo": ["TRUIST BANK"],
            "RecordDate": 1777301574,
            "DocType": "(MTG) MORTGAGE",
            "BookType": None,
            "BookNum": None,
            "PageNum": None,
            "Legal": "SEE IMAGE",
            "SalesPrice": None,
            "ID": "OPAQUE_ID_BBBB",
            "PageCount": 7,
            "UUID": "2D996CC07CEFC0058CD550FEF997660CC7441A31557BC9F0AA3A68E64298508B",
        },
    ],
    "CertificationFees": None,
}


def test_extract_results_parses_json_payload(hillsborough_config):
    from titlepro.search.recorder.base_recorder import DocumentRecord
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    docs = adapter.extract_results(HILLSBOROUGH_JSON_FIXTURE)

    assert isinstance(docs, list)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)

    by_num = {d.document_number: d for d in docs}
    assert "2025214758" in by_num
    assert "2026161803" in by_num

    deed = by_num["2025214758"]
    assert deed.document_type == "(D) DEED"
    # Epoch 1747407459 -> 05/16/2025 (UTC)
    assert deed.recording_date == "05/16/2025"
    assert "FROMER ALANA" in deed.grantors
    assert "FROMER MICHAEL A" in deed.grantees
    assert deed.pages == "1"

    mtg = by_num["2026161803"]
    assert mtg.document_type == "(MTG) MORTGAGE"
    assert "TRUIST BANK" in mtg.grantees

    # Cache populated for downloader
    assert adapter._id_cache["2025214758"] == "OPAQUE_ID_AAAA"
    assert adapter._id_cache["2026161803"] == "OPAQUE_ID_BBBB"


def test_extract_results_handles_string_and_empty(hillsborough_config):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    # Empty / None
    assert adapter.extract_results(None) == []
    assert adapter.extract_results("") == []
    # JSON string
    docs = adapter.extract_results(json.dumps(HILLSBOROUGH_JSON_FIXTURE))
    assert len(docs) == 2
    # Bare list
    docs = adapter.extract_results(HILLSBOROUGH_JSON_FIXTURE["ResultList"])
    assert len(docs) == 2


# ---------------------------------------------------------------------------
# 5/6) Helpers
# ---------------------------------------------------------------------------

def test_normalize_name_canonicalizes_last_first():
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    norm = HillsboroughHTTPAdapter._normalize_name
    assert norm("FROMER, MICHAEL") == "FROMER MICHAEL"
    assert norm("FROMER MICHAEL") == "FROMER MICHAEL"
    assert norm("fromer michael") == "FROMER MICHAEL"
    assert norm("Del Monte, Angel") == "DEL MONTE ANGEL"
    assert norm("  Fromer ,  Michael  ") == "FROMER MICHAEL"
    assert norm("") == ""


def test_epoch_to_mmddyyyy_conversion():
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    cv = HillsboroughHTTPAdapter._epoch_to_mmddyyyy
    # 1747407459 = 2025-05-16 ~17:37 UTC
    assert cv(1747407459) == "05/16/2025"
    # 792374400 = 1995-02-10 00:00 UTC (the DEL MONTE deed - the Clerk
    # appears to record the date as the UTC midnight before the actual
    # filing day; this is consistent across the entire archive).
    assert cv(792374400) == "02/10/1995"
    assert cv(None) == ""
    assert cv("not-a-number") == "not-a-number"


# ---------------------------------------------------------------------------
# 7) Registry routing
# ---------------------------------------------------------------------------

def test_registry_hillsborough_http_platform_resolves():
    from titlepro.search.recorder.counties import registry
    adapter = registry.get_recorder("fl_hillsborough")
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )
    assert isinstance(adapter, HillsboroughHTTPAdapter)
    assert adapter.county_name == "Hillsborough"


# ---------------------------------------------------------------------------
# 8) perform_search builds JSON payload + parses mocked response
# ---------------------------------------------------------------------------

def test_perform_search_with_mocked_session(hillsborough_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True  # skip warm-up

    captured: dict[str, Any] = {}

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: HILLSBOROUGH_JSON_FIXTURE
        return resp

    monkeypatch.setattr(adapter.session, "post", fake_post)

    docs = adapter.perform_search(
        "FROMER, MICHAEL",
        party_type="Grantor/Grantee",
        doc_type="DEED",
        date_from="01/01/2010",
        date_to="05/26/2026",
    )
    assert len(docs) == 2

    payload = json.loads(captured["data"])
    assert payload["PartyName"] == ["FROMER MICHAEL"]  # normalized
    assert payload["DocType"] == ["(D) DEED"]  # semantic -> Hillsborough code
    assert payload["RecordDateFrom"] == "01/01/2010"
    assert payload["RecordDateTo"] == "05/26/2026"
    assert captured["headers"]["Content-Type"].startswith("application/json")


def test_perform_search_returns_empty_when_session_fails(hillsborough_config, monkeypatch):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)

    # Block warm_session by making the landing GET fail.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated network failure")
    monkeypatch.setattr(adapter.session, "get", boom)

    docs = adapter.perform_search("FROMER MICHAEL", party_type="All")
    assert docs == []
    assert adapter.last_failure and adapter.last_failure.startswith("landing_error")


# ---------------------------------------------------------------------------
# 9) pull_pdf flow
# ---------------------------------------------------------------------------

def test_pull_pdf_uses_cached_id_and_writes_file(hillsborough_config, monkeypatch, tmp_path):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True
    adapter._id_cache["2025214758"] = "OPAQUE_ID_AAAA"

    captured: dict[str, Any] = {}

    pdf_bytes = b"%PDF-1.7\n%fake-hillsborough-pdf\n%%EOF"

    def fake_get(url, timeout=None, **kw):
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        resp.content = pdf_bytes
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "2025214758.pdf"
    result = adapter.pull_pdf("2025214758", dest)

    assert result["status"] == "success"
    assert result["size"] == len(pdf_bytes)
    assert dest.exists() and dest.read_bytes()[:4] == b"%PDF"
    assert "OPAQUE_ID_AAAA" in captured["url"]
    assert "Watermark" in captured["url"]


def test_pull_pdf_handles_non_pdf_response(hillsborough_config, monkeypatch, tmp_path):
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True
    adapter._id_cache["999"] = "BADID"

    def fake_get(url, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"<html>not a pdf</html>"
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    result = adapter.pull_pdf("999", tmp_path / "999.pdf")
    assert result["status"] == "error"
    assert "non-PDF" in result["message"]


# ---------------------------------------------------------------------------
# 10) download_pdf — canonical pipeline entry point
# ---------------------------------------------------------------------------

def test_download_pdf_method_exists(hillsborough_config):
    """The pipeline-canonical download_pdf() method must be present + callable."""
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    assert hasattr(adapter, "download_pdf")
    assert callable(adapter.download_pdf)
    # Recipe-config values from hillsborough.json
    assert "{id}" in adapter._dip_pdf_url_template
    assert adapter._dip_assert_pdf_magic is True


def test_pull_pdf_is_back_compat_alias_for_download_pdf(hillsborough_config, monkeypatch, tmp_path):
    """pull_pdf() must delegate to download_pdf() for backwards compatibility."""
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True
    adapter._doc_id_by_number["2025214758"] = "OPAQUE_ID_AAAA"

    pdf_bytes = b"%PDF-1.7\nfake\n%%EOF"

    def fake_get(url, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = pdf_bytes
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "out.pdf"
    via_pull = adapter.pull_pdf("2025214758", dest)
    assert via_pull["status"] == "success"
    assert via_pull["size"] == len(pdf_bytes)


def test_download_pdf_uses_doc_id_by_number_cache(hillsborough_config, monkeypatch, tmp_path):
    """download_pdf() must resolve doc_id via _doc_id_by_number (pipeline sidecar
    key), not require a fresh search."""
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True
    # Simulate pipeline rehydrate — replacing the alias.
    adapter._doc_id_by_number = {"2025214758": "OPAQUE_ID_AAAA"}

    pdf_bytes = b"%PDF-1.7\nfake\n%%EOF"
    captured: dict[str, Any] = {}

    def fake_get(url, timeout=None, **kw):
        captured["url"] = url
        resp = MagicMock()
        resp.status_code = 200
        resp.content = pdf_bytes
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "2025214758.pdf"
    result = adapter.download_pdf("2025214758", dest)

    assert result["status"] == "success"
    assert result["src_via"] == "watermark_api"
    assert "OPAQUE_ID_AAAA" in captured["url"]
    assert "Watermark" in captured["url"]
    assert dest.read_bytes() == pdf_bytes


def test_download_pdf_returns_error_when_no_id_and_no_search(hillsborough_config, monkeypatch, tmp_path):
    """If neither cache has the doc_id and pull_detail returns an error,
    surface a clean error dict."""
    from titlepro.search.recorder.counties.adapters.hillsborough_http_adapter import (
        HillsboroughHTTPAdapter,
    )

    adapter = HillsboroughHTTPAdapter(hillsborough_config)
    adapter._session_warmed = True

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 500
        resp.json = lambda: {}
        return resp

    monkeypatch.setattr(adapter.session, "post", fake_post)

    result = adapter.download_pdf("999", tmp_path / "999.pdf")
    assert result["status"] == "error"
    assert "HTTP 500" in result["message"] or "no opaque" in result["message"]
