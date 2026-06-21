import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Set, List

from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from webdriver_manager.chrome import ChromeDriverManager

from titlepro import DOWNLOAD_DIR

DEFAULT_TITLEPRO_URL = "https://www.titlepro247.com/"
SECRETS_FILENAME = "secrets.json"
DOWNLOAD_DIRNAME = "downloaded_doc"

# TitlePro County Codes for California
# Format: county_name (lowercase) -> TitlePro county code
CALIFORNIA_COUNTY_CODES = {
    "alameda": "06001",
    "alpine": "06003",
    "amador": "06005",
    "butte": "06007",
    "calaveras": "06009",
    "colusa": "06011",
    "contra costa": "06013",
    "del norte": "06015",
    "el dorado": "06017",
    "fresno": "06019",
    "glenn": "06021",
    "humboldt": "06023",
    "imperial": "06025",
    "inyo": "06027",
    "kern": "06029",
    "kings": "06031",
    "lake": "06033",
    "lassen": "06035",
    "los angeles": "06037",
    "madera": "06039",
    "marin": "06041",
    "mariposa": "06043",
    "mendocino": "06045",
    "merced": "06047",
    "modoc": "06049",
    "mono": "06051",
    "monterey": "06053",
    "napa": "06055",
    "nevada": "06057",
    "orange": "06059",
    "placer": "06061",
    "plumas": "06063",
    "riverside": "06065",
    "sacramento": "06067",
    "san benito": "06069",
    "san bernardino": "06071",
    "san diego": "06073",
    "san francisco": "06075",
    "san joaquin": "06077",
    "san luis obispo": "06079",
    "san mateo": "06081",
    "santa barbara": "06083",
    "santa clara": "06085",
    "santa cruz": "06087",
    "shasta": "06089",
    "sierra": "06091",
    "siskiyou": "06093",
    "solano": "06095",
    "sonoma": "06097",
    "stanislaus": "06099",
    "sutter": "06101",
    "tehama": "06103",
    "trinity": "06105",
    "tulare": "06107",
    "tuolumne": "06109",
    "ventura": "06111",
    "yolo": "06113",
    "yuba": "06115",
}

def log(msg: str) -> None:
    print(f"[titlepro] {msg}", flush=True)


def load_secrets(path: Path, base_url_override: Optional[str] = None) -> Tuple[str, str, str]:
    if not path.exists():
        raise SystemExit(f"Missing secrets file at {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"secrets.json is not valid JSON: {exc}")

    username = data.get("TITLEPRO_USERNAME")
    password = data.get("TITLEPRO_PASSWORD")
    base_url = base_url_override or data.get("TITLEPRO_URL") or data.get("TITLEPRO_WEBSITE") or DEFAULT_TITLEPRO_URL
    if not username or not password:
        raise SystemExit("secrets.json must include TITLEPRO_USERNAME and TITLEPRO_PASSWORD")
    if not base_url:
        raise SystemExit("secrets.json must include TITLEPRO_URL or TITLEPRO_WEBSITE, or leave it blank to use default.")
    return username, password, base_url


def prompt_user_inputs() -> Tuple[str, str]:
    doc_num = input("Enter the document number: ").strip()
    year = input("Enter the year (YYYY): ").strip()

    if not doc_num:
        raise SystemExit("Document number is required.")
    if len(year) != 4 or not year.isdigit():
        raise SystemExit("Year must be a 4-digit value like 2024.")
    return doc_num, year


def build_driver(download_dir: Path, headless: bool = False) -> webdriver.Chrome:
    options = Options()
    prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,  # force PDFs to download instead of opening in Chrome viewer
    }
    options.add_experimental_option("prefs", prefs)

    # Headless mode - browser runs invisibly in background
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        log("Running in HEADLESS mode (browser hidden)")
    else:
        log("Running in VISIBLE mode (browser will be shown)")

    raw_path = Path(ChromeDriverManager().install())
    # webdriver-manager can occasionally return a non-executable info file; normalize to the actual binary.
    driver_path = raw_path
    if not raw_path.name.startswith("chromedriver"):
        candidate = raw_path.parent / "chromedriver"
        if candidate.exists():
            driver_path = candidate
    if not driver_path.exists():
        raise SystemExit(f"Could not locate chromedriver binary near {raw_path}")
    # Ensure executable bit is set (fixes PermissionError cases).
    try:
        driver_path.chmod(driver_path.stat().st_mode | 0o755)
    except PermissionError as exc:
        raise SystemExit(f"Unable to set execute permission on {driver_path}: {exc}")

    service = Service(str(driver_path))
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


