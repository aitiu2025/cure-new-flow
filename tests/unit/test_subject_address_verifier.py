"""Unit tests for subject_address_verifier.

Golden fixtures derived from Tony Roveda's Broward Test Review
(2026-05-21), specifically the SIMMONS wrong-property finding.

2026-05-22: added tests for extract_subject_address_from_text(),
motivated by the 0522 ANAND failure where the naive first-match
regex picked the lender's Orlando office over the subject Fort
Lauderdale property.
"""
from titlepro.verification.subject_address_verifier import (
    AddressMatchResult,
    verify_subject_address,
    verify_with_lender_hq_rescue,
    parse_address,
    extract_subject_address_from_text,
)


SUBJECT_SIMMONS = "2151 NW 93rd Ave, Pembroke Pines, FL"


def test_identical_addresses_match():
    """Case 1: identical addresses should hit MATCH with similarity >= 0.95."""
    result = verify_subject_address(SUBJECT_SIMMONS, SUBJECT_SIMMONS)
    assert isinstance(result, AddressMatchResult)
    assert result.status == "MATCH"
    assert result.similarity >= 0.95
    assert result.matched_components["street_number"] is True
    assert result.matched_components["city"] is True


def test_simmons_wrong_property_no_match():
    """Case 2: the actual SIMMONS bug - 6830 Falconsgate Davie vs 2151 NW 93rd Pembroke Pines.

    This is the critical regression test. The two addresses share neither
    street number, street name, NOR city, so similarity must be very low
    and status must be NO_MATCH.
    """
    extracted = "6830 Falconsgate Avenue, Davie, FL"
    result = verify_subject_address(extracted, SUBJECT_SIMMONS)
    assert result.status == "NO_MATCH"
    assert result.similarity < 0.40, (
        f"Expected similarity < 0.40 for SIMMONS wrong-property mismatch, "
        f"got {result.similarity}. Evidence: {result.evidence}"
    )
    # And the matched_components dict should show the structural mismatches.
    assert result.matched_components["street_number"] is False
    assert result.matched_components["city"] is False


def test_abbreviation_tolerance():
    """Case 3: 'Avenue' vs 'Ave', 'Florida' vs 'FL', case differences -> MATCH."""
    extracted = "2151 NW 93rd Avenue, Pembroke Pines, Florida 33024"
    subject = "2151 NW 93rd Ave, PEMBROKE PINES, FL"
    result = verify_subject_address(extracted, subject)
    assert result.status == "MATCH", (
        f"Expected MATCH for abbreviation-only differences; got "
        f"{result.status} (similarity={result.similarity}). "
        f"Evidence: {result.evidence}"
    )
    assert result.similarity >= 0.85


def test_same_building_different_unit_ambiguous():
    """Case 4: same building, different unit numbers.

    Decision: AMBIGUOUS. Rationale: same street_number + street_name +
    city is a strong signal these are the same physical building (think
    condo / apartment complex), but the unit difference means the legal
    parcel may differ. The downstream UI should flag for human review
    rather than auto-accept or auto-reject.
    """
    extracted = "100 Main St #5, Tampa, FL"
    subject = "100 Main St #7, Tampa, FL"
    result = verify_subject_address(extracted, subject)
    assert result.status in {"AMBIGUOUS", "NO_MATCH"}, (
        f"Expected AMBIGUOUS or NO_MATCH for unit-only difference; got "
        f"{result.status}. Evidence: {result.evidence}"
    )
    # Pin to AMBIGUOUS specifically (current implementation caps score at 0.75).
    assert result.status == "AMBIGUOUS"


def test_ocr_noise_tolerance():
    """Case 5: '215l' (lowercase L) instead of '2151' -> AMBIGUOUS or MATCH."""
    extracted = "215l NW 93rd Ave, Pembroke Pines, FL"
    result = verify_subject_address(extracted, SUBJECT_SIMMONS)
    assert result.status in {"MATCH", "AMBIGUOUS"}, (
        f"Expected MATCH or AMBIGUOUS for OCR-noisy street number; got "
        f"{result.status}. Evidence: {result.evidence}"
    )
    # And similarity must be substantially above the no-match floor.
    assert result.similarity >= 0.55


