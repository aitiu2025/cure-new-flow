"""Unit tests for vesting_chain_walker."""
from __future__ import annotations

from titlepro.verification.vesting_chain_walker import (
    VestingChainFinding,
    walk_vesting_chain,
)


def _deed(
    num: str,
    date: str,
    *,
    deed_type: str = "DEED_WARRANTY",
    grantor: str = "",
    grantee: str = "",
) -> dict:
    return {
        "doc_number": num,
        "inferred_type": deed_type,
        "recording_date": date,
        "grantor": grantor,
        "grantee": grantee,
    }


# ---------------------------------------------------------------------------
# 1. PASS — candidate is 9 years older (RILEY arm's-length case)
# ---------------------------------------------------------------------------
def test_pass_arms_length_acquisition_9_years_older():
    documents = [
        _deed(
            "2021099994",
            "2021-05-13",
            deed_type="DEED_QUITCLAIM",
            grantor="RILEY, ROBERT S AND LYN M",
            grantee="RILEY TRUST DATED 03/05/2014",
        ),
        _deed(
            "2012188921",
            "2012-11-05",
            deed_type="DEED_WARRANTY",
            grantor="STIEFEL PROPERTIES LLC",
            grantee="RILEY, ROBERT S AND LYN M",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "PASS"
    assert result.current_vesting_doc_number == "2021099994"
    assert result.candidate_prior_vesting_doc_number == "2012188921"
    assert result.candidate_age_days_from_current is not None
    assert result.candidate_age_days_from_current >= 30


# ---------------------------------------------------------------------------
# 2. SAME_DAY_REFI — same-day trust overlap (RILEY Jun 2 regression case)
# ---------------------------------------------------------------------------
def test_same_day_trust_overlap_refi_interim_detected():
    documents = [
        _deed(
            "2021099994",
            "2021-05-13",
            deed_type="DEED_QUITCLAIM",
            grantor="RILEY, ROBERT S AND LYN M",
            grantee="RILEY TRUST DATED 03/05/2014",
        ),
        _deed(
            "2021099992",
            "2021-05-13",
            deed_type="DEED_QUITCLAIM",
            grantor="RILEY TRUST DATED 03/05/2014",
            grantee="RILEY, ROBERT S AND LYN M",
        ),
        _deed(
            "2012188921",
            "2012-11-05",
            deed_type="DEED_WARRANTY",
            grantor="STIEFEL PROPERTIES LLC",
            grantee="RILEY, ROBERT S AND LYN M",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.current_vesting_doc_number == "2021099994"
    assert result.candidate_prior_vesting_doc_number == "2021099992"
    assert result.candidate_age_days_from_current == 0
    assert result.recommended_walk_target_doc_number == "2012188921"
    assert "2021099992" in result.walked_past_doc_numbers


# ---------------------------------------------------------------------------
# 3. SAME_DAY_REFI — 5-day-old husband-wife overlap
# ---------------------------------------------------------------------------
def test_within_refi_window_husband_wife_overlap():
    documents = [
        _deed(
            "2024-100",
            "2024-06-01",
            deed_type="DEED_QUITCLAIM",
            grantor="SMITH, JOHN AND JANE",
            grantee="SMITH FAMILY TRUST",
        ),
        _deed(
            "2024-099",
            "2024-05-27",
            deed_type="DEED_QUITCLAIM",
            grantor="SMITH FAMILY TRUST",
            grantee="SMITH, JOHN AND JANE",
        ),
        _deed(
            "2010-050",
            "2010-04-22",
            deed_type="DEED_WARRANTY",
            grantor="ABC HOLDINGS LLC",
            grantee="SMITH, JOHN AND JANE",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.candidate_age_days_from_current == 5
    assert result.recommended_walk_target_doc_number == "2010-050"


# ---------------------------------------------------------------------------
# 4. SAME_DAY_REFI — shared surname (individual <-> trust within a week)
# ---------------------------------------------------------------------------
def test_shared_surname_overlap_within_week():
    documents = [
        _deed(
            "2022-200",
            "2022-09-10",
            grantor="JOHNSON, ROBERT",
            grantee="JOHNSON, ROBERT TRUST",
        ),
        _deed(
            "2022-195",
            "2022-09-04",
            grantor="JOHNSON, ROBERT TRUST",
            grantee="JOHNSON, ROBERT",
        ),
        _deed(
            "2008-001",
            "2008-01-15",
            grantor="XYZ PROPERTIES LLC",
            grantee="JOHNSON, ROBERT",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.recommended_walk_target_doc_number == "2008-001"


# ---------------------------------------------------------------------------
# 5. AMBIGUOUS — candidate 10 days old, NO overlap (could be quick resale)
# ---------------------------------------------------------------------------
def test_ambiguous_no_party_overlap_within_window():
    # Quick-resale shape with NO overlap between Current and Candidate:
    # an unusual but legitimate fact pattern that should be flagged for
    # operator review (AMBIGUOUS), not auto-classified as a refi interim.
    documents = [
        _deed(
            "2024-100",
            "2024-06-10",
            grantor="NEW_OWNER, DAN",
            grantee="BUYER, BOB",
        ),
        _deed(
            "2024-095",
            "2024-05-31",
            grantor="PRIOR_SELLER, CARLA",
            grantee="NEXT_HOLDER, EVE",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "AMBIGUOUS"


# ---------------------------------------------------------------------------
# 6. PASS — candidate is 31 days older (just past the default window)
# ---------------------------------------------------------------------------
def test_just_past_default_window_returns_pass():
    documents = [
        _deed(
            "2024-100",
            "2024-06-01",
            grantor="X TRUST",
            grantee="X, JOHN",
        ),
        _deed(
            "2024-050",
            "2024-05-01",
            grantor="X, JOHN",
            grantee="X TRUST",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "PASS"
    assert result.candidate_age_days_from_current == 31


# ---------------------------------------------------------------------------
# 7. Multi-deed same-day cluster — walker skips all interim cluster
# ---------------------------------------------------------------------------
def test_multi_deed_same_day_cluster_walker_skips_all():
    documents = [
        _deed(
            "C-4",
            "2020-03-15",
            grantor="RUSSO, MIKE AND SARA",
            grantee="RUSSO FAMILY TRUST",
        ),
        _deed(
            "C-3",
            "2020-03-15",
            grantor="RUSSO FAMILY TRUST",
            grantee="RUSSO, MIKE AND SARA",
        ),
        _deed(
            "C-2",
            "2020-03-15",
            grantor="RUSSO, MIKE AND SARA",
            grantee="RUSSO FAMILY TRUST",
        ),
        _deed(
            "ARM-LENGTH",
            "2005-08-08",
            grantor="OLD OWNER LLC",
            grantee="RUSSO, MIKE AND SARA",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.recommended_walk_target_doc_number == "ARM-LENGTH"


# ---------------------------------------------------------------------------
# 8. Walker recommends the most-recent arm's-length acquisition
# ---------------------------------------------------------------------------
def test_walker_picks_most_recent_arms_length():
    documents = [
        _deed(
            "2024-100",
            "2024-06-01",
            grantor="SMITH, JOHN",
            grantee="SMITH TRUST",
        ),
        _deed(
            "2024-099",
            "2024-06-01",
            grantor="SMITH TRUST",
            grantee="SMITH, JOHN",
        ),
        _deed(
            "2015-001",
            "2015-04-10",
            grantor="UNRELATED, ALICE",
            grantee="SMITH, JOHN",
        ),
        _deed(
            "2000-001",
            "2000-01-01",
            grantor="OLDER LLC",
            grantee="UNRELATED, ALICE",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    # Most-recent arm's-length acquisition is 2015-001 (not 2000-001).
    assert result.recommended_walk_target_doc_number == "2015-001"


# ---------------------------------------------------------------------------
# 9. Missing recording date -> AMBIGUOUS
# ---------------------------------------------------------------------------
def test_missing_recording_date_returns_ambiguous():
    documents = [
        _deed("X-1", "2024-06-01", grantor="A, ONE", grantee="A TRUST"),
        {
            "doc_number": "X-2",
            "inferred_type": "DEED_WARRANTY",
            "grantor": "A TRUST",
            "grantee": "A, ONE",
        },
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "AMBIGUOUS"


# ---------------------------------------------------------------------------
# 10. Only one deed -> PASS, candidate is None
# ---------------------------------------------------------------------------
def test_only_one_deed_pass_with_none_candidate():
    documents = [
        _deed("ONLY", "2020-01-01", grantor="X LLC", grantee="Y INDIVIDUAL"),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "PASS"
    assert result.current_vesting_doc_number == "ONLY"
    assert result.candidate_prior_vesting_doc_number is None


# ---------------------------------------------------------------------------
# 11. PR's Deed (inheritance) is legitimate Prior Vesting even if recent
# ---------------------------------------------------------------------------
def test_pr_deed_inheritance_never_walked_past():
    documents = [
        _deed(
            "C-100",
            "2024-06-01",
            deed_type="DEED_WARRANTY",
            grantor="HEIR, MARY",
            grantee="BUYER, BOB",
        ),
        _deed(
            "PR-DEED",
            "2024-05-15",
            deed_type="DEED_PERSONAL_REPRESENTATIVE",
            grantor="ESTATE OF DEPARTED, JOHN",
            grantee="HEIR, MARY",
        ),
    ]
    result = walk_vesting_chain(documents)
    # PR deed is the legitimate Prior Vesting -- walker MUST NOT recommend
    # walking past it even if within the refi window.
    assert result.status == "PASS"
    assert result.candidate_prior_vesting_doc_number == "PR-DEED"


# ---------------------------------------------------------------------------
# 12. Trust normalization handles "as Trustees of THE X TRUST DATED ..."
# ---------------------------------------------------------------------------
def test_trust_normalization_handles_dated_variants():
    documents = [
        _deed(
            "C-1",
            "2022-04-10",
            grantor="ANDERSEN, KIM, AS TRUSTEE OF THE ANDERSEN FAMILY REVOCABLE TRUST DATED 01/01/2020",
            grantee="ANDERSEN, KIM",
        ),
        _deed(
            "C-2",
            "2022-04-10",
            grantor="ANDERSEN, KIM",
            grantee="ANDERSEN, KIM, TRUSTEE OF THE ANDERSEN FAMILY LIVING TRUST DTD 01/01/2020",
        ),
        _deed(
            "ARM",
            "2010-09-09",
            grantor="OLD OWNER LLC",
            grantee="ANDERSEN, KIM",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.recommended_walk_target_doc_number == "ARM"


# ---------------------------------------------------------------------------
# 13. Surname-overlap detection between sole and h+w forms
# ---------------------------------------------------------------------------
def test_surname_overlap_sole_vs_husband_wife():
    documents = [
        _deed(
            "C-1",
            "2023-07-15",
            grantor="WILLIAMS, JOHN, A SINGLE MAN",
            grantee="WILLIAMS, JOHN AND JANE, HUSBAND AND WIFE",
        ),
        _deed(
            "ARM",
            "2018-02-12",
            grantor="THIRDPARTY HOLDINGS",
            grantee="WILLIAMS, JOHN, A SINGLE MAN",
        ),
    ]
    result = walk_vesting_chain(documents)
    # Same John on both sides of C-1 -- party overlap -- candidate is same day
    # NO: candidate ARM is 5+ years older. So PASS.
    assert result.status == "PASS"
    assert result.candidate_prior_vesting_doc_number == "ARM"


# ---------------------------------------------------------------------------
# 14. current_vesting_doc_number override works
# ---------------------------------------------------------------------------
def test_explicit_current_vesting_override():
    documents = [
        _deed(
            "NEWEST",
            "2025-01-01",
            grantor="UNRELATED, X",
            grantee="UNRELATED, Y",
        ),
        _deed(
            "EXPLICIT",
            "2021-05-13",
            grantor="RILEY, ROBERT",
            grantee="RILEY TRUST",
        ),
        _deed(
            "INTERIM",
            "2021-05-13",
            grantor="RILEY TRUST",
            grantee="RILEY, ROBERT",
        ),
        _deed(
            "OLD",
            "2010-01-01",
            grantor="OLD LLC",
            grantee="RILEY, ROBERT",
        ),
    ]
    result = walk_vesting_chain(
        documents, current_vesting_doc_number="EXPLICIT"
    )
    assert result.current_vesting_doc_number == "EXPLICIT"
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.recommended_walk_target_doc_number == "OLD"


# ---------------------------------------------------------------------------
# 15. subject_owner_names hint improves detection with thin metadata
# ---------------------------------------------------------------------------
def test_subject_owner_names_hint_helps():
    # Both deeds have very minimal grantor/grantee strings, but the
    # subject-owner-names hint signals the expected surname.
    documents = [
        _deed(
            "C-1",
            "2024-06-01",
            grantor="HARRIS",
            grantee="HARRIS REVOCABLE TRUST",
        ),
        _deed(
            "C-2",
            "2024-06-01",
            grantor="HARRIS REVOCABLE TRUST",
            grantee="HARRIS",
        ),
        _deed(
            "ARM",
            "2008-08-08",
            grantor="DEVELOPER INC",
            grantee="HARRIS, RICHARD",
        ),
    ]
    result = walk_vesting_chain(
        documents, subject_owner_names=["HARRIS, RICHARD AND PATRICIA"]
    )
    assert result.status == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert result.recommended_walk_target_doc_number == "ARM"


# ---------------------------------------------------------------------------
# 16. refi_window_days is configurable
# ---------------------------------------------------------------------------
def test_refi_window_days_configurable():
    documents = [
        _deed(
            "C-1",
            "2024-06-15",
            grantor="DOE, JOHN",
            grantee="DOE TRUST",
        ),
        _deed(
            "C-2",
            "2024-06-01",
            grantor="DOE TRUST",
            grantee="DOE, JOHN",
        ),
        _deed(
            "ARM",
            "2010-01-01",
            grantor="OTHER LLC",
            grantee="DOE, JOHN",
        ),
    ]
    # With a tight 7-day window the 14-day-old candidate is OUT of the
    # window -- so PASS, candidate is the genuine Prior Vesting.
    result_tight = walk_vesting_chain(documents, refi_window_days=7)
    assert result_tight.status == "PASS"
    # With the default 30-day window the candidate is IN scope -- so refi.
    result_default = walk_vesting_chain(documents)
    assert result_default.status == "SAME_DAY_REFI_INTERIM_DETECTED"


# ---------------------------------------------------------------------------
# 17. to_dict() is JSON-serializable shape
# ---------------------------------------------------------------------------
def test_finding_to_dict_shape():
    finding = VestingChainFinding(
        status="SAME_DAY_REFI_INTERIM_DETECTED",
        current_vesting_doc_number="A",
        candidate_prior_vesting_doc_number="B",
        candidate_age_days_from_current=0,
        candidate_party_overlap_reason="test",
        recommended_walk_target_doc_number="C",
        recommended_walk_target_reason="test",
        walked_past_doc_numbers=["B"],
        ordered_chain=[
            {
                "document_number": "A",
                "tenure": "current",
                "kind": "current_vesting",
            },
        ],
    )
    d = finding.to_dict()
    assert d["status"] == "SAME_DAY_REFI_INTERIM_DETECTED"
    assert d["walked_past_doc_numbers"] == ["B"]
    assert d["ordered_chain"][0]["document_number"] == "A"
    # Mutating the returned list must not affect the dataclass.
    d["walked_past_doc_numbers"].append("X")
    d["ordered_chain"][0]["document_number"] = "X"
    assert finding.walked_past_doc_numbers == ["B"]
    assert finding.ordered_chain[0]["document_number"] == "A"


# ---------------------------------------------------------------------------
# 18. v1.7 tenure-stop extension — Certificate of Title is never walked past
# ---------------------------------------------------------------------------
def test_certificate_of_title_never_walked_past():
    documents = [
        _deed(
            "SALE",
            "2024-06-01",
            deed_type="DEED_WARRANTY",
            grantor="BUYER, BOB",
            grantee="NEW_OWNER, NANCY",
        ),
        _deed(
            "CT",
            "2024-05-20",
            deed_type="CERTIFICATE_OF_TITLE",
            grantor="CLERK OF COURT",
            grantee="BUYER, BOB",
        ),
        _deed(
            "OLDER",
            "2010-01-01",
            grantor="OLD OWNER",
            grantee="CLERK OF COURT",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "PASS"
    assert result.candidate_prior_vesting_doc_number == "CT"
    assert result.recommended_walk_target_doc_number is None
    assert result.ordered_chain[-1]["kind"] == "tenure_commencing"


# ---------------------------------------------------------------------------
# 19. v1.7 tenure-stop extension — free-text Tax Deed is a deed stop
# ---------------------------------------------------------------------------
def test_tax_deed_free_text_is_tenure_stop():
    documents = [
        _deed(
            "SALE",
            "2024-06-01",
            deed_type="DEED_WARRANTY",
            grantor="BUYER, BOB",
            grantee="NEW_OWNER, NANCY",
        ),
        _deed(
            "TAX",
            "2024-05-20",
            deed_type="Tax Deed",
            grantor="TAX COLLECTOR",
            grantee="BUYER, BOB",
        ),
        _deed(
            "OLDER",
            "2010-01-01",
            grantor="OLD OWNER",
            grantee="TAX COLLECTOR",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert result.status == "PASS"
    assert result.candidate_prior_vesting_doc_number == "TAX"
    assert result.ordered_chain[-1]["document_number"] == "TAX"


# ---------------------------------------------------------------------------
# 20. v1.7 ordered_chain carries current/interim/tenure-commencing rows
# ---------------------------------------------------------------------------
def test_ordered_chain_emitted_for_same_day_refi():
    documents = [
        _deed(
            "2021099994",
            "2021-05-13",
            deed_type="DEED_QUITCLAIM",
            grantor="RILEY, ROBERT S AND LYN M",
            grantee="RILEY TRUST DATED 03/05/2014",
        ),
        _deed(
            "2021099992",
            "2021-05-13",
            deed_type="DEED_QUITCLAIM",
            grantor="RILEY TRUST DATED 03/05/2014",
            grantee="RILEY, ROBERT S AND LYN M",
        ),
        _deed(
            "2012188921",
            "2012-11-05",
            deed_type="DEED_WARRANTY",
            grantor="STIEFEL PROPERTIES LLC",
            grantee="RILEY, ROBERT S AND LYN M",
        ),
    ]
    result = walk_vesting_chain(documents)
    assert [row["document_number"] for row in result.ordered_chain] == [
        "2021099994",
        "2021099992",
        "2012188921",
    ]
    assert [row["kind"] for row in result.ordered_chain] == [
        "current_vesting",
        "interim",
        "tenure_commencing",
    ]
