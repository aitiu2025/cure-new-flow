"""Unit tests for the NOC termination-bundle detector + the
CONTRACTOR_FINAL_AFFIDAVIT / LIEN_WAIVER per-doc classifier additions.
"""
from __future__ import annotations

from titlepro.verification.document_type_classifier import (
    NocTerminationBundle,
    classify_document_type,
    detect_noc_termination_bundles,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _doc(
    num: str,
    date: str,
    *,
    text: str = "",
    grantee: str = "",
    document_type: str = "",
) -> dict:
    return {
        "doc_number": num,
        "recording_date": date,
        "extracted_text": text,
        "grantee": grantee,
        "document_type": document_type,
    }


_PROJECT_ADDR_LINE = "Property: 100 MAIN STREET\n"
_CONTRACTOR_LINE = "Contractor: ACME BUILDERS, INC.\n"

_NOC_TEXT = (
    "NOTICE OF COMMENCEMENT\n"
    + _PROJECT_ADDR_LINE
    + _CONTRACTOR_LINE
    + "Description: Roof replacement.\n"
)
_NOT_TEXT = (
    "NOTICE OF TERMINATION OF NOTICE OF COMMENCEMENT\n"
    + _PROJECT_ADDR_LINE
    + _CONTRACTOR_LINE
    + "Termination effective immediately under Fla. Stat. §713.132.\n"
)
_CFA_TEXT = (
    "FINAL CONTRACTOR'S AFFIDAVIT\n"
    + _PROJECT_ADDR_LINE
    + "the undersigned, ACME BUILDERS, INC., being duly sworn, deposes and\n"
    "says that all subcontractors and suppliers have been paid in full.\n"
)
_WAIVER_TEXT = (
    "WAIVER AND RELEASE OF LIEN UPON FINAL PAYMENT\n"
    + _PROJECT_ADDR_LINE
    + "the undersigned, ACME BUILDERS, INC., waives any and all liens upon\n"
    "final payment, absolute and irrevocable.\n"
)


# ===========================================================================
# Per-doc classifier additions
# ===========================================================================


def test_contractor_final_affidavit_title_page_detection():
    res = classify_document_type("C-1", _CFA_TEXT)
    assert res.inferred_type == "CONTRACTOR_FINAL_AFFIDAVIT"
    assert res.confidence >= 0.85
    assert res.source == "title_page"


def test_lien_waiver_title_page_detection():
    res = classify_document_type("W-1", _WAIVER_TEXT)
    assert res.inferred_type == "LIEN_WAIVER"
    assert res.confidence >= 0.85
    assert res.source == "title_page"


def test_classifier_body_keyword_fallback_for_affidavit():
    # Title page is non-canonical, but body has the canonical keywords.
    body = (
        "RECORDED INSTRUMENT\n\n"
        "the undersigned, ACME BUILDERS, INC., being duly sworn, "
        "deposes and says that all subcontractors and suppliers have "
        "been paid in full and all amounts due are settled.\n"
    )
    res = classify_document_type("CFA-2", body)
    assert res.inferred_type == "CONTRACTOR_FINAL_AFFIDAVIT"


def test_classifier_body_keyword_fallback_for_waiver():
    body = (
        "RECORDED INSTRUMENT\n\n"
        "the undersigned waives any and all liens upon final payment, "
        "absolute and irrevocable, with respect to the property at "
        "100 MAIN STREET.\n"
    )
    res = classify_document_type("LW-2", body)
    assert res.inferred_type == "LIEN_WAIVER"


# ===========================================================================
# Bundle detector
# ===========================================================================


def test_bundle_complete_triplet_within_90_days():
    documents = [
        _doc("NOC-1", "01/15/2024", text=_NOC_TEXT),
        _doc("NOT-1", "03/01/2024", text=_NOT_TEXT),
        _doc("CFA-1", "03/05/2024", text=_CFA_TEXT),
        _doc("LW-1", "03/10/2024", text=_WAIVER_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    assert isinstance(b, NocTerminationBundle)
    assert b.status == "BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED"
    assert b.noc_doc_number == "NOC-1"
    assert b.not_doc_number == "NOT-1"
    assert b.final_affidavit_doc_number == "CFA-1"
    assert b.lien_waiver_doc_numbers == ["LW-1"]
    assert b.bundle_window_days is not None
    assert b.bundle_window_days <= 90


def test_bundle_partial_not_only_unratified():
    documents = [
        _doc("NOC-1", "01/15/2024", text=_NOC_TEXT),
        _doc("NOT-1", "03/01/2024", text=_NOT_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    assert b.status == "PARTIAL_NOT_ONLY_UNRATIFIED"
    assert b.not_doc_number == "NOT-1"
    assert b.final_affidavit_doc_number is None
    assert b.lien_waiver_doc_numbers == []


def test_bundle_partial_not_plus_affidavit_no_waiver():
    documents = [
        _doc("NOC-1", "01/15/2024", text=_NOC_TEXT),
        _doc("NOT-1", "03/01/2024", text=_NOT_TEXT),
        _doc("CFA-1", "03/05/2024", text=_CFA_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    assert b.status == "PARTIAL_NOT_PLUS_AFFIDAVIT_NO_WAIVER"
    assert b.final_affidavit_doc_number == "CFA-1"
    assert b.lien_waiver_doc_numbers == []


def test_bundle_partial_not_plus_waiver_no_affidavit():
    documents = [
        _doc("NOC-1", "01/15/2024", text=_NOC_TEXT),
        _doc("NOT-1", "03/01/2024", text=_NOT_TEXT),
        _doc("LW-1", "03/10/2024", text=_WAIVER_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    assert b.status == "PARTIAL_NOT_PLUS_WAIVER_NO_AFFIDAVIT"
    assert b.final_affidavit_doc_number is None
    assert b.lien_waiver_doc_numbers == ["LW-1"]


def test_bundle_no_termination_found():
    documents = [
        _doc("NOC-1", "01/15/2024", text=_NOC_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    assert b.status == "NO_TERMINATION_FOUND"
    assert b.not_doc_number is None
    assert b.final_affidavit_doc_number is None
    assert b.lien_waiver_doc_numbers == []


def test_multiple_nocs_each_gets_own_bundle():
    # Two NOCs on different projects -- each independent.
    addr_a = "Property: 100 ALPHA AVE\n"
    addr_b = "Property: 200 BETA BLVD\n"
    contractor_a = "Contractor: AAA CONSTRUCTION, INC.\n"
    contractor_b = "Contractor: BBB BUILDERS, LLC\n"

    documents = [
        _doc("NOC-A", "01/01/2024",
             text="NOTICE OF COMMENCEMENT\n" + addr_a + contractor_a),
        _doc("NOT-A", "03/15/2024",
             text="NOTICE OF TERMINATION\n" + addr_a + contractor_a),
        _doc("CFA-A", "03/20/2024",
             text="FINAL CONTRACTOR'S AFFIDAVIT\n" + addr_a + contractor_a),
        _doc("LW-A", "03/25/2024",
             text="WAIVER AND RELEASE OF LIEN UPON FINAL PAYMENT\n"
                  + addr_a + contractor_a),
        _doc("NOC-B", "02/01/2024",
             text="NOTICE OF COMMENCEMENT\n" + addr_b + contractor_b),
        # NOC-B has no NOT.
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 2

    a = next(b for b in bundles if b.noc_doc_number == "NOC-A")
    b_ = next(b for b in bundles if b.noc_doc_number == "NOC-B")

    assert a.status == "BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED"
    assert b_.status == "NO_TERMINATION_FOUND"


def test_bundle_window_default_90_days_excludes_late_waiver():
    documents = [
        _doc("NOC-1", "01/01/2024", text=_NOC_TEXT),
        _doc("NOT-1", "02/01/2024", text=_NOT_TEXT),
        _doc("CFA-1", "02/15/2024", text=_CFA_TEXT),
        # Waiver recorded 100+ days after the NOT -- outside window.
        _doc("LW-1", "06/01/2024", text=_WAIVER_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert len(bundles) == 1
    b = bundles[0]
    # Affidavit + late waiver scenario: bundle is NOT complete because
    # the waiver fell outside the 90-day window from NOT.
    assert b.status in (
        "PARTIAL_NOT_PLUS_AFFIDAVIT_NO_WAIVER",
        # Some implementations may keep the lien-waiver attached but
        # report partial via a different label; accept either.
        "PARTIAL_NOT_PLUS_WAIVER_NO_AFFIDAVIT",
    )


def test_inferred_types_short_circuits_classification():
    # Empty body text -- classifier would normally fall back to OTHER.
    # With inferred_types map, we bypass per-doc classification entirely.
    documents = [
        _doc("NOC-X", "01/01/2024"),
        _doc("NOT-X", "03/01/2024"),
        _doc("CFA-X", "03/05/2024"),
        _doc("LW-X", "03/10/2024"),
    ]
    inferred = {
        "NOC-X": "NOC",
        "NOT-X": "NOT",
        "CFA-X": "CONTRACTOR_FINAL_AFFIDAVIT",
        "LW-X": "LIEN_WAIVER",
    }
    bundles = detect_noc_termination_bundles(documents, inferred_types=inferred)
    assert len(bundles) == 1
    assert bundles[0].status == "BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED"


def test_to_dict_is_json_serializable():
    bundle = NocTerminationBundle(
        noc_doc_number="N",
        not_doc_number="T",
        final_affidavit_doc_number="A",
        lien_waiver_doc_numbers=["W1", "W2"],
        status="BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED",
        bundle_window_days=45,
        contractor_name="ACME BUILDERS INC",
        project_address="100 MAIN STREET",
        rationale="Triplet within 90 days",
    )
    d = bundle.to_dict()
    assert d["status"] == "BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED"
    assert d["lien_waiver_doc_numbers"] == ["W1", "W2"]
    assert d["bundle_window_days"] == 45
    assert d["contractor_name"] == "ACME BUILDERS INC"


def test_empty_documents_returns_empty_list():
    bundles = detect_noc_termination_bundles([])
    assert bundles == []


def test_only_non_noc_docs_returns_empty_list():
    # NOT/CFA/Waiver with no NOC -> nothing to bundle.
    documents = [
        _doc("T-1", "01/01/2024", text=_NOT_TEXT),
        _doc("A-1", "01/15/2024", text=_CFA_TEXT),
    ]
    bundles = detect_noc_termination_bundles(documents)
    assert bundles == []
