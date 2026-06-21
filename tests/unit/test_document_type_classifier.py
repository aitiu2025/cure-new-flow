"""Unit tests for document_type_classifier.

Validates the title-page / body-keyword / grantee-hint priority chain
and confirms canonical-type mapping. Built from Broward ANAND v2
patterns (2026-05-22) where the recorder's ``document_type`` column
holds a grantee name rather than the real legal doc type.
"""
from titlepro.verification.document_type_classifier import (
    DocumentTypeClassification,
    classify_document_type,
    classify_all_documents,
)


# ---------------------------------------------------------------------------
# Title-page scan tests
# ---------------------------------------------------------------------------


def test_mortgage_title_page():
    text = "THIS MORTGAGE is made this 1st day of January 2015 between..."
    r = classify_document_type("113091903", text)
    assert r.inferred_type == "MORTGAGE"
    assert r.confidence >= 0.9
    assert r.source == "title_page"


def test_satisfaction_title_page():
    text = "SATISFACTION OF MORTGAGE\n\nKNOW ALL MEN BY THESE PRESENTS that..."
    r = classify_document_type("X", text)
    assert r.inferred_type == "SATISFACTION"
    assert r.source == "title_page"
    assert r.confidence >= 0.9


def test_modification_body():
    # No banner in the first chars - body scan must pick MODIFICATION.
    text = "blah blah this MORTGAGE MODIFICATION AGREEMENT is entered into..."
    r = classify_document_type("113649611", text)
    assert r.inferred_type == "MODIFICATION"


def test_quitclaim_variants():
    for variant in ["QUIT-CLAIM DEED", "QUIT CLAIM DEED", "QUITCLAIM DEED"]:
        text = f"{variant}\n\nThis deed made the..."
        r = classify_document_type("X", text)
        assert r.inferred_type == "DEED_QUITCLAIM", (
            f"failed for variant {variant!r}; got {r.inferred_type}"
        )


def test_warranty_deed():
    text = "WARRANTY DEED\n\nKNOW ALL MEN BY THESE PRESENTS..."
    r = classify_document_type("110509369", text)
    assert r.inferred_type == "DEED_WARRANTY"


def test_special_warranty_deed():
    text = "Special Warranty Deed\n\nThis Special Warranty Deed made..."
    r = classify_document_type("110509369", text)
    assert r.inferred_type == "DEED_WARRANTY"


def test_noc():
    text = "NOTICE OF COMMENCEMENT\n\nThe undersigned owner..."
    r = classify_document_type("119437728", text)
    assert r.inferred_type == "NOC"


# ---------------------------------------------------------------------------
# Fallback / negative tests
# ---------------------------------------------------------------------------


def test_fallback_to_grantee_hint():
    """When body has no canonical phrase, infer from grantee hint."""
    text = "blah blah" * 100  # no canonical phrases anywhere
    r = classify_document_type("X", text, grantee_hint="TRUIST BANK")
    assert r.inferred_type == "MORTGAGE"  # bank grantee -> likely mortgage
    assert r.confidence <= 0.5
    assert r.source == "fallback"


def test_other_when_no_signal():
    r = classify_document_type("X", "completely unrelated text",
                               grantee_hint=None)
    assert r.inferred_type == "OTHER"


# ---------------------------------------------------------------------------
# Bulk classification
# ---------------------------------------------------------------------------


def test_bulk_classify():
    docs = [{"document_number": "M1"}, {"document_number": "S1"}]
    texts = {"M1": "THIS MORTGAGE is...",
             "S1": "SATISFACTION OF MORTGAGE..."}
    results = classify_all_documents(docs, texts)
    assert results["M1"].inferred_type == "MORTGAGE"
    assert results["S1"].inferred_type == "SATISFACTION"


# ---------------------------------------------------------------------------
# Edge cases derived from real Broward ANAND data
# ---------------------------------------------------------------------------


def test_release_of_mortgage_banner_beats_mortgage():
    """A 'Release of Mortgage' title-page banner must NOT be classified
    as MORTGAGE just because the word 'MORTGAGE' appears."""
    text = (
        "ORIGINAL DOCUMENT\nRelease of Mortgage\n"
        "KNOW ALL MEN BY THESE PRESENTS that SUNTRUST BANK Mortgagee..."
    )
    r = classify_document_type("112706540", text)
    assert r.inferred_type == "RELEASE"


def test_modification_banner_beats_mortgage():
    """A 'MODIFICATION OF MORTGAGE' banner wins over plain MORTGAGE."""
    text = (
        "This Modification of Mortgage prepared by:\n"
        "MODIFICATION OF MORTGAGE\n"
        "THIS MODIFICATION OF MORTGAGE dated June 16, 2015..."
    )
    r = classify_document_type("113091903", text)
    assert r.inferred_type == "MODIFICATION"


def test_dataclass_to_dict():
    r = DocumentTypeClassification(
        doc_number="X",
        inferred_type="MORTGAGE",
        confidence=0.95,
        evidence="snippet",
        source="title_page",
    )
    d = r.to_dict()
    assert d["doc_number"] == "X"
    assert d["inferred_type"] == "MORTGAGE"
    assert d["confidence"] == 0.95
    assert d["source"] == "title_page"
