#!/usr/bin/env python3
"""
Generate a professionally formatted PDF Title Examination Report from Markdown.
Matches the CURE UI report style.
"""

import sys
from pathlib import Path
from datetime import datetime
from io import BytesIO

def check_weasyprint():
    """Check if weasyprint is available, provide installation instructions if not."""
    try:
        from weasyprint import HTML, CSS
        return True
    except ImportError:
        print("ERROR: weasyprint is not installed.")
        print("Install it with: pip3 install weasyprint")
        print("On macOS, you may also need: brew install pango")
        return False

def markdown_to_styled_html(markdown_content: str, owner_name: str, property_address: str = "") -> str:
    """
    Convert markdown report to professionally styled HTML for PDF generation.
    Matches professional title report formatting standards.
    """
    import re

    # Parse markdown and convert to HTML
    lines = markdown_content.split('\n')
    html_parts = []

    in_table = False
    table_headers = []
    table_rows = []
    in_code_block = False

    def flush_table():
        nonlocal in_table, table_headers, table_rows
        if table_headers or table_rows:
            table_html = '<table class="report-table">\n'
            if table_headers:
                table_html += '<thead><tr>'
                for h in table_headers:
                    table_html += f'<th>{h}</th>'
                table_html += '</tr></thead>\n'
            table_html += '<tbody>\n'
            for row in table_rows:
                table_html += '<tr>'
                for cell in row:
                    table_html += f'<td>{cell}</td>'
                table_html += '</tr>\n'
            table_html += '</tbody></table>\n'
            html_parts.append(table_html)
        in_table = False
        table_headers = []
        table_rows = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            if in_table:
                flush_table()
            continue

        # Code blocks
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            html_parts.append(f'<pre class="code-block">{stripped}</pre>')
            continue

        # Headers
        if stripped.startswith('# '):
            if in_table: flush_table()
            html_parts.append(f'<h1 class="main-title">{stripped[2:]}</h1>')
            continue
        elif stripped.startswith('## '):
            if in_table: flush_table()
            html_parts.append(f'<h2 class="section-title">{stripped[3:]}</h2>')
            continue
        elif stripped.startswith('### '):
            if in_table: flush_table()
            html_parts.append(f'<h3 class="subsection-title">{stripped[4:]}</h3>')
            continue

        # Horizontal rules
        if stripped == '---':
            if in_table: flush_table()
            html_parts.append('<hr class="section-divider">')
            continue

        # Tables
        if '|' in stripped:
            cells = [c.strip() for c in stripped.split('|')[1:-1]]

            # Check if it's a separator row (---|---|---)
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue

            if not in_table:
                in_table = True
                table_headers = cells
            else:
                table_rows.append(cells)
            continue

        # Bold text
        stripped = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', stripped)

        # Lists
        if stripped.startswith('- '):
            if in_table: flush_table()
            html_parts.append(f'<li>{stripped[2:]}</li>')
            continue

        if re.match(r'^\d+\.\s', stripped):
            if in_table: flush_table()
            text = re.sub(r'^\d+\.\s', '', stripped)
            html_parts.append(f'<li>{text}</li>')
            continue

        # Regular paragraphs
        if in_table: flush_table()
        html_parts.append(f'<p>{stripped}</p>')

    # Flush any remaining table
    if in_table:
        flush_table()

    body_content = '\n'.join(html_parts)

    # Professional CSS styling matching CURE UI
    css = """
    @page {
        size: letter;
        margin: 0.75in;
        @top-center {
            content: "Title Examination Report";
            font-size: 9pt;
            color: #666;
        }
        @bottom-center {
            content: "Page " counter(page) " of " counter(pages);
            font-size: 9pt;
            color: #666;
        }
        @bottom-right {
            content: "Generated: """ + datetime.now().strftime("%m/%d/%Y") + """";
            font-size: 8pt;
            color: #999;
        }
    }

    body {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 10pt;
        line-height: 1.4;
        color: #333;
        margin: 0;
        padding: 0;
    }

    .header-banner {
        background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 100%);
        color: white;
        padding: 20px 25px;
        margin: -0.75in -0.75in 20px -0.75in;
        width: calc(100% + 1.5in);
    }

    .header-banner h1 {
        margin: 0;
        font-size: 22pt;
        font-weight: 600;
        letter-spacing: 0.5px;
    }

    .header-banner .subtitle {
        margin: 5px 0 0 0;
        font-size: 11pt;
        opacity: 0.9;
    }

    .report-meta {
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 4px;
        padding: 12px 15px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        flex-wrap: wrap;
    }

    .report-meta-item {
        margin-right: 20px;
    }

    .report-meta-label {
        font-size: 8pt;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .report-meta-value {
        font-size: 10pt;
        font-weight: 600;
        color: #333;
    }

    h1.main-title {
        display: none; /* Hidden since we have banner */
    }

    h2.section-title {
        color: #1e3a5f;
        font-size: 14pt;
        font-weight: 600;
        border-bottom: 2px solid #2c5282;
        padding-bottom: 5px;
        margin-top: 25px;
        margin-bottom: 12px;
        page-break-after: avoid;
    }

    h3.subsection-title {
        color: #2c5282;
        font-size: 11pt;
        font-weight: 600;
        margin-top: 18px;
        margin-bottom: 8px;
        page-break-after: avoid;
    }

    .section-divider {
        border: none;
        border-top: 1px solid #dee2e6;
        margin: 15px 0;
    }

    table.report-table {
        width: 100%;
        border-collapse: collapse;
        margin: 10px 0 15px 0;
        font-size: 9pt;
        page-break-inside: avoid;
    }

    table.report-table th {
        background: #2c5282;
        color: white;
        font-weight: 600;
        text-align: left;
        padding: 8px 10px;
        border: 1px solid #1e3a5f;
    }

    table.report-table td {
        padding: 6px 10px;
        border: 1px solid #dee2e6;
        vertical-align: top;
    }

    table.report-table tr:nth-child(even) {
        background: #f8f9fa;
    }

    table.report-table tr:hover {
        background: #e9ecef;
    }

    p {
        margin: 8px 0;
        text-align: justify;
    }

    li {
        margin: 4px 0;
        margin-left: 20px;
    }

    strong {
        color: #1e3a5f;
    }

    .code-block {
        background: #f4f4f4;
        border: 1px solid #ddd;
        border-radius: 3px;
        padding: 8px 12px;
        font-family: 'Courier New', monospace;
        font-size: 9pt;
        overflow-x: auto;
    }

    .status-clear {
        color: #28a745;
        font-weight: bold;
    }

    .status-warning {
        color: #ffc107;
        font-weight: bold;
    }

    .status-alert {
        color: #dc3545;
        font-weight: bold;
    }

    .footer-disclaimer {
        margin-top: 30px;
        padding: 15px;
        background: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 4px;
        font-size: 8pt;
        color: #856404;
    }

    .footer-disclaimer h4 {
        margin: 0 0 8px 0;
        font-size: 9pt;
    }

    /* [REPORT_FORMAT_DEBUGLOGS] New CSS classes for report format updates */

    /* Party header styling for liens section */
    .party-header {
        font-size: 12pt;
        font-weight: bold;
        color: #1e3a5f;
        margin-top: 16px;
        margin-bottom: 8px;
        padding: 6px 10px;
        background-color: #e8f4f8;
        border-left: 4px solid #2c5282;
        border-radius: 2px;
    }

    /* Open lien styling - red/warning */
    .lien-open {
        color: #dc3545;
        font-weight: bold;
        background-color: #f8d7da;
        padding: 2px 6px;
        border-radius: 3px;
    }

    /* Released lien styling - green */
    .lien-released {
        color: #28a745;
        font-weight: bold;
        background-color: #d4edda;
        padding: 2px 6px;
        border-radius: 3px;
    }

    /* Discovered name highlight */
    .discovered-name {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        padding: 2px 6px;
        border-radius: 3px;
        font-style: italic;
    }

    /* Title Vested As section styling */
    .vesting-section {
        background-color: #e8f4f8;
        border: 2px solid #2c5282;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 16px 0;
        font-size: 11pt;
    }

    .vesting-section strong {
        font-size: 12pt;
        color: #1e3a5f;
    }

    /* Search summary section styling */
    .search-summary {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 4px;
        padding: 12px 16px;
        margin: 16px 0;
        font-size: 10pt;
    }

    .search-summary strong {
        color: #1e3a5f;
    }

    /* Documents examined table styling */
    .documents-examined-table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 9pt;
    }

    .documents-examined-table th {
        background-color: #1e3a5f;
        color: white;
        padding: 8px 10px;
        text-align: left;
    }

    .documents-examined-table td {
        padding: 6px 10px;
        border-bottom: 1px solid #dee2e6;
    }

    .documents-examined-table tr:nth-child(even) td {
        background-color: #f8f9fa;
    }

    /* Found Via column styling */
    .found-via {
        font-size: 8pt;
        color: #666;
        font-style: italic;
    }
    """

    # Build complete HTML document
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Two Party Title Examination Report - {owner_name}</title>
    <style>
    {css}
    </style>
