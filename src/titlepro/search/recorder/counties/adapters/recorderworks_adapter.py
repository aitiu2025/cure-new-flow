"""
RecorderWorks Platform Adapter for California County Recorders.

Supports counties using the RecorderWorks platform:
- Amador, Calaveras, Imperial, Merced, Orange, Stanislaus

The RecorderWorks platform uses ASP.NET with Telerik RadGrid tables.
"""

import os
import time
from typing import List, Dict, Optional
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


class RecorderWorksAdapter(BaseRecorderSearch):
    """
    Selenium automation adapter for RecorderWorks platform.

    This adapter works with counties that use the RecorderWorks system,
    which features ASP.NET WebForms with Telerik RadGrid result tables.

    Search Strategy:
    - Name format: "Last First" (e.g., "Lau Casey")
    - Party Type: "Grantor/Grantee" for best results
    - Allow Partial Match: Configurable
    """

    # Default selectors (can be overridden by config)
    DEFAULT_SELECTORS = {
        # Navigation
        "name_tab": "//a[contains(text(), 'Name')]",

        # Search form elements
        "party_type_dropdown": "MainContent_MainMenu1_SearchByName1_partytype",
        "name_field": "MainContent_MainMenu1_SearchByName1_nameForSearch",
        "start_date_field": "MainContent_MainMenu1_SearchByName1_startdate",
        "end_date_field": "MainContent_MainMenu1_SearchByName1_enddate",
        "partial_match_checkbox": "MainContent_MainMenu1_SearchByName1_allowPartial",
        "search_button": "MainContent_MainMenu1_SearchByName1_btnSearch",

        # Results page - updated selectors for 2024+ RecorderWorks version
        "results_table": "//table[contains(@class, 'rgMasterTable')]",
        "result_rows": "tr.searchResultRow",
        "no_results": "//*[contains(text(), '0 Result')]",
        "back_to_search": "//a[contains(text(), 'Back to Search')]",
        "result_count": "//*[contains(text(), 'Result(s)')]"
    }

    def __init__(self, config: Dict, start_date: str = "01/01/2010", end_date: str = None, partial_match: bool = True):
        """
        Initialize RecorderWorks adapter with county configuration.

        Args:
            config: County configuration dictionary from JSON
            start_date: Search start date in MM/DD/YYYY format
            end_date: Search end date in MM/DD/YYYY format (defaults to today)
            partial_match: Whether to enable partial match by default
        """
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config
        self.partial_match = partial_match

        # Extract config values
        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "")
        self._search_url = config.get("search_url", self._base_url)

        # Merge selectors (config overrides defaults)
        self.selectors = {**self.DEFAULT_SELECTORS}
        if "selectors" in config:
            self.selectors.update(config["selectors"])

        # Party type mapping (can be customized per county)
        self.party_type_map = config.get("party_type_map", {
            "Grantor/Grantee": "Grantor/Grantee",
            "All": "All",
            "Grantor": "Grantor",
            "Grantee": "Grantee"
        })

        # Available party types for this county
        self.available_party_types = config.get("party_types", ["All", "Grantor", "Grantee", "Grantor/Grantee"])
        self.default_party_type = config.get("default_party_type", "Grantor/Grantee")

        # Name format handling
        # Some counties need "Last, First" (with comma) vs "Last First" (space only)
        self.name_format = config.get("name_format", "Last First")
        self.name_separator = config.get("name_separator", " ")  # Default is space

        # Document number patterns - support multiple patterns per county
        # Some counties use YYYY-NNNNNNN format (e.g., Amador: 2013-0003290)
        # Others use 20XXXXXXXXXXX format (e.g., Orange: 2024000114065)
        self.doc_number_patterns = config.get("doc_number_patterns", [])
        if not self.doc_number_patterns:
            self.doc_number_patterns = [config.get("doc_number_pattern", r"^20\d{10,11}$")]

        # Create a combined regex pattern for extraction
        self.doc_number_pattern = self._build_combined_pattern()

    def _build_combined_pattern(self) -> str:
        """Build a combined regex pattern from multiple patterns."""
        if len(self.doc_number_patterns) == 1:
            return self.doc_number_patterns[0]
        # Combine patterns with OR, removing ^ and $ anchors for combination
        patterns = []
        for p in self.doc_number_patterns:
            p = p.strip('^$')
            patterns.append(f"({p})")
        return f"^({'|'.join(patterns)})$"

    def format_name_for_search(self, name: str) -> str:
        """
        Format a name according to county-specific requirements.

        Input is assumed to be "Last First" format.
        Output format depends on county config (e.g., "Last, First" for Amador).

        Args:
            name: Name in "Last First" format

        Returns:
            Formatted name for this county's search
        """
        parts = name.strip().split()
        if len(parts) < 2:
            return name  # Single word, return as-is

        # First part is last name, rest is first name(s)
        last_name = parts[0]
        first_name = " ".join(parts[1:])

        # Apply county-specific separator
        return f"{last_name}{self.name_separator}{first_name}"

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    def setup_driver(self):
        """Initialize Chrome WebDriver with appropriate options."""
        options = Options()

        # Common options for stability
        # options.add_argument("--headless=new")
        # options.add_argument("--headless")
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
                driver_path = ChromeDriverManager().install()
                if not driver_path.endswith('chromedriver'):
                    driver_dir = os.path.dirname(driver_path)
                    driver_path = os.path.join(driver_dir, 'chromedriver')
                service = Service(driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"WebDriver manager failed: {e}")
            print("Trying default Chrome driver...")
            self.driver = webdriver.Chrome(options=options)

        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 15)

        print(f"Browser initialized for {self.county_name} County (RecorderWorks)")

    def navigate_to_search(self):
        """Navigate to the recorder website and access the Name search tab."""
        url = self._search_url or self._base_url
        print(f"Navigating to {url}")
        self.driver.get(url)
        time.sleep(2)

        # Click on Name tab
        try:
            name_tab = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.selectors["name_tab"]))
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
                EC.presence_of_element_located((By.ID, self.selectors["party_type_dropdown"]))
            )
            select = Select(dropdown)

            # Get available options from dropdown
            available_options = [opt.text for opt in select.options]

            # Determine the value to use
            value = self.party_type_map.get(party_type, party_type)

            # If requested value not available, use fallback
            if value not in available_options:
                # Fallback order: "All" -> first available option
                if "All" in available_options:
                    value = "All"
                    print(f"  Note: '{party_type}' not available, using 'All'")
                else:
                    value = available_options[0] if available_options else "All"
                    print(f"  Note: '{party_type}' not available, using '{value}'")

            select.select_by_visible_text(value)
            time.sleep(0.5)
            print(f"  Set party type: {value}")
        except Exception as e:
            print(f"  Warning: Could not set party type: {e}")

    def _set_dates(self):
        """Set the search date range."""
        try:
            inputs = self.driver.find_elements(By.XPATH, "//input[@type='text']")
            date_inputs = []

            for inp in inputs:
                inp_id = (inp.get_attribute('id') or '').lower()
                inp_name = (inp.get_attribute('name') or '').lower()
                if 'date' in inp_id or 'date' in inp_name:
                    date_inputs.append(inp)

            if len(date_inputs) >= 2:
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
                print("  Warning: Could not find date fields, using website defaults")

        except Exception as e:
            print(f"  Warning: Could not set dates: {e}")

    def _set_partial_match(self, enabled: bool):
        """Set partial match checkbox state."""
        try:
            checkbox_selectors = [
                (By.ID, self.selectors["partial_match_checkbox"]),
                (By.XPATH, "//input[@type='checkbox'][contains(@id, 'partial') or contains(@id, 'Partial')]"),
                (By.XPATH, "//input[@type='checkbox'][contains(@name, 'partial') or contains(@name, 'Partial')]"),
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
                print("  Warning: Partial match checkbox not found")
        except Exception as e:
            print(f"  Warning: Could not set partial match: {e}")

    def set_partial_match(self, enabled: bool):
        """Public setter for partial match behavior."""
        self.partial_match = bool(enabled)

    def _enter_name(self, name: str):
        """Enter the name to search for."""
        name_field = self.wait.until(
            EC.presence_of_element_located((By.ID, self.selectors["name_field"]))
        )
        name_field.clear()
        name_field.send_keys(name)
        time.sleep(0.5)
        print(f"  Entered name: {name}")

    def _click_search(self):
        """Click the search button and wait for results."""
        search_button = self.wait.until(
            EC.element_to_be_clickable((By.ID, self.selectors["search_button"]))
        )
        search_button.click()
        print("  Clicked search button")
        time.sleep(3)

    def perform_search(self, name: str, party_type: str = "Grantor/Grantee") -> List[DocumentRecord]:
        """
        Perform a name search on the RecorderWorks platform.

        Args:
            name: Name to search (use "Last First" format, e.g., "Lau Casey")
            party_type: One of "All", "Grantor", "Grantee", "Grantor/Grantee"

        Returns:
            List of DocumentRecord objects
        """
        # Format name according to county requirements
        formatted_name = self.format_name_for_search(name)

        print(f"\n  Performing search:")
        print(f"    Original Name: {name}")
        print(f"    Formatted Name: {formatted_name}")
        print(f"    Party Type: {party_type}")
        print(f"    County: {self.county_name}")

        # Set up search parameters
        self._set_party_type(party_type)
        self._enter_name(formatted_name)
        self._set_dates()
        self._set_partial_match(self.partial_match)

        # Execute search
        self._click_search()

        # Check for no results
        try:
            no_results = self.driver.find_element(By.XPATH, self.selectors["no_results"])
            if no_results:
                print("  No results found")
                return []
        except NoSuchElementException:
            pass

        return self.extract_results()

    def extract_results(self) -> List[DocumentRecord]:
        """Extract document records from the RecorderWorks results table."""
        documents = []

        try:
            time.sleep(3)

            # Check result count
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                if "0 Result" in page_text:
                    print("  No results found for this search")
                    return []
                import re
                match = re.search(r'(\d+)\s*Result', page_text)
                if match:
                    print(f"  Found {match.group(1)} Result(s)")
            except:
                pass

            # JavaScript extraction - Updated for 2024+ RecorderWorks structure
            # Supports multiple document number formats:
            # - Orange format: 2024000114065 (20XXXXXXXXXXX)
            # - Amador format: 2013-0003290 (YYYY-NNNNNNN)
            extract_script = """
            var results = [];
            var seenDocNums = {};
            var docPatternStr = arguments[0];
            var docPattern = new RegExp(docPatternStr);

            // Also create flexible patterns for different counties
            var flexPatterns = [
                /^20\\d{10,}$/,           // Orange format: 2024000114065
                /^\\d{4}-\\d{5,}$/,        // Amador format: 2013-0003290
                /^\\d{4}-\\d+$/,           // Generic year-number format
            ];

            // Helper to check if text matches any doc pattern
            function isDocNumber(text) {
                if (!text) return false;
                text = text.trim();
                if (docPattern.test(text)) return true;
                for (var i = 0; i < flexPatterns.length; i++) {
                    if (flexPatterns[i].test(text)) return true;
                }
                return false;
            }

            // Helper to extract names from containers
            function extractNames(container, selector) {
                var names = [];
                if (container) {
                    var items = container.querySelectorAll(selector);
                    for (var i = 0; i < items.length; i++) {
                        var name = items[i].innerText.trim();
                        if (name) names.push(name);
                    }
                }
                return names.join('; ');
            }

            // Strategy 1: New RecorderWorks structure with searchResultRow
            var rows = document.querySelectorAll('tr.searchResultRow');

            if (rows.length > 0) {
                for (var i = 0; i < rows.length; i++) {
                    var row = rows[i];
                    var cells = row.querySelectorAll('td');

                    // Find document number (usually in cells 2-3)
                    var docNum = null;
                    var docCellIdx = -1;
                    for (var c = 0; c < Math.min(5, cells.length); c++) {
                        var cellText = cells[c].innerText.trim();
                        if (isDocNumber(cellText)) {
                            docNum = cellText;
                            docCellIdx = c;
                            break;
                        }
                    }

                    if (!docNum || seenDocNums[docNum]) continue;
                    seenDocNums[docNum] = true;

                    // Extract from docTypeGrtGrteeContainer (Orange County style)
                    var container = row.querySelector('.docTypeGrtGrteeContainer');
                    var grantors = '';
                    var grantees = '';
                    var grantor_grantees = '';
                    var doc_type = '';

                    if (container) {
                        // Grantors from GrtContainer
                        var grtContainer = container.querySelector('.GrtContainer');
                        grantors = extractNames(grtContainer, 'p.enableHighlight');

                        // Grantees from GrteeContainer
                        var grteeContainer = container.querySelector('.GrteeContainer');
                        grantees = extractNames(grteeContainer, 'p.enableHighlight');

                        // Grantor/Grantees (searched party) from GrGrteeContainer
                        var grGrteeContainer = container.querySelector('.GrGrteeContainer');
                        if (grGrteeContainer) {
                            var items = grGrteeContainer.querySelectorAll('p');
                            var names = [];
                            for (var p = 0; p < items.length; p++) {
                                var name = items[p].innerText.trim();
                                if (name) names.push(name);
                            }
                            grantor_grantees = names.join('; ');
                        }

                        // Document type from DocTypeContainer
                        var docTypeContainer = container.querySelector('.DocTypeContainer');
                        if (docTypeContainer) {
                            doc_type = docTypeContainer.innerText.trim();
                        }
                    } else {
                        // Amador/other county style - data is in cells directly
                        // Cell structure: checkbox | checkbox | docNum | docNum | combined_text | date | pages
                        // Combined text contains: grantors, grantor_grantees, doc_type
                        if (cells.length >= 5) {
                            var combinedCell = null;
                            // Find the cell with combined data (after doc number cells)
                            for (var c = docCellIdx + 1; c < cells.length; c++) {
                                var text = cells[c].innerText.trim();
                                // Skip if it's a date or number
                                if (!/^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(text) && !/^\\d{1,3}$/.test(text) && text.length > 5) {
                                    combinedCell = cells[c];
                                    break;
                                }
                            }

                            if (combinedCell) {
                                var lines = combinedCell.innerText.split('\\n').map(function(l) { return l.trim(); }).filter(function(l) { return l; });
                                // Last line is usually doc type
                                if (lines.length > 0) {
                                    doc_type = lines[lines.length - 1];
                                    // Other lines are names
                                    var nameLines = lines.slice(0, -1);
                                    grantor_grantees = nameLines.join('; ');
                                }
                            }
                        }
                    }

                    // Recording date and pages in last 2 cells
                    var rec_date = cells.length >= 2 ? cells[cells.length - 2].innerText.trim() : '';
                    var pages = cells.length >= 1 ? cells[cells.length - 1].innerText.trim() : '';

                    // Validate date format
                    if (!/^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(rec_date)) {
                        // Try to find date in row
                        for (var c = cells.length - 1; c >= 0; c--) {
                            var txt = cells[c].innerText.trim();
                            if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{4}$/.test(txt)) {
                                rec_date = txt;
                                break;
                            }
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

            // Strategy 2: Legacy RadGrid structure (rgRow/rgAltRow)
            if (results.length === 0) {
                var masterTable = document.querySelector('table.rgMasterTable');
                if (masterTable) {
                    var rows = masterTable.querySelectorAll('tbody tr.rgRow, tbody tr.rgAltRow');
                    for (var i = 0; i < rows.length; i++) {
                        var cells = rows[i].querySelectorAll('td');
                        if (cells.length >= 7) {
                            var docNum = cells[0] ? cells[0].innerText.trim() : '';
                            if (docNum && isDocNumber(docNum) && !seenDocNums[docNum]) {
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
            }

            // Strategy 3: Fallback - find any table containing doc numbers
            if (results.length === 0) {
                var allTables = document.querySelectorAll('table');
                for (var t = 0; t < allTables.length; t++) {
                    var table = allTables[t];
                    var rows = table.querySelectorAll('tr');
                    for (var i = 0; i < rows.length; i++) {
                        var cells = rows[i].querySelectorAll('td');
                        if (cells.length >= 5) {
                            var docNum = cells[0] ? cells[0].innerText.trim() : '';
                            if (docNum && isDocNumber(docNum) && !seenDocNums[docNum]) {
                                seenDocNums[docNum] = true;
                                results.push({
                                    document_number: docNum,
                                    grantors: cells.length > 1 ? cells[1].innerText.trim() : '',
                                    grantees: cells.length > 2 ? cells[2].innerText.trim() : '',
                                    grantor_grantees: '',
                                    document_type: cells.length > 3 ? cells[3].innerText.trim() : '',
                                    recording_date: cells.length > 4 ? cells[4].innerText.trim() : '',
                                    pages: cells.length > 5 ? cells[5].innerText.trim() : ''
                                });
                            }
                        }
                    }
                    if (results.length > 0) break;
                }
            }

            return {
                results: results,
                strategyUsed: rows.length > 0 ? 'searchResultRow' :
                              (document.querySelector('table.rgMasterTable') ? 'rgMasterTable' : 'fallback'),
                totalResults: results.length
            };
            """

            js_data = self.driver.execute_script(extract_script, self.doc_number_pattern)

            if js_data:
                results_list = js_data.get('results', [])
                strategy = js_data.get('strategyUsed', 'unknown')

                if results_list:
                    print(f"  Extracted {len(results_list)} document(s) via {strategy} strategy")
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

        except Exception as e:
            print(f"  Error extracting results: {e}")
            import traceback
            traceback.print_exc()

        return documents

    def return_to_search(self):
        """Navigate back to search form for another search."""
        try:
            back_link = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.selectors["back_to_search"]))
            )
            back_link.click()
            time.sleep(2)
            print("  Returned to search form")
        except TimeoutException:
            print("  Back link not found, reloading page")
            self.navigate_to_search()
