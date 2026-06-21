#!/usr/bin/env python3
"""
Test script to verify multi-county search functionality.
Run this to test different counties with subjects from the Excel file.

Usage:
    python3 test_counties.py
"""

import requests
import json
import sys

API_BASE = "http://localhost:5555"

# Test subjects from the Excel file
TEST_CASES = [
    # County, Name, Description
    ("orange", "Wong Jenson", "Ethnic name from Excel"),
    ("orange", "Nelson Shawn", "Common name from Excel"),
    ("amador", "Rosenkrans Terry", "Ethnic name from Excel"),
    ("amador", "Lamb Gizelle", "Common name from Excel"),
    ("stanislaus", "Jones Brett", "Common name from Excel"),
    ("stanislaus", "Sobowale Olamilekan", "Ethnic name from Excel"),
    ("imperial", "Jaramillo Enrizue", "Ethnic name from Excel"),
    ("calaveras", "Foster Kacey", "Common name from Excel"),
    ("merced", "Anderson Renee", "Common name from Excel"),
]


def test_search(county: str, name: str, description: str):
    """Test a single search."""
    print(f"\n{'='*60}")
    print(f"Testing: {county.upper()} - {name}")
    print(f"({description})")
    print('='*60)

    payload = {
        "owner_name": name,
        "county": county,
        "start_date": "01/01/2015",
        "end_date": "01/26/2026"
    }

    try:
        r = requests.post(f"{API_BASE}/search-recorder", json=payload, timeout=300)
        data = r.json()

        success = data.get("success", False)
        total = data.get("summary", {}).get("total_unique", 0)
        docs = data.get("documents", [])

        print(f"Success: {success}")
        print(f"Documents found: {total}")

        if docs:
            print("\nFirst 3 documents:")
            for d in docs[:3]:
                print(f"  {d.get('document_number')}: {d.get('document_type')} ({d.get('recording_date')})")
        else:
            # Show search details
            details = data.get("search_details", [])
            if details:
                print("\nSearch attempts:")
                for detail in details:
                    print(f"  Name searched: {detail.get('name')}")
                    for attempt in detail.get("attempts", []):
                        label = attempt.get("label", "")
                        unique = attempt.get("total_unique", 0)
                        modes = attempt.get("mode_counts", {})
                        print(f"    {label}: {unique} unique docs")
                        if modes:
                            for mode, count in modes.items():
                                print(f"      {mode}: {count}")

        return total > 0

    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to server. Is it running on localhost:5555?")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    print("="*60)
    print("CURE Multi-County Search Test")
    print("="*60)

    # Check server status
    try:
        r = requests.get(f"{API_BASE}/status", timeout=5)
        status = r.json()
        print(f"Server: {status.get('status')}")
        print(f"Multi-county: {status.get('multi_county_available')}")
        print(f"Supported counties: {status.get('supported_counties')}")
    except:
        print("ERROR: Server not running. Start it with:")
        print("  cd titlePro && python3 titlepro_api_server.py")
        sys.exit(1)

    # Run tests
    results = []
    for county, name, desc in TEST_CASES:
        success = test_search(county, name, desc)
        results.append((county, name, success))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed = sum(1 for _, _, s in results if s)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    print("\nResults by county:")
    for county, name, success in results:
        status = "✓ FOUND" if success else "✗ 0 docs"
        print(f"  {county}: {name} - {status}")

    if passed < total:
        print("\nNote: Some searches returned 0 documents.")
        print("This may be because:")
        print("  1. The borrower has no recorded documents in that county")
        print("  2. The date range doesn't cover their transactions")
        print("  3. The county website structure differs from Orange County")


if __name__ == "__main__":
    main()
