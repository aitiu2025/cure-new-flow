#!/usr/bin/env python3
"""
TitlePro Workflow Test Script
Tests the full workflow: CA Recorder Search -> TitlePro Download -> Report Generation

This script uses the DYNAMIC search flow (not hardcoded documents):
1. Searches CA Recorder portal for documents by name
2. Downloads documents from TitlePro
3. Generates reports

Run: python test_workflow.py [--name "Kwa Danny"] [--quick]
"""

import json
import time
import requests
import subprocess
import sys
from pathlib import Path

API_URL = "http://localhost:5555"
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloaded_doc"
BATCH_PROCESSOR = BASE_DIR / "titlepro" / "search" / "recorder" / "batch_processor.py"

# Default test case - can be overridden via command line
DEFAULT_TEST_NAME = "Kwa Danny"
DEFAULT_TEST_ADDRESS = "12612 Lansdale Circle #176, Stanton CA 90680"

def log(msg, level="INFO"):
    print(f"[{level}] {msg}")

def test_api_status():
    """Test 1: Check API server status"""
    log("Testing /status endpoint...")
    try:
        r = requests.get(f"{API_URL}/status", timeout=5)
        r.raise_for_status()
        data = r.json()
        assert data["status"] == "online", "API should be online"
        log(f"  ✓ API is online: {data['message']}", "PASS")
        return True
    except Exception as e:
        log(f"  ✗ API status check failed: {e}", "FAIL")
        return False

def test_batch_processor_search(name: str, start_date: str = "01/01/2000"):
    """
    Test 2: Run batch_processor.py to search CA Recorder portal
    This is the PROPER workflow - dynamically searches for documents
    """
    log(f"Running CA Recorder search for: {name}")
    log(f"  Using batch_processor.py (Step 1: Name Search)")

    safe_name = name.replace(" ", "_").replace(",", "")
    output_dir = DOWNLOAD_DIR / safe_name

    try:
        # Run batch_processor with --skip-download to just get document list
        result = subprocess.run(
            [
                sys.executable,
                str(BATCH_PROCESSOR),
                "--name", name,
                "--start-date", start_date,
                "--skip-download"
            ],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout for search
            cwd=str(BASE_DIR / "titlepro" / "search" / "recorder")
        )

        if result.returncode != 0:
            log(f"  ✗ Search failed: {result.stderr[:500]}", "FAIL")
            return None

        # Check for documents_found.json
        docs_file = output_dir / "documents_found.json"
        if not docs_file.exists():
            log(f"  ✗ documents_found.json not created", "FAIL")
            return None

        documents = json.loads(docs_file.read_text())
        log(f"  ✓ Found {len(documents)} documents from recorder search", "PASS")

        return documents

    except subprocess.TimeoutExpired:
        log(f"  ✗ Search timed out", "FAIL")
        return None
    except Exception as e:
        log(f"  ✗ Search error: {e}", "FAIL")
        return None

