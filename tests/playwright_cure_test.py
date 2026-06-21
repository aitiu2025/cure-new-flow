#!/usr/bin/env python3
"""
CURE Full Pipeline Playwright Test
Runs all 21 test subjects through the CURE website end-to-end.
Tests: Search → Download → Analyze → Report generation
"""

import json
import time
import os
import sys
import base64
import io
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─── Configuration ───────────────────────────────────────────────────────────
CURE_URL = "http://localhost:5555/"
PER_TEST_TIMEOUT_MS = 15 * 60 * 1000  # 15 minutes per test
STEP_POLL_INTERVAL_MS = 2000  # Check step status every 2 seconds
STEP_TIMEOUT_MS = 12 * 60 * 1000  # 12 minutes max for all steps to finish
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_results")

# ─── Test Subjects (from summary_20260203_200919.json) ───────────────────────
TEST_SUBJECTS = [
    {"test_id": 1, "county_id": "calaveras", "county": "Calaveras", "platform": "recorderworks",
     "borrowers": ["Samantha De Martin", "Andrew Chaffey"],
     "address": "2676 Karooked Rd", "city": "Arnold"},
    {"test_id": 2, "county_id": "del_norte", "county": "Del Norte", "platform": "tyler",
     "borrowers": ["Robert Flock", "Elizabeth Valley"],
     "address": "1780 Alamador Dr", "city": "Crescent City"},
    {"test_id": 3, "county_id": "fresno", "county": "Fresno", "platform": "tyler",
     "borrowers": ["Nicole Itzel Zamora", "Kawon Chidozie"],
     "address": "Satalite Lane", "city": "Fresno"},
    {"test_id": 4, "county_id": "humboldt", "county": "Humboldt", "platform": "tyler",
     "borrowers": ["Jason Harrell", "Yezdan Martinez Tachines"],
     "address": "1806 Aghist Street", "city": "Eureka"},
    {"test_id": 5, "county_id": "imperial", "county": "Imperial", "platform": "recorderworks",
     "borrowers": ["Enrique Jaramillo", "Cynthia Jaramillo"],
     "address": "906 Corral St", "city": "Calexico"},
    {"test_id": 6, "county_id": "inyo", "county": "Inyo", "platform": "tyler",
     "borrowers": ["Rosario Loer", "Gale Loer"],
     "address": "", "city": "Bakersfield"},
    {"test_id": 7, "county_id": "kings", "county": "Kings", "platform": "tyler",
     "borrowers": ["Alexander Carothers", "Kathleen Lee Carothers"],
     "address": "977 Folletts", "city": "Lemoore"},
    {"test_id": 8, "county_id": "lake", "county": "Lake", "platform": "tyler",
     "borrowers": ["Fred A Dill"],
     "address": "10832 Borein Big Oak", "city": "Kelseyville"},
    {"test_id": 9, "county_id": "madera", "county": "Madera", "platform": "tyler",
     "borrowers": ["Lila Corona", "Katherine Pomewhyz"],
     "address": "45840 W Honcut", "city": "Visalia"},
    {"test_id": 10, "county_id": "merced", "county": "Merced", "platform": "recorderworks",
     "borrowers": ["Dawna Goprian"],
     "address": "2994 Cordial", "city": "Merced"},
    {"test_id": 11, "county_id": "monterey", "county": "Monterey", "platform": "tyler",
     "borrowers": ["James E Hodge", "Wendy A Hodge"],
     "address": "13000 Fennel", "city": "East Garrison"},
    {"test_id": 12, "county_id": "san_benito", "county": "San Benito", "platform": "tyler",
     "borrowers": ["Maria Magdalena Carrillo", "Ernesto Carrillo"],
     "address": "580 Harborview", "city": "Laconia"},
    {"test_id": 13, "county_id": "san_joaquin", "county": "San Joaquin", "platform": "tyler",
     "borrowers": ["Julie A Parent", "Steven J Parent"],
     "address": "2030 Heavenly Way", "city": "Lodi"},
    {"test_id": 14, "county_id": "san_luis_obispo", "county": "San Luis Obispo", "platform": "tyler",
     "borrowers": ["Daniel Coal Porto", "Molly Holland"],
     "address": "50 Summers Dr", "city": "Templeton"},
    {"test_id": 15, "county_id": "santa_cruz", "county": "Santa Cruz", "platform": "tyler",
     "borrowers": ["Michael L Kim", "Monica Kim", "Andrew Franklin"],
     "address": "10636 Alba Rd", "city": "Ben Lomond"},
    {"test_id": 16, "county_id": "sierra", "county": "Sierra", "platform": "tyler",
     "borrowers": ["Barbara Parks"],
     "address": "", "city": "Weed"},
    {"test_id": 17, "county_id": "stanislaus", "county": "Stanislaus", "platform": "recorderworks",
     "borrowers": ["Clama Lyn Tor Sobowale"],
     "address": "3200 Crimble", "city": "Modesto"},
    {"test_id": 18, "county_id": "trinity", "county": "Trinity", "platform": "tyler",
     "borrowers": ["Wesley Paul Schriner", "Anne Marie Schriner"],
     "address": "360 Marylino", "city": "Weaverville"},
    {"test_id": 19, "county_id": "tulare", "county": "Tulare", "platform": "tyler",
     "borrowers": ["James Gregory Saavedra", "Maria Lisa Saavedra"],
     "address": "30039 W Porterie Ave", "city": "Visalia"},
    {"test_id": 20, "county_id": "tuolumne", "county": "Tuolumne", "platform": "tyler",
     "borrowers": ["Ann Hegde"],
     "address": "", "city": ""},
    {"test_id": 21, "county_id": "yolo", "county": "Yolo", "platform": "tyler",
     "borrowers": ["Susanne Elizabeth Harrell", "Michael Kelly Darnell"],
     "address": "579 Groson Cy", "city": "Weed"},
    # Orange County - tax info scraping via OC Treasurer
    {"test_id": 22, "county_id": "orange", "county": "Orange", "platform": "oc_recorder",
     "borrowers": ["Wong Jenson", "Phan Wong"],
     "address": "1234 N Main St", "city": "Orange",
     "oc_tax_lookup": True},
]

