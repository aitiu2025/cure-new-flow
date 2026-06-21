"""Unit tests for the DuProcess Web Inquiry HTTP recorder adapter (Seminole FL et al.).

Mocked sessions only -- no live DuProcess traffic. The live host geo-blocks the build
env; the canned JSON shapes below mirror the SPA's igGrid result columns (verified from
assets/index.6bae0200.js, capture 2026-02-11). See
src/titlepro/api/downloaded_doc/0610/Seminole_PORTILLA_v1/phase0_probe_recorder.md.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.search.recorder.base_recorder import DocumentRecord  # noqa: E402
from titlepro.search.recorder.counties.adapters.duprocess_http_adapter import (  # noqa: E402
    DuProcessHTTPAdapter,
    obfuscate_gin,
    build_access_key,
)


CONFIG = {
    "county_id": "fl_seminole",
    "county_name": "Seminole",
    "app_root": "https://recording.seminoleclerk.org/DuProcessWebInquiry/",
    "impersonate_profile": "safari17_2_ios",
    "party_type_map": {"All": "", "Both": "", "Grantor": "F", "Grantee": "T"},
}


def _resp(status_code: int, payload: Any):
    r = MagicMock()
    r.status_code = status_code
    r.text = payload if isinstance(payload, str) else json.dumps(payload)
    return r


SEARCH_ROWS = [
    {
        "gin": "5551234",
        "inst_num": "2018012345",
        "from_party": "SMITH JOHN",
        "to_party": "PORTILLA MARK J & ANGELA M",
        "instrument_type": "DEED",
        "file_date": "06/15/2018 12:00:00 AM",
        "book_reel": "09112",
        "page": "0455",
        "num_pages": "3",
        "real_estate_id": "01-21-29-5LM-0000-0510",
        "verified_status": "Verified",
    },
    {
        "gin": "5559999",
        "inst_num": "2018012346",
        "from_party": "PORTILLA MARK J & ANGELA M",
        "to_party": "FAIRWAY MORTGAGE",
        "instrument_type": "MORTGAGE",
        "file_date": "/Date(1529020800000)/",
        "book_reel": "09112",
        "page": "0460",
        "num_pages": "12",
        "parcel_number": "01-21-29-5LM-0000-0510",
    },
]


def test_obfuscate_gin_cipher():
    assert obfuscate_gin("12345") == "ABCDE"
    assert obfuscate_gin("0987") == "JIHG"
    assert obfuscate_gin("0000000") == "JJJJJJJ"


def test_build_access_key_recipe():
    ak = build_access_key("12345", "0", datetime(2026, 6, 10, 14, 37, 5))
    assert ak == "ABCDE!0-37-5"
    # dotted IP octets are summed
    ak2 = build_access_key("12", "1.2.3.4", datetime(2026, 6, 10, 0, 9, 0))
    assert ak2 == "AB!10-9-0"


def test_build_criteria_array_full_field_set():
    a = DuProcessHTTPAdapter(CONFIG)
    raw = a.build_criteria_array(
        name="PORTILLA, MARK", direction="", inst_type="'DEED'",
        date_from="01/01/1990", date_to="06/10/2026",
    )
    arr = json.loads(raw)
    assert isinstance(arr, list) and len(arr) == 1
    c = arr[0]
    assert c["full_name"] == "PORTILLA, MARK"
    assert c["inst_type"] == "'DEED'"
    assert c["direction"] == ""
    assert c["file_date_start"] == "01/01/1990"
    assert c["file_date_end"] == "06/10/2026"
    # apostrophes stripped from name
    raw2 = a.build_criteria_array(name="O'BRIEN, PAT")
    assert json.loads(raw2)[0]["full_name"] == "OBRIEN, PAT"


def test_criteria_array_parcel_search_leg():
    a = DuProcessHTTPAdapter(CONFIG)
    c = json.loads(a.build_criteria_array(parcel_id="01212950000000510"))[0]
    assert c["parcel_id"] == "01212950000000510"
    assert c["full_name"] == ""


def test_perform_search_parses_rows_and_caches_gin_and_apn():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a._session_warmed = True
    a.session.get.return_value = _resp(200, SEARCH_ROWS)
    recs = a.perform_search("PORTILLA, MARK", party_type="All")
    assert len(recs) == 2
    assert all(isinstance(r, DocumentRecord) for r in recs)
    assert recs[0].document_number == "2018012345"
    assert recs[0].document_type == "DEED"
    assert recs[0].grantees == "PORTILLA MARK J & ANGELA M"
    assert recs[0].pages == "3"
    # gin + apn cached for downstream image retrieval / parcel re-search
    assert a._gin_by_number["2018012345"] == "5551234"
    assert a.last_apn_by_number["2018012345"] == "01-21-29-5LM-0000-0510"


def test_file_date_normalization_both_shapes():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a._session_warmed = True
    a.session.get.return_value = _resp(200, SEARCH_ROWS)
    recs = a.perform_search("PORTILLA, MARK")
    # "06/15/2018 12:00:00 AM" -> "06/15/2018"
    assert recs[0].recording_date == "06/15/2018"
    # "/Date(1529020800000)/" -> "06/15/2018"
    assert recs[1].recording_date == "06/15/2018"


def test_extract_results_handles_d_envelope():
    a = DuProcessHTTPAdapter(CONFIG)
    recs = a.extract_results(json.dumps({"d": SEARCH_ROWS}))
    assert len(recs) == 2


def test_extract_results_handles_records_envelope():
    a = DuProcessHTTPAdapter(CONFIG)
    recs = a.extract_results({"Records": SEARCH_ROWS})
    assert len(recs) == 2


def test_perform_search_http_error_returns_empty():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a._session_warmed = True
    a.session.get.return_value = _resp(500, "boom")
    assert a.perform_search("PORTILLA, MARK") == []
    assert "500" in (a.last_failure or "")


def test_party_type_direction_mapping():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a._session_warmed = True
    a.session.get.return_value = _resp(200, [])
    a.perform_search("PORTILLA, MARK", party_type="Grantor")
    sent = json.loads(a.session.get.call_args.kwargs["params"]["criteria_array"])[0]
    assert sent["direction"] == "F"


def test_query_instrument_id_direct_retrieval():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, {"gin": "5551234"})
    out = a.query_instrument_id(book="09112", page="0455")
    assert out == {"gin": "5551234"}
    params = a.session.get.call_args.kwargs["params"]
    assert params["book"] == "09112" and params["page"] == "0455"


def test_document_image_and_pdf_urls_use_obfuscated_gin():
    a = DuProcessHTTPAdapter(CONFIG)
    urls = a.document_image_urls("12345", num_pages=2)
    assert len(urls) == 2
    assert urls[0].endswith("/GetDocumentPage/undefined,ABCDE,0")
    assert urls[1].endswith(",ABCDE,1")
    pdf = a.pdf_document_url("12345")
    assert "/CreateDocument/undefined," in pdf
    assert "ABCDE!" in pdf


def test_verified_until_date_msajax_parse():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a.session.get.return_value = _resp(200, '"/Date(1529020800000)/"')
    assert a.get_verified_until_date() == "06/15/2018"


def test_pull_detail_resolves_gin_from_cache():
    a = DuProcessHTTPAdapter(CONFIG)
    a.session = MagicMock()
    a._session_warmed = True
    a._gin_by_number["2018012345"] = "5551234"
    a.session.get.return_value = _resp(200, {"PrimaryKeyValue": 5551234, "InstrumentType": {}})
    out = a.pull_detail("2018012345")
    assert out["gin"] == "5551234"
    assert "detail" in out
