#!/usr/bin/env python3
"""OCR all downloaded PDFs to extracted_texts/<instrument>.txt.

Uses pdftoppm (poppler) → tesseract. Parallel via ThreadPoolExecutor.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CASE_DIR = Path("/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/0523/Manatee_FERNANDEZ_fromLocalDb")
PDF_DIR = CASE_DIR / "downloads"
OUT_DIR = CASE_DIR / "extracted_texts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def ocr_pdf(pdf: Path) -> tuple[str, int, int]:
    """Return (instrument, pages, bytes)."""
    stem = pdf.stem  # MCCCC-<instrument>-<slug>
    parts = stem.split("-", 2)
    instrument = parts[1]
    out = OUT_DIR / f"{instrument}.txt"

    with tempfile.TemporaryDirectory(prefix=f"ocr_{instrument}_") as tmp:
        tmp_dir = Path(tmp)
        # Convert to PNGs @ 250 dpi
        subprocess.run(
            ["pdftoppm", "-r", "250", "-png", str(pdf), str(tmp_dir / "p")],
            check=True,
        )
        pngs = sorted(tmp_dir.glob("p-*.png"))
        text_parts = []
        for i, png in enumerate(pngs, start=1):
            result = subprocess.run(
                ["tesseract", str(png), "-", "-l", "eng"],
                check=False,
                capture_output=True,
                text=True,
            )
            text_parts.append(f"=== PAGE {i} ===\n{result.stdout}\n")
        full_text = "\n".join(text_parts)
        out.write_text(full_text, encoding="utf-8")
    return instrument, len(pngs), len(full_text)


def main() -> int:
    pdfs = sorted(PDF_DIR.glob("MCCCC-*.pdf"))
    print(f"[*] OCR'ing {len(pdfs)} PDFs in parallel (max 4 workers)...")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(ocr_pdf, pdf): pdf for pdf in pdfs}
        for fut in as_completed(futures):
            pdf = futures[fut]
            try:
                instrument, pages, nbytes = fut.result()
                print(f"  [+] {instrument}: {pages} page(s), {nbytes:,} chars")
                results.append((instrument, pages, nbytes))
            except Exception as exc:
                print(f"  [!] {pdf.name} failed: {exc}")
    print("=== OCR complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
