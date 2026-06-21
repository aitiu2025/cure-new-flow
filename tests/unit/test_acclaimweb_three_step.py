"""Scaffold tests for the three-step JSON search flow (Brevard AcclaimWeb).

All HTTP is mocked. Live shapes captured 2026-06-10 (case Brevard_LEWIS_v1):
  step1 → Telerik name-picker treeview fragment
  step2 → results-shell page (rows ajax-bound)
  step3 → Search/GridResults JSON {data:[...], total:N}

STAGED in the case dir (Write to tests/unit denied this session).
Install at tests/unit/test_acclaimweb_three_step.py.
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

from titlepro.search.recorder.counties.adapters.acclaimweb_http_adapter import (  # noqa: E402
    AcclaimWebHTTPAdapter,
)


BREVARD_CONFIG = {
    "county_name": "Brevard",
    "base_url": "https://vaclmweb1.brevardclerk.us/AcclaimWeb/",
    "search_url": "https://vaclmweb1.brevardclerk.us/AcclaimWeb/search/SearchTypeName",
    "search_flow": "three_step_json",
    "doctype_deed_value": "80",
    "doctype_deed_display": "DEED (D)",
    "doctype_numeric_map": {"DEED": "80", "TAX_DEED": "145"},
    "default_book_type_numeric": "3",
    "three_step_post_delay_seconds": 0,
    "party_type_map": {"Both": "Both", "All": "Both", "Grantor": "Direct", "Grantee": "Reverse"},
    "supported_party_types": ["Both", "Direct", "Reverse"],
    "doc_image_url_pattern": {"record_type": 3, "pre_pdf_delay_seconds": 0,
                              "pdf_fetch_retries": 1, "pdf_retry_delay_seconds": 0},
}

NAME_TREE_HTML = """
<form action="/AcclaimWeb/Search/SearchTypePreName" method="post">
<div id="NameListTreeView">
 <li><div><input class="t-input" name="itemValue" type="hidden" value="LEWIS (2)" /></div>
  <ul>
   <li><div><input class="t-input" name="itemValue" type="hidden" value="LEWIS, ANGELA D" /></div></li>
   <li><div><input class="t-input" name="itemValue" type="hidden" value="LEWIS, ANGELA DIANNA" /></div></li>
  </ul>
 </li>
