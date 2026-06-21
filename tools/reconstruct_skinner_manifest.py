#!/usr/bin/env python3
"""Reconstruct documents_found.json for Duval_SKINNER_v1 from local extracted MD
headers + download_manifest.json + phase1_subject_chain.json. NO network, NO OCR.

Mirrors the Pasco_RILEY_v1 documents_found.json schema (list of per-entry dicts).
"""
import json
import os
import re

CASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "titlepro", "api", "downloaded_doc", "0610", "Duval_SKINNER_v1",
)


def party_list(party1_names, party2_names):
    """Build the RILEY-style parties list + semicolon grantor/grantee strings."""
    parties = []
    for n in party1_names:
        parties.append({"role": "Party 1", "name": n})
    for n in party2_names:
        parties.append({"role": "Party 2", "name": n})
    return parties, "; ".join(party1_names), "; ".join(party2_names)


# Per-doc facts harvested locally from MD banners + chronology/linkage + download
# manifest labels. recording_date + book_page come verbatim from each MD header
# banner ("Doc # X, OR BK B Page P ... Recorded MM/DD/YYYY"). Party-1 = grantor
# (From: side), Party-2 = grantee (To: side), per FL recorder indexing convention.
DOCS = [
    {
        "document_number": "2010174837",
        "document_type": "WARRANTY DEED",
        "recording_date": "07/28/2010",
        "book_page": "15319 / 1154",
        "page_count": "2",
        "legal": "L325 RIVERBROOK AT GLEN KERNAN UN4",
        "p1": ["DRUGG CHRIS", "DRUGG ASHLEY"],
        "p2": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2010174838",
        "document_type": "MORTGAGE",
        "recording_date": "07/28/2010",
        "book_page": "15319 / 1156",
        "page_count": "16",
        "legal": "L325 RIVERBROOK AT GLEN KERNAN UN4",
        "p1": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "p2": ["MORTGAGE ELEC REG SYS INC"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2012088448",
        "document_type": "JUDGMENT",
        "recording_date": "",
        "book_page": "15921 / 1207",
        "page_count": "2",
        "legal": "",
        "p1": [],
        "p2": [],
        "subject_property": False,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2015282677",
        "document_type": "MORTGAGE",
        "recording_date": "12/11/2015",
        "book_page": "17396 / 1128",
        "page_count": "14",
        "legal": "L325 RIVERBROOK AT GLEN KERNAN UN4",
        "p1": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "p2": ["MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2016020826",
        "document_type": "SATISFACTION",
        "recording_date": "01/28/2016",
        "book_page": "17443 / 388",
        "page_count": "1",
        "legal": "",
        "p1": ["MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        "p2": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "subject_property": True,
        "satisfies_book_page": "15319 / 1156",
    },
    {
        "document_number": "2020282510",
        "document_type": "MORTGAGE",
        "recording_date": "12/17/2020",
        "book_page": "19501 / 1700",
        "page_count": "17",
        "legal": "L 325 RIVERBROOK GLEN KERNAN UNIT FOUR",
        "p1": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "p2": ["COMMUNITY FIRST CREDIT UNION OF FL"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2020291263",
        "document_type": "SATISFACTION",
        "recording_date": "12/31/2020",
        "book_page": "19517 / 1335",
        "page_count": "1",
        "legal": "",
        "p1": ["MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        "p2": ["SKINNER MICHAEL W", "SKINNER SALLY JANE"],
        "subject_property": True,
        "satisfies_book_page": "17396 / 1128",
    },
    {
        "document_number": "2021034715",
        "document_type": "NOTICE OF COMMENCEMENT",
        "recording_date": "02/08/2021",
        "book_page": "19577 / 2106",
        "page_count": "1",
        "legal": "PIN 167730-6710 L 325 RIVERBROOK AT GLEN KERNAN U 4",
        "p1": ["SKINNER MICHAEL"],
        "p2": ["TROPICAL ENCLOSURES BY MASTER SCREENS INC"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2025000296",
        "document_type": "MORTGAGE",
        "recording_date": "01/02/2025",
        "book_page": "21313 / 371",
        "page_count": "10",
        "legal": "PIN 167730 6710 L 325 RIVERBROOK AT GLEN KERNAN U FOUR",
        "p1": ["SKINNER SALLY JANE"],
        "p2": ["COMMUNITY FIRST CREDIT UNION OF FLORIDA"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2026088533",
        "document_type": "MORTGAGE",
        "recording_date": "04/16/2026",
        "book_page": "21870 / 322",
        "page_count": "16",
        "legal": "LOT 325 RIVERBROOK AT GLEN KERNAN UNIT FOUR",
        "p1": ["SKINNER SALLY JANE"],
        "p2": ["COMMUNITY FIRST CREDIT UNION OF FLORIDA"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2026120984",
        "document_type": "SATISFACTION",
        "recording_date": "05/22/2026",
        "book_page": "21917 / 1680",
        "page_count": "1",
        "legal": "",
        "p1": ["COMMUNITY FIRST CREDIT UNION OF FLORIDA"],
        "p2": ["SKINNER SALLY JANE"],
        "subject_property": True,
        "satisfies_book_page": "21313 / 371",
    },
    {
        "document_number": "2005290167",
        "document_type": "WARRANTY DEED",
        "recording_date": "08/08/2005",
        "book_page": "12667 / 943",
        "page_count": "2",
        "legal": "L325 RIVERBROOK AT GLEN KERNAN UN4",
        "p1": ["JERNIGAN THOMAS"],
        "p2": ["DRUGG CHRIS", "DRUGG ASHLEY"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2005290168",
        "document_type": "MORTGAGE",
        "recording_date": "08/08/2005",
        "book_page": "12667 / 945",
        "page_count": "20",
        "legal": "L325 RIVERBROOK AT GLEN KERNAN UN4",
        "p1": ["DRUGG CHRIS", "DRUGG ASHLEY"],
        "p2": ["MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        "subject_property": True,
        "satisfies_book_page": "",
    },
    {
        "document_number": "2010166032",
        "document_type": "RELEASE OF MORTGAGE",
        "recording_date": "07/19/2010",
        "book_page": "15309 / 2295",
        "page_count": "1",
        "legal": "",
        "p1": ["MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"],
        "p2": ["DRUGG ASHLEY"],
        "subject_property": True,
        "satisfies_book_page": "12667 / 945",
    },
    {
        "document_number": "2006423506",
        "document_type": "NOTICE OF COMMENCEMENT",
        "recording_date": "12/08/2006",
        "book_page": "13687 / 2281",
        "page_count": "1",
        "legal": "",
        "p1": ["DRUGG"],
        "p2": [],
        "subject_property": True,
        "satisfies_book_page": "",
    },
]


def build():
    out = []
    for d in DOCS:
        parties, grantors, grantees = party_list(d["p1"], d["p2"])
        out.append({
            "document_number": d["document_number"],
            "document_type": d["document_type"],
            "recording_date": d["recording_date"],
            "book_page": d["book_page"],
            "page_count": d["page_count"],
            "legal": d["legal"],
            "parties": parties,
            "grantors": grantors,
            "grantees": grantees,
            "subject_property": d["subject_property"],
            "satisfies_book_page": d["satisfies_book_page"],
        })
    return out


def validate(manifest):
    extracted_stems = [
        f[:-len("_extracted.md")]
        for f in os.listdir(CASE_DIR)
        if f.endswith("_extracted.md")
    ]
    assert len(extracted_stems) == 15, (
        f"Expected 15 extracted MD files, found {len(extracted_stems)}"
    )
    matched = 0
    unmatched = []
    for entry in manifest:
        dn = entry["document_number"]
        if any(dn in stem for stem in extracted_stems):
            matched += 1
        else:
            unmatched.append(dn)
    return matched, len(manifest), unmatched, sorted(extracted_stems)


if __name__ == "__main__":
    manifest = build()
    out_path = os.path.join(CASE_DIR, "documents_found.json")
    with open(out_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    matched, total, unmatched, stems = validate(manifest)
    print(f"WROTE: {out_path}")
    print(f"ENTRY COUNT: {total}")
    print(f"VALIDATION: {matched}/{total} document_numbers resolve to extracted MD files")
    if unmatched:
        print(f"UNMATCHED: {unmatched}")
    else:
        print("UNMATCHED: none")
    print("\n--- extracted stems on disk ---")
    for s in stems:
        print("  " + s)
