"""Unit tests for src/titlepro/reports/build_json_xml_reports.py.

Covers:
- MD-input path produces both <stem>.json and <stem>.xml
- JSON validates against the canonical schema (all 4 spec metadata fields present)
- source_input_used == "markdown" when MD exists
- XML parses cleanly and root tag matches stem
- PDF-fallback test (best-effort; skipped if PyMuPDF/reportlab unavailable)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "src" / "titlepro" / "reports" / "build_json_xml_reports.py"

REQUIRED_TOP_KEYS = {
    "report_metadata",
    "preamble_markdown",
    "sections",
    "section_count",
    "structured_artifacts",
}
REQUIRED_META_KEYS = {
    "report_type",
    "case_dir",
    "case_name",
    "source_markdown",
    "source_pdf",
    "source_input_used",
    "generated_at",
    "source_modified",
    "generator_version",
}
MANDATORY_NEW_FIELDS = {"source_input_used", "source_pdf", "case_name", "generator_version"}


SAMPLE_MD = """# RAW TWO-OWNER TITLE SEARCH EXAMINATION REPORT

This is preamble text appearing before the first H2.

## PHASE 1: RECORDER NAME SEARCHES

Recorder name searches were completed for **DOE JANE** in Test County.

## PHASE 2: DOCUMENT INVENTORY

Inventory classification details.

| Doc # | Type |
|---|---|
| 1 | DOT |
| 2 | Grant Deed |

## PHASE 3: TAX & PROPERTY LOOKUP

