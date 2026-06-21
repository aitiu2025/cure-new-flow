from __future__ import annotations

import re
from pathlib import Path


RAW_DOC_TYPE = "raw"
TITLE_DOC_TYPE = "title_notes"

# ---------------------------------------------------------------------------
# doc_type selection guide (read before rendering a new report PDF):
#
#   RAW_DOC_TYPE    -> white background (default).
#                     Use for:
#                       * RAW_TWO_OWNER_SEARCH_EXAM.pdf
#                       * OnE_Report_*.pdf  (Ownership-and-Encumbrance reports)
#                       * Any other engineering-facing or customer-facing
#                         CURE report that is NOT the Title Examination Notes.
#
#   TITLE_DOC_TYPE  -> cream / yellow-notepad background (#FFFDF0) + "LOGO"
#                     header-right.
#                     Use ONLY for: Title_Examination_Notes.pdf
#                     Do NOT use for OnE reports — that yellow background is
#                     reserved for the Title Examination Notes deliverable.
# ---------------------------------------------------------------------------


CSS_RAW = """
@page {
    size: letter;
    margin: 0.7in 0.7in 0.9in 0.7in;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: Calibri, Arial, sans-serif;
        font-size: 8pt;
        color: #999;
    }
    @bottom-right {
        content: "CURE TitlePro — Confidential";
        font-family: Calibri, Arial, sans-serif;
        font-size: 7pt;
        color: #bbb;
    }
}

body {
    font-family: Calibri, "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #333;
}
"""


CSS_TITLE = """
@page {
    size: letter;
    margin: 0.7in 0.7in 0.9in 0.7in;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: Calibri, Arial, sans-serif;
        font-size: 8pt;
        color: #999;
    }
    @bottom-right {
        content: "CURE TitlePro — Confidential";
        font-family: Calibri, Arial, sans-serif;
        font-size: 7pt;
        color: #bbb;
    }
}

body {
    font-family: Calibri, "Segoe UI", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #333;
    background-color: #FFFDF0;
}
"""


