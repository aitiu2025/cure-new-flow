"""Unit tests for the PublicSoft BrowserView OR recorder adapter (Polk County).

No live traffic — the live host (apps.polkcountyclerk.net) is firewall/geo-fenced
and was unreachable Wave-1, so request/response shapes were reverse-engineered
from the SPA's archived JS bundle (see Polk_BUNKER_v1/phase0_probe_recorder.md).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.search.recorder.base_recorder import DocumentRecord  # noqa: E402
from titlepro.search.recorder.counties.adapters.publicsoft_or_adapter import (  # noqa: E402
    PublicSoftORAdapter,
    _truthy,
)

POLK_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDXBPCKXRqaD74rYrPXU/DA4Z5H"
    "mJbNivwCYijae6QXu/QLqS3GbyGrxkrEmdODbYWOLJfWBvaQSALcolSyKQUvtkjz"
    "g61bJC2/xNk4HTHFrA4uAMMvC+49RlSgtEm5dI10+YOp0TGId1d4E0Ey0RDQxNWa"
    "ev2TeleyipADuctnqwIDAQAB\n"
    "-----END PUBLIC KEY-----\n"
)


def _cfg(**overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "county_id": "fl_polk",
        "county_name": "Polk",
        "state": "FL",
        "platform": "publicsoft_or",
        "base_url": "https://apps.polkcountyclerk.net/browserviewor/",
        "encrypt_data": False,
        "rsa_public_key": POLK_PUBLIC_KEY,
        "name_format": "last_first_no_comma",
    }
    base.update(overrides)
    return base


def _adapter(**overrides) -> PublicSoftORAdapter:
    return PublicSoftORAdapter(_cfg(**overrides), start_date="01/01/2010", end_date="06/10/2026")


def test_rsa_encrypt_matches_jsencrypt_shape():
    a = _adapter(encrypt_data=True)
    ct = a._enc("BUNKER WILLIAM")
    raw = base64.b64decode(ct)
    assert len(raw) == 128
    assert len(ct) == 172
    assert a._enc("BUNKER WILLIAM") != ct


def test_encrypt_data_false_is_passthrough():
    a = _adapter(encrypt_data=False)
    assert a._enc("BUNKER WILLIAM") == "BUNKER WILLIAM"
    assert a._enc_int(200) == 200
    assert a._enc_int(0) == 0


def test_enc_int_leading_space_when_encrypted():
    a = _adapter(encrypt_data=True)
    assert a._enc_int(0) == 0
    enc = a._enc_int(700)
    assert isinstance(enc, str) and len(base64.b64decode(enc)) == 128


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Bunker, William Joseph", "BUNKER WILLIAM JOSEPH"),
        ("BUNKER WILLIAM", "BUNKER WILLIAM"),
        ("  Julie  Chambers   Bunker ", "JULIE CHAMBERS BUNKER"),
    ],
)
def test_name_normalization_last_first(raw, expected):
    assert _adapter()._normalize_name(raw) == expected


def test_build_search_payload_deed_first():
    a = _adapter()
    p = a.build_search_payload(name="BUNKER WILLIAM", doc_type="DEED")
    assert p["Party"] == "BUNKER WILLIAM"
    assert p["DocTypes"] == "DEED"
    assert p["FromDate"] == "20100101"
    assert p["ToDate"] == "20260610"
    assert p["StartRow"] == 0


def test_build_search_payload_all_docs_has_no_doctypes():
    p = _adapter().build_search_payload(name="BUNKER WILLIAM")
    assert "DocTypes" not in p
    assert p["Party"] == "BUNKER WILLIAM"


def test_build_search_payload_file_number_direct_retrieval():
    p = _adapter().build_search_payload(file_number="2018123456")
    assert p["FileNumber"] == "2018123456"
    assert "Party" not in p


def test_build_search_payload_parcel():
    p = _adapter().build_search_payload(parcel="24-29-12-000000-012345")
    assert p["Parcel"] == "24-29-12-000000-012345"
    assert p["Party"] == ""


def test_date_conversion_variants():
    a = _adapter()
    assert a._to_wire_date("03/15/2018") == "20180315"
    assert a._to_wire_date("2018-03-15") == "20180315"
    assert a._to_wire_date("") == ""


def test_document_detail_payload_id_path():
    a = _adapter()
    p = a.build_document_detail_payload(doc_id="ABC123", page_number=2)
    assert p["ID"] == " ABC123"
    assert p["Page"] == "2"
    assert p["Convert"] is True


def test_document_detail_payload_book_page_path():
    a = _adapter()
    p = a.build_document_detail_payload(book="4521", page="1410", book_type="O")
    assert p["Book"] == " 4521"
    assert p["PageNumber"] == " 1410"
    assert p["BookType"] == " O"


def test_pdf_payload():
    a = _adapter()
    p = a.build_pdf_payload(doc_id="ABC123", start_page=1, pages=3)
    assert p["ID"] == " ABC123"
    assert p["StartPage"] == 1
    assert p["Pages"] == 3


_CANNED_ROWS: List[Dict[str, Any]] = [
    {
        "_total_rows": 2, "_start_row": 0, "_end_row": 2, "_max_rows": 0,
        "doc_number": "2018123456", "grantor": "TOIVANEN PERTTU",
        "grantee": "BUNKER WILLIAM JOSEPH; BUNKER JULIE CHAMBERS",
        "doc_type": "DEED", "record_date": "2018-05-14T00:00:00", "pages": 3, "id": "ROW-1",
    },
    {
        "doc_number": "2019099887", "grantor": "BUNKER WILLIAM JOSEPH",
        "grantee": "FAIRWAY INDEPENDENT MORTGAGE", "doc_type": "MTG",
        "record_date": "20190620", "pages": 12, "id": "ROW-2",
    },
]


def test_parse_search_results_maps_rows():
    a = _adapter()
    docs = a.parse_search_results(_CANNED_ROWS)
    assert len(docs) == 2
    assert all(isinstance(d, DocumentRecord) for d in docs)
    d0 = docs[0]
    assert d0.document_number == "2018123456"
    assert d0.grantors == "TOIVANEN PERTTU"
    assert "BUNKER JULIE CHAMBERS" in d0.grantees
    assert d0.document_type == "DEED"
    assert d0.recording_date == "05/14/2018"
    assert d0.pages == "3"
    assert docs[1].recording_date == "06/20/2019"


def test_parse_caches_doc_ids():
    a = _adapter()
    a.parse_search_results(_CANNED_ROWS)
    assert a._doc_id_by_number["2018123456"] == "ROW-1"
    assert a._doc_id_by_number["2019099887"] == "ROW-2"


def test_search_meta_reads_total_rows():
    meta = PublicSoftORAdapter.search_meta(_CANNED_ROWS)
    assert meta["total_rows"] == 2
    assert meta["start_row"] == 0


def test_result_field_map_override():
    a = _adapter(result_field_map={
        "document_number": ["cfn"], "grantors": ["from"], "grantees": ["to"],
        "document_type": ["kind"], "recording_date": ["rdate"], "pages": ["pg"],
        "doc_id": ["rid"],
    })
    rows = [{"cfn": "X1", "from": "A", "to": "B", "kind": "DEED", "rdate": "01/02/2020", "pg": 1, "rid": "z"}]
    docs = a.parse_search_results(rows)
    assert docs[0].document_number == "X1"
    assert docs[0].document_type == "DEED"
    assert a._doc_id_by_number["X1"] == "z"


def test_warm_session_reads_encrypt_data_from_clientinfo():
    a = _adapter(encrypt_data=None)
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"name": "Polk", "encryptData": "Y", "showParty": "Y"}
    sess.get.return_value = resp
    a.session = sess
    assert a.warm_session() is True
    assert a._encrypt_data is True


def test_perform_search_end_to_end_mocked():
    a = _adapter()
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _CANNED_ROWS
    sess.post.return_value = resp
    a.session = sess
    a._session_warmed = True
    docs = a.perform_search("Bunker, William Joseph", doc_type="DEED")
    assert len(docs) == 2
    args, kwargs = sess.post.call_args
    body = json.loads(kwargs["data"])
    assert body["Party"] == "BUNKER WILLIAM JOSEPH"
    assert body["DocTypes"] == "DEED"


def test_truthy_helper():
    assert _truthy("Y") and _truthy("1") and _truthy("T") and _truthy(True)
    assert not _truthy("") and not _truthy(None) and not _truthy("N") and not _truthy(False)
