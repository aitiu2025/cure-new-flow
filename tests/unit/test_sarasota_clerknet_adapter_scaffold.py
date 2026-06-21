"""STAGED scaffold tests for the Sarasota ClerkNet HTTP recorder adapter.

OPERATOR ACTION REQUIRED: direct Write to tests/unit/ was permission-denied
during the Wave-1 session (2026-06-10). To install:

    cp "src/titlepro/api/downloaded_doc/0610/Sarasota_BRUNO_v1/staged_tests_test_sarasota_clerknet_adapter_scaffold.py" \
       "tests/unit/test_sarasota_clerknet_adapter_scaffold.py"

No network. The WebForms LANDING-page fixture mirrors the live capture from
the 2026-06-10 probe (field names, hidden fields, doc-type checkbox markup
are verbatim shapes). The RESULT-grid fixture is SYNTHETIC Telerik RadGrid
markup (live POST operator-denied in Wave 1) — Wave 2 must re-validate
against a captured live result page.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Walk upward to the repo root so the test passes from BOTH tests/unit/ and
# the Wave-1 staged location inside the case dir.
_here = Path(__file__).resolve()
REPO_ROOT = next(
    p for p in _here.parents if (p / "src" / "titlepro" / "search").is_dir()
)
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.search.recorder.counties.adapters.sarasota_clerknet_http_adapter import (  # noqa: E402
    SarasotaClerkNetHTTPAdapter,
)

CONFIG_PATH = (
    SRC / "titlepro" / "search" / "recorder" / "counties" / "config" / "fl" / "sarasota.json"
)


@pytest.fixture
def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def adapter(config) -> SarasotaClerkNetHTTPAdapter:
    return SarasotaClerkNetHTTPAdapter(
        config, start_date="01/01/1990", end_date="06/10/2026"
    )


# Landing-page fixture — hidden fields + form controls verbatim-shaped from
# the 2026-06-10 live capture of OfficialRecords.aspx.
LANDING_HTML = """
<html><body>
<form method="post" action="./OfficialRecords.aspx" id="decorationZone">
<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />
<input type="hidden" name="__EVENTARGUMENT" id="__EVENTARGUMENT" value="" />
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS_AAA111" />
<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="GEN12345" />
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV_BBB222" />
<input type="hidden" name="ToolkitScriptManager1_HiddenField" id="ToolkitScriptManager1_HiddenField" value="" />
<input id="ctl00_cphBody_tbParty" name="ctl00$cphBody$tbParty" type="text" value="" />
<input id="ctl00_cphBody_tbPartyFirst" name="ctl00$cphBody$tbPartyFirst" type="text" value="" />
<input id="ctl00_cphBody_tbLic" name="ctl00$cphBody$tbLic" type="text" value="" />
<input id="ctl00_cphBody_rdAppFrom_dateInput" name="ctl00$cphBody$rdAppFrom$dateInput" type="text" />
<input id="ctl00_cphBody_rdAppTo_dateInput" name="ctl00$cphBody$rdAppTo$dateInput" type="text" />
<input id="ctl00_cphBody_tbBook" name="ctl00$cphBody$tbBook" type="text" value="" />
<input id="ctl00_cphBody_tbPage" name="ctl00$cphBody$tbPage" type="text" value="" />
<input id="cphBody_cbDocType_71" type="checkbox" name="ctl00$cphBody$cbDocType$71" value="D" /><label for="cphBody_cbDocType_71">DEED</label>
<input id="cphBody_cbDocType_146" type="checkbox" name="ctl00$cphBody$cbDocType$146" value="M" /><label for="cphBody_cbDocType_146">MORTGAGE</label>
<input id="cphBody_cbDocType_167" type="checkbox" name="ctl00$cphBody$cbDocType$167" value="NC" /><label for="cphBody_cbDocType_167">NOTICE OF COM</label>
<input id="cphBody_cbDocType_254" type="checkbox" name="ctl00$cphBody$cbDocType$254" value="SM" /><label for="cphBody_cbDocType_254">SATISFACTION OF MORTGAGE</label>
<span id="ctl00_cphBody_bSearch"><input type="submit" name="ctl00$cphBody$bSearch_input" id="ctl00_cphBody_bSearch_input" value="Search" /></span>
<div id="ctl00_cphBody_rgCaseList" class="RadGrid RadGrid_Simple"></div>
</form>
</body></html>
"""

# LIVE-VALIDATED RadGrid result fixture (Wave-2 POST #1, 2026-06-10): real
# columns are Image | Instrument Number | Book-Page | Date Recorded |
# Document Type | Name | Legal Description. The Name cell carries ALL
# parties <br>-separated, no grantor/grantee marker. Image href is
# /viewTiff.aspx?intrnum=<instrument>.
RESULTS_HTML = """
<html><body>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS_ROTATED_2" />
<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="GEN12345" />
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV_ROTATED_2" />
<div id="ctl00_cphBody_rgCaseList" class="RadGrid RadGrid_Simple">
<table class="rgMasterTable" id="ctl00_cphBody_rgCaseList_ctl00">
<thead><tr>
  <th scope="col" class="rgHeader"><a href="#">Image</a></th>
  <th scope="col" class="rgHeader"><a href="#">Instrument Number</a></th>
  <th scope="col" class="rgHeader"><a href="#">Book-Page</a></th>
  <th scope="col" class="rgHeader"><a href="#">Date Recorded</a></th>
  <th scope="col" class="rgHeader"><a href="#">Document Type</a></th>
  <th scope="col" class="rgHeader"><a href="#">Name</a></th>
  <th scope="col" class="rgHeader"><a href="#">Legal Description</a></th>
