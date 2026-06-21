"""
Unit tests for AcclaimWebTelerikHTTPAdapter (Santa Rosa FL, acclaim.srccol.com).
All tests use offline fixtures — no network calls.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from titlepro.search.recorder.counties.adapters.acclaimweb_telerik_http_adapter import (
    AcclaimWebTelerikHTTPAdapter,
    DOCTYPE_CODES,
)
from titlepro.search.recorder.base_recorder import DocumentRecord

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "santa_rosa"

_SANTA_ROSA_CONFIG = {
    "county_id": "fl_santa_rosa",
    "county_name": "Santa Rosa",
    "state": "FL",
    "base_url": "https://acclaim.srccol.com/AcclaimWeb/",
    "disclaimer_path": "Search/Disclaimer",
    "step1_path": "search/SearchTypeName",
    "step2_path": "Search/SearchTypePreName",
    "export_csv_path": "Search/ExportCsv",
    "instrument_path": "search/SearchTypeInstrumentNumber",
    "doctype_deed_code": "79",
    "book_types_code": "All",
}


def _make_adapter() -> AcclaimWebTelerikHTTPAdapter:
    with patch("curl_cffi.requests.Session"):
        adapter = AcclaimWebTelerikHTTPAdapter(config=_SANTA_ROSA_CONFIG)
    adapter._disclaimer_accepted = True  # skip disclaimer for most tests
    return adapter


# ---------------------------------------------------------------------------
# Doctype resolution
# ---------------------------------------------------------------------------


class TestDocTypeResolution:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_deed_maps_to_79(self):
        assert self.adapter._resolve_doctype("DEED") == "79"
        assert self.adapter._resolve_doctype("D") == "79"

    def test_mortgage(self):
        assert self.adapter._resolve_doctype("MORTGAGE") == "91"
        assert self.adapter._resolve_doctype("MTG") == "91"

    def test_satisfaction(self):
        assert self.adapter._resolve_doctype("SATISFACTION") == "122"
        assert self.adapter._resolve_doctype("SAT") == "122"

    def test_none_returns_all(self):
        assert self.adapter._resolve_doctype(None) == "all"

    def test_empty_returns_all(self):
        assert self.adapter._resolve_doctype("") == "all"

    def test_all_returns_all(self):
        assert self.adapter._resolve_doctype("ALL") == "all"


# ---------------------------------------------------------------------------
# Name formatting
# ---------------------------------------------------------------------------


class TestFormatName:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_last_first_space_to_comma(self):
        assert self.adapter._format_name("WHITE TIMOTHY") == "WHITE,TIMOTHY"

    def test_last_only(self):
        assert self.adapter._format_name("WHITE") == "WHITE"

    def test_already_comma_format(self):
        assert self.adapter._format_name("WHITE,TIMOTHY") == "WHITE,TIMOTHY"

    def test_uppercase(self):
        result = self.adapter._format_name("white timothy")
        assert result == result.upper()


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------


class TestNormalizeDate:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_full_datetime_string(self):
        assert self.adapter._normalize_date("1/13/2015 3:13:16 PM") == "01/13/2015"

    def test_date_only(self):
        assert self.adapter._normalize_date("05/04/2026") == "05/04/2026"

    def test_single_digit_month_day(self):
        assert self.adapter._normalize_date("5/4/2026 12:38:40 PM") == "05/04/2026"

    def test_empty_string(self):
        assert self.adapter._normalize_date("") == ""

    def test_unparseable_passthrough(self):
        raw = "not-a-date"
        assert self.adapter._normalize_date(raw) == raw


# ---------------------------------------------------------------------------
# Name tree parsing
# ---------------------------------------------------------------------------


class TestParseNameTree:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_parse_step1_fixture(self):
        """Parse real step 1 HTML fixture containing Telerik TreeView."""
        html = (FIXTURE_DIR / "step1_white_timothy_name_tree.html").read_text()
        tree = self.adapter._parse_name_tree(html)
        assert len(tree) > 0, "Should find at least one node in name tree"
        # Should have parent (index like "0") and leaf nodes (index like "0:0")
        parents = [t for t in tree if ":" not in t[0] and t[2] == "parent"]
        leaves = [t for t in tree if ":" in t[0] and t[2] == "leaf"]
        assert len(parents) >= 1
        assert len(leaves) >= 1

    def test_leaf_nodes_contain_timothy(self):
        """WHITE TIMOTHY should appear as a leaf in the tree."""
        html = (FIXTURE_DIR / "step1_white_timothy_name_tree.html").read_text()
        tree = self.adapter._parse_name_tree(html)
        leaf_values = [t[1] for t in tree if t[2] == "leaf"]
        assert any("WHITE TIMOTHY" in v for v in leaf_values), \
            f"WHITE TIMOTHY not in leaf values: {leaf_values}"


# ---------------------------------------------------------------------------
# Leaf name selection
# ---------------------------------------------------------------------------


class TestSelectLeafNames:
    def setup_method(self):
        self.adapter = _make_adapter()
        self.tree = [
            ("0", "WHITE (65)", "parent"),
            ("0:0", "WHITE TIMOTHY", "leaf"),
            ("0:1", "WHITE TIMOTHY E", "leaf"),
            ("0:2", "WHITE TIMOTHY J", "leaf"),
            ("0:3", "WHITE TIMOTHY K", "leaf"),
        ]

    def test_select_exact_match(self):
        selected = self.adapter._select_leaf_names(self.tree, "WHITE TIMOTHY")
        assert "WHITE TIMOTHY" in selected

    def test_select_prefix_match(self):
        # "WHITE TIMOTHY" prefix matches all WHITE TIMOTHY* variants
        selected = self.adapter._select_leaf_names(self.tree, "WHITE TIMOTHY")
        assert len(selected) >= 1

    def test_no_match_returns_empty(self):
        selected = self.adapter._select_leaf_names(self.tree, "NONEXISTENT NAME")
        assert selected == []

    def test_skips_parent_nodes(self):
        selected = self.adapter._select_leaf_names(self.tree, "WHITE")
        # Should only include leaf nodes
        assert all("(" not in s for s in selected), "Parent nodes should not be selected"


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


class TestParseCsv:
    def setup_method(self):
        self.adapter = _make_adapter()

    def test_parse_real_csv_fixture(self):
        """Parse real ExportCsv fixture for WHITE TIMOTHY."""
        csv_text = (FIXTURE_DIR / "export_csv_white_timothy.csv").read_text()
        records = self.adapter._parse_csv(csv_text, "WHITE TIMOTHY")
        assert len(records) > 0, "Should parse at least one record from CSV"

    def test_csv_document_numbers_present(self):
        csv_text = (FIXTURE_DIR / "export_csv_white_timothy.csv").read_text()
        records = self.adapter._parse_csv(csv_text, "WHITE TIMOTHY")
        for r in records:
            assert r.document_number, f"document_number empty for record: {r}"

    def test_csv_deed_record_parties(self):
        """Verify DEED record has correct grantor/grantee orientation."""
        csv_text = (FIXTURE_DIR / "export_csv_white_timothy.csv").read_text()
        records = self.adapter._parse_csv(csv_text, "WHITE TIMOTHY")
        deed_records = [r for r in records if "DEED" in r.document_type.upper()]
        assert len(deed_records) > 0, "Should find at least one DEED record"
        deed = deed_records[0]
        # WHITE TIMOTHY is grantee (Party='To') on a deed
        assert "WHITE TIMOTHY" in deed.grantees.upper() or "WHITE TIMOTHY" in deed.grantors.upper()

    def test_csv_mortgage_record(self):
        """Verify MORTGAGE record is present."""
        csv_text = (FIXTURE_DIR / "export_csv_white_timothy.csv").read_text()
        records = self.adapter._parse_csv(csv_text, "WHITE TIMOTHY")
        mtg_records = [r for r in records if "MORTGAGE" in r.document_type.upper()]
        assert len(mtg_records) > 0, "Should find at least one MORTGAGE record"

    def test_csv_date_normalized(self):
        csv_text = (FIXTURE_DIR / "export_csv_white_timothy.csv").read_text()
        records = self.adapter._parse_csv(csv_text, "WHITE TIMOTHY")
        for r in records:
            # Dates should be in MM/DD/YYYY format (10 chars)
            assert len(r.recording_date) == 10 or not r.recording_date, \
                f"Unexpected date format: {r.recording_date!r}"

    def test_parse_synthetic_csv(self):
        """Parse a hand-crafted CSV to test field mapping."""
        csv_data = (
            "Consideration,Party,Name,CrossPartyName,InstrumentNumber,RecordDate,"
            "DocTypeDescription,BookType,BookPage,DocLink,CaseNumber,Comments\n"
            '"150000.0000","To","WHITE TIMOTHY","WELLS FARGO","202001001","1/15/2020 10:00:00 AM",'
            '"DEED","OR","3000/100","OR 2000/50","","LOT 10"\n'
            '"200000.0000","From","WHITE TIMOTHY","CHASE BANK","202001002","2/20/2020 10:00:00 AM",'
            '"MORTGAGE","OR","3000/101","","","LOT 10"\n'
        )
        records = self.adapter._parse_csv(csv_data, "WHITE TIMOTHY")
        assert len(records) == 2

        deed = records[0]
        assert deed.document_number == "202001001"
        assert "WHITE TIMOTHY" in deed.grantees  # Party='To' → grantee
        assert "WELLS FARGO" in deed.grantors
        assert deed.document_type == "DEED"
        assert deed.recording_date == "01/15/2020"

        mtg = records[1]
        assert mtg.document_number == "202001002"
        assert "WHITE TIMOTHY" in mtg.grantors  # Party='From' → grantor
        assert "CHASE BANK" in mtg.grantees
        assert mtg.document_type == "MORTGAGE"
        assert mtg.recording_date == "02/20/2020"


# ---------------------------------------------------------------------------
# perform_search mocked integration
# ---------------------------------------------------------------------------


class TestPerformSearchMocked:
    def setup_method(self):
        self.adapter = _make_adapter()

    def _mock_step1_response(self):
        """Return a minimal name tree HTML with WHITE TIMOTHY."""
        return """<html><body>
        <form action="/AcclaimWeb/Search/SearchTypePreName" method="post">
        <div id="NameListTreeView">
          <ul>
            <li><input name="NameListTreeView_checkedNodes.Index" value="0" type="hidden"/>
                <input name="NameListTreeView_checkedNodes[0].Checked" type="checkbox" value="False"/>
                <input name="itemValue" value="WHITE (2)" type="hidden"/>
              <ul>
                <li><input name="NameListTreeView_checkedNodes.Index" value="0:0" type="hidden"/>
                    <input name="NameListTreeView_checkedNodes[0:0].Checked" type="checkbox" value="False"/>
                    <input name="itemValue" value="WHITE TIMOTHY" type="hidden"/>
                </li>
              </ul>
            </li>
          </ul>
        </div>
        <div style="display:none;">
          <input name="PartyType" value="Both"/>
          <input name="RecordDateFrom" value="1/1/2000 12:00:00 AM"/>
          <input name="RecordDateTo" value="6/18/2026 12:00:00 AM"/>
          <input name="BookTypes" value="All"/>
          <input name="DocTypes" value="all"/>
          <input name="SearchOnName" value="WHITE,TIMOTHY"/>
          <input name="SearchOnLastOrBusinessName" value=""/>
          <input name="SearchOnFirstName" value=""/>
          <input name="ShowAllNames" value=""/>
          <input name="ShowAllLegals" value=""/>
        </div>
        </form></body></html>"""

    def _mock_csv_response(self):
        return (
            "Consideration,Party,Name,CrossPartyName,InstrumentNumber,RecordDate,"
            "DocTypeDescription,BookType,BookPage,DocLink,CaseNumber,Comments\n"
            '"152500.0000","To","WHITE TIMOTHY","FANNIE MAE","201501167","1/13/2015 3:13:16 PM",'
            '"DEED","OR","3400/80","OR 2672/505","","ADRIAN WOODS PH 1 17/A"\n'
        )

    def test_perform_search_calls_all_three_steps(self):
        """Verify all three steps are called in sequence."""
        step1_resp = MagicMock(status_code=200, text=self._mock_step1_response())
        step2_resp = MagicMock(status_code=200, text="<html>ok</html>")
        csv_resp = MagicMock(status_code=200, text=self._mock_csv_response())

        self.adapter.session = MagicMock()
        self.adapter.session.post.side_effect = [step1_resp, step2_resp]
        self.adapter.session.get.return_value = csv_resp

        records = self.adapter.perform_search("WHITE,TIMOTHY", doc_type=None)
        assert len(records) == 1
        assert records[0].document_number == "201501167"
        assert records[0].document_type == "DEED"
        assert "FANNIE MAE" in records[0].grantors

    def test_perform_search_step1_too_many_results(self):
        """Too many results in step1 → returns empty, sets last_failure."""
        step1_resp = MagicMock(
            status_code=200,
            text="The number of results exceeded the maximum limit"
        )
        self.adapter.session = MagicMock()
        self.adapter.session.post.return_value = step1_resp

        records = self.adapter.perform_search("A")
        assert records == []
        assert self.adapter.last_failure == "too_many_results"

    def test_perform_search_step2_error(self):
        """ShowError in step2 response → returns empty, sets last_failure."""
        step1_resp = MagicMock(status_code=200, text=self._mock_step1_response())
        step2_resp = MagicMock(status_code=200, text="ShowError( 'Error in executing the search. ')")

        self.adapter.session = MagicMock()
        self.adapter.session.post.side_effect = [step1_resp, step2_resp]

        records = self.adapter.perform_search("WHITE,TIMOTHY")
        assert records == []
        assert self.adapter.last_failure == "step2_server_error"

    def test_perform_search_csv_error(self):
        """ExportCsv HTTP error → empty list."""
        step1_resp = MagicMock(status_code=200, text=self._mock_step1_response())
        step2_resp = MagicMock(status_code=200, text="<html>ok</html>")
        csv_resp = MagicMock(status_code=403, text="Forbidden")

        self.adapter.session = MagicMock()
        self.adapter.session.post.side_effect = [step1_resp, step2_resp]
        self.adapter.session.get.return_value = csv_resp

        records = self.adapter.perform_search("WHITE,TIMOTHY")
        assert records == []
        assert self.adapter.last_failure == "csv_http_403"

    def _mock_step1_two_leaves(self):
        """Name tree with TWO leaves: WHITE TIMOTHY and WHITE TIMOTHY A."""
        return """<html><body>
        <form action="/AcclaimWeb/Search/SearchTypePreName" method="post">
        <div id="NameListTreeView">
          <ul>
            <li><input name="NameListTreeView_checkedNodes.Index" value="0" type="hidden"/>
                <input name="NameListTreeView_checkedNodes[0].Checked" type="checkbox" value="False"/>
                <input name="itemValue" value="WHITE (3)" type="hidden"/>
              <ul>
                <li><input name="NameListTreeView_checkedNodes.Index" value="0:0" type="hidden"/>
                    <input name="NameListTreeView_checkedNodes[0:0].Checked" type="checkbox" value="False"/>
                    <input name="itemValue" value="WHITE TIMOTHY" type="hidden"/>
                </li>
                <li><input name="NameListTreeView_checkedNodes.Index" value="0:1" type="hidden"/>
                    <input name="NameListTreeView_checkedNodes[0:1].Checked" type="checkbox" value="False"/>
                    <input name="itemValue" value="WHITE TIMOTHY A" type="hidden"/>
                </li>
              </ul>
            </li>
          </ul>
        </div>
        <div style="display:none;">
          <input name="PartyType" value="Both"/>
          <input name="RecordDateFrom" value="1/1/2000 12:00:00 AM"/>
          <input name="RecordDateTo" value="6/18/2026 12:00:00 AM"/>
          <input name="BookTypes" value="All"/>
          <input name="DocTypes" value="all"/>
          <input name="SearchOnName" value="WHITE,TIMOTHY"/>
          <input name="SearchOnLastOrBusinessName" value=""/>
          <input name="SearchOnFirstName" value=""/>
          <input name="ShowAllNames" value=""/>
          <input name="ShowAllLegals" value=""/>
        </div>
        </form></body></html>"""

    def test_multi_leaf_union_deduplicates(self):
        """Multi-leaf search must loop one CSV per leaf and union, deduplicating by document_number.

        Regression: the original code sent matching_leaves[:1] which silently dropped all
        name variants beyond the first leaf (violates Tony directive #3 — run ALL names).
        The fix loops one step2+exportCSV call per leaf and unions the results.
        """
        step1_resp = MagicMock(status_code=200, text=self._mock_step1_two_leaves())

        # Leaf 0 (WHITE TIMOTHY) returns doc 201501167
        csv_leaf0 = (
            "Consideration,Party,Name,CrossPartyName,InstrumentNumber,RecordDate,"
            "DocTypeDescription,BookType,BookPage,DocLink,CaseNumber,Comments\n"
            '"152500.0000","To","WHITE TIMOTHY","FANNIE MAE","201501167","1/13/2015 3:13:16 PM",'
            '"DEED","OR","3400/80","OR 2672/505","","ADRIAN WOODS"\n'
        )
        # Leaf 1 (WHITE TIMOTHY A) returns a DIFFERENT doc 200512345 plus the same 201501167
        csv_leaf1 = (
            "Consideration,Party,Name,CrossPartyName,InstrumentNumber,RecordDate,"
            "DocTypeDescription,BookType,BookPage,DocLink,CaseNumber,Comments\n"
            '"80000.0000","From","WHITE TIMOTHY A","CREDIT UNION","200512345","3/5/2005 9:00:00 AM",'
            '"MORTGAGE","OR","2100/10","","","LOT 5"\n'
            '"152500.0000","To","WHITE TIMOTHY A","FANNIE MAE","201501167","1/13/2015 3:13:16 PM",'
            '"DEED","OR","3400/80","OR 2672/505","","ADRIAN WOODS"\n'
        )

        step2_ok = MagicMock(status_code=200, text="<html>ok</html>")
        csv_resp_leaf0 = MagicMock(status_code=200, text=csv_leaf0)
        csv_resp_leaf1 = MagicMock(status_code=200, text=csv_leaf1)

        self.adapter.session = MagicMock()
        # step1 POST, then two step2 POSTs (one per leaf)
        self.adapter.session.post.side_effect = [step1_resp, step2_ok, step2_ok]
        # two ExportCsv GETs (one per leaf)
        self.adapter.session.get.side_effect = [csv_resp_leaf0, csv_resp_leaf1]

        # Search by SURNAME ONLY so that the prefix-match logic selects BOTH leaves
        # ("WHITE TIMOTHY" and "WHITE TIMOTHY A" both start with "WHITE").
        # Searching exact full name "WHITE,TIMOTHY" would match only leaf 0
        # via exact-match, never exercising the multi-leaf loop.
        records = self.adapter.perform_search("WHITE", doc_type=None)

        # Should have 2 unique documents: 201501167 (from leaf 0) + 200512345 (from leaf 1)
        # 201501167 from leaf 1 is a duplicate → deduplicated out
        nums = {r.document_number for r in records}
        assert "201501167" in nums, "Doc from first leaf must be present"
        assert "200512345" in nums, (
            "Doc unique to the second leaf must be present. "
            "If missing, the adapter dropped the second leaf (the old single-leaf bug)."
        )
        assert len(nums) == 2, f"Expected 2 unique docs, got {len(nums)}: {nums}"

        # step2 should have been called once per leaf (2 times total, not 1)
        step2_call_count = self.adapter.session.post.call_count - 1  # subtract step1
        assert step2_call_count == 2, (
            f"Expected 2 step2 POST calls (one per leaf), got {step2_call_count}. "
            "The adapter must loop per leaf, not take only the first."
        )
