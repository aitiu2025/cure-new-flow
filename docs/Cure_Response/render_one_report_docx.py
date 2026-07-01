#!/usr/bin/env python3
"""Render a CURE report markdown file to DOCX via pandoc.

Uses pandoc to convert markdown to a Microsoft Word document. Preserves
table structure, bold formatting, blockquotes, and page breaks. The output
is fully editable in Microsoft Word / Apple Pages / Google Docs for
reviewer markup and feedback.

Usage:
    python3 render_one_report_docx.py <input.md> <output.docx>

Optional environment / flags (future):
    --reference-doc <path>   pass a reference docx to pandoc for style overrides
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _strip_operator_memos(md_text: str):
    """Strip operator-only memo blocks before the OnE goes to DOCX.

    Prefers the canonical sanitizer in titlepro.verification.report_sanitizer;
    falls back to an equivalent marker-bounded strip if the package is not
    importable (e.g. script run standalone outside the repo). Marker-bounded, so
    no real examiner flag/warning is ever touched.
    """
    try:
        # repo_root/src on sys.path so the canonical module wins.
        src = Path(__file__).resolve().parents[2] / "src"
        if src.exists() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from titlepro.verification.report_sanitizer import strip_operator_memos

        clean, _ = strip_operator_memos(md_text)
        return clean
    except Exception:
        open_re = re.compile(r"\[?\s*INTERNAL\s+MEMO\b", re.IGNORECASE)
        close_re = re.compile(
            r"(END\s+INTERNAL\s+MEMO|REMOVE\s+EVERYTHING\s+BELOW|DELETE\s+EVERYTHING\s+BELOW)",
            re.IGNORECASE,
        )
        lines = md_text.split("\n")
        out, i, n = [], 0, len(lines)
        while i < n:
            if open_re.search(lines[i]):
                j = i
                while j < n and not close_re.search(lines[j]):
                    j += 1
                i = (j if j < n else n - 1) + 1
                continue
            out.append(lines[i])
            i += 1
        return "\n".join(out)


# The historical reference.docx currently causes pandoc/LibreOffice to render
# markdown table text outside empty table grids. Keep DOCX generation on
# pandoc's default table model until the reference document is rebuilt.
DEFAULT_REFERENCE_DOC: Path | None = None


def md_to_docx(md_path: Path, docx_path: Path, reference_doc: Path | None = None) -> None:
    # Apply a reference document only when explicitly provided or when a vetted
    # default has been restored.
    if reference_doc is None and DEFAULT_REFERENCE_DOC and DEFAULT_REFERENCE_DOC.exists():
        reference_doc = DEFAULT_REFERENCE_DOC
    # Sanitize operator memos out of the OnE before pandoc sees it.
    sanitized = _strip_operator_memos(md_path.read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(sanitized)
        src_md = Path(tf.name)
    cmd = [
        "pandoc",
        str(src_md),
        "-o", str(docx_path),
        "-f", "markdown+pipe_tables+raw_html+hard_line_breaks+raw_attribute",
        "-t", "docx",
        "--standalone",
    ]
    if reference_doc and reference_doc.exists():
        cmd += ["--reference-doc", str(reference_doc)]
    try:
        subprocess.run(cmd, check=True)
    finally:
        src_md.unlink(missing_ok=True)
    size = docx_path.stat().st_size
    print(f"[+] Rendered {docx_path.name} ({size:,} bytes)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: render_one_report_docx.py <input.md> <output.docx> [reference.docx]")
        sys.exit(1)
    md = Path(sys.argv[1])
    docx = Path(sys.argv[2])
    ref = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    md_to_docx(md, docx, ref)
