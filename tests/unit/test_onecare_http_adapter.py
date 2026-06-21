"""
Unit tests for OneCareHTTPAdapter (Lake + Pinellas FL).

All tests run against pre-captured fixtures (no live network calls).
Live-probe fixtures were captured 2026-06-18 from Lake County FL:
  tests/unit/fixtures/onecare/lake_gridresults_smith_deed.json
  tests/unit/fixtures/onecare/lake_step1_nametree_brown.html
  tests/unit/fixtures/onecare/lake_step2_prename.html
  tests/unit/fixtures/onecare/lake_detail_2025155316.html

Pinellas is CF-blocked from datacenter; its tests use synthesised fixtures
that mirror the Lake HTML structure (same AcclaimWeb platform).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Ensure the src tree is on sys.path when running from the repo root.
_REPO_ROOT = Path(__file__).parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from titlepro.search.recorder.counties.adapters.onecare_http_adapter import (
    OneCareHTTPAdapter,
    _normalize_name,
    _parse_ms_date,
    GRID_AJAX_HEADERS,
)

# ─────────────────────────────────────────── fixture paths ──

_FIXTURES = Path(__file__).parent / "fixtures" / "onecare"


def _read(name: str) -> str:
    p = _FIXTURES / name
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return ""


def _read_json(name: str) -> Dict:
    p = _FIXTURES / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


# ─────────────────────────────────────────── shared config ──

_LAKE_CONFIG: Dict[str, Any] = {
    "county_id": "fl_lake",
    "county_name": "Lake",
    "state": "FL",
    "platform": "onecare_http",
    "base_url": "https://officialrecords.lakecountyclerk.org/",
    "cloudflare_required": False,
    "impersonate_profile": "safari17_2_ios",
    "default_book_type_numeric": "1",
    "doctype_deed_value": "26",
    "doctype_deed_display": "DEED (D)",
    "doctype_numeric_map": {
        "DEED": "26",
        "MORTGAGE": "41",
        "SATISFACTION": "55",
        "RELEASE": "52",
        "JUDGMENT_LIEN": "31",
        "LIS_PENDENS": "36",
    },
    "record_type_official_records": 1,
    "party_type_map": {
        "Both": "Both",
        "All": "Both",
        "Grantor": "Direct",
        "Grantee": "Reverse",
    },
    "step_delay_seconds": 0,  # no sleep in tests
}

_PINELLAS_CONFIG: Dict[str, Any] = {
    **_LAKE_CONFIG,
    "county_id": "fl_pinellas",
    "county_name": "Pinellas",
    "base_url": "https://officialrecords.mypinellasclerk.gov/",
    "cloudflare_required": True,
}


# ─────────────────────────────────────────── helper to build pre-warmed adapter ──

def _make_adapter(config: Dict, pre_warmed: bool = True) -> OneCareHTTPAdapter:
    adapter = OneCareHTTPAdapter(config, start_date="01/01/1985")
    if pre_warmed:
        adapter._session_warmed = True  # skip disclaimer in unit tests
    return adapter


# ─────────────────────────────────────────── test cases ──


class TestHelpers(unittest.TestCase):
    """Unit tests for pure-function helpers."""

    def test_normalize_name_strips_comma(self):
        self.assertEqual(_normalize_name("BROWN, LAURENCE"), "BROWN LAURENCE")

    def test_normalize_name_collapses_spaces(self):
        self.assertEqual(_normalize_name("BROWN  LAURENCE  R"), "BROWN LAURENCE R")

    def test_normalize_name_uppercases(self):
        self.assertEqual(_normalize_name("smith john"), "SMITH JOHN")

    def test_parse_ms_date_valid(self):
        # /Date(830186974000)/ → 04/22/1996 (UTC)
        result = _parse_ms_date("/Date(830186974000)/")
        # Accept any date-like string from any timezone
        self.assertRegex(result, r"\d{2}/\d{2}/\d{4}")

    def test_parse_ms_date_passthrough(self):
        self.assertEqual(_parse_ms_date("not-a-date"), "not-a-date")

    def test_parse_ms_date_empty(self):
        self.assertEqual(_parse_ms_date(""), "")


class TestAdapterInit(unittest.TestCase):
    """Adapter initialises correctly from config dict."""

    def test_lake_base_url_trailing_slash(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertTrue(adapter.base_url.endswith("/"))

    def test_lake_county_name(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertEqual(adapter.county_name, "Lake")

    def test_pinellas_cloudflare_flag(self):
        adapter = _make_adapter(_PINELLAS_CONFIG)
        self.assertTrue(adapter._cloudflare_required)

    def test_default_book_type(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertEqual(adapter._default_book_type, "1")

    def test_deed_doctype_value(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertEqual(adapter._doctype_deed_value, "26")

    def test_driver_is_none(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertIsNone(adapter.driver)

    def test_setup_driver_noop(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertIsNone(adapter.setup_driver())

    def test_urls_constructed(self):
        adapter = _make_adapter(_LAKE_CONFIG)
        self.assertIn("SearchTypeName", adapter._search_url)
        self.assertIn("SearchTypePreName", adapter._prename_url)
        self.assertIn("GridResults", adapter._grid_url)
        self.assertIn("DocumentPdfAllPages", adapter._pdf_url_tmpl)


class TestResolveDoctype(unittest.TestCase):
    """_resolve_doctype maps semantic names to numeric codes."""

    def setUp(self):
        self.adapter = _make_adapter(_LAKE_CONFIG)

    def test_deed_returns_26(self):
        code, display = self.adapter._resolve_doctype("DEED")
        self.assertEqual(code, "26")

    def test_none_returns_deed(self):
        code, _ = self.adapter._resolve_doctype(None)
        self.assertEqual(code, "26")

    def test_deed_d_display_string(self):
        code, _ = self.adapter._resolve_doctype("DEED (D)")
        self.assertEqual(code, "26")

    def test_mortgage_from_map(self):
        code, _ = self.adapter._resolve_doctype("MORTGAGE")
        self.assertEqual(code, "41")

    def test_unknown_passthrough(self):
        code, _ = self.adapter._resolve_doctype("99")
        self.assertEqual(code, "99")


class TestRowToRecord(unittest.TestCase):
    """_row_to_record converts a GridResults JSON row to DocumentRecord."""

    def setUp(self):
        self.adapter = _make_adapter(_LAKE_CONFIG)
        # Representative row from the live Lake fixture
        self.sample_row = {
            "TransactionItemId": 9026169,
            "IsViewed": None,
            "U": "",
            "Party": "To",
            "Name": "SMITH 2015 IRREVOCABLE TRUST",
            "SortName": "SMITH2015IRREVOCABLETRUST",
            "CrossPartyName": "SHARPE ROBERT C IND AND TR",
            "CompressedCrossPartyName": "SHARPEROBERTCINDANDTR",
            "RecordDate": "/Date(1766154775000)/",
            "DocType": "D",
            "BookType": "O",
            "BookPage": "6652/492",
            "NumericPage": 492.0,
            "InstrumentNumber": "2025155316",
            "NumericInstrumentNumber": 2025155316.0,
            "TransactionId": 1790956,
            "DocLegalDescription": "LT 77 ORANGE BLOSSOM GARDENS UN ONE",
            "CaseNumber": None,
            "Consideration": 425000.0,
        }

    def test_instrument_number(self):
        rec = self.adapter._row_to_record(self.sample_row)
        self.assertEqual(rec.document_number, "2025155316")

    def test_party_to_means_grantor_is_cross(self):
        rec = self.adapter._row_to_record(self.sample_row)
        # Party="To" → Name is GRANTEE, CrossPartyName is GRANTOR
        self.assertIn("SHARPE", rec.grantors)
        self.assertIn("SMITH 2015", rec.grantees)

    def test_party_from_means_grantor_is_name(self):
        row = {**self.sample_row, "Party": "From"}
        rec = self.adapter._row_to_record(row)
        self.assertIn("SMITH 2015", rec.grantors)
        self.assertIn("SHARPE", rec.grantees)

    def test_document_type(self):
        rec = self.adapter._row_to_record(self.sample_row)
        self.assertEqual(rec.document_type, "D")

    def test_recording_date_parsed(self):
        rec = self.adapter._row_to_record(self.sample_row)
        self.assertRegex(rec.recording_date, r"\d{2}/\d{2}/\d{4}")

    def test_row_extras_populated(self):
        self.adapter._row_to_record(self.sample_row)
        extras = self.adapter.row_extras.get("2025155316", {})
        self.assertEqual(extras.get("TransactionItemId"), "9026169")
        self.assertEqual(extras.get("BookPage"), "6652/492")

    def test_missing_instrument_number_returns_none(self):
        row = {**self.sample_row, "InstrumentNumber": ""}
        rec = self.adapter._row_to_record(row)
        self.assertIsNone(rec)

    def test_grantor_grantee_combined_field(self):
        rec = self.adapter._row_to_record(self.sample_row)
        self.assertIn("/", rec.grantor_grantees)


class TestGridResultsParsing(unittest.TestCase):
    """Parse the real Lake GridResults fixture."""

    def setUp(self):
        self.fixture = _read_json("lake_gridresults_smith_deed.json")
        self.adapter = _make_adapter(_LAKE_CONFIG)

    def test_fixture_loaded(self):
        """Fixture must exist and have the right shape."""
        self.assertIn("data", self.fixture)
        self.assertIn("total", self.fixture)

    def test_total_six(self):
        self.assertEqual(self.fixture["total"], 6)

    def test_all_rows_parsed(self):
        rows = self.fixture.get("data", [])
        records = []
        for row in rows:
            rec = self.adapter._row_to_record(row)
            if rec:
                records.append(rec)
        self.assertEqual(len(records), 6)

    def test_instrument_numbers_are_strings(self):
        rows = self.fixture.get("data", [])
        for row in rows:
            rec = self.adapter._row_to_record(row)
            if rec:
                self.assertIsInstance(rec.document_number, str)
                self.assertGreater(len(rec.document_number), 0)

    def test_doc_type_is_deed(self):
        """All rows in the deed fixture should have DocType 'D'."""
        rows = self.fixture.get("data", [])
        for row in rows:
            rec = self.adapter._row_to_record(row)
            if rec:
                self.assertEqual(rec.document_type, "D")


class TestStep1NameParsing(unittest.TestCase):
    """Parse the Telerik treeview HTML from the real Lake step-1 response."""

    def setUp(self):
        self.html = _read("lake_step1_nametree_brown.html")

    def test_fixture_has_item_values(self):
        items = re.findall(
            r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"', self.html
        )
        self.assertGreater(len(items), 0)

    def test_root_node_has_count_in_parens(self):
        items = re.findall(
            r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"', self.html
        )
        root_nodes = [v for v in items if "(" in v and v.endswith(")")]
        self.assertGreater(len(root_nodes), 0)

    def test_leaf_nodes_have_no_parens(self):
        items = re.findall(
            r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"', self.html
        )
        leaf_nodes = [v for v in items if "(" not in v or not v.endswith(")")]
        self.assertGreater(len(leaf_nodes), 0)

    def test_laurence_variants_in_tree(self):
        items = re.findall(
            r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"', self.html
        )
        laurence = [v for v in items if "LAURENCE" in v.upper()]
        self.assertGreater(len(laurence), 0)

    def test_normalize_filter_selects_laurence(self):
        items = re.findall(
            r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"', self.html
        )
        leaves = [v for v in items if "(" not in v or not v.endswith(")")]
        norm = _normalize_name("BROWN LAURENCE")
        selected = [v for v in leaves if _normalize_name(v).startswith(norm)]
        self.assertGreater(len(selected), 0)
        for v in selected:
            self.assertIn("LAURENCE", v.upper())


class TestPerformSearchMocked(unittest.TestCase):
    """perform_search end-to-end with mocked HTTP session."""

    def setUp(self):
        self.adapter = _make_adapter(_LAKE_CONFIG)

    def _make_mock_response(self, status=200, text="", json_data=None):
        r = MagicMock()
        r.status_code = status
        r.text = text
        if json_data is not None:
            r.json.return_value = json_data
        else:
            r.json.side_effect = ValueError("not json")
        return r

    def _step1_html(self, names: List[str]) -> str:
        """Minimal Telerik treeview HTML with the given itemValues."""
        parts = []
        for i, n in enumerate(names):
            parts.append(
                f'<input class="t-input" name="NameListTreeView_checkedNodes.Index" '
                f'type="hidden" value="0:{i}" />'
                f'<input class="t-input" '
                f'name="NameListTreeView_checkedNodes[0:{i}].Checked" '
                f'type="checkbox" value="False" />'
                f'<input class="t-input" name="itemValue" type="hidden" value="{n}" />'
            )
        # Include hidden date inputs with server-appended time suffix
        parts.append('<input name="RecordDateFrom" type="text" value="1/1/1985 12:00:00 AM" />')
        parts.append('<input name="RecordDateTo" type="text" value="6/18/2026 12:00:00 AM" />')
        return "\n".join(parts)

    def test_no_names_found_returns_empty(self):
        """Step-1 returns 'No names found' → empty list, no failure."""
        self.adapter.session.post = MagicMock(
            return_value=self._make_mock_response(
                text="No names found. Please try your search again."
            )
        )
        result = self.adapter.perform_search("ZZZZZZ", doc_type="DEED")
        self.assertEqual(result, [])
        self.assertIsNone(self.adapter.last_failure)

    def test_prename_error_sets_failure(self):
        """Step-1 returns error text → last_failure set, empty list."""
        self.adapter.session.post = MagicMock(
            return_value=self._make_mock_response(
                text="Error in getting list of names (pre name search)."
            )
        )
        result = self.adapter.perform_search("SMITH", doc_type="DEED")
        self.assertEqual(result, [])
        self.assertEqual(self.adapter.last_failure, "step1_prename_error")

    def test_step1_network_error(self):
        """Step-1 network error → empty list, failure flagged."""
        self.adapter.session.post = MagicMock(side_effect=OSError("timeout"))
        result = self.adapter.perform_search("SMITH", doc_type="DEED")
        self.assertEqual(result, [])
        self.assertEqual(self.adapter.last_failure, "step1_network_error")

    def test_full_three_step_flow(self):
        """Successful three-step returns parsed DocumentRecord list."""
        step1_html = self._step1_html(["SMITH JOHN A", "SMITH JOHN B"])
        step2_html = "<html>total:0</html>"  # empty init — data fetched via step3
        step3_json = {
            "data": [
                {
                    "InstrumentNumber": "2025001234",
                    "TransactionItemId": 12345,
                    "Party": "From",
                    "Name": "SMITH JOHN A",
                    "CrossPartyName": "JONES MARY",
                    "RecordDate": "/Date(1700000000000)/",
                    "DocType": "D",
                    "BookType": "O",
                    "BookPage": "6500/100",
                    "NumericPage": 1.0,
                    "DocLegalDescription": "LT 1 SOME SUBDIVISION",
                    "CaseNumber": None,
                    "Consideration": 250000.0,
                }
            ],
            "total": 1,
        }

        responses = [
            self._make_mock_response(text=step1_html),   # step1
            self._make_mock_response(text=step2_html),   # step2
            self._make_mock_response(json_data=step3_json),  # step3
        ]
        self.adapter.session.post = MagicMock(side_effect=responses)

        result = self.adapter.perform_search("SMITH JOHN", doc_type="DEED")
        self.assertEqual(len(result), 1)
        rec = result[0]
        self.assertEqual(rec.document_number, "2025001234")
        self.assertEqual(rec.document_type, "D")
        self.assertIn("SMITH", rec.grantors)
        self.assertIn("JONES", rec.grantees)

    def test_grid_requires_xhr_header(self):
        """GridResults call must include X-Requested-With: XMLHttpRequest."""
        step1_html = self._step1_html(["SMITH JOHN A"])
        step2_html = "<html>prename result</html>"
        step3_json = {"data": [], "total": 0}

        call_headers: List[Dict] = []
        original_post = self.adapter.session.post

        def capture_post(url, data=None, headers=None, **kwargs):
            call_headers.append(dict(headers or {}))
            if "GridResults" in url:
                m = MagicMock()
                m.status_code = 200
                m.json.return_value = step3_json
                return m
            elif "SearchTypePreName" in url:
                return self._make_mock_response(text=step2_html)
            else:
                return self._make_mock_response(text=step1_html)

        self.adapter.session.post = capture_post
        self.adapter.perform_search("SMITH JOHN", doc_type="DEED")

        # Find the GridResults call headers
        grid_headers = [h for h in call_headers if h.get("X-Requested-With") == "XMLHttpRequest"]
        self.assertGreater(len(grid_headers), 0,
            "GridResults POST must include X-Requested-With: XMLHttpRequest")

    def test_step3_http_error_returns_empty(self):
        """Step-3 HTTP error → empty result, failure flagged."""
        step1_html = self._step1_html(["SMITH JOHN A"])
        step2_html = "<html>prename</html>"

        call_count = 0
        def side_effect(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "SearchTypeName" in url:
                return self._make_mock_response(text=step1_html)
            elif "SearchTypePreName" in url:
                return self._make_mock_response(text=step2_html)
            else:  # GridResults
                return self._make_mock_response(status=500, text="error")

        self.adapter.session.post = side_effect
        result = self.adapter.perform_search("SMITH JOHN", doc_type="DEED")
        self.assertEqual(result, [])
        self.assertIn("step3_http", self.adapter.last_failure)

    def test_party_type_both(self):
        """Party type 'Both' maps to 'Both' radio value."""
        step1_html = self._step1_html(["SMITH JOHN A"])
        calls = []
        def capture(url, data=None, **kwargs):
            calls.append({"url": url, "data": dict(data or {})})
            if "SearchTypeName" in url:
                return self._make_mock_response(text=step1_html)
            r = MagicMock()
            r.status_code = 200
            r.text = "<html></html>"
            r.json.return_value = {"data": [], "total": 0}
            return r
        self.adapter.session.post = capture
        self.adapter.perform_search("SMITH JOHN", party_type="Both", doc_type="DEED")
        step1_data = calls[0]["data"]
        self.assertEqual(step1_data.get("PartyType"), "Both")
        self.assertEqual(step1_data.get("Both"), "Both")

    def test_party_type_grantor_maps_to_direct(self):
        """Party type 'Grantor' maps to 'Direct'."""
        step1_html = self._step1_html(["SMITH JOHN A"])
        calls = []
        def capture(url, data=None, **kwargs):
            calls.append({"url": url, "data": dict(data or {})})
            if "SearchTypeName" in url:
                return self._make_mock_response(text=step1_html)
            r = MagicMock()
            r.status_code = 200
            r.text = "<html></html>"
            r.json.return_value = {"data": [], "total": 0}
            return r
        self.adapter.session.post = capture
        self.adapter.perform_search("SMITH JOHN", party_type="Grantor", doc_type="DEED")
        step1_data = calls[0]["data"]
        self.assertEqual(step1_data.get("PartyType"), "Direct")

    def test_all_leaves_selected_when_no_prefix_match(self):
        """If no leaf normalises to the search prefix, ALL leaves are selected (Tony #5)."""
        # Search "SMITH ZZZZ" but only "SMITH ALPHA" and "SMITH BETA" are in the tree
        step1_html = self._step1_html(["SMITH ALPHA", "SMITH BETA"])
        calls = []
        def capture(url, data=None, **kwargs):
            calls.append({"url": url, "data": dict(data or {})})
            if "SearchTypeName" in url:
                return self._make_mock_response(text=step1_html)
            r = MagicMock()
            r.status_code = 200
            r.text = "<html></html>"
            r.json.return_value = {"data": [], "total": 0}
            return r
        self.adapter.session.post = capture
        self.adapter.perform_search("SMITH ZZZZ", doc_type="DEED")
        prename_data = calls[1]["data"]
        # Should include BOTH leaves as fallback
        self.assertIn("SMITH ALPHA", prename_data.get("NameList", ""))
        self.assertIn("SMITH BETA", prename_data.get("NameList", ""))


class TestPullDetail(unittest.TestCase):
    """pull_detail fetches and parses the instrument detail page."""

    def setUp(self):
        self.adapter = _make_adapter(_LAKE_CONFIG)
        self.detail_html = _read("lake_detail_2025155316.html")

    def test_transaction_item_id_from_fixture(self):
        """Real fixture must contain the known hdnTransactionItemId."""
        if not self.detail_html:
            self.skipTest("lake_detail_2025155316.html fixture not found")
        m = re.search(r'hdnTransactionItemId[^"]*"\s+value="([^"]+)"', self.detail_html, re.I)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "9026169")

    def test_pull_detail_calls_jump_endpoint(self):
        """pull_detail GETs the JumpToInstrumentNumber URL."""
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.text = '<input id="hdnTransactionItemId" value="9026169" />'
        self.adapter.session.get = MagicMock(return_value=mock_r)

        result = self.adapter.pull_detail("2025155316")
        call_url = self.adapter.session.get.call_args[0][0]
        self.assertIn("JumpToInstrumentNumber", call_url)
        self.assertIn("2025155316", call_url)
        self.assertIn("1", call_url)   # record_type_official_records=1
        self.assertEqual(result.get("TransactionItemId"), "9026169")

    def test_pull_detail_http_error(self):
        mock_r = MagicMock()
        mock_r.status_code = 404
        self.adapter.session.get = MagicMock(return_value=mock_r)
        result = self.adapter.pull_detail("9999999")
        self.assertIn("error", result)

    def test_pull_detail_network_error(self):
        self.adapter.session.get = MagicMock(side_effect=OSError("timeout"))
        result = self.adapter.pull_detail("9999999")
        self.assertIn("error", result)