def test_parse_address_components_roundtrip():
    """Sanity: parse_address extracts the expected components."""
    comp = parse_address("2151 NW 93rd Ave, Pembroke Pines, FL 33024")
    assert comp.street_number == "2151"
    assert comp.directional == "NW"
    assert comp.street_type == "AVENUE"
    assert comp.city == "PEMBROKE PINES"
    assert comp.state == "FL"
    assert comp.zip_code == "33024"


def test_evidence_text_is_human_readable():
    """The evidence string should mention the mismatching components."""
    result = verify_subject_address(
        "6830 Falconsgate Avenue, Davie, FL", SUBJECT_SIMMONS
    )
    assert "street_number" in result.evidence
    assert "MISMATCH" in result.evidence


# ---------------------------------------------------------------------------
# extract_subject_address_from_text tests (2026-05-22, ANAND failure mode)
# ---------------------------------------------------------------------------


def test_extract_subject_address_prefers_property_keyword():
    """Real ANAND mortgage text has the lender's Orlando address FIRST, with
    the subject Fort Lauderdale address near the 'currently has the address
    of' preamble. Extractor must pick the latter."""
    text = """
    Loan Number 12345
    Mortgagee: SunTrust Bank
    7455 Chancellor Drive, Orlando, FL 32801
    ...
    BORROWER promises to pay ... Property which currently has the address of
    2856 NE 27TH Street, Fort Lauderdale, FL 33305
    ...
    """
    addr = extract_subject_address_from_text(
        text, subject_hint="2856 NE 27th Street, Fort Lauderdale, FL"
    )
    assert "2856 NE 27TH" in addr.upper()
    assert "Orlando" not in addr


def test_extract_subject_address_anand_120225084_real_text():
    """Replicate the 0522 failure: the regex extracted
    '0800\\nwhich currently has the address of...' for doc 120225084."""
    text = (
        "some intro text 0800\n"
        "which currently has the address of 2856 NE 27TH Street, "
        "FORT LAUDERDALE, FL"
    )
    addr = extract_subject_address_from_text(
        text, subject_hint="2856 NE 27TH ST, FORT LAUDERDALE, FL"
    )
    result = verify_subject_address(addr, "2856 NE 27TH ST, FORT LAUDERDALE, FL")
    assert result.status == "MATCH", (
        f"Expected MATCH after extractor fix, got {result.status} "
        f"(addr={addr!r}, similarity={result.similarity})"
    )


def test_extract_subject_address_penalizes_lender_address():
    """When a lender/return-to address sits near 'After recording return to'
    and the actual subject address is labelled with 'Property:', the latter
    must win."""
    text = (
        "After recording return to: First American Title, "
        "1 Some St, Lender Town, FL\n"
        "\n"
        "Property: 2151 NW 93rd Ave, Pembroke Pines, FL"
    )
    addr = extract_subject_address_from_text(
        text, subject_hint="2151 NW 93rd Ave, Pembroke Pines, FL"
    )
    assert "2151 NW" in addr
    assert "Lender Town" not in addr


def test_extract_subject_address_returns_first_if_no_context():
    """With no context keywords and no hint, the only candidate wins."""
    text = "Some doc with just one address: 100 Main St, Tampa, FL"
    addr = extract_subject_address_from_text(text)
    assert "100 Main" in addr


def test_extract_returns_all_candidates_with_scores():
    """return_all_candidates=True returns (best, list-of-tuples). The top
    candidate must outscore the lender candidate."""
    text = (
        "Lender at 7455 Chancellor Drive, Orlando, FL. "
        "Property which currently has the address of "
        "2856 NE 27TH Street, Fort Lauderdale, FL"
    )
    selected, candidates = extract_subject_address_from_text(
        text, return_all_candidates=True
    )
    assert "2856 NE 27TH" in selected
    assert len(candidates) >= 2
    top = max(candidates, key=lambda c: c[1])
    second = sorted(candidates, key=lambda c: -c[1])[1]
    assert top[1] > second[1], (
        f"Expected top candidate to outscore the runner-up; got "
        f"top={top}, second={second}"
    )