</tr></thead>
<tbody>
<tr class="rgRow" id="ctl00_cphBody_rgCaseList_ctl00__0">
  <td><a target=_blank href=/viewTiff.aspx?intrnum=2013021460>View Image</a></td>
  <td>2013021460</td><td>2180-2594</td><td>02/25/2013</td><td>DEED</td>
  <td>SHOLA THOMAS P<br>BRUNO EMELIA M<br>BRUNO EMELIA M TRUSTEE<br></td>
  <td>LOT 22 RIVENDELL UNIT 1<br></td>
</tr>
<tr class="rgAltRow" id="ctl00_cphBody_rgCaseList_ctl00__1">
  <td><a target=_blank href=/viewTiff.aspx?intrnum=2013023999>View Image</a></td>
  <td>2013023999</td><td></td><td>03/01/2013</td><td>MORTGAGE</td>
  <td>BRUNO EMELIA M<br>SUNCOAST BANK<br></td>
  <td>LOT 22 RIVENDELL UNIT 1<br></td>
</tr>
<tr class="rgRow" id="ctl00_cphBody_rgCaseList_ctl00__2">
  <td><a target=_blank href=/viewTiff.aspx?intrnum=2013023999>View Image</a></td>
  <td>2013023999</td><td></td><td>03/01/2013</td><td>MORTGAGE</td>
  <td>DUPLICATE ROW<br>SHOULD BE DEDUPED<br></td>
  <td></td>
