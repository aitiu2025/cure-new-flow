"""
MBC Platform Property Tax Lookup (mptsweb.com)

Scrapes property tax information from the MBC/Municipal Payment platform
used by many California counties including Amador, Plumas, Lake, Kings, etc.

No CAPTCHA required (unlike Orange County).

County URLs are loaded from config/county_tax_urls.json (platform == "mbc").

Usage:
    from titlepro.tax.mbc_tax_scraper import lookup_mbc_tax
    result = lookup_mbc_tax("015520016000", "amador")
"""

import time
import re
import json
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException,
        ElementClickInterceptedException, StaleElementReferenceException
    )
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False


# ---------------------------------------------------------------------------
# Load MBC county URLs from the centralized JSON config
# ---------------------------------------------------------------------------

def _load_mbc_urls_from_config() -> Dict[str, str]:
    """
    Build the MBC_COUNTY_URLS dict from config/county_tax_urls.json.

    Filters for entries where platform == 'mbc' and maps
    county_key -> base_url.  Falls back to a hardcoded dict if the
    config file is unavailable so the module remains functional.
    """
    config_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "county_tax_urls.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        counties = data.get("counties", {})
        mbc_urls = {}
        for key, cfg in counties.items():
            if cfg.get("platform") == "mbc":
                mbc_urls[key] = cfg["base_url"]
        if mbc_urls:
            return mbc_urls
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        print(f"[mbc-tax] Warning: Could not load config from {config_path}: {exc}", flush=True)

    # Fallback: hardcoded defaults so the module works even without the config file
    return {
        "amador":     "https://common1.mptsweb.com/MBC/amador/tax/search",
        "plumas":     "https://common1.mptsweb.com/MBC/plumas/tax/search",
        "tehama":     "https://common1.mptsweb.com/mbc/tehama/tax/search",
        "kings":      "https://common1.mptsweb.com/MBC/kings/tax/search",
        "lake":       "https://common2.mptsweb.com/MBC/lake/tax/search",
        "mono":       "https://common2.mptsweb.com/mbc/mono/tax/search",
        "san_benito": "https://common2.mptsweb.com/mbc/sanbenito/tax/search",
        "butte":      "https://common2.mptsweb.com/mbc/butte/tax/search",
        "placer":     "https://common3.mptsweb.com/mbc/placer/tax/search",
        "tulare":     "https://common2.mptsweb.com/MBC/tulare/tax/search",
    }


# MBC platform county URLs
# Loaded from config/county_tax_urls.json; falls back to hardcoded defaults
MBC_COUNTY_URLS = _load_mbc_urls_from_config()


def log(msg: str) -> None:
    print(f"[mbc-tax] {msg}", flush=True)