def wait_for_download(download_dir: Path, before_files: Set[Path], timeout: int = 60) -> List[Path]:
    end = time.time() + timeout
    while time.time() < end:
        current = {p for p in download_dir.iterdir() if p.is_file()}
        crdownload = [p for p in current if p.suffix == ".crdownload"]
        new_files = [p for p in current if p not in before_files and p.suffix != ".crdownload"]
        if new_files:
            return new_files
        if crdownload:
            time.sleep(1)
            continue
        time.sleep(1)
    return []


def click_if_present(driver: webdriver.Chrome, locator: Tuple[str, str], timeout: int = 5) -> bool:
    try:
        el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        try:
            el.click()
            return True
        except ElementClickInterceptedException:
            try:
                driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:
                return False
    except TimeoutException:
        return False


def login(driver: webdriver.Chrome, wait: WebDriverWait, username: str, password: str, base_url: str) -> None:
    driver.get(base_url)
    # Handle cookie/consent banner if present (blocks login button click).
    click_if_present(driver, (By.ID, "onetrust-accept-btn-handler"), timeout=5)
    wait.until(EC.visibility_of_element_located((By.ID, "UserName"))).send_keys(username)
    wait.until(EC.visibility_of_element_located((By.ID, "Password"))).send_keys(password)
    login_btn = wait.until(EC.element_to_be_clickable((By.ID, "login-submit")))
    driver.execute_script("arguments[0].scrollIntoView(true);", login_btn)
    try:
        login_btn.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", login_btn)


def open_document_tab(wait: WebDriverWait) -> None:
    time.sleep(2)  # Wait for page to stabilize after login
    doc_tab = wait.until(EC.element_to_be_clickable((By.ID, "documents")))
    doc_tab.click()
    time.sleep(2)  # Wait for tab content to load
    # Ensure the search inputs are ready.
    try:
        wait.until(EC.presence_of_element_located((By.ID, "documentno")))
        wait.until(EC.element_to_be_clickable((By.ID, "documentno")))
    except TimeoutException:
        pass


def get_county_code(county: str) -> str:
    """
    Get TitlePro county code from county name.

    Args:
        county: County name (e.g., "amador", "Amador County", "AMADOR")

    Returns:
        TitlePro county code (e.g., "06005")

    Raises:
        ValueError if county not found
    """
    # Normalize county name
    county_normalized = county.lower().strip()

    # Replace underscores with spaces (county_id format uses underscores, e.g. san_luis_obispo)
    county_normalized = county_normalized.replace("_", " ")

    # Remove common suffixes
    for suffix in [" county", " county, ca", ", ca", " ca"]:
        if county_normalized.endswith(suffix):
            county_normalized = county_normalized[:-len(suffix)]

    county_normalized = county_normalized.strip()

    if county_normalized in CALIFORNIA_COUNTY_CODES:
        return CALIFORNIA_COUNTY_CODES[county_normalized]

    # Try partial match
    for name, code in CALIFORNIA_COUNTY_CODES.items():
        if county_normalized in name or name in county_normalized:
            return code

    raise ValueError(f"County '{county}' not found in TitlePro. Available counties: {list(CALIFORNIA_COUNTY_CODES.keys())}")


def select_county(driver: webdriver.Chrome, wait: WebDriverWait, county: str) -> None:
    """
    Select a county from the TitlePro county dropdown.

    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        county: County name or code (e.g., "amador", "06005", "Amador County, CA")
    """
    log(f"Selecting county: {county}")

    # First, we need to select California in the state dropdown
    try:
        state_select_el = wait.until(EC.element_to_be_clickable((By.ID, "StateList")))
        state_select = Select(state_select_el)

        # Check current state selection
        current_state = state_select.first_selected_option.text
        log(f"Current state: {current_state}")

        if current_state.upper() != "CALIFORNIA":
            log("Selecting California...")
            state_select.select_by_visible_text("CALIFORNIA")
            time.sleep(1)  # Wait for county dropdown to update
    except Exception as e:
        log(f"Warning: Could not select state: {e}")

    # Now select the county
    try:
        county_select_el = wait.until(EC.element_to_be_clickable((By.ID, "CountyList")))
        county_select = Select(county_select_el)

        # Check if input is already a code (starts with 0)
        if county.startswith("0") and len(county) == 5:
            county_code = county
        else:
            county_code = get_county_code(county)

        log(f"Selecting county code: {county_code}")
        county_select.select_by_value(county_code)
        time.sleep(0.5)  # Brief pause for UI to update

        # Verify selection
        selected_option = county_select.first_selected_option.text
        log(f"County selected: {selected_option}")

    except Exception as e:
        log(f"Error selecting county: {e}")
        raise


