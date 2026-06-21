"""Scaffold tests for ManateeHTTPAdapter.

Verifies:
  1. The adapter imports without pulling Selenium/Playwright/UC.
  2. Construction from the Manatee JSON config + public API surface.
  3. extract_results() parses Manatee's <table id="results"> grid correctly.
  4. Date normalization (MM/DD/YYYY ↔ YYYY-MM-DD).
  5. Failure mode: when the anti-forgery handshake fails, last_failure is set.
  6. perform_search() returns [] (not raises) when session can't warm.
  7. Registry routes platform='manatee_http' → ManateeHTTPAdapter.

Live portal NOT hit — those are end-to-end tests in the case folder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

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
    / "manatee.json"
)


@pytest.fixture(scope="module")
def manatee_config() -> dict:
    with CONFIG_PATH.open("r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1) No browser-driver leakage at import time
# ---------------------------------------------------------------------------

def test_adapter_module_does_not_import_selenium_or_playwright():
    """Manatee HTTP adapter source must not import Selenium / Playwright / UC."""
    import importlib.util

    adapter_path = (
        SRC
        / "titlepro"
        / "search"
        / "recorder"
        / "counties"
        / "adapters"
        / "manatee_http_adapter.py"
    )

    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(
        "_isolated_manatee_http_adapter", adapter_path
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
    ), f"manatee_http_adapter leaked browser modules: {truly_new_leaks}"

    src = adapter_path.read_text(encoding="utf-8")
    for needle in (
        "import selenium",
        "from selenium",
        "import playwright",
        "from playwright",
        "import undetected_chromedriver",
        "from undetected_chromedriver",
    ):
        assert needle not in src, f"forbidden import in adapter: {needle}"


# ---------------------------------------------------------------------------
# 2) Construction
# ---------------------------------------------------------------------------

def test_adapter_constructs_from_manatee_config(manatee_config):
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    assert adapter.county_name == "Manatee"
    assert adapter.base_url.startswith("https://records.manateeclerk.com")
    assert adapter._session_warmed is False
    assert adapter.last_failure is None
    assert adapter.driver is None

    # http_form_fields applied from config
    assert adapter._field_name == "SearchInputs.Party"
    assert adapter._field_date_from == "SearchInputs.StartDate"
    assert adapter._field_date_to == "SearchInputs.EndDate"
    assert adapter._field_doc_type == "SearchInputs.InstrumentTypeId"
    assert adapter._field_page_size == "SearchInputs.PageSize"

    # Doctype codes loaded
    assert adapter._doctype_codes["DEED"] == "11"
    assert adapter._doctype_codes["MORTGAGE"] == "21"


# ---------------------------------------------------------------------------
# 3) Public API surface
# ---------------------------------------------------------------------------

def test_adapter_has_full_api_surface(manatee_config):
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    for method in (
        "warm_session",
        "setup_driver",
        "navigate_to_search",
        "perform_search",
        "pull_detail",
        "extract_results",
        "return_to_search",
        "image_download_url",
    ):
        assert hasattr(adapter, method), f"missing method: {method}"
        assert callable(getattr(adapter, method)), f"not callable: {method}"

    # ABC no-ops return None
    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


# ---------------------------------------------------------------------------
# 4) extract_results() parses Manatee result grid
# ---------------------------------------------------------------------------

MANATEE_RESULTS_FIXTURE = """
<html><body>
<table id="results" class="table table-primary">
  <tr>
    <th class="no-print">View</th>
    <th>Instrument</th>
    <th>From</th>
    <th>To</th>
    <th>Type</th>
    <th>Book</th>
    <th>Page</th>
    <th>Price</th>
    <th>Legal</th>
    <th>Date</th>
    <th>Pages</th>
  </tr>
  <tr class="data-row">
    <td class="no-print">
      <a class="doc-btn" href="/OfficialRecords/DisplayInstrument/4098479">
        <span class="glyphicon glyphicon-file"></span>
      </a>
    </td>
    <td>201841020434</td>
    <td>
      <ol>
        <li>TOIVANEN REIJO</li>
        <li>TOIVANEN PIRJO</li>
      </ol>
    </td>
    <td>
      <ol>
        <li>FERNANDEZ PABLO</li>
        <li>ROZANES DANIELA</li>
      </ol>
    </td>
    <td>DEED                                              </td>
    <td>2716</td>
    <td>2565</td>
    <td>$272,000.00</td>
    <td>LOT 141 SABAL HARBOUR</td>
    <td style="white-space:nowrap;">03-01-2018</td>
    <td>1</td>
  </tr>
  <tr class="data-row">
    <td class="no-print">
      <a class="doc-btn" href="/OfficialRecords/DisplayInstrument/4500001">
        <span class="glyphicon glyphicon-file"></span>
      </a>
    </td>
    <td>202641040260</td>
    <td><ol><li>FERNANDEZ PABLO</li><li>ROZANES DANIELA</li></ol></td>
    <td><ol><li>SOUTHSTATE BANK</li></ol></td>
    <td>MORTGAGE</td>
    <td>3050</td>
    <td>1500</td>
    <td>$115,000.00</td>
    <td>LOT 141 SABAL HARBOUR</td>
    <td style="white-space:nowrap;">04-09-2026</td>
    <td>15</td>
  </tr>