</div>
</form>
"""

GRID_JSON = {
    "data": [
        {
            "TransactionItemId": 2576997,
            "Party": "To",
            "Name": "LEWIS, ANGELA D",
            "CrossPartyName": "BROOKING, STEVE",
            "RecordDate": "/Date(830186974000)/",
            "DocTypeDescription": "DEED",
            "BookType": "OR",
            "BookPage": "3563/2270",
            "InstrumentNumber": "1996067410",
            "Consideration": 66500.0,
            "DocLegalDescription": "LT 16 BLK 1633 PB 17 PG 34 PORT MALABAR UNIT 32",
            "CaseNumber": None,
        },
        {
            "TransactionItemId": 999,
            "Party": "From",
            "Name": "LEWIS, ANGELA D",
            "CrossPartyName": "ACME MORTGAGE LLC",
            "RecordDate": "/Date(1180186974000)/",
            "DocTypeDescription": "MORTGAGE",
            "BookType": "OR",
            "BookPage": "5000/100",
            "InstrumentNumber": "2007123456",
            "Consideration": 0,
            "DocLegalDescription": "",
            "CaseNumber": None,
        },
    ],
    "total": 2,
}


def _resp(status=200, text="", payload=None):
    r = MagicMock()
    r.status_code = status
    if payload is not None:
        r.text = json.dumps(payload)
        r.json.return_value = payload
    else:
        r.text = text
        r.json.side_effect = ValueError("not json")
    return r


def _adapter():
    a = AcclaimWebHTTPAdapter(BREVARD_CONFIG, start_date="01/01/1990", end_date="06/10/2026")
    a.session = MagicMock()
    a._session_warmed = True
    return a


# --------------------------------------------------------------- unit helpers


def test_parse_name_tree_returns_leaves_only():
    leaves = AcclaimWebHTTPAdapter._parse_name_tree(NAME_TREE_HTML)
    assert leaves == ["LEWIS, ANGELA D", "LEWIS, ANGELA DIANNA"]


# Duval/OnCore renders the name picker as a Kendo TreeView whose dataSource is
# embedded in a kendo.syncReady(...) script block. The config object also holds
# JS expressions (template: jQuery('#treeview').html()) that are NOT valid JSON,
# so the whole object can't be json.loads'd — only the "dataSource":[...] array
# can. Leaves are nodes WITHOUT a child `items` array; both parent and leaf
# `text` carry a trailing (N) count that must be stripped.
NAME_TREE_KENDO_JSON = """
<div id="NameListTreeView"></div><script>
kendo.syncReady(function(){jQuery("#NameListTreeView").kendoTreeView({"checkboxes":{"name":"checkedFiles","template":jQuery('#treeview1').html()},"loadOnDemand":false,"template":jQuery('#treeview').html(),"dataSource":[{"id":null,"text":"SKINNER (15)","expanded":true,"items":[{"id":null,"text":"SKINNER MICHAEL (2)"},{"id":null,"text":"SKINNER MICHAEL S (1)"},{"id":null,"text":"SKINNER MICHAEL W (4)"}]}]});});
</script>
"""


def test_parse_name_tree_kendo_json_dataSource():
    leaves = AcclaimWebHTTPAdapter._parse_name_tree(NAME_TREE_KENDO_JSON)
    # (N) counts stripped; surname-group parent "SKINNER (15)" excluded.
    assert leaves == ["SKINNER MICHAEL", "SKINNER MICHAEL S", "SKINNER MICHAEL W"]


def test_parse_ms_date():
    assert AcclaimWebHTTPAdapter._parse_ms_date("/Date(830186974000)/") == "04/22/1996"
    assert AcclaimWebHTTPAdapter._parse_ms_date("") == ""
    assert AcclaimWebHTTPAdapter._parse_ms_date("garbage") == "garbage"


def test_doctype_values_mapping():
    a = _adapter()
    assert a._three_step_doctype_values(None) == ("all", "All")
    assert a._three_step_doctype_values("DEED") == ("80", "DEED (D)")
    assert a._three_step_doctype_values("TAX_DEED") == ("145", "TAX_DEED")
    assert a._three_step_doctype_values("77") == ("77", "77")


# --------------------------------------------------------------- full chain


def test_three_step_search_full_chain():
    a = _adapter()
    a.session.post.side_effect = [
        _resp(text=NAME_TREE_HTML),       # step 1
        _resp(text="<html>shell</html>"),  # step 2
        _resp(payload=GRID_JSON),          # step 3
    ]
    docs = a.perform_search("LEWIS, ANGELA D", party_type="Both", doc_type="DEED")
    assert len(docs) == 2
    d1, d2 = docs
    assert d1.document_number == "1996067410"
    assert d1.grantors == "BROOKING, STEVE"          # Party=To → Name is grantee
    assert d1.grantees == "LEWIS, ANGELA D"
    assert d1.document_type == "DEED"
    assert d1.recording_date == "04/22/1996"
    assert d2.document_number == "2007123456"
    assert d2.grantors == "LEWIS, ANGELA D"          # Party=From → Name is grantor
    assert d2.grantees == "ACME MORTGAGE LLC"

    # Extras cached for direct retrieval + report enrichment.
    ex = a.row_extras["1996067410"]
    assert ex["transaction_item_id"] == 2576997
    assert ex["book_page"] == "3563/2270"
    assert "PORT MALABAR" in ex["legal_description"]

    # Step-1 payload carried the numeric doctype + booktype + IsParsedName.
    step1_kwargs = a.session.post.call_args_list[0]
    payload = step1_kwargs.kwargs.get("data") or step1_kwargs.args[1]
    assert payload["DocTypes"] == "80"
    assert payload["BookTypes"] == "3"
    assert payload["IsParsedName"] == "False"
    assert payload["PartyType"] == "Both"

    # Step-2 NameList was the |||-join of matched leaves (both ANGELA D*).
    step2_kwargs = a.session.post.call_args_list[1]
    p2 = step2_kwargs.kwargs.get("data") or step2_kwargs.args[1]
    assert p2["NameList"] == "LEWIS, ANGELA D|||LEWIS, ANGELA DIANNA"
    assert p2["RecordDateFrom"].endswith("12:00:00 AM")


def test_three_step_prename_error_sets_last_failure():
    a = _adapter()
    a.session.post.side_effect = [
        _resp(text="Error in getting list of names (pre name search)."),
    ]
    docs = a.perform_search("LEWIS, ANGELA D", party_type="Both", doc_type="DEED")
    assert docs == []
    assert a.last_failure == "three_step_prename_error"


def test_three_step_no_names_matched_returns_empty_no_failure():
    a = _adapter()
    a.session.post.side_effect = [_resp(text="<div>no itemValue inputs</div>")]
    a.last_failure = None
    docs = a.perform_search("ZZZUNKNOWN, NAME", party_type="Both")
    assert docs == []
    assert a.last_failure is None  # legit zero-match, not a failure


def test_three_step_falls_back_to_all_leaves_when_no_startswith():
    a = _adapter()
    a.session.post.side_effect = [
        _resp(text=NAME_TREE_HTML),
        _resp(text="<html>shell</html>"),
        _resp(payload={"data": [], "total": 0}),
    ]
    docs = a.perform_search("SMITH, BOB", party_type="Both")
    assert docs == []
    p2 = a.session.post.call_args_list[1].kwargs.get("data") or a.session.post.call_args_list[1].args[1]
    # No leaf startswith SMITH → all leaves selected for completeness.
    assert "LEWIS, ANGELA D" in p2["NameList"]


def test_three_step_pagination_accumulates_until_total():
    a = _adapter()
    page1 = {"data": [dict(GRID_JSON["data"][0])], "total": 2}
    page2 = {"data": [dict(GRID_JSON["data"][1])], "total": 2}
    a.session.post.side_effect = [
        _resp(text=NAME_TREE_HTML),
        _resp(text="<html>shell</html>"),
        _resp(payload=page1),
        _resp(payload=page2),
    ]
    docs = a.perform_search("LEWIS, ANGELA D", party_type="Both")
    assert [d.document_number for d in docs] == ["1996067410", "2007123456"]


def test_broward_default_flow_unchanged():
    """search_flow absent → legacy single-POST path still used (regression)."""
    cfg = {
        "county_name": "Broward",
        "base_url": "https://officialrecords.broward.org/AcclaimWeb/",
        "doc_image_url_pattern": {"record_type": 27},
    }
    a = AcclaimWebHTTPAdapter(cfg, start_date="01/01/2010", end_date="06/10/2026")
    assert a._search_flow == "single_post"
    a.session = MagicMock()
    a._session_warmed = True
    a.session.post.return_value = _resp(text="<table><tr class='t-no-data'></tr></table>")
    docs = a.perform_search("ANAND, RISHI", party_type="All")
    assert docs == []
    # Exactly ONE post (the legacy single-POST), not the 3-step chain.
    assert a.session.post.call_count == 1


NAME_TREE_DUAL_FORMAT = """
<div id="NameListTreeView">
 <li><div><input name="itemValue" type="hidden" value="LEWIS (4)" /></div>
  <ul>
   <li><div><input name="itemValue" type="hidden" value="LEWIS, ANGELA D" /></div></li>
   <li><div><input name="itemValue" type="hidden" value="LEWIS,ANGELA D" /></div></li>
   <li><div><input name="itemValue" type="hidden" value="LEWIS,ANGELA DIANNA" /></div></li>
   <li><div><input name="itemValue" type="hidden" value="LEWIS,ANGELA H" /></div></li>
  </ul>
 </li>
