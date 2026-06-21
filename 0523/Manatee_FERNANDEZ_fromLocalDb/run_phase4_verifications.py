#!/usr/bin/env python3
"""Phase 4 verification pipeline for Manatee FERNANDEZ subject.

1. Extract text from each downloaded PDF (pdfplumber direct extraction).
2. Run subject_address_verifier per doc against 4837 SABAL HARBOUR DR.
3. Run released_mortgage_linker over the corpus.
4. Emit phase1_verifications.json sidecar.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pdfplumber

CASE_DIR = Path("/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/0523/Manatee_FERNANDEZ_fromLocalDb")
DOWNLOAD_DIR = CASE_DIR / "downloads"
TEXT_DIR = CASE_DIR / "extracted_texts"
TEXT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/src")
from titlepro.verification.subject_address_verifier import (
    verify_subject_address,
    extract_subject_address_from_text,
)
from titlepro.verification.released_mortgage_linker import classify_mortgages

SUBJECT_ADDRESS = "4837 SABAL HARBOUR DR, BRADENTON, FL"
SUBJECT_HINT = "SABAL HARBOUR"


def extract_pdf_text(pdf_path: Path) -> str:
    """pdfplumber-based text extraction. Returns '' on failure."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
            return "\n\n".join(pages)
    except Exception as exc:
        print(f"[!] extract failed for {pdf_path.name}: {exc}")
        return ""


def main() -> int:
    with (CASE_DIR / "candidate_documents.json").open("r") as fh:
        rows = json.load(fh)
    by_inst = {r["instrument"]: r for r in rows}

    pdf_files = sorted(DOWNLOAD_DIR.glob("MCCCC-*.pdf"))
    print(f"[*] Processing {len(pdf_files)} PDFs")

    doc_records = []
    extracted_texts = {}

    for pdf_path in pdf_files:
        # parse instrument from filename: MCCCC-<instrument>-<slug>.pdf
        stem = pdf_path.stem
        parts = stem.split("-", 2)
        if len(parts) < 3:
            continue
        instrument = parts[1]
        slug = parts[2]
        meta = by_inst.get(instrument, {})

        print(f"[>] {instrument} ({meta.get('doc_type', '?')})")
        text_out = TEXT_DIR / f"{instrument}.txt"
        # Prefer existing OCR text; only fall back to pdfplumber if .txt is empty
        if text_out.exists() and text_out.stat().st_size > 100:
            text = text_out.read_text(encoding="utf-8")
        else:
            text = extract_pdf_text(pdf_path)
            text_out.write_text(text, encoding="utf-8")

        extracted_texts[instrument] = text

        # Subject address verification (Directive #4)
        addr_result = None
        extracted_addr = None
        if text.strip():
            extracted_addr = extract_subject_address_from_text(
                text, subject_hint=SUBJECT_HINT
            )
            if extracted_addr:
                match = verify_subject_address(extracted_addr, SUBJECT_ADDRESS)
                addr_result = {
                    "extracted": extracted_addr,
                    "status": match.status,
                    "similarity": match.similarity,
                    "matched_components": match.matched_components,
                    "evidence": match.evidence,
                }

        doc_records.append({
            "instrument": instrument,
            "slug": slug,
            "doc_type": meta.get("doc_type"),
            "record_date": meta.get("record_date"),
            "book": meta.get("book"),
            "page": meta.get("page"),
            "grantors": meta.get("grantors"),
            "grantees": meta.get("grantees"),
            "legal": meta.get("legal"),
            "pages_count": meta.get("pages_count"),
            "text_chars": len(text),
            "address_verification": addr_result,
        })

    # Released mortgage linker (Directive #6)
    # Build the documents list in the format the linker expects.
    docs_for_linker = []
    for r in doc_records:
        docs_for_linker.append({
            "doc_number": r["instrument"],
            "doc_type": (r["doc_type"] or "").upper(),
            "grantors": r["grantors"] or "",
            "grantees": r["grantees"] or "",
            "legal_description": r["legal"] or "",
            "recorded_date": r["record_date"] or "",
        })

    texts_for_linker = {inst: text for inst, text in extracted_texts.items()}

    try:
        mortgage_classifications = classify_mortgages(docs_for_linker, texts_for_linker)
        mortgages_serialized = {k: v.to_dict() for k, v in mortgage_classifications.items()}
    except Exception as exc:
        print(f"[!] released_mortgage_linker failed: {exc}")
        mortgages_serialized = {"_error": str(exc)}

    sidecar = {
        "subject": {
            "address": SUBJECT_ADDRESS,
            "apn": "1697719559",
            "owners": ["FERNANDEZ PABLO", "ROZANES DANIELA"],
        },
        "documents": doc_records,
        "mortgage_classifications": mortgages_serialized,
    }
    out = CASE_DIR / "phase1_verifications.json"
    out.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
    print(f"[+] Wrote {out}")

    # Print summary table
    print("\n=== Subject-address verification summary ===")
    for r in doc_records:
        av = r["address_verification"]
        if av is None:
            print(f"  {r['instrument']:15s}  {r['doc_type']:25s}  NO_TEXT_OR_NO_ADDRESS")
        else:
            print(f"  {r['instrument']:15s}  {r['doc_type']:25s}  {av['status']:10s}  {av['similarity']:.2f}  '{av['extracted']}'")

    print("\n=== Mortgage classifications ===")
    if isinstance(mortgages_serialized, dict) and "_error" not in mortgages_serialized:
        for inst, cls in mortgages_serialized.items():
            print(f"  {inst}: {cls['status']}  releases={[r['satisfaction_doc_number'] for r in cls['release_chain']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
