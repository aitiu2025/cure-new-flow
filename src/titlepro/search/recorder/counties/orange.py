"""
Orange County Recorder search automation.
Website: https://cr.occlerkrecorder.gov/RecorderWorksInternet/
"""

import time
from typing import List
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException
)

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


class OrangeCountyRecorder(BaseRecorderSearch):
    """
    Selenium automation for Orange County Clerk-Recorder website.

    Website URL: https://cr.occlerkrecorder.gov/RecorderWorksInternet/

    Search Strategy:
    - Name format: "Last First" (e.g., "Lau Casey")
    - Party Type: "Grantor/Grantee" for best results
    - Allow Partial Match: True
    """

    # Element selectors (from website analysis)
    SELECTORS = {
        # Navigation
        "name_tab": "//a[contains(text(), 'Name')]",

        # Search form elements
        "party_type_dropdown": "MainContent_MainMenu1_SearchByName1_partytype",
        "name_field": "MainContent_MainMenu1_SearchByName1_nameForSearch",
        "start_date_field": "MainContent_MainMenu1_SearchByName1_startdate",
        "end_date_field": "MainContent_MainMenu1_SearchByName1_enddate",
        "partial_match_checkbox": "MainContent_MainMenu1_SearchByName1_allowPartial",
        "search_button": "MainContent_MainMenu1_SearchByName1_btnSearch",

        # Results page
        "results_table": "//table[contains(@class, 'rgMasterTable')]",
        "result_rows": "//table[contains(@class, 'rgMasterTable')]//tbody//tr[contains(@class, 'rgRow') or contains(@class, 'rgAltRow')]",
        "no_results": "//*[contains(text(), '0 Result')]",
        "back_to_search": "//a[contains(text(), 'Back to Search')]",
        "result_count": "//*[contains(text(), 'Result(s)')]"
    }

    def __init__(self, start_date: str = "01/01/2010", end_date: str = None, partial_match: bool = True):
        super().__init__(start_date=start_date, end_date=end_date)
        self.partial_match = partial_match

    @property
    def county_name(self) -> str:
        return "Orange"

    @property
    def base_url(self) -> str:
        return "https://cr.occlerkrecorder.gov/RecorderWorksInternet/"

    def setup_driver(self):
        """Initialize Chrome WebDriver with appropriate options."""
        options = Options()
        # Run in visible mode as per user preference
        # options.add_argument("--headless")  # Commented out for visible browser

        #options.add_argument("--headless=new")  # Headless mode for server
        # Common options for stability
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        # Avoid detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        try:
            if USE_WEBDRIVER_MANAGER:
                # Get the correct chromedriver path
                driver_path = ChromeDriverManager().install()
                # Fix: webdriver-manager sometimes returns wrong file, get the actual chromedriver
                if not driver_path.endswith('chromedriver'):
                    import os
                    driver_dir = os.path.dirname(driver_path)
                    driver_path = os.path.join(driver_dir, 'chromedriver')
                service = Service(driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"WebDriver manager failed: {e}")
            print("Trying default Chrome driver...")
            # Fallback to system chromedriver
            self.driver = webdriver.Chrome(options=options)

        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 15)

        print(f"Browser initialized for {self.county_name} County")

    def navigate_to_search(self):
        """Navigate to the recorder website and access the Name search tab."""
        print(f"Navigating to {self.base_url}")
        self.driver.get(self.base_url)
        time.sleep(2)

        # Click on Name tab
        try:
            name_tab = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.SELECTORS["name_tab"]))
            )
            name_tab.click()
            time.sleep(1)
            print("  Clicked Name tab")
        except TimeoutException:
            print("  Warning: Name tab not found, may already be on name search page")

    def _set_party_type(self, party_type: str):
        """Set the party type dropdown value."""
        try:
            dropdown = self.wait.until(
                EC.presence_of_element_located((By.ID, self.SELECTORS["party_type_dropdown"]))
            )
            select = Select(dropdown)

            # Map common party type names to dropdown values
            party_type_map = {
                "Grantor/Grantee": "Grantor/Grantee",
                "All": "All",
                "Grantor": "Grantor",
                "Grantee": "Grantee"
            }

            value = party_type_map.get(party_type, party_type)
            select.select_by_visible_text(value)
            time.sleep(0.5)
            print(f"  Set party type: {value}")
        except Exception as e:
            print(f"  Warning: Could not set party type: {e}")

    def _set_dates(self):
        """Set the search date range - optimized for speed."""
        try:
            from selenium.webdriver.common.keys import Keys

            # Find all text inputs that could be date fields
            inputs = self.driver.find_elements(By.XPATH, "//input[@type='text']")
            date_inputs = []

            for inp in inputs:
                inp_id = (inp.get_attribute('id') or '').lower()
                inp_name = (inp.get_attribute('name') or '').lower()
                if 'date' in inp_id or 'date' in inp_name:
                    date_inputs.append(inp)

            if len(date_inputs) >= 2:
                # Use JavaScript for faster date setting
                self.driver.execute_script(
                    "arguments[0].value = arguments[1];",
                    date_inputs[0], self.start_date
                )
                self.driver.execute_script(
                    "arguments[0].value = arguments[1];",
                    date_inputs[1], self.end_date
                )
                print(f"  Set date range: {self.start_date} to {self.end_date}")
            else:
                print(f"  Warning: Could not find date fields, using website defaults")

        except Exception as e:
            print(f"  Warning: Could not set dates: {e}")

    def _enable_partial_match(self):
        """Enable partial match checkbox if not already checked."""
        self._set_partial_match(True)

    def _set_partial_match(self, enabled: bool):
        """Set partial match checkbox state."""
        try:
            # Try multiple ways to find the checkbox
            checkbox_selectors = [
                (By.ID, self.SELECTORS["partial_match_checkbox"]),
                (By.XPATH, "//input[@type='checkbox'][contains(@id, 'partial') or contains(@id, 'Partial')]"),
                (By.XPATH, "//input[@type='checkbox'][contains(@name, 'partial') or contains(@name, 'Partial')]"),
                (By.XPATH, "//label[contains(text(), 'Partial')]/input[@type='checkbox']"),
                (By.XPATH, "//label[contains(text(), 'Partial')]//preceding-sibling::input[@type='checkbox']"),
            ]

            checkbox = None
            for selector in checkbox_selectors:
                try:
                    checkbox = self.driver.find_element(*selector)
                    if checkbox:
                        break
                except:
                    continue

            if checkbox:
                is_selected = checkbox.is_selected()
                if enabled and not is_selected:
                    checkbox.click()
                    print("  Enabled partial match")
                elif not enabled and is_selected:
                    checkbox.click()
                    print("  Disabled partial match")
                else:
                    state = "enabled" if enabled else "disabled"
                    print(f"  Partial match already {state}")
            else:
                print("  Warning: Partial match checkbox not found")
        except Exception as e:
            print(f"  Warning: Could not set partial match: {e}")

    def set_partial_match(self, enabled: bool):
        """Public setter for partial match behavior."""
        self.partial_match = bool(enabled)

    def _enter_name(self, name: str):
        """Enter the name to search for."""
        name_field = self.wait.until(
            EC.presence_of_element_located((By.ID, self.SELECTORS["name_field"]))
        )
        name_field.clear()
        name_field.send_keys(name)
        time.sleep(0.5)
        print(f"  Entered name: {name}")

    def _click_search(self):
        """Click the search button and wait for results."""
        search_button = self.wait.until(
            EC.element_to_be_clickable((By.ID, self.SELECTORS["search_button"]))
        )
        search_button.click()
        print("  Clicked search button")

        # Wait for results to load
        time.sleep(3)

    def perform_search(self, name: str, party_type: str = "Grantor/Grantee") -> List[DocumentRecord]:
        """
        Perform a name search on Orange County Recorder.

        Args:
            name: Name to search (use "Last First" format, e.g., "Lau Casey")
            party_type: One of "All", "Grantor", "Grantee", "Grantor/Grantee"

        Returns:
            List of DocumentRecord objects
        """
        print(f"\n  Performing search:")
        print(f"    Name: {name}")
        print(f"    Party Type: {party_type}")

        # Set up search parameters
        self._set_party_type(party_type)
        self._enter_name(name)
        self._set_dates()
        self._set_partial_match(self.partial_match)

        # Execute search
        self._click_search()

        # Check for no results
        try:
            no_results = self.driver.find_element(By.XPATH, self.SELECTORS["no_results"])
            if no_results:
                print("  No results found")
                return []
        except NoSuchElementException:
            pass  # Results exist

        # Extract results
        return self.extract_results()

    def extract_results(self) -> List[DocumentRecord]:
        """Extract document records from the results table."""
        documents = []

        try:
            # Wait for page to load
            time.sleep(3)

            # Check result count
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                if "0 Result" in page_text:
                    print("  No results found for this search")
                    return []
                # Try to find result count
                import re
                match = re.search(r'(\d+)\s*Result', page_text)
                if match:
                    print(f"  Found {match.group(1)} Result(s)")
            except:
                pass

            # Use JavaScript to extract data - specifically for Orange County RecorderWorks
            extract_script = """
            var results = [];
            var seenDocNums = {};

            // The Orange County site uses a RadGrid with specific structure
            // Column order: Document Number | Grantors | Grantees | Grantor/Grantees | Document Type | Rec. Date | Pages

            // Strategy 1: Try to find the RadGrid master table
            var masterTable = document.querySelector('table.rgMasterTable');

            if (masterTable) {
                var rows = masterTable.querySelectorAll('tbody tr.rgRow, tbody tr.rgAltRow');
                for (var i = 0; i < rows.length; i++) {
                    var cells = rows[i].querySelectorAll('td');
                    if (cells.length >= 7) {
                        var docNum = cells[0] ? cells[0].innerText.trim() : '';
                        if (docNum && docNum.match(/^20\\d{10,11}$/) && !seenDocNums[docNum]) {
                            seenDocNums[docNum] = true;
                            results.push({
                                document_number: docNum,
                                grantors: cells[1] ? cells[1].innerText.trim() : '',
                                grantees: cells[2] ? cells[2].innerText.trim() : '',
                                grantor_grantees: cells[3] ? cells[3].innerText.trim() : '',
                                document_type: cells[4] ? cells[4].innerText.trim() : '',
                                recording_date: cells[5] ? cells[5].innerText.trim() : '',
                                pages: cells[6] ? cells[6].innerText.trim() : ''
                            });
                        }
                    }
                }
            }

            // Strategy 2: If no results, try any table with proper structure
            if (results.length === 0) {
                var allTables = document.querySelectorAll('table');
                for (var t = 0; t < allTables.length; t++) {
                    var table = allTables[t];
                    var rows = table.querySelectorAll('tr');
                    for (var i = 0; i < rows.length; i++) {
                        var cells = rows[i].querySelectorAll('td');
                        if (cells.length >= 7) {
                            var docNum = cells[0] ? cells[0].innerText.trim() : '';
                            if (docNum && docNum.match(/^20\\d{10,11}$/) && !seenDocNums[docNum]) {
                                seenDocNums[docNum] = true;
                                results.push({
                                    document_number: docNum,
                                    grantors: cells[1] ? cells[1].innerText.trim() : '',
                                    grantees: cells[2] ? cells[2].innerText.trim() : '',
                                    grantor_grantees: cells[3] ? cells[3].innerText.trim() : '',
                                    document_type: cells[4] ? cells[4].innerText.trim() : '',
                                    recording_date: cells[5] ? cells[5].innerText.trim() : '',
                                    pages: cells[6] ? cells[6].innerText.trim() : ''
                                });
                            }
                        }
                    }
                    if (results.length > 0) break;
                }
            }

            // Strategy 3: Parse the visible text - split by tab first to get columns
            if (results.length === 0) {
                var bodyText = document.body.innerText;
                // Split by tab to get column segments
                var segments = bodyText.split('\\t');

                for (var i = 0; i < segments.length; i++) {
                    var segment = segments[i].trim();
                    // Check if this segment starts with a document number
                    var docMatch = segment.match(/^(20\\d{10,11})/);
                    if (docMatch && !seenDocNums[docMatch[1]]) {
                        var docNum = docMatch[1];
                        seenDocNums[docNum] = true;

                        // Get the next 6 segments for the columns
                        // Clean up each segment by removing extra newlines
                        var cleanSegment = function(s) {
                            return s ? s.replace(/\\n+/g, ' ').trim() : '';
                        };

                        var grantors = cleanSegment(segments[i+1] || '');
                        var grantees = cleanSegment(segments[i+2] || '');
                        var grantor_grantees = cleanSegment(segments[i+3] || '');
                        var doc_type = cleanSegment(segments[i+4] || '');
                        var rec_date = cleanSegment(segments[i+5] || '');
                        var pages = cleanSegment(segments[i+6] || '');

                        // The date and pages might be in one segment like "9/20/2005\\t2"
                        // or the date might contain the pages after it
                        if (rec_date && rec_date.match(/\\d+\\/\\d+\\/\\d+/)) {
                            var dateParts = rec_date.split(/\\s+/);
                            if (dateParts.length >= 1) {
                                rec_date = dateParts[0];
                            }
                            if (dateParts.length >= 2 && !pages) {
                                pages = dateParts[1];
                            }
                        }

                        results.push({
                            document_number: docNum,
                            grantors: grantors,
                            grantees: grantees,
                            grantor_grantees: grantor_grantees,
                            document_type: doc_type,
                            recording_date: rec_date,
                            pages: pages
                        });
                    }
                }
            }

            return {
                results: results,
                debug: {
                    masterTableFound: !!masterTable,
                    totalResults: results.length
                }
            };
            """

            js_data = self.driver.execute_script(extract_script)

            if js_data:
                results_list = js_data.get('results', [])
                debug_info = js_data.get('debug', {})

                print(f"  Debug: {debug_info.get('docElementsFound', 0)} doc elements, {debug_info.get('totalRows', 0)} total rows")

                if results_list:
                    print(f"  Extracted {len(results_list)} document(s) via JavaScript")
                    for r in results_list:
                        doc = DocumentRecord(
                            document_number=r.get('document_number', ''),
                            grantors=r.get('grantors', ''),
                            grantees=r.get('grantees', ''),
                            grantor_grantees=r.get('grantor_grantees', ''),
                            document_type=r.get('document_type', ''),
                            recording_date=r.get('recording_date', ''),
                            pages=r.get('pages', '')
                        )
                        documents.append(doc)
                else:
                    print("  No documents found in structured data")
                    # Print sample of page text to debug
                    sample = debug_info.get('sampleText', '')[:300]
                    print(f"  Page sample: {sample}...")
            else:
                print("  JavaScript extraction returned nothing")

        except Exception as e:
            print(f"  Error extracting results: {e}")
            import traceback
            traceback.print_exc()

        return documents

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if text:
            return text.strip().replace('\n', ' ').replace('\r', '')
        return ""

    def return_to_search(self):
        """Navigate back to search form for another search."""
        try:
            # Try clicking "Back to Search" link
            back_link = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.SELECTORS["back_to_search"]))
            )
            back_link.click()
            time.sleep(2)
            print("  Returned to search form")
        except TimeoutException:
            # If no back link, navigate to URL again
            print("  Back link not found, reloading page")
            self.navigate_to_search()


# Convenience function for standalone usage
def search_orange_county(name1: str, name2: str,
                         start_date: str = "01/01/2010",
                         end_date: str = None,
                         output_file: str = None) -> dict:
    """
    Search Orange County Recorder for two names and find common documents.

    Args:
        name1: First name to search (use "Last First" format)
        name2: Second name to search (use "Last First" format)
        start_date: Search start date (MM/DD/YYYY)
        end_date: Search end date (MM/DD/YYYY), defaults to today
        output_file: Optional JSON output filename

    Returns:
        Dictionary with search results

    Example:
        results = search_orange_county("Lau Casey", "Lau Brandi")
    """
    with OrangeCountyRecorder(start_date=start_date, end_date=end_date) as recorder:
        recorder.navigate_to_search()
        results = recorder.search_two_names(name1, name2)

        if output_file:
            recorder.export_json(results, output_file)

        return results
