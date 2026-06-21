#!/usr/bin/env python3
"""
Standalone script to run OC Recorder search for Mastrangelo.
Bypasses the API server threading issues.
"""
import sys
import os
import json

sys.path.insert(0, '/home/ubuntu/titlePro/src')

from titlepro.search.ca_recorder.counties.orange import OrangeCountyRecorder

names = ["MASTRANGELO ANTHONY", "MASTRANGELO GEORGIANN", "MASTRANGELO FAMILY TRUST"]
start_date = "01/01/2000"
end_date = "04/12/2026"
output_file = "/home/ubuntu/cure_titlepro_mastrangelo/search_results.json"

print(f"Starting OC Recorder search for: {names}")
print(f"Date range: {start_date} to {end_date}")
print("-" * 60)

recorder = OrangeCountyRecorder(start_date=start_date, end_date=end_date)

all_results = {}

with recorder as r:
    print("Browser initialized, navigating to search page...")
    r.navigate_to_search()
    print("Search page loaded.")
    
    for name in names:
        print(f"\nSearching for: {name}")
        try:
            results = r.search_name(name, partial_match=True)
            all_results[name] = results
            print(f"  Found {len(results)} results for {name}")
            for doc in results[:5]:
                print(f"    - {doc}")
        except Exception as e:
            print(f"  ERROR searching {name}: {e}")
            all_results[name] = []

print("\n" + "=" * 60)
print(f"Total searches complete. Saving to {output_file}")

os.makedirs(os.path.dirname(output_file), exist_ok=True)
with open(output_file, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)

print(f"Results saved to {output_file}")
print("Done.")
