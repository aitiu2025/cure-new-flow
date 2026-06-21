"""Build JSON + XML versions of an existing RAW + Title md/pdf pair.

Combines the markdown (preferred) or PDF (fallback) structure (H2 sections) with the
case-dir's structured artifacts (documents_found.json, tax_*.json, document_metadata.json,
workflow_config.json, etc.) into a single canonical export per report type.

Canonical schema (see also docs/SYSTEM_PROMPT_pdf_to_json_xml.md):

    report_metadata:
      report_type       — title from first H1 of the source
      case_dir          — absolute path
      case_name         — basename of the case dir
      source_markdown   — md filename (empty string if PDF-only)
      source_pdf        — pdf filename (or null if missing)
      source_input_used — "markdown" or "pdf"
      generated_at      — ISO-8601 of conversion
      source_modified   — ISO-8601 of source file mtime
      generator_version — schema/script version literal, currently "1.0"
    preamble_markdown
    sections[]          — [{heading, content_markdown}, ...]
    section_count
    structured_artifacts

Usage:
    python3 build_json_xml_reports.py <case_dir>
"""
from __future__ import annotations
import json
import re
import sys
import html
from pathlib import Path
from datetime import datetime


GENERATOR_VERSION = "1.0"


def parse_markdown_sections(md_path: Path) -> dict:
    """Parse an md file into structured H1 title + H2 sections."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Capture the document title (first H1)
    title = ""
    for ln in lines:
        m = re.match(r"^#\s+(.+)$", ln)
        if m:
            title = m.group(1).strip()
            break

    # Collect H2 sections
    sections = []
    current_header = None
    current_buf: list[str] = []
    preamble: list[str] = []
    saw_first_h2 = False
    for ln in lines:
        h2 = re.match(r"^##\s+(.+)$", ln)
        if h2:
            if current_header is not None:
                sections.append((current_header, "\n".join(current_buf).strip()))
            current_header = h2.group(1).strip()
            current_buf = []
            saw_first_h2 = True
        else:
            if saw_first_h2:
                current_buf.append(ln)
            else:
                preamble.append(ln)
    if current_header is not None:
        sections.append((current_header, "\n".join(current_buf).strip()))

    return {
        "title": title,
        "preamble": "\n".join(preamble).strip(),
        "sections": [{"heading": h, "content_markdown": c} for h, c in sections],
        "section_count": len(sections),
        "source_file": str(md_path),
        "source_bytes": md_path.stat().st_size,
        "source_modified": datetime.fromtimestamp(md_path.stat().st_mtime).isoformat(),
    }


def parse_pdf_sections(pdf_path: Path) -> dict:
    """PDF-only fallback parser. Uses PyMuPDF if available; degrades gracefully."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "PyMuPDF (fitz) is required for PDF-only conversion; install with `pip install pymupdf`"
        ) from e

    doc = fitz.open(str(pdf_path))
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    lines = full_text.splitlines()

    # Title: first reasonable nonblank line
    title = ""
    nonblank = [l.strip() for l in lines if l.strip()]
    for cand in nonblank[:8]:
        if len(cand) >= 30 and any(c.isalpha() for c in cand):
            title = cand
            break

    H2_PATTERNS = [
        re.compile(r"^(PHASE \d+:[^\n]+)$", re.IGNORECASE),
        re.compile(
            r"^(TITLE EXAMINATION SUMMARY|CHAIN OF TITLE|DEEDS OF TRUST.*MORTGAGES?|"
            r"DOCUMENTS EXAMINED|CRITICAL ISSUE.*|NOTES AND OBSERVATIONS|"
            r"CURRENT OWNERSHIP|JUDGMENTS.*LIENS.*ENCUMBRANCES|TAX STATUS|"
            r"EXHIBIT A.*LEGAL DESCRIPTION|DISCLAIMER)$"
        ),
        re.compile(r"^([A-Z]\.\s+[A-Z][^\n]{6,})$"),
    ]

    sections: list[tuple[str, str]] = []
    preamble: list[str] = []
    current_header = None
    current_buf: list[str] = []
    saw_first = False
    for raw in lines:
        ln = raw.strip()
        matched = next((p.match(ln) for p in H2_PATTERNS if p.match(ln)), None)
        if matched:
            if current_header is not None:
                sections.append((current_header, "\n".join(current_buf).strip()))
            current_header = matched.group(1).strip()
            current_buf = []
            saw_first = True
        else:
            (current_buf if saw_first else preamble).append(raw)
    if current_header is not None:
        sections.append((current_header, "\n".join(current_buf).strip()))

    return {
        "title": title,
        "preamble": "\n".join(preamble).strip(),
        "sections": [{"heading": h, "content_markdown": c} for h, c in sections],
        "section_count": len(sections),
        "source_file": str(pdf_path),
        "source_bytes": pdf_path.stat().st_size,
        "source_modified": datetime.fromtimestamp(pdf_path.stat().st_mtime).isoformat(),
    }


def safe_json_load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except Exception as e:
        return {"_load_error": str(e), "_path": str(p)}


