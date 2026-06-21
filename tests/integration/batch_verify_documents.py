"""
Batch verify which documents are available on TitlePro.
This will attempt to download each document and report the results.
"""

import sys
import time
from pathlib import Path

from titlepro.download.selenium_downloader import download_document

# Documents to verify - extracted from CURE.html
DOCUMENTS_TO_VERIFY = [
    {"num": "2021000676044", "year": "2021", "type": "RECONVEYANCE"},
    {"num": "2021000666293", "year": "2021", "type": "RECONVEYANCE"},
    {"num": "2019000538907", "year": "2019", "type": "RECONVEYANCE"},
    {"num": "2012000628593", "year": "2012", "type": "RECONVEYANCE"},
    {"num": "2010000482779", "year": "2010", "type": "QUITCLAIM DEED"},
    {"num": "2005000744648", "year": "2005", "type": "LIS PENDENS"},
]

def main():
    print("=" * 70)
    print("TitlePro Document Availability Verification")
    print("=" * 70)
    print(f"Testing {len(DOCUMENTS_TO_VERIFY)} documents...")
    print()

    results = []

    for i, doc in enumerate(DOCUMENTS_TO_VERIFY, 1):
        print(f"\n[{i}/{len(DOCUMENTS_TO_VERIFY)}] Testing: {doc['num']} ({doc['year']}) - {doc['type']}")
        print("-" * 50)

        try:
            result = download_document(
                doc_num=doc["num"],
                year=doc["year"],
                headless=False,  # Show browser so you can watch
                owner_name="Kwa_Danny"
            )

            doc["result"] = result
            doc["available"] = result["status"] in ["success", "warning"] and len(result.get("files", [])) > 0
            doc["files"] = result.get("files", [])
            doc["message"] = result.get("message", "")

            if doc["available"]:
                print(f"  ✓ AVAILABLE - Files: {', '.join(doc['files'])}")
            else:
                print(f"  ✗ NOT AVAILABLE - {doc['message']}")

        except Exception as e:
            doc["available"] = False
            doc["message"] = str(e)
            doc["files"] = []
            print(f"  ✗ ERROR - {e}")

        results.append(doc)

        # Small delay between requests to be nice to the server
        if i < len(DOCUMENTS_TO_VERIFY):
            print("  Waiting 3 seconds before next document...")
            time.sleep(3)

    # Print summary
    print("\n" + "=" * 70)
    print("VERIFICATION RESULTS SUMMARY")
    print("=" * 70)

    available_count = sum(1 for d in results if d["available"])
    print(f"\nAvailable: {available_count}/{len(results)}")
    print()

    print("Document Status:")
    print("-" * 70)
    for doc in results:
        status = "✓ AVAILABLE" if doc["available"] else "✗ NOT AVAILABLE"
        files = ", ".join(doc["files"]) if doc["files"] else "N/A"
        print(f"  {doc['num']} ({doc['year']}) {doc['type']}")
        print(f"    Status: {status}")
        print(f"    Files: {files}")
        print()

    # Generate update code for CURE.html
    print("\n" + "=" * 70)
    print("SUGGESTED documentsData UPDATE FOR CURE.html:")
    print("=" * 70)
    for doc in results:
        if doc["available"]:
            filename = doc["files"][0] if doc["files"] else f"{doc['num']}.pdf"
            print(f"{{ num: '{doc['num']}', type: '{doc['type']}', typeClass: 'recon', date: 'XX/XX/XXXX', status: '✓ Downloaded', available: true, filename: '{filename}' }},")
        else:
            print(f"{{ num: '{doc['num']}', type: '{doc['type']}', typeClass: 'recon', date: 'XX/XX/XXXX', status: '✗ Not on TitlePro', available: false }},")

if __name__ == "__main__":
    main()
