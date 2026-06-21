"""Scaffold tests for LandmarkAdapter.

Mirrors test_acclaimweb_http_adapter_scaffold.py. Verifies:
  1. No Selenium / Playwright / undetected_chromedriver leakage at import.
  2. Adapter constructs from the Palm Beach JSON config.
  3. Public API surface (warm_session, perform_search, perform_parcel_search,
     pull_detail, extract_results, return_to_search, set_captcha_solver, plus
     the ABC no-ops).
  4. extract_results() parses a Landmark HTML grid fixture into DocumentRecord
     instances using:
       - tr[id^="doc_"] convention
       - <a onclick="GetDetailSection('...')"> fallback
       - regex-on-cell fallback
  5. _parse_detail_html() returns the expected dict shape (mirrors AcclaimWeb).
  6. perform_search() sets last_failure=needs_captcha when no solver is wired
     AND captcha_required is True (the documented manual-checkpoint fallback).
  7. Sitekey scraping helper extracts the data-sitekey from a recaptchasection.
  8. Registry routes platform='landmark' to LandmarkAdapter for fl_palm_beach.
  9. landmark_template.json exists and carries all _TODO_ markers (sanity).
 10. Party-type and date payload mapping matches Landmark's numeric vocab.

Tests do NOT hit the live Palm Beach portal — end-to-end live validation is
captured in src/titlepro/api/downloaded_doc/0526/PalmBeach_HABER_v1/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
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
    / "palm_beach.json"
)
TEMPLATE_PATH = CONFIG_PATH.parent / "landmark_template.json"


@pytest.fixture(scope="module")
def palm_beach_config() -> dict:
    with CONFIG_PATH.open("r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1) No browser-driver leakage at import time
# ---------------------------------------------------------------------------

def test_landmark_adapter_does_not_import_selenium_or_playwright():
    """Source-level check + isolated-import check, mirroring the AcclaimWeb test."""
    import importlib.util

    adapter_path = (
        SRC
        / "titlepro"
        / "search"
        / "recorder"
        / "counties"
        / "adapters"
        / "landmark_adapter.py"
    )
    assert adapter_path.exists(), f"Landmark adapter missing at {adapter_path}"

    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(
        "_isolated_landmark_adapter", adapter_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    after = set(sys.modules.keys())
    new_modules = after - before

    leaked = [
        m for m in new_modules
        if (m == "selenium" or m.startswith("selenium.")
            or m == "playwright" or m.startswith("playwright.")
            or m == "undetected_chromedriver" or m.startswith("undetected_chromedriver."))
    ]
    truly_new_leaks = [m for m in leaked if m not in before]
    assert not truly_new_leaks, f"Landmark adapter leaked browser modules: {truly_new_leaks}"

    # Source-level check: no MODULE-LEVEL browser imports. An indented
    # (lazy, inside-a-function) selenium import is permitted for exactly one
    # documented exception: `_async_scrape_sitekey` renders the page once to
    # scrape an async-JS reCAPTCHA sitekey (Wave-2, 2026-05-29) and caches it
    # on disk. The SEARCH path itself must stay pure HTTP (Tony directive #1)
    # — that's what the import-leak check above enforces at runtime.
    src_lines = adapter_path.read_text(encoding="utf-8").splitlines()
    forbidden = (
        "import selenium", "from selenium",
        "import playwright", "from playwright",
        "import undetected_chromedriver", "from undetected_chromedriver",
    )
    for lineno, line in enumerate(src_lines, start=1):
        stripped = line.lstrip()
        if not any(stripped.startswith(needle) for needle in forbidden):
            continue
        assert line != stripped, (
            f"Landmark adapter has a MODULE-LEVEL browser import at line "
            f"{lineno}: {stripped!r} — lazy in-function imports only."
        )
        assert "playwright" not in stripped and "undetected" not in stripped, (
            f"Only selenium is permitted for the sitekey-scrape fallback; "
            f"line {lineno}: {stripped!r}"
        )


# ---------------------------------------------------------------------------
# 2) Construction + 3) public API surface
# ---------------------------------------------------------------------------

def test_landmark_adapter_constructs_from_palm_beach_config(palm_beach_config):
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    adapter = LandmarkAdapter(palm_beach_config)
    assert adapter.county_name == "Palm Beach"
    assert adapter.base_url.startswith("https://erec.mypalmbeachclerk.com/")
    assert adapter._session_warmed is False
    assert adapter.last_failure is None
    assert adapter.driver is None
    assert adapter.captcha_required is True
    # Endpoint resolution
    assert adapter._ep_name_search == "Search/NameSearch"
    assert adapter._ep_disclaimer == "Search/SetDisclaimer"
    assert adapter._ep_show_captcha == "Search/ShowCaptcha"
    assert adapter._ep_parcel_search == "Search/ParcelIdSearch"
    # Party-type vocab is numeric
    assert adapter.party_type_map["Both"] == "0"
    assert adapter.party_type_map["Grantor"] == "1"
    assert adapter.party_type_map["Grantee"] == "2"
    # Sitekey carried from config
    assert adapter._site_key == "6LdBHOorAAAAALwRLkAZpnNsfcp7qfFS4YIGIRTU"


def test_landmark_adapter_has_full_api_surface(palm_beach_config):
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)

    required = (
        "warm_session", "setup_driver", "navigate_to_search", "perform_search",
        "perform_parcel_search", "pull_detail", "extract_results",
        "return_to_search", "set_captcha_solver",
    )
    for method in required:
        assert hasattr(adapter, method), f"missing method: {method}"
        assert callable(getattr(adapter, method)), f"not callable: {method}"

    assert adapter.setup_driver() is None
    assert adapter.navigate_to_search() is None
    assert adapter.return_to_search() is None


# ---------------------------------------------------------------------------
# 4) extract_results() parses Landmark HTML
# ---------------------------------------------------------------------------

LANDMARK_RESULTS_FIXTURE = """
<html><body>
<table id="resultsTable" class="results">
  <thead><tr><th>Doc #</th><th>Date</th><th>Type</th><th>Grantor</th><th>Grantee</th><th>Pages</th></tr></thead>
  <tbody>
    <tr id="doc_20220123456">
      <td><a href="javascript:void(0);" onclick="GetDetailSection('20220123456', 0)">20220123456</a></td>
      <td>03/15/2022</td>
      <td>D</td>
      <td>HABER DANA</td>
      <td>HABER MARK</td>
      <td>3</td>
    </tr>
    <tr id="doc_20210098765">
      <td><a onclick="GetDetailSection('20210098765', 1)">20210098765</a></td>
      <td>06/22/2021</td>
      <td>MTG</td>
      <td>HABER DANA</td>
      <td>WELLS FARGO BANK NA</td>
      <td>15</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_extract_results_parses_landmark_grid(palm_beach_config):
    from titlepro.search.recorder.base_recorder import DocumentRecord
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    adapter = LandmarkAdapter(palm_beach_config)
    docs = adapter.extract_results(LANDMARK_RESULTS_FIXTURE)

    assert isinstance(docs, list)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)

    by_num = {d.document_number: d for d in docs}
    assert "20220123456" in by_num
    assert "20210098765" in by_num

    d1 = by_num["20220123456"]
    assert d1.recording_date == "03/15/2022"
    assert "HABER" in d1.grantors
    assert "HABER" in d1.grantees
    assert d1.pages == "3"