# ─── Step Definitions ────────────────────────────────────────────────────────
STEPS = {
    1: "API Server Check",
    2: "Search County Recorder",
    3: "Check Existing Files",
    4: "Download Documents",
    5: "Verify Files",
    6: "Claude AI Analysis",
    7: "Tax Information",
    8: "Generate Report",
}

# ─── Orange County Tax Configuration ─────────────────────────────────────────
OC_TAX_URL = "https://taxbill.octreasurer.gov/"
OC_TAX_CAPTCHA_MAX_ATTEMPTS = 3
OC_TAX_TIMEOUT_MS = 30000

logger = logging.getLogger("oc_tax")


# ─── Orange County Tax Scraper ───────────────────────────────────────────────

def _ocr_captcha_image(captcha_b64):
    """
    Attempt OCR on the OC Treasurer CAPTCHA image.

    The CAPTCHA is a 5-character alphanumeric code rendered as a JPEG with
    horizontal line distortion. OCR success rate is low (~10-20%) due to the
    distortion overlapping with character strokes.

    Returns the OCR text string, or None if OCR is unavailable or fails.
    """
    try:
        import pytesseract
        from PIL import Image, ImageFilter
        import numpy as np
    except ImportError:
        logger.warning("pytesseract/Pillow/numpy not installed - captcha OCR unavailable")
        return None

    try:
        captcha_bytes = base64.b64decode(captcha_b64)
        img = Image.open(io.BytesIO(captcha_bytes))

        # Convert to grayscale
        img = img.convert('L')

        # Convert to numpy array for line removal
        arr = np.array(img)
        h, w = arr.shape

        # Binary threshold: dark pixels (text + lines) become 1
        binary = (arr < 140).astype(np.uint8)

        # Remove horizontal distortion lines:
        # Lines span a large portion of the image width
        for y in range(h):
            dark_count = np.sum(binary[y, :])
            if dark_count > w * 0.6:
                binary[y, :] = 0

        # Remove thin isolated horizontal lines (1-2px tall)
        for y in range(1, h - 1):
            row_ratio = np.sum(binary[y, :]) / w
            above_ratio = np.sum(binary[y - 1, :]) / w
            below_ratio = np.sum(binary[y + 1, :]) / w
            if row_ratio > 0.3 and above_ratio < 0.15 and below_ratio < 0.15:
                binary[y, :] = 0

        # Convert back: white background, dark text
        cleaned = ((1 - binary) * 255).astype(np.uint8)
        img_cleaned = Image.fromarray(cleaned)

        # Scale up 3x for better OCR accuracy
        img_cleaned = img_cleaned.resize((w * 3, h * 3), Image.LANCZOS)

        # Smooth edges, then re-threshold
        img_cleaned = img_cleaned.filter(ImageFilter.MedianFilter(3))
        img_cleaned = img_cleaned.point(lambda x: 255 if x > 128 else 0)

        # Run tesseract with restricted character whitelist
        text = pytesseract.image_to_string(
            img_cleaned,
            config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        ).strip().replace(' ', '')

        return text if text else None

    except Exception as e:
        logger.warning(f"Captcha OCR failed: {e}")
        return None


def _extract_captcha_b64(page):
    """Extract the base64-encoded CAPTCHA image from the modal."""
    return page.evaluate("""() => {
        const img = document.getElementById('captcha');
        if (!img) return null;
        const src = img.getAttribute('src');
        if (src && src.startsWith('data:image')) {
            return src.split(',')[1];
        }
        return null;
    }""")


def _solve_oc_captcha(page, screenshot_dir=None, max_attempts=OC_TAX_CAPTCHA_MAX_ATTEMPTS):
    """
    Attempt to solve the OC Treasurer text-based CAPTCHA.

    The CAPTCHA modal contains:
      - #captcha: base64 JPEG image of 5 alphanumeric characters
      - #captchaInput: text input (maxLength=5, auto-uppercased)
      - #verify: submit button (disabled until input has content)
      - #refresh: image button to generate new captcha

    Returns True if captcha was solved, False otherwise.
    """
    for attempt in range(max_attempts):
        logger.info(f"  OC Tax captcha attempt {attempt + 1}/{max_attempts}")

        captcha_b64 = _extract_captcha_b64(page)
        if not captcha_b64:
            logger.warning("  No captcha image found in modal")
            return False

        # Save captcha image for debugging
        if screenshot_dir:
            try:
                raw_bytes = base64.b64decode(captcha_b64)
                path = os.path.join(screenshot_dir, f"oc_tax_captcha_attempt{attempt}.jpg")
                with open(path, "wb") as f:
                    f.write(raw_bytes)
            except Exception:
                pass

        code = _ocr_captcha_image(captcha_b64)
        logger.info(f"  OCR result: {code}")

        if not code or len(code) < 4 or len(code) > 6:
            logger.info(f"  Bad OCR length ({len(code) if code else 0}), refreshing captcha")
            try:
                page.locator('#refresh').click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
            continue

        # Trim to 5 characters (captcha is always 5 chars)
        code = code[:5]
        logger.info(f"  Trying code: {code}")

        # Fill captcha input
        page.locator("#captchaInput").fill("")
        page.locator("#captchaInput").fill(code)
        page.wait_for_timeout(500)

        # Check if verify button is enabled
        verify_disabled = page.evaluate("document.getElementById('verify')?.disabled")
        if verify_disabled:
            logger.info("  Verify button still disabled, refreshing")
            try:
                page.locator('#refresh').click()
                page.wait_for_timeout(1500)
            except Exception:
                pass
            continue

        # Click verify
        page.locator("#verify").click()
        page.wait_for_timeout(3000)

        # Check if captcha was solved
        body_text = page.inner_text("body")
        if "VERIFY THAT YOU ARE HUMAN" not in body_text:
            logger.info("  CAPTCHA SOLVED")
            return True

        if "Incorrect Captcha" in body_text:
            logger.info(f"  Incorrect answer: {code}")
            page.locator("#captchaInput").fill("")
            page.wait_for_timeout(1000)

    logger.warning(f"  Failed to solve captcha after {max_attempts} attempts")
    return False