CSS_SHARED = """
.page-break { page-break-before: always; margin: 0; padding: 0; height: 0; }
.page-break-before, div.page-break-before {
    page-break-before: always;
    margin: 0; padding: 0; height: 0;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #3A7BBF;
    padding-bottom: 8px;
    margin-bottom: 16px;
}

.header-left { font-size: 14pt; font-weight: bold; color: #1a5276; }
.header-right { font-size: 11pt; font-weight: bold; color: #3A7BBF; font-style: italic; }

.main-title {
    font-size: 16pt;
    font-weight: bold;
    text-align: center;
    margin-bottom: 6px;
    color: #1a5276;
    text-transform: uppercase;
    letter-spacing: 1px;
    border-bottom: 3px solid #e74c3c;
    padding-bottom: 10px;
}

.meta-line { margin: 3px 0; font-size: 10pt; color: #444; }
.meta-line strong { color: #1a5276; }

.section-title {
    font-size: 12pt;
    font-weight: bold;
    margin-top: 20px;
    margin-bottom: 10px;
    color: #fff;
    text-transform: uppercase;
    background-color: #3A7BBF;
    padding: 7px 12px;
    border-radius: 3px;
    page-break-after: avoid;
}

.subsection-title {
    font-size: 11pt;
    font-weight: bold;
    margin-top: 14px;
    margin-bottom: 6px;
    color: #1a5276;
    border-left: 4px solid #3A7BBF;
    padding-left: 10px;
    page-break-after: avoid;
}

.detail-title {
    font-size: 10.5pt;
    font-weight: bold;
    margin-top: 12px;
    margin-bottom: 4px;
    color: #2c3e50;
    border-left: 3px solid #7f8c8d;
    padding-left: 8px;
    page-break-after: avoid;
}

.section-divider { border: none; border-top: 1px solid #ddd; margin: 14px 0; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 16px 0;
    font-size: 9pt;
    page-break-inside: auto;
}

th {
    background-color: #3A7BBF;
    color: #fff;
    font-weight: bold;
    text-align: left;
    padding: 7px 8px;
    font-size: 8.5pt;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}

td {
    padding: 6px 8px;
    border-bottom: 1px solid #e0e0e0;
    vertical-align: top;
    line-height: 1.35;
}

tr:nth-child(even) td { background-color: #ffffff; }

.status-open { color: #c0392b; font-weight: bold; }
.status-potentially-open { color: #e67e22; font-weight: bold; }
.status-closed { color: #27ae60; font-weight: bold; }
.status-critical { color: #c0392b; font-weight: bold; }
.status-not-subject { color: #7f8c8d; font-weight: bold; font-style: italic; }
.status-unknown { color: #8e44ad; font-weight: bold; }

s { color: #999; text-decoration: line-through; }

.blockquote-critical,
.blockquote-disclaimer,
.blockquote-recommendations,
.blockquote-source,
.blockquote-note,
.blockquote-resolved,
.blockquote-default {
    padding: 12px 16px;
    margin: 14px 0;
    border-radius: 0 4px 4px 0;
}

.blockquote-critical {
    background-color: #fdf2f2;
    border-left: 5px solid #e74c3c;
}
.blockquote-critical p, .blockquote-critical li { font-size: 10pt; margin: 4px 0; color: #5a1a1a; }
.blockquote-critical strong { color: #c0392b; }

.blockquote-disclaimer {
    background-color: #fefce8;
    border-left: 5px solid #f59e0b;
}
.blockquote-disclaimer p { font-size: 9.5pt; color: #78350f; margin: 4px 0; }

.blockquote-recommendations {
    background-color: #f0fdf4;
    border-left: 5px solid #22c55e;
}
.blockquote-recommendations p, .blockquote-recommendations li { font-size: 10pt; margin: 4px 0; color: #14532d; }
.blockquote-recommendations strong { color: #15803d; }

.blockquote-source {
    background-color: #f8f9fa;
    border-left: 5px solid #6b7280;
}
.blockquote-source p { font-size: 9.5pt; color: #4b5563; margin: 3px 0; }

.blockquote-note {
    background-color: #fffbeb;
    border-left: 5px solid #f59e0b;
}
.blockquote-note p { font-size: 10pt; margin: 4px 0; color: #78350f; }
.blockquote-note strong { color: #92400e; }

.blockquote-resolved {
    background-color: #f0fdf4;
    border-left: 5px solid #16a34a;
}
.blockquote-resolved p { font-size: 10pt; margin: 4px 0; color: #14532d; }
.blockquote-resolved strong { color: #15803d; }

.blockquote-default {
    background-color: #eff6ff;
    border-left: 5px solid #3b82f6;
}
.blockquote-default p, .blockquote-default li { font-size: 10pt; margin: 4px 0; color: #1e3a5f; }
.blockquote-default strong { color: #1a5276; }

.numbered-item { margin: 4px 0 4px 20px; padding-left: 5px; font-size: 10pt; }
.bullet-item { margin: 3px 0 3px 20px; padding-left: 5px; font-size: 10pt; position: relative; }
.bullet-item::before { content: "•"; position: absolute; left: -12px; color: #3A7BBF; font-weight: bold; }

.footer-text { font-size: 9pt; color: #888; margin: 2px 0; }
p { margin: 5px 0; }
strong { color: #1a5276; }
li { margin: 3px 0; padding-left: 4px; }
"""


