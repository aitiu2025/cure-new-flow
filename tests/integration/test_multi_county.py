#!/usr/bin/env python3
"""
Test script for CURE Multi-County System.
Tests real borrower searches across multiple counties.
"""

import requests
import json
import time
import sys

API_BASE = "http://localhost:5555"

# Test cases from the spreadsheet - real borrower data
TEST_CASES = [
    {
        "county": "orange",
        "owner_name": "Wong Jenson",
        "description": "Orange County - Wong Jenson & Phan Wong"
    },
    {
        "county": "amador",
        "owner_name": "Rosenkrans Terry",
        "description": "Amador County - Terry & Valerie Rosenkrans"
    },
    {
        "county": "calaveras",
        "owner_name": "Foster Kacey",
        "description": "Calaveras County - Kacey J Foster"
    },
    {
        "county": "imperial",
        "owner_name": "Brown Christina",
        "description": "Imperial County - Christina N Brown"
    },
    {
        "county": "stanislaus",
        "owner_name": "Jones Brett",
        "description": "Stanislaus County - Brett Davis Jones"
    },
]


def check_server():
    """Check if API server is running."""
    try:
        r = requests.get(f"{API_BASE}/status", timeout=5)
        data = r.json()
        print(f"Server Status: {data.get('status')}")
        print(f"Multi-County Available: {data.get('multi_county_available')}")
        print(f"Supported Counties: {data.get('supported_counties')}")
        return data.get('status') == 'online'
    except Exception as e:
        print(f"Server not available: {e}")
        return False


def run_search(county, owner_name, start_date="01/01/2015", end_date="01/23/2026"):
    """Run a recorder search."""
    payload = {
        "owner_name": owner_name,
        "county": county,
        "start_date": start_date,
        "end_date": end_date
    }

    print(f"\n  Sending request to {API_BASE}/search-recorder")
    print(f"  Payload: {json.dumps(payload)}")

    try:
        r = requests.post(
            f"{API_BASE}/search-recorder",
            json=payload,
            timeout=300  # 5 minute timeout for Selenium operations
        )
        return r.json()
    except requests.Timeout:
        return {"success": False, "error": "Request timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_tests(test_indices=None):
    """Run specified tests or all tests."""
    print("=" * 70)
    print("CURE Multi-County End-to-End Test")
    print("=" * 70)

    # Check server
    print("\nChecking API server...")
    if not check_server():
        print("\nERROR: API server not running. Start it with:")
        print("  python titlepro_api_server.py")
        return

    # Determine which tests to run
    if test_indices:
        cases = [TEST_CASES[i] for i in test_indices if i < len(TEST_CASES)]
    else:
        cases = TEST_CASES

    print(f"\nRunning {len(cases)} test(s)...")

    results = []
    for i, tc in enumerate(cases):
        print(f"\n{'=' * 70}")
        print(f"TEST {i+1}: {tc['description']}")
        print(f"{'=' * 70}")
        print(f"  County: {tc['county']}")
        print(f"  Owner: {tc['owner_name']}")

        start_time = time.time()
        result = run_search(tc['county'], tc['owner_name'])
        elapsed = time.time() - start_time

        success = result.get('success', False)
        doc_count = result.get('summary', {}).get('total_unique', 0)

        print(f"\n  Result:")
        print(f"    Success: {success}")
        print(f"    Time: {elapsed:.1f} seconds")

        if success:
            print(f"    Documents found: {doc_count}")
            county_name = result.get('search_params', {}).get('county_name', 'Unknown')
            print(f"    County searched: {county_name}")

            # Show sample documents
            docs = result.get('documents', [])[:5]
            if docs:
                print(f"    Sample documents:")
                for doc in docs:
                    doc_num = doc.get('document_number', 'N/A')
                    doc_type = doc.get('document_type', 'UNKNOWN')
                    rec_date = doc.get('recording_date', 'N/A')
                    print(f"      - {doc_num}: {doc_type} ({rec_date})")
                if doc_count > 5:
                    print(f"      ... and {doc_count - 5} more")
        else:
            error = result.get('error', 'Unknown error')
            print(f"    Error: {error}")

        results.append({
            "test": tc['description'],
            "success": success,
            "documents": doc_count,
            "time": elapsed
        })

        # Small delay between tests
        if i < len(cases) - 1:
            print("\n  Waiting 3 seconds before next test...")
            time.sleep(3)

    # Summary
    print(f"\n{'=' * 70}")
    print("TEST SUMMARY")
    print(f"{'=' * 70}")

    passed = sum(1 for r in results if r['success'])
    total_docs = sum(r['documents'] for r in results)
    total_time = sum(r['time'] for r in results)

    print(f"Tests passed: {passed}/{len(results)}")
    print(f"Total documents found: {total_docs}")
    print(f"Total time: {total_time:.1f} seconds")

    for r in results:
        status = "✓ PASS" if r['success'] else "✗ FAIL"
        print(f"  {status}: {r['test']} ({r['documents']} docs, {r['time']:.1f}s)")


if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) > 1:
        # Run specific tests by index
        indices = [int(x) for x in sys.argv[1:] if x.isdigit()]
        run_tests(indices)
    else:
        # Run all tests
        run_tests()
