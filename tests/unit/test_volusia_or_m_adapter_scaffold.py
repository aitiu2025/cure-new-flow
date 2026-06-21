"""Scaffold tests for the Volusia or_m recorder adapter.

The results-grid fixture is the REAL inquiry.aspx HTML from the Internet
Archive's 2026-01-13 capture of https://app02.clerk.org/or_m/inquiry.aspx
(saved at tests/fixtures/volusia/or_m_inquiry_wayback_20260113.html). It
contains both the populated WebForms search form AND a 25-party-row results
grid — so hidden-field harvesting, payload assembly, and grid parsing are all
exercised against genuine portal markup.

LIVE portal could not be probed on 2026-06-10: clerk.org refuses TCP from
non-US egress IPs. Wave-2 must re-validate live from a US network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.search.recorder.counties.adapters.volusia_or_m_adapter import (  # noqa: E402
    VolusiaOrMAdapter,
)

FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "volusia" / "or_m_inquiry_wayback_20260113.html"
)
HTML = FIXTURE.read_text()

CONFIG = {
    "county_name": "Volusia",
    "base_url": "https://app02.clerk.org/or_m/",
    "record_cap": "500",
    "doc_type_map": {"DEED": "DEED", "MORTGAGE": "MORTGAGE"},
    "party_type_map": {
        "Both": "BOTH",
        "Grantor/Grantee": "BOTH",
        "All": "BOTH",
        "Grantor": "DIRECT",
        "Grantee": "REVERSE",
    },
}


@pytest.fixture
def adapter():
    return VolusiaOrMAdapter(CONFIG, start_date="01/01/1996", end_date="06/10/2026")


# ---------------------------------------------------------------------------
# Hidden-field harvesting (WebForms VIEWSTATE flow)
# ---------------------------------------------------------------------------


def test_harvest_hidden_fields_finds_viewstate(adapter):
    fields = adapter._harvest_hidden_fields(HTML)
    assert "__VIEWSTATE" in fields
    assert "__VIEWSTATEGENERATOR" in fields
    assert "__EVENTVALIDATION" in fields
    assert fields["__VIEWSTATE"]  # non-empty
    assert fields["__VIEWSTATEGENERATOR"] == "A968739B"


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def test_build_search_payload_shape(adapter):
    adapter._hidden_fields = adapter._harvest_hidden_fields(HTML)
    p = adapter.build_search_payload("GUILD, MARYKE Y", "Both", doc_type="DEED")

    assert p["__EVENTTARGET"] == "ctl00$ContentPlaceHolder1$search"
    assert p["__VIEWSTATE"]
    assert p["ctl00$ContentPlaceHolder1$name"] == "GUILD MARYKE Y"  # comma stripped
    assert p["ctl00$ContentPlaceHolder1$nameType"] == "BOTH"
    # doctype option values are right-padded to 20 chars on the portal.
    assert p["ctl00$ContentPlaceHolder1$doctype"] == "DEED".ljust(20)
    assert len(p["ctl00$ContentPlaceHolder1$doctype"]) == 20
    assert p["ctl00$ContentPlaceHolder1$fromDateTxt"] == "01/01/1996"
    assert p["ctl00$ContentPlaceHolder1$toDateTxt"] == "06/10/2026"
    assert p["ctl00$ContentPlaceHolder1$Grid$ctl01$MaxRows"] == "500"


def test_build_search_payload_all_doc_types_empty(adapter):
    adapter._hidden_fields = {"__VIEWSTATE": "x"}
    p = adapter.build_search_payload("GUILD JUSTIN P", "Grantor")
    assert p["ctl00$ContentPlaceHolder1$doctype"] == ""
    assert p["ctl00$ContentPlaceHolder1$nameType"] == "DIRECT"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("GUILD, MARYKE Y", "GUILD MARYKE Y"),
        ("guild justin p", "GUILD JUSTIN P"),
        ("  SMITH ,  JOHN ", "SMITH JOHN"),
    ],
)
def test_normalize_name(raw, expected):
    assert VolusiaOrMAdapter._normalize_name(raw) == expected


# ---------------------------------------------------------------------------
# Results-grid parsing — real Wayback markup
# ---------------------------------------------------------------------------


def test_extract_results_merges_party_rows(adapter):
    records = adapter.extract_results(HTML)
    # 25 party rows on the page collapse to 9 distinct instruments.
    assert len(records) == 9
    by_num = {r.document_number: r for r in records}

    jdo = by_num["2015177048"]
    # Full doc type comes from the popover data-content, not the abbreviation.
    assert jdo.document_type == "JUDGMENT/ORDER"
    assert jdo.recording_date == "09/22/2015"
    assert jdo.grantors == "STATE OF FLORIDA"
    assert "BENITEZ SIPRIANO OCAMPO" in jdo.grantees


def test_extract_results_multi_party_deed(adapter):
    records = adapter.extract_results(HTML)
    by_num = {r.document_number: r for r in records}
    deed = by_num["2015177052"]
    assert deed.document_type == "DEED"
    # Husband + wife on each side, merged from 4 grid rows.
    assert "BUSEK RICHARD COLLUM" in deed.grantors
    assert "BUSEK MARY HELEN" in deed.grantors
    assert "HUFF ROBERT J" in deed.grantees
    assert "HUFF CAROLYN JOYCE" in deed.grantees


def test_extract_results_empty_html(adapter):
    assert adapter.extract_results("<html><body>no grid</body></html>") == []
    assert adapter.extract_results("") == []


def test_extract_results_skips_header_and_pager_rows(adapter):
    records = adapter.extract_results(HTML)
    nums = [r.document_number for r in records]
    assert all(n.isdigit() for n in nums)
    assert len(nums) == len(set(nums))  # no duplicates after merge


# ---------------------------------------------------------------------------
# Direct retrieval (Broward-Standard item #4)
# ---------------------------------------------------------------------------


def test_direct_instrument_url(adapter):
    url = adapter.direct_instrument_url("2016240819")
    assert url == "https://app02.clerk.org/or_m/Default.aspx?s=orapr&i=2016240819"


def test_interface_parity_props(adapter):
    assert adapter.county_name == "Volusia"
    assert adapter.base_url == "https://app02.clerk.org/or_m/"
    assert adapter.setup_driver() is None