</head>
<body>
    <div class="header-banner">
        <h1>TWO PARTY TITLE EXAMINATION REPORT</h1>
        <div class="subtitle">Amador County, California</div>
    </div>

    <div class="report-meta">
        <div class="report-meta-item">
            <div class="report-meta-label">Property Owner</div>
            <div class="report-meta-value">{owner_name.replace('_', ' ')}</div>
        </div>
        <div class="report-meta-item">
            <div class="report-meta-label">Property Address</div>
            <div class="report-meta-value">{property_address or "19301 Shake Ridge Road, Volcano, CA 95689"}</div>
        </div>
        <div class="report-meta-item">
            <div class="report-meta-label">Report Date</div>
            <div class="report-meta-value">{datetime.now().strftime("%B %d, %Y")}</div>
        </div>
        <div class="report-meta-item">
            <div class="report-meta-label">APN</div>
            <div class="report-meta-value">021-390-003-000</div>
        </div>
    </div>

    {body_content}

    <div class="footer-disclaimer">
        <h4>DISCLAIMER</h4>
        <p>This report is for informational purposes only and does not constitute a commitment to insure title.
        The information contained herein has been obtained from public records and is believed to be accurate
        but is not warranted. A full title insurance commitment should be obtained for any real estate transaction.</p>
    </div>
