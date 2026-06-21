#!/usr/bin/env python3
"""
Run test subjects through the CURE API sequentially.
Uses Last-First name format (as the recorder expects).
Calls: search-recorder → batch-download → generate-report
"""

import requests
import json
import time
import sys
from datetime import datetime

API = "http://localhost:5555"

# Test subjects with names in LAST FIRST format (how the recorder expects them)
# Only non-CAPTCHA counties that are most likely to work
TEST_SUBJECTS = [
    # RecorderWorks counties (no CAPTCHA) - most reliable
    {"county": "stanislaus", "label": "Stanislaus (RecorderWorks)",
     "owner_name": "Sobowale Clama",
     "address": "3200 Crimble, Modesto, CA"},

    {"county": "merced", "label": "Merced (RecorderWorks)",
     "owner_name": "Goprian Dawna",
     "address": "2994 Cordial, Merced, CA"},

    {"county": "imperial", "label": "Imperial (RecorderWorks)",
     "owner_name": "Jaramillo Enrique",
     "address": "906 Corral St, Calexico, CA"},

    {"county": "calaveras", "label": "Calaveras (RecorderWorks)",
     "owner_name": "De Martin Samantha",
     "address": "2676 Karooked Rd, Arnold, CA"},

    # Tyler counties (no CAPTCHA - newly configured)
    {"county": "monterey", "label": "Monterey (Tyler, no CAPTCHA)",
     "owner_name": "Hodge James E",
     "address": "13000 Fennel, East Garrison, CA"},

    {"county": "san_luis_obispo", "label": "San Luis Obispo (Tyler, no CAPTCHA)",
     "owner_name": "Porto Daniel Coal",
     "address": "50 Summers Dr, Templeton, CA"},

    {"county": "santa_cruz", "label": "Santa Cruz (Tyler, no CAPTCHA)",
     "owner_name": "Kim Michael L",
     "address": "10636 Alba Rd, Ben Lomond, CA"},

    {"county": "trinity", "label": "Trinity (Tyler, no CAPTCHA)",
     "owner_name": "Schriner Wesley Paul",
     "address": "360 Marylino, Weaverville, CA"},
]


