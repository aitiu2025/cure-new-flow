"""
Orange County Property Tax Lookup

This module retrieves property tax information from the OC Treasurer website
using Selenium automation with CAPTCHA solving via OCR.

Usage:
    python tax_lookup.py 937-67-322

Returns tax information including:
- Tax year
- Annual tax amount
- First/Second installment amounts and status
- Property address
"""

import time
import json
import re
import base64
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime
from io import BytesIO

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

try:
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

TAX_WEBSITE_URL = "https://taxbill.octreasurer.gov/"


def setup_driver(headless: bool = True):
    """Initialize Chrome WebDriver."""
    options = Options()

    if headless:
        options.add_argument("--headless")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        if USE_WEBDRIVER_MANAGER:
            driver_path = ChromeDriverManager().install()
            if not driver_path.endswith('chromedriver'):
                import os
                driver_dir = os.path.dirname(driver_path)
                driver_path = os.path.join(driver_dir, 'chromedriver')
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"WebDriver manager failed: {e}")
        driver = webdriver.Chrome(options=options)

    driver.implicitly_wait(10)
    return driver


def solve_captcha_image(driver) -> Optional[str]:
    """
    Extract and solve the CAPTCHA image using OCR.

    The OC Treasurer website uses a simple text-based CAPTCHA displayed as an image.
    We use Tesseract OCR to read the text after preprocessing the image.
    """
    if not OCR_AVAILABLE:
        return None

    try:
        captcha_img = driver.find_element(By.ID, 'captcha')
        src = captcha_img.get_attribute('src')

        if not src or 'data:image' not in src:
            return None

        # Extract base64 image data
        header, data = src.split(',', 1)
        image_bytes = base64.b64decode(data)

        # Open and preprocess image
        img = Image.open(BytesIO(image_bytes))

        # Convert to grayscale
        img = img.convert('L')

        # Resize for better OCR accuracy
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.5)

        # Binarize - convert to black and white
        threshold = 140
        img = img.point(lambda p: 255 if p > threshold else 0)

        # Check if image is inverted (white text on dark background)
        pixels = list(img.getdata())
        dark_ratio = sum(1 for p in pixels if p < 128) / len(pixels)
        if dark_ratio > 0.5:
            img = ImageOps.invert(img)

        # Apply morphological operations to clean noise
        img = img.filter(ImageFilter.MaxFilter(3))
        img = img.filter(ImageFilter.MinFilter(3))

        # OCR with optimized settings for CAPTCHA
        text = pytesseract.image_to_string(
            img,
            config='--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        ).strip()

        # Clean result - keep only alphanumeric characters
        clean = re.sub(r'[^A-Z0-9]', '', text.upper())

        if clean and 4 <= len(clean) <= 8:
            return clean

    except Exception as e:
        print(f"CAPTCHA solving error: {e}")

    return None


def handle_captcha(driver, max_attempts: int = 5) -> bool:
    """
    Handle CAPTCHA modal if present.

    Returns True if CAPTCHA was solved or not present, False if failed.
    """
    for attempt in range(max_attempts):
        try:
            captcha_img = driver.find_element(By.ID, 'captcha')
            if not captcha_img.is_displayed():
                return True

            print(f"  CAPTCHA attempt {attempt + 1}/{max_attempts}")

            captcha_text = solve_captcha_image(driver)

            if captcha_text:
                # Find and fill the CAPTCHA input
                captcha_input = driver.find_element(
                    By.XPATH,
                    "//div[contains(@class, 'modal')]//input[@type='text']"
                )
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
                time.sleep(0.5)

                # Click Verify button
                verify_btn = driver.find_element(
                    By.XPATH,
                    "//button[contains(text(), 'Verify')]"
                )
                verify_btn.click()
                time.sleep(2)

                # Check for error message
                try:
                    error = driver.find_element(
                        By.XPATH,
                        "//*[contains(text(), 'Incorrect')]"
                    )
                    if error.is_displayed():
                        print(f"    Incorrect, retrying...")
                        time.sleep(1)
                        continue
                except NoSuchElementException:
                    print(f"    CAPTCHA solved!")
                    return True
            else:
                print(f"    Could not read CAPTCHA")

        except NoSuchElementException:
            # No CAPTCHA modal present
            return True
        except Exception as e:
            print(f"    CAPTCHA handling error: {e}")
            return True

    return False


def lookup_tax_by_apn(apn: str, headless: bool = True) -> Dict:
    """
    Look up property tax information by APN (Assessor's Parcel Number).

    Args:
        apn: APN in format like "937-67-322" or "93767322"
        headless: Run browser in headless mode (default True)

    Returns:
        Dictionary with tax information including:
        - success: bool
        - apn: str
        - property_address: str
        - tax_year: str (e.g., "2025-2026")
        - annual_tax: str (e.g., "$3,500.00")
        - first_installment_amount: str
        - first_installment_status: str ("PAID" or "UNPAID")
        - second_installment_amount: str
        - second_installment_status: str ("PAID" or "UNPAID")
        - lookup_timestamp: str
    """
    if not SELENIUM_AVAILABLE:
        return {
            "success": False,
            "error": "Selenium not installed. Run: pip install selenium",
            "apn": apn
        }

    if not OCR_AVAILABLE:
        return {
            "success": False,
            "error": "OCR not available. Run: pip install pytesseract pillow",
            "apn": apn
        }

    # Normalize APN format - remove dashes and spaces
    clean_apn = apn.replace("-", "").replace(" ", "")

    result = {
        "success": False,
        "apn": apn,
        "clean_apn": clean_apn,
        "lookup_timestamp": datetime.now().isoformat()
    }

    driver = None
    try:
        print(f"Looking up tax info for APN: {apn}")
        driver = setup_driver(headless=headless)

        # Navigate to tax website
        driver.get(TAX_WEBSITE_URL)
        time.sleep(5)

        # Find the Parcel Number input field
        parcel_input = driver.find_element(
            By.XPATH,
            "//input[@placeholder='Enter Parcel No. e.g. 98806878 or 98806878.0100']"
        )

        # Scroll into view
        driver.execute_script(
            'arguments[0].scrollIntoView({block: "center"});',
            parcel_input
        )
        time.sleep(1)

        # Enter APN using JavaScript for reliability
        driver.execute_script('''
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
            arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        ''', parcel_input, clean_apn)
        time.sleep(2)

        # Click the Find button
        find_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(@class, 'find-btn')]"
        )
        for btn in find_buttons:
            if btn.is_displayed() and not btn.get_attribute('disabled'):
                driver.execute_script('arguments[0].click();', btn)
                break

        time.sleep(3)

        # Handle CAPTCHA
        if not handle_captcha(driver, max_attempts=5):
            result["error"] = "CAPTCHA verification failed after 5 attempts"
            return result

        time.sleep(2)

        # Get page content
        page_text = driver.find_element(By.TAG_NAME, 'body').text

        # Check if property was found
        if 'No records found' in page_text:
            result["error"] = f"No property found for APN: {apn}"
            return result

        # Extract property address
        loc_match = re.search(r'Property Location[:\s]*\n?([^\n]+)', page_text)
        if loc_match:
            result["property_address"] = loc_match.group(1).strip()

        # Extract payment status from main page
        if 'FIRST INSTALLMENT PAID' in page_text.upper():
            result["first_installment_status"] = "PAID"
        elif 'FIRST INSTALLMENT UNPAID' in page_text.upper():
            result["first_installment_status"] = "UNPAID"

        if 'SECOND INSTALLMENT PAID' in page_text.upper():
            result["second_installment_status"] = "PAID"
        elif 'SECOND INSTALLMENT UNPAID' in page_text.upper():
            result["second_installment_status"] = "UNPAID"

        # Try to get detailed tax amounts by clicking View Tax Details
        try:
            view_links = driver.find_elements(
                By.XPATH,
                "//a[contains(text(), 'View Tax Details')]"
            )
            if view_links:
                driver.execute_script(
                    'arguments[0].scrollIntoView({block: "center"});',
                    view_links[0]
                )
                time.sleep(0.5)
                driver.execute_script('arguments[0].click();', view_links[0])
                time.sleep(4)

                details_text = driver.find_element(By.TAG_NAME, 'body').text

                # Extract tax year
                year_match = re.search(r'(\d{4})\s*[-–]\s*(\d{4})', details_text)
                if year_match:
                    result["tax_year"] = f"{year_match.group(1)}-{year_match.group(2)}"

                # Extract amounts using various patterns
                # Total tax
                total_patterns = [
                    r'Total\s*(?:Tax|Due)[:\s]*\$?([\d,]+\.\d{2})',
                    r'Annual\s*Tax[:\s]*\$?([\d,]+\.\d{2})',
                    r'Tax\s*Amount[:\s]*\$?([\d,]+\.\d{2})',
                ]
                for pattern in total_patterns:
                    match = re.search(pattern, details_text, re.IGNORECASE)
                    if match:
                        result["annual_tax"] = f"${match.group(1)}"
                        break

                # First installment
                first_patterns = [
                    r'1st\s*Installment[:\s]*\$?([\d,]+\.\d{2})',
                    r'First\s*Installment[:\s]*\$?([\d,]+\.\d{2})',
                ]
                for pattern in first_patterns:
                    match = re.search(pattern, details_text, re.IGNORECASE)
                    if match:
                        result["first_installment_amount"] = f"${match.group(1)}"
                        break

                # Second installment
                second_patterns = [
                    r'2nd\s*Installment[:\s]*\$?([\d,]+\.\d{2})',
                    r'Second\s*Installment[:\s]*\$?([\d,]+\.\d{2})',
                ]
                for pattern in second_patterns:
                    match = re.search(pattern, details_text, re.IGNORECASE)
                    if match:
                        result["second_installment_amount"] = f"${match.group(1)}"
                        break

        except Exception as e:
            print(f"Could not get detailed tax info: {e}")

        # Extract tax year from main page if not found in details
        if not result.get("tax_year"):
            year_match = re.search(r'(\d{4})\s*[-–]\s*(\d{4})', page_text)
            if year_match:
                result["tax_year"] = f"{year_match.group(1)}-{year_match.group(2)}"

        result["success"] = True
        result["verification_url"] = TAX_WEBSITE_URL
        result["data_source"] = "OC Treasurer-Tax Collector website"

    except TimeoutException:
        result["error"] = "Timeout waiting for page to load"
    except Exception as e:
        result["error"] = str(e)
    finally:
        if driver:
            driver.quit()

    return result


