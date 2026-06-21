#!/usr/bin/env python3
"""OCR PDFs to markdown files using PyMuPDF + pytesseract."""

import sys
import os
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io

PDF_DIR = os.path.dirname(os.path.abspath(__file__))
PDFS = [
    "B48488243.pdf",
    "B48488388.pdf",
    "B48488594.pdf",
    "B48488755.pdf",
]

def ocr_pdf(pdf_path):
    """Extract text from a scanned PDF using OCR."""
    doc = fitz.open(pdf_path)
    pages_text = []
    for i, page in enumerate(doc):
        # First try native text extraction
        text = page.get_text().strip()
        if len(text) > 50:
            pages_text.append((i + 1, text))
            continue
        # Fall back to OCR
        mat = fitz.Matrix(300 / 72, 300 / 72)  # 300 DPI
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img)
        pages_text.append((i + 1, text.strip()))
    doc.close()
    return pages_text

def main():
    for pdf_name in PDFS:
        pdf_path = os.path.join(PDF_DIR, pdf_name)
        if not os.path.exists(pdf_path):
            print(f"SKIP: {pdf_name} not found")
            continue

        base = os.path.splitext(pdf_name)[0]
        md_path = os.path.join(PDF_DIR, f"{base}_extracted.md")

        print(f"Processing {pdf_name}...", end=" ", flush=True)
        pages = ocr_pdf(pdf_path)

        with open(md_path, "w") as f:
            f.write(f"# DOCUMENT: {pdf_name}\n\n")
            for page_num, text in pages:
                f.write(f"## Page {page_num}\n")
                f.write(text + "\n\n")

        print(f"Done → {base}_extracted.md ({len(pages)} pages)")

if __name__ == "__main__":
    main()
