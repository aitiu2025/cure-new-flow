"""
AcclaimWeb Platform Adapter for California County Recorders.

Supports counties using the AcclaimWeb platform (Acclaim Systems Inc.):
- CA: San Diego (arcc-acclaim.sdcounty.ca.gov)
- FL coverage roadmap (same platform, future work): Broward, Brevard, Volusia,
  Lee, Pinellas, St. Lucie, etc.

AcclaimWeb is ASP.NET MVC/Razor with a Kendo UI grid for results. Unlike
RecorderWorks (which is classic WebForms with __VIEWSTATE), AcclaimWeb posts
the search form via jQuery/AJAX against MVC controller actions and renders
results into a Kendo grid (`tr.k-master-row`).

Reference probe: docs/acclaimweb_sandiego_probe.md
"""

import os
import re
import time
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


class AcclaimWebRecorderSearch(BaseRecorderSearch):
    """
    Selenium automation adapter for the AcclaimWeb platform.

    Search strategy:
    - Accept the disclaimer landing (one click).
    - Navigate to /AcclaimWeb/search/SearchTypeName.
    - Submit LastName/FirstName + party-type + date range form.
    - Parse the Kendo grid results into DocumentRecord rows.

    Image download is intentionally left as a TODO: San Diego ARCC paywalls
    unredacted PDFs, so image fetch typically falls back to TitlePro247.
    """

    # Default selectors — mostly XPath since AcclaimWeb selectors are MVC/Razor
    # (snake-cased ids would NOT match; AcclaimWeb uses PascalCase model-bound names).
    DEFAULT_SELECTORS = {
        # Disclaimer page
        "disclaimer_checkbox": "//input[@type='checkbox' and (contains(@id,'Disclaimer') or contains(@name,'Disclaimer') or contains(@id,'Agree'))]",
        "disclaimer_accept": (
            "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'i have read') "
            "or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'i agree') "
            "or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'accept')] "
            "| //button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'accept') "
            "or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'agree') "
            "or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'continue')] "
            "| //input[@type='submit' and (contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') "
            "or contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'agree'))]"
        ),

        # Navigation — Name search link from home/menu
        "name_search_link": "//a[contains(@href,'SearchTypeName') or contains(text(),'Name Search') or contains(text(),'Search by Name')]",

        # Search form (Razor MVC PascalCase field names)
        "last_name_field": "//input[@id='LastName' or @name='LastName']",
        "first_name_field": "//input[@id='FirstName' or @name='FirstName']",
        # Combined fallback (some Acclaim deployments use a single "Name" box)
        "name_field": "//input[@id='Name' or @name='Name']",
        "party_type_dropdown": "//select[@id='PartyType' or @name='PartyType']",
        "start_date_field": "//input[@id='DateFiledFrom' or @name='DateFiledFrom' or contains(@id,'FromDate') or contains(@id,'StartDate')]",
        "end_date_field": "//input[@id='DateFiledTo' or @name='DateFiledTo' or contains(@id,'ToDate') or contains(@id,'EndDate')]",
        "search_button": (
            "//button[@id='btnSearch' or contains(@class,'btnSearch') or contains(text(),'Search')] "
            "| //input[@type='submit' and (contains(@value,'Search') or contains(@id,'Search'))]"
        ),

        # Results grid. Broward renders a TELERIK grid (tr.t-alt / tr.t-row),
        # NOT Kendo (tr.k-master-row / tr.k-alt) — the original Kendo-only
        # selectors made the perform_search WebDriverWait predicate (and the
        # no-results row-count check) time out waiting for k-* rows that never
        # appear on Broward. Broaden to cover BOTH platforms, matching what
        # extract_results() already unions.
        "results_grid": "//div[@id='SearchResultsGrid' or contains(@class,'k-grid') or contains(@class,'t-grid') or contains(@class,'t-widget')]",
        "result_rows": "//table//tr[contains(@class,'k-master-row') or contains(@class,'k-alt') or contains(@class,'t-alt') or contains(@class,'t-row') or contains(@class,'t-state-default')]",
        "no_results": "//*[contains(text(),'No records') or contains(text(),'No results') or contains(text(),'0 records')]",
        "back_to_search": "//a[contains(text(),'New Search') or contains(text(),'Back')]",
    }

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: str = None,
    ):
        """
        Initialize AcclaimWeb adapter with county configuration.

        Args:
            config: County configuration dictionary from JSON.
            start_date: Search start date (MM/DD/YYYY).
            end_date: Search end date (MM/DD/YYYY), defaults to today.
        """
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        # Extract config values
        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "")
        self._search_url = config.get("search_url", self._base_url)
        self._disclaimer_url = config.get("disclaimer_url", self._base_url)

        # Merge selectors (config overrides defaults)
        self.selectors = {**self.DEFAULT_SELECTORS}
        if "selectors" in config:
            self.selectors.update(config["selectors"])

        # Party-type mapping. AcclaimWeb typically uses "Grantor", "Grantee",
        # "Both" (= Grantor/Grantee).
        self.party_type_map = config.get("party_type_map", {
            "Grantor/Grantee": "Both",
            "All": "Both",
            "Grantor": "Grantor",
            "Grantee": "Grantee",
        })

        # Name-format mode: "split" => use LastName + FirstName inputs (default);
        # "combined" => use single Name field with "Last First" string.
        self.name_format = config.get("name_format", "split")

        # CAPTCHA — San Diego AcclaimWeb has none per the CA master sheet.
        self.captcha_required = bool(config.get("captcha_required", False))

        # Doc-number patterns
        self.doc_number_patterns = config.get(
            "doc_number_patterns",
            [config.get("doc_number_pattern", r"^\d{4}-\d{6,12}$")],
        )
        self.doc_number_pattern = self._build_combined_pattern()

        # Internal flags
        self._disclaimer_accepted = False

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _retry_on_stale(action, retries: int = 3, settle: float = 0.5):
        """Run ``action`` re-trying on StaleElementReferenceException.

        Kendo UI (which AcclaimWeb is built on) re-renders DOM nodes between
        user interactions (typeahead, grid pagination, validation). Any cached
        WebElement reference can go stale between fetch and interaction, so
        callers that absolutely must hold a reference briefly should wrap the
        interaction in this helper. The preferred pattern is still to re-find
        the element by selector immediately before each interaction.
        """
        last_exc = None
        for attempt in range(retries):
            try:
                return action()
            except StaleElementReferenceException as exc:
                last_exc = exc
                if attempt == retries - 1:
                    raise
                time.sleep(settle)
        # Should be unreachable, but keep mypy/pyflakes happy.
        if last_exc is not None:
            raise last_exc

    def _find_clickable(self, xpath: str, timeout: int = 10):
        """Locate-and-return a clickable element fresh from the DOM."""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )

    def _find_present(self, xpath: str, timeout: int = 10):
        """Locate-and-return a DOM-present element fresh from the DOM."""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )

    def _safe_click(self, xpath: str, timeout: int = 10):
        """Click the element found by ``xpath`` with stale-element retries.

        Re-locates the element on every attempt so a re-render between locate
        and click won't poison the reference. Falls back to JS click if the
        native click is intercepted (Akamai overlay etc.).
        """
        def _do():
            el = self._find_clickable(xpath, timeout)
            try:
                el.click()
            except StaleElementReferenceException:
                raise
            except Exception:
                # Re-find then JS-click (the prior element may have detached).
                el2 = self._find_clickable(xpath, timeout)
                self.driver.execute_script("arguments[0].click();", el2)
            return True

        return self._retry_on_stale(_do, retries=3, settle=0.5)

    def _safe_send_keys(self, xpath: str, value: str, timeout: int = 10):
        """Clear + send_keys with stale-element retries (re-finds each attempt)."""
        def _do():
            el = self._find_present(xpath, timeout)
            el.clear()
            el.send_keys(value)
            return True

        return self._retry_on_stale(_do, retries=3, settle=0.5)

    def _build_combined_pattern(self) -> str:
        if len(self.doc_number_patterns) == 1:
            return self.doc_number_patterns[0]
        parts = [f"({p.strip('^$')})" for p in self.doc_number_patterns]
        return f"^({'|'.join(parts)})$"

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------ driver

    def setup_driver(self):
        """Initialize Chrome WebDriver.

        AcclaimWeb portals vary by hosting:
          - San Diego CA → ASP.NET/Kendo only, no edge protection
          - Broward FL  → Cloudflare-fronted (blocks naive Selenium)
          - Brevard FL  → Akamai (same as SD)

        Try `undetected-chromedriver` first (patches Chrome to hide automation
        flags + TLS/JA3 differences). Falls back to vanilla Selenium with
        stealth flags if UC isn't installed or fails to init.
        """
        # First attempt: undetected-chromedriver (handles Cloudflare on Broward etc.)
        try:
            import undetected_chromedriver as uc
            uc_options = uc.ChromeOptions()
            uc_options.add_argument("--window-size=1920,1080")
            uc_options.add_argument("--disable-blink-features=AutomationControlled")
            # Persistent profile builds reCAPTCHA / Cloudflare trust over sessions
            profile_dir = os.path.expanduser("~/.titlepro/chrome_profile_acclaim")
            os.makedirs(profile_dir, exist_ok=True)
            uc_options.add_argument(f"--user-data-dir={profile_dir}")
            # version_main=148 matches Chrome 148.0.x; use_subprocess=True is UC default & most stable on macOS
            self.driver = uc.Chrome(options=uc_options, version_main=148, use_subprocess=True)
            self.driver.implicitly_wait(5)
            self.wait = WebDriverWait(self.driver, 20)
            print(f"Browser initialized for {self.county_name} County (AcclaimWeb via undetected-chromedriver)")
            return
        except Exception as uc_exc:
            print(f"undetected-chromedriver init failed: {uc_exc}; falling back to vanilla Chrome")

        # Fallback: vanilla Selenium Chrome with basic stealth flags
        options = Options()
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
                if not driver_path.endswith("chromedriver"):
                    driver_dir = os.path.dirname(driver_path)
                    driver_path = os.path.join(driver_dir, "chromedriver")
                service = Service(driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)
        except Exception as exc:
            print(f"WebDriver manager failed: {exc}; falling back to default Chrome driver")
            self.driver = webdriver.Chrome(options=options)

        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 20)
        print(f"Browser initialized for {self.county_name} County (AcclaimWeb, vanilla Chrome)")

    # ---------------------------------------------------------------- disclaimer

    def acknowledge_disclaimer(self) -> bool:
        """Click the disclaimer Accept/Agree button if present.

        AcclaimWeb deployments vary: some show a one-click Accept link, others
        require checking a precondition checkbox first. We try both.
        """
        if self._disclaimer_accepted:
            return True

        # Optional checkbox precondition — re-find inside retry to survive
        # any framework re-render between locate and click.
        def _check_box():
            try:
                cb = self.driver.find_element(By.XPATH, self.selectors["disclaimer_checkbox"])
            except NoSuchElementException:
                return False
            if cb and not cb.is_selected():
                self.driver.execute_script("arguments[0].click();", cb)
                time.sleep(0.5)
                print("  Checked disclaimer precondition checkbox")
            return True

        try:
            self._retry_on_stale(_check_box, retries=3, settle=0.5)
        except StaleElementReferenceException:
            # Checkbox is non-critical; carry on.
            pass

        # Accept link/button — _safe_click re-locates on every attempt.
        try:
            self._safe_click(self.selectors["disclaimer_accept"], timeout=10)
            time.sleep(2)
            print("  Accepted disclaimer")
            self._disclaimer_accepted = True
            return True
        except TimeoutException:
            # Disclaimer may already be accepted (cookie) or absent on direct deeplinks.
            print("  No disclaimer found (may already be accepted)")
            self._disclaimer_accepted = True
            return True

    # ------------------------------------------------------------------ navigate

    def navigate_to_search(self):
        """Open the portal, accept disclaimer, then load the name-search page."""
        url = self._search_url or self._base_url
        print(f"Navigating to {url}")
        self.driver.get(url)
        time.sleep(2)

        self.acknowledge_disclaimer()

        # If we landed somewhere other than the name-search page, click the
        # "Name Search" link or push the explicit search URL. We probe with a
        # cheap find_elements call (no waiting) and then use _safe_click so
        # the actual click re-finds the element to dodge Kendo/Akamai
        # re-renders.
        link_found = bool(
            self.driver.find_elements(By.XPATH, self.selectors["name_search_link"])
        )
        if link_found:
            try:
                self._safe_click(self.selectors["name_search_link"], timeout=10)
                time.sleep(2)
                print("  Clicked Name Search link")
            except (TimeoutException, StaleElementReferenceException) as exc:
                print(f"  Name Search link click failed ({exc}); falling back to deeplink")
                link_found = False

        if not link_found and "SearchTypeName" not in (self.driver.current_url or ""):
            deeplink = self._search_url.rstrip("/")
            # Append the canonical AcclaimWeb route if base URL was given.
            if "/search/" not in deeplink.lower():
                deeplink = deeplink + "/search/SearchTypeName"
            print(f"  Direct-navigating to {deeplink}")
            self.driver.get(deeplink)
            time.sleep(2)

    # --------------------------------------------------------------- form fields

    def _set_party_type(self, party_type: str):
        # Wrap the entire fetch+Select+select_by_visible_text flow in the
        # stale-retry helper. Kendo dropdowns re-render their <option> nodes
        # whenever an adjacent typeahead fires, which can stale our Select.
        def _do():
            dropdown = self._find_present(self.selectors["party_type_dropdown"], timeout=20)
            select = Select(dropdown)
            available = [opt.text.strip() for opt in select.options]
            value = self.party_type_map.get(party_type, party_type)
            if value not in available:
                # Fallback: prefer Both > All > first option
                for candidate in ("Both", "All"):
                    if candidate in available:
                        value = candidate
                        break
                else:
                    value = available[0] if available else value
                print(f"  Note: party_type '{party_type}' not available; using '{value}'")
            select.select_by_visible_text(value)
            time.sleep(0.3)
            print(f"  Set party type: {value}")
            return True

        try:
            self._retry_on_stale(_do, retries=3, settle=0.5)
        except StaleElementReferenceException as exc:
            print(f"  Warning: party type dropdown kept going stale ({exc})")
        except Exception as exc:
            print(f"  Warning: could not set party type ({exc})")

    def _enter_name(self, name: str):
        """Enter the search name.

        - "split" mode (default for AcclaimWeb): input is "Last First", split
          into LastName + FirstName inputs.
        - "combined" mode: a single Name input gets the full string.
        """
        parts = name.strip().split()
        last = parts[0] if parts else name
        first = " ".join(parts[1:]) if len(parts) > 1 else ""

        if self.name_format == "combined":
            try:
                # _safe_send_keys re-finds the element on each retry, dodging
                # Kendo typeahead re-renders that frequently stale the input.
                self._safe_send_keys(self.selectors["name_field"], name, timeout=20)
                print(f"  Entered combined name: {name}")
                return
            except TimeoutException:
                print("  Combined name field not found; falling back to split mode")
            except StaleElementReferenceException:
                print("  Combined name field kept going stale; falling back to split mode")

        # Split mode — last name first (typeahead may re-render once Kendo
        # binds suggestions, so send_keys flow is wrapped in stale-retry).
        try:
            self._safe_send_keys(self.selectors["last_name_field"], last, timeout=20)
            print(f"  Entered LastName: {last}")
        except TimeoutException:
            print("  Warning: LastName field not found")
        except StaleElementReferenceException:
            print("  Warning: LastName field kept going stale")

        if first:
            try:
                self._safe_send_keys(self.selectors["first_name_field"], first, timeout=5)
                print(f"  Entered FirstName: {first}")
            except (NoSuchElementException, TimeoutException):
                print("  Warning: FirstName field not found (LastName-only search)")
            except StaleElementReferenceException:
                print("  Warning: FirstName field kept going stale")

    def _set_dates(self):
        """Set DateFiledFrom / DateFiledTo via JS (Kendo date pickers swallow keystrokes).

        Wrap the fetch+JS-set sequence in stale-retry: a Kendo datepicker can
        re-create its bound input when the user typeahead above it triggers a
        validation cycle, which staled our prior reference in live testing.
        """
        for sel_key, value, label in (
            ("start_date_field", self.start_date, "from"),
            ("end_date_field", self.end_date, "to"),
        ):
            def _do(sel_key=sel_key, value=value, label=label):
                try:
                    fld = self.driver.find_element(By.XPATH, self.selectors[sel_key])
                except NoSuchElementException:
                    print(f"  Warning: {label} date field not found")
                    return False
                # JS-set bypasses Kendo's onfocus validation
                self.driver.execute_script("arguments[0].value = arguments[1];", fld, value)
                # Dispatch change so Kendo's MVVM picks it up
                self.driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
                    fld,
                )
                print(f"  Set date {label}: {value}")
                return True

            try:
                self._retry_on_stale(_do, retries=3, settle=0.4)
            except StaleElementReferenceException as exc:
                print(f"  Warning: {label} date field kept going stale ({exc})")
            except Exception as exc:
                print(f"  Warning: could not set {label} date ({exc})")

    def _click_search(self):
        # _safe_click re-finds the button on every attempt — important because
        # form validation on blur (firing as we tab out of date/name fields)
        # can re-render Kendo's submit button just before we click it.
        self._safe_click(self.selectors["search_button"], timeout=20)
        print("  Clicked search button")
        # Kendo grid populates async; wait for rows or no-results message
        time.sleep(3)

    # --------------------------------------------------------------- search flow

    def perform_search(self, name: str, party_type: str = "Grantor/Grantee") -> List[DocumentRecord]:
        print(f"\n  Performing search:")
        print(f"    Name: {name}")
        print(f"    Party Type: {party_type}")
        print(f"    County: {self.county_name}")

        self._enter_name(name)
        self._set_party_type(party_type)
        self._set_dates()
        self._click_search()

        # Wait for the result grid to render at least one row OR a
        # no-results banner. The original predicate was correct — the bug
        # was that runs 2-6 reused stale prior-search rows because
        # `return_to_search` did NOT actually reload the form. With
        # `return_to_search` now forcing URL navigation, the form is fresh
        # on every entry, so the stale-row hazard is gone.
        try:
            WebDriverWait(self.driver, 20).until(
                lambda d: (
                    d.find_elements(By.XPATH, self.selectors["result_rows"])
                    or d.find_elements(By.XPATH, self.selectors["no_results"])
                )
            )
        except TimeoutException:
            print("  Warning: results grid did not populate within 20s")

        # Small settle so any post-dataBound re-render finishes before we
        # read the DOM in extract_results (JS-only read, but be defensive).
        time.sleep(2.0)

        # No-results check — XPath-based to match `selectors["no_results"]`
        # exactly, plus a Telerik-specific tr.t-no-data check. The previous
        # over-broad `.t-no-data` CSS check was matching transient empty
        # markers DURING the grid re-bind and reporting zero rows even
        # when real rows were about to render.
        if self.driver.find_elements(By.XPATH, self.selectors["no_results"]):
            # Confirm — sometimes the no-results banner sits BESIDE a populated grid.
            row_count = len(self.driver.find_elements(By.XPATH, self.selectors["result_rows"]))
            if row_count == 0:
                print("  No records found")
                return []
            print(f"  no_results banner present but grid has {row_count} rows — proceeding to extract")

        return self.extract_results()

    def extract_results(self) -> List[DocumentRecord]:
        """Extract document records from the Kendo grid.

        AcclaimWeb's Kendo grid renders one row per document. Column order
        varies by tenant config, so we extract via JS by detecting which
        column holds a doc-number-shaped string, then map neighbors.
        """
        documents: List[DocumentRecord] = []

        extract_script = r"""
        var docPatternStr = arguments[0];
        var docPattern = new RegExp(docPatternStr);

        // Flexible fallback patterns (cover BOOK-PAGE legacy + standard formats)
        var flexPatterns = [
            /^\d{4}-\d{6,12}$/,  // San Diego: 2024-1234567890
            /^\d{4}-\d{5,}$/,    // shorter year-number
            /^20\d{10,}$/,       // RecorderWorks-style 13-14 digit
            /^[A-Z]{1,3}\d{4,}-\d+$/  // some legacy book/page formats
        ];

        function isDocNumber(text) {
            if (!text) return false;
            text = text.trim();
            if (docPattern.test(text)) return true;
            for (var i = 0; i < flexPatterns.length; i++) {
                if (flexPatterns[i].test(text)) return true;
            }
            return false;
        }

        function cellText(c) { return c ? (c.innerText || c.textContent || '').trim() : ''; }

        var results = [];
        var seen = {};

        // Strategy 1: result-grid rows. Cover both Kendo (CA San Diego) and
        // Telerik MVC (Broward FL) row classes — Broward emits tr.t-alt
        // without a leading `.t-row` parent class. Hardcoding only Kendo
        // selectors here was the [N, 0, 0, 0, 0, 0] state-contamination
        // bug (Agent B's investigation, 2026-05-22).
        var rows = document.querySelectorAll('tr.t-alt, tr.t-row, tr.k-master-row, tr.k-alt, tr.t-state-default');
        for (var i = 0; i < rows.length; i++) {
            var cells = rows[i].querySelectorAll('td');
            if (cells.length < 3) continue;

            // Identify doc-number cell
            var docNum = null, docIdx = -1;
            for (var c = 0; c < cells.length; c++) {
                var txt = cellText(cells[c]);
                // Sometimes the doc number is inside an <a> within the cell
                if (!txt) {
                    var a = cells[c].querySelector('a');
                    if (a) txt = (a.innerText || a.textContent || '').trim();
                }
                if (isDocNumber(txt)) { docNum = txt; docIdx = c; break; }
            }
            if (!docNum || seen[docNum]) continue;
            seen[docNum] = true;

            // Heuristic column mapping: AcclaimWeb tenants vary, so we scan.
            var rec_date = '', doc_type = '', grantors = '', grantees = '', pages = '';
            for (var c = 0; c < cells.length; c++) {
                if (c === docIdx) continue;
                var txt = cellText(cells[c]);
                if (!txt) continue;
                if (!rec_date && /^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(txt)) {
                    rec_date = txt;
                } else if (!pages && /^\d{1,3}$/.test(txt) && parseInt(txt, 10) <= 500) {
                    pages = txt;
                } else if (!doc_type && txt.length > 2 && txt.length < 60 && /[A-Za-z]/.test(txt) && !/[,;]/.test(txt)) {
                    // Short label cell — likely doc type
                    doc_type = txt;
                } else if (txt.length >= 2) {
                    // Longer text → likely names. First long string -> grantors, second -> grantees.
                    if (!grantors) grantors = txt;
                    else if (!grantees) grantees = txt;
                }
            }

            results.push({
                document_number: docNum,
                grantors: grantors,
                grantees: grantees,
                grantor_grantees: (grantors && grantees) ? (grantors + '; ' + grantees) : (grantors || grantees),
                document_type: doc_type,
                recording_date: rec_date,
                pages: pages
            });
        }

        // Strategy 2: ALWAYS scan all tables and merge by doc-number. Telerik
        // grids on Broward show only page 1 of result rows in the visible
        // `tr.t-alt` set — additional rows may live in adjacent tables,
        // hidden pagination pages, or fallback containers. Running this as
        // a SUPPLEMENT (not an alternative to Strategy 1) gives us full
        // coverage. This is the 0522 fix for missing Tony golden docs.
        var strategy1_count = results.length;
        var tables = document.querySelectorAll('table');
        for (var t = 0; t < tables.length; t++) {
            var trs = tables[t].querySelectorAll('tbody tr');
            for (var r = 0; r < trs.length; r++) {
                var cells = trs[r].querySelectorAll('td');
                if (cells.length < 3) continue;
                var docNum = null;
                for (var c = 0; c < cells.length; c++) {
                    var txt = cellText(cells[c]);
                    if (!txt) {
                        var a = cells[c].querySelector('a');
                        if (a) txt = (a.innerText || a.textContent || '').trim();
                    }
                    if (isDocNumber(txt)) { docNum = txt; break; }
                }
                if (docNum && !seen[docNum]) {
                    seen[docNum] = true;
                    // Apply the same heuristic column scan we use in Strategy 1
                    // so the merged rows have clean metadata.
                    var rec_date = '', doc_type = '', grantors = '', grantees = '', pages = '';
                    for (var c = 0; c < cells.length; c++) {
                        var txt = cellText(cells[c]);
                        if (!txt) continue;
                        if (txt === docNum) continue;
                        if (!rec_date && /^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(txt)) {
                            rec_date = txt;
                        } else if (!pages && /^\d{1,3}$/.test(txt) && parseInt(txt, 10) <= 500) {
                            pages = txt;
                        } else if (!doc_type && txt.length > 2 && txt.length < 60 && /[A-Za-z]/.test(txt) && !/[,;]/.test(txt)) {
                            doc_type = txt;
                        } else if (txt.length >= 2) {
                            if (!grantors) grantors = txt;
                            else if (!grantees) grantees = txt;
                        }
                    }
                    results.push({
                        document_number: docNum,
                        grantors: grantors,
                        grantees: grantees,
                        grantor_grantees: (grantors && grantees) ? (grantors + '; ' + grantees) : (grantors || grantees),
                        document_type: doc_type,
                        recording_date: rec_date,
                        pages: pages
                    });
                }
            }
        }

        return {
            results: results,
            strategy: 'union',
            strategy1_count: strategy1_count,
            strategy2_added: results.length - strategy1_count
        };
        """

        try:
            time.sleep(2)
            js_data = self.driver.execute_script(extract_script, self.doc_number_pattern)
            if not js_data:
                return documents

            rows = js_data.get("results", [])
            strategy = js_data.get("strategy", "?")
            s1 = js_data.get("strategy1_count", "?")
            s2 = js_data.get("strategy2_added", "?")
            print(f"  Extracted {len(rows)} document(s) via {strategy} strategy (s1={s1}, s2_added={s2})")
            for r in rows:
                documents.append(
                    DocumentRecord(
                        document_number=r.get("document_number", ""),
                        grantors=r.get("grantors", ""),
                        grantees=r.get("grantees", ""),
                        grantor_grantees=r.get("grantor_grantees", ""),
                        document_type=r.get("document_type", ""),
                        recording_date=r.get("recording_date", ""),
                        pages=r.get("pages", ""),
                    )
                )

            # TODO: handle Kendo pagination (next-page button) and multi-page result sets.

        except Exception as exc:
            print(f"  Error extracting results: {exc}")
            import traceback
            traceback.print_exc()

        return documents

    # ------------------------------------------------------------- return / dl

    def return_to_search(self):
        """Reset the search form to a clean state.

        Broward's post-search DOM has no `New Search` / `Back` link, so the
        click-and-fallback pattern would silently re-bind to the current
        results page (stale cookies, stale anti-forgery token, stale form
        fields). That's part of the state-contamination Agent B traced.

        Force a hard URL navigation back to the search page and wait until
        the name input is empty before returning. Per-call independence is
        non-negotiable; relying on a "Back" link is not.
        """
        # Try the click path first for tenants that DO have a Back link.
        try:
            self._safe_click(self.selectors["back_to_search"], timeout=4)
            time.sleep(1)
        except (TimeoutException, StaleElementReferenceException):
            pass  # Fall through to URL navigation.

        # URL-navigate to guarantee a fresh form, then wait until the name
        # field has been re-rendered AND is empty.
        try:
            self.driver.get(self._search_url)
        except Exception as exc:
            print(f"  return_to_search: navigate to {self._search_url} failed: {exc}")

        # Wait up to 8s for the name input to render empty.
        def _form_is_clean(d):
            try:
                val = d.execute_script(
                    """
                    var f = document.getElementById('SearchOnName')
                         || document.getElementById('LastName')
                         || document.getElementById('Name');
                    return f ? (f.value || '') : null;
                    """
                )
            except Exception:
                return False
            return val == "" or val is None or val == "null"

        try:
            WebDriverWait(self.driver, 8).until(_form_is_clean)
        except TimeoutException:
            print("  Warning: search form did not return to a clean state within 8s")
        time.sleep(0.8)

    def download_documents(self, case_dir: str, documents: List[DocumentRecord]):
        """Download document PDFs to the case directory.

        TODO: San Diego ARCC paywalls unredacted PDFs behind per-page fees. The
        free public viewer renders images server-side and does not expose a
        direct PDF download URL. Realistically, image fetch should fall back
        to TitlePro247 (shared image-download portal — see
        `docs/County_URL_Mapping_CA_OH.md`).

        This stub writes documents_found.json metadata only. Wire the actual
        per-document image fetch when the paywall path is decided by the
        leader.
        """
        import json
        from pathlib import Path

        out_dir = Path(case_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = out_dir / "documents_found.json"
        with manifest.open("w") as f:
            json.dump(
                {
                    "county": self.county_name,
                    "platform": "acclaimweb",
                    "search_timestamp": None,
                    "documents": [d.to_dict() for d in documents],
                    "note": "AcclaimWeb image download deferred — paywall path TBD. Use TitlePro247 fallback for PDFs.",
                },
                f,
                indent=2,
            )
        print(f"  Wrote manifest {manifest} ({len(documents)} doc(s)); image PDFs not downloaded (TODO).")
