import os
from typing import List, Dict, Any
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors

class ReportFormatter:
    @staticmethod
    def generate_markdown(subject_name: str, vested: List[Dict], liens: List[Dict], doc_list: List[Dict], party_mapping: Dict[str, Any]) -> str:
        md = f"""
# Property Title Report for {subject_name}
_Generated: {datetime.now().strftime('%b %d, %Y %H:%M')}_

---

## 1. Vested Information
"""
        if vested:
            for idx, v in enumerate(vested, 1):
                md += f"### Vested Entry {idx}\n"
                for k, val in v.items():
                    md += f"- **{k.title().replace('_', ' ')}**: {val}\n"
        else:
            md += '> No vested information found.\n'
        md += "\n---\n\n## 2. Lien Attributions\n"
        if liens:
            for idx, l in enumerate(liens, 1):
                md += f"### Lien Entry {idx}\n"
                for k, val in l.items():
                    md += f"- **{k.title().replace('_', ' ')}**: {val}\n"
        else:
            md += '> No liens found.\n'
        md += "\n---\n\n## 3. Deduplicated Document List\n"
        if doc_list:
            md += '| Doc ID | Title | Type | Date |\n|---|---|---|---|\n'
            for d in doc_list:
                md += f"| {d.get('doc_id', '')} | {d.get('title', '')} | {d.get('type', '')} | {d.get('date', '')} |\n"
        else:
            md += '> No documents.\n'
        md += "\n---\n\n## 4. Party Mapping\n"
        if party_mapping:
            for party, attributes in party_mapping.items():
                md += f"- **{party}**:\n"
                if isinstance(attributes, dict):
                    for k, v in attributes.items():
                        md += f"    - {k}: {v}\n"
                else:
                    md += f"    - {attributes}\n"
        else:
            md += '> No party mapping data.\n'
        return md

    @staticmethod
    def generate_pdf(filepath: str, subject_name: str, vested: List[Dict], liens: List[Dict], doc_list: List[Dict], party_mapping: Dict[str, Any]):
        doc = SimpleDocTemplate(filepath, pagesize=LETTER, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        story = []
        styles = getSampleStyleSheet()
        header_style = ParagraphStyle('Header', parent=styles['Heading1'], fontSize=18, spaceAfter=12)
        section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#0d3758'), spaceBefore=12, spaceAfter=6)
        bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontName='Helvetica-Bold')
        normal_style = styles['Normal']

        # Title
        story.append(Paragraph(f"Property Title Report for {subject_name}", header_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%b %d, %Y %H:%M')}", styles['Italic']))
        story.append(Spacer(1, 12))
        story.append(Paragraph('<hr width="100%" color="#C0C0C0"/>', normal_style))

        # Vested
        story.append(Paragraph('1. Vested Information', section_style))
        if vested:
            for idx, v in enumerate(vested, 1):
                story.append(Paragraph(f"<b>Vested Entry {idx}</b>", bold_style))
                for k, val in v.items():
                    story.append(Paragraph(f"<b>{k.title().replace('_', ' ')}:</b> {val}", normal_style))
                story.append(Spacer(1, 6))
        else:
            story.append(Paragraph('No vested information found.', normal_style))
        story.append(Spacer(1, 12))

        # Liens
        story.append(Paragraph('2. Lien Attributions', section_style))
        if liens:
            for idx, l in enumerate(liens, 1):
                story.append(Paragraph(f"<b>Lien Entry {idx}</b>", bold_style))
                for k, val in l.items():
                    story.append(Paragraph(f"<b>{k.title().replace('_', ' ')}:</b> {val}", normal_style))
                story.append(Spacer(1, 6))
        else:
            story.append(Paragraph('No liens found.', normal_style))
        story.append(Spacer(1, 12))

        # Docs
        story.append(Paragraph('3. Deduplicated Document List', section_style))
        if doc_list:
            table_data = [["Doc ID", "Title", "Type", "Date"]]
            for d in doc_list:
                table_data.append([
                    d.get('doc_id', ''), d.get('title', ''), d.get('type', ''), d.get('date', '')
                ])
            t = Table(table_data, hAlign='LEFT', colWidths=[70, 170, 60, 60])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0d3758')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 11),
                ('INNERGRID', (0,0), (-1,-1), 0.25, colors.gray),
                ('BOX', (0,0), (-1,-1), 0.5, colors.black),
                ('ROWBACKGROUNDS', (1,0), (-1,-1), [colors.whitesmoke, colors.lightgrey]),
                ('ALIGN', (0,0), (-1,-1), 'LEFT')
            ]))
            story.append(t)
        else:
            story.append(Paragraph('No documents.', normal_style))
        story.append(Spacer(1, 12))

        # Party mapping
        story.append(Paragraph('4. Party Mapping', section_style))
        if party_mapping:
            for party, attributes in party_mapping.items():
                story.append(Paragraph(f"<b>{party}</b>", bold_style))
                if isinstance(attributes, dict):
                    for k, v in attributes.items():
                        story.append(Paragraph(f"- {k}: {v}", normal_style))
                else:
                    story.append(Paragraph(f"- {attributes}", normal_style))
                story.append(Spacer(1, 4))
        else:
            story.append(Paragraph('No party mapping data.', normal_style))

        doc.build(story)


def generate_reports_for_subject(subject_id: str, subject_data: Dict[str, Any], output_dir: str):
    """
    subject_id: e.g. 'Smith John' or 'APN 123-456-78'
    subject_data: {
       'vested': [...],
       'liens': [...],
       'documents': [...],
       'party_mapping': {...}
    }
    output_dir: where to save reports
    """
    subject_name = subject_id
    vested = subject_data.get('vested', [])
    liens = subject_data.get('liens', [])
    docs = subject_data.get('documents', [])
    party_mapping = subject_data.get('party_mapping', {})

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    md_content = ReportFormatter.generate_markdown(subject_name, vested, liens, docs, party_mapping)
    md_path = os.path.join(output_dir, f"{subject_id.replace(' ', '_')}_TitleReport.md")
    pdf_path = os.path.join(output_dir, f"{subject_id.replace(' ', '_')}_TitleReport.pdf")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    ReportFormatter.generate_pdf(pdf_path, subject_name, vested, liens, docs, party_mapping)
    return md_path, pdf_path