# ---------------------------------------------------------------------------
# F7: Lender-HQ rescue (promoted out of Manatee_FERNANDEZ_v1 glue code)
# ---------------------------------------------------------------------------


SUBJECT_FERNANDEZ = "4837 SABAL HARBOUR DR, BRADENTON, FL"


def test_lender_hq_rescue_fires_when_primary_is_lender_office():
    """The CrossCountry-Brecksville-OH lender HQ in mortgage 202141105578.

    Reproduces the exact F7 failure mode from Manatee_FERNANDEZ_v1:
    upstream extractor returned the lender HQ as the primary; the rescue
    re-scans all candidates and promotes the subject-matching one.
    """
    text = (
        "MORTGAGE for an amount of $290,000 dated August 6, 2021.\n"
        + "6850 Miller Road, Brecksville, OH 44141\n"
        + ("borrower covenants " * 80)
        + " in the County of Manatee, State of Florida, more particularly "
        + "described as: Lot 141 SABAL HARBOUR PHASE V, per plat thereof. "
        + "4837 SABAL HARBOUR DR, BRADENTON, FL 34203 "
        + "(for informational purposes only)."
    )
    rescued, promoted = verify_with_lender_hq_rescue(
        text,
        SUBJECT_FERNANDEZ,
        primary_extracted_address="6850 Miller Road, Brecksville, OH 44141",
    )
    # Rescue must fire because primary was the OH lender HQ.
    assert promoted is not None, (
        f"Expected F7 rescue to fire; promoted=None, rescued={rescued}"
    )
    assert "4837" in promoted
    assert rescued.status == "MATCH"
    assert "F7 lender-HQ rescue" in rescued.evidence


def test_lender_hq_rescue_no_primary_supplied_uses_internal_pass():
    """Backward-compat path: when caller omits primary_extracted_address,
    the rescue runs its own primary pass (without subject_hint by default).
    """
    text = (
        "When recorded mail to: 6850 Miller Road, Brecksville, OH 44141.\n"
        + ("filler " * 40)
        + "Common address: 4837 SABAL HARBOUR DR, BRADENTON, FL 34203."
    )
    rescued, promoted = verify_with_lender_hq_rescue(text, SUBJECT_FERNANDEZ)
    # Either path is acceptable — what matters is the final verdict is MATCH.
    assert rescued.status == "MATCH"


def test_lender_hq_rescue_skips_when_primary_already_matches():
    """If the primary extraction already returns MATCH, rescue must not fire."""
    text = (
        "Property Address: 4837 SABAL HARBOUR DR, BRADENTON, FL 34203.\n"
        "After recording return to: 6850 Miller Road, Brecksville, OH 44141."
    )
    result, promoted = verify_with_lender_hq_rescue(text, SUBJECT_FERNANDEZ)
    assert promoted is None  # primary was MATCH already
    assert result.status == "MATCH"


def test_lender_hq_rescue_leaves_primary_when_no_subject_in_doc():
    """If the doc genuinely contains no subject-matching address (other property),
    rescue must NOT fabricate a match — it must leave the primary verdict alone.
    """
    text = (
        "When recorded, return to: 6850 Miller Road, Brecksville, OH 44141.\n"
        + ("filler " * 30)
        + "Property Address: 15444 TRINITY FALL WAY, BRADENTON, FL 34212."
    )
    result, promoted = verify_with_lender_hq_rescue(text, SUBJECT_FERNANDEZ)
    # No 4837 SABAL HARBOUR anywhere — rescue must NOT promote anything
    assert promoted is None
    assert result.status in {"NO_MATCH", "AMBIGUOUS"}
