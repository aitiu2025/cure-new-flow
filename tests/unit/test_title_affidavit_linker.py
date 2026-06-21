"""Unit tests for title_affidavit_linker.

Validates the identity-disclaimer pairing logic motivated by the RILEY
(Pasco) case: a Title Affidavit recorded at closing disclaims a common-
name judgment debtor and cites the OR Book/Page of the judgment(s) it
disclaims.

Test naming convention mirrors test_not_needed_audit.py (T1-T9).
"""
from __future__ import annotations

import pytest

from titlepro.verification.title_affidavit_linker import (
    TitleAffidavitPairing,
    extract_or_citations,
    is_title_affidavit,
    link_title_affidavits_to_judgments,
)


RILEY_TITLE_AFFIDAVIT_TEXT = """# DOCUMENT: 2012188920.pdf

## Page 1 (ocr)
Recorded 11/05/2012 at 09:14 AM, Pasco County Clerk

TITLE AFFIDAVIT

I, ROBERT S. RILEY, being first duly sworn, depose and say:

1. That I am the same person who took title to the property described
   herein by Warranty Deed of even date.

2. That I am NOT the ROBERT RILEY named as judgment debtor in the
   Final Judgment recorded in OR 8626/1641, Public Records of Pasco
   County, Florida, nor am I the ROBERT RILEY named in the Final
   Judgment recorded in Official Records Book 3850, Page 412.

3. That I affirm and disclaim any identity with the judgment debtor(s)
   referenced above.

FURTHER AFFIANT SAYETH NAUGHT.
"""

SINGLE_CITATION_AFFIDAVIT_TEXT = """# DOCUMENT: 2020111111.pdf

## Page 1 (ocr)
Recorded 03/14/2020 at 11:00 AM, Broward County Commission

AFFIDAVIT OF TITLE

I, JANE DOE, being duly sworn, state that I am not the JANE DOE
named in the judgment recorded in OR 50001/200 of the Public Records
of Broward County, Florida. I affirm and disclaim any identity with
said judgment debtor.
"""

ORPHAN_CITATION_AFFIDAVIT_TEXT = """# DOCUMENT: 2021999999.pdf

## Page 1 (ocr)
Recorded 06/01/2021 at 14:00 PM

TITLE AFFIDAVIT

I, JOHN Q PUBLIC, being duly sworn, depose: I am not the JOHN PUBLIC
named in the Final Judgment recorded at OR 12345/678, nor the one at
Book 99999 Page 1.
"""

BODY_FALLBACK_AFFIDAVIT_TEXT = """# DOCUMENT: 2022555555.pdf

## Page 1 (ocr)
Recorded 09/09/2022

[Title page OCR garbled]

I, JANE Q SAMPLE, being first duly sworn, depose and say I am not
one and the same person as the judgment debtor named in the
Final Judgment recorded at OR 6000/100.
"""

MORTGAGE_TEXT = """# DOCUMENT: 110509370.pdf

## Page 1 (ocr)
CFN # 110509370, Recorded 01/23/2012

MORTGAGE

This MORTGAGE is given to SUNTRUST MORTGAGE, INC.
in the original principal amount of $750,000.00.

(Borrower Affidavit attached as Exhibit B.)
"""


def test_T1_single_affidavit_disclaims_one_judgment_in_documents():
    documents = [
        {"doc_number": "2020111111", "document_type": "TITLE AFFIDAVIT"},
        {"doc_number": "1990123456", "document_type": "FINAL JUDGMENT",
         "book": "50001", "page": "200"},
    ]
    extracted = {
        "2020111111": SINGLE_CITATION_AFFIDAVIT_TEXT,
        "1990123456": "Final Judgment text...",
    }
    pairings = link_title_affidavits_to_judgments(documents, extracted)
    assert len(pairings) == 1
    p = pairings[0]
    assert p.affidavit_doc_number == "2020111111"
    assert p.matched_judgment_doc_numbers == ["1990123456"]
    assert any("50001" in r for r in p.disclaimed_or_book_page_refs)
    assert p.affidavit_recording_date == "2020-03-14"


def test_T2_single_affidavit_disclaims_two_judgments_at_different_refs():
    documents = [
        {"doc_number": "2012188920", "document_type": "TITLE AFFIDAVIT"},
        {"doc_number": "J_RILEY_OLD_1", "document_type": "FINAL JUDGMENT",
         "book": "8626", "page": "1641"},
        {"doc_number": "J_RILEY_OLD_2", "document_type": "FINAL JUDGMENT",
         "or_book_page": "OR 3850/412"},
    ]
    extracted = {"2012188920": RILEY_TITLE_AFFIDAVIT_TEXT}
    pairings = link_title_affidavits_to_judgments(documents, extracted)
    assert len(pairings) == 1
    p = pairings[0]
    assert p.affidavit_doc_number == "2012188920"
    assert set(p.matched_judgment_doc_numbers) == {"J_RILEY_OLD_1", "J_RILEY_OLD_2"}
    assert p.affiant_name is not None
    assert "RILEY" in p.affiant_name.upper()