def test_extract_results_empty_html_returns_empty(palm_beach_config):
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body>no records found in any results table here</body></html>") == []


def test_extract_results_handles_no_records_banner(palm_beach_config):
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    no_results_html = """
    <html><body>
    <div class="results"><h1>Results</h1>
    <div class="alert">No records found for the given search criteria. Please refine your search.</div>
    </div></body></html>
    """
    assert adapter.extract_results(no_results_html) == []


# ---------------------------------------------------------------------------
# 5) pull_detail() static parser
# ---------------------------------------------------------------------------

DETAIL_FIXTURE = """
<html><body>
<table class="details">
  <tr><td>Document Number</td><td>20220123456</td></tr>
  <tr><td>Recording Date</td><td>03/15/2022</td></tr>
  <tr><td>Doc Type</td><td>DEED</td></tr>
  <tr><td>Parcel ID</td><td>00-43-46-25-12-345-6789</td></tr>
  <tr><td>Book/Page</td><td>33445 / 1234</td></tr>
</table>
<table class="parties">
  <tr><th>Role</th><th>Party Name</th></tr>
  <tr><td>Grantor</td><td>HABER DANA</td></tr>
  <tr><td>Grantee</td><td>HABER MARK</td></tr>
</table>
</body></html>
"""


def test_pull_detail_parser_returns_indexed_apn_and_parties():
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    detail = LandmarkAdapter._parse_detail_html(DETAIL_FIXTURE, "20220123456")
    assert isinstance(detail, dict)
    assert detail["document_number"] == "20220123456"
    assert detail["recording_date"] == "03/15/2022"
    assert detail["doc_type"] == "DEED"
    assert detail["indexed_apn"].startswith("00-43-46")
    assert detail["book_page"].startswith("33445")
    roles = {p["role"] for p in detail["parties"]}
    assert "Grantor" in roles and "Grantee" in roles