def _render_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    html = "<table>\n<thead><tr>"
    for cell in rows[0]:
        cell = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cell)
        html += f"<th>{cell}</th>"
    html += "</tr></thead>\n<tbody>\n"
    for row in rows[1:]:
        html += "<tr>"
        for cell in row:
            cell = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cell)
            cell = re.sub(r"~~(.+?)~~", r"<s>\1</s>", cell)
            upper = cell.upper()
            if "POTENTIALLY OPEN" in upper:
                cell = f'<span class="status-potentially-open">{cell}</span>'
            elif (
                "OPEN" in upper
                and "POTENTIALLY" not in upper
                and "CLOSED" not in upper
                and "NOT ON" not in upper
            ):
                cell = f'<span class="status-open">{cell}</span>'
            elif "RECONVEYED" in upper or "CLOSED" in upper or "RESOLVED" in upper:
                cell = f'<span class="status-closed">{cell}</span>'
            elif "CRITICAL" in upper:
                cell = f'<span class="status-critical">{cell}</span>'
            elif "NOT ON SUBJECT" in upper or "DOES NOT" in upper:
                cell = f'<span class="status-not-subject">{cell}</span>'
            elif "DOCUMENT UNAVAILABLE" in upper or "UNKNOWN" in upper or "NOT DOWNLOADED" in upper:
                cell = f'<span class="status-unknown">{cell}</span>'
            html += f"<td>{cell}</td>"
        html += "</tr>\n"
    html += "</tbody></table>\n"
    return html


def markdown_to_html(markdown_content: str) -> str:
    lines = markdown_content.split("\n")
    html_parts: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []
    in_blockquote = False
    blockquote_lines: list[str] = []

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if in_table:
            html_parts.append(_render_table(table_rows))
            in_table = False
            table_rows = []

    def flush_blockquote() -> None:
        nonlocal in_blockquote, blockquote_lines
        if not in_blockquote:
            return
        content = "\n".join(blockquote_lines)
        css_class = "blockquote-default"
        upper = content.upper()
        if "CRITICAL" in upper or "REMAINING ISSUES" in upper:
            css_class = "blockquote-critical"
        elif "DISCLAIMER" in upper:
            css_class = "blockquote-disclaimer"
        elif "RECOMMENDATION" in upper or "EXAMINER'S" in upper:
            css_class = "blockquote-recommendations"
        elif "SOURCE DATA" in upper or "DOCUMENTS DOWNLOADED" in upper:
            css_class = "blockquote-source"
        elif "NOTE" in upper[:50] or "KEY FINDING" in upper:
            css_class = "blockquote-note"
        elif "RESOLVED" in upper:
            css_class = "blockquote-resolved"

        processed: list[str] = []
        for line in blockquote_lines:
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            line = re.sub(r"\*(.+?)\*", r"<em>\1</em>", line)
            if line.strip().startswith("- "):
                processed.append(f"<li>{line.strip()[2:]}</li>")
            else:
                processed.append(f"<p>{line}</p>")
        html_parts.append(f'<div class="{css_class}">{"".join(processed)}</div>')
        in_blockquote = False
        blockquote_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> ") or (stripped == ">" and in_blockquote):
            flush_table()
            if not in_blockquote:
                in_blockquote = True
                blockquote_lines = []
            blockquote_lines.append(stripped[2:] if stripped.startswith("> ") else "")
            continue
        if in_blockquote and stripped == "":
            blockquote_lines.append("")
            continue
        if in_blockquote:
            flush_blockquote()

        if stripped.startswith("# Abstractor Notes/Chain"):
            # The HTML wrapper already emits a single .page-header at the top of <body>.
            # Emitting a .page-break + duplicate header here forces a blank first page
            # in the PDF (page-break-before: always with no preceding content). Skip.
            flush_table()
            continue

        if stripped.startswith("# "):
            flush_table()
            title = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped[2:])
            html_parts.append(f'<h1 class="main-title">{title}</h1>')
            continue
        if stripped.startswith("## "):
            flush_table()
            title = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped[3:])
            html_parts.append(f'<h2 class="section-title">{title}</h2>')
            continue
        if stripped.startswith("### "):
            flush_table()
            title = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped[4:])
            html_parts.append(f'<h3 class="subsection-title">{title}</h3>')
            continue
        if stripped.startswith("#### "):
            flush_table()
            title = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped[5:])
            html_parts.append(f'<h4 class="detail-title">{title}</h4>')
            continue
        if stripped == "---":
            flush_table()
            html_parts.append('<hr class="section-divider">')
            continue

        # Raw HTML page-break directives — pass through verbatim so weasyprint /
        # xhtml2pdf honor the page-break-before CSS rule.  Used by OnE §8
        # Exhibit A which must render on its own page (per
        # OnE_Report_System_Prompt.md).
        if stripped in (
            '<div class="page-break-before"></div>',
            "<div class=\"page-break-before\"></div>",
            '<div class="page-break"></div>',
        ):
            flush_table()
            html_parts.append(stripped)
            continue

        if "|" in stripped and stripped.startswith("|"):
            if re.match(r"\|[-:\s|]+\|", stripped):
                continue
            cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
            if cells:
                if not in_table:
                    in_table = True
                    table_rows = []
                table_rows.append(cells)
            continue

        if in_table:
            flush_table()

        if stripped.startswith("**") and ":**" in stripped:
            match = re.match(r"\*\*(.+?):\*\*\s*(.*)", stripped)
            if match:
                key, value = match.groups()
                value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
                html_parts.append(f'<p class="meta-line"><strong>{key}:</strong> {value}</p>')
                continue

        if re.match(r"^\d+\.", stripped):
            text = re.sub(r"^\d+\.\s*", "", stripped)
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            html_parts.append(f'<p class="numbered-item">{text}</p>')
            continue

        if stripped.startswith("- "):
            text = stripped[2:]
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
            html_parts.append(f'<p class="bullet-item">{text}</p>')
            continue

        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            html_parts.append(f'<p class="footer-text"><em>{stripped[1:-1]}</em></p>')
            continue

        if stripped:
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
            html_parts.append(f"<p>{text}</p>")

    flush_table()
    flush_blockquote()
    return "\n".join(html_parts)