</body>
</html>
"""
    return html


def generate_pdf(md_path: Path, output_path: Path = None):
    """Generate PDF from markdown file."""
    from weasyprint import HTML

    if not md_path.exists():
        print(f"ERROR: Markdown file not found: {md_path}")
        return False

    # Read markdown content
    markdown_content = md_path.read_text()

    # Extract owner name from path
    owner_name = md_path.parent.name

    # Convert to styled HTML
    html_content = markdown_to_styled_html(markdown_content, owner_name)

    # Determine output path
    if output_path is None:
        output_path = md_path.parent / f"Two_Party_Title_Examination_{owner_name}_{datetime.now().strftime('%Y%m%d')}.pdf"

    # Generate PDF
    print(f"Generating PDF report...")
    print(f"  Source: {md_path}")
    print(f"  Output: {output_path}")

    try:
        HTML(string=html_content).write_pdf(str(output_path))
        print(f"\n✓ PDF generated successfully: {output_path}")
        print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")
        return True
    except Exception as e:
        print(f"ERROR: PDF generation failed: {e}")
        return False


def main():
    # Check dependencies
    if not check_weasyprint():
        sys.exit(1)

    # Default paths
    base_dir = Path(__file__).parent
    from titlepro import DOWNLOAD_DIR
    default_md = DOWNLOAD_DIR / "ROSENKRANS_TERRY_VALERIE" / "TWO_PARTY_TITLE_EXAMINATION_REPORT.md"

    # Get input path from command line or use default
    if len(sys.argv) > 1:
        md_path = Path(sys.argv[1])
    else:
        md_path = default_md

    # Get output path from command line
    output_path = None
    if len(sys.argv) > 2:
        output_path = Path(sys.argv[2])

    # Generate PDF
    success = generate_pdf(md_path, output_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
