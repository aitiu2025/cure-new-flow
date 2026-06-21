"""Unit tests for the deterministic Legal Description splice (#3, 2026-06-14).

`repair_legal_description_section` overwrites the generated report's Legal
Description section with the canonical verbatim block from
`legal_descriptions.json`, so an LLM paraphrase self-heals instead of forcing
a full agentic regeneration. After a successful splice the post-generation
validator must pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.verification.legal_description_validator import (
    RepairResult,
    pick_canonical_entry,
    repair_legal_description_section,
    validate_legal_description,
)


CANONICAL_BLOCK = (
    "LOT 14, BLOCK 3, OF SUNSET ACRES, ACCORDING TO THE PLAT THEREOF AS "
    "RECORDED IN PLAT BOOK 22, PAGE 17, OF THE PUBLIC RECORDS OF "
    "HILLSBOROUGH COUNTY, FLORIDA. EXCEPTING THEREFROM THE SOUTH 10 FEET."
)
CANONICAL_APN = "A-12-29-18-3RT-000003-00014.0"


def _write(tmp_path: Path, sidecar: dict, md: str) -> tuple[Path, Path]:
    sidecar_path = tmp_path / "legal_descriptions.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    md_path = tmp_path / "RAW.md"
    md_path.write_text(md, encoding="utf-8")
    return md_path, sidecar_path


def _sidecar_one() -> dict:
    return {
        "20240253555": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "apn_verbatim": CANONICAL_APN,
            "document_type": "Warranty Deed",
        }
    }


def test_splice_replaces_paraphrase_and_fixes_apn(tmp_path: Path):
    md = (
        "# Report\n\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "Lot 14 in Block 3 of Sunset Acres (paraphrased), APN A-12-29-18.\n"
        "Source Instrument: Document No. 20240253555 (Warranty Deed)\n"
        "Recorded: 02/01/2024\n\n"
        "## DEEDS OF TRUST / MORTGAGES\n- none\n"
    )
    md_path, sidecar_path = _write(tmp_path, _sidecar_one(), md)

    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    assert result.canonical_doc_number == "20240253555"

    text = result.text
    # Verbatim block present character-for-character.
    assert CANONICAL_BLOCK in text
    # Authoritative APN present; the truncated paraphrase APN line is gone.
    assert CANONICAL_APN in text
    # Source-instrument + recorded citation lines preserved.
    assert "Source Instrument: Document No. 20240253555" in text
    assert "Recorded: 02/01/2024" in text
    # Downstream sections untouched.
    assert "## DEEDS OF TRUST / MORTGAGES" in text


def test_validation_passes_after_splice(tmp_path: Path):
    md = (
        "# Report\n\n"
        "## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "totally wrong paraphrase with no plat reference at all\n\n"
        "## DEEDS OF TRUST / MORTGAGES\n- none\n"
    )
    md_path, sidecar_path = _write(tmp_path, _sidecar_one(), md)

    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    md_path.write_text(result.text, encoding="utf-8")

    validation = validate_legal_description(md_path, sidecar_path)
    assert validation.success is True


def test_no_apn_no_needle_still_passes_via_verbatim_present(tmp_path: Path):
    """A legal with no APN and none of the token-needles must still pass once
    spliced — the appended citation lines dilute Jaccard, so the validator
    relies on the verbatim-block-present criterion."""
    block = (
        "LOT 7, BLOCK 12, OF MAPLEWOOD ESTATES UNIT TWO, ACCORDING TO THE "
        "MAP OR PLAT THEREOF AS RECORDED IN PLAT BOOK 45, PAGE 88, OF THE "
        "PUBLIC RECORDS OF ORANGE COUNTY, FLORIDA."
    )
    sidecar = {"111": {"legal_description_verbatim": block, "document_type": "Warranty Deed"}}
    md = (
        "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "Lot Seven Block Twelve Maplewood (paraphrase)\n"
        "Source Instrument: Document No. 111 (Warranty Deed)\n\n"
        "## DEEDS OF TRUST / MORTGAGES\nnone\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    md_path.write_text(result.text, encoding="utf-8")
    assert validate_legal_description(md_path, sidecar_path).success is True


def test_no_legal_heading_does_not_fabricate(tmp_path: Path):
    """If there is no Legal Description heading, the splice must NOT invent a
    section — it returns unchanged and leaves the validator to flag it."""
    sidecar = {"222": {"legal_description_verbatim": CANONICAL_BLOCK, "apn_verbatim": "X"}}
    md = "# Report\n\n## SOMETHING ELSE\ncontent only\n"
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is False
    assert result.reason == "no legal heading"
    assert result.text == md


def test_canonical_picker_rejects_dot_boilerplate(tmp_path: Path):
    """An entry that is captured Deed-of-Trust covenant text (>=3 boilerplate
    markers) must never be chosen as canonical over a real Exhibit A."""
    sidecar = {
        "good": {"legal_description_verbatim": CANONICAL_BLOCK, "apn_verbatim": CANONICAL_APN},
        "dot": {
            "legal_description_verbatim": (
                "BORROWER COVENANTS and UNIFORM COVENANTS in this Security "
                "Instrument per Fannie Mae / Freddie Mac Form 3005 LOT junk"
            ),
            "apn_verbatim": "99",
        },
    }
    picked = pick_canonical_entry(sidecar)
    assert picked is not None
    assert picked[0] == "good"


def test_fl_folio_metes_legal_is_accepted(tmp_path: Path):
    """Regression (FROMER/Hillsborough benchmark 2026-06-15): a Florida
    folio/metes-and-bounds legal has NO 'LOT'/'PARCEL' token. The old picker
    gate rejected it and the splice silently no-op'd on every FL county. The
    block must now be accepted and spliced."""
    fl_block = (
        "A PORTION OF SECTION 19, TOWNSHIP 28 SOUTH, RANGE 19 EAST, "
        "HILLSBOROUGH COUNTY, FLORIDA, BEING FURTHER DESCRIBED AS FOLLOWS: "
        "FOLIO NO. 144999.0000; PIN NO. A-19-28-19-445-000008-00024-0. "
        "BEGINNING AT THE NW CORNER, THENCE RUN EAST 100 FEET, THENCE SOUTH "
        "50 FEET TO THE POINT OF BEGINNING."
    )
    sidecar = {"2016025198": {"legal_description_verbatim": fl_block, "document_type": "Warranty Deed"}}
    picked = pick_canonical_entry(sidecar)
    assert picked is not None and picked[0] == "2016025198"

    md = (
        "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "some paraphrased FL legal\n\n## DEEDS OF TRUST / MORTGAGES\nnone\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    assert fl_block in result.text
    md_path.write_text(result.text, encoding="utf-8")
    assert validate_legal_description(md_path, sidecar_path).success is True


def test_no_canonical_block_is_noop(tmp_path: Path):
    """Sidecar present but no entry has a usable verbatim block -> no-op."""
    sidecar = {"1": {"apn_verbatim": "123", "legal_description_verbatim": ""}}
    md = "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\nstuff\n"
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is False
    assert result.reason == "no canonical block"


def test_missing_sidecar_is_noop(tmp_path: Path):
    md = "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\nstuff\n"
    md_path = tmp_path / "RAW.md"
    md_path.write_text(md, encoding="utf-8")
    result = repair_legal_description_section(md_path, tmp_path / "nope.json")
    assert result.changed is False
    assert result.reason == "sidecar missing"
    assert result.text == md


# --- P1: deed must beat a longer mortgage / deed-of-trust entry --------------

# A deed-of-trust "Exhibit A" that is LONGER than the vesting deed's legal, so a
# pure block-length ranking would (wrongly) pick it. It still carries a legal
# signal token (LOT) so the legal-description gate accepts it as a candidate.
DOT_LONGER_BLOCK = (
    "EXHIBIT A — LEGAL DESCRIPTION ATTACHED TO SECURITY INSTRUMENT. "
    "LOT 14, BLOCK 3, OF SUNSET ACRES, ACCORDING TO THE PLAT THEREOF AS "
    "RECORDED IN PLAT BOOK 22, PAGE 17, OF THE PUBLIC RECORDS OF "
    "HILLSBOROUGH COUNTY, FLORIDA, TOGETHER WITH ALL IMPROVEMENTS NOW OR "
    "HEREAFTER ERECTED ON THE PROPERTY, AND ALL EASEMENTS, APPURTENANCES, "
    "AND FIXTURES NOW OR HEREAFTER A PART OF THE PROPERTY."
)


def test_picker_prefers_deed_over_longer_mortgage():
    """P1 repro: a longer DEED OF TRUST 'Exhibit A' must NOT outrank the actual
    Warranty Deed. The deed wins despite being the shorter block."""
    sidecar = {
        "WD1": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "apn_verbatim": CANONICAL_APN,
            "document_type": "Warranty Deed",
        },
        "DOT1": {
            "legal_description_verbatim": DOT_LONGER_BLOCK,
            "apn_verbatim": "99",
            "document_type": "Deed of Trust",
        },
    }
    assert len(DOT_LONGER_BLOCK) > len(CANONICAL_BLOCK)  # length trap is live
    picked = pick_canonical_entry(sidecar)
    assert picked is not None
    assert picked[0] == "WD1"


def test_picker_prefers_deed_over_longer_trust_deed_and_mortgage():
    """'TRUST DEED' and 'MORTGAGE' are also security instruments (they contain
    the word DEED / are clearly not a conveyance) and must lose to a deed."""
    for sec_type in ("Trust Deed", "MORTGAGE", "Assignment of Mortgage", "HELOC Modification"):
        sidecar = {
            "SEC": {
                "legal_description_verbatim": DOT_LONGER_BLOCK,
                "apn_verbatim": "99",
                "document_type": sec_type,
            },
            "DEED": {
                "legal_description_verbatim": CANONICAL_BLOCK,
                "apn_verbatim": CANONICAL_APN,
                "document_type": "(D) DEED",  # bullet/parenthetical variant seen in the wild
            },
        }
        picked = pick_canonical_entry(sidecar)
        assert picked is not None and picked[0] == "DEED", sec_type


def test_picker_unknown_doctype_falls_back_to_length_heuristic():
    """When document_type is missing/unknown, the entry is NOT dropped — it
    falls back to the existing longest-block + APN tie-break. Two type-less
    entries: the longer block wins (legacy behaviour preserved)."""
    shorter = "LOT 1, BLOCK 1, OF SHORT PLAT, PLAT BOOK 1, PAGE 1."
    longer = (
        "LOT 2, BLOCK 2, OF LONGER PLAT SUBDIVISION, ACCORDING TO THE PLAT "
        "THEREOF AS RECORDED IN PLAT BOOK 99, PAGE 42, PUBLIC RECORDS."
    )
    sidecar = {
        "short": {"legal_description_verbatim": shorter},
        "long": {"legal_description_verbatim": longer},
    }
    assert len(longer) > len(shorter)
    picked = pick_canonical_entry(sidecar)
    assert picked is not None and picked[0] == "long"


def test_picker_deed_beats_unknown_even_when_unknown_is_longer():
    """A typed DEED outranks a longer untyped/unknown entry (deed rank > unknown
    rank), but an unknown still outranks a security instrument."""
    longer_unknown = DOT_LONGER_BLOCK  # long, no document_type
    sidecar = {
        "unknown_long": {"legal_description_verbatim": longer_unknown},
        "deed_short": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "document_type": "Quit Claim Deed",
        },
    }
    picked = pick_canonical_entry(sidecar)
    assert picked is not None and picked[0] == "deed_short"


def test_picker_single_entry_not_dropped_regardless_of_type():
    """No-regression: a lone entry (even a security instrument) is still picked —
    the deprioritization only matters when a better candidate exists."""
    sidecar = {
        "only_dot": {
            "legal_description_verbatim": DOT_LONGER_BLOCK,
            "document_type": "Deed of Trust",
        }
    }
    picked = pick_canonical_entry(sidecar)
    assert picked is not None and picked[0] == "only_dot"


def test_splice_uses_deed_not_mortgage_end_to_end(tmp_path: Path):
    """End-to-end: the spliced section + source instrument must come from the
    deed (WD1), not the longer mortgage (DOT1)."""
    sidecar = {
        "WD1": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "apn_verbatim": CANONICAL_APN,
            "document_type": "Warranty Deed",
        },
        "DOT1": {
            "legal_description_verbatim": DOT_LONGER_BLOCK,
            "document_type": "Deed of Trust",
        },
    }
    md = (
        "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\nparaphrase\n\n"
        "## DEEDS OF TRUST / MORTGAGES\nnone\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    assert result.canonical_doc_number == "WD1"
    assert CANONICAL_BLOCK in result.text
    assert "SECURITY INSTRUMENT" not in result.text  # the DOT block did not leak
    assert "Document No. WD1" in result.text


# --- P2a: a Source Instrument line is ALWAYS present when none was preserved --

def test_source_instrument_line_present_with_apn_no_preserved_citation(tmp_path: Path):
    """P2a repro: sidecar has an APN AND the original section had NO source
    citation to preserve. The repaired section must STILL carry a fallback
    'Source Instrument: Document No. ...' line — not just legal + parcel."""
    sidecar = {
        "20240253555": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "apn_verbatim": CANONICAL_APN,
            "document_type": "Warranty Deed",
        }
    }
    md = (
        "# Report\n\n## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "Lot 14 in Block 3 of Sunset Acres (paraphrased), no citation here.\n\n"
        "## DEEDS OF TRUST / MORTGAGES\n- none\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    # APN line present...
    assert f"Parcel Identification Number: {CANONICAL_APN}" in result.text
    # ...AND the required source-instrument line present (the bug omitted this).
    assert "Source Instrument: Document No. 20240253555 (Warranty Deed)" in result.text


def test_source_instrument_line_not_duplicated_when_preserved(tmp_path: Path):
    """When the original section already carried a source citation, the splice
    must NOT also append the deterministic fallback (no duplicate source line)."""
    sidecar = {
        "20240253555": {
            "legal_description_verbatim": CANONICAL_BLOCK,
            "apn_verbatim": CANONICAL_APN,
            "document_type": "Warranty Deed",
        }
    }
    md = (
        "# Report\n\n## LEGAL DESCRIPTION (EXHIBIT A)\n"
        "paraphrase\n"
        "Source Instrument: Document No. 20240253555 (Warranty Deed)\n\n"
        "## DEEDS OF TRUST / MORTGAGES\n- none\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    assert result.text.count("Source Instrument: Document No. 20240253555") == 1


def test_source_instrument_fallback_when_no_apn_and_no_citation(tmp_path: Path):
    """No APN and no preserved citation -> fallback source line still emitted
    (pre-existing behaviour, locked here)."""
    block = (
        "LOT 7, BLOCK 12, OF MAPLEWOOD ESTATES UNIT TWO, ACCORDING TO THE "
        "MAP OR PLAT THEREOF AS RECORDED IN PLAT BOOK 45, PAGE 88."
    )
    sidecar = {"111": {"legal_description_verbatim": block, "document_type": "Warranty Deed"}}
    md = (
        "# R\n\n## LEGAL DESCRIPTION (EXHIBIT A)\nparaphrase only\n\n"
        "## DEEDS OF TRUST / MORTGAGES\nnone\n"
    )
    md_path, sidecar_path = _write(tmp_path, sidecar, md)
    result = repair_legal_description_section(md_path, sidecar_path)
    assert result.changed is True
    assert "Source Instrument: Document No. 111 (Warranty Deed)" in result.text