</table>
</body></html>
"""


def test_extract_results_parses_manatee_grid(manatee_config):
    from titlepro.search.recorder.base_recorder import DocumentRecord
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    docs = adapter.extract_results(MANATEE_RESULTS_FIXTURE)

    assert isinstance(docs, list)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)

    by_num = {d.document_number: d for d in docs}
    assert "201841020434" in by_num
    assert "202641040260" in by_num

    d1 = by_num["201841020434"]
    assert d1.recording_date == "03/01/2018"  # normalized from 03-01-2018
    assert d1.document_type == "DEED"
    assert d1.pages == "1"
    assert "TOIVANEN REIJO" in d1.grantors
    assert "TOIVANEN PIRJO" in d1.grantors
    assert "FERNANDEZ PABLO" in d1.grantees
    assert "ROZANES DANIELA" in d1.grantees

    d2 = by_num["202641040260"]
    assert d2.document_type == "MORTGAGE"
    assert d2.recording_date == "04/09/2026"
    assert "FERNANDEZ PABLO" in d2.grantors
    assert "SOUTHSTATE BANK" in d2.grantees


def test_extract_results_empty_html_returns_empty(manatee_config):
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body>no results</body></html>") == []


# ---------------------------------------------------------------------------
# 5) Date normalization
# ---------------------------------------------------------------------------

def test_normalize_date_accepts_both_formats(manatee_config):
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    assert adapter._normalize_date("01/01/2010") == "2010-01-01"
    assert adapter._normalize_date("5/26/2026") == "2026-05-26"
    assert adapter._normalize_date("2010-01-01") == "2010-01-01"
    assert adapter._normalize_date("") == ""


# ---------------------------------------------------------------------------
# 6) Failure mode contract
# ---------------------------------------------------------------------------

def test_warm_session_sets_failure_flag_when_token_get_fails(monkeypatch, manatee_config):
    """When the GET to the Party page fails, warm_session must return False
    and set last_failure='needs_session_token'."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(adapter, "_refresh_antiforgery_token", boom)

    ok = adapter.warm_session()
    assert ok is False
    assert adapter.last_failure == "needs_session_token"


def test_perform_search_returns_empty_when_session_unwarmed(monkeypatch, manatee_config):
    """If warm_session can't acquire a token, perform_search returns []
    (pipeline branches on adapter.last_failure)."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(adapter, "_refresh_antiforgery_token", boom)

    result = adapter.perform_search("FERNANDEZ PABLO", party_type="Both")
    assert result == []
    assert adapter.last_failure == "needs_session_token"


# ---------------------------------------------------------------------------
# 7) Image download URL composition
# ---------------------------------------------------------------------------

def test_image_download_url_composition(manatee_config):
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    url = adapter.image_download_url("4098479")
    assert url == (
        "https://records.manateeclerk.com/OfficialRecords/"
        "DisplayInstrument/InstrumentResultFile/4098479/1/1"
    )


# ---------------------------------------------------------------------------
# 8) Registry wiring
# ---------------------------------------------------------------------------

def test_registry_manatee_http_platform_resolves(manatee_config):
    """The registry must route platform='manatee_http' → ManateeHTTPAdapter."""
    from titlepro.search.recorder.counties import registry
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = registry.get_recorder("fl_manatee")
    assert isinstance(adapter, ManateeHTTPAdapter)
    # registry config flipped to manatee_http
    info = registry.get_county_info("fl_manatee")
    assert info["platform"] == "manatee_http"
    assert info.get("stub") is not True


# ---------------------------------------------------------------------------
# 9) Doc-type code mapping in payload
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 10) download_pdf — canonical pipeline entry point
# ---------------------------------------------------------------------------

def test_download_pdf_method_exists(manatee_config):
    """The pipeline-canonical download_pdf() method must be present + callable."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    assert hasattr(adapter, "download_pdf")
    assert callable(adapter.download_pdf)
    # Recipe-config values from manatee.json
    assert "{doc_id}" in adapter._dip_pdf_url_template
    assert adapter._dip_assert_pdf_magic is True
    assert hasattr(adapter, "_doc_id_by_number")


