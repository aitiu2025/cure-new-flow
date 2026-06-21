"""Unit tests for not_needed_audit.

Validates that the audit module correctly recovers the two satisfactions
silently dropped by Broward's search-index F9 bug:

* 111293535 - SunTrust satisfaction -> mortgage 110509370 (Book/Page)
* 116593405 - TD Bank satisfaction -> mortgage 111249687 (MERS MIN)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from titlepro.verification.not_needed_audit import (
    BOOK_PAGE_RE,
    DOC_NUM_RE,
    LEDGER_TYPES,
    MIN_RE,
    PRINCIPAL_RE,
    RECOVERABLE_TYPES,
    MissingMortgageMetadata,
    MortgageMetadata,
    _classify_with_audit,
    _extract_mortgage_metadata,
    _strip_banner,
    audit_not_needed,
)
from titlepro.verification.released_mortgage_linker import classify_mortgages


SUNTRUST_SATISFACTION_TEXT = """# DOCUMENT: 111293535.pdf

## Page 1 (ocr)
CFN # 111293535, OR BK 49468 Page 396, Page 1 of 1, Recorded 02/01/2013 at
07:28 AM, Broward County Commission, Deputy Clerk ERECORD

Loan #: 0273164574

When Recorded Return To:
SunTrust Mortgage, Inc.

SATISFACTION OF MORTGAGE

KNOW ALL MEN BY THESE PRESENTS: That MORTGAGE ELECTRONIC REGISTRATION
SYSTEMS, INC., AS NOMINEE FOR SUNTRUST MORTGAGE, INC, is the owner and holder of a certain
Mortgage Deed executed by RISHI G. ANAND AND PAYAL M. ANAND recorded in Official Records Book
48462, Page 1412 or Document # 110509370, in the office of the Clerk of the Circuit Court of BROWARD
County, Florida, upon the property situated in said State and County as more fully described in said Mortgage.
"""

TD_BANK_SATISFACTION_TEXT = """# DOCUMENT: 116593405.pdf

## Page 1 (ocr)
Instr# 116593405 , Page 1 of 2, Recorded 07/07/2020 at 10:27 AM
Broward County Commission

Return To:
LIEN SOLUTIONS

MERS SIS # 888-679-6377 MIN: 100341850025078449

This document was prepared by
TD BANK N.A.-COLL DEPT. RP 143

SATISFACTION OF MORTGAGE

THIS DOCUMENT is signed by Mortgage Electronic Registration Systems, Inc., as nominee for TD
Bank, N.A., its successors and assigns, who is the owner and holder of a Mortgage dated
01/04/2013, from RISHI G ANAND AND PAYAL ANAND to Mortgage Electronic Registration Systems,
Inc., as nominee for TD Bank, N.A., securing that certain promissory note in the original
principal amount of $1,519,500.00 , which Mortgage is recorded in Official Records: Book: OR
49410 Page: 211 , Parcel ID Number:494225-04-0800, Public Records of Broward County, Florida.
"""

SUNTRUST_MORTGAGE_TEXT = """# DOCUMENT: 110509370.pdf

## Page 1 (ocr)
CFN # 110509370, OR BK 48462 Page 1412, Page 1 of 15, Recorded 01/23/2012 at
12:45 PM, Broward County Commission, Doc M: $5250.00 Int. Tax $3000.00
Deputy Clerk 3305

MORTGAGE

This MORTGAGE is given to SUNTRUST MORTGAGE, INC.
in the original principal amount of $750,000.00
"""

TD_BANK_MORTGAGE_TEXT = """# DOCUMENT: 111249687.pdf

## Page 1 (ocr)
CFN # 111249687, OR BK 49410 Page 211, Page 1 of 17, Recorded 01/11/2013 at
09:33 AM, Broward County Commission, Doc M: $5318.25 Int. Tax $3039.00
Deputy Clerk 3505