def test_api_batch_download(owner_name: str, documents: list, show_browser: bool = False):
    """
    Test 3: Download documents via API (not hardcoded)
    Uses the documents found by the recorder search
    """
    log(f"Downloading {len(documents)} documents via API...")

    # Convert to API format
    api_docs = []
    for doc in documents:
        doc_num = doc.get("document_number", "")
        if doc_num:
            year = doc_num[:4] if len(doc_num) >= 4 else "2020"
            api_docs.append({
                "num": doc_num,
                "year": year,
                "type": doc.get("document_type", "DOCUMENT")
            })

    if not api_docs:
        log("  ✗ No documents to download", "FAIL")
        return False

    try:
        r = requests.post(f"{API_URL}/batch-download", json={
            "owner_name": owner_name,
            "documents": api_docs,
            "show_browser": show_browser,
            "skip_existing": True
        }, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data["status"] != "started":
            log(f"  ✗ Batch failed to start: {data}", "FAIL")
            return False

        batch_id = data["batch_id"]
        log(f"  Batch started: {batch_id}")

        # Poll for completion
        max_wait = 600  # 10 minutes for full batch
        start = time.time()
        while time.time() - start < max_wait:
            r = requests.get(f"{API_URL}/batch-status/{batch_id}", timeout=5)
            status = r.json()

            completed = status.get("completed", 0)
            total = status.get("total", len(api_docs))
            current = status.get("current", "")

            if status["status"] == "completed":
                results = status.get("results", [])
                successes = [r for r in results if r["status"] in ("success", "skipped")]
                log(f"  ✓ Batch completed: {len(successes)}/{len(results)} successful", "PASS")
                return True
            else:
                log(f"  ... {completed}/{total} complete, current: {current}")
                time.sleep(10)

        log(f"  ✗ Batch timed out after {max_wait}s", "FAIL")
        return False

    except Exception as e:
        log(f"  ✗ Batch download error: {e}", "FAIL")
        return False

def test_metadata_exists(owner_name: str):
    """Test 4: Verify metadata file was created"""
    log("Checking metadata file...")

    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_DIR / safe_owner
    metadata_path = folder_path / "document_metadata.json"

    try:
        if not metadata_path.exists():
            log(f"  ✗ Metadata file not found: {metadata_path}", "FAIL")
            return False

        metadata = json.loads(metadata_path.read_text())
        log(f"  ✓ Metadata file exists with {len(metadata)} entries", "PASS")

        # Show first few entries
        for i, (doc_num, info) in enumerate(list(metadata.items())[:3]):
            log(f"    {doc_num} -> {info.get('filename', 'N/A')}")
        if len(metadata) > 3:
            log(f"    ... and {len(metadata) - 3} more")

        return True

    except Exception as e:
        log(f"  ✗ Metadata check failed: {e}", "FAIL")
        return False

def test_check_files_api(owner_name: str, documents: list):
    """Test 5: Verify check-files API returns correct data"""
    log("Testing /check-files API...")

    try:
        api_docs = [{"num": d.get("document_number")} for d in documents if d.get("document_number")]

        r = requests.post(f"{API_URL}/check-files", json={
            "owner_name": owner_name,
            "documents": api_docs
        }, timeout=10)
        r.raise_for_status()
        data = r.json()

        found_count = sum(1 for d in data.get("documents", []) if d.get("file_exists"))
        total_count = len(api_docs)

        log(f"  ✓ {found_count}/{total_count} files found", "PASS")
        log(f"    Metadata entries: {data.get('metadata_entries', 0)}")

        return found_count > 0

    except Exception as e:
        log(f"  ✗ Check files failed: {e}", "FAIL")
        return False

def test_generate_report(owner_name: str, address: str):
    """Test 6: Generate report via API"""
    log("Testing report generation...")

    try:
        r = requests.post(f"{API_URL}/generate-report", json={
            "owner_name": owner_name,
            "property_address": address
        }, timeout=30)
        r.raise_for_status()
        data = r.json()

        if data.get("success"):
            log(f"  ✓ Report generated", "PASS")
            if data.get("report_markdown"):
                log(f"    Markdown: {len(data['report_markdown'])} chars")
            return True
        else:
            log(f"  ✗ Report failed: {data.get('error')}", "FAIL")
            return False

    except Exception as e:
        log(f"  ✗ Report generation failed: {e}", "FAIL")
        return False

def test_list_files(owner_name: str):
    """Test 7: List all downloaded files"""
    log("Testing file listing...")

    try:
        safe_owner = owner_name.replace(" ", "_").replace(",", "")
        r = requests.get(f"{API_URL}/list-files/{safe_owner}", timeout=10)
        r.raise_for_status()
        data = r.json()

        if not data.get("folder_exists"):
            log(f"  ✗ Folder does not exist", "FAIL")
            return False

        files = data.get("files", [])
        log(f"  ✓ Found {len(files)} files", "PASS")

        for f in files[:5]:
            log(f"    - {f['name']}")
        if len(files) > 5:
            log(f"    ... and {len(files) - 5} more")

        return True

    except Exception as e:
        log(f"  ✗ File listing failed: {e}", "FAIL")
        return False

def cleanup_folder(owner_name: str):
    """Remove test folder"""
    import shutil
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_DIR / safe_owner

    if folder_path.exists():
        try:
            shutil.rmtree(folder_path)
            log(f"Cleaned up: {folder_path}")
        except Exception as e:
            log(f"Warning: Could not cleanup: {e}")

def main():
    import argparse

    parser = argparse.ArgumentParser(description="TitlePro Workflow Test")
    parser.add_argument("--name", "-n", default=DEFAULT_TEST_NAME,
                        help=f"Name to search (default: {DEFAULT_TEST_NAME})")
    parser.add_argument("--address", "-a", default=DEFAULT_TEST_ADDRESS,
                        help="Property address")
    parser.add_argument("--start-date", default="01/01/2000",
                        help="Search start date (MM/DD/YYYY)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick test - skip batch download, use existing files")
    parser.add_argument("--cleanup", action="store_true",
                        help="Clean up test folder after tests")
    parser.add_argument("--show-browser", action="store_true",
                        help="Show browser during downloads")

    args = parser.parse_args()

    print("=" * 60)
    print("TitlePro Workflow Test")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"Test Name: {args.name}")
    print(f"Address: {args.address}")
    print(f"Start Date: {args.start_date}")
    print(f"Quick Mode: {args.quick}")
    print("=" * 60)
    print()

    results = []
    documents = None

    # Test 1: API Status
    print("\n--- Test 1: API Status ---")
    if not test_api_status():
        log("API not available. Start with: python titlepro_api_server.py", "ERROR")
        return 1
    results.append(("API Status", True))

    # Test 2: Recorder Search (gets document list dynamically)
    print("\n--- Test 2: CA Recorder Search ---")
    documents = test_batch_processor_search(args.name, args.start_date)
    if documents is None:
        log("Stopping due to search failure", "WARN")
        results.append(("CA Recorder Search", False))
    else:
        results.append(("CA Recorder Search", True))
        log(f"  Documents to download: {len(documents)}")

    # Test 3: Batch Download (uses dynamic document list)
    if documents and not args.quick:
        print("\n--- Test 3: Batch Download ---")
        if test_api_batch_download(args.name, documents, args.show_browser):
            results.append(("Batch Download", True))
        else:
            results.append(("Batch Download", False))
    elif args.quick:
        print("\n--- Test 3: Batch Download (SKIPPED - quick mode) ---")
        results.append(("Batch Download", "SKIP"))

    # Test 4: Metadata
    if documents:
        print("\n--- Test 4: Metadata Check ---")
        results.append(("Metadata Check", test_metadata_exists(args.name)))

    # Test 5: Check Files API
    if documents:
        print("\n--- Test 5: Check Files API ---")
        results.append(("Check Files API", test_check_files_api(args.name, documents)))

    # Test 6: Generate Report
    if documents:
        print("\n--- Test 6: Generate Report ---")
        results.append(("Generate Report", test_generate_report(args.name, args.address)))

    # Test 7: List Files
    if documents:
        print("\n--- Test 7: List Files ---")
        results.append(("List Files", test_list_files(args.name)))

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result == "SKIP":
            status = "⊘ SKIP"
            skipped += 1
        elif result:
            status = "✓ PASS"
            passed += 1
        else:
            status = "✗ FAIL"
            failed += 1
        print(f"  {status}: {name}")

    print()
    print(f"Passed: {passed}, Failed: {failed}, Skipped: {skipped}")
    print("=" * 60)

    # Cleanup if requested
    if args.cleanup:
        cleanup_folder(args.name)
    else:
        safe_owner = args.name.replace(" ", "_").replace(",", "")
        folder_path = DOWNLOAD_DIR / safe_owner
        print(f"\nTest folder: {folder_path}")
        print("Run with --cleanup to remove after tests")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