</div>
"""


def test_leaf_match_normalizes_comma_spacing_lewis_regression():
    """Brevard stores pre-2007 names as 'LEWIS, ANGELA D' and 2007+ as
    'LEWIS,ANGELA D'. A space-sensitive match selected only the former and
    silently dropped the subject's CURRENT open Truist mortgage (2026091512).
    Both comma forms of the same identity must be selected; different middle
    initials (ANGELA H) must stay excluded."""
    a = _adapter()
    a.session.post.side_effect = [
        _resp(text=NAME_TREE_DUAL_FORMAT),
        _resp(text="<html>shell</html>"),
        _resp(payload={"data": [], "total": 0}),
    ]
    a.perform_search("LEWIS, ANGELA D", party_type="Both")
    p2 = a.session.post.call_args_list[1].kwargs.get("data") or a.session.post.call_args_list[1].args[1]
    selected = p2["NameList"].split("|||")
    assert "LEWIS, ANGELA D" in selected
    assert "LEWIS,ANGELA D" in selected
    assert "LEWIS,ANGELA DIANNA" in selected   # DIANNA startswith "ANGELA D"
    assert "LEWIS,ANGELA H" not in selected


def test_normalize_party_name():
    f = AcclaimWebHTTPAdapter._normalize_party_name
    # Comma is treated as whitespace so all three index renderings of the SAME
    # identity collapse to one form: Telerik comma-space, Telerik comma-no-space,
    # and Kendo TreeView comma-less (Duval/OnCore).
    assert (
        f("LEWIS, ANGELA D")
        == f("LEWIS,ANGELA D")
        == f("LEWIS ANGELA D")
        == "LEWIS ANGELA D"
    )
    assert f("  lewis ,  angela   d ") == "LEWIS ANGELA D"
    assert f("LEWIS,ANGELA H") != f("LEWIS,ANGELA D")
    # Comma-form search prefix must startswith-match a comma-less Kendo leaf of
    # the same identity (Duval SKINNER MICHAEL W regression).
    assert f("SKINNER MICHAEL W").startswith(f("SKINNER, MICHAEL"))
    assert not f("SKINNER MICHAEL T").startswith(f("SKINNER, MICHAEL W"))


def test_download_pdf_uses_grid_cached_token(tmp_path):
    a = _adapter()
    a.row_extras["1996067410"] = {"transaction_item_id": 2576997}
    viewer_html = "src='/WebAtalaCache/abc123_2576997_docPdf.pdf'"
    pdf_bytes = b"%PDF-1.4 fake"
    sir = _resp(text="Done")
    viewer = _resp(text=viewer_html)
    pdf = MagicMock(); pdf.status_code = 200; pdf.content = pdf_bytes
    a.session.get.side_effect = [sir, viewer, pdf]
    out = a.download_pdf("1996067410", tmp_path / "x.pdf")
    assert out["status"] == "success"
    assert out["src_via"] == "grid_cache"
    assert (tmp_path / "x.pdf").read_bytes() == pdf_bytes
    # No jump GET — first session.get was StartImageRetrieval.
    first_url = a.session.get.call_args_list[0].args[0]
    assert "StartImageRetrieval" in first_url