def test_T3_affidavit_cites_or_refs_that_do_not_match_returns_empty_match():
    documents = [
        {"doc_number": "2021999999", "document_type": "TITLE AFFIDAVIT"},
        {"doc_number": "UNRELATED_J", "document_type": "FINAL JUDGMENT",
         "book": "1", "page": "2"},
    ]
    extracted = {"2021999999": ORPHAN_CITATION_AFFIDAVIT_TEXT}
    pairings = link_title_affidavits_to_judgments(documents, extracted)
    assert len(pairings) == 1
    p = pairings[0]
    assert p.matched_judgment_doc_numbers == []
    assert len(p.disclaimed_or_book_page_refs) >= 1
    assert "but none resolve" in p.rationale or "audit trail" in p.rationale


def test_T4_no_affidavit_in_documents_returns_empty_list():
    documents = [
        {"doc_number": "M1", "document_type": "MORTGAGE"},
        {"doc_number": "D1", "document_type": "WARRANTY DEED"},
    ]
    extracted = {"M1": MORTGAGE_TEXT, "D1": "Warranty Deed text"}
    pairings = link_title_affidavits_to_judgments(documents, extracted)
    assert pairings == []


def test_T5_affidavit_detected_from_title_page_banner():
    doc = {"doc_number": "X", "document_type": "MISC"}
    assert is_title_affidavit(doc, extracted_text=RILEY_TITLE_AFFIDAVIT_TEXT)
    assert is_title_affidavit(doc, extracted_text=SINGLE_CITATION_AFFIDAVIT_TEXT)


def test_T6_affidavit_detected_via_body_keyword_fallback():
    doc = {"doc_number": "Y", "document_type": "AFFIDAVIT"}
    assert is_title_affidavit(doc, extracted_text=BODY_FALLBACK_AFFIDAVIT_TEXT)
    doc_mortgage = {"doc_number": "Z", "document_type": "MORTGAGE"}
    assert not is_title_affidavit(doc_mortgage,
                                  extracted_text=BODY_FALLBACK_AFFIDAVIT_TEXT)


def test_T7_or_book_page_regex_handles_both_format_styles():
    text = (
        "Final Judgment recorded in OR 8626/1641, Public Records of "
        "Pasco County, and the Final Judgment recorded in Official "
        "Records Book 3850, Page 412."
    )
    cites = extract_or_citations(text)
    pairs = {(b, p) for (_v, b, p) in cites}
    assert ("8626", "1641") in pairs
    assert ("3850", "412") in pairs

    text2 = "as recorded in OR BK 8626 Pg 1641."
    cites2 = extract_or_citations(text2)
    assert any(b == "8626" and p == "1641" for (_v, b, p) in cites2)


def test_T8_inferred_types_kwarg_forces_detection_without_text():
    documents = [
        {"doc_number": "AFF_FORCED", "document_type": "MISC"},
        {"doc_number": "J_AT_50001_200", "document_type": "FINAL JUDGMENT",
         "book": "50001", "page": "200"},
    ]
    extracted = {"AFF_FORCED": ""}
    inferred = {"AFF_FORCED": "TITLE_AFFIDAVIT"}
    pairings = link_title_affidavits_to_judgments(
        documents, extracted, inferred_types=inferred
    )
    assert len(pairings) == 1
    assert pairings[0].affidavit_doc_number == "AFF_FORCED"
    assert pairings[0].matched_judgment_doc_numbers == []
    assert pairings[0].disclaimed_or_book_page_refs == []

    documents2 = [{"doc_number": "AFF_TEXT_ONLY", "document_type": "MISC"}]
    extracted2 = {"AFF_TEXT_ONLY": RILEY_TITLE_AFFIDAVIT_TEXT}
    pairings2 = link_title_affidavits_to_judgments(documents2, extracted2)
    assert len(pairings2) == 1


def test_T9_to_dict_serialization_round_trip():
    p = TitleAffidavitPairing(
        affidavit_doc_number="2012188920",
        affidavit_recording_date="2012-11-05",
        disclaimed_or_book_page_refs=["OR 8626/1641", "Book 3850 Page 412"],
        matched_judgment_doc_numbers=["J1", "J2"],
        affiant_name="ROBERT S. RILEY",
        rationale="Test rationale.",
    )
    d = p.to_dict()
    assert d["affidavit_doc_number"] == "2012188920"
    assert d["affidavit_recording_date"] == "2012-11-05"
    assert d["disclaimed_or_book_page_refs"] == ["OR 8626/1641", "Book 3850 Page 412"]
    assert d["matched_judgment_doc_numbers"] == ["J1", "J2"]
    assert d["affiant_name"] == "ROBERT S. RILEY"
    import json
    json.dumps(d)