def _extract_oc_tax_data(page):
    """
    Extract tax information from the OC Treasurer result page.

    After a successful address/APN search, the result page displays:
    - Account Information section with Property Details (APN, Property Location)
    - Bill Documents section with links to PDF bills
    - Search Results tables: Secured Property Taxes and Unsecured Property Taxes
      (columns: APN, TDN, Tax Year, Roll Type, Status)
    - Current & Previous Year Tax Bills section with View Tax Bill buttons

    Returns a dict with all extracted fields.
    """
    data = {}

    # Get the full page text for pattern matching
    try:
        body_text = page.inner_text("body")
        data["raw_text"] = body_text[:5000]
    except Exception:
        body_text = ""
        data["raw_text"] = ""

    # Extract Property Details from the Account Information section
    try:
        property_info = page.evaluate("""() => {
            const result = {};

            // Find the PROPERTY DETAILS section elements
            // The page uses label-value format: "Parcel Number:" then the value
            const allText = document.body.innerText || '';

            // Parcel Number
            const parcelMatch = allText.match(/Parcel Number[:\\s]+([\\d\\-\\.]+)/);
            if (parcelMatch) result.parcel_number = parcelMatch[1].trim();

            // Property Location - match the address line (ends at "Click here" or newline)
            const locMatch = allText.match(/Property Location[:\\s]+([\\dA-Z][A-Z\\d\\s]+(?:ST|AV|AVE|BLVD|DR|LN|RD|CT|PL|WAY|CIR|PKWY|HWY)\\s+[A-Z\\s]+)/);
            if (locMatch) {
                result.property_location = locMatch[1].trim();
            } else {
                // Fallback: match up to next known keyword
                const locFallback = allText.match(/Property Location[:\\s]+(.+?)(?:Click here|Quick|\\n)/);
                if (locFallback) result.property_location = locFallback[1].trim();
            }

            return result;
        }""")
        if property_info.get("parcel_number"):
            data["apn"] = property_info["parcel_number"]
        if property_info.get("property_location"):
            data["property_location"] = property_info["property_location"]
    except Exception:
        pass

    # Extract Secured Property Tax records from the Search Results table
    try:
        tax_records = page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            const secured = [];
            const unsecured = [];

            for (const table of tables) {
                const rows = Array.from(table.rows);
                if (rows.length < 2) continue;

                // Check header row for expected columns
                const headers = Array.from(rows[0].cells).map(c => c.textContent.trim());
                const hasAPN = headers.some(h => h.includes('APN'));
                const hasTaxYear = headers.some(h => h.includes('Tax Year'));
                if (!hasAPN || !hasTaxYear) continue;

                // Determine if secured or unsecured by checking prior heading
                const prevEl = table.previousElementSibling;
                const heading = prevEl ? prevEl.textContent.trim() : '';
                const isUnsecured = heading.toLowerCase().includes('unsecured');

                for (let i = 1; i < rows.length; i++) {
                    const cells = Array.from(rows[i].cells).map(c => c.textContent.trim());
                    if (cells.length < 5) continue;
                    // cells: [View button, APN, TDN, Tax Year, Roll Type, Status]
                    const record = {
                        apn: cells[1] || '',
                        tdn: cells[2] || '',
                        tax_year: cells[3] || '',
                        roll_type: cells[4] || '',
                        status: cells[5] || '',
                    };
                    if (record.apn && record.tax_year) {
                        if (isUnsecured) {
                            unsecured.push(record);
                        } else {
                            secured.push(record);
                        }
                    }
                }
            }
            return {secured: secured, unsecured: unsecured};
        }""")
        data["secured_tax_records"] = tax_records.get("secured", [])
        data["unsecured_tax_records"] = tax_records.get("unsecured", [])
    except Exception:
        data["secured_tax_records"] = []
        data["unsecured_tax_records"] = []

    # Extract Current & Previous Year Tax Bills section
    try:
        tax_bills = page.evaluate("""() => {
            const body = document.body.textContent || '';
            const bills = [];
            // Match fiscal year patterns like "2025 - 2026"
            const yearPattern = /(20\\d{2})\\s*-\\s*(20\\d{2})/g;
            let match;
            while ((match = yearPattern.exec(body)) !== null) {
                const fiscal_year = match[1] + '-' + match[2];
                if (!bills.includes(fiscal_year)) {
                    bills.push(fiscal_year);
                }
            }
            return bills;
        }""")
        data["available_tax_bill_years"] = tax_bills
    except Exception:
        data["available_tax_bill_years"] = []

    # Extract all table data (raw format for completeness)
    try:
        tables = page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            return Array.from(tables).map((t, idx) => ({
                index: idx,
                rows: Array.from(t.rows).map(r =>
                    Array.from(r.cells).map(c => c.textContent.trim())
                ),
            }));
        }""")
        data["tables"] = tables
    except Exception:
        data["tables"] = []

    # Extract definition list pairs (dt/dd)
    try:
        details = page.evaluate("""() => {
            const dts = document.querySelectorAll('dt');
            return Array.from(dts).map(dt => ({
                label: dt.textContent.trim(),
                value: dt.nextElementSibling
                    ? dt.nextElementSibling.textContent.trim()
                    : '',
            }));
        }""")
        data["detail_pairs"] = details
    except Exception:
        data["detail_pairs"] = []

    # Extract card/panel section content
    try:
        cards = page.evaluate("""() => {
            const els = document.querySelectorAll('.card-body, .panel-body');
            return Array.from(els).slice(0, 10).map(e => ({
                text: e.textContent.trim().substring(0, 500),
            }));
        }""")
        data["card_sections"] = cards
    except Exception:
        data["card_sections"] = []

    # Extract structured data by scanning text for common patterns
    _parse_tax_fields(body_text, data)

    # Determine overall payment status from secured records
    if data.get("secured_tax_records"):
        statuses = [r.get("status", "").upper() for r in data["secured_tax_records"]]
        if all(s == "PAID" for s in statuses):
            data["payment_status"] = "Paid"
        elif any(s == "UNPAID" for s in statuses):
            data["payment_status"] = "Unpaid"
        elif any(s == "DELINQUENT" for s in statuses):
            data["payment_status"] = "Delinquent"

    return data