def submit_document_request(driver: webdriver.Chrome, wait: WebDriverWait, doc_num: str, year: str, county: str = None) -> None:
    """
    Submit a document request on TitlePro.

    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        doc_num: Document/instrument number
        year: Year (YYYY format)
        county: Optional county name or code. If not provided, uses current selection.
    """
    # Wait for page to be fully loaded
    time.sleep(2)

    # Select county first if provided
    if county:
        select_county(driver, wait, county)
        time.sleep(1)  # Wait for any UI updates after county selection

    # Wait for elements to be interactable (not just visible)
    year_el = wait.until(EC.element_to_be_clickable((By.ID, "year")))
    doc_el = wait.until(EC.element_to_be_clickable((By.ID, "documentno")))

    # Use JavaScript to clear and set values (more reliable)
    driver.execute_script("arguments[0].value = '';", year_el)
    driver.execute_script("arguments[0].value = '';", doc_el)
    time.sleep(0.5)

    # Click to focus, then send keys
    year_el.click()
    time.sleep(0.3)
    year_el.send_keys(year)

    doc_el.click()
    time.sleep(0.3)
    doc_el.send_keys(doc_num)

    time.sleep(0.5)
    buy_btn = wait.until(EC.element_to_be_clickable((By.ID, "btn-buyNow")))
    driver.execute_script("arguments[0].scrollIntoView(true);", buy_btn)
    time.sleep(0.3)
    try:
        buy_btn.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", buy_btn)

    time.sleep(1)
    click_if_present(driver, (By.ID, "modal-dup-documents_btn_Continue"))

def wait_for_loading(driver: webdriver.Chrome, timeout: int = 10) -> None:
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".k-loading-mask, .loading-mask, .spinner, .k-loading-image, .ajax-loader",
                )
            )
        )
    except TimeoutException:
        pass

def open_order_and_download(driver: webdriver.Chrome, wait: WebDriverWait, doc_num: str, download_dir: Path, before_files: Set[Path]) -> List[Path]:
    click_if_present(driver, (By.ID, "my-orders"), timeout=10)
    wait_for_loading(driver, timeout=10)

    # Prefer to click the View Document link for the row that matches the requested document number.
    row_xpath = f"//tr[.//td[contains(normalize-space(), '{doc_num}')]]"
    view_xpath_span = f"{row_xpath}//span[contains(@class, 'documentorderlink')]"
    view_xpath_anchor = f"{row_xpath}//a[contains(., 'View Document') or contains(., 'View Order')]"

    def try_click_view() -> bool:
        for locator in [
            (By.XPATH, view_xpath_span),
            (By.XPATH, view_xpath_anchor),
        ]:
            try:
                link_el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable(locator))
                driver.execute_script("arguments[0].scrollIntoView(true);", link_el)
                try:
                    link_el.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", link_el)
                return True
            except TimeoutException:
                continue
        return False

    # Try on current page; if not found and a next-page arrow exists, page forward once.
    if not try_click_view():
        next_locators = [
            (By.XPATH, "//a[contains(@title, 'next') or contains(@aria-label, 'next') or text()='>']"),
            (By.XPATH, "//a[contains(@class, 'k-pager-nav') and contains(@title, 'next')]"),
        ]
        clicked_next = any(click_if_present(driver, loc, timeout=3) for loc in next_locators)
        if clicked_next:
            wait_for_loading(driver, timeout=10)
            if not try_click_view():
                raise TimeoutException(f"Could not find a View link for document number {doc_num} on subsequent pages")
        else:
            raise TimeoutException(f"Could not find a View link for document number {doc_num}")

    try:
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
        driver.switch_to.window(driver.window_handles[-1])
    except TimeoutException:
        pass

    # If the viewer opens as a PDF, the download may be automatic. Also try explicit download controls.
    click_if_present(
        driver,
        (By.XPATH, "//button[contains(translate(., 'DOWNLOAD', 'download'), 'download')]"),
        timeout=10,
    ) or click_if_present(
        driver,
        (By.XPATH, "//a[contains(translate(., 'DOWNLOAD', 'download'), 'download')]"),
        timeout=10,
    )

    downloaded = wait_for_download(download_dir, before_files, timeout=60)
    return downloaded


