"""Unit tests for released_mortgage_linker.

Golden fixtures derived from Tony Roveda's Broward Test Review
(2026-05-21) - specifically the ANAND released-mortgage gap where
`111249687`, `112424642`, `110509371` were satisfied but appeared
in the report as still open.
"""
from titlepro.verification.released_mortgage_linker import (
    ReleaseLink,
    MortgageClassification,
    classify_mortgages,
    is_mortgage,
    satisfaction_kind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(num: str, doc_type: str, **extras) -> dict:
    base = {"doc_number": num, "document_type": doc_type}
    base.update(extras)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_anand_released_mortgage_linked():
    """Case 1: ANAND released mortgage 111249687 - satisfaction references it."""
    documents = [
        _doc("111249687", "MORTGAGE"),
        _doc("999000111", "SATISFACTION OF MORTGAGE"),
    ]
    extracted_texts = {
        "999000111": (
            "This Satisfaction of Mortgage hereby satisfies Mortgage "
            "recorded as Instrument 111249687 in the Official Records of "
            "Broward County, Florida."
        ),
    }
    result = classify_mortgages(documents, extracted_texts)
    assert "111249687" in result
    mc = result["111249687"]
    assert mc.status == "released"
    assert len(mc.release_chain) == 1
    link = mc.release_chain[0]
    assert link.mortgage_doc_number == "111249687"
    assert link.satisfaction_doc_number == "999000111"
    assert link.satisfaction_type == "satisfaction"
    assert "111249687" in link.evidence_text


def test_open_mortgage_no_satisfaction():
    """Case 2: a mortgage with no matching satisfaction is `open`."""
    documents = [
        _doc("120857331", "MORTGAGE"),
        _doc("999000222", "SATISFACTION OF MORTGAGE"),
    ]
    # Satisfaction text references some OTHER mortgage, not 120857331.
    extracted_texts = {
        "999000222": "Satisfies Mortgage Instrument 100000000 of record.",
    }
    result = classify_mortgages(documents, extracted_texts)
    assert result["120857331"].status == "open"
    assert result["120857331"].release_chain == []


def test_modification_chain():
    """Case 3: modification of 113649611 -> mortgage classified as `modified`."""
    documents = [
        _doc("113649611", "MORTGAGE"),
        _doc("120826721", "MODIFICATION OF MORTGAGE"),
    ]
    extracted_texts = {
        "120826721": (
            "This Modification modifies Instrument 113649611 originally "
            "recorded in the public records of Broward County, FL."
        ),
    }
    result = classify_mortgages(documents, extracted_texts)
    mc = result["113649611"]
    assert mc.status == "modified"
    assert "120826721" in mc.related_modifications
    # Released takes priority over modified; status here must NOT be released.
    assert mc.release_chain == []


def test_false_positive_avoidance():
    """Case 4: an 8-digit number in the satisfaction text that ISN'T a mortgage.

    For example, a property address line like '21518765 Some Address' could
    contain an 8-digit run. As long as that number is NOT in the mortgage
    set, no link should be produced.
    """
    documents = [
        _doc("120857331", "MORTGAGE"),
        _doc("999000333", "SATISFACTION OF MORTGAGE"),
    ]
    extracted_texts = {
        # The number 21518765 looks like an instrument # but is not in the
        # mortgage list -> linker must NOT produce a false-positive link.
        "999000333": (
            "Property address line 21518765 Some Street, City, FL. "
            "Satisfies Mortgage Instrument 100000000."
        ),
    }
    result = classify_mortgages(documents, extracted_texts)
    mc = result["120857331"]
    assert mc.status == "open", (
        f"Expected open (no false positive), got {mc.status} with chain "
        f"{[(l.mortgage_doc_number, l.evidence_text) for l in mc.release_chain]}"
    )
    assert mc.release_chain == []


def test_multi_instrument_cross_reference():
    """Case 5: one satisfaction references three mortgages - all three released.

    Mirrors the real ANAND finding: 111249687, 112424642, 110509371 all
    appeared in a consolidated satisfaction-of-mortgage document.
    """
    documents = [
        _doc("111249687", "MORTGAGE"),
        _doc("112424642", "MORTGAGE"),
        _doc("110509371", "MORTGAGE"),
        _doc("999000444", "SATISFACTION OF MORTGAGE"),
    ]
    extracted_texts = {
        "999000444": (
            "This consolidated Satisfaction of Mortgage hereby releases "
            "the following instruments recorded in Broward County, FL: "
            "Instrument 111249687, Instrument 112424642, and "
            "Instrument 110509371. All obligations are hereby discharged."
        ),
    }
    result = classify_mortgages(documents, extracted_texts)
    for num in ("111249687", "112424642", "110509371"):
        assert num in result, f"Missing classification for {num}"
        mc = result[num]
        assert mc.status == "released", (
            f"Mortgage {num} should be released; got {mc.status}"
        )
        assert len(mc.release_chain) == 1
        assert mc.release_chain[0].satisfaction_doc_number == "999000444"


# ---------------------------------------------------------------------------
# Helper-function smoke tests
# ---------------------------------------------------------------------------


def test_is_mortgage_filters_non_mortgages():
    assert is_mortgage(_doc("1", "MORTGAGE")) is True
    assert is_mortgage(_doc("2", "MTG")) is True
    assert is_mortgage(_doc("3", "SATISFACTION OF MORTGAGE")) is False
    assert is_mortgage(_doc("4", "RELEASE OF MORTGAGE")) is False
    assert is_mortgage(_doc("5", "ASSIGNMENT OF MORTGAGE")) is False
    assert is_mortgage(_doc("6", "MODIFICATION OF MORTGAGE")) is False
    assert is_mortgage(_doc("7", "DEED")) is False


def test_satisfaction_kind_detects_all_three_variants():
    assert satisfaction_kind(_doc("1", "SATISFACTION OF MORTGAGE")) == "satisfaction"
    assert satisfaction_kind(_doc("2", "RELEASE OF MORTGAGE")) == "release"
    assert satisfaction_kind(_doc("3", "DISCHARGE OF MORTGAGE")) == "discharge"
    assert satisfaction_kind(_doc("4", "MORTGAGE")) is None


def test_release_link_to_dict_serializable():
    link = ReleaseLink(
        mortgage_doc_number="111249687",
        satisfaction_doc_number="999000111",
        satisfaction_type="satisfaction",
        evidence_text="snippet",
    )
    d = link.to_dict()
    assert d["mortgage_doc_number"] == "111249687"
    assert d["satisfaction_type"] == "satisfaction"


def test_mortgage_classification_to_dict():
    mc = MortgageClassification(doc_number="X", status="open")
    d = mc.to_dict()
    assert d == {
        "doc_number": "X",
        "status": "open",
        "release_chain": [],
        "related_modifications": [],
    }


# ---------------------------------------------------------------------------
# Integration with document_type_classifier (inferred_types path)
# ---------------------------------------------------------------------------


def test_classify_with_inferred_types():
    """When inferred_types is provided, classify_mortgages should use it
    instead of the (unreliable) document_type field.

    Mirrors the Broward ANAND failure mode: the search-results
    document_type column holds a grantee name ('TRUIST BANK') or a
    placeholder ('From'), so the raw `is_mortgage` predicate returns
    False for every record. With inferred_types from
    `document_type_classifier`, the linker should correctly identify
    mortgages and link satisfactions to them.
    """
    docs = [
        _doc("112424642", "TRUIST BANK"),  # actually a mortgage
        _doc("112706540", "From"),         # actually a satisfaction
    ]
    extracted_texts = {
        "112424642": "blah",
        "112706540": "This Satisfaction of Mortgage satisfies Mortgage "
                     "recorded as Instrument 112424642 in the Official "
                     "Records of Broward County, FL.",
    }
    # Without inferred_types the linker can't tell 112424642 is a mortgage
    # (its document_type is 'TRUIST BANK', not 'MORTGAGE').
    raw = classify_mortgages(docs, extracted_texts)
    assert "112424642" not in raw  # baseline Broward bug confirmed

    # With inferred_types we should now classify it as a released mortgage.
    inferred = {"112424642": "MORTGAGE", "112706540": "SATISFACTION"}
    classifications = classify_mortgages(
        docs, extracted_texts, inferred_types=inferred
    )
    assert "112424642" in classifications
    mc = classifications["112424642"]
    assert mc.status == "released"
    assert len(mc.release_chain) == 1
    assert mc.release_chain[0].satisfaction_doc_number == "112706540"
    assert mc.release_chain[0].satisfaction_type == "satisfaction"
