#!/usr/bin/env python3
"""
Batch Document Processor for CA Recorder Search + TitlePro Download

This script:
1. Searches Orange County Recorder for a name (as Grantor and Grantee)
2. Creates a union of all documents found
3. Downloads each document from TitlePro247
4. Creates a summary report with Name, Address, APN, and Document IDs

Usage:
    python batch_processor.py --name "Kwa Danny" --address "12612 Lansdale Circle"
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

TITLEPRO_DIR = Path(__file__).resolve().parent.parent.parent.parent
from titlepro import DOWNLOAD_DIR

from titlepro.search.recorder.counties.orange import OrangeCountyRecorder
from titlepro.search.recorder.utils import parse_owner_names

# TitlePro downloader imports
try:
    from titlepro.download.selenium_downloader import (
        download_document,  # Use the main function with retry logic
        SECRETS_FILENAME, DOWNLOAD_DIRNAME
    )
    TITLEPRO_AVAILABLE = True
except ImportError as e:
    print(f"Warning: TitlePro downloader not available: {e}")
    TITLEPRO_AVAILABLE = False

MAX_RESULTS_BEFORE_TIGHTEN = 30


def search_recorder(name: str, start_date: str, end_date: str) -> List[Dict]:
    """
    Search Orange County Recorder for one or more names as Grantor and Grantee.
    Returns union of all documents found.
    """
    all_documents = {}  # Use dict to deduplicate by document number
    names = parse_owner_names(name)

    print(f"\n{'='*60}")
    print(f"ORANGE COUNTY RECORDER SEARCH")
    print(f"{'='*60}")
    print(f"Names: {', '.join(names) if names else 'None'}")
    print(f"Date Range: {start_date} to {end_date}")

    if not names:
        print("\nNo valid names provided. Exiting search.")
        return []

    def run_search_modes(recorder: OrangeCountyRecorder, search_name: str, partial_match: bool) -> Dict[str, Dict]:
        doc_map: Dict[str, Dict] = {}
        modes = ["Grantor", "Grantee", "Grantor/Grantee"]

        for party_type in modes:
            print(f"\n--- Searching as {party_type}: {search_name} ---")
            recorder.set_partial_match(partial_match)
            try:
                result = recorder.search_name(search_name, party_type)
                for doc in result.documents:
                    if doc.document_number:
                        doc_map[doc.document_number] = doc.to_dict()
                print(f"  Found {len(result.documents)} documents as {party_type}")
            except Exception as e:
                print(f"  Error searching as {party_type}: {e}")
            finally:
                recorder.return_to_search()

        return doc_map

    with OrangeCountyRecorder(start_date=start_date, end_date=end_date) as recorder:
        recorder.navigate_to_search()

        for idx, search_name in enumerate(names, start=1):
            print(f"\nSearching name ({idx}/{len(names)}): {search_name}")

            doc_map = run_search_modes(recorder, search_name, partial_match=True)
            unique_count = len(doc_map)

            if unique_count == 0:
                surname = search_name.split()[0]
                if surname and surname.lower() != search_name.lower():
                    print(f"\nNo results for {search_name}. Retrying with surname only: {surname}")
                    doc_map = run_search_modes(recorder, surname, partial_match=True)
                    unique_count = len(doc_map)

            if unique_count >= MAX_RESULTS_BEFORE_TIGHTEN:
                print(f"\n{unique_count} results found for {search_name}. Tightening search (exact match).")
                tightened_map = run_search_modes(recorder, search_name, partial_match=False)
                if tightened_map:
                    doc_map = tightened_map
                    unique_count = len(doc_map)
                    print(f"  Tightened results: {unique_count} documents")
                else:
                    print("  Tightened search returned no results; keeping original set.")

            for doc_num, doc in doc_map.items():
                all_documents[doc_num] = doc

    print(f"\n  Total unique documents: {len(all_documents)}")
    return list(all_documents.values())


def batch_download_documents(documents: List[Dict], output_dir: Path, secrets_path: Path, owner_name: str = None) -> Dict[str, Optional[str]]:
    """
    Download all documents from TitlePro247.
    Uses the download_document function which has retry logic for connection errors.
    Returns dict mapping document number to downloaded file path (or None if failed).
    """
    if not TITLEPRO_AVAILABLE:
        print("TitlePro downloader not available")
        return {doc.get('document_number', ''): None for doc in documents}

    results = {}

    print(f"\n{'='*60}")
    print(f"TITLEPRO DOCUMENT DOWNLOAD")
    print(f"{'='*60}")
    print(f"Documents to download: {len(documents)}")
    print(f"Output directory: {output_dir}")

    for i, doc in enumerate(documents, 1):
        doc_num = doc.get('document_number', '')
        if not doc_num:
            continue

        # Extract year from document number (first 4 digits)
        year = doc_num[:4] if len(doc_num) >= 4 else datetime.now().strftime("%Y")

        print(f"\n[{i}/{len(documents)}] Document: {doc_num} (Year: {year})")

        # Use the main download_document function which has retry logic
        result = download_document(
            doc_num=doc_num,
            year=year,
            headless=False,  # Show browser for batch processing
            owner_name=owner_name
        )

        if result.get("status") == "success":
            files = result.get("files", [])
            if files:
                # Get the full path to the first downloaded file
                downloaded_path = output_dir / files[0]
                results[doc_num] = str(downloaded_path)
                print(f"  ✓ Downloaded: {files[0]}")
            else:
                results[doc_num] = None
                print(f"  ✗ No files in result")
        else:
            results[doc_num] = None
            print(f"  ✗ Failed: {result.get('message', 'Unknown error')}")

        # Small delay between downloads to avoid rate limiting
        if i < len(documents):
            time.sleep(2)

    return results


def create_report(name: str, address: str, documents: List[Dict],
                  downloaded_files: Dict[str, Optional[str]], output_dir: Path) -> Dict:
    """
    Create a summary report with all information.
    """
    report = {
        "search_info": {
            "name": name,
            "address": address,
            "search_timestamp": datetime.now().isoformat(),
            "county": "Orange"
        },
        "summary": {
            "total_documents_found": len(documents),
            "documents_downloaded": sum(1 for v in downloaded_files.values() if v),
            "documents_failed": sum(1 for v in downloaded_files.values() if v is None)
        },
        "documents": []
    }

    for doc in documents:
        doc_num = doc.get('document_number', '')
        doc_entry = {
            **doc,
            "downloaded_file": downloaded_files.get(doc_num),
            "download_status": "success" if downloaded_files.get(doc_num) else "failed"
        }
        report["documents"].append(doc_entry)

    # Save report
    report_path = output_dir / "report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"REPORT SAVED")
    print(f"{'='*60}")
    print(f"Report file: {report_path}")
    print(f"Total documents: {report['summary']['total_documents_found']}")
    print(f"Downloaded: {report['summary']['documents_downloaded']}")
    print(f"Failed: {report['summary']['documents_failed']}")

    return report


def print_final_summary(report: Dict):
    """Print a human-readable summary."""
    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY")
    print(f"{'='*60}")

    info = report.get("search_info", {})
    print(f"\nName: {info.get('name', 'N/A')}")
    print(f"Address: {info.get('address', 'N/A')}")
    print(f"County: {info.get('county', 'N/A')}")

    print(f"\nDocuments Found:")
    print("-" * 60)

    for doc in report.get("documents", []):
        status = "✓" if doc.get("download_status") == "success" else "✗"
        doc_num = doc.get("document_number", "N/A")
        doc_type = doc.get("document_type", "N/A")
        rec_date = doc.get("recording_date", "N/A")

        print(f"  {status} {doc_num}")
        if doc_type:
            print(f"      Type: {doc_type}")
        if rec_date:
            print(f"      Date: {rec_date}")
        if doc.get("downloaded_file"):
            print(f"      File: {Path(doc['downloaded_file']).name}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch process: Search recorder + download from TitlePro"
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="Name to search (Last First format, e.g., 'Kwa Danny')"
    )
    parser.add_argument(
        "--address", "-a",
        default="",
        help="Property address for filtering/reference"
    )
    parser.add_argument(
        "--start-date",
        default="01/01/2000",
        help="Search start date (MM/DD/YYYY)"
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Search end date (MM/DD/YYYY, default: today)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Output directory for downloads (default: creates from name)"
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip TitlePro download, only search recorder"
    )

    args = parser.parse_args()

    # Set defaults
    end_date = args.end_date or datetime.now().strftime("%m/%d/%Y")

    # Create output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Create directory based on name
        safe_name = args.name.replace(" ", "_").replace(",", "")
        output_dir = DOWNLOAD_DIR / safe_name

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Step 1: Search recorder
    documents = search_recorder(args.name, args.start_date, end_date)

    if not documents:
        print("\nNo documents found. Exiting.")
        return

    # Save document list
    docs_file = output_dir / "documents_found.json"
    with open(docs_file, 'w') as f:
        json.dump(documents, f, indent=2)
    print(f"\nDocument list saved to: {docs_file}")

    # Step 2: Download from TitlePro (if not skipped)
    downloaded_files = {}
    if not args.skip_download:
        secrets_path = TITLEPRO_DIR / SECRETS_FILENAME
        if secrets_path.exists():
            safe_name = args.name.replace(" ", "_").replace(",", "")
            downloaded_files = batch_download_documents(documents, output_dir, secrets_path, owner_name=safe_name)
        else:
            print(f"\nWarning: secrets.json not found at {secrets_path}")
            print("Skipping TitlePro download.")
    else:
        print("\nSkipping TitlePro download (--skip-download flag)")

    # Step 3: Create report
    report = create_report(args.name, args.address, documents, downloaded_files, output_dir)

    # Step 4: Print summary
    print_final_summary(report)

    # Step 5: Generate RAW Two Owner Search Exam using report_generator
    # This ensures CLI and UI produce identical output
    try:
        from titlepro.reports.report_generator import generate_report_for_owner
        safe_name = args.name.replace(" ", "_").replace(",", "")
        print(f"\n{'='*60}")
        print(f"GENERATING RAW TWO OWNER SEARCH EXAM")
        print(f"{'='*60}")
        result = generate_report_for_owner(safe_name, args.address)
        if result.get("success"):
            print(f"Report source: {result.get('source', 'unknown')}")
            print(f"Markdown report saved to: {output_dir / 'RAW_TWO_OWNER_SEARCH_EXAM.md'}")
            if result.get("source") == "detailed_json":
                print("Using detailed FINAL_REPORT.json for full report generation")
            else:
                print("Using basic metadata - create FINAL_REPORT.json for detailed report")
        else:
            print(f"Warning: Report generation failed: {result.get('error')}")
    except ImportError as e:
        print(f"\nNote: report_generator not available ({e})")
        print("Run from titlePro root directory for full report generation")
    except Exception as e:
        print(f"\nWarning: Could not generate RAW Two Owner Search Exam: {e}")


if __name__ == "__main__":
    main()