def _parse_tax_fields(body_text, data):
    """
    Parse known tax-related fields from the page text.

    Populates the data dict with structured fields when patterns match:
    - apn: Assessor Parcel Number
    - owner_name: Property owner name(s)
    - property_address: Situs address
    - tax_year: Fiscal year
    - total_tax: Total annual tax amount
    - first_installment / second_installment: Installment amounts
    - payment_status: Paid, Unpaid, Delinquent, etc.
    - assessed_land / assessed_improvements / assessed_total: Values
    """
    import re

    # APN pattern: 8 digits possibly with dash or dot
    apn_match = re.search(r'(?:APN|Parcel\s*(?:Number|No|#))[:\s]*(\d[\d\-\.]+)', body_text, re.IGNORECASE)
    if apn_match:
        data["apn"] = apn_match.group(1).strip()

    # Dollar amounts near known labels
    dollar_pattern = r'\$[\d,]+\.?\d*'

    for label, key in [
        (r'Total\s+Tax', 'total_tax'),
        (r'1st\s+Install|First\s+Install', 'first_installment'),
        (r'2nd\s+Install|Second\s+Install', 'second_installment'),
        (r'Amount\s+Due', 'amount_due'),
        (r'Net\s+Taxable\s+Value', 'net_taxable_value'),
        (r'Land\s+Value|Land', 'assessed_land'),
        (r'Improvement|Structure', 'assessed_improvements'),
    ]:
        match = re.search(label + r'[:\s]*(' + dollar_pattern + r')', body_text, re.IGNORECASE)
        if match:
            data[key] = match.group(1).strip()

    # Payment status keywords
    status_lower = body_text.lower()
    if 'paid' in status_lower and 'unpaid' not in status_lower:
        data['payment_status'] = 'Paid'
    elif 'unpaid' in status_lower:
        data['payment_status'] = 'Unpaid'
    elif 'delinquent' in status_lower:
        data['payment_status'] = 'Delinquent'
    elif 'defaulted' in status_lower:
        data['payment_status'] = 'Defaulted'

    # Tax year pattern: "20XX-XX" or "FY 20XX-XX"
    year_match = re.search(r'(?:FY|Tax\s+Year|Fiscal\s+Year)[:\s]*(20\d{2}[\-\/]?\d{2,4})', body_text, re.IGNORECASE)
    if year_match:
        data['tax_year'] = year_match.group(1).strip()


def search_orange_county_tax(page, property_address, owner_name="", screenshot_dir=None):
    """
    Search the Orange County Treasurer-Tax Collector website for tax information.

    This function navigates to https://taxbill.octreasurer.gov/, searches by
    property address using the autocomplete combobox, solves the text-based
    CAPTCHA (via OCR with pytesseract), and extracts tax bill data from the
    result page.

    Args:
        page: Playwright page object (should be from a Chromium browser context).
        property_address: Street address to search (e.g. "1234 N Main St").
            The site uses autocomplete, so partial addresses work. The function
            selects the first matching suggestion.
        owner_name: Optional owner name for logging/identification. Not used
            in the search itself (the OC site does not support owner name search
            for secured properties).
        screenshot_dir: Optional directory path to save debug screenshots.

    Returns:
        dict with the following structure:
        {
            "status": "success" | "captcha_failed" | "no_results" | "error",
            "error_message": str or None,
            "search_address": str,           # The address typed into search
            "selected_address": str or None,  # The autocomplete option selected
            "url": str,                       # Final page URL
            "data": {                         # Only present on success
                "apn": str,
                "total_tax": str,
                "payment_status": str,
                "first_installment": str,
                "second_installment": str,
                "assessed_land": str,
                "assessed_improvements": str,
                "tax_year": str,
                "tables": [...],
                "detail_pairs": [...],
                "raw_text": str,
                ...
            }
        }

    Limitations:
        - The CAPTCHA OCR success rate is approximately 10-20%. The distorted
          text image uses horizontal line overlays that confuse tesseract.
        - If pytesseract or Pillow are not installed, captcha solving is skipped.
        - The site does not support searching by owner name for secured properties.
        - Running in headless mode means manual captcha fallback is not available.
        - Rate limiting or IP blocking by the site is possible with repeated requests.
    """
    result = {
        "status": "error",
        "error_message": None,
        "search_address": property_address,
        "selected_address": None,
        "url": "",
        "data": {},
        "timestamp": datetime.now().isoformat(),
    }

    if not property_address:
        result["status"] = "error"
        result["error_message"] = "No property address provided"
        return result

    try:
        # 1. Navigate to OC Treasurer Tax Search
        logger.info(f"  OC Tax: Navigating to {OC_TAX_URL}")
        page.goto(OC_TAX_URL, wait_until="networkidle", timeout=OC_TAX_TIMEOUT_MS)
        page.wait_for_timeout(3000)  # Allow Angular app to fully render

        # 2. Type address into the autocomplete combobox
        #    The address input is an ng-select combobox under the
        #    "SEARCH BY PROPERTY ADDRESS" section
        combobox = page.locator('[role="combobox"]')
        if combobox.count() == 0:
            result["error_message"] = "Address combobox not found on page"
            return result

        combobox.click()
        combobox.fill(property_address)
        page.wait_for_timeout(2500)  # Wait for autocomplete API call + dropdown

        # 3. Check for and select autocomplete suggestions
        options = page.locator('[role="option"]')
        option_count = options.count()

        if option_count == 0:
            result["status"] = "no_results"
            result["error_message"] = f"No address matches found for: {property_address}"
            if screenshot_dir:
                page.screenshot(
                    path=os.path.join(screenshot_dir, "oc_tax_no_results.png")
                )
            return result

        # Select the first matching option
        selected_text = options.first.inner_text().strip()
        result["selected_address"] = selected_text
        logger.info(f"  OC Tax: Selecting address: {selected_text}")
        options.first.click()
        page.wait_for_timeout(1000)

        # 4. Click the "Find" button (first one in the Secured section)
        find_btn = page.locator("button.find-btn.btn.btn-primary").first
        find_btn.click(timeout=10000)
        page.wait_for_timeout(3000)

        # 5. Handle CAPTCHA if it appears
        body_text = page.inner_text("body")
        if "VERIFY THAT YOU ARE HUMAN" in body_text:
            logger.info("  OC Tax: CAPTCHA detected, attempting to solve...")

            if screenshot_dir:
                page.screenshot(
                    path=os.path.join(screenshot_dir, "oc_tax_captcha_modal.png")
                )

            captcha_solved = _solve_oc_captcha(
                page, screenshot_dir=screenshot_dir
            )

            if not captcha_solved:
                result["status"] = "captcha_failed"
                result["error_message"] = (
                    "Failed to solve OC Treasurer CAPTCHA via OCR. "
                    "The text-based image CAPTCHA has horizontal line distortion "
                    "that reduces OCR accuracy. Consider running in headed mode "
                    "for manual captcha solving, or using an APN-based lookup "
                    "if the APN is known."
                )
                if screenshot_dir:
                    page.screenshot(
                        path=os.path.join(screenshot_dir, "oc_tax_captcha_failed.png")
                    )
                return result

        # 6. Wait for result page to load
        page.wait_for_timeout(3000)
        result["url"] = page.url

        # 7. Extract tax data from the result page
        logger.info("  OC Tax: Extracting tax data from result page...")
        tax_data = _extract_oc_tax_data(page)
        result["data"] = tax_data
        result["status"] = "success"

        if screenshot_dir:
            page.screenshot(
                path=os.path.join(screenshot_dir, "oc_tax_result.png"),
                full_page=True,
            )

        logger.info(f"  OC Tax: Extraction complete. Keys: {list(tax_data.keys())}")

    except PlaywrightTimeout as e:
        result["status"] = "error"
        result["error_message"] = f"Timeout: {str(e)[:200]}"
        logger.error(f"  OC Tax timeout: {e}")
        if screenshot_dir:
            try:
                page.screenshot(
                    path=os.path.join(screenshot_dir, "oc_tax_timeout.png")
                )
            except Exception:
                pass

    except Exception as e:
        result["status"] = "error"
        result["error_message"] = f"Exception: {str(e)[:300]}"
        logger.error(f"  OC Tax error: {e}")
        if screenshot_dir:
            try:
                page.screenshot(
                    path=os.path.join(screenshot_dir, "oc_tax_error.png")
                )
            except Exception:
                pass

    return result