def render_markdown_pdf(
    markdown_path: Path,
    pdf_path: Path,
    title: str,
    header_left: str,
    doc_type: str,
) -> Path:
    markdown_content = markdown_path.read_text(encoding="utf-8")
    # Render-time safety net: strip operator-only internal-memo blocks from every
    # client/engineering-facing artifact EXCEPT the Title Examination Notes (which
    # is the examiner doc and legitimately carries relocated memos). This only ever
    # removes marker-delimited operator memos — never a real examiner flag/warning.
    if doc_type != TITLE_DOC_TYPE:
        from titlepro.verification.report_sanitizer import strip_operator_memos

        markdown_content, _removed = strip_operator_memos(markdown_content)
    body_html = markdown_to_html(markdown_content)
    css = (CSS_TITLE if doc_type == TITLE_DOC_TYPE else CSS_RAW) + CSS_SHARED
    header_right = "LOGO" if doc_type == TITLE_DOC_TYPE else "CURE TitlePro"
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="page-header">
    <span class="header-left">{header_left}</span>
    <span class="header-right">{header_right}</span>
</div>
{body_html}
</body>
</html>"""
    html_path = pdf_path.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    try:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(pdf_path))
        return pdf_path
    except ImportError:
        try:
            from io import BytesIO
            from xhtml2pdf import pisa
        except ImportError as exc:
            raise RuntimeError(
                "PDF rendering requires either weasyprint or xhtml2pdf to be installed."
            ) from exc

        # xhtml2pdf cannot parse nested at-rules inside @page (e.g. @bottom-center).
        # Strip them before rendering so the CSS parser doesn't crash.
        xhtml2pdf_html = re.sub(r"@(?:bottom|top)-\w+\s*\{[^}]*\}", "", html)
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(xhtml2pdf_html, dest=pdf_buffer)
        if pisa_status.err:
            raise RuntimeError("xhtml2pdf failed to generate the PDF output.")
        pdf_path.write_bytes(pdf_buffer.getvalue())
        return pdf_path
