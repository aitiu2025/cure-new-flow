"""Unit tests for ``titlepro.verification.tony_commentary_generator``.

Confirms that the generator:

1. Writes ``Tony_verified_commentary.md`` to a case folder.
2. Emits every required section.
3. PRESERVES the internal-tool vocabulary (linker / verifier / classifier /
   MATCH scores) that the customer-facing Title MUST suppress (per F11) —
   the commentary is engineering-facing and these references are the whole
   point of having a companion file.
4. Uses the canonical directive-citation format
   ``As per directive #N (one-line description)`` and never the
   reviewer-name variants.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from titlepro.verification.tony_commentary_generator import (
    DIRECTIVES,
    cite,
    generate_commentary,
)


# ---------------------------------------------------------------------------
# Fixture: a minimal case folder that mirrors the structure of
# `src/titlepro/api/downloaded_doc/0522/Broward_ANAND_v2/`.
# ---------------------------------------------------------------------------


@pytest.fixture
def case_dir(tmp_path: Path) -> Path:
    d = tmp_path / "case_unit_test"
    d.mkdir()
    (d / "workflow_config.json").write_text(
        json.dumps(
            {
                "owner_name": "TEST OWNER",
                "county": "fl_broward",
                "search_requests": [
                    {"name": "TEST, OWNER", "party_types": ["Grantor"]},
                    {"name": "TEST, SPOUSE", "party_types": ["Grantor"]},
                ],
                "property_address": "123 MAIN ST, TESTVILLE, FL",
                "subject_id": "CURE-TEST-001",
                "output_folder_name": "case_unit_test",
            }
        )
    )
    (d / "search_results.json").write_text(
        json.dumps(
            {
                "search_parameters": {"owner_name": "TEST OWNER"},
                "summary": {"total_searches": 6, "total_unique_documents": 3},
                "runs": [
                    {"name_searched": "TEST, OWNER", "result_count": 16},
                    {"name_searched": "TEST, OWNER", "result_count": 16},
                    {"name_searched": "TEST, OWNER", "result_count": 16},
                    {"name_searched": "TEST, SPOUSE", "result_count": 11},
                    {"name_searched": "TEST, SPOUSE", "result_count": 11},
                    {"name_searched": "TEST, SPOUSE", "result_count": 11},
                ],
            }
        )
    )
    (d / "documents_found.json").write_text(
        json.dumps(
            [
                {"document_number": "111111", "found_via_names": ["TEST, OWNER"]},
                {"document_number": "222222", "found_via_names": ["TEST, SPOUSE"]},
                {"document_number": "333333", "found_via_names": ["TEST, OWNER"]},
            ]
        )
    )
    (d / "broward_download_manifest.json").write_text(
        json.dumps(
            [
                {"doc": "111111", "status": "success"},
                {"doc": "222222", "status": "success"},
                {"doc": "333333", "status": "success"},
            ]
        )
    )
    (d / "phase1_verifications.json").write_text(
        json.dumps(
            {
                "subject_address": "123 MAIN ST, TESTVILLE, FL",
                "subject_address_verification": {
                    "111111": {
                        "extracted_address": "123 MAIN ST, TESTVILLE, FL",
                        "status": "MATCH",
                        "similarity": 1.0,
                        "evidence": "street_number match: '123'",
                    },
                    "222222": {
                        "extracted_address": "999 OTHER ST, ELSEWHERE, FL",
                        "status": "NO_MATCH",
                        "similarity": 0.05,
                        "evidence": "street_number MISMATCH",
                    },
                    "333333": {
                        "extracted_address": "123 MAIN ST, TESTVILLE, FL",
                        "status": "MATCH",
                        "similarity": 0.95,
                        "evidence": "fuzzy match",
                    },
                },
                "document_type_classifications": {
                    "111111": {
                        "inferred_type": "DEED_WARRANTY",
                        "confidence": 0.95,
                        "source": "title_page",
                        "evidence": "Special Warranty Deed",
                    },
                    "222222": {
                        "inferred_type": "MORTGAGE",
                        "confidence": 0.9,
                        "source": "title_page",
                        "evidence": "MORTGAGE",
                    },
                    "333333": {
                        "inferred_type": "RELEASE",
                        "confidence": 0.9,
                        "source": "title_page",
                        "evidence": "Release of Mortgage",
                    },
                },
                "mortgage_classifications": {
                    "222222": {
                        "status": "released",
                        "release_chain": [
                            {
                                "mortgage": "222222",
                                "satisfaction": "333333",
                                "type": "release",
                                "evidence": "Release of Mortgage 222222",
                            }
                        ],
                        "related_modifications": [],
                    }
                },
            }
        )
    )
    (d / "prohibited_documents.json").write_text(
        json.dumps(
            [
                {
                    "document_number": "999000",
                    "record_date": "01/01/2020",
                    "doc_type": "CPX",
                    "prohibited_reason": "FL Chapter 2002-302",
                    "prohibited_message": (
                        "In accordance with CHAPTER 2002-302 of the Laws of Florida..."
                    ),
                }
            ]
        )
    )
    (d / "Title_Examination_Notes.md").write_text(
        "# Abstractor Notes/Chain\n\n"
        "## TITLE EXAMINATION SUMMARY\n\n"
        "Subject: 123 MAIN ST, TESTVILLE, FL\n"
        "## CHAIN OF TITLE\n\n"
        "Doc 111111 — Special Warranty Deed.\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n\n"
        "Lot 1 Block 2\n"
        "## DEEDS OF TRUST / MORTGAGES\n\n"
        "RELEASED: Mortgage 222222 satisfied by Release 333333.\n"
        "## DOCUMENTS EXAMINED\n\n"
        "- 111111\n- 222222\n- 333333\n"
    )
    (d / "RAW_TWO_OWNER_SEARCH_EXAM.md").write_text(
        "## PHASE 1: RECORDER NAME SEARCHES\n"
        "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION\n"
        "## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION\n"
        "## PHASE 4: TAX & PROPERTY LOOKUP\n"
        "## PHASE 5: RAW EXAM REPORT\n"
    )
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


REQUIRED_SECTIONS = [
    "## Verifier Verdict",
    "## Step 0 — Source of Truth",
    "## Six Directives — Scorecard",
    "## Known Failure Modes — Scans",
    "## Subject-Property Address Verification (per doc)",
    "## Document Type Classification (per doc)",
    "## Mortgage Status Classification (per mortgage)",
    "## Linker-vs-LLM Discrepancies",
    "## Engineering Follow-ups",
    "## Prohibited Documents",
    "## Tony-Style Verdict",
]


def test_generator_writes_file(case_dir: Path) -> None:
    out_path = generate_commentary(case_dir)
    assert out_path.exists()
    assert out_path.name == "Tony_verified_commentary.md"
    assert out_path.parent == case_dir


def test_all_required_sections_present(case_dir: Path) -> None:
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    for section in REQUIRED_SECTIONS:
        assert section in text, f"missing required section: {section}"


def test_directive_citation_format(case_dir: Path) -> None:
    """Every directive citation must inline the description; no bare
    ``directive #N`` and no reviewer-name variant."""
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    # Every "directive #N" occurrence should be inside a citation containing
    # an inline parenthetical with the canonical description.
    canonical = re.findall(r"As per directive #\d+ \([^)]+\)", text)
    assert canonical, "expected at least one canonical directive citation"
    # Reviewer name MUST NOT appear in directive citations.
    forbidden_patterns = [
        r"(?i)Per Tony directive",
        r"(?i)\bTony directive\b",
        r"(?i)\bTony Roveda\b",
        r"(?i)\bAs per Tony",
    ]
    for pat in forbidden_patterns:
        assert not re.search(pat, text), f"forbidden reviewer-name pattern leaked: {pat}"