def get_tax_info_for_report(apn: str, headless: bool = True) -> Dict:
    """
    Get tax information formatted for FINAL_REPORT.json structure.

    This is the main function to call from report_generator.py.
    Returns a tax_information dict ready to be merged into the report.
    """
    result = lookup_tax_by_apn(apn, headless=headless)

    if result.get("success"):
        return {
            "tax_year": result.get("tax_year", "2025-2026"),
            "apn": apn,
            "annual_tax_estimated": result.get("annual_tax", "See OC Treasurer website"),
            "first_installment_amount": result.get("first_installment_amount"),
            "first_installment_status": result.get("first_installment_status"),
            "first_installment_due": "December 10",
            "second_installment_amount": result.get("second_installment_amount"),
            "second_installment_status": result.get("second_installment_status"),
            "second_installment_due": "April 10",
            "property_address": result.get("property_address"),
            "verification_url": TAX_WEBSITE_URL,
            "data_source": "OC Treasurer-Tax Collector website",
            "lookup_timestamp": result.get("lookup_timestamp")
        }
    else:
        return {
            "tax_year": "2025-2026",
            "apn": apn,
            "annual_tax_estimated": "Unable to retrieve - verify at OC Treasurer website",
            "first_installment_due": "December 10",
            "second_installment_due": "April 10",
            "verification_url": TAX_WEBSITE_URL,
            "data_source": f"Lookup failed - {result.get('error', 'Unknown error')}",
            "lookup_error": result.get("error")
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python tax_lookup.py <APN>")
        print("  python tax_lookup.py 937-67-322")
        print("")
        print("Note: APN can be in format 937-67-322 or 93767322")
        sys.exit(1)

    apn = sys.argv[1]
    headless = "--visible" not in sys.argv

    print(f"\nLooking up tax information for APN: {apn}")
    print("=" * 50)

    result = lookup_tax_by_apn(apn, headless=headless)

    print("\nResult:")
    print(json.dumps(result, indent=2))

    if result.get("success"):
        print("\nFormatted for report:")
        formatted = get_tax_info_for_report(apn)
        print(json.dumps(formatted, indent=2))