class TestDownloadPdf(unittest.TestCase):
    """download_pdf fetches /Image/DocumentPdfAllPages/{txn_id}."""

    def setUp(self):
        self.adapter = _make_adapter(_LAKE_CONFIG)

    def test_uses_documentpdfallpages_url(self):
        """PDF download URL must contain DocumentPdfAllPages."""
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.content = b"%PDF-1.4 fake content"
        mock_r.headers = {"content-type": "application/pdf"}
        self.adapter.session.get = MagicMock(return_value=mock_r)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            ok = self.adapter.download_pdf(
                "2025155316", path, transaction_item_id="9026169"
            )
            self.assertTrue(ok)
            call_url = self.adapter.session.get.call_args[0][0]
            self.assertIn("DocumentPdfAllPages", call_url)
            self.assertIn("9026169", call_url)
        finally:
            os.unlink(path)

    def test_pdf_bytes_written_to_disk(self):
        pdf_bytes = b"%PDF-1.4 content"
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.content = pdf_bytes
        mock_r.headers = {"content-type": "application/pdf"}
        self.adapter.session.get = MagicMock(return_value=mock_r)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            self.adapter.download_pdf("2025155316", path, transaction_item_id="9026169")
            self.assertEqual(Path(path).read_bytes(), pdf_bytes)
        finally:
            os.unlink(path)

    def test_fallback_to_row_extras(self):
        """download_pdf can resolve txn_id from row_extras."""
        self.adapter.row_extras["2025155316"] = {"TransactionItemId": "9026169"}
        pdf_bytes = b"%PDF-1.4 x"
        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.content = pdf_bytes
        mock_r.headers = {"content-type": "application/pdf"}
        self.adapter.session.get = MagicMock(return_value=mock_r)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            ok = self.adapter.download_pdf("2025155316", path)
            self.assertTrue(ok)
        finally:
            os.unlink(path)

    def test_http_error_returns_false(self):
        mock_r = MagicMock()
        mock_r.status_code = 404
        self.adapter.session.get = MagicMock(return_value=mock_r)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            ok = self.adapter.download_pdf(
                "9999999", path, transaction_item_id="12345"
            )
            self.assertFalse(ok)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_missing_txn_id_returns_false(self):
        ok = self.adapter.download_pdf("9999999", "/tmp/nope.pdf")
        self.assertFalse(ok)