def test_cite_helper_returns_canonical_format() -> None:
    for n, desc in DIRECTIVES.items():
        out = cite(n)
        assert out == f"As per directive #{n} ({desc})"
    # All six directives are present.
    assert set(DIRECTIVES.keys()) == {1, 2, 3, 4, 5, 6}


def test_internal_tool_references_preserved(case_dir: Path) -> None:
    """The whole point of the commentary file: it MUST contain the
    internal-tool vocabulary that the Title strips. This confirms the
    generator preserves engineering signal in the engineering-facing file.
    """
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    expected_engineering_markers = [
        "released_mortgage_linker",
        "subject_address_verifier",
        "document_type_classifier",
        "MATCH",
        "NO_MATCH",
        "release_chain",
        "Engineering Follow-ups",
    ]
    for marker in expected_engineering_markers:
        assert marker in text, f"engineering marker missing from commentary: {marker}"


def test_address_table_matches_phase1(case_dir: Path) -> None:
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    # Each phase1_verifications doc# must appear in the address table.
    phase1 = json.loads((case_dir / "phase1_verifications.json").read_text())
    for doc in phase1["subject_address_verification"]:
        assert doc in text, f"doc# {doc} missing from commentary"


def test_prohibited_doc_surfaced(case_dir: Path) -> None:
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    assert "999000" in text
    assert "FL Chapter 2002-302" in text


def test_mortgage_release_chain_evidence_present(case_dir: Path) -> None:
    out_path = generate_commentary(case_dir)
    text = out_path.read_text()
    # Released MTG 222222 should be linked to satisfaction 333333 with evidence.
    assert "222222" in text and "333333" in text
    assert "release_chain" in text or "Release-chain evidence" in text


def test_missing_files_tolerated(tmp_path: Path) -> None:
    """Generator must not crash when artifacts are missing."""
    case = tmp_path / "empty_case"
    case.mkdir()
    out_path = generate_commentary(case)
    assert out_path.exists()
    # Every required section is still present, just with placeholder bodies.
    text = out_path.read_text()
    for section in REQUIRED_SECTIONS:
        assert section in text