Return To:
TD Bank N.A.

MORTGAGE

MIN 100341850025078449

(D) "Lender" is TD Bank, N.A.
securing that certain promissory note in the original principal amount of
$1,519,500.00
"""

HELOC_MORTGAGE_TEXT = """# DOCUMENT: 112725704.pdf

## Page 1 (ocr)
CFN # 112725704, OR BK 49600 Page 100, Page 1 of 5, Recorded 04/15/2014 at
10:00 AM, Broward County Commission, Deputy Clerk 1234

HOME EQUITY LINE OF CREDIT
"""

SUBORDINATION_TEXT = """# DOCUMENT: 113649611.pdf

## Page 1 (ocr)
CFN # 113649611, OR BK 49800 Page 50, Page 1 of 3, Recorded 06/01/2015 at
11:00 AM, Broward County Commission, Deputy Clerk 5678

SUBORDINATION AGREEMENT

This Subordination Agreement is given in favor of the holder of the
Mortgage recorded in Book 49600 Page 100.
"""


def test_T1_recoverable_types_constants():
    assert RECOVERABLE_TYPES == {"SATISFACTION", "RELEASE", "DISCHARGE", "MODIFICATION"}
    assert "SUBORDINATION" in LEDGER_TYPES
    assert "ASSIGNMENT" in LEDGER_TYPES
    assert LEDGER_TYPES.issuperset(RECOVERABLE_TYPES)


def test_T2_book_page_regex_variants():
    samples = [
        ("OR BK 48462 Page 1412", ("48462", "1412")),
        ("Book: OR 49410 Page: 211", ("49410", "211")),
        ("Book 48462, Page 1412", ("48462", "1412")),
        ("Bk 49468 Pg 396", ("49468", "396")),
    ]
    for s, expected in samples:
        m = BOOK_PAGE_RE.search(s)
        assert m, f"Should match: {s!r}"
        assert m.groups() == expected


def test_T3_min_regex():
    assert MIN_RE.search("MIN: 100341850025078449").group(1) == "100341850025078449"
    assert MIN_RE.search("MIN 100341850025078449").group(1) == "100341850025078449"
    assert MIN_RE.search("MIN #100341850025078449").group(1) == "100341850025078449"
    assert MIN_RE.search("MIN: 12345678") is None


def test_T4_doc_num_regex():
    assert DOC_NUM_RE.search("Document # 110509370").group(1) == "110509370"
    assert DOC_NUM_RE.search("Instr# 116593405").group(1) == "116593405"
    assert DOC_NUM_RE.search("CFN # 110509369").group(1) == "110509369"
    assert DOC_NUM_RE.search("CFN 111293535").group(1) == "111293535"


def test_T5_principal_regex_anchored():
    m = PRINCIPAL_RE.search(
        "in the original principal amount of $1,519,500.00, which Mortgage"
    )
    assert m
    assert m.group(1) == "1,519,500.00"
    assert PRINCIPAL_RE.search("notary fee $20.00") is None


def test_T6_strip_banner_removes_recorder_header():
    stripped = _strip_banner(SUNTRUST_SATISFACTION_TEXT)
    assert "49468" not in stripped[:80]
    assert "48462" in stripped


def test_T7_suntrust_banner_skip_selects_mortgage_slot():
    all_hits = [
        (m.group(1), m.group(2))
        for m in BOOK_PAGE_RE.finditer(SUNTRUST_SATISFACTION_TEXT)
    ]
    assert ("49468", "396") in all_hits
    assert ("48462", "1412") in all_hits

    stripped = _strip_banner(SUNTRUST_SATISFACTION_TEXT)
    body_hits = [
        (m.group(1), m.group(2)) for m in BOOK_PAGE_RE.finditer(stripped)
    ]
    assert body_hits
    assert body_hits[0] == ("48462", "1412")


def test_T8_extract_mortgage_metadata():
    docs = [
        {"doc_number": "110509370"},
        {"doc_number": "111249687"},
    ]
    extracted = {
        "110509370": SUNTRUST_MORTGAGE_TEXT,
        "111249687": TD_BANK_MORTGAGE_TEXT,
    }
    metas = _extract_mortgage_metadata(docs, extracted)
    suntrust = metas["110509370"]
    assert suntrust.book == "48462"
    assert suntrust.page == "1412"
    td = metas["111249687"]
    assert td.book == "49410"
    assert td.page == "211"
    assert td.min_number == "100341850025078449"
    assert td.original_principal == "1519500.00"


def test_T9_book_page_regex_matches_both_satisfaction_variants():
    su_stripped = _strip_banner(SUNTRUST_SATISFACTION_TEXT)
    su = BOOK_PAGE_RE.search(su_stripped)
    assert su is not None
    assert su.groups() == ("48462", "1412")

    td_stripped = _strip_banner(TD_BANK_SATISFACTION_TEXT)
    td = BOOK_PAGE_RE.search(td_stripped)
    assert td is not None
    assert td.groups() == ("49410", "211")


def test_T10_classify_with_audit_picks_satisfaction():
    canonical, conf, _ev = _classify_with_audit(
        "111293535", SUNTRUST_SATISFACTION_TEXT
    )
    assert canonical == "SATISFACTION"
    assert conf >= 0.9


def test_T11_td_bank_min_match(tmp_path):
    """T11 (critical): TD Bank satisfaction recovers to mortgage 111249687.
    The text contains Book/Page (49410/211) and MIN (100341850025078449) —
    Book/Page is more specific so wins. To prove MIN works alone, we run
    with mortgage metadata that ONLY has MIN populated.
    """
    case_dir = tmp_path / "case"
    nn_dir = case_dir / "not_needed"
    nn_dir.mkdir(parents=True)
    (nn_dir / "116593405_extracted.md").write_text(
        TD_BANK_SATISFACTION_TEXT, encoding="utf-8"
    )

    # Full metadata: Book/Page wins (more specific).
    docs = [{"doc_number": "111249687"}]
    texts = {"111249687": TD_BANK_MORTGAGE_TEXT}
    known = _extract_mortgage_metadata(docs, texts)

    result = audit_not_needed(case_dir, known)
    assert len(result.recovered) == 1
    rec = result.recovered[0]
    assert rec.doc_number == "116593405"
    assert rec.target_mortgage_doc == "111249687"
    assert rec.match_method in ("book_page", "min", "doc_number"), (
        f"Expected one of book_page/min/doc_number, got {rec.match_method}"
    )
    assert rec.classified_type == "SATISFACTION"

    # MIN-only metadata: only MIN should match.
    known_min_only = {
        "111249687": MortgageMetadata(
            doc_number="111249687",
            min_number="100341850025078449",
        ),
    }
    result_min = audit_not_needed(case_dir, known_min_only)
    assert len(result_min.recovered) == 1
    assert result_min.recovered[0].match_method == "min", (
        f"With MIN-only metadata, expected method=min, got "
        f"{result_min.recovered[0].match_method}"
    )


def test_T12_full_audit_returns_both_satisfactions(tmp_path):
    case_dir = tmp_path / "ANAND_v2"
    nn_dir = case_dir / "not_needed"
    nn_dir.mkdir(parents=True)

    (nn_dir / "111293535_extracted.md").write_text(
        SUNTRUST_SATISFACTION_TEXT, encoding="utf-8"
    )
    (nn_dir / "116593405_extracted.md").write_text(
        TD_BANK_SATISFACTION_TEXT, encoding="utf-8"
    )
    (nn_dir / "113649611_extracted.md").write_text(
        SUBORDINATION_TEXT, encoding="utf-8"
    )

    docs = [
        {"doc_number": "110509370"},
        {"doc_number": "111249687"},
        {"doc_number": "112725704"},
    ]
    texts = {
        "110509370": SUNTRUST_MORTGAGE_TEXT,
        "111249687": TD_BANK_MORTGAGE_TEXT,
        "112725704": HELOC_MORTGAGE_TEXT,
    }
    known = _extract_mortgage_metadata(docs, texts)

    result = audit_not_needed(case_dir, known)
    by_doc = {r.doc_number: r for r in result.recovered}
    assert "111293535" in by_doc
    assert by_doc["111293535"].target_mortgage_doc == "110509370"
    # Match method depends on which cross-ref appears first in priority
    # order: doc_number > book_page > min > principal. SunTrust text
    # cites "Document # 110509370" so doc_number wins.
    assert by_doc["111293535"].match_method in ("doc_number", "book_page"), (
        f"Got {by_doc['111293535'].match_method}"
    )
    assert by_doc["111293535"].classified_type == "SATISFACTION"

    assert "116593405" in by_doc
    assert by_doc["116593405"].target_mortgage_doc == "111249687"
    # TD Bank text has no explicit Document # for the mortgage, so
    # Book/Page wins (more specific than MIN).
    assert by_doc["116593405"].match_method in ("book_page", "min"), (
        f"Got {by_doc['116593405'].match_method}"
    )
    assert by_doc["116593405"].classified_type == "SATISFACTION"

    assert "113649611" not in by_doc
    ledger_by_doc = {e.doc_number: e for e in result.ledger}
    assert "113649611" in ledger_by_doc
    assert ledger_by_doc["113649611"].disposition == "skipped_subordination"


def test_T13_missing_metadata_raises():
    with pytest.raises(MissingMortgageMetadata):
        audit_not_needed(Path("/tmp/non_existent_xyz_case"), {})

    bare = {"110509370": MortgageMetadata(doc_number="110509370")}
    with pytest.raises(MissingMortgageMetadata):
        audit_not_needed(Path("/tmp/non_existent_xyz_case"), bare)


def test_T14_e2e_full_flow_via_classify_mortgages(tmp_path):
    case_dir = tmp_path / "ANAND_v2_e2e"
    nn_dir = case_dir / "not_needed"
    nn_dir.mkdir(parents=True)
    (nn_dir / "111293535_extracted.md").write_text(
        SUNTRUST_SATISFACTION_TEXT, encoding="utf-8"
    )
    (nn_dir / "116593405_extracted.md").write_text(
        TD_BANK_SATISFACTION_TEXT, encoding="utf-8"
    )

    documents = [
        {"doc_number": "110509370", "document_type": "MORTGAGE"},
        {"doc_number": "111249687", "document_type": "MORTGAGE"},
    ]
    extracted_texts = {
        "110509370": SUNTRUST_MORTGAGE_TEXT,
        "111249687": TD_BANK_MORTGAGE_TEXT,
    }

    known = _extract_mortgage_metadata(documents, extracted_texts)
    audit_result = audit_not_needed(case_dir, known)
    assert len(audit_result.recovered) == 2

    inferred_types = {
        "110509370": "MORTGAGE",
        "111249687": "MORTGAGE",
    }
    classifications = classify_mortgages(
        documents,
        extracted_texts,
        inferred_types=inferred_types,
        recovered_docs=audit_result.recovered,
    )

    assert "110509370" in classifications
    suntrust = classifications["110509370"]
    assert suntrust.status == "released", (
        f"SunTrust mortgage 110509370 status: {suntrust.status}"
    )
    assert len(suntrust.release_chain) >= 1
    assert suntrust.release_chain[0].satisfaction_doc_number == "111293535"

    assert "111249687" in classifications
    td = classifications["111249687"]
    assert td.status == "released", (
        f"TD Bank mortgage 111249687 status: {td.status}"
    )
    assert len(td.release_chain) >= 1
    assert td.release_chain[0].satisfaction_doc_number == "116593405"
