"""
Unit tests for LeonLformsHTTPAdapter (lforms.leonclerk.com).
All tests use offline fixtures — no network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from titlepro.search.recorder.counties.adapters.leon_lforms_http_adapter import (
    LeonLformsHTTPAdapter,
)
from titlepro.search.recorder.base_recorder import DocumentRecord

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "leon"

_LEON_CONFIG = {
    "county_id": "fl_leon",
    "county_name": "Leon",
    "state": "FL",
    "base_url": "https://lforms.leonclerk.com/official_records/",
    "search_url": "https://lforms.leonclerk.com/official_records/search.asp",
    "detail_url": "https://lforms.leonclerk.com/official_records/document_info.asp",
    "my_unique_id": "1",
    "subscriber_code": "510",
    "doctype_deed_code": "D",
}


def _make_adapter() -> LeonLformsHTTPAdapter:
    with patch("curl_cffi.requests.Session"):
        adapter = LeonLformsHTTPAdapter(config=_LEON_CONFIG)
    return adapter


# ---------------------------------------------------------------------------
# Name compression tests
# ---------------------------------------------------------------------------


class TestCompressName:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_last_first_with_space(self):
        assert self.adapter._compress_name("JONES TELLIE") == "JONES,TELLIE"

    def test_last_only(self):
        assert self.adapter._compress_name("JONES") == "JONES"

    def test_last_comma_first(self):
        assert self.adapter._compress_name("JONES,TELLIE") == "JONES,TELLIE"

    def test_last_comma_space_first(self):
        assert self.adapter._compress_name("JONES, TELLIE") == "JONES,TELLIE"

    def test_strips_ampersand(self):
        # & is stripped before comma substitution: "AT&T MOBILITY" → "ATT MOBILITY" → "ATT,MOBILITY"
        result = self.adapter._compress_name("AT&T MOBILITY")
        assert "&" not in result, "Ampersand should be stripped"
        assert "," in result or result == "ATT MOBILITY", "Should convert space to comma"

    def test_uppercase(self):
        assert "jones" not in self.adapter._compress_name("jones tellie")


# ---------------------------------------------------------------------------
# Doctype resolution
# ---------------------------------------------------------------------------


class TestResolveDoctype:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_deed_full(self):
        assert self.adapter._resolve_doctype("DEED") == "D"

    def test_deed_code(self):
        assert self.adapter._resolve_doctype("D") == "D"

    def test_mortgage(self):
        assert self.adapter._resolve_doctype("MORTGAGE") == "MTG"
        assert self.adapter._resolve_doctype("MTG") == "MTG"

    def test_none_returns_empty(self):
        assert self.adapter._resolve_doctype(None) == ""

    def test_empty_returns_empty(self):
        assert self.adapter._resolve_doctype("") == ""

    def test_unknown_passthrough(self):
        # Unknown codes passed through as-is
        assert self.adapter._resolve_doctype("CUSTOM") == "CUSTOM"


# ---------------------------------------------------------------------------
# HTML result parsing
# ---------------------------------------------------------------------------


class TestParseResults:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_parse_deed_jones_fixture(self):
        """Parse real captured fixture: JONES deed search."""
        html = (FIXTURE_DIR / "search_deed_jones.html").read_text()
        records = self.adapter._parse_results(html, "JONES")
        # Expect multiple rows
        assert len(records) > 0, "Should return at least one record from JONES search"
        # Verify structure of first record
        first = records[0]
        assert isinstance(first, DocumentRecord)
        assert first.document_number  # documentid present
        assert first.grantors or first.grantees  # at least one party
        assert first.document_type in ("D", "MTG", "SAT", "LN", "FL", "AGR", "CIV", "REL", "ASG", "POA", "SC")

    def test_parse_fields_correctly(self):
        """Verify field mapping from fixture HTML."""
        html = (FIXTURE_DIR / "search_deed_jones.html").read_text()
        records = self.adapter._parse_results(html, "JONES")
        # Find a DEED record
        deeds = [r for r in records if r.document_type == "D"]
        assert len(deeds) > 0, "Should find at least one DEED in JONES search"
        deed = deeds[0]
        assert deed.document_number.isdigit(), "document_number should be numeric (documentid)"
        assert "/" in deed.recording_date or deed.recording_date  # date present

    def test_parse_noresult_fixture(self):
        """Empty result returns empty list."""
        html = (FIXTURE_DIR / "search_noresult.html").read_text()
        records = self.adapter._parse_results(html, "NORESULTXYZ")
        assert records == []

    def test_no_table_sets_failure(self):
        """Missing table sets last_failure."""
        records = self.adapter._parse_results("<html><body>No table here</body></html>", "TEST")
        assert records == []
        assert self.adapter.last_failure == "no_table_found"


# ---------------------------------------------------------------------------
# Document detail parsing
# ---------------------------------------------------------------------------


class TestParseDetail:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_parse_detail_fixture(self):
        """Parse real document_info HTML fixture."""
        html = (FIXTURE_DIR / "document_info_2975684.html").read_text()
        detail = self.adapter._parse_detail(html)
        assert isinstance(detail["grantors"], list)
        assert isinstance(detail["grantees"], list)
        assert len(detail["grantors"]) > 0, "Should have at least one grantor"
        assert len(detail["grantees"]) > 0, "Should have at least one grantee"
        # doc_type should say DEED
        assert "DEED" in detail["doc_type"].upper(), f"Expected DEED in doc_type, got {detail['doc_type']!r}"
        assert detail["book_page"]  # book/page present
        assert detail["record_date"]  # date present


# ---------------------------------------------------------------------------
# perform_search integration test (mocked HTTP)
# ---------------------------------------------------------------------------


class TestPerformSearch:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_perform_search_returns_records_on_200(self):
        """Mocked successful search returns parsed records."""
        html = (FIXTURE_DIR / "search_deed_jones.html").read_text()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        self.adapter.session = MagicMock()
        self.adapter.session.get.return_value = mock_resp

        records = self.adapter.perform_search("JONES", doc_type="DEED")
        assert len(records) > 0
        assert all(r.document_type for r in records)

    def test_perform_search_http_error_returns_empty(self):
        """HTTP error returns empty list and sets last_failure."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        self.adapter.session = MagicMock()
        self.adapter.session.get.return_value = mock_resp

        records = self.adapter.perform_search("JONES")
        assert records == []
        assert self.adapter.last_failure == "http_500"

    def test_perform_search_network_error_returns_empty(self):
        """Network exception returns empty list and sets last_failure."""
        self.adapter.session = MagicMock()
        self.adapter.session.get.side_effect = Exception("connection refused")

        records = self.adapter.perform_search("JONES")
        assert records == []
        assert "request_error" in self.adapter.last_failure