# ---------------------------------------------------------------------------
# 6) Failure-mode contract: needs_captcha when solver unavailable
# ---------------------------------------------------------------------------

def test_perform_search_needs_captcha_when_no_solver(monkeypatch, palm_beach_config):
    """Without a wired solver, perform_search must return [] and set
    last_failure='needs_captcha' so the pipeline can branch to manual."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    adapter = LandmarkAdapter(palm_beach_config)
    # Skip the live HTTP warm-up entirely.
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True
    # Force ShowCaptcha to return True (already the default in config).
    monkeypatch.setattr(adapter, "_resolve_captcha_token", lambda: None)

    result = adapter.perform_search("HABER DANA", party_type="Both")
    assert result == []
    assert adapter.last_failure == "needs_captcha"


def test_perform_search_uses_solver_token_when_wired(monkeypatch, palm_beach_config):
    """When a solver IS wired AND opted in, the token is passed through to
    NameSearch and HTTP 200 plus the DataTables follow-up returns rows.

    Landmark uses DataTables in server-side mode: the NameSearch POST returns
    only the wrapper (with the inline ``records of N`` count); rows come from
    a second POST to ``/Search/GetSearchResults`` returning JSON.
    """
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    adapter = LandmarkAdapter(palm_beach_config)
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2.return_value = "FAKE_TOKEN_XYZ"
    mock_solver.service = "2captcha"
    adapter.captcha_solver = mock_solver
    # Force ShowCaptcha to skip live HTTP — pretend already done.
    adapter._captcha_check_done = True

    # NameSearch returns DataTables wrapper with embedded count.
    NAMESEARCH_WRAPPER = (
        "<html><body>"
        "<table id='resultsTable'><thead><tr><th>#</th></tr></thead></table>"
        "<script>"
        "var extra = false;"
        "oTable =$('#resultsTable').DataTable({"
        " 'info': '<b>Returned _TOTAL_ records of 2</b>',"
        " 'ajax': { url: site + 'Search/GetSearchResults', type: 'POST' }"
        "});"
        "</script>"
        "</body></html>"
    )
    # GetSearchResults returns JSON in DataTables 1.10 server-side schema.
    GETRESULTS_JSON = {
        "draw": "1",
        "recordsTotal": 2,
        "recordsFiltered": 2,
        "data": [
            {
                "0": "nobreak_1",
                "3": "V",
                "4": "HABER DANA",
                "5": "HABER MARK<div class='nameSeperator'></div>HABER DANA",
                "6": "WELLS FARGO BANK NA",
                "7": "nobreak_03/15/2022",
                "9": "nobreak_DEED",
                "11": "33445",
                "12": "1234",
                "13": "nobreak_20220123456",
                "15": "legalfield_BOCA WINDS L109",
                "28": "nobreak_3",
                "29": "hidden_19380499",
                "DT_RowId": "doc_19380499_1",
            },
            {
                "0": "nobreak_2",
                "3": "V",
                "4": "HABER DANA",
                "5": "FIFTH THIRD BANK NA",
                "6": "FIFTH THIRD BANK NA",
                "7": "nobreak_04/17/2026",
                "9": "nobreak_MORTGAGE",
                "11": "36458",
                "12": "00117",
                "13": "nobreak_20260138664",
                "15": "legalfield_BOCA WINDS L109",
                "28": "nobreak_15",
                "29": "hidden_28269779",
                "DT_RowId": "doc_28269779_2",
            },
        ],
    }

    import json as _json
    posts = []

    class FakeNameSearchResp:
        status_code = 200
        text = NAMESEARCH_WRAPPER

    class FakeGetResultsResp:
        status_code = 200
        text = _json.dumps(GETRESULTS_JSON)
        @staticmethod
        def json():
            return GETRESULTS_JSON

    def fake_post(url, data=None, headers=None, timeout=None):
        posts.append({"url": url, "data": data, "headers": headers})
        if url.endswith("/Search/NameSearch"):
            return FakeNameSearchResp()
        if url.endswith("/Search/GetSearchResults"):
            return FakeGetResultsResp()
        raise AssertionError(f"unexpected POST to {url}")

    monkeypatch.setattr(adapter.session, "post", fake_post)

    docs = adapter.perform_search("HABER DANA", party_type="Both")

    # Two-stage flow: at least one POST to NameSearch + one to GetSearchResults
    assert any(p["url"].endswith("/Search/NameSearch") for p in posts)
    assert any(p["url"].endswith("/Search/GetSearchResults") for p in posts)

    # Captcha token forwarded
    ns_post = next(p for p in posts if p["url"].endswith("/Search/NameSearch"))
    assert ns_post["data"]["g-recaptcha-response"] == "FAKE_TOKEN_XYZ"
    # Party type mapped to numeric '0' (Both)
    assert ns_post["data"]["type"] == "0"
    # Name forwarded verbatim
    assert ns_post["data"]["name"] == "HABER DANA"
    # bookType correctly set to '0' (All Books), NOT empty — this was the 500 cause
    assert ns_post["data"]["bookType"] == "0"

    # Rows parsed from GetSearchResults JSON
    assert len(docs) == 2
    by_num = {d.document_number: d for d in docs}
    assert "20220123456" in by_num
    assert "20260138664" in by_num
    deed = by_num["20220123456"]
    assert deed.document_type == "DEED"
    assert deed.recording_date == "03/15/2022"
    assert "HABER DANA" in deed.grantors
    assert "HABER MARK" in deed.grantees
    assert deed.pages == "3"


# ---------------------------------------------------------------------------
# 7) Sitekey scraping helper
# ---------------------------------------------------------------------------

def test_sitekey_scraper_handles_recaptcha_div():
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    html = (
        '<div class="recaptchasection-Name recaptchasection" '
        'style="display: none" data-sitekey="6LdBHOorAAAAALwRLkAZpnNsfcp7qfFS4YIGIRTU"></div>'
    )
    assert LandmarkAdapter._scrape_sitekey(html) == "6LdBHOorAAAAALwRLkAZpnNsfcp7qfFS4YIGIRTU"
    assert LandmarkAdapter._scrape_sitekey("") is None
    assert LandmarkAdapter._scrape_sitekey("<div>no captcha here</div>") is None


# ---------------------------------------------------------------------------
# 8) Registry wiring sanity check
# ---------------------------------------------------------------------------

def test_registry_landmark_platform_resolves_to_landmark_adapter():
    from titlepro.search.recorder.counties import registry
    adapter = registry.get_recorder("fl_palm_beach")
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    assert isinstance(adapter, LandmarkAdapter)
    # Registry entry is no longer stub
    info = registry.get_county_info("fl_palm_beach")
    assert "stub" not in info or info.get("stub") is False


# ---------------------------------------------------------------------------
# 9) Template config exists for Wave-2 county additions
# ---------------------------------------------------------------------------

def test_landmark_template_config_exists_with_todo_markers():
    assert TEMPLATE_PATH.exists(), f"Landmark template missing at {TEMPLATE_PATH}"
    raw = TEMPLATE_PATH.read_text(encoding="utf-8")
    template = json.loads(raw)
    # Template must declare itself a template, NOT in_progress / active
    assert template.get("status") == "template"
    # And carry _TODO_ markers so devs see exactly what to fill in
    todo_markers = ["county_id", "county_name", "base_url", "recorder_root", "recaptcha_site_key"]
    for key in todo_markers:
        v = template.get(key, "")
        assert "_TODO_" in str(v), f"Template field {key!r} must have a _TODO_ marker, got {v!r}"


# ---------------------------------------------------------------------------
# 9b) Two-stage DataTables fetch helpers
# ---------------------------------------------------------------------------

def test_scrape_total_count_parses_records_of_N():
    """The inline ``records of N</b>`` text in the NameSearch response is the
    canonical source of the result total — it predates the GetSearchResults
    fetch and is needed to decide whether to make that follow-up call.
    """
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    html = (
        "<html><body><script>"
        "'info': '<b ' + ... + 'records of 6</b>',"
        "</script></body></html>"
    )
    assert LandmarkAdapter._scrape_total_count(html) == 6

    # Empty results — DataTables emits "records of 0"
    html_empty = (
        "<script>"
        "'info': '<b>Returned _TOTAL_ records of 0</b>',"
        "'infoEmpty': '<b>Returned 0 records</b>',"
        "</script>"
    )
    assert LandmarkAdapter._scrape_total_count(html_empty) == 0

    # No count text at all — caller uses record_cap fallback
    assert LandmarkAdapter._scrape_total_count("") == 0


def test_row_to_document_record_strips_prefixes(palm_beach_config):
    """Landmark JSON cells carry class-hint prefixes (nobreak_/hidden_/...) that
    the rowCallback strips before display. Adapter must do the same so the
    persisted DocumentRecord values are clean."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    row = {
        "3": "V",
        "4": "HABER DANA",
        "5": "HABER MARK<div class='nameSeperator'></div>HABER DANA",
        "7": "nobreak_11/01/2019",
        "9": "nobreak_DEED",
        "11": "30996",
        "12": "00616",
        "13": "nobreak_20190401915",
        "15": "legalfield_TUSCANY C L44 PCN: 00-41-47-22-04-000-1090",
        "28": "nobreak_2",
        "29": "hidden_23030131",
        "DT_RowId": "doc_23030131_2",
    }
    # _row_to_document_record is now an instance method (uses self._col for
    # per-county column overrides). Instantiate with Palm Beach config.
    adapter = LandmarkAdapter(palm_beach_config)
    rec = adapter._row_to_document_record(row)
    assert rec.document_number == "20190401915"  # instrument number, not internal id
    assert rec.recording_date == "11/01/2019"
    assert rec.document_type == "DEED"
    assert rec.pages == "2"
    # Names are HTML-stripped — the <div class='nameSeperator'></div> becomes ; separator
    assert "HABER MARK" in rec.grantees
    assert "HABER DANA" in rec.grantees
    assert "HABER DANA" in rec.grantors