def check_server():
    """Verify server is running."""
    try:
        r = requests.get(f"{API}/status", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def search_recorder(owner_name, county, timeout=600):
    """Call search-recorder and poll for results."""
    print(f"  Searching {county} for '{owner_name}'...")

    # Start the search
    resp = requests.post(f"{API}/search-recorder", json={
        "owner_name": owner_name,
        "county": county,
    }, timeout=30)

    data = resp.json()

    # Check if it returns a job_id (async) or results directly (sync)
    if "job_id" in data:
        job_id = data["job_id"]
        print(f"  Background job started: {job_id}")
        # Poll for completion
        start = time.time()
        while (time.time() - start) < timeout:
            try:
                status_resp = requests.get(f"{API}/search-recorder-status/{job_id}", timeout=10)
                status = status_resp.json()
                if status.get("status") == "completed":
                    result = status.get("result", {})
                    docs = result.get("documents", [])
                    print(f"  Search completed: {len(docs)} documents found ({time.time()-start:.0f}s)")
                    return result
                elif status.get("status") == "error":
                    print(f"  Search error: {status.get('error', 'unknown')}")
                    return status.get("result", {"success": False, "documents": []})
                else:
                    elapsed = time.time() - start
                    phase = status.get("phase", "")
                    docs_so_far = status.get("documents_found", 0)
                    if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                        print(f"    [{elapsed:.0f}s] {phase} - {docs_so_far} docs so far")
            except Exception as e:
                pass
            time.sleep(2)

        print(f"  Search timed out after {timeout}s")
        # Try to get partial results
        try:
            status_resp = requests.get(f"{API}/search-recorder-status/{job_id}", timeout=10)
            return status_resp.json().get("result", {"success": False, "documents": []})
        except Exception:
            return {"success": False, "documents": []}

    elif data.get("success"):
        # Synchronous response
        docs = data.get("documents", [])
        print(f"  Search returned: {len(docs)} documents")
        return data
    else:
        print(f"  Search failed: {data.get('error', 'unknown')}")
        return data


def batch_download(owner_name, documents, timeout=600):
    """Download documents via batch-download endpoint."""
    if not documents:
        print(f"  No documents to download")
        return

    missing_docs = [d for d in documents if not d.get("file_exists")]
    if not missing_docs:
        print(f"  All {len(documents)} documents already downloaded")
        return

    print(f"  Downloading {len(missing_docs)} documents...")

    resp = requests.post(f"{API}/batch-download", json={
        "owner_name": owner_name,
        "documents": missing_docs,
        "show_browser": False,
        "skip_existing": True,
    }, timeout=30)

    data = resp.json()
    batch_id = data.get("batch_id")
    if not batch_id:
        print(f"  Batch download failed: {data.get('error', 'no batch_id')}")
        return

    print(f"  Batch job started: {batch_id}")

    # Poll for completion
    start = time.time()
    while (time.time() - start) < timeout:
        try:
            status_resp = requests.get(f"{API}/batch-status/{batch_id}", timeout=10)
            status = status_resp.json()

            if status.get("status") == "completed":
                completed = status.get("completed", 0)
                print(f"  Download completed: {completed} documents ({time.time()-start:.0f}s)")
                return
            elif status.get("status") == "error" or status.get("status") == "failed":
                print(f"  Download error: {status.get('message', 'unknown')}")
                return
            else:
                elapsed = time.time() - start
                completed = status.get("completed", 0)
                current = status.get("current", "")
                if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                    print(f"    [{elapsed:.0f}s] Downloaded {completed}/{len(missing_docs)}: {current}")
        except Exception:
            pass
        time.sleep(3)

    print(f"  Download timed out after {timeout}s")


def check_files(owner_name, documents):
    """Check which files already exist."""
    if not documents:
        return documents
    resp = requests.post(f"{API}/check-files", json={
        "owner_name": owner_name,
        "documents": documents,
    }, timeout=30)
    data = resp.json()
    return data.get("documents", documents)


def generate_report(owner_name, address=""):
    """Generate the RAW Two Owner Search report."""
    print(f"  Generating report...")
    resp = requests.post(f"{API}/generate-report", json={
        "owner_name": owner_name,
        "property_address": address,
    }, timeout=120)
    data = resp.json()
    if data.get("success") and data.get("report_markdown"):
        md_len = len(data["report_markdown"])
        print(f"  Report generated: {md_len} chars")
        return data
    else:
        print(f"  Report generation: {data.get('error', 'no markdown returned')}")
        return data


def run_subject(subject):
    """Run the full pipeline for one test subject."""
    county = subject["county"]
    label = subject["label"]
    owner_name = subject["owner_name"]
    address = subject.get("address", "")

    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"  Owner: {owner_name}")
    print(f"  Address: {address}")
    print(f"{'='*60}")

    start = time.time()
    result = {
        "county": county, "label": label, "owner_name": owner_name,
        "started_at": datetime.now().isoformat(),
    }

    # Step 1: Search
    search_result = search_recorder(owner_name, county)
    documents = search_result.get("documents", [])
    result["documents_found"] = len(documents)

    if not documents:
        result["result"] = "NO_DOCS"
        result["duration"] = time.time() - start
        print(f"  Result: NO DOCUMENTS FOUND ({result['duration']:.0f}s)")
        return result

    # Step 2: Check existing files
    print(f"  Checking existing files...")
    documents = check_files(owner_name, documents)
    existing = sum(1 for d in documents if d.get("file_exists"))
    missing = len(documents) - existing
    print(f"  Existing: {existing}, Missing: {missing}")

    # Step 3: Download missing
    if missing > 0:
        batch_download(owner_name, documents)

    # Step 4: Generate report
    report_result = generate_report(owner_name, address)
    has_report = bool(report_result.get("report_markdown"))

    duration = time.time() - start
    result.update({
        "result": "PASS" if has_report else "PARTIAL",
        "documents_found": len(documents),
        "documents_downloaded": existing + missing,
        "has_report": has_report,
        "duration": duration,
    })

    icon = "✅" if has_report else "⚠️"
    print(f"\n  {icon} Result: {result['result']} | {len(documents)} docs | {duration:.0f}s")
    return result


def main():
    print("=" * 60)
    print("CURE Sequential Test Runner")
    print(f"Testing {len(TEST_SUBJECTS)} subjects")
    print("=" * 60)

    if not check_server():
        print("ERROR: Server not running at localhost:5555")
        sys.exit(1)

    print("Server is online.")

    all_results = []
    for i, subject in enumerate(TEST_SUBJECTS):
        print(f"\n[{i+1}/{len(TEST_SUBJECTS)}]", end="")
        result = run_subject(subject)
        all_results.append(result)

        # Save incrementally
        with open("test_results/sequential_test_results.json", "w") as f:
            json.dump({"results": all_results, "timestamp": datetime.now().isoformat()}, f, indent=2)

    # Summary
    print(f"\n\n{'='*60}")
    print("FINAL SUMMARY")
    print("=" * 60)
    for r in all_results:
        icon = {"PASS": "✅", "PARTIAL": "⚠️", "NO_DOCS": "❌"}.get(r["result"], "?")
        docs = r.get("documents_found", 0)
        dur = r.get("duration", 0)
        print(f"  {icon} {r['label']:40s} | {docs:3d} docs | {dur:.0f}s | {r['result']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
