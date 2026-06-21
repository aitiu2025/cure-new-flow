#!/usr/bin/env python3
"""
Download Group A (subject parcel) + Group C (critical cloud) documents
for FERNANDEZ/ROZANES at 4837 SABAL HARBOUR DR, BRADENTON.

All doc_ids sourced from local manatee_cache.db candidate_documents.json.
Uses query_manatee_clerk.download_pdf() for HTTP session-aware download.
"""
import json
import os
import sys
import time
from pathlib import Path

# Import the proven downloader from sibling project
TOOLS_DIR = "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/US_Counties_Data/FL/AIProjects/Manatee_Title_Abstractor_Tools"
sys.path.insert(0, TOOLS_DIR)
from query_manatee_clerk import download_pdf  # noqa: E402

CASE_DIR = Path("/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/0523/Manatee_FERNANDEZ_fromLocalDb")
CANDIDATES_JSON = CASE_DIR / "candidate_documents.json"
DOWNLOAD_DIR = CASE_DIR / "downloads"

# Group A (14 subject-parcel docs) + Group C (1 critical cloud).
# Group B (8 different-parcel docs) intentionally excluded per user decision.
INCLUDE_INSTRUMENTS = {
    # Group A — Subject parcel (Lot 141 Sabal Harbour Phase V)
    "201541003454395": "A1-Toivanen-NOC-2015",
    "201841020434":    "A2-VESTING-DEED-Toivanen-to-Fernandez-2018",
    "201841020435":    "A3-Purchase-Mortgage-Fairway-2018",
    "202041027841":    "A4-Affidavit-2020",
    "202041027842":    "A5-Termination-of-2019-NOC",
    "201941092835":    "A6-NOC-FERNADEZ-misspelled-2019",
    "202041027843":    "A7-Suncoast-HELOC-2020",
    "202041043360":    "A8-Satisfaction-of-2018-Fairway-MTG",
    "202541032476":    "A9-NOC-Freedom-Forever-Solar-2025",
    "202541046441":    "A10-UCC-Solar-Mosaic-2025",
    "202641010612":    "A11-Solar-Affidavit-2026",
    "202641040260":    "A12-SouthState-Mortgage-2026-CURRENT-1st",
    "202641040261":    "A13-Subordination-of-Suncoast-HELOC-2026",
    "202641050708":    "A14-Termination-of-Solar-Mosaic-UCC-2026",
    # Group C — Critical cloud (identity unconfirmed)
    "202141142133":    "C1-DR-Judgment-FERNANDEZ-PABLO-C-2021",
}

REQUEST_DELAY_SEC = 1.5  # polite spacing to avoid rate limit


def main() -> int:
    with CANDIDATES_JSON.open("r", encoding="utf-8") as fh:
        rows = json.load(fh)
    by_instrument = {r["instrument"]: r for r in rows}

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    ok = 0
    skipped = 0
    failed = 0

    for instrument, slug in INCLUDE_INSTRUMENTS.items():
        rec = by_instrument.get(instrument)
        if rec is None:
            print(f"[!] Instrument {instrument} not found in candidate_documents.json — skipping")
            skipped += 1
            manifest.append({"instrument": instrument, "status": "NOT_IN_CACHE", "slug": slug})
            continue

        doc_id = rec.get("doc_id") or ""
        doc_type = rec.get("doc_type", "")
        rec_date = rec.get("record_date", "")
        pages = rec.get("pages_count", "")

        if not doc_id or doc_id == "N/A":
            print(f"[!] {instrument} ({slug}) has doc_id={doc_id!r} — cannot fetch via standard endpoint (likely sealed)")
            skipped += 1
            manifest.append({
                "instrument": instrument, "doc_id": doc_id, "status": "NO_DOC_ID",
                "slug": slug, "doc_type": doc_type, "record_date": rec_date,
                "note": "Cache has no doc_id — likely sealed (DR/Family Court privacy) or pre-image-system record",
            })
            continue

        pdf_filename = f"MCCCC-{instrument}-{slug}.pdf"
        target = DOWNLOAD_DIR / pdf_filename

        if target.exists() and target.stat().st_size > 0:
            print(f"[=] {pdf_filename} already present ({target.stat().st_size} bytes) — skipping fetch")
            ok += 1
            manifest.append({
                "instrument": instrument, "doc_id": doc_id, "status": "ALREADY_PRESENT",
                "slug": slug, "doc_type": doc_type, "record_date": rec_date, "pages": pages,
                "path": str(target.relative_to(CASE_DIR)),
            })
            continue

        print(f"[>] Downloading {instrument} ({doc_type}, {rec_date}) doc_id={doc_id} → {pdf_filename}")
        success = download_pdf(doc_id, pdf_filename, str(DOWNLOAD_DIR))
        status = "OK" if success else "FAILED"
        manifest.append({
            "instrument": instrument, "doc_id": doc_id, "status": status,
            "slug": slug, "doc_type": doc_type, "record_date": rec_date, "pages": pages,
            "path": str(target.relative_to(CASE_DIR)) if success else None,
        })
        if success:
            ok += 1
        else:
            failed += 1
        time.sleep(REQUEST_DELAY_SEC)

    manifest_path = CASE_DIR / "download_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump({
            "subject": "4837 SABAL HARBOUR DR, BRADENTON FL",
            "apn": "1697719559",
            "totals": {"requested": len(INCLUDE_INSTRUMENTS), "ok": ok, "skipped": skipped, "failed": failed},
            "documents": manifest,
        }, fh, indent=2)

    print(f"\n=== Download Summary ===")
    print(f"  Requested: {len(INCLUDE_INSTRUMENTS)}")
    print(f"  OK:        {ok}")
    print(f"  Skipped:   {skipped}")
    print(f"  Failed:    {failed}")
    print(f"  Manifest:  {manifest_path}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