</tr>
</tbody></table></div>
</body></html>
"""


# ------------------------------------------------------------------ config


def test_config_loads_and_adapter_instantiates(adapter, config):
    assert config["county_id"] == "fl_sarasota"
    assert config["platform"] == "sarasota_clerknet_http"
    assert config["captcha_required"] is False
    assert adapter.county_name == "Sarasota"
    assert "secure.sarasotaclerk.com" in adapter.base_url
    assert adapter.driver is None  # Tony #1: no browser, ever


def test_config_doctype_semantics(config):
    codes = config["doctype_codes"]
    assert codes["DEED"] == "D"
    assert codes["NOC"] == "NC"
    assert codes["SATISFACTION_OF_MORTGAGE"] == "SM"
    assert codes["DECLARATION_OF_TRUST"] == "DTR"  # trust-chain case support


# --------------------------------------------------------- WebForms state


def test_refresh_webforms_state_scrapes_hidden_fields(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    st = adapter._webforms_state
    assert st["__VIEWSTATE"] == "VS_AAA111"
    assert st["__VIEWSTATEGENERATOR"] == "GEN12345"
    assert st["__EVENTVALIDATION"] == "EV_BBB222"
    assert st["__EVENTTARGET"] == ""


def test_webforms_state_rotates_on_new_response(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    adapter._refresh_webforms_state(RESULTS_HTML)
    # anti-[N,0,0,0,0,0]: the SECOND response's VIEWSTATE must win
    assert adapter._webforms_state["__VIEWSTATE"] == "VS_ROTATED_2"
    assert adapter._webforms_state["__EVENTVALIDATION"] == "EV_ROTATED_2"


def test_refresh_doctype_indices(adapter):
    adapter._refresh_doctype_indices(LANDING_HTML)
    assert adapter._doctype_index_by_code["D"] == 71
    assert adapter._doctype_index_by_code["M"] == 146
    assert adapter._doctype_index_by_code["NC"] == 167
    assert adapter._doctype_index_by_code["SM"] == 254


# -------------------------------------------------------------- payloads


def test_build_search_payload_name_search(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    adapter._refresh_doctype_indices(LANDING_HTML)
    p = adapter.build_search_payload(name="BRUNO EMELIA M")
    assert p["ctl00$cphBody$tbParty"] == "BRUNO EMELIA M"
    assert p["ctl00$cphBody$tbPartyFirst"] == ""
    assert p["ctl00$cphBody$tbLic"] == ""
    assert p["ctl00$cphBody$rdAppFrom$dateInput"] == "1/1/1990"
    assert p["ctl00$cphBody$rdAppTo$dateInput"] == "6/10/2026"
    assert p["__VIEWSTATE"] == "VS_AAA111"
    assert p["__EVENTVALIDATION"] == "EV_BBB222"
    assert p["ctl00$cphBody$bSearch_input"] == "Search"
    # No doc-type filter → no checkbox key at all
    assert not any(k.startswith("ctl00$cphBody$cbDocType$") for k in p)


def test_build_search_payload_deed_first(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    adapter._refresh_doctype_indices(LANDING_HTML)
    p = adapter.build_search_payload(name="SHOLA THOMAS P", doc_type="DEED")
    assert p["ctl00$cphBody$cbDocType$71"] == "D"  # Tony #2 deed-first


def test_build_search_payload_doctype_without_warm_raises(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    # No _refresh_doctype_indices → index unknown → must raise loudly, not
    # silently drop the filter.
    with pytest.raises(ValueError):
        adapter.build_search_payload(name="X", doc_type="DEED")


def test_build_search_payload_instrument_direct_retrieval(adapter):
    adapter._refresh_webforms_state(LANDING_HTML)
    p = adapter.build_search_payload(instrument="2013021460")
    assert p["ctl00$cphBody$tbLic"] == "2013021460"
    assert p["ctl00$cphBody$tbParty"] == ""
    # Instrument retrieval must NOT be date-bounded
    assert p["ctl00$cphBody$rdAppFrom$dateInput"] == ""
    assert p["ctl00$cphBody$rdAppTo$dateInput"] == ""


def test_normalize_date_variants(adapter):
    assert adapter._normalize_date("01/01/1990") == "1/1/1990"
    assert adapter._normalize_date("06/10/2026") == "6/10/2026"
    assert adapter._normalize_date("2026-06-10") == "6/10/2026"
    assert adapter._normalize_date("") == ""
    assert adapter._normalize_date(None) == ""


# --------------------------------------------------------- extract_results


def test_extract_results_header_driven_and_deduped(adapter):
    docs = adapter.extract_results(RESULTS_HTML)
    assert len(docs) == 2  # third row is a duplicate instrument → deduped
    d0 = docs[0]
    assert d0.document_number == "2013021460"
    assert d0.recording_date == "02/25/2013"
    assert d0.document_type == "DEED"
    # The live grid does NOT mark grantor/grantee — combined parties land in
    # grantor_grantees; per-side fields stay empty until OCR classification.
    assert d0.grantors == "" and d0.grantees == ""
    assert "SHOLA THOMAS P" in d0.grantor_grantees
    assert "BRUNO EMELIA M TRUSTEE" in d0.grantor_grantees
    d1 = docs[1]
    assert d1.document_number == "2013023999"
    assert "SUNCOAST BANK" in d1.grantor_grantees
    # Image URL stashed for the download phase (live viewTiff shape)
    assert "viewTiff.aspx?intrnum=2013021460" in adapter._doc_id_by_number["2013021460"]
    # Book-Page + Legal stashed in row extras
    extras = adapter._row_extras_by_number["2013021460"]
    assert extras["book_page"] == "2180-2594"
    assert "RIVENDELL" in extras["legal"]
    assert "SHOLA THOMAS P" in extras["parties"]


def test_extract_results_empty_and_no_grid(adapter):
    assert adapter.extract_results("") == []
    assert adapter.extract_results("<html><body><p>No records found.</p></body></html>") == []


def test_radinput_client_state_payload(adapter):
    """ClientState is LOAD-BEARING (live-proven): the server reads
    valueAsString from <field>_ClientState, not the bare text input."""
    adapter._refresh_webforms_state(LANDING_HTML)
    p = adapter.build_search_payload(name="BRUNO", first_name="EMELIA")
    cs = p["ctl00_cphBody_tbParty_ClientState"]
    assert '"valueAsString":"BRUNO"' in cs
    cs_first = p["ctl00_cphBody_tbPartyFirst_ClientState"]
    assert '"valueAsString":"EMELIA"' in cs_first
    # Date ClientStates use the Telerik wire format yyyy-MM-dd-00-00-00
    cs_from = p["ctl00_cphBody_rdAppFrom_dateInput_ClientState"]
    assert '"valueAsString":"1990-01-01-00-00-00"' in cs_from
    # Hidden picker field carries yyyy-MM-dd
    assert p["ctl00$cphBody$rdAppFrom"] == "1990-01-01"


def test_split_subject_name():
    split = SarasotaClerkNetHTTPAdapter.split_subject_name
    assert split("BRUNO EMELIA M") == ("BRUNO", "EMELIA M")
    assert split("SHOLA THOMAS") == ("SHOLA", "THOMAS")
    assert split("BRUNO") == ("BRUNO", "")
    # Trust/business names are NOT split
    assert split("THOMAS SHOLA AND EMELIA BRUNO REVOCABLE TRUST") == (
        "THOMAS SHOLA AND EMELIA BRUNO REVOCABLE TRUST", "",
    )


def test_pull_pdf_uses_viewtiff_endpoint(adapter):
    """pull_pdf GETs the live-validated /viewTiff.aspx?intrnum= endpoint."""
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"%PDF-1.4 fake"
    resp.headers = {"content-type": "application/pdf"}
    session = MagicMock()
    session.get.return_value = resp
    adapter.session = session
    body = adapter.pull_pdf("2013021460")
    assert body.startswith(b"%PDF")
    url_called = session.get.call_args[0][0]
    assert "viewTiff.aspx?intrnum=2013021460" in url_called


def test_pager_info_and_refusal_threshold(adapter):
    items, pages = adapter._pager_info("&nbsp; 500  items in  42  pages")
    assert (items, pages) == (500, 42)
    assert adapter._pager_info("<html>no pager</html>") == (0, 1)