def test_extract_pcn_from_legal():
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    assert LandmarkAdapter._extract_pcn_from_legal(
        "L: 109 SUB: BOCA WINDS PARCEL E PCN: 00-41-47-22-04-000-1090"
    ) == "00-41-47-22-04-000-1090"
    assert LandmarkAdapter._extract_pcn_from_legal("") == ""
    assert LandmarkAdapter._extract_pcn_from_legal("no parcel here") == ""


# ---------------------------------------------------------------------------
# 10) Tax-URL entry for Palm Beach exists
# ---------------------------------------------------------------------------

def test_palm_beach_tax_url_registered():
    tax_cfg = json.loads(
        (REPO_ROOT / "config" / "county_tax_urls.json").read_text(encoding="utf-8")
    )
    counties = tax_cfg.get("counties", {})
    assert "fl_palm_beach" in counties, "fl_palm_beach missing from county_tax_urls.json"
    pb = counties["fl_palm_beach"]
    assert "pbctax.publicaccessnow.com" in pb["base_url"]
    assert pb.get("platform_family") == "aumentum"


# ---------------------------------------------------------------------------
# 11) download_pdf — page-count scrape + image stitch + cache seeding
# ---------------------------------------------------------------------------

def test_scrape_page_count_parses_image_count():
    """The detail HTML for a Landmark document carries `var imageCount = N;`.
    The page-count scrape MUST find it (it's the only way to know how many
    page-image fetches to make)."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    html = (
        "<html><body><script>\n"
        "    var imageCount = 2;\n"
        "    var transImageCount = 0;\n"
        "    var something = 'other';\n"
        "</script></body></html>"
    )
    assert LandmarkAdapter._scrape_page_count(html) == 2

    # Empty / missing — caller falls back to single-page attempt
    assert LandmarkAdapter._scrape_page_count("") == 0
    assert LandmarkAdapter._scrape_page_count("<html>no page count here</html>") == 0

    # Only transImageCount available (Landmark tenants that emit only that)
    html_trans = "<script>var transImageCount = 5;</script>"
    assert LandmarkAdapter._scrape_page_count(html_trans) == 5


def test_seed_doc_id_and_lookup_for_download(palm_beach_config):
    """seed_doc_id is the public hook for re-using a search result set
    without re-running the captcha-gated search."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    adapter.seed_doc_id("20190401915", "23030131")
    assert adapter._doc_id_by_number["20190401915"] == "23030131"
    # Empty strings are no-ops
    adapter.seed_doc_id("", "123")
    adapter.seed_doc_id("20190401915", "")
    assert len(adapter._doc_id_by_number) == 1


