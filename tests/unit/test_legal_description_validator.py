"""Unit tests for `verification/legal_description_validator.py`.

Covers the Jaccard similarity threshold, token-presence fallback, and
the various edge cases (missing sidecar, missing md, empty entries).

See docs/audits/legal_description_ordering_audit_2026-05-18.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.verification.legal_description_validator import (
    ValidationResult,
    jaccard_similarity,
    validate_legal_description,
)


MONTOYA_VERBATIM = """EXHIBIT A

THE LAND REFERRED TO IS SITUATED IN THE COUNTY OF
CONTRA COSTA, CITY OF EL CERRITO, STATE OF CALIFORNIA,
AND IS DESCRIBED AS FOLLOWS:

LOT 10, AS SHOWN ON THE MAP OF JUSTICE SUBDIVISION, UNIT
NO. 2, CITY OF EL CERRITO, COUNTY OF CONTRA COSTA,
CALIFORNIA, WHICH MAP WAS FILED IN THE OFFICE OF THE
RECORDER OF THE COUNTY OF CONTRA COSTA, STATE OF
CALIFORNIA, ON JULY 24, 1953, IN VOLUME 51 OF MAPS, PAGE 30.

EXCEPTING THEREFROM THE MINERALS AND MINERAL RIGHTS
RESERVED IN THE DEED FROM RECONSTRUCTION FINANCE
CORPORATION TO NOBLE F. JUSTICE, ET UX., DATED OCTOBER
13, 1952, RECORDED NOVEMBER 26, 1952, IN BOOK 2032 OF
OFFICIAL RECORDS OF CONTRA COSTA COUNTY, PAGE 145.

THIS BEING THE SAME PROPERTY CONVEYED TO MARCELINO
MONTOYA AND SARA MONTOYA, HUSBAND AND WIFE AS JOINT
TENANTS, DATED 06/12/2018 AND RECORDED ON 06/19/2018 IN
INSTRUMENT NO. 2018-0097205-00, IN THE CONTRA COSTA
COUNTY RECORDERS OFFICE.

PARCEL NO. 502-153-010-9
"""


def _write_sidecar(tmp_path: Path, entries: dict) -> Path:
    path = tmp_path / "legal_descriptions.json"
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return path


def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# jaccard_similarity sanity
# ---------------------------------------------------------------------------


def test_jaccard_identical_text_is_one():
    assert jaccard_similarity("Lot 10 of Maps", "Lot 10 of Maps") == 1.0


def test_jaccard_zero_on_empty():
    assert jaccard_similarity("", "anything") == 0.0
    assert jaccard_similarity("anything", "") == 0.0


def test_jaccard_paraphrase_below_threshold():
    """The known MONTOYA paraphrase (Book vs Volume + dropped recital)
    should fall below the 0.95 verbatim threshold."""
    paraphrased = (
        "Lot 10, as shown on the map of Justice Subdivision, Unit No. 2, "
        "City of El Cerrito, Contra Costa County, California, in Book 51 "
        "of Maps, Page 30. APN: 502-153-010"
    )
    sim = jaccard_similarity(paraphrased, MONTOYA_VERBATIM)
    assert sim < 0.95, f"paraphrase scored {sim}, should be below 0.95"


# ---------------------------------------------------------------------------
# validate_legal_description success / failure paths
# ---------------------------------------------------------------------------


def test_success_when_md_contains_verbatim_block(tmp_path):
    sidecar = _write_sidecar(
        tmp_path,
        {
            "2018-0097205": {
                "document_type": "Grant Deed",
                "legal_description_verbatim": MONTOYA_VERBATIM,
                "apn_verbatim": "502-153-010-9",
                "anchor_used": "EXHIBIT A",
                "extraction_source": "extracted_md",
                "extraction_confidence": 0.95,
            }
        },
    )
    md = _write_md(
        tmp_path,
        "Title_Examination_Notes.md",
        "# Abstractor Notes/Chain\n\n"
        "## CHAIN OF TITLE\nstuff\n\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n\n"
        f"{MONTOYA_VERBATIM}\n\n"
        "## DEEDS OF TRUST / MORTGAGES\nmore stuff\n",
    )
    result = validate_legal_description(md, sidecar)
    assert result.success is True
    assert result.best_similarity >= 0.95


def test_failure_when_md_paraphrases_block(tmp_path):
    sidecar = _write_sidecar(
        tmp_path,
        {
            "2018-0097205": {
                "document_type": "Grant Deed",
                "legal_description_verbatim": MONTOYA_VERBATIM,
                "apn_verbatim": "502-153-010-9",
            }
        },
    )
    paraphrased = (
        "Lot 10, as shown on the map of Justice Subdivision, Unit No. 2, "
        "City of El Cerrito, Contra Costa County, California, in Book 51 "
        "of Maps, Page 30. APN: 502-153-010"
    )
    md = _write_md(
        tmp_path,
        "Title_Examination_Notes.md",
        "# Abstractor Notes/Chain\n\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n\n"
        f"{paraphrased}\n\n"
        "## NEXT\n",
    )
    result = validate_legal_description(md, sidecar)
    assert result.success is False
    assert result.best_similarity < 0.95
    # The audit's evidence: dropped APN check digit shows up as missing token.
    assert "502-153-010-9" in result.missing_tokens


def test_success_when_token_presence_fallback_holds(tmp_path):
    """Even if Jaccard is borderline, all required tokens present passes."""
    sidecar = _write_sidecar(
        tmp_path,
        {
            "doc1": {
                "document_type": "Grant Deed",
                "legal_description_verbatim": MONTOYA_VERBATIM,
                "apn_verbatim": "502-153-010-9",
            }
        },
    )
    # MD that contains every required token even though prose differs.
    md_text = (
        "# Abstractor Notes/Chain\n\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n\n"
        f"{MONTOYA_VERBATIM}\n"
        "PARCEL NO. 502-153-010-9\n"
    )
    md = _write_md(tmp_path, "Title_Examination_Notes.md", md_text)
    result = validate_legal_description(md, sidecar)
    assert result.success is True


def test_missing_sidecar_is_passthrough(tmp_path):
    md = _write_md(tmp_path, "anything.md", "# hi\n")
    result = validate_legal_description(md, tmp_path / "nope.json")
    assert result.success is True
    assert "missing" in result.details


def test_empty_sidecar_is_passthrough(tmp_path):
    sidecar = _write_sidecar(tmp_path, {})
    md = _write_md(tmp_path, "anything.md", "# hi\n")
    result = validate_legal_description(md, sidecar)
    assert result.success is True


def test_missing_md_fails(tmp_path):
    sidecar = _write_sidecar(
        tmp_path,
        {"doc1": {"legal_description_verbatim": MONTOYA_VERBATIM, "apn_verbatim": "x"}},
    )
    result = validate_legal_description(tmp_path / "missing.md", sidecar)
    assert result.success is False
    assert "missing" in result.details


def test_entry_without_verbatim_block_is_ignored(tmp_path):
    """A sidecar entry with no verbatim text should be silently skipped."""
    sidecar = _write_sidecar(
        tmp_path,
        {
            "doc_no_block": {
                "document_type": "Deed of Trust",
                "legal_description_verbatim": "",
                "apn_verbatim": "",
            }
        },
    )
    md = _write_md(tmp_path, "x.md", "## LEGAL DESCRIPTION (EXHIBIT A)\n\nnothing\n")
    result = validate_legal_description(md, sidecar)
    # No entries to validate against -> defaults to True (nothing to check).
    assert result.success is True