def dict_to_xml(obj, root: str = "root") -> str:
    """Naive dict/list -> XML walker. Element names get sanitized."""

    def sanitize_tag(tag: str) -> str:
        t = re.sub(r"[^A-Za-z0-9_]+", "_", str(tag)).strip("_")
        if not t or t[0].isdigit():
            t = "n_" + t
        return t or "node"

    def render(value, tag, indent: int) -> str:
        pad = "  " * indent
        tag = sanitize_tag(tag)
        if isinstance(value, dict):
            if not value:
                return f"{pad}<{tag}/>"
            inner = "\n".join(render(v, k, indent + 1) for k, v in value.items())
            return f"{pad}<{tag}>\n{inner}\n{pad}</{tag}>"
        if isinstance(value, list):
            if not value:
                return f"{pad}<{tag}/>"
            inner = "\n".join(render(v, "item", indent + 1) for v in value)
            return f"{pad}<{tag}>\n{inner}\n{pad}</{tag}>"
        if value is None or value == "":
            return f"{pad}<{tag}/>"
        s = html.escape(str(value))
        return f"{pad}<{tag}>{s}</{tag}>"

    return f'<?xml version="1.0" encoding="UTF-8"?>\n{render(obj, root, 0)}\n'


def build_report(case_dir: Path, stem: str, structured_extras: dict) -> dict | None:
    """Build the canonical report dict for one stem (RAW or Title).

    Prefers <stem>.md; falls back to <stem>.pdf. Returns None when neither exists.
    Emits the 4 spec metadata fields: source_input_used, source_pdf, case_name,
    generator_version.
    """
    md_path = case_dir / f"{stem}.md"
    pdf_path = case_dir / f"{stem}.pdf"

    md_exists = md_path.exists()
    pdf_exists = pdf_path.exists()

    if not md_exists and not pdf_exists:
        return None

    if md_exists:
        parsed = parse_markdown_sections(md_path)
        source_input_used = "markdown"
        source_markdown = md_path.name
    else:
        parsed = parse_pdf_sections(pdf_path)
        source_input_used = "pdf"
        source_markdown = ""

    return {
        "report_metadata": {
            "report_type": parsed["title"] or f"{stem}",
            "case_dir": str(case_dir),
            "case_name": case_dir.name,
            "source_markdown": source_markdown,
            "source_pdf": pdf_path.name if pdf_exists else None,
            "source_input_used": source_input_used,
            "generated_at": datetime.now().isoformat(),
            "source_modified": parsed["source_modified"],
            "generator_version": GENERATOR_VERSION,
        },
        "preamble_markdown": parsed["preamble"],
        "sections": parsed["sections"],
        "section_count": parsed["section_count"],
        "structured_artifacts": structured_extras,
    }


def load_structured_artifacts(case_dir: Path) -> dict:
    structured = {
        "workflow_config":     safe_json_load(case_dir / "workflow_config.json"),
        "workflow_status":     safe_json_load(case_dir / "workflow_status.json"),
        "documents_found":     safe_json_load(case_dir / "documents_found.json"),
        "search_results":      safe_json_load(case_dir / "search_results.json"),
        "document_metadata":   safe_json_load(case_dir / "document_metadata.json"),
        "extracted_documents": safe_json_load(case_dir / "extracted_documents.json"),
        "download_manifest":   safe_json_load(case_dir / "download_manifest.json"),
        "tax_data":            None,
        "tax_data_path":       None,
        "tax_lookup_status":   safe_json_load(case_dir / "tax_lookup_status.json"),
    }
    for p in case_dir.glob("tax_*.json"):
        if p.name == "tax_lookup_status.json":
            continue
        structured["tax_data"] = safe_json_load(p)
        structured["tax_data_path"] = p.name
        break
    return structured


REPORT_STEMS = ("RAW_TWO_OWNER_SEARCH_EXAM", "Title_Examination_Notes")


def build_case(case_dir: Path) -> list[dict]:
    """Build JSON+XML for every report stem in the case dir; return per-stem summary."""
    structured = load_structured_artifacts(case_dir)

    out_summary: list[dict] = []
    for stem in REPORT_STEMS:
        report = build_report(case_dir, stem, structured)
        if report is None:
            out_summary.append({"stem": stem, "status": "skipped (no md/pdf source)"})
            continue
        json_path = case_dir / f"{stem}.json"
        xml_path = case_dir / f"{stem}.xml"

        json_text = json.dumps(report, indent=2, default=str)
        # Validate JSON parses
        json.loads(json_text)
        json_path.write_text(json_text, encoding="utf-8")

        xml_text = dict_to_xml(report, root=stem)
        # Validate XML parses
        import xml.etree.ElementTree as ET
        ET.fromstring(xml_text)
        xml_path.write_text(xml_text, encoding="utf-8")

        out_summary.append({
            "stem": stem,
            "status": "written",
            "source_input_used": report["report_metadata"]["source_input_used"],
            "json": str(json_path),
            "json_bytes": json_path.stat().st_size,
            "xml": str(xml_path),
            "xml_bytes": xml_path.stat().st_size,
            "section_count": report.get("section_count"),
        })
    return out_summary


def main():
    if len(sys.argv) < 2:
        print("usage: build_json_xml_reports.py <case_dir>", file=sys.stderr)
        sys.exit(2)
    case_dir = Path(sys.argv[1])
    if not case_dir.is_dir():
        print(f"not a directory: {case_dir}", file=sys.stderr)
        sys.exit(2)

    summary = build_case(case_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