Tax bill PAID. APN 123-456-78.
"""


def assert_canonical_schema(data: dict) -> None:
    """Schema assertion helper. Raises AssertionError with details on first mismatch."""
    top = set(data.keys())
    missing_top = REQUIRED_TOP_KEYS - top
    assert not missing_top, f"missing top-level keys: {missing_top}"

    meta = data["report_metadata"]
    meta_keys = set(meta.keys())
    missing_meta = REQUIRED_META_KEYS - meta_keys
    assert not missing_meta, f"missing report_metadata keys: {missing_meta}"

    for f in MANDATORY_NEW_FIELDS:
        # all 4 mandatory new fields must be PRESENT (not necessarily truthy — source_pdf may be null)
        assert f in meta, f"mandatory new field missing: {f}"

    # types
    assert isinstance(data["sections"], list), "sections must be a list"
    assert isinstance(data["section_count"], int), "section_count must be int"
    assert data["section_count"] == len(data["sections"]), "section_count must match len(sections)"
    assert isinstance(data["structured_artifacts"], dict), "structured_artifacts must be a dict"

    assert meta["source_input_used"] in ("markdown", "pdf"), (
        f"source_input_used must be 'markdown' or 'pdf', got {meta['source_input_used']!r}"
    )
    assert meta["generator_version"] == "1.0", (
        f"generator_version must be '1.0', got {meta['generator_version']!r}"
    )


def _run(case_dir: Path) -> dict:
    """Invoke the script via subprocess and return the parsed JSON summary."""
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(case_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"script failed: stderr={res.stderr}\nstdout={res.stdout}"
    return json.loads(res.stdout)


@pytest.fixture()
def case_dir(tmp_path: Path) -> Path:
    """A minimal synthetic case dir with a RAW md source."""
    d = tmp_path / "TestCounty_DOE_Jane"
    d.mkdir()
    (d / "RAW_TWO_OWNER_SEARCH_EXAM.md").write_text(SAMPLE_MD, encoding="utf-8")
    # add one structured artifact to exercise the loader
    (d / "workflow_config.json").write_text(
        json.dumps({"owner_name": "DOE JANE", "county": "test"}), encoding="utf-8"
    )
    return d


def test_script_exists():
    """Smoke test: the converter is at its long-term home."""
    assert SCRIPT.exists(), f"converter not found at {SCRIPT}"


def test_md_input_produces_json_and_xml(case_dir: Path):
    summary = _run(case_dir)
    assert isinstance(summary, list)
    raw_summary = next(s for s in summary if s["stem"] == "RAW_TWO_OWNER_SEARCH_EXAM")
    assert raw_summary["status"] == "written"
    assert (case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").exists()
    assert (case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.xml").exists()


def test_json_contains_all_4_mandatory_metadata_fields(case_dir: Path):
    _run(case_dir)
    data = json.loads((case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    meta = data["report_metadata"]
    for f in MANDATORY_NEW_FIELDS:
        assert f in meta, f"mandatory field missing: {f}"
    assert meta["case_name"] == case_dir.name
    assert meta["source_input_used"] == "markdown"
    assert meta["generator_version"] == "1.0"
    # source_pdf is null when no .pdf exists (still emitted)
    assert meta["source_pdf"] is None


def test_json_validates_against_canonical_schema(case_dir: Path):
    _run(case_dir)
    data = json.loads((case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    assert_canonical_schema(data)


def test_xml_parses_and_root_matches_stem(case_dir: Path):
    _run(case_dir)
    xml_text = (case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.xml").read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    assert root.tag == "RAW_TWO_OWNER_SEARCH_EXAM"
    # report_metadata child present
    rm = root.find("report_metadata")
    assert rm is not None
    assert rm.find("case_name").text == case_dir.name
    assert rm.find("source_input_used").text == "markdown"
    assert rm.find("generator_version").text == "1.0"


def test_source_input_used_is_markdown_when_md_exists(case_dir: Path):
    # also put a pdf in the dir to confirm md is still preferred
    (case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.pdf").write_bytes(b"%PDF-1.4\n%fake\n")
    _run(case_dir)
    data = json.loads((case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    assert data["report_metadata"]["source_input_used"] == "markdown"
    assert data["report_metadata"]["source_pdf"] == "RAW_TWO_OWNER_SEARCH_EXAM.pdf"


def test_sections_parsed_from_markdown(case_dir: Path):
    _run(case_dir)
    data = json.loads((case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    headings = [s["heading"] for s in data["sections"]]
    assert "PHASE 1: RECORDER NAME SEARCHES" in headings
    assert "PHASE 2: DOCUMENT INVENTORY" in headings
    assert "PHASE 3: TAX & PROPERTY LOOKUP" in headings
    assert data["section_count"] == 3


def test_structured_artifacts_loaded(case_dir: Path):
    _run(case_dir)
    data = json.loads((case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    sa = data["structured_artifacts"]
    assert sa["workflow_config"] == {"owner_name": "DOE JANE", "county": "test"}
    # other artifacts that don't exist should be null
    assert sa["search_results"] is None
    assert sa["tax_data"] is None


def test_missing_source_skipped(tmp_path: Path):
    """A case dir with neither md nor pdf for a stem should be skipped (not crash)."""
    d = tmp_path / "Empty_Case"
    d.mkdir()
    # write a Title md but no RAW source at all
    (d / "Title_Examination_Notes.md").write_text("# Title Exam\n\n## OWNERSHIP\nDetails.\n", encoding="utf-8")
    summary = _run(d)
    raw = next(s for s in summary if s["stem"] == "RAW_TWO_OWNER_SEARCH_EXAM")
    title = next(s for s in summary if s["stem"] == "Title_Examination_Notes")
    assert raw["status"].startswith("skipped")
    assert title["status"] == "written"
    assert not (d / "RAW_TWO_OWNER_SEARCH_EXAM.json").exists()
    assert (d / "Title_Examination_Notes.json").exists()


def test_pdf_fallback(tmp_path: Path):
    """Optional: if PyMuPDF + reportlab available, generate a tiny PDF and confirm PDF path is used."""
    fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")
    reportlab = pytest.importorskip("reportlab", reason="reportlab not installed")
    from reportlab.pdfgen import canvas  # type: ignore

    d = tmp_path / "PdfOnly_Case"
    d.mkdir()
    pdf_path = d / "RAW_TWO_OWNER_SEARCH_EXAM.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(72, 800, "RAW TWO-OWNER TITLE SEARCH EXAMINATION REPORT")
    c.drawString(72, 760, "PHASE 1: RECORDER NAME SEARCHES")
    c.drawString(72, 740, "Some content for phase 1.")
    c.drawString(72, 700, "PHASE 2: DOCUMENT INVENTORY")
    c.drawString(72, 680, "Some content for phase 2.")
    c.save()

    summary = _run(d)
    raw = next(s for s in summary if s["stem"] == "RAW_TWO_OWNER_SEARCH_EXAM")
    assert raw["status"] == "written"
    assert raw["source_input_used"] == "pdf"

    data = json.loads((d / "RAW_TWO_OWNER_SEARCH_EXAM.json").read_text(encoding="utf-8"))
    assert_canonical_schema(data)
    assert data["report_metadata"]["source_input_used"] == "pdf"
    assert data["report_metadata"]["source_pdf"] == "RAW_TWO_OWNER_SEARCH_EXAM.pdf"
    assert data["report_metadata"]["source_markdown"] == ""