def test_extract_results_populates_doc_id_cache(manatee_config):
    """The doc_id from the view-icon <a href> must be cached per-Instrument."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    adapter.extract_results(MANATEE_RESULTS_FIXTURE)
    # The view-icon href in the fixture is /OfficialRecords/DisplayInstrument/4098479
    # → instrument 201841020434 maps to doc_id "4098479".
    assert adapter._doc_id_by_number["201841020434"] == "4098479"
    assert adapter._doc_id_by_number["202641040260"] == "4500001"


def test_download_pdf_happy_path(monkeypatch, manatee_config, tmp_path):
    """Use cached doc_id → recipe URL → write PDF bytes."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    adapter._session_warmed = True
    adapter._doc_id_by_number = {"201841020434": "4098479"}

    pdf_bytes = b"%PDF-1.5\nmock-manatee-deed\n%%EOF"
    captured: dict[str, Any] = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        resp.content = pdf_bytes
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "201841020434.pdf"
    result = adapter.download_pdf("201841020434", dest)

    assert result["status"] == "success", result
    assert result["size"] == len(pdf_bytes)
    assert result["src_via"] == "instrument_result_file"
    assert result["pdf_url"].endswith("/4098479/1/1")
    assert dest.read_bytes() == pdf_bytes
    # Referer header is set for the static-image GET.
    assert captured["headers"]["Referer"].endswith("/Party")


def test_download_pdf_returns_error_when_no_doc_id_and_no_search(
    monkeypatch, manatee_config, tmp_path
):
    """If neither cache has the doc_id and pull_detail can't find it,
    surface a clean error."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    adapter._session_warmed = True
    adapter._antiforgery_token = "TOK"

    # pull_detail will try a search; we make the search POST return zero rows.
    def fake_get(url, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><body>no results</body></html>"
        return resp

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html><body>no results</body></html>"
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)
    monkeypatch.setattr(adapter.session, "post", fake_post)

    result = adapter.download_pdf("999999999999", tmp_path / "x.pdf")
    assert result["status"] == "error"


def test_download_pdf_returns_error_on_non_pdf_response(monkeypatch, manatee_config, tmp_path):
    """If the image URL responds with HTML rather than %PDF bytes, surface error."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)
    adapter._session_warmed = True
    adapter._doc_id_by_number = {"201841020434": "4098479"}

    def fake_get(url, headers=None, timeout=None, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"<html><body>not a pdf</body></html>"
        return resp

    monkeypatch.setattr(adapter.session, "get", fake_get)

    result = adapter.download_pdf("201841020434", tmp_path / "x.pdf")
    assert result["status"] == "error"
    assert "non-PDF" in result["message"]


def test_perform_search_maps_doc_type_label_to_code(monkeypatch, manatee_config):
    """When perform_search is given doc_type='DEED', the outgoing payload's
    InstrumentTypeId field should carry the numeric code '11' from
    doctype_codes config."""
    from titlepro.search.recorder.counties.adapters.manatee_http_adapter import (
        ManateeHTTPAdapter,
    )

    adapter = ManateeHTTPAdapter(manatee_config)

    # Pretend session is warmed
    adapter._session_warmed = True
    adapter._antiforgery_token = "FAKE_TOKEN"

    captured = {}

    class _FakeResp:
        status_code = 200
        text = "<html><body></body></html>"

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return _FakeResp()

    monkeypatch.setattr(adapter.session, "post", fake_post)

    adapter.perform_search(
        "FERNANDEZ PABLO",
        party_type="Both",
        doc_type="DEED",
        date_from="01/01/2010",
        date_to="05/26/2026",
    )

    payload = captured["data"]
    assert payload["SearchInputs.InstrumentTypeId"] == "11"
    assert payload["SearchInputs.Party"] == "FERNANDEZ PABLO"
    assert payload["SearchInputs.StartDate"] == "2010-01-01"
    assert payload["SearchInputs.EndDate"] == "2026-05-26"
    assert payload["__RequestVerificationToken"] == "FAKE_TOKEN"
    assert payload["SearchInputs.SearchType"] == "Party"
    assert payload["SearchInputs.PageSize"] == "100"