def build_driver(headless: bool = True) -> "webdriver.Chrome":
    """Build a Chrome WebDriver for MBC tax lookup."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Anti-detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if USE_WEBDRIVER_MANAGER:
        raw_path = Path(ChromeDriverManager().install())
        driver_path = raw_path
        if not raw_path.name.startswith("chromedriver"):
            candidate = raw_path.parent / "chromedriver"
            if candidate.exists():
                driver_path = candidate
        try:
            driver_path.chmod(driver_path.stat().st_mode | 0o755)
        except PermissionError:
            pass
        service = Service(str(driver_path))
    else:
        service = Service()

    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver


def clean_apn(apn: str) -> str:
    """Remove dashes, spaces, and non-digit chars from APN for search input."""
    return re.sub(r"[^0-9]", "", apn)


def parse_currency(text: str) -> Optional[str]:
    """Extract a dollar amount like $1,234.56 from text."""
    match = re.search(r"\$[\d,]+\.?\d*", text)
    return match.group(0) if match else None


def lookup_mbc_tax(apn: str, county: str, headless: bool = True) -> Dict:
    """
    Look up property tax information from the MBC platform.

    Args:
        apn: Assessor's Parcel Number (any format)
        county: County name (lowercase, e.g., "amador")
        headless: Run browser invisibly (default True)

    Returns:
        Dict with tax information or error details
    """
    if not SELENIUM_AVAILABLE:
        return {"success": False, "error": "Selenium not installed"}

    county_key = county.lower().strip()
    # Remove common suffixes
    for suffix in [" county", " county, ca", ", ca"]:
        if county_key.endswith(suffix):
            county_key = county_key[:-len(suffix)]
    # Normalize spaces to underscores to match config keys (e.g. "san benito" -> "san_benito")
    county_key = county_key.replace(" ", "_")

    base_url = MBC_COUNTY_URLS.get(county_key)
    if not base_url:
        return {
            "success": False,
            "status": "TAX_NO_RUNNER",
            "notes": (
                "Tax lookup runner not configured for this county on the "
                "MBC platform. Manual portal verification required."
            ),
            "error": "",
        }

    cleaned_apn = clean_apn(apn)
    if len(cleaned_apn) < 6:
        return {"success": False, "error": f"APN too short after cleaning: '{cleaned_apn}' (need at least 6 digits)"}

    log(f"Looking up tax for APN {apn} (cleaned: {cleaned_apn}) in {county_key} county")
    log(f"URL: {base_url}")

    driver = None
    result = {
        "success": False,
        "apn": apn,
        "clean_apn": cleaned_apn,
        "county": county_key,
        "lookup_timestamp": datetime.now().isoformat(),
        "verification_url": base_url,
        "data_source": f"{county_key.title()} County Tax Collector (MBC Platform)",
    }

    try:
        driver = build_driver(headless=headless)
        wait = WebDriverWait(driver, 15)

        # Step 1: Navigate to the search page
        log("Navigating to MBC tax search page...")
        driver.get(base_url)
        time.sleep(2)

        # Step 2: Select "Fee Parcel" search mode
        # MBC uses radio buttons or tabs for search type
        log("Selecting Fee Parcel search mode...")
        try:
            # Try clicking the Fee Parcel radio/tab
            fee_parcel_selectors = [
                (By.XPATH, "//label[contains(text(), 'Fee Parcel')]"),
                (By.XPATH, "//input[@value='FeeParcel' or @value='fee_parcel']"),
                (By.XPATH, "//*[contains(text(), 'FEE PARCEL')]"),
                (By.XPATH, "//a[contains(text(), 'Fee Parcel')]"),
                (By.CSS_SELECTOR, "[data-search-type='FeeParcel']"),
            ]
            clicked = False
            for selector in fee_parcel_selectors:
                try:
                    el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(selector))
                    el.click()
                    clicked = True
                    log("Fee Parcel search mode selected")
                    break
                except (TimeoutException, NoSuchElementException):
                    continue

            if not clicked:
                log("Fee Parcel selector not found - proceeding with default search mode")
        except Exception as e:
            log(f"Warning: Could not select Fee Parcel mode: {e}")

        time.sleep(1)

        # Step 3: Set Roll Year to current year if dropdown exists
        try:
            year_selectors = [
                (By.ID, "RollYear"),
                (By.NAME, "RollYear"),
                (By.CSS_SELECTOR, "select[name*='year' i], select[id*='year' i], select[id*='roll' i]"),
            ]
            for selector in year_selectors:
                try:
                    year_el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(selector))
                    select = Select(year_el)
                    # Select the first (most recent) option
                    current_year = select.first_selected_option.text.strip()
                    log(f"Roll year: {current_year}")
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
        except Exception as e:
            log(f"Warning: Could not check roll year: {e}")

        # Step 4: Enter APN in search field
        log(f"Entering APN: {cleaned_apn}")
        input_found = False
        search_input_selectors = [
            (By.ID, "SearchValue"),
            (By.ID, "SearchParcel"),
            (By.NAME, "SearchParcel"),
            (By.ID, "txtSearch"),
            (By.NAME, "txtSearch"),
            (By.CSS_SELECTOR, "input[type='text'][placeholder*='arcel' i]"),
            (By.CSS_SELECTOR, "input[type='text'][placeholder*='APN' i]"),
            (By.CSS_SELECTOR, "input[type='text'][placeholder*='SEARCH TERM' i]"),
            (By.CSS_SELECTOR, "input[type='search']"),
            (By.CSS_SELECTOR, "input.form-control[type='text']"),
            (By.CSS_SELECTOR, "#searchInput"),
            (By.XPATH, "//input[@type='text' and not(@type='hidden')]"),
        ]

        for selector in search_input_selectors:
            try:
                input_el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(selector))
                input_el.clear()
                input_el.send_keys(cleaned_apn)
                input_found = True
                log(f"APN entered using selector: {selector}")
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if not input_found:
            # Last resort: find any visible text input
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']:not([style*='display:none'])")
                for inp in inputs:
                    if inp.is_displayed():
                        inp.clear()
                        inp.send_keys(cleaned_apn)
                        input_found = True
                        log("APN entered via fallback visible input")
                        break
            except Exception:
                pass

        if not input_found:
            result["error"] = "Could not find search input field on MBC page"
            return result

        time.sleep(0.5)

        # Step 5: Click Search button
        log("Clicking Search button...")
        search_btn_selectors = [
            (By.ID, "SearchSubmit"),
            (By.CSS_SELECTOR, "button#SearchSubmit"),
            (By.XPATH, "//button[text()='SEARCH']"),
            (By.CSS_SELECTOR, "button[type='submit'].btn-default"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.XPATH, "//button[contains(text(), 'Search')]"),
            (By.XPATH, "//input[@value='Search']"),
            (By.CSS_SELECTOR, ".btn-search, .search-btn, #btnSearch"),
            (By.CSS_SELECTOR, "button.btn-primary"),
        ]

        btn_clicked = False
        for selector in search_btn_selectors:
            try:
                btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable(selector))
                try:
                    btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", btn)
                btn_clicked = True
                log("Search submitted")
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if not btn_clicked:
            # Try pressing Enter on the input field
            try:
                from selenium.webdriver.common.keys import Keys
                input_el.send_keys(Keys.RETURN)
                btn_clicked = True
                log("Search submitted via Enter key")
            except Exception:
                result["error"] = "Could not click search button"
                return result

        # Step 6: Wait for results
        log("Waiting for results...")
        time.sleep(3)

        # Step 7: Check for "no results" message
        page_text = driver.page_source
        no_result_patterns = [
            "no results", "no records", "not found", "no matching",
            "no parcels", "0 results", "no data"
        ]
        for pattern in no_result_patterns:
            if pattern in page_text.lower():
                result["error"] = f"No tax records found for APN {apn} in {county_key.title()} County"
                return result

        # Step 8: Try to click into the parcel detail if results are in a table
        try:
            # MBC shows "View Details" links for each result
            row_selectors = [
                (By.XPATH, "//a[contains(text(), 'View Details')]"),
                (By.XPATH, "//a[contains(@href, '/tax/main/')]"),
                (By.CSS_SELECTOR, "table tbody tr td a"),
                (By.CSS_SELECTOR, ".search-results a"),
                (By.CSS_SELECTOR, "table.table tbody tr:first-child"),
                (By.XPATH, "//table//tbody//tr[1]//a"),
                (By.XPATH, "//a[contains(@href, 'main')]"),
            ]
            for selector in row_selectors:
                try:
                    link = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(selector))
                    link.click()
                    log("Clicked into parcel detail page")
                    time.sleep(3)
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
        except Exception as e:
            log(f"Note: Could not click detail link (may already be on detail page): {e}")

        # Step 9: Extract tax data from the page
        log("Extracting tax information...")
        page_text = driver.find_element(By.TAG_NAME, "body").text

        # Extract tax year - MBC detail page shows "YEAR\n2025" format
        tax_year_match = re.search(r"(?:Tax|Roll|Fiscal)\s*Year[:\s]*(\d{4}[\-/]\d{2,4})", page_text, re.IGNORECASE)
        if tax_year_match:
            result["tax_year"] = tax_year_match.group(1)
        else:
            # MBC detail page format: "YEAR\n2025"
            year_match = re.search(r"YEAR\s*\n?\s*(\d{4})", page_text, re.IGNORECASE)
            if year_match:
                yr = int(year_match.group(1))
                result["tax_year"] = f"{yr}-{yr + 1}"
            else:
                # Fallback: Roll Year format
                year_match = re.search(r"Roll Year[:\s]*(\d{4})", page_text, re.IGNORECASE)
                if year_match:
                    yr = int(year_match.group(1))
                    result["tax_year"] = f"{yr}-{yr + 1}"

        # Extract total tax / annual tax
        # MBC detail page shows "Totals - 1st and 2nd Installments\nTotal Due\n$2,787.66"
        total_patterns = [
            r"Totals\s*-\s*1st\s*and\s*2nd.*?Total\s*Due\s*\n?\$?([\d,]+\.?\d*)",
            r"(?:Total|Annual)\s*(?:Tax|Due|Amount)[:\s]*\$?([\d,]+\.?\d*)",
            r"(?:Tax\s*Amount|Total\s*Taxes)[:\s]*\$?([\d,]+\.?\d*)",
            r"(?:Secured\s*)?Total[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pat in total_patterns:
            match = re.search(pat, page_text, re.IGNORECASE | re.DOTALL)
            if match:
                result["annual_tax"] = f"${match.group(1)}"
                break

        # Extract installment amounts and statuses
        # MBC detail format: "1st Installment\nPaid Status\nPAID\n...\nTotal Due\n$1,393.83"
        inst1_match = re.search(r"1st\s*Installment.*?Total\s*Due\s*\n?\$?([\d,]+\.?\d*)", page_text, re.IGNORECASE | re.DOTALL)
        if inst1_match:
            result["first_installment_amount"] = f"${inst1_match.group(1)}"
        else:
            inst1_patterns = [
                r"1st\s*Install(?:ment)?[:\s]*\$?([\d,]+\.?\d*)",
                r"First\s*Install(?:ment)?[:\s]*\$?([\d,]+\.?\d*)",
            ]
            for pat in inst1_patterns:
                match = re.search(pat, page_text, re.IGNORECASE)
                if match:
                    result["first_installment_amount"] = f"${match.group(1)}"
                    break

        inst2_match = re.search(r"2nd\s*Installment.*?Total\s*Due\s*\n?\$?([\d,]+\.?\d*)", page_text, re.IGNORECASE | re.DOTALL)
        if inst2_match:
            result["second_installment_amount"] = f"${inst2_match.group(1)}"
        else:
            inst2_patterns = [
                r"2nd\s*Install(?:ment)?[:\s]*\$?([\d,]+\.?\d*)",
                r"Second\s*Install(?:ment)?[:\s]*\$?([\d,]+\.?\d*)",
            ]
            for pat in inst2_patterns:
                match = re.search(pat, page_text, re.IGNORECASE)
                if match:
                    result["second_installment_amount"] = f"${match.group(1)}"
                    break

        # Extract payment status - MBC shows "Paid Status\nPAID" or "Paid Status\nDUE"
        inst1_status_match = re.search(r"1st\s*Installment.*?Paid\s*Status\s*\n?\s*(PAID|DUE|UNPAID|DELINQUENT)", page_text, re.IGNORECASE | re.DOTALL)
        if inst1_status_match:
            status = inst1_status_match.group(1).upper()
            result["first_installment_status"] = "PAID" if status == "PAID" else "UNPAID"
        elif re.search(r"1st.*(?:PAID|Paid)", page_text):
            result["first_installment_status"] = "PAID"
        elif re.search(r"1st.*(?:UNPAID|Unpaid|Due|DELINQUENT)", page_text, re.IGNORECASE):
            result["first_installment_status"] = "UNPAID"

        inst2_status_match = re.search(r"2nd\s*Installment.*?Paid\s*Status\s*\n?\s*(PAID|DUE|UNPAID|DELINQUENT)", page_text, re.IGNORECASE | re.DOTALL)
        if inst2_status_match:
            status = inst2_status_match.group(1).upper()
            result["second_installment_status"] = "PAID" if status == "PAID" else "UNPAID"
        elif re.search(r"2nd.*(?:PAID|Paid)", page_text):
            result["second_installment_status"] = "PAID"
        elif re.search(r"2nd.*(?:UNPAID|Unpaid|Due|DELINQUENT)", page_text, re.IGNORECASE):
            result["second_installment_status"] = "UNPAID"

        # Extract assessed values
        assessed_patterns = [
            r"(?:Total|Net)\s*(?:Assessed|Taxable)\s*Value[:\s]*\$?([\d,]+\.?\d*)",
            r"Assessed\s*Value[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pat in assessed_patterns:
            match = re.search(pat, page_text, re.IGNORECASE)
            if match:
                result["assessed_value_total"] = f"${match.group(1)}"
                break

        land_match = re.search(r"Land[:\s]*\$?([\d,]+\.?\d*)", page_text)
        if land_match:
            result["assessed_value_land"] = f"${land_match.group(1)}"

        imp_match = re.search(r"Improvement[s]?[:\s]*\$?([\d,]+\.?\d*)", page_text)
        if imp_match:
            result["assessed_value_improvements"] = f"${imp_match.group(1)}"

        # Extract property address if shown
        addr_match = re.search(r"(?:Property|Situs)\s*Address[:\s]*(.+?)(?:\n|$)", page_text, re.IGNORECASE)
        if addr_match:
            result["property_address"] = addr_match.group(1).strip()

        # Check delinquency
        if re.search(r"delinquen", page_text, re.IGNORECASE):
            result["delinquent"] = True
        else:
            result["delinquent"] = False

        # Determine if we got meaningful data
        has_data = any(k in result for k in ["annual_tax", "first_installment_amount", "tax_year", "assessed_value_total"])
        if has_data:
            result["success"] = True
            result["first_installment_due"] = "December 10"
            result["second_installment_due"] = "April 10"
            log(f"Tax lookup successful: {result.get('annual_tax', 'N/A')} for {result.get('tax_year', 'N/A')}")
        else:
            # Save page text for debugging
            result["error"] = "Could not parse tax data from MBC results page"
            result["_page_text_snippet"] = page_text[:2000]
            log("Warning: Could not extract meaningful tax data from page")

    except TimeoutException as e:
        result["error"] = f"Timeout waiting for MBC page to load: {e}"
        log(f"Timeout error: {e}")
    except Exception as e:
        result["error"] = f"MBC tax lookup failed: {e}"
        log(f"Error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return result


def get_mbc_counties():
    """Return list of supported MBC platform counties."""
    return list(MBC_COUNTY_URLS.keys())


def is_mbc_county(county: str) -> bool:
    """Check if a county uses the MBC platform."""
    county_key = county.lower().strip()
    for suffix in [" county", " county, ca", ", ca"]:
        if county_key.endswith(suffix):
            county_key = county_key[:-len(suffix)]
    # Normalize spaces to underscores to match config keys (e.g. "san benito" -> "san_benito")
    county_key = county_key.replace(" ", "_")
    return county_key in MBC_COUNTY_URLS


# CLI entry point for testing
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Look up property tax via MBC platform")
    parser.add_argument("apn", help="Assessor's Parcel Number")
    parser.add_argument("--county", "-c", default="amador", help="County name (default: amador)")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    args = parser.parse_args()

    result = lookup_mbc_tax(args.apn, args.county, headless=not args.visible)
    print(json.dumps(result, indent=2))
