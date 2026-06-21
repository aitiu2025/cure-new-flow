#!/usr/bin/env python3
"""Render OnE_Report_<Subject>.md → OnE_Report_<Subject>.pdf.

Letter size, 1-inch margins, styled tables, navy headers, red critical-issue
callouts. Uses weasyprint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown
from weasyprint import HTML, CSS

CSS_STYLES = """
@page {
    size: Letter;
    margin: 1in;
    @top-left {
        content: "Ownership and Encumbrance Report";
        font-family: 'Helvetica', sans-serif;
        font-size: 9pt;
        color: #1f3a5f;
    }
    @top-right {
        content: "%%HEADER_RIGHT%%";
        font-family: 'Helvetica', sans-serif;
        font-size: 9pt;
        color: #1f3a5f;
    }
    @bottom-left {
        content: "CURE TitlePro — Confidential";
        font-family: 'Helvetica', sans-serif;
        font-size: 8pt;
        color: #6b7280;
    }
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-family: 'Helvetica', sans-serif;
        font-size: 8pt;
        color: #6b7280;
    }
}

body {
    font-family: 'Helvetica', 'Arial', sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: #1f2937;
}

h1 {
    color: #1f3a5f;
    font-size: 22pt;
    border-bottom: 3px solid #1f3a5f;
    padding-bottom: 6px;
    margin-top: 0;
    margin-bottom: 8pt;
}

h2 {
    color: #1f3a5f;
    font-size: 14pt;
    margin-top: 18pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #d1d5db;
    padding-bottom: 3px;
    page-break-after: avoid;
}

h3 {
    color: #2c4a6e;
    font-size: 12pt;
    margin-top: 12pt;
    margin-bottom: 4pt;
    page-break-after: avoid;
}

h4 {
    color: #3c5a7e;
    font-size: 10.5pt;
    margin-top: 10pt;
    margin-bottom: 3pt;
    page-break-after: avoid;
}

p {
    margin: 4pt 0;
}

/* CRITICAL ISSUES CALLOUT — red left border + pink background */
blockquote {
    border-left: 4pt solid #c0392b;
    background: #fff5f5;
    margin: 8pt 0;
    padding: 8pt 12pt;
    color: #2c3e50;
    font-size: 9.5pt;
}

blockquote p {
    margin: 4pt 0;
}

blockquote strong {
    color: #c0392b;
}

/* Tables */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 8pt 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}

table th {
    background: #1f3a5f;
    color: #ffffff;
    text-align: left;
    padding: 6pt 8pt;
    font-weight: 600;
    border: 1px solid #1f3a5f;
}

table td {
    padding: 5pt 8pt;
    border: 1px solid #cccccc;
    vertical-align: top;
}

table tr:nth-child(even) td {
    background: #f4f6f8;
}

table tr:nth-child(odd) td {
    background: #ffffff;
}

/* Bold the first column of 2-column "field/value" tables */
table tr td:first-child strong {
    color: #1f3a5f;
}

/* POTENTIALLY OPEN warnings — bold red */
strong {
    color: #1f3a5f;
}

/* Lists */
ul, ol {
    margin: 4pt 0;
    padding-left: 18pt;
}

li {
    margin: 2pt 0;
}

/* Code / inline instrument numbers */
code {
    font-family: 'Menlo', 'Courier New', monospace;
    font-size: 9pt;
    background: #f1f3f5;
    padding: 1px 4px;
    border-radius: 2px;
    color: #c0392b;
}

/* Horizontal rule */
hr {
    border: none;
    border-top: 1px solid #d1d5db;
    margin: 12pt 0;
}

/* Page break before Exhibit A. The ```{=openxml}``` block in the source is the
   DOCX-only page break (pandoc interprets it); for the PDF it is stripped and
   this div-driven CSS break takes over so Exhibit A starts on its own page. */
.page-break-before {
    page-break-before: always;
}

/* Italic-block (small examiner notes) */
em {
    color: #4b5563;
}

/* The footer-style attribution line at end */
p:last-of-type em {
    font-size: 8.5pt;
    color: #6b7280;
}
"""


def _strip_operator_memos(md_text: str) -> str:
    """Strip operator-only memo blocks before the OnE PDF is built.

    Uses the canonical sanitizer when importable; otherwise an equivalent
    marker-bounded fallback. Marker-bounded — never touches a real examiner flag.
    """
    try:
        src = Path(__file__).resolve().parents[2] / "src"
        if src.exists() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from titlepro.verification.report_sanitizer import strip_operator_memos

        return strip_operator_memos(md_text)[0]
    except Exception:
        import re as _re

        open_re = _re.compile(r"\[?\s*INTERNAL\s+MEMO\b", _re.IGNORECASE)
        close_re = _re.compile(
            r"(END\s+INTERNAL\s+MEMO|REMOVE\s+EVERYTHING\s+BELOW|DELETE\s+EVERYTHING\s+BELOW)",
            _re.IGNORECASE,
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


def _strip_raw_openxml(md_text: str) -> str:
    """Drop ```{=openxml}``` raw blocks (DOCX-only page breaks) so they don't
    render as literal code in the PDF. The sibling
    `<div class="page-break-before">` drives the PDF page break instead."""
    import re as _re

    return _re.sub(r"```\{=openxml\}.*?```\s*", "", md_text, flags=_re.DOTALL)


def _derive_header_right(md_path: Path, md_text: str) -> str:
    """Per-subject running-header (top-right) for the OnE PDF.

    Was hardcoded to "CURE File: CURE-2026-05-22-FL-BROWARD-B" (the ANAND
    template), which leaked onto every report's page margins. Derive it instead
    from the report: the surname from the OnE_Report_<Name>.md filename + the
    county from the Subject line. Falls back to a neutral label.
    """
    import re as _re

    name = ""
    m = _re.match(r"OnE_Report_(.+)", md_path.stem)
    if m:
        name = m.group(1).replace("_", " ").strip().upper()
    county = ""
    cm = _re.search(r"\b([A-Z][A-Za-z.\- ]+?\s+County)\b", md_text)
    if cm:
        county = cm.group(1).strip()
        county = _re.sub(r",?\s*(Florida|FL)\s*$", "", county).strip()
    label = " — ".join(p for p in (name, county) if p)
    # Quote-safe for embedding in the CSS content: string.
    return (label or "CURE TitlePro").replace('"', "'")


def md_to_pdf(md_path: Path, pdf_path: Path) -> None:
    md_text = _strip_raw_openxml(_strip_operator_memos(md_path.read_text(encoding="utf-8")))
    css_styles = CSS_STYLES.replace("%%HEADER_RIGHT%%", _derive_header_right(md_path, md_text))
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )

    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OnE Report</title></head>
<body>
{html_body}
</body></html>
"""
    HTML(string=html_doc, base_url=str(md_path.parent)).write_pdf(
        str(pdf_path),
        stylesheets=[CSS(string=css_styles)],
    )
    print(f"[+] Rendered {pdf_path} ({pdf_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: render_one_report.py <input.md> <output.pdf>")
        sys.exit(1)
    md_to_pdf(Path(sys.argv[1]), Path(sys.argv[2]))