def get_step_statuses(page):
    """Read the status of all 8 steps from the DOM."""
    statuses = {}
    for i in range(1, 9):
        try:
            step_el = page.locator(f"#step{i}")
            classes = step_el.get_attribute("class") or ""
            # Extract status text from the step
            text = step_el.inner_text().strip()

            if "error" in classes:
                statuses[i] = {"status": "error", "text": text}
            elif "completed" in classes:
                statuses[i] = {"status": "completed", "text": text}
            elif "active" in classes:
                statuses[i] = {"status": "active", "text": text}
            else:
                statuses[i] = {"status": "pending", "text": text}
        except Exception:
            statuses[i] = {"status": "unknown", "text": ""}
    return statuses


def wait_for_pipeline_complete(page, timeout_ms=STEP_TIMEOUT_MS):
    """Wait until all steps are completed/error or the Generate button re-enables."""
    start = time.time()
    timeout_sec = timeout_ms / 1000
    last_status_print = 0

    while (time.time() - start) < timeout_sec:
        # Check if the Generate button is re-enabled (pipeline finished)
        try:
            btn = page.locator("#generateBtn")
            btn_disabled = btn.get_attribute("disabled")
            btn_text = btn.inner_text().strip()

            if btn_disabled is None and "Generate Report" in btn_text:
                # Button is re-enabled, pipeline is done
                return get_step_statuses(page)
        except Exception:
            pass

        # Print status periodically
        elapsed = time.time() - start
        if elapsed - last_status_print > 30:
            statuses = get_step_statuses(page)
            active_steps = [f"Step {k}: {v['text'][:60]}" for k, v in statuses.items() if v['status'] == 'active']
            if active_steps:
                print(f"  [{elapsed:.0f}s] Active: {'; '.join(active_steps)}")
            last_status_print = elapsed

        time.sleep(STEP_POLL_INTERVAL_MS / 1000)

    # Timeout - return whatever we have
    return get_step_statuses(page)


def determine_result(step_statuses):
    """Determine overall pass/fail and failure category."""
    # Check for errors
    for step_num, info in step_statuses.items():
        if info["status"] == "error":
            return {
                "result": "FAIL",
                "failed_step": step_num,
                "failed_step_name": STEPS.get(step_num, f"Step {step_num}"),
                "error_text": info["text"],
                "category": categorize_failure(step_num),
            }

    # Check if all steps completed
    completed_count = sum(1 for info in step_statuses.values() if info["status"] == "completed")
    if completed_count == 8:
        # Check step 2 for "No recorder documents found" - that's a search issue
        step2_text = step_statuses[2].get("text", "")
        if "No recorder documents found" in step2_text or "0 recorder documents" in step2_text:
            return {
                "result": "WARN",
                "failed_step": 2,
                "failed_step_name": "Search County Recorder",
                "error_text": step2_text,
                "category": "NO_RESULTS",
            }
        return {"result": "PASS", "failed_step": None, "failed_step_name": None, "error_text": None, "category": None}

    # Some steps still pending/active = timeout
    incomplete = [k for k, v in step_statuses.items() if v["status"] in ("active", "pending")]
    return {
        "result": "TIMEOUT",
        "failed_step": min(incomplete) if incomplete else None,
        "failed_step_name": STEPS.get(min(incomplete), "") if incomplete else "",
        "error_text": f"Steps {incomplete} did not complete within timeout",
        "category": "TIMEOUT",
    }


def categorize_failure(step_num):
    """Categorize failures by step number."""
    categories = {
        1: "SERVER_ERROR",
        2: "SEARCH_FAIL",
        3: "FILE_CHECK_FAIL",
        4: "DOWNLOAD_FAIL",
        5: "VERIFY_FAIL",
        6: "ANALYSIS_FAIL",
        7: "TAX_LOOKUP_FAIL",
        8: "REPORT_GEN_FAIL",
    }
    return categories.get(step_num, "UNKNOWN")


