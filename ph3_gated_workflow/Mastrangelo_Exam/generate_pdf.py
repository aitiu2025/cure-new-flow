#!/usr/bin/env python3
"""Generate a professional PDF from Abstractor Notes markdown using WeasyPrint."""

import re
import sys
from pathlib import Path

def render_table(rows):
    if not rows:
        return ""
    html = '<table>\n<thead><tr>'
    for cell in rows[0]:
        cell = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', cell)
        html += f'<th>{cell}</th>'
    html += '</tr></thead>\n<tbody>\n'
    for row in rows[1:]:
        html += '<tr>'
        for cell in row:
            cell = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', cell)
            # Highlight OPEN/CRITICAL status cells
            if 'OPEN' in cell and 'POTENTIALLY' not in cell:
                cell = f'<span class="status-open">{cell}</span>'
            elif 'POTENTIALLY OPEN' in cell:
                cell = f'<span class="status-potentially-open">{cell}</span>'
            elif 'RECONVEYED' in cell or 'CLOSED' in cell:
                cell = f'<span class="status-closed">{cell}</span>'
            elif 'CRITICAL' in cell:
                cell = f'<span class="status-critical">{cell}</span>'
            html += f'<td>{cell}</td>'
        html += '</tr>\n'
    html += '</tbody></table>\n'
    return html