def save_artifacts(driver: webdriver.Chrome, download_dir: Path, label: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = label.replace(" ", "_")
    screenshot_path = download_dir / f"{ts}_{safe_label}.png"
    html_path = download_dir / f"{ts}_{safe_label}.html"
    try:
        driver.save_screenshot(str(screenshot_path))
    except Exception:
        pass
    try:
        html_path.write_text(driver.page_source)
    except Exception:
        pass


def load_metadata(download_dir: Path) -> dict:
    """Load the metadata file that maps instrument numbers to filenames."""
    metadata_path = download_dir / "document_metadata.json"
    if metadata_path.exists():
        try:
            return json.loads(metadata_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_metadata(download_dir: Path, metadata: dict) -> None:
    """Save the metadata file."""
    metadata_path = download_dir / "document_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))


def download_document(doc_num: str, year: str, headless: bool = False, owner_name: str = None, county: str = None,
                      document_type: str = None, found_via_names: List[str] = None,
                      base_url_override: Optional[str] = None) -> dict:
    """
    Download a document from TitlePro247.

    [DEDUPLICATION_DEBUGLOGS] - Enhanced with deduplication metadata support

    Args:
        doc_num: Document/instrument number
        year: Year (YYYY format)
        headless: If True, run browser invisibly. If False, show browser window.
        owner_name: Optional owner name for organizing downloads into subfolders
        county: County name or code (e.g., "amador", "06005", "Amador County, CA").
                If not provided, uses TitlePro's default selection (Alpine County).
        document_type: Optional document type (e.g., "GRANT DEED", "DEED OF TRUST")
        found_via_names: Optional list of search names this document was found under.
                        Used for deduplication tracking in multi-name searches.

    Returns:
        dict with status, message, and downloaded files info
    """
    # secrets.json lives at config/secrets.json (or project root as fallback)
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    secrets_path = base_dir / "config" / SECRETS_FILENAME
    if not secrets_path.exists():
        secrets_path = base_dir / SECRETS_FILENAME

    # Create owner-specific subfolder if owner_name provided
    if owner_name:
        safe_owner = owner_name.replace(" ", "_").replace(",", "")
        download_dir = DOWNLOAD_DIR / safe_owner
    else:
        download_dir = DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "status": "success",
        "message": "",
        "files": [],
        "download_dir": str(download_dir),
        "doc_num": doc_num,
        "county": county,
        "base_url": base_url_override,
    }

    try:
        username, password, base_url = load_secrets(secrets_path, base_url_override=base_url_override)
        result["base_url"] = base_url
    except (SystemExit, Exception) as exc:
        log(f"Failed to load secrets: {exc}")
        result["status"] = "error"
        result["message"] = f"Failed to load secrets: {exc}"
        return result

    try:
        driver = build_driver(download_dir, headless=headless)
    except (SystemExit, Exception) as exc:
        log(f"Failed to start browser: {exc}")
        result["status"] = "error"
        result["message"] = f"Failed to start browser: {exc}"
        return result

    wait = WebDriverWait(driver, 25)
    before_files = {p for p in download_dir.iterdir() if p.is_file()}

    try:
        log("Logging in...")
        login(driver, wait, username, password, base_url)
        log("Opening Documents tab immediately post-login...")
        open_document_tab(wait)
        county_info = f" in {county}" if county else ""
        log(f"Submitting document request for #{doc_num} ({year}){county_info}...")
        submit_document_request(driver, wait, doc_num, year, county=county)
        log("Opening order and attempting download...")
        downloaded = open_order_and_download(driver, wait, doc_num, download_dir, before_files)
        if downloaded:
            result["files"] = [p.name for p in downloaded]
            result["message"] = f"Downloaded {len(downloaded)} file(s): " + ", ".join(p.name for p in downloaded)
            log(result["message"])

            # Save metadata mapping instrument number to filename
            # [DEDUPLICATION_DEBUGLOGS] Enhanced metadata with deduplication fields
            metadata = load_metadata(download_dir)
            doc_metadata = {
                "filename": downloaded[0].name if downloaded else None,
                "year": year,
                "downloaded_at": datetime.now().isoformat(),
                "all_files": [p.name for p in downloaded]
            }
            # Add deduplication tracking fields if provided
            if document_type:
                doc_metadata["document_type"] = document_type
            if found_via_names:
                doc_metadata["found_via_names"] = found_via_names
                doc_metadata["is_party_specific"] = len(found_via_names) == 1
            metadata[doc_num] = doc_metadata
            save_metadata(download_dir, metadata)
            log(f"Saved metadata: {doc_num} -> {downloaded[0].name}")
        else:
            result["status"] = "warning"
            result["message"] = f"Requested download for document #{doc_num} ({year}) but no new files detected"
            log(result["message"])
    except Exception as exc:
        log(f"Error encountered: {exc}")
        save_artifacts(driver, download_dir, "failure")

        # Check if files were actually downloaded despite the error
        # This handles cases where connection drops but file still downloaded
        # Wait a bit for any in-progress downloads to complete
        pdf_files = []
        for retry in range(3):
            time.sleep(2)  # Wait for potential in-flight downloads
            after_files = {p for p in download_dir.iterdir() if p.is_file()}
            new_files = sorted(after_files - before_files)

            # Filter for actual document files (PDFs, not debug artifacts)
            pdf_files = [f for f in new_files if f.suffix.lower() == '.pdf']
            if pdf_files:
                break
            log(f"Checking for downloaded files (attempt {retry + 1}/3)...")

        if pdf_files:
            # Files were downloaded despite the error!
            result["status"] = "success"
            result["files"] = [p.name for p in pdf_files]
            result["message"] = f"Downloaded {len(pdf_files)} file(s) (connection dropped but files saved): " + ", ".join(p.name for p in pdf_files)
            result["connection_error"] = str(exc)
            log(result["message"])

            # Save metadata
            # [DEDUPLICATION_DEBUGLOGS] Enhanced metadata with deduplication fields
            metadata = load_metadata(download_dir)
            doc_metadata = {
                "filename": pdf_files[0].name if pdf_files else None,
                "year": year,
                "downloaded_at": datetime.now().isoformat(),
                "all_files": [p.name for p in pdf_files],
                "note": "Downloaded despite connection error"
            }
            # Add deduplication tracking fields if provided
            if document_type:
                doc_metadata["document_type"] = document_type
            if found_via_names:
                doc_metadata["found_via_names"] = found_via_names
                doc_metadata["is_party_specific"] = len(found_via_names) == 1
            metadata[doc_num] = doc_metadata
            save_metadata(download_dir, metadata)
            log(f"Saved metadata despite error: {doc_num} -> {pdf_files[0].name}")
        else:
            result["status"] = "error"
            result["message"] = str(exc)
    finally:
        try:
            driver.quit()
        except:
            pass  # Driver may already be closed

    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download documents from TitlePro247")
    parser.add_argument("--doc", "-d", help="Document number")
    parser.add_argument("--year", "-y", help="Year (YYYY)")
    parser.add_argument("--county", "-c", help="County name or code (e.g., 'amador', '06005', 'Amador County, CA')")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (invisible)")
    parser.add_argument("--visible", action="store_true", help="Run browser in visible mode (show automation)")
    parser.add_argument("--owner", "-o", help="Owner name for subfolder organization")

    args = parser.parse_args()

    # Determine headless mode (default to visible if --visible flag, otherwise check --headless)
    headless = args.headless and not args.visible

    # If no command line args, prompt interactively
    if args.doc and args.year:
        doc_num = args.doc
        year = args.year
    else:
        doc_num, year = prompt_user_inputs()

    result = download_document(doc_num, year, headless=headless, owner_name=args.owner, county=args.county)

    if result["status"] == "error":
        raise SystemExit(f"Error: {result['message']}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
