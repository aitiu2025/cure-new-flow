"""Scaffold tests for PascoHTTPAdapter (Pasco County FL recorder — Wave-1).

Verifies:
  1. No Selenium / Playwright module pulls.
  2. Construction from config/fl/pasco.json.
  3. Public API surface (warm_session, perform_search, pull_detail,
     download_pdf, extract_results, ABC no-ops).
  4. build_name_search_payload emits the verbatim wire shape captured in the
     2026-06-10 probe (deed-first docset label, namedir A/D/R, ISO dates).
  5. _normalize_name / _to_iso_date / _to_mmddyyyy conversions.
  6. extract_results parses the SYNTHETIC results fixture (live result-row
     HTML is unverified until the first user-approved Wave-2 POST — this
     fixture locks the parser CONTRACT, not the live markup).
  7. perform_search / pull_detail against a mocked session.
  8. download_pdf returns a structured error when no image href is known.

No live HTTP is performed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Locate the repo root by walking up until we find src/titlepro — works both
# from tests/unit/ (canonical home) and from the case-dir staging location.
_here = Path(__file__).resolve()
REPO_ROOT = next(
    p for p in _here.parents if (p / "src" / "titlepro").is_dir()
)
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONFIG_PATH = (
    SRC / "titlepro" / "search" / "recorder" / "counties" / "config" / "fl" / "pasco.json"
)
ADAPTER_PATH = (
    SRC / "titlepro" / "search" / "recorder" / "counties" / "adapters" / "pasco_http_adapter.py"
)


@pytest.fixture(scope="module")
def pasco_config() -> dict:
    with CONFIG_PATH.open("r") as f:
        return json.load(f)


@pytest.fixture()
def adapter(pasco_config):
    from titlepro.search.recorder.counties.adapters.pasco_http_adapter import (
        PascoHTTPAdapter,
    )

    a = PascoHTTPAdapter(pasco_config, start_date="01/01/1990", end_date="06/10/2026")
    a.session = MagicMock()
    return a


# SYNTHETIC results fixture — locks the defensive-parser contract.
RESULTS_FIXTURE = """
<html><body>
<table>
  <tr><th>Instrument</th><th>Party 1</th><th>Party 2</th><th>Type</th><th>Recorded</th><th>Book/Page</th></tr>
  <tr>
    <td><a href="appdot-public-sup-svcs-results-or-instrument-detail.asp?instr=2014123456">2014123456</a></td>
    <td>DOE JOHN A</td>
    <td>DOE JANE B</td>
    <td>DEED / PROPERTY TRANSFER</td>
    <td>03/05/2014</td>
    <td>9021 / 1234</td>
  </tr>
  <tr>
    <td>1998045678</td>
    <td>ACME MORTGAGE CORP</td>
    <td>DOE JOHN A</td>
    <td>SATISFACTION</td>
    <td>1998-06-15</td>
    <td>4012 / 887</td>
  </tr>