def capture_console_errors(page):
    """Collect console errors from the page."""
    errors = []
    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
    return errors


def run_single_test(page, test_subject, screenshot_dir):
    """Run a single test subject through the CURE pipeline."""
    test_id = test_subject["test_id"]
    county = test_subject["county"]
    county_id = test_subject["county_id"]
    borrowers = test_subject["borrowers"]
    address = test_subject.get("address", "")
    city = test_subject.get("city", "")

    owner_name = ", ".join(borrowers)
    full_address = f"{address}, {city}, CA" if address and city else address or ""

    print(f"\n{'='*70}")
    print(f"TEST #{test_id}: {county} County ({test_subject['platform']})")
    print(f"  Owner: {owner_name}")
    print(f"  Address: {full_address or '(none)'}")
    print(f"{'='*70}")

    result = {
        "test_id": test_id,
        "county": county,
        "county_id": county_id,
        "platform": test_subject["platform"],
        "borrowers": borrowers,
        "address": full_address,
        "started_at": datetime.now().isoformat(),
    }

    try:
        # Navigate to CURE
        page.goto(CURE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)  # Wait for counties to load

        # Wait for county dropdown to be populated (check for "(23 counties)" text)
        page.wait_for_function(
            """() => {
                const el = document.getElementById('countyCount');
                return el && el.textContent.includes('counties') && !el.textContent.includes('loading');
            }""",
            timeout=15000
        )

        # Select county
        page.select_option("#county", value=county_id)
        page.wait_for_timeout(500)

        # Enter owner name
        owner_input = page.locator("#ownerName")
        owner_input.fill("")
        owner_input.fill(owner_name)

        # Enter property address if available
        if full_address:
            addr_input = page.locator("#propertyAddress")
            addr_input.fill("")
            addr_input.fill(full_address)

        # Uncheck "Show Browser" to keep it headless for speed (use JS since it's a custom styled checkbox)
        page.evaluate("document.getElementById('showBrowserCheckbox').checked = false")

        # Take pre-search screenshot
        page.screenshot(path=os.path.join(screenshot_dir, f"test_{test_id}_{county_id}_before.png"))

        # Collect console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)

        # Click Generate Report
        print(f"  Clicking Generate Report...")
        page.locator("#generateBtn").click()

        # Wait for pipeline to complete
        start_time = time.time()
        step_statuses = wait_for_pipeline_complete(page, STEP_TIMEOUT_MS)
        duration = time.time() - start_time

        # Get result
        test_result = determine_result(step_statuses)

        # Take post-search screenshot
        page.screenshot(path=os.path.join(screenshot_dir, f"test_{test_id}_{county_id}_after.png"), full_page=True)

        # Collect step details
        step_details = {}
        for step_num, info in step_statuses.items():
            step_details[f"step_{step_num}"] = {
                "name": STEPS[step_num],
                "status": info["status"],
                "text": info["text"],
            }

        result.update({
            "result": test_result["result"],
            "failed_step": test_result["failed_step"],
            "failed_step_name": test_result["failed_step_name"],
            "error_text": test_result["error_text"],
            "category": test_result["category"],
            "duration_seconds": round(duration, 1),
            "step_details": step_details,
            "console_errors": console_errors[-10:] if console_errors else [],  # Last 10
            "screenshot": f"test_{test_id}_{county_id}_after.png",
        })

        status_icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "TIMEOUT": "⏰"}.get(test_result["result"], "❓")
        print(f"  {status_icon} Result: {test_result['result']} ({duration:.1f}s)")
        if test_result["failed_step"]:
            print(f"  Failed at: Step {test_result['failed_step']} - {test_result['failed_step_name']}")
            print(f"  Error: {test_result['error_text'][:100]}")

        # ── Orange County Tax Lookup (runs after pipeline for OC subjects) ──
        if test_subject.get("oc_tax_lookup") and full_address:
            print(f"  Running Orange County tax information lookup...")
            try:
                oc_tax_result = search_orange_county_tax(
                    page=page,
                    property_address=address,  # Use raw address without city/state suffix
                    owner_name=owner_name,
                    screenshot_dir=screenshot_dir,
                )
                result["oc_tax"] = oc_tax_result
                oc_status = oc_tax_result.get("status", "unknown")
                print(f"  OC Tax lookup: {oc_status}")
                if oc_status == "success":
                    tax_data = oc_tax_result.get("data", {})
                    if tax_data.get("total_tax"):
                        print(f"    Total Tax: {tax_data['total_tax']}")
                    if tax_data.get("payment_status"):
                        print(f"    Payment Status: {tax_data['payment_status']}")
                elif oc_status == "captcha_failed":
                    print(f"    CAPTCHA could not be solved via OCR")
                elif oc_status == "no_results":
                    print(f"    No address matches found")
                else:
                    print(f"    Error: {oc_tax_result.get('error_message', 'Unknown')[:100]}")
            except Exception as e:
                result["oc_tax"] = {
                    "status": "error",
                    "error_message": f"OC Tax lookup exception: {str(e)[:200]}",
                }
                print(f"  OC Tax lookup failed: {str(e)[:100]}")

            # Navigate back to CURE for any subsequent tests
            try:
                page.goto(CURE_URL, wait_until="networkidle", timeout=15000)
            except Exception:
                pass

    except PlaywrightTimeout as e:
        page.screenshot(path=os.path.join(screenshot_dir, f"test_{test_id}_{county_id}_timeout.png"))
        result.update({
            "result": "TIMEOUT",
            "failed_step": None,
            "failed_step_name": "Playwright Timeout",
            "error_text": str(e)[:200],
            "category": "PLAYWRIGHT_TIMEOUT",
            "duration_seconds": STEP_TIMEOUT_MS / 1000,
            "step_details": {},
            "console_errors": [],
            "screenshot": f"test_{test_id}_{county_id}_timeout.png",
        })
        print(f"  ⏰ TIMEOUT: {str(e)[:100]}")

    except Exception as e:
        try:
            page.screenshot(path=os.path.join(screenshot_dir, f"test_{test_id}_{county_id}_error.png"))
        except Exception:
            pass
        result.update({
            "result": "ERROR",
            "failed_step": None,
            "failed_step_name": "Exception",
            "error_text": str(e)[:300],
            "category": "EXCEPTION",
            "duration_seconds": 0,
            "step_details": {},
            "console_errors": [],
            "screenshot": f"test_{test_id}_{county_id}_error.png",
        })
        print(f"  💥 ERROR: {str(e)[:100]}")

    result["finished_at"] = datetime.now().isoformat()
    return result