class TestConfigJson(unittest.TestCase):
    """Config JSON files are valid and have the required keys."""

    _REQUIRED = ["county_id", "county_name", "state", "platform", "base_url",
                 "doctype_deed_value", "default_book_type_numeric"]

    def _load(self, filename: str) -> Dict:
        p = (_REPO_ROOT / "src/titlepro/search/recorder/counties/config/fl" / filename)
        if not p.exists():
            self.skipTest(f"{filename} not found")
        return json.loads(p.read_text())

    def test_lake_json_valid(self):
        cfg = self._load("lake.json")
        for key in self._REQUIRED:
            self.assertIn(key, cfg, f"lake.json missing key '{key}'")

    def test_lake_platform_onecare(self):
        cfg = self._load("lake.json")
        self.assertEqual(cfg.get("platform"), "onecare_http")

    def test_lake_cloudflare_false(self):
        cfg = self._load("lake.json")
        self.assertFalse(cfg.get("cloudflare_required"))

    def test_pinellas_json_valid(self):
        cfg = self._load("pinellas.json")
        for key in self._REQUIRED:
            self.assertIn(key, cfg, f"pinellas.json missing key '{key}'")

    def test_pinellas_platform_onecare(self):
        cfg = self._load("pinellas.json")
        self.assertEqual(cfg.get("platform"), "onecare_http")

    def test_pinellas_cloudflare_true(self):
        cfg = self._load("pinellas.json")
        self.assertTrue(cfg.get("cloudflare_required"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