</table>
</body></html>
"""


def test_adapter_module_does_not_import_selenium_or_playwright():
    import importlib.util

    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(
        "_isolated_pasco_http_adapter", ADAPTER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    new_modules = set(sys.modules.keys()) - before
    leaked = [
        m
        for m in new_modules
        if m.split(".")[0] in {"selenium", "playwright", "undetected_chromedriver"}
    ]
    assert not leaked, f"adapter leaked browser modules: {leaked}"

    src = ADAPTER_PATH.read_text(encoding="utf-8")
    for needle in (
        "import selenium", "from selenium",
        "import playwright", "from playwright",
        "import undetected_chromedriver", "from undetected_chromedriver",
    ):
        assert needle not in src


def test_constructs_from_config_and_surface(adapter, pasco_config):
    assert adapter.county_name == "Pasco"
    assert adapter.base_url.startswith("https://app.pascoclerk.com")
    assert pasco_config["platform"] == "pasco_asp_http"
    for method in (
        "warm_session", "perform_search", "pull_detail", "download_pdf",
        "extract_results", "setup_driver", "navigate_to_search",
        "return_to_search", "build_name_search_payload",
    ):
        assert callable(getattr(adapter, method)), method
    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


def test_build_name_search_payload_deed_first(adapter):
    payload = adapter.build_name_search_payload(
        "RILEY, ROBERT S", party_type="Both", doc_type="DEED",
        date_from="01/01/1990", date_to="06/10/2026",
    )
    assert payload == {
        "name": "RILEY ROBERT S",
        "fromdate": "1990-01-01",
        "todate": "2026-06-10",
        "docset": "DEED / PROPERTY TRANSFER",
        "namedir": "A",
        "Submit": "Search by Name",
    }


def test_build_name_search_payload_party_directions_and_default_docset(adapter):
    p_grantor = adapter.build_name_search_payload("DOE JOHN", party_type="Grantor")
    p_grantee = adapter.build_name_search_payload("DOE JOHN", party_type="Grantee")
    p_unknown = adapter.build_name_search_payload("DOE JOHN", party_type="???")
    assert p_grantor["namedir"] == "D"
    assert p_grantee["namedir"] == "R"
    assert p_unknown["namedir"] == "A"
    assert p_grantor["docset"] == "ALL"
    assert p_grantor["fromdate"] == "1990-01-01"
    assert p_grantor["todate"] == "2026-06-10"


def test_name_truncated_to_portal_maxlength(adapter):
    long_name = "RILEY ROBERT S AND LYN MARIE TRUSTEES OF THE RILEY TRUST"
    payload = adapter.build_name_search_payload(long_name)
    assert len(payload["name"]) <= 30


def test_normalize_name(adapter):
    assert adapter._normalize_name("Riley, Robert S") == "RILEY ROBERT S"
    assert adapter._normalize_name("  riley   robert ") == "RILEY ROBERT"
    assert adapter._normalize_name("") == ""


def test_date_conversions(adapter):
    assert adapter._to_iso_date("03/05/2014") == "2014-03-05"
    assert adapter._to_iso_date("2014-03-05") == "2014-03-05"
    assert adapter._to_iso_date("") == ""
    assert adapter._to_mmddyyyy("2014-03-05") == "03/05/2014"
    assert adapter._to_mmddyyyy("03/05/2014") == "03/05/2014"


def test_extract_results_parses_fixture(adapter):
    docs = adapter.extract_results(RESULTS_FIXTURE)
    assert len(docs) == 2

    d1 = docs[0]
    assert d1.document_number == "2014123456"
    assert d1.document_type == "DEED / PROPERTY TRANSFER"
    assert d1.recording_date == "03/05/2014"
    assert "DOE JOHN A" in d1.grantors
    assert "DOE JANE B" in d1.grantees

    d2 = docs[1]
    assert d2.document_number == "1998045678"
    assert d2.document_type == "SATISFACTION"
    assert d2.recording_date == "06/15/1998"  # ISO token normalized

    assert "2014123456" in adapter._detail_href_by_number
    assert adapter._detail_href_by_number["2014123456"].startswith(
        "https://app.pascoclerk.com/"
    )


def test_extract_results_empty_and_garbage(adapter):
    assert adapter.extract_results(None) == []
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body>No records found</body></html>") == []


def _resp(status=200, text="", content=b""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.content = content or text.encode()
    return r


def test_perform_search_posts_form_and_parses(adapter):
    adapter.session.get.return_value = _resp(200, "<html>landing</html>")
    adapter.session.post.return_value = _resp(200, RESULTS_FIXTURE)

    docs = adapter.perform_search(
        "RILEY ROBERT S", party_type="Both", doc_type="DEED",
        date_from="01/01/1990", date_to="06/10/2026",
    )
    assert len(docs) == 2

    url, kwargs = adapter.session.post.call_args[0][0], adapter.session.post.call_args[1]
    assert url.endswith("appdot-public-sup-svcs-results-or-name-search.asp")
    assert kwargs["data"]["docset"] == "DEED / PROPERTY TRANSFER"
    assert kwargs["data"]["name"] == "RILEY ROBERT S"


def test_perform_search_http_error_returns_empty(adapter):
    adapter.session.get.return_value = _resp(200, "landing")
    adapter.session.post.return_value = _resp(500, "boom")
    assert adapter.perform_search("DOE JOHN") == []
    assert adapter.last_failure == "http_500"


# Live-verified instrument-detail page (2026-06-10, trust deed 2014038847):
# the GET detail endpoint carries Book/Page, page count, recording fee, the
# short legal, and the full Indexed Names (Party 1 / Party 2) table.
DETAIL_FIXTURE = """
<html><body>
<h2>Instrument Detail for 2014038847</h2>
<table>
  <tr><td>Instrument</td><td>2014038847</td></tr>
  <tr><td>Date</td><td>3/13/2014</td></tr>
  <tr><td>Time</td><td>10:21AM</td></tr>
  <tr><td>Book</td><td>9005</td></tr>
  <tr><td>Page</td><td>2848</td></tr>
  <tr><td>Document</td><td>DEED / PROPERTY TRANSFER</td></tr>
  <tr><td># Pages</td><td>3</td></tr>
  <tr><td>Recording Fee</td><td>$27.00</td></tr>
  <tr><td>Legal</td><td>04-24-21</td></tr>
