#!/usr/bin/env python3
"""
Standalone script to run OC Recorder search for Mastrangelo.
Works on Mac ARM (Apple Silicon).

HOW TO RUN:
  1. Place this file in the ROOT of the titlePro folder
     (same level as the 'src' folder, NOT inside src/titlepro)
  2. Open Terminal and run:
       cd /path/to/titlePro
       python3 run_mastrangelo.py
  3. A Chrome browser window will open and run the search automatically.
  4. Results saved to: titlePro/cure_titlepro_mastrangelo/search_results.json
"""

import sys
import os
import json
import glob

# ── Path setup ────────────────────────────────────────────────────────────────
# Works whether the script is in the root OR accidentally in src/titlepro
script_dir = os.path.dirname(os.path.abspath(__file__))
# Walk up until we find the 'src' folder
search_dir = script_dir
for _ in range(4):
    if os.path.isdir(os.path.join(search_dir, 'src')):
        break
    search_dir = os.path.dirname(search_dir)

src_path = os.path.join(search_dir, 'src')
sys.path.insert(0, src_path)
print(f"Using src path: {src_path}")

# ── Patch orange.py to use non-headless Chrome on Mac ─────────────────────────
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

def _mac_setup_driver(self):
    """Mac-compatible Chrome driver setup — non-headless, auto-finds chromedriver."""
    options = Options()
    # Non-headless so the site doesn't block us
    # options.add_argument("--headless=new")   # <-- disabled for Mac
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Find chromedriver on Mac (wdm cache)
    driver_path = None
    mac_patterns = [
        os.path.expanduser("~/.wdm/drivers/chromedriver/mac64/*/chromedriver-mac-arm64/chromedriver"),
        os.path.expanduser("~/.wdm/drivers/chromedriver/mac_arm64/*/chromedriver-mac-arm64/chromedriver"),
        os.path.expanduser("~/.wdm/drivers/chromedriver/mac64/*/chromedriver"),
        "/usr/local/bin/chromedriver",
        "/opt/homebrew/bin/chromedriver",
    ]
    for pattern in mac_patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            driver_path = matches[0]
            print(f"  Found ChromeDriver: {driver_path}")
            break

    try:
        if driver_path and os.path.exists(driver_path):
            service = Service(driver_path)
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            print("  No chromedriver found in known paths, trying system default...")
            self.driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"  Chrome setup error: {e}")
        print("  Trying webdriver-manager as fallback...")
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            wdm_path = ChromeDriverManager().install()
            # wdm sometimes returns the NOTICES file, not the binary
            if not wdm_path.endswith('chromedriver'):
                wdm_dir = os.path.dirname(wdm_path)
                wdm_path = os.path.join(wdm_dir, 'chromedriver')
            service = Service(wdm_path)
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception as e2:
            print(f"  webdriver-manager also failed: {e2}")
            raise

    from selenium.webdriver.support.ui import WebDriverWait
    self.driver.implicitly_wait(5)
    self.wait = WebDriverWait(self.driver, 15)
    print(f"  Browser initialized for {self.county_name} County")


# Monkey-patch before importing OrangeCountyRecorder
from titlepro.search.ca_recorder.counties import orange as orange_module
from titlepro.search.ca_recorder.counties.orange import OrangeCountyRecorder
OrangeCountyRecorder.setup_driver = _mac_setup_driver

# ── Search config ─────────────────────────────────────────────────────────────
names = ["MASTRANGELO ANTHONY", "MASTRANGELO GEORGIANN", "MASTRANGELO FAMILY TRUST"]
start_date = "01/01/2000"
end_date   = "04/12/2026"

output_dir  = os.path.join(search_dir, "cure_titlepro_mastrangelo")
output_file = os.path.join(output_dir, "search_results.json")
os.makedirs(output_dir, exist_ok=True)

print(f"\nSearching: {names}")
print(f"Date range: {start_date} → {end_date}")
print(f"Results will be saved to: {output_file}")
print("-" * 60)

# ── Run search ────────────────────────────────────────────────────────────────
recorder    = OrangeCountyRecorder(start_date=start_date, end_date=end_date)
all_results = {}

try:
    with recorder as r:
        print("Navigating to OC Recorder search page...")
        r.navigate_to_search()
        print("Search page loaded.\n")

        for name in names:
            print(f"Searching: {name}")
            try:
                results = r.search_name(name, partial_match=True)
                all_results[name] = results
                print(f"  → {len(results)} result(s) found")
                for i, doc in enumerate(results[:15]):
                    print(f"     [{i+1}] {doc}")
                if len(results) > 15:
                    print(f"     ... and {len(results)-15} more")
            except Exception as e:
                print(f"  ERROR: {e}")
                all_results[name] = []
            print()

except Exception as e:
    print(f"\nFATAL ERROR: {e}")
    import traceback
    traceback.print_exc()

# ── Save results ──────────────────────────────────────────────────────────────
total = sum(len(v) for v in all_results.values())
print("=" * 60)
print(f"Search complete. Total records found: {total}")

with open(output_file, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)

print(f"\nResults saved to:\n  {output_file}")
print("\nNow share that JSON file to generate the full title report.")