def markdown_to_html(md_content):
    lines = md_content.split('\n')
    html_parts = []
    in_table = False
    table_rows = []
    in_blockquote = False
    blockquote_lines = []
    blockquote_type = "default"

    def flush_table():
        nonlocal in_table, table_rows
        if in_table:
            html_parts.append(render_table(table_rows))
            in_table = False
            table_rows = []

    def flush_blockquote():
        nonlocal in_blockquote, blockquote_lines, blockquote_type
        if in_blockquote:
            content = '\n'.join(blockquote_lines)
            # Detect blockquote type
            css_class = "blockquote-default"
            if 'CRITICAL ISSUES' in content.upper():
                css_class = "blockquote-critical"
            elif 'DISCLAIMER' in content.upper():
                css_class = "blockquote-disclaimer"
            elif 'RECOMMENDATIONS' in content.upper() or "EXAMINER'S" in content.upper():
                css_class = "blockquote-recommendations"
            elif 'Source Data' in content:
                css_class = "blockquote-source"

            # Process content
            processed = []
            for bline in blockquote_lines:
                bline = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', bline)
                bline = re.sub(r'\*(.+?)\*', r'<em>\1</em>', bline)
                if bline.strip().startswith('- '):
                    bline = f'<li>{bline.strip()[2:]}</li>'
                elif bline.strip().startswith(r'\d'):
                    bline = f'<li>{re.sub(r"^d+.s*", "", bline.strip())}</li>'
                else:
                    bline = f'<p>{bline}</p>'
                processed.append(bline)

            html_parts.append(f'<div class="{css_class}">{"".join(processed)}</div>')
            in_blockquote = False
            blockquote_lines = []

    for line in lines:
        stripped = line.strip()

        # Blockquote handling
        if stripped.startswith('> ') or (stripped == '>' and in_blockquote):
            flush_table()
            if not in_blockquote:
                in_blockquote = True
                blockquote_lines = []
            text = stripped[2:] if stripped.startswith('> ') else ''
            blockquote_lines.append(text)
            continue
        elif in_blockquote and stripped == '':
            # Empty line might continue blockquote or end it
            blockquote_lines.append('')
            continue
        elif in_blockquote:
            flush_blockquote()

        # Page break header: "# Abstractor Notes/Chain ... LOGO"
        if stripped.startswith('# Abstractor Notes/Chain'):
            flush_table()
            html_parts.append('<div class="page-break"></div>')
            html_parts.append('<div class="page-header"><span class="header-left">Abstractor Notes/Chain</span><span class="header-right">CURE TitlePro</span></div>')
            continue

        # H1
        if stripped.startswith('# ') and not stripped.startswith('# Abstractor'):
            flush_table()
            title = stripped[2:]
            title = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', title)
            html_parts.append(f'<h1 class="main-title">{title}</h1>')
            continue

        # H2
        if stripped.startswith('## '):
            flush_table()
            section = stripped[3:]
            section = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', section)
            html_parts.append(f'<h2 class="section-title">{section}</h2>')
            continue

        # H3
        if stripped.startswith('### '):
            flush_table()
            sub = stripped[4:]
            sub = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', sub)
            html_parts.append(f'<h3 class="subsection-title">{sub}</h3>')
            continue

        # HR
        if stripped == '---':
            flush_table()
            html_parts.append('<hr class="section-divider">')
            continue

        # Table rows
        if '|' in stripped and stripped.startswith('|'):
            if re.match(r'\|[-:\s|]+\|', stripped):
                continue
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if cells:
                if not in_table:
                    in_table = True
                    table_rows = []
                table_rows.append(cells)
            continue

        if in_table:
            flush_table()

        # Bold metadata lines
        if stripped.startswith('**') and ':**' in stripped:
            match = re.match(r'\*\*(.+?):\*\*\s*(.*)', stripped)
            if match:
                key, value = match.groups()
                value = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', value)
                html_parts.append(f'<p class="meta-line"><strong>{key}:</strong> {value}</p>')
            continue

        # Numbered list
        if re.match(r'^\d+\.', stripped):
            text = re.sub(r'^\d+\.\s*', '', stripped)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            html_parts.append(f'<p class="numbered-item">{text}</p>')
            continue

        # Bullet list
        if stripped.startswith('- '):
            text = stripped[2:]
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            html_parts.append(f'<p class="bullet-item">{text}</p>')
            continue

        # Italic footer
        if stripped.startswith('*') and stripped.endswith('*') and not stripped.startswith('**'):
            text = stripped[1:-1]
            html_parts.append(f'<p class="footer-text"><em>{text}</em></p>')
            continue

        # Regular paragraph
        if stripped:
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            html_parts.append(f'<p>{text}</p>')

    flush_table()
    flush_blockquote()

    body = '\n'.join(html_parts)

    css = '''
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

    .page-break {
        page-break-before: always;
        margin: 0;
        padding: 0;
        height: 0;
    }

    .page-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #2980b9;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }
    .header-left {
        font-size: 14pt;
        font-weight: bold;
        color: #1a5276;
    }
    .header-right {
        font-size: 11pt;
        font-weight: bold;
        color: #2980b9;
        font-style: italic;
    }

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

    .meta-line {
        margin: 3px 0;
        font-size: 10pt;
        color: #444;
    }
    .meta-line strong { color: #1a5276; }

    .section-title {
        font-size: 12pt;
        font-weight: bold;
        margin-top: 20px;
        margin-bottom: 10px;
        color: #fff;
        text-transform: uppercase;
        background-color: #2980b9;
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
        border-left: 4px solid #2980b9;
        padding-left: 10px;
        page-break-after: avoid;
    }

    .section-divider {
        border: none;
        border-top: 1px solid #ddd;
        margin: 14px 0;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0 16px 0;
        font-size: 9pt;
        page-break-inside: auto;
    }
    th {
        background-color: #2980b9;
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
    tr:nth-child(even) td { background-color: #f8f9fa; }
    tr:hover td { background-color: #eef5fb; }

    .status-open {
        color: #c0392b;
        font-weight: bold;
    }
    .status-potentially-open {
        color: #e67e22;
        font-weight: bold;
    }
    .status-closed {
        color: #27ae60;
        font-weight: bold;
    }
    .status-critical {
        color: #c0392b;
        font-weight: bold;
    }

    /* Blockquotes */
    .blockquote-critical {
        background-color: #fdf2f2;
        border-left: 5px solid #e74c3c;
        padding: 12px 16px;
        margin: 14px 0;
        border-radius: 0 4px 4px 0;
    }
    .blockquote-critical p, .blockquote-critical li {
        font-size: 10pt;
        margin: 4px 0;
        color: #5a1a1a;
    }
    .blockquote-critical strong { color: #c0392b; }

    .blockquote-disclaimer {
        background-color: #fefce8;
        border-left: 5px solid #f59e0b;
        padding: 12px 16px;
        margin: 14px 0;
        border-radius: 0 4px 4px 0;
    }
    .blockquote-disclaimer p {
        font-size: 9.5pt;
        color: #78350f;
        margin: 4px 0;
    }

    .blockquote-recommendations {
        background-color: #f0fdf4;
        border-left: 5px solid #22c55e;
        padding: 12px 16px;
        margin: 14px 0;
        border-radius: 0 4px 4px 0;
    }
    .blockquote-recommendations p, .blockquote-recommendations li {
        font-size: 10pt;
        margin: 4px 0;
        color: #14532d;
    }
    .blockquote-recommendations strong { color: #15803d; }

    .blockquote-source {
        background-color: #f8f9fa;
        border-left: 5px solid #6b7280;
        padding: 10px 16px;
        margin: 14px 0;
    }
    .blockquote-source p {
        font-size: 9.5pt;
        color: #4b5563;
        margin: 3px 0;
    }

    .blockquote-default {
        background-color: #eff6ff;
        border-left: 5px solid #3b82f6;
        padding: 12px 16px;
        margin: 14px 0;
        border-radius: 0 4px 4px 0;
    }
    .blockquote-default p, .blockquote-default li {
        font-size: 10pt;
        margin: 4px 0;
        color: #1e3a5f;
    }
    .blockquote-default strong { color: #1a5276; }

    .numbered-item {
        margin: 4px 0 4px 20px;
        padding-left: 5px;
        font-size: 10pt;
    }
    .numbered-item::before {
        color: #2980b9;
        font-weight: bold;
    }

    .bullet-item {
        margin: 3px 0 3px 20px;
        padding-left: 5px;
        font-size: 10pt;
        position: relative;
    }
    .bullet-item::before {
        content: "•";
        position: absolute;
        left: -12px;
        color: #2980b9;
        font-weight: bold;
    }

    .footer-text {
        font-size: 9pt;
        color: #888;
        margin: 2px 0;
    }

    p { margin: 5px 0; }

    strong { color: #1a5276; }

    li {
        margin: 3px 0;
        padding-left: 4px;
    }
    '''

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Abstractor Notes — MASTRANGELO</title>
<style>{css}</style>
</head>
<body>
<div class="page-header">
    <span class="header-left">Abstractor Notes/Chain</span>
    <span class="header-right">CURE TitlePro</span>
</div>
{body}
</body>
</html>'''
    return html


def main():
    md_path = Path("/Users/ag/Downloads/0414_CA_Exams/MASTRANGELO_ANTHONY/RAW_Abstractor_Notes_Mastrangelo.md")
    pdf_path = Path("/Users/ag/Downloads/0414_CA_Exams/MASTRANGELO_ANTHONY/Abstractor_Notes_Mastrangelo.pdf")

    print(f"Reading: {md_path}")
    md_content = md_path.read_text()

    print("Converting markdown to styled HTML...")
    html_content = markdown_to_html(md_content)

    # Save HTML for debugging
    html_path = md_path.with_suffix('.html')
    html_path.write_text(html_content)
    print(f"HTML saved: {html_path}")

    print("Generating PDF with WeasyPrint...")
    from weasyprint import HTML
    HTML(string=html_content).write_pdf(str(pdf_path))
    print(f"PDF saved: {pdf_path}")
    print(f"Size: {pdf_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