def test_download_pdf_requires_cached_doc_id(palm_beach_config, tmp_path, monkeypatch):
    """download_pdf MUST fail soft (status=error, phase=id_resolution) when
    the instrument number has no internal-id mapping — never hard-crash."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True

    result = adapter.download_pdf("99999999999", tmp_path / "missing.pdf")
    assert result["status"] == "error"
    assert result["phase"] == "id_resolution"
    assert "20190401915" not in result.get("error", "")  # generic error, not leaking docs


# A 1x1 PNG generated by Python's `PIL.Image.new('RGB', (1,1)).save(...)`.
# Used as a synthetic page-image so the stitch test doesn't have to hit the
# network. Hardcoded so the test is hermetic.
_SYNTHETIC_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00"
    b"\x05\xfe\x02\xfe\xa3?\xae\xa9\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_download_pdf_stitches_pages_into_pdf(palm_beach_config, tmp_path, monkeypatch):
    """End-to-end download_pdf with mocked HTTP — proves the adapter
    stitches >=2 page-images into a valid PDF."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True
    adapter.seed_doc_id("20190401915", "23030131")

    DETAIL_HTML = "<html><body><script>var imageCount = 2; var transImageCount = 0;</script></body></html>"

    class FakeDetail:
        status_code = 200
        text = DETAIL_HTML

    class FakeImage:
        status_code = 200
        content = _SYNTHETIC_PNG_BYTES
        headers = {"content-type": "image/png"}

    def fake_post(url, data=None, headers=None, timeout=None):
        assert url.endswith("/Document/Index"), url
        assert data["id"] == "23030131"
        return FakeDetail()

    def fake_get(url, params=None, timeout=None, headers=None):
        assert "GetDocumentImage" in url
        assert params["documentId"] == "23030131"
        return FakeImage()

    monkeypatch.setattr(adapter.session, "post", fake_post)
    monkeypatch.setattr(adapter.session, "get", fake_get)

    dest = tmp_path / "deed_20190401915.pdf"
    result = adapter.download_pdf("20190401915", dest)
    assert result["status"] == "success", result
    assert result["pages"] == 2
    assert result["internal_id"] == "23030131"
    assert dest.exists()
    pdf_bytes = dest.read_bytes()
    assert pdf_bytes[:4] == b"%PDF", "stitched file is not a PDF"
    assert dest.stat().st_size > 200  # sanity-bound