def save_results(results, results_file):
    """Save results incrementally."""
    summary = {
        "execution_time": datetime.now().isoformat(),
        "total_tests": len(results),
        "passed": sum(1 for r in results if r["result"] == "PASS"),
        "failed": sum(1 for r in results if r["result"] == "FAIL"),
        "warnings": sum(1 for r in results if r["result"] == "WARN"),
        "timeouts": sum(1 for r in results if r["result"] in ("TIMEOUT", "ERROR")),
        "results": results,
    }
    with open(results_file, "w") as f:
        json.dump(summary, f, indent=2)


def generate_backlog_md(results, output_file):
    """Generate titlePro_Backlog.md with JIRA-like tasks for failures."""
    failures = [r for r in results if r["result"] in ("FAIL", "WARN", "TIMEOUT", "ERROR")]
    passes = [r for r in results if r["result"] == "PASS"]

    lines = []
    lines.append("# TitlePro CURE - Test Backlog")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Tests**: {len(results)} | **Passed**: {len(passes)} | **Failed/Issues**: {len(failures)}")
    lines.append("")

    # Summary table
    lines.append("## Test Results Summary")
    lines.append("")
    lines.append("| # | County | Platform | Result | Failed Step | Duration |")
    lines.append("|---|--------|----------|--------|-------------|----------|")
    for r in sorted(results, key=lambda x: x["test_id"]):
        icon = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN", "TIMEOUT": "TIMEOUT", "ERROR": "ERROR"}.get(r["result"], "?")
        step = r.get("failed_step_name") or "-"
        dur = f"{r.get('duration_seconds', 0):.0f}s"
        lines.append(f"| {r['test_id']} | {r['county']} | {r['platform']} | {icon} | {step} | {dur} |")
    lines.append("")

    # Backlog items for failures
    if failures:
        lines.append("---")
        lines.append("")
        lines.append("## Backlog Items")
        lines.append("")

        # Group by category
        by_category = {}
        for f in failures:
            cat = f.get("category", "UNKNOWN")
            by_category.setdefault(cat, []).append(f)

        ticket_num = 1
        for category, items in sorted(by_category.items()):
            lines.append(f"### Category: {category}")
            lines.append("")

            for item in items:
                lines.append(f"#### TP-{ticket_num:03d}: [{item['county']} County] {category}")
                lines.append("")
                lines.append(f"- **Priority**: {'P1 - Critical' if category == 'SEARCH_FAIL' else 'P2 - High' if category in ('DOWNLOAD_FAIL', 'TIMEOUT') else 'P3 - Medium'}")
                lines.append(f"- **County**: {item['county']} (`{item['county_id']}`)")
                lines.append(f"- **Platform**: {item['platform']}")
                lines.append(f"- **Borrowers**: {', '.join(item.get('borrowers', []))}")
                lines.append(f"- **Address**: {item.get('address', 'N/A')}")
                lines.append(f"- **Failed Step**: Step {item.get('failed_step', '?')} - {item.get('failed_step_name', '?')}")
                lines.append(f"- **Error**: `{item.get('error_text', 'N/A')[:200]}`")
                lines.append(f"- **Duration**: {item.get('duration_seconds', 0):.0f}s")
                lines.append(f"- **Screenshot**: `tests/screenshots/{item.get('screenshot', 'N/A')}`")
                lines.append("")

                # Step-by-step details
                if item.get("step_details"):
                    lines.append("  **Step Details:**")
                    for step_key in sorted(item["step_details"].keys()):
                        step = item["step_details"][step_key]
                        s_icon = {"completed": "done", "error": "FAIL", "active": "...", "pending": "-"}.get(step["status"], "?")
                        lines.append(f"  - {step['name']}: [{s_icon}] {step.get('text', '')[:80]}")
                    lines.append("")

                if item.get("console_errors"):
                    lines.append("  **Console Errors:**")
                    for err in item["console_errors"][:5]:
                        lines.append(f"  - `{err[:120]}`")
                    lines.append("")

                lines.append(f"  **Acceptance Criteria:**")
                lines.append(f"  - [ ] Search {item['county']} County recorder returns documents for test borrower(s)")
                lines.append(f"  - [ ] Documents download successfully")
                lines.append(f"  - [ ] Claude AI analysis completes")
                lines.append(f"  - [ ] Report generates without errors")
                lines.append(f"  - [ ] Re-run Playwright test passes")
                lines.append("")
                lines.append("---")
                lines.append("")
                ticket_num += 1

    # Passing counties
    if passes:
        lines.append("## Passing Counties (No Action Needed)")
        lines.append("")
        for p in sorted(passes, key=lambda x: x["test_id"]):
            step_summary = ""
            if p.get("step_details"):
                s2 = p["step_details"].get("step_2", {}).get("text", "")
                step_summary = f" - {s2}" if s2 else ""
            lines.append(f"- **{p['county']}** ({p['platform']}){step_summary} [{p.get('duration_seconds', 0):.0f}s]")
        lines.append("")

    with open(output_file, "w") as f:
        f.write("\n".join(lines))

    return len(failures)


