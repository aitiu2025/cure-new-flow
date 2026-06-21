"""Regression tests for the Legal Description verbatim validator, anchored
on the MONTOYA audit evidence (Book-vs-VOLUME paraphrase, dropped APN check
digit, dropped conveyance recital).

History: the original version of this test asserted that the on-disk MONTOYA
Title md FAILS the validator — correct while the case folder still held the
pre-fix paraphrased output. The case was re-run after the 2026-05-18 fix and
the folder now carries the verbatim Exhibit A, so that assertion inverted
(triaged 2026-06-10). The rejection regression now runs against a synthetic
paraphrase built from the same OCR source, which keeps it independent of
case-folder state; the on-disk md is asserted to PASS.

See docs/audits/legal_description_ordering_audit_2026-05-18.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from titlepro.verification.legal_description_validator import (
    validate_legal_description,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MONTOYA_CASE = (
    PROJECT_ROOT
    / "src/titlepro/api/downloaded_doc/0513/ContraCosta_MONTOYA_Marcelino"
)

_montoya_available = (MONTOYA_CASE / "Title_Examination_Notes.md").exists() and (
    MONTOYA_CASE / "B49178046_extracted.md"
).exists()


def _montoya_sidecar(tmp_path: Path) -> Path:
    """Synthesize the sidecar `extract_legal_descriptions` would produce,
    sourced from the MONTOYA OCR markdown."""
    extracted_md = (MONTOYA_CASE / "B49178046_extracted.md").read_text(
        encoding="utf-8"
    )
    m = re.search(r"EXHIBIT A.*?PARCEL NO\. 502-153-010-9", extracted_md, re.DOTALL)
    assert m, "EXHIBIT A block not found in MONTOYA OCR markdown"
    sidecar = {
        "2026-0022802": {
            "document_type": "DEED OF TRUST",
            "legal_description_verbatim": m.group(0),
            "apn_verbatim": "502-153-010-9",
            "anchor_used": "EXHIBIT A",
            "extraction_source": "extracted_md",
            "extraction_confidence": 0.95,
        }
    }
    sidecar_path = tmp_path / "legal_descriptions.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    return sidecar_path


@pytest.mark.skipif(
    not _montoya_available,
    reason="MONTOYA case dir not present in this checkout",
)
def test_paraphrased_montoya_md_fails_verbatim_validator(tmp_path):
    """A paraphrased Legal Description (the pre-fix MONTOYA failure mode)
    MUST be rejected: VOLUME→Book swap, APN check digit dropped, conveyance
    recital dropped. This is the exact shape the 2026-05-18 audit caught."""
    sidecar_path = _montoya_sidecar(tmp_path)
    verbatim = json.loads(sidecar_path.read_text())["2026-0022802"][
        "legal_description_verbatim"
    ]

    paraphrased = verbatim
    # Reproduce the audit's paraphrase defects:
    paraphrased = re.sub(r"(?i)\bVOLUME\b", "Book", paraphrased)
    paraphrased = paraphrased.replace("502-153-010-9", "502-153-010")
    paraphrased = re.sub(
        r"THIS BEING THE SAME PROPERTY.*", "", paraphrased, flags=re.DOTALL
    )
    md_path = tmp_path / "Title_Examination_Notes.md"
    md_path.write_text(
        "# Abstractor Notes/Chain\n\n## LEGAL DESCRIPTION (EXHIBIT A)\n\n"
        + paraphrased
        + "\n\n## DOCUMENTS EXAMINED\n\n- none\n",
        encoding="utf-8",
    )

    result = validate_legal_description(md_path, sidecar_path)
    assert result.success is False, (
        f"Validator failed to flag paraphrased MONTOYA Title md. "
        f"sim={result.best_similarity}, missing={result.missing_tokens}, "
        f"details={result.details}"
    )
    assert "502-153-010-9" in result.missing_tokens


@pytest.mark.skipif(
    not _montoya_available,
    reason="MONTOYA case dir not present in this checkout",
)
def test_regenerated_montoya_md_passes_verbatim_validator(tmp_path):
    """The post-fix on-disk MONTOYA Title md carries the verbatim Exhibit A
    (VOLUME, EXCEPTING THEREFROM, conveyance recital, APN with check digit)
    and must pass — via the required-token criterion even where OCR noise
    keeps raw Jaccard below the 0.95 similarity threshold."""
    sidecar_path = _montoya_sidecar(tmp_path)
    md_path = MONTOYA_CASE / "Title_Examination_Notes.md"

    result = validate_legal_description(md_path, sidecar_path)
    assert result.success is True, (
        f"Regenerated verbatim MONTOYA md should pass: "
        f"sim={result.best_similarity}, missing={result.missing_tokens}, "
        f"details={result.details}"
    )
    assert "502-153-010-9" in result.matched_tokens
    assert not result.missing_tokens