def test_download_pdf_refuses_runaway_page_count(palm_beach_config, tmp_path, monkeypatch):
    """A pdf_max_pages cap MUST stop the adapter from fetching e.g. 100,000
    pages if the internal-id resolves to the wrong document — defense in
    depth against state-contamination class bugs."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    cfg = dict(palm_beach_config)
    cfg["pdf_max_pages"] = 10
    adapter = LandmarkAdapter(cfg)
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True
    adapter.seed_doc_id("20190401915", "23030131")

    RUNAWAY_HTML = "<html><script>var imageCount = 9999;</script></html>"

    class FakeDetail:
        status_code = 200
        text = RUNAWAY_HTML

    monkeypatch.setattr(adapter.session, "post", lambda *a, **k: FakeDetail())
    # Should NEVER reach the GET call
    monkeypatch.setattr(adapter.session, "get", lambda *a, **k: pytest.fail("unexpected GET"))

    result = adapter.download_pdf("20190401915", tmp_path / "bad.pdf")
    assert result["status"] == "error"
    assert result["phase"] == "page_count_validation"
    assert "9999" in result["error"] and "10" in result["error"]


def test_doc_id_cache_populated_during_fetch_data_rows(palm_beach_config, monkeypatch):
    """The instrument # -> internal_id mapping must be populated as part of
    perform_search so download_pdf can later resolve it without a re-search."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter
    adapter = LandmarkAdapter(palm_beach_config)
    monkeypatch.setattr(adapter, "warm_session", lambda: True)
    adapter._session_warmed = True

    mock_solver = MagicMock()
    mock_solver.solve_recaptcha_v2.return_value = "T"
    adapter.captcha_solver = mock_solver
    adapter._captcha_check_done = True

    NAMESEARCH_WRAPPER = (
        "<script>'info': '<b>Returned _TOTAL_ records of 1</b>',</script>"
    )
    GETRESULTS_JSON = {
        "draw": "1", "recordsTotal": 1, "recordsFiltered": 1,
        "data": [{
            "4": "HABER DANA",
            "5": "HABER MARK",
            "7": "nobreak_11/01/2019",
            "9": "nobreak_DEED",
            "13": "nobreak_20190401915",
            "28": "nobreak_2",
            "29": "hidden_23030131",
            "DT_RowId": "doc_23030131_1",
        }]
    }

    import json as _json

    class FakeNs:
        status_code = 200
        text = NAMESEARCH_WRAPPER

    class FakeGr:
        status_code = 200
        text = _json.dumps(GETRESULTS_JSON)
        @staticmethod
        def json():
            return GETRESULTS_JSON

    def fake_post(url, data=None, headers=None, timeout=None):
        if url.endswith("/Search/NameSearch"):
            return FakeNs()
        if url.endswith("/Search/GetSearchResults"):
            return FakeGr()
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(adapter.session, "post", fake_post)

    docs = adapter.perform_search("HABER DANA")
    assert len(docs) == 1
    assert docs[0].document_number == "20190401915"
    # The doc_id cache must now hold the mapping for download_pdf
    assert adapter._doc_id_by_number.get("20190401915") == "23030131"