</table>
<table>
  <tr><th>Name</th><th>Name Type</th></tr>
  <tr><td>RILEY ROBERT S</td><td>Party 1</td></tr>
  <tr><td>RILEY LYN M</td><td>Party 1</td></tr>
  <tr><td>RILEY ROBERT S TR</td><td>Party 2</td></tr>
  <tr><td>RILEY LYN M TR</td><td>Party 2</td></tr>
  <tr><td>RILEY TRUST</td><td>Party 2</td></tr>
</table>
<a href="appdot-public-sup-svcs-form-or-image-validate.asp?instrument=2014038847&pageCt=3">View Document</a>
</body></html>
"""


def test_pull_detail_gets_detail_page_and_parses_indexed_names(adapter):
    adapter._session_warmed = True
    adapter.session.get.return_value = _resp(200, DETAIL_FIXTURE)
    detail = adapter.pull_detail("2014038847")
    url = adapter.session.get.call_args[0][0]
    assert "appdot-public-sup-svcs-results-or-instr-detail.asp" in url
    assert "tbqs=2014038847" in url
    assert detail["document_number"] == "2014038847"
    assert detail["doc_type"] == "DEED / PROPERTY TRANSFER"
    assert detail["book_page"] == "9005 / 2848"
    assert detail["page_count"] == "3"
    names = {(p["name"], p["role"]) for p in detail["parties"]}
    assert ("RILEY ROBERT S", "Party 1") in names
    assert ("RILEY TRUST", "Party 2") in names
    assert len(detail["parties"]) == 5


def test_download_pdf_without_solver_reports_captcha_gate(adapter, tmp_path):
    adapter._session_warmed = True
    adapter.session.get.side_effect = [
        _resp(200, DETAIL_FIXTURE),      # pull_detail
        _resp(200, "<html>form</html>"), # image-form GET
        _resp(200, content=b"PNGDATA"),  # captcha image GET
    ]
    out = adapter.download_pdf("2014038847", tmp_path / "x.pdf")
    assert out["status"] == "error"
    assert out.get("captcha_required") is True
    assert not (tmp_path / "x.pdf").exists()


def test_download_pdf_with_solver_yields_pdf(adapter, tmp_path):
    adapter._session_warmed = True
    adapter.session.get.side_effect = [
        _resp(200, DETAIL_FIXTURE),      # pull_detail
        _resp(200, "<html>form</html>"), # image-form GET
        _resp(200, content=b"PNGDATA"),  # captcha image GET
    ]
    adapter.session.post.return_value = _resp(200, content=b"%PDF-1.4 real")
    out = adapter.download_pdf(
        "2014038847", tmp_path / "doc.pdf", captcha_solver=lambda b: "ABC123"
    )
    assert out["status"] == "success"
    assert (tmp_path / "doc.pdf").read_bytes().startswith(b"%PDF")
    assert adapter.session.post.call_args[1]["data"]["imagecode"] == "ABC123"