def main():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = os.path.join(RESULTS_DIR, f"playwright_full_pipeline_{timestamp}.json")
    backlog_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "titlePro_Backlog.md")

    print("=" * 70)
    print("CURE Full Pipeline Test - Playwright")
    print(f"Testing {len(TEST_SUBJECTS)} counties")
    print(f"Results: {results_file}")
    print(f"Backlog: {backlog_file}")
    print("=" * 70)

    all_results = []

    with sync_playwright() as p:
        # Launch browser - headless for speed
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()

        # Set generous default timeout
        page.set_default_timeout(30000)

        for i, subject in enumerate(TEST_SUBJECTS):
            print(f"\n[{i+1}/{len(TEST_SUBJECTS)}] Starting test...")

            result = run_single_test(page, subject, SCREENSHOT_DIR)
            all_results.append(result)

            # Save incrementally after each test
            save_results(all_results, results_file)

            # Brief pause between tests
            time.sleep(2)

        browser.close()

    # Generate backlog
    failure_count = generate_backlog_md(all_results, backlog_file)

    # Final summary
    passed = sum(1 for r in all_results if r["result"] == "PASS")
    failed = sum(1 for r in all_results if r["result"] == "FAIL")
    warned = sum(1 for r in all_results if r["result"] == "WARN")
    timed_out = sum(1 for r in all_results if r["result"] in ("TIMEOUT", "ERROR"))

    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    print(f"  PASSED:   {passed}/{len(all_results)}")
    print(f"  FAILED:   {failed}/{len(all_results)}")
    print(f"  WARNINGS: {warned}/{len(all_results)}")
    print(f"  TIMEOUTS: {timed_out}/{len(all_results)}")
    print(f"\n  Results saved to: {results_file}")
    print(f"  Backlog saved to: {backlog_file}")
    print(f"  Screenshots in:   {SCREENSHOT_DIR}/")
    print("=" * 70)


def run_oc_tax_test(address="1234 N Main St", headless=True):
    """
    Standalone Orange County tax lookup test.

    Usage:
        python3 tests/playwright_cure_test.py --oc-tax "906 Corral St"
        python3 tests/playwright_cure_test.py --oc-tax "1234 N Main St" --headed

    Args:
        address: Property address to search in Orange County.
        headless: If False, opens visible browser for manual captcha solving.
    """
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Configure logging for standalone mode
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    print("=" * 70)
    print("Orange County Tax Information Lookup - Standalone Test")
    print(f"  Address: {address}")
    print(f"  Mode: {'Headless' if headless else 'Headed (manual captcha)'}")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=300 if not headless else 0)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(OC_TAX_TIMEOUT_MS)

        if not headless:
            # In headed mode, allow manual captcha solving with longer timeout
            print("\n  NOTE: If CAPTCHA appears, you have 60 seconds to solve it manually.")
            print("  The script will attempt OCR first, then wait for manual input.\n")

        result = search_orange_county_tax(
            page=page,
            property_address=address,
            screenshot_dir=SCREENSHOT_DIR,
        )

        # If captcha failed in headed mode, wait for manual solving
        if not headless and result["status"] == "captcha_failed":
            print("\n  OCR failed. Please solve the CAPTCHA manually in the browser...")
            start = time.time()
            while time.time() - start < 60:
                body = page.inner_text("body")
                if "VERIFY THAT YOU ARE HUMAN" not in body:
                    print("  CAPTCHA solved manually!")
                    page.wait_for_timeout(3000)
                    result["data"] = _extract_oc_tax_data(page)
                    result["status"] = "success"
                    result["url"] = page.url
                    page.screenshot(
                        path=os.path.join(SCREENSHOT_DIR, "oc_tax_result_manual.png"),
                        full_page=True,
                    )
                    break
                time.sleep(2)

        browser.close()

    # Print results
    print("\n" + "=" * 70)
    print("OC TAX LOOKUP RESULTS")
    print("=" * 70)
    print(f"  Status: {result['status']}")
    print(f"  Search Address: {result['search_address']}")
    print(f"  Selected Address: {result.get('selected_address', 'N/A')}")
    print(f"  URL: {result.get('url', 'N/A')}")

    if result["status"] == "success":
        data = result.get("data", {})
        print(f"\n  --- Property Information ---")
        for key in ["apn", "property_location", "payment_status", "tax_year",
                     "total_tax", "first_installment", "second_installment",
                     "amount_due", "assessed_land", "assessed_improvements",
                     "net_taxable_value"]:
            if data.get(key):
                print(f"  {key}: {data[key]}")

        if data.get("secured_tax_records"):
            print(f"\n  --- Secured Tax Records ({len(data['secured_tax_records'])}) ---")
            for rec in data["secured_tax_records"]:
                print(f"    APN: {rec['apn']}  Year: {rec['tax_year']}  "
                      f"Type: {rec['roll_type']}  Status: {rec['status']}")

        if data.get("unsecured_tax_records"):
            print(f"\n  --- Unsecured Tax Records ({len(data['unsecured_tax_records'])}) ---")
            for rec in data["unsecured_tax_records"]:
                print(f"    APN: {rec['apn']}  Year: {rec['tax_year']}  "
                      f"Type: {rec['roll_type']}  Status: {rec['status']}")

        if data.get("available_tax_bill_years"):
            print(f"\n  --- Available Tax Bill Years ---")
            print(f"    {', '.join(data['available_tax_bill_years'])}")

        if data.get("tables"):
            print(f"\n  Raw tables found: {len(data['tables'])}")

        if data.get("detail_pairs"):
            print(f"\n  Detail pairs found: {len(data['detail_pairs'])}")
            for d in data["detail_pairs"][:10]:
                print(f"    {d['label']}: {d['value']}")
    else:
        if result.get("error_message"):
            print(f"  Error: {result['error_message']}")

    # Save full result to JSON
    result_file = os.path.join(SCREENSHOT_DIR, "oc_tax_result.json")
    with open(result_file, "w") as f:
        # Exclude raw_text from JSON for readability
        output = dict(result)
        if output.get("data", {}).get("raw_text"):
            output["data"]["raw_text"] = output["data"]["raw_text"][:500] + "..."
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Full results saved to: {result_file}")
    print(f"  Screenshots in: {SCREENSHOT_DIR}/")
    print("=" * 70)

    return result


if __name__ == "__main__":
    if "--oc-tax" in sys.argv:
        # Standalone OC tax test mode
        idx = sys.argv.index("--oc-tax")
        address = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "1234 N Main St"
        headless = "--headed" not in sys.argv
        run_oc_tax_test(address=address, headless=headless)
    else:
        main()