# ---------------------------------------------------------------------------
# pipeline_mode guard: _async_scrape_sitekey must NOT launch Selenium
# ---------------------------------------------------------------------------

def test_async_scrape_sitekey_guarded_in_pipeline_mode(palm_beach_config):
    """When pipeline_mode=True, _async_scrape_sitekey must NOT launch a browser.

    Regression guard: _async_scrape_sitekey uses Selenium (headless Chrome) as
    a one-off operator sitekey-mint tool. It must never auto-run during a
    pipeline search because it blocks on a slow browser launch + page render,
    and the pipeline runs in headless environments without Chrome available.

    When pipeline_mode is set, the method must:
    1. Return None immediately (no Selenium import attempted).
    2. Set last_failure = 'needs_sitekey_mint'.
    """
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    cfg = {**palm_beach_config, "pipeline_mode": True}
    adapter = LandmarkAdapter(cfg)

    # Confirm the flag is set
    assert adapter._pipeline_mode is True

    # Call _async_scrape_sitekey — must return None without launching Chrome
    result = adapter._async_scrape_sitekey()

    assert result is None, (
        f"_async_scrape_sitekey must return None in pipeline_mode. Got {result!r}."
    )
    assert adapter.last_failure == "needs_sitekey_mint", (
        f"last_failure must be 'needs_sitekey_mint' when pipeline_mode blocks the scrape. "
        f"Got {adapter.last_failure!r}."
    )


def test_async_scrape_sitekey_guarded_by_no_browser_alias(palm_beach_config):
    """no_browser=True is an alias for pipeline_mode=True."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    cfg = {**palm_beach_config, "no_browser": True}
    adapter = LandmarkAdapter(cfg)

    assert adapter._pipeline_mode is True
    result = adapter._async_scrape_sitekey()
    assert result is None
    assert adapter.last_failure == "needs_sitekey_mint"


def test_pipeline_mode_false_by_default(palm_beach_config):
    """pipeline_mode defaults to False (preserving backward-compat for operator use)."""
    from titlepro.search.recorder.counties.adapters.landmark_adapter import LandmarkAdapter

    cfg = dict(palm_beach_config)
    cfg.pop("pipeline_mode", None)
    cfg.pop("no_browser", None)
    adapter = LandmarkAdapter(cfg)

    assert adapter._pipeline_mode is False