# ---------------------------------------------------------------------------
# Default start_date two-owner window regression
# Regression: original default was "01/01/2010" which cuts pre-2010 instruments
# from a two-owner search.  Must be "01/01/1985" to cover a 40-year window.
# ---------------------------------------------------------------------------


def test_default_start_date_is_two_owner_window():
    """LeonLformsHTTPAdapter default start_date must be '01/01/1985'.

    A default of '01/01/2010' silently truncates pre-2010 instruments from
    two-owner searches, causing missed prior-owner liens / encumbrances.
    """
    with patch("curl_cffi.requests.Session"):
        adapter = LeonLformsHTTPAdapter(config=_LEON_CONFIG)
    assert adapter.start_date == "01/01/1985", (
        f"Default start_date should be '01/01/1985' for a two-owner search window. "
        f"Got {adapter.start_date!r}. A value of '01/01/2010' would silently drop "
        f"pre-2010 instruments (mortgages, judgments, etc.)."
    )


def test_explicit_start_date_overrides_default():
    """When an explicit start_date is passed, it takes precedence over the default."""
    with patch("curl_cffi.requests.Session"):
        adapter = LeonLformsHTTPAdapter(config=_LEON_CONFIG, start_date="01/01/2000")
    assert adapter.start_date == "01/01/2000"
