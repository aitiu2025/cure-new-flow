"""
Script to explore TitlePro's county dropdown and find Amador County.
"""
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from webdriver_manager.chrome import ChromeDriverManager

SECRETS_FILENAME = "secrets.json"

def load_secrets(path: Path):
    if not path.exists():
        raise SystemExit(f"Missing secrets file at {path}")
    data = json.loads(path.read_text())
    username = data.get("TITLEPRO_USERNAME")
    password = data.get("TITLEPRO_PASSWORD")
    base_url = data.get("TITLEPRO_URL", "https://www.titlepro247.com/")
    return username, password, base_url

def build_driver(headless: bool = False):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

    raw_path = Path(ChromeDriverManager().install())
    driver_path = raw_path
    if not raw_path.name.startswith("chromedriver"):
        candidate = raw_path.parent / "chromedriver"
        if candidate.exists():
            driver_path = candidate

    service = Service(str(driver_path))
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver

def main():
    base_dir = Path(__file__).resolve().parent
    secrets_path = base_dir / SECRETS_FILENAME
    username, password, base_url = load_secrets(secrets_path)

    print("Starting browser...")
    driver = build_driver(headless=False)  # Visible for debugging
    wait = WebDriverWait(driver, 25)

    try:
        # Login
        print(f"Navigating to {base_url}")
        driver.get(base_url)

        # Handle cookie banner
        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            cookie_btn.click()
        except:
            pass

        # Login
        print("Logging in...")
        wait.until(EC.visibility_of_element_located((By.ID, "UserName"))).send_keys(username)
        wait.until(EC.visibility_of_element_located((By.ID, "Password"))).send_keys(password)
        login_btn = wait.until(EC.element_to_be_clickable((By.ID, "login-submit")))
        driver.execute_script("arguments[0].click();", login_btn)

        time.sleep(3)

        # Click Documents tab
        print("Opening Documents tab...")
        doc_tab = wait.until(EC.element_to_be_clickable((By.ID, "documents")))
        doc_tab.click()
        time.sleep(2)

        # Look for county-related elements
        print("\n=== Searching for county-related elements ===")

        # Try various selectors for county dropdown
        selectors_to_try = [
            ("id", "county"),
            ("id", "countyId"),
            ("id", "CountyId"),
            ("id", "ddlCounty"),
            ("id", "countySelect"),
            ("id", "state"),
            ("id", "stateId"),
            ("name", "county"),
            ("name", "countyId"),
            ("css", "select[name*='county']"),
            ("css", "select[id*='county']"),
            ("css", "select[id*='County']"),
            ("css", "#documents select"),
            ("xpath", "//select[contains(@id, 'county') or contains(@id, 'County')]"),
            ("xpath", "//label[contains(text(), 'County')]/following-sibling::select"),
            ("xpath", "//label[contains(text(), 'County')]/..//select"),
        ]

        for selector_type, selector in selectors_to_try:
            try:
                if selector_type == "id":
                    el = driver.find_element(By.ID, selector)
                elif selector_type == "name":
                    el = driver.find_element(By.NAME, selector)
                elif selector_type == "css":
                    el = driver.find_element(By.CSS_SELECTOR, selector)
                elif selector_type == "xpath":
                    el = driver.find_element(By.XPATH, selector)

                print(f"  FOUND: {selector_type}={selector}")
                print(f"    Tag: {el.tag_name}, ID: {el.get_attribute('id')}, Name: {el.get_attribute('name')}")

                # If it's a select, list options
                if el.tag_name.lower() == 'select':
                    select = Select(el)
                    options = select.options
                    print(f"    Options count: {len(options)}")

                    # Search for Amador
                    for opt in options:
                        opt_text = opt.text.upper()
                        opt_value = opt.get_attribute('value')
                        if 'AMADOR' in opt_text:
                            print(f"    *** AMADOR FOUND: value='{opt_value}', text='{opt.text}'")
                        if 'ALPINE' in opt_text:
                            print(f"    Alpine entry: value='{opt_value}', text='{opt.text}'")

                    # Print first 10 options
                    print("    First 10 options:")
                    for i, opt in enumerate(options[:10]):
                        print(f"      {i}: value='{opt.get_attribute('value')}', text='{opt.text}'")
            except Exception as e:
                pass  # Element not found with this selector

        # Look for all select elements on the page
        print("\n=== All SELECT elements on page ===")
        all_selects = driver.find_elements(By.TAG_NAME, "select")
        print(f"Found {len(all_selects)} select elements")

        for i, sel in enumerate(all_selects):
            sel_id = sel.get_attribute('id') or '(no id)'
            sel_name = sel.get_attribute('name') or '(no name)'
            sel_class = sel.get_attribute('class') or ''

            # Check if visible
            is_visible = sel.is_displayed()

            print(f"\n  [{i}] id='{sel_id}', name='{sel_name}', visible={is_visible}")

            if is_visible or 'county' in sel_id.lower() or 'county' in sel_name.lower():
                try:
                    select = Select(sel)
                    options = select.options
                    print(f"      Options: {len(options)}")

                    # Check for Amador
                    for opt in options:
                        if 'AMADOR' in opt.text.upper():
                            print(f"      *** AMADOR FOUND in select '{sel_id}': '{opt.text}'")

                    # Show first few options
                    for j, opt in enumerate(options[:5]):
                        print(f"        {j}: '{opt.text}' (value='{opt.get_attribute('value')}')")
                    if len(options) > 5:
                        print(f"        ... and {len(options) - 5} more")
                except Exception as e:
                    print(f"      Error reading options: {e}")

        # Save page source for analysis
        page_source_path = base_dir / "titlepro_documents_tab.html"
        page_source_path.write_text(driver.page_source)
        print(f"\n=== Page source saved to {page_source_path} ===")

        # Take screenshot
        screenshot_path = base_dir / "titlepro_documents_tab.png"
        driver.save_screenshot(str(screenshot_path))
        print(f"Screenshot saved to {screenshot_path}")

        print("\n=== Done. Press Enter to close browser ===")
        input()

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
