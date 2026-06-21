"""
Tyler Technologies Platform Adapter for California County Recorders.

Supports counties using Tyler Technologies (tylerhost.net) platform:
- No CAPTCHA: Calaveras, Monterey, San Luis Obispo, Santa Cruz, Trinity
- With CAPTCHA: Del Norte, Fresno, Humboldt, Inyo, Kings, Lake, Madera,
                San Benito, San Joaquin, Sierra, Tulare, Tuolumne, Yolo

Tyler Technologies uses a modern web interface with disclaimer acceptance.
"""

import time
import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

from titlepro.automation.checkpoints import CaptchaCheckpointRequired, checkpoint_sessions

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


class TylerAdapter(BaseRecorderSearch):
    """
    Selenium automation adapter for Tyler Technologies platform.

    This adapter works with counties using Tyler Technologies (tylerhost.net),
    which features:
    - Disclaimer/agreement page on first visit
    - Modern JavaScript-based interface
    - Optional CAPTCHA on some counties
    - Standard table-based results

    Search Strategy:
    - Name format: "Last First" (e.g., "Smith John")
    - Requires accepting disclaimer before searching
    - May require CAPTCHA solving
    """

    # Default selectors for Tyler Technologies platform
    DEFAULT_SELECTORS = {
        # Disclaimer page
        "disclaimer_checkbox": "//input[@type='checkbox']",
        "disclaimer_accept": "//button[contains(text(), 'Accept') or contains(text(), 'agree') or contains(text(), 'Continue')]",

        # Navigation
        "name_search_link": "//a[contains(@href, 'NameSearch') or contains(text(), 'Name Search')]",
        "search_menu": "//a[contains(text(), 'Search')]",

        # Search form elements
        "party_type_dropdown": "//select[contains(@id, 'PartyType') or contains(@name, 'PartyType')]",
        "last_name_field": "//input[contains(@id, 'LastName') or contains(@name, 'LastName')]",
        "first_name_field": "//input[contains(@id, 'FirstName') or contains(@name, 'FirstName')]",
        "name_field": "//input[contains(@id, 'Name') and not(contains(@id, 'First')) and not(contains(@id, 'Last'))]",
        "start_date_field": "//input[contains(@id, 'StartDate') or contains(@id, 'FromDate') or contains(@name, 'startDate') or contains(@id, 'RecordingDateStart') or contains(@id, 'recordingDateStart')]",
        "end_date_field": "//input[contains(@id, 'EndDate') or contains(@id, 'ToDate') or contains(@name, 'endDate') or contains(@id, 'RecordingDateEnd') or contains(@id, 'recordingDateEnd')]",
        "search_button": "//button[contains(text(), 'Search')] | //input[@type='submit' and contains(@value, 'Search')]",

        # CAPTCHA elements
        "recaptcha_frame": "//iframe[contains(@src, 'recaptcha')]",
        "recaptcha_checkbox": "//div[@class='recaptcha-checkbox-border']",
        "recaptcha_response": "//textarea[@id='g-recaptcha-response']",

        # Results page
        "results_table": "//table[contains(@class, 'table') or contains(@class, 'results') or contains(@class, 'grid')]",
        "result_rows": "//table//tbody//tr",
        "no_results": "//*[contains(text(), 'No records found') or contains(text(), '0 records') or contains(text(), 'No results')]",
        "back_to_search": "//a[contains(text(), 'Back') or contains(text(), 'New Search')]",
        "result_count": "//*[contains(text(), 'record') or contains(text(), 'result')]"
    }

    def __init__(self, config: Dict, start_date: str = "01/01/2010", end_date: str = None):
        """
        Initialize Tyler adapter with county configuration.

        Args:
            config: County configuration dictionary from JSON
            start_date: Search start date in MM/DD/YYYY format
            end_date: Search end date in MM/DD/YYYY format (defaults to today)
        """
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        # Extract config values
        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "")
        self._search_url = config.get("search_url", "")
        self._disclaimer_url = config.get("disclaimer_url", self._base_url)

        # CAPTCHA configuration
        self.captcha_required = config.get("captcha_required", False)
        self.captcha_type = config.get("captcha_type", "recaptcha_v2")
        self.allow_automated_captcha_solver = bool(config.get("allow_automated_captcha_solver", False))
        self.requires_manual_captcha = bool(config.get("requires_manual_captcha", self.captcha_required))
        self.manual_captcha_timeout_seconds = int(
            config.get("manual_captcha_timeout_seconds")
            or os.environ.get("MANUAL_CAPTCHA_TIMEOUT", "300")
        )
        self.captcha_solver = None

        # Merge selectors (config overrides defaults)
        self.selectors = {**self.DEFAULT_SELECTORS}
        if "selectors" in config:
            self.selectors.update(config["selectors"])

        # Name format configuration
        self.name_format = config.get("name_format", "split")  # "split" or "combined"

        # Party type options
        self.party_type_map = config.get("party_type_map", {
            "Grantor/Grantee": "Both",
            "All": "Both",
            "Grantor": "Grantor",
            "Grantee": "Grantee"
        })

        # Document number pattern
        self.doc_number_pattern = config.get("doc_number_pattern", r"^\d{4}-\d+$|^\d{10,}$")

        # Track if disclaimer was accepted
        self._disclaimer_accepted = False

        # Multi-step navigation configuration
        self._navigation_steps = config.get("navigation_steps", None)

        # Track the actual search page URL (set after navigation completes)
        self._resolved_search_url = None

        # Path for diagnostic dumps when extraction looks suspicious. Set by
        # the pipeline via set_debug_dir(); defaults to /tmp.
        self._debug_dir: Optional[Path] = None

        # Partial match mode (Tyler uses partial matching by default)
        self.partial_match = True

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    def set_captcha_solver(self, solver):
        """
        Set the CAPTCHA solver instance for counties that require it.

        Args:
            solver: CaptchaSolver instance from captcha module
        """
        if self.allow_automated_captcha_solver:
            self.captcha_solver = solver
            return
        print(
            f"Automated CAPTCHA solver ignored for {self.county_name} County. "
            "Recorder workflow uses manual human checkpoints by default."
        )

    def _inject_recaptcha_token(self, token: str) -> bool:
        """Inject a 2Captcha/AntiCaptcha-solved reCAPTCHA v2 token into the page.

        Sets the token in every g-recaptcha-response textarea (innerHTML + value),
        then tries to trigger the reCAPTCHA callback via 4 fallback strategies:
          A. data-callback attribute on .g-recaptcha widget
          B. enterprise reCAPTCHA detection (skip callback paths that crash)
          C. safe walk of ___grecaptcha_cfg.clients[*].callback
          D. enable disabled "I Accept" / "Search" buttons directly

        Returns True if injection ran without error. Caller must still verify
        navigation/state change to confirm the token was accepted.
        """
        if not token:
            return False
        # CRITICAL: callbacks are invoked via setTimeout(0) so they run on a
        # later tick — otherwise a callback that submits the search form
        # synchronously will block this execute_script call until the server
        # responds (often >120s = chromedriver read timeout).
        #
        # ALSO CRITICAL for SBD/Tyler: the search form AJAX-POSTs with
        # `data: {"g-recaptcha-response": grecaptcha.getResponse()}` — so we
        # MUST override grecaptcha.getResponse() to return our token, otherwise
        # the AJAX sends empty and the server returns a fresh CAPTCHA.
        js = """
        var token = arguments[0];
        try {
            // 1. Set token in ALL textareas — synchronous, instant
            var areas = document.getElementsByName('g-recaptcha-response');
            for (var i = 0; i < areas.length; i++) {
                areas[i].innerHTML = token;
                areas[i].value = token;
                areas[i].style.display = 'block';
            }
            // 1b. Override grecaptcha.getResponse() to return our token so any
            // form-submit JS that reads via the grecaptcha API gets the token.
            try {
                if (typeof window.grecaptcha === 'undefined') { window.grecaptcha = {}; }
                window.grecaptcha.getResponse = function(){ return token; };
                if (window.grecaptcha.enterprise) {
                    window.grecaptcha.enterprise.getResponse = function(){ return token; };
                }
            } catch(e) {}
            // Strategy D-FIRST: enable any disabled accept/search buttons NOW
            var btns = document.querySelectorAll(
                "button[id*='Accept'], button[id*='accept'], button[id*='submit'], button[type='submit']"
            );
            for (var b = 0; b < btns.length; b++) {
                btns[b].removeAttribute('disabled');
                btns[b].classList.remove('ui-state-disabled');
                btns[b].classList.remove('ui-disabled');
            }
            // Strategy A: data-callback — fire ASYNC so the form submit doesn't block us
            var widgets = document.querySelectorAll('.g-recaptcha, [data-sitekey]');
            for (var w = 0; w < widgets.length; w++) {
                var cb = widgets[w].getAttribute('data-callback');
                if (cb && typeof window[cb] === 'function') {
                    setTimeout(function(name){ try { window[name](token); } catch(e) {} }, 0, cb);
                    return 'A-async:' + cb;
                }
            }
            // Strategy B: enterprise — skip callbacks entirely
            if (window.grecaptcha && window.grecaptcha.enterprise) {
                return 'B:enterprise-token-only';
            }
            // Strategy C: walk ___grecaptcha_cfg.clients[*].callback — fire ASYNC
            if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                var clients = window.___grecaptcha_cfg.clients;
                var stack = [];
                for (var k in clients) stack.push(clients[k]);
                var seen = 0;
                while (stack.length && seen < 500) {
                    var node = stack.pop();
                    seen++;
                    if (!node || typeof node !== 'object') continue;
                    for (var key in node) {
                        try {
                            if (key === 'callback' && typeof node[key] === 'function') {
                                var fn = node[key];
                                setTimeout(function(f){ try { f(token); } catch(e) {} }, 0, fn);
                                return 'C-async:cb';
                            } else if (node[key] && typeof node[key] === 'object') {
                                stack.push(node[key]);
                            }
                        } catch(e) {}
                    }
                }
            }
            return 'D:token-set+buttons-enabled';
        } catch(e) { return 'ERR:' + e.message; }
        """
        try:
            # Cap execute_script at 30s — should be near-instant; if longer,
            # the page is broken and we fall through to human checkpoint.
            self.driver.set_script_timeout(30)
            result = self.driver.execute_script(js, token)
            print(f"  Token injection: {result}")
            return True
        except Exception as e:
            print(f"  Token injection failed: {e}")
            return False

    def _read_recaptcha_textarea(self) -> str:
        """Read the current value of any g-recaptcha-response textarea (by name).

        Use this as a fallback when grecaptcha.getResponse() returns empty even
        though we wrote the token into the textarea ourselves.
        """
        try:
            return self.driver.execute_script(
                "var ta = document.getElementsByName('g-recaptcha-response');"
                "for (var i = 0; i < ta.length; i++) { if (ta[i].value) return ta[i].value; }"
                "return '';"
            ) or ""
        except Exception:
            return ""

    def _post_solve_advance(self, pre_solve_url: str, settle_ms: int = 1500, nav_timeout_s: int = 20) -> None:
        """After a successful auto-solve, click the right button to advance.

        Two cases:
          (1) On /user/disclaimer  → click 'I Accept' + wait for nav to /search/
          (2) On /search/...       → click the search submit/find button again so
                                     the form posts with the freshly-injected token.

        Best-effort: any failure here just falls through; the next _handle_captcha
        call will either succeed (if the page advanced) or re-raise the human
        checkpoint (if not).
        """
        import time as _time
        _time.sleep(settle_ms / 1000.0)
        try:
            current = self.driver.current_url
        except Exception:
            return
        current_lc = current.lower()

        if "/user/disclaimer" in current_lc:
            # Case 1: disclaimer page — click 'I Accept' + wait for nav
            click_js = """
            var ids = ['submitDisclaimerAccept', 'submitDisclaimer', 'btnAccept', 'AcceptButton'];
            for (var i = 0; i < ids.length; i++) {
                var b = document.getElementById(ids[i]);
                if (b) {
                    try { b.removeAttribute('disabled'); b.classList.remove('ui-state-disabled'); } catch(e){}
                    try { b.click(); return 'clicked:' + ids[i]; } catch(e){}
                }
            }
            var buttons = document.querySelectorAll('button, input[type="submit"]');
            for (var j = 0; j < buttons.length; j++) {
                var t = (buttons[j].textContent || buttons[j].value || '').trim().toLowerCase();
                if (t === 'i accept' || t === 'accept' || t === 'continue') {
                    try { buttons[j].removeAttribute('disabled'); } catch(e){}
                    try { buttons[j].click(); return 'clicked-by-text:' + t; } catch(e){}
                }
            }
            return 'no-button-found';
            """
            try:
                res = self.driver.execute_script(click_js)
                print(f"  Disclaimer accept: {res}")
            except Exception as e:
                print(f"  Disclaimer accept click failed: {e}")
                return

            deadline = _time.time() + nav_timeout_s
            while _time.time() < deadline:
                try:
                    if "/user/disclaimer" not in self.driver.current_url.lower():
                        print(f"  ✓ Advanced past disclaimer to: {self.driver.current_url}")
                        return
                except Exception:
                    pass
                _time.sleep(0.5)
            print(f"  ⚠ Still on disclaimer after {nav_timeout_s}s; current URL: {self.driver.current_url}")
            return

        # Case 2: NOT on disclaimer (likely /search/...) — re-submit the search
        # so the form posts with the freshly-injected reCAPTCHA token.
        click_js = """
        // Try standard Tyler search submit IDs first
        var ids = ['btnSearchEnter', 'searchButton', 'btnSearch', 'btnFind', 'submitSearch'];
        for (var i = 0; i < ids.length; i++) {
            var b = document.getElementById(ids[i]);
            if (b) {
                try { b.removeAttribute('disabled'); b.classList.remove('ui-state-disabled'); } catch(e){}
                try { b.click(); return 'clicked:' + ids[i]; } catch(e){}
            }
        }
        // Fallback: button/link whose text matches Search/Find/Submit
        var els = document.querySelectorAll('button, a[data-role="button"], input[type="submit"]');
        for (var j = 0; j < els.length; j++) {
            var t = (els[j].textContent || els[j].value || '').trim().toLowerCase();
            if (t === 'search' || t === 'find' || t === 'submit') {
                try { els[j].removeAttribute('disabled'); } catch(e){}
                try { els[j].click(); return 'clicked-by-text:' + t; } catch(e){}
            }
        }
        return 'no-search-button-found';
        """
        try:
            res = self.driver.execute_script(click_js)
            print(f"  Re-submit search: {res}")
        except Exception as e:
            print(f"  Re-submit failed: {e}")
            return
        # Settle for nav / page state change
        _time.sleep(2.0)

    def set_debug_dir(self, debug_dir):
        """Configure where diagnostic dumps land when extraction is suspicious."""
        self._debug_dir = Path(debug_dir) if debug_dir else None

    def _dump_search_page_state(self, reason: str, js_data: dict, expected_count: int) -> Optional[Path]:
        """Write the current results-page state to disk for triage.

        Captures: URL, body innerText, head/outerHTML of the active jQuery Mobile
        page (or body), the first ~25 <li>/<tr>/<a> samples, and the JS extractor's
        debug payload. Returns the path written.
        """
        try:
            target_dir = self._debug_dir or Path("/tmp")
            target_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = (self._county_name or "tyler").lower().replace(" ", "_")
            out_path = target_dir / f"_debug_search_page_{slug}_{stamp}.txt"

            url = self.driver.current_url
            try:
                title = self.driver.title
            except Exception:
                title = ""
            body_text = ""
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass

            sample_script = r"""
            var scope = document.querySelector('.ui-page-active') ||
                        document.querySelector('[data-role="page"]:last-of-type') ||
                        document.body;
            var sampleHtml = (scope.outerHTML || '').substring(0, 20000);
            function dump(sel, max) {
                var els = scope.querySelectorAll(sel);
                var out = [];
                for (var i = 0; i < Math.min(els.length, max); i++) {
                    out.push((els[i].outerHTML || '').substring(0, 600));
                }
                return { count: els.length, samples: out };
            }
            return {
                activeScope: scope.tagName + (scope.id ? '#' + scope.id : '') +
                             (scope.className ? '.' + scope.className.split(' ').slice(0,3).join('.') : ''),
                listCount: document.querySelectorAll('ul').length,
                tableCount: document.querySelectorAll('table').length,
                links: dump('a[href]', 25),
                lis: dump('ul li', 25),
                trs: dump('table tr', 15),
                resultLinks: dump('a[href*="document"], a[href*="detail"], a[href*="DOCDETAIL"]', 25),
                scopeHtmlHead: sampleHtml
            };
            """
            try:
                sample = self.driver.execute_script(sample_script) or {}
            except Exception as e:
                sample = {"sample_script_error": str(e)}

            with out_path.open("w", encoding="utf-8") as f:
                f.write(f"# Tyler search-page diagnostic dump\n")
                f.write(f"# reason       : {reason}\n")
                f.write(f"# timestamp    : {stamp}\n")
                f.write(f"# county       : {self._county_name}\n")
                f.write(f"# url          : {url}\n")
                f.write(f"# title        : {title}\n")
                f.write(f"# expectedCount: {expected_count}\n")
                f.write(f"# js_format    : {js_data.get('format')}\n")
                f.write(f"# js_results   : {len(js_data.get('results', []) or [])}\n")
                f.write(f"# active scope : {sample.get('activeScope')}\n")
                f.write(f"# total <ul>   : {sample.get('listCount')}\n")
                f.write(f"# total <table>: {sample.get('tableCount')}\n")
                f.write("\n== js debug payload ==\n")
                f.write(json.dumps(js_data.get("debug", {}), indent=2)[:6000])
                f.write("\n\n== body innerText (first 8000 chars) ==\n")
                f.write(body_text[:8000])
                f.write("\n\n== <a> samples ==\n")
                f.write(f"total: {sample.get('links', {}).get('count')}\n")
                for s in sample.get('links', {}).get('samples', []):
                    f.write(s + "\n---\n")
                f.write("\n== <li> samples ==\n")
                f.write(f"total: {sample.get('lis', {}).get('count')}\n")
                for s in sample.get('lis', {}).get('samples', []):
                    f.write(s + "\n---\n")
                f.write("\n== <tr> samples ==\n")
                f.write(f"total: {sample.get('trs', {}).get('count')}\n")
                for s in sample.get('trs', {}).get('samples', []):
                    f.write(s + "\n---\n")
                f.write("\n== result-link samples (doc/detail/DOCDETAIL hrefs) ==\n")
                f.write(f"total: {sample.get('resultLinks', {}).get('count')}\n")
                for s in sample.get('resultLinks', {}).get('samples', []):
                    f.write(s + "\n---\n")
                f.write("\n== active scope outerHTML (first 20000 chars) ==\n")
                f.write(sample.get("scopeHtmlHead", "") or "")

            print(f"  [debug] dumped page state to {out_path}")
            return out_path
        except Exception as e:
            print(f"  [debug] failed to dump page state: {e}")
            return None

    def setup_driver(self):
        """Initialize Chrome WebDriver with appropriate options."""
        options = Options()

        # Common options for stability
        #options.add_argument("--headless=new")
        #options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")

        # Avoid detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Optional dedicated Chrome user-data-dir. Set TYLER_CHROME_PROFILE to
        # an absolute path (e.g. ~/.titlepro/chrome_profile_orange) so parallel
        # adapter sessions don't collide on the default profile lock and so a
        # paused CAPTCHA checkpoint can be resumed against a stable session.
        profile_dir = os.environ.get("TYLER_CHROME_PROFILE")
        if profile_dir:
            profile_dir = os.path.expanduser(profile_dir)
            os.makedirs(profile_dir, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile_dir}")
            print(f"  Tyler Chrome profile: {profile_dir}")

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

        print(f"Browser initialized for {self.county_name} County (Tyler Technologies)")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Keep the visible browser alive while a human checkpoint is pending."""
        if exc_type and issubclass(exc_type, CaptchaCheckpointRequired):
            print(f"Keeping {self.county_name} browser session open for CAPTCHA resume.")
            return False
        self.close()
        return False

    def _accept_disclaimer(self) -> bool:
        """
        Accept the disclaimer/agreement page if present.

        Returns:
            True if disclaimer was accepted or not required, False on failure
        """
        if self._disclaimer_accepted:
            return True

        try:
            # Check for disclaimer page indicators
            page_text = self.driver.page_source.lower()
            disclaimer_keywords = ['disclaimer', 'agreement', 'terms', 'accept', 'agree']

            if not any(keyword in page_text for keyword in disclaimer_keywords):
                print("  No disclaimer page detected")
                self._disclaimer_accepted = True
                return True

            # SBD/Tyler-style CAPTCHA-gated disclaimer: the accept button is
            # disabled until the reCAPTCHA is solved. If a CAPTCHA is present
            # AND we have a solver attached, run the CAPTCHA flow now —
            # _handle_captcha + _post_solve_advance will click I-Accept and
            # navigate off the disclaimer page automatically.
            try:
                recaptcha_present = bool(
                    self.driver.find_elements(By.XPATH, self.selectors.get("recaptcha_frame", "//iframe[contains(@src,'recaptcha')]"))
                )
            except Exception:
                recaptcha_present = False
            if recaptcha_present and self.captcha_solver is not None:
                print("  CAPTCHA gate detected on disclaimer; invoking auto-solve before accept")
                try:
                    self._handle_captcha()
                except CaptchaCheckpointRequired:
                    # auto-solve failed; fall through to legacy accept logic
                    pass
                # If _post_solve_advance navigated us past disclaimer, we're done
                if "/user/disclaimer" not in (self.driver.current_url or "").lower():
                    print("  ✓ Disclaimer cleared via CAPTCHA auto-solve")
                    self._disclaimer_accepted = True
                    return True

            # Try to find and check any required checkbox
            try:
                checkbox = self.driver.find_element(By.XPATH, self.selectors["disclaimer_checkbox"])
                if not checkbox.is_selected():
                    checkbox.click()
                    time.sleep(0.5)
                    print("  Checked disclaimer checkbox")
            except NoSuchElementException:
                pass  # No checkbox required

            # Click accept/continue button
            accept_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.selectors["disclaimer_accept"]))
            )
            accept_button.click()
            time.sleep(2)
            print("  Accepted disclaimer")
            self._disclaimer_accepted = True
            return True

        except TimeoutException:
            print("  No disclaimer accept button found (may not be required)")
            self._disclaimer_accepted = True
            return True
        except Exception as e:
            print(f"  Error accepting disclaimer: {e}")
            return False

    def _execute_navigation_step(self, step: Dict) -> bool:
        """
        Execute a single navigation step from the navigation_steps config.

        Supports three strategies for click actions:
        1. Selenium XPath (standard approach)
        2. JavaScript DOM search (for dynamically rendered SPA elements)
        3. Fallback URL navigation (direct URL if clicks fail)

        Args:
            step: Step dictionary with keys:
                - action: "accept_disclaimer", "click_link", or "click_button"
                - selector: XPath selector for the element
                - text_match: Text to search for via JavaScript (fallback)
                - fallback_url: URL to navigate to if click fails (fallback)
                - wait_after: Seconds to wait after action (default 2)
                - description: Human-readable step description

        Returns:
            True if step succeeded, False on failure
        """
        action = step.get("action", "")
        selector = step.get("selector", "")
        text_match = step.get("text_match", "")
        fallback_url = step.get("fallback_url", "")
        wait_after = step.get("wait_after", 2)
        description = step.get("description", action)

        try:
            if action == "accept_disclaimer":
                result = self._accept_disclaimer()
                time.sleep(wait_after)
                return result

            elif action in ("click_link", "click_button"):
                # Strategy 1: Standard Selenium XPath
                try:
                    element = self.wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    element.click()
                    time.sleep(wait_after)
                    print(f"  Navigation step: {description}")
                    return True
                except (TimeoutException, NoSuchElementException):
                    print(f"  XPath selector not found, trying JavaScript approach...")

                # Strategy 2: JavaScript DOM search for dynamically rendered elements
                if text_match:
                    js_click = """
                    var searchText = arguments[0].toLowerCase();
                    var allElements = document.querySelectorAll(
                        'a, button, [role="link"], [role="button"], ' +
                        '.list-group-item, .searchLink, [onclick], ' +
                        'li a, div a, span a, h4 a'
                    );
                    for (var i = 0; i < allElements.length; i++) {
                        var el = allElements[i];
                        var text = (el.textContent || el.innerText || '').toLowerCase().trim();
                        if (text.includes(searchText)) {
                            el.scrollIntoView({block: 'center'});
                            el.click();
                            return true;
                        }
                    }
                    return false;
                    """
                    try:
                        clicked = self.driver.execute_script(js_click, text_match)
                        if clicked:
                            time.sleep(wait_after)
                            print(f"  Navigation step (JS click): {description}")
                            return True
                    except Exception as js_err:
                        print(f"  JavaScript click failed: {js_err}")

                # Strategy 3: Fallback URL navigation
                if fallback_url:
                    print(f"  Using fallback URL: {fallback_url}")
                    self.driver.get(fallback_url)
                    time.sleep(wait_after)
                    print(f"  Navigation step (URL fallback): {description}")
                    return True

                print(f"  Warning: All strategies failed for: {description}")
                return False

            else:
                print(f"  Warning: Unknown navigation action '{action}' in step: {description}")
                return True

        except Exception as e:
            # Last resort: try fallback URL
            if fallback_url:
                try:
                    self.driver.get(fallback_url)
                    time.sleep(wait_after)
                    print(f"  Navigation step (URL fallback after error): {description}")
                    return True
                except Exception:
                    pass
            print(f"  Error in navigation step '{description}': {e}")
            return False

    def _handle_captcha(self) -> bool:
        """
        Detect CAPTCHA and pause the workflow if human action is required.

        Resolution order:
            1. If no CAPTCHA in DOM → pass through.
            2. If a token is ALREADY present (user pre-solved) → pass through.
            3. Otherwise → raise a resumable human checkpoint.

        Returns:
            True if CAPTCHA solved or not present.

        Raises:
            CaptchaCheckpointRequired: when the visible browser must pause for
            the user to solve CAPTCHA and resume the workflow.
        """
        if not self.captcha_required:
            return True

        MANUAL_CAPTCHA_TIMEOUT_SECONDS = self.manual_captcha_timeout_seconds

        def _current_token() -> str:
            """Read grecaptcha.getResponse() across all reCAPTCHA widgets."""
            try:
                return self.driver.execute_script(
                    "try {"
                    "  if (typeof grecaptcha === 'undefined') return '';"
                    "  if (typeof grecaptcha.getResponse !== 'function') return '';"
                    "  var t = '';"
                    "  for (var i = 0; i < 4; i++) {"
                    "    try { var v = grecaptcha.getResponse(i); if (v && v.length) { t = v; break; } } catch(e){}"
                    "  }"
                    "  if (!t) { try { t = grecaptcha.getResponse() || ''; } catch(e){} }"
                    "  if (!t) {"
                    "    var ta = document.getElementById('g-recaptcha-response');"
                    "    if (ta && ta.value) t = ta.value;"
                    "  }"
                    "  return t || '';"
                    "} catch(e) { return ''; }"
                ) or ""
            except Exception:
                return ""

        try:
            # Check if CAPTCHA is present
            recaptcha_frame = self.driver.find_elements(By.XPATH, self.selectors["recaptcha_frame"])

            if not recaptcha_frame:
                print("  No CAPTCHA detected on this page")
                return True

            print(f"  CAPTCHA detected (type: {self.captcha_type})")

            # Pre-solved? (user clicked the checkbox before this call ran)
            pre_token = _current_token()
            if pre_token:
                print(f"  CAPTCHA already solved (token length {len(pre_token)})")
                return True

            # 2Captcha/AntiCaptcha auto-solve (if solver was attached by registry).
            # Requires county config: captcha_required=true + allow_automated_captcha_solver=true,
            # plus CAPTCHA_API_KEY env var.
            if self.captcha_solver is not None:
                try:
                    site_key = self.driver.execute_script(
                        """
                        try {
                            // Method 1: data-sitekey HTML attribute
                            var el = document.querySelector('.g-recaptcha[data-sitekey], [data-sitekey]');
                            if (el) {
                                var v = el.getAttribute('data-sitekey');
                                if (v) return v;
                            }
                            // Method 2: parse 'k=' from any reCAPTCHA iframe src
                            var iframes = document.querySelectorAll('iframe[src*="recaptcha"]');
                            for (var i = 0; i < iframes.length; i++) {
                                var src = iframes[i].src || '';
                                var m = src.match(/[?&]k=([^&]+)/);
                                if (m && m[1]) return m[1];
                            }
                            // Method 3: walk ___grecaptcha_cfg.clients for sitekey
                            if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                                var cfg = window.___grecaptcha_cfg.clients;
                                var stack = [];
                                for (var k in cfg) stack.push(cfg[k]);
                                var seen = 0;
                                while (stack.length && seen < 500) {
                                    var node = stack.pop();
                                    seen++;
                                    if (!node || typeof node !== 'object') continue;
                                    if (node.sitekey) return node.sitekey;
                                    for (var key in node) {
                                        try {
                                            if (typeof node[key] === 'object' && node[key]) stack.push(node[key]);
                                        } catch(e){}
                                    }
                                }
                            }
                            return '';
                        } catch(e) { return ''; }
                        """
                    ) or ""
                    if site_key:
                        page_url = self.driver.current_url
                        print(f"  Auto-solving via {self.captcha_solver.service} (site_key {site_key[:12]}...)")
                        token = self.captcha_solver.solve_recaptcha_v2(site_key, page_url)
                        if token and self._inject_recaptcha_token(token):
                            # Verify the token landed somewhere in the page (textarea
                            # OR grecaptcha API). On pages that don't initialize
                            # grecaptcha JS, getResponse() returns empty even after
                            # the textarea is set — so also check raw textarea.
                            settle = _current_token() or self._read_recaptcha_textarea()
                            if settle:
                                print(f"  ✓ Auto-solve succeeded (token len {len(settle)})")
                                # Post-solve: if on disclaimer page, click 'I Accept'
                                # and wait for nav. If on search page, re-click submit
                                # so the form re-submits with the new token.
                                self._post_solve_advance(page_url)
                                return True
                            else:
                                print(f"  Token did not stick — trusting injection anyway (D-strategy fallback)")
                                # Even if verification can't confirm, the textarea was set.
                                # Try to advance — if it works, great; if not, the human
                                # checkpoint fires from the NEXT _handle_captcha call.
                                self._post_solve_advance(page_url)
                                return True
                        else:
                            print("  Auto-solve returned no token; will try human checkpoint")
                    else:
                        print("  No data-sitekey found on page; skipping auto-solve")
                except Exception as exc:
                    print(f"  Auto-solve error ({type(exc).__name__}): {exc}")

            # Bug #13 (SBD post-submit loop): Some Tyler portals (e.g. San
            # Bernardino /search/DOCSEARCH516S1) leave the reCAPTCHA iframe in
            # the DOM AFTER a successful submit, but the token is consumed on
            # submit (single-use). So we'd see iframe + empty token and falsely
            # raise CaptchaCheckpointRequired in a loop. Before raising, check
            # if results are visible — if so, the search already succeeded.
            try:
                result_rows_selector = (
                    self.selectors.get("result_rows")
                    or self.selectors.get("results_table")
                )
                if result_rows_selector:
                    results_rows = self.driver.find_elements(
                        By.XPATH, result_rows_selector
                    )
                    visible_rows = [r for r in results_rows if r.is_displayed()]
                    if visible_rows:
                        print(
                            f"  Results visible ({len(visible_rows)} rows) — "
                            "search succeeded despite lingering CAPTCHA iframe; "
                            "skipping checkpoint"
                        )
                        return True
            except Exception:
                pass

            try:
                current_url = self.driver.current_url
            except Exception:
                current_url = None

            message = (
                f"{self.county_name} County recorder requires CAPTCHA. "
                "Please solve it in the visible browser, then click Resume in the workflow. "
                "Do not close the browser window."
            )
            session = checkpoint_sessions.create(
                checkpoint_type="captcha",
                county=self.county_name,
                step="recorder_search_captcha",
                message=message,
                resource=self,
                details={
                    "captcha_type": self.captcha_type,
                    "url": current_url,
                    "timeout_seconds": MANUAL_CAPTCHA_TIMEOUT_SECONDS,
                    "manual_only": True,
                },
                timeout_seconds=MANUAL_CAPTCHA_TIMEOUT_SECONDS,
            )

            print("  CAPTCHA checkpoint created; waiting for user resume.")
            print(f"  Resume token: {session.resume_token}")
            raise CaptchaCheckpointRequired(
                resume_token=session.resume_token,
                county=self.county_name,
                step="recorder_search_captcha",
                message=message,
                details=session.public_payload()["details"],
            )

        except CaptchaCheckpointRequired:
            raise
        except Exception as e:
            print(f"  Error handling CAPTCHA: {e}")
            return False

    def navigate_to_search(self):
        """Navigate to the recorder website and access the Name search page.

        Supports two modes:
        - Multi-step: When 'navigation_steps' is defined in config, follows
          each step sequentially to build proper session state.
        - Direct (legacy): Navigates directly to search_url, then tries to
          click the Name Search link.
        """
        # Step 1: Always start at the disclaimer/base URL
        url = self._disclaimer_url or self._base_url
        print(f"Navigating to {url}")
        self.driver.get(url)
        time.sleep(2)

        if self._navigation_steps:
            # Multi-step navigation mode
            print(f"  Using multi-step navigation ({len(self._navigation_steps)} steps)")
            for i, step in enumerate(self._navigation_steps, 1):
                description = step.get("description", f"Step {i}")
                print(f"  Step {i}/{len(self._navigation_steps)}: {description}")
                success = self._execute_navigation_step(step)
                if not success:
                    print(f"  Warning: Navigation step {i} failed, attempting to continue")
        else:
            # Legacy direct navigation mode (existing behavior)
            self._accept_disclaimer()

            # Navigate to search page if different from base
            if self._search_url and self._search_url != self._base_url:
                print(f"  Navigating to search page: {self._search_url}")
                self.driver.get(self._search_url)
                time.sleep(2)

            # Try to find and click Name Search link
            try:
                name_link = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, self.selectors["name_search_link"]))
                )
                name_link.click()
                time.sleep(1)
                print("  Clicked Name Search link")
            except TimeoutException:
                print("  Warning: Name Search link not found, may already be on search page")

        # Store the resolved search page URL for return_to_search()
        self._resolved_search_url = self.driver.current_url
        print(f"  Search page URL: {self._resolved_search_url}")

    def _set_party_type(self, party_type: str):
        """Set the party type dropdown value."""
        value = self.party_type_map.get(party_type, "Both")

        # Strategy 1: Try XPath selector for <select> dropdown
        try:
            dropdown = self.driver.find_element(By.XPATH, self.selectors["party_type_dropdown"])
            select = Select(dropdown)
            try:
                select.select_by_visible_text(value)
            except:
                try:
                    select.select_by_value(value)
                except:
                    for option in select.options:
                        if value.lower() in option.text.lower():
                            select.select_by_visible_text(option.text)
                            break
            time.sleep(0.5)
            print(f"  Set party type: {value}")
            return
        except (NoSuchElementException, TimeoutException):
            pass

        # Strategy 2: JavaScript - find any select or radio by label
        try:
            js_set = self.driver.execute_script("""
                var value = arguments[0];
                // Try all select elements
                var selects = document.querySelectorAll('select');
                for (var i = 0; i < selects.length; i++) {
                    var opts = selects[i].options;
                    for (var j = 0; j < opts.length; j++) {
                        if (opts[j].text.toLowerCase().includes(value.toLowerCase()) ||
                            opts[j].value.toLowerCase().includes(value.toLowerCase())) {
                            selects[i].value = opts[j].value;
                            selects[i].dispatchEvent(new Event('change', {bubbles: true}));
                            return 'select';
                        }
                    }
                }
                // Try radio buttons
                var radios = document.querySelectorAll('input[type="radio"]');
                for (var i = 0; i < radios.length; i++) {
                    var label = document.querySelector('label[for="' + radios[i].id + '"]');
                    var labelText = label ? label.textContent : '';
                    if (labelText.toLowerCase().includes(value.toLowerCase()) ||
                        (radios[i].value || '').toLowerCase().includes(value.toLowerCase())) {
                        radios[i].click();
                        return 'radio';
                    }
                }
                return null;
            """, value)
            if js_set:
                print(f"  Set party type (JS {js_set}): {value}")
                time.sleep(0.5)
                return
        except Exception:
            pass

        print(f"  Warning: No party type control found (may not exist on this search page)")

    def _set_dates(self):
        """Set the search date range."""
        start_set = False
        end_set = False

        # Strategy 1: XPath selectors
        try:
            start_field = self.driver.find_element(By.XPATH, self.selectors["start_date_field"])
            start_field.clear()
            start_field.send_keys(self.start_date)
            start_set = True
        except (NoSuchElementException, Exception):
            pass

        try:
            end_field = self.driver.find_element(By.XPATH, self.selectors["end_date_field"])
            end_field.clear()
            end_field.send_keys(self.end_date)
            end_set = True
        except (NoSuchElementException, Exception):
            pass

        # Strategy 2: JavaScript label-based search for date fields
        if not start_set or not end_set:
            try:
                js_result = self.driver.execute_script("""
                    function findAndSetDateField(labelKeywords, value) {
                        var inputs = document.querySelectorAll('input');
                        for (var i = 0; i < inputs.length; i++) {
                            var input = inputs[i];
                            var id = (input.id || '').toLowerCase();
                            var name = (input.name || '').toLowerCase();
                            var ph = (input.placeholder || '').toLowerCase();
                            var ariaLabel = (input.getAttribute('aria-label') || '').toLowerCase();
                            var dataRole = (input.getAttribute('data-role') || '').toLowerCase();

                            // Check label element
                            var labelEl = document.querySelector('label[for="' + input.id + '"]');
                            var labelText = labelEl ? labelEl.textContent.toLowerCase() : '';

                            // Check parent label
                            var parentLabel = input.closest('label');
                            if (parentLabel) labelText += ' ' + parentLabel.textContent.toLowerCase();

                            var allText = id + ' ' + name + ' ' + ph + ' ' + ariaLabel + ' ' + labelText;

                            var matches = false;
                            for (var k = 0; k < labelKeywords.length; k++) {
                                if (allText.includes(labelKeywords[k])) {
                                    matches = true;
                                    break;
                                }
                            }
                            if (matches) {
                                input.value = '';
                                input.value = value;
                                input.dispatchEvent(new Event('input', {bubbles: true}));
                                input.dispatchEvent(new Event('change', {bubbles: true}));
                                input.dispatchEvent(new Event('blur', {bubbles: true}));
                                return true;
                            }
                        }
                        return false;
                    }

                    var results = {};
                    if (arguments[2]) {
                        results.startSet = findAndSetDateField(
                            ['start', 'from', 'begin', 'recording date s', 'recordingdatestart'],
                            arguments[0]
                        );
                    }
                    if (arguments[3]) {
                        results.endSet = findAndSetDateField(
                            ['end', 'to date', 'thru', 'through', 'recording date e', 'recordingdateend'],
                            arguments[1]
                        );
                    }
                    return results;
                """, self.start_date, self.end_date, not start_set, not end_set)

                if js_result:
                    if js_result.get('startSet'):
                        start_set = True
                    if js_result.get('endSet'):
                        end_set = True
            except Exception:
                pass

        if start_set or end_set:
            print(f"  Set date range: {self.start_date} to {self.end_date}")
        else:
            print("  Warning: Could not find date fields")

    def _safe_clear_and_type(self, field, text: str):
        """
        Safely clear a field and type text into it.

        Tyler/jQuery Mobile inputs may throw 'invalid element state' on .clear()
        or 'element not interactable' on .send_keys(). This method tries multiple
        strategies to handle these cases.

        Strategy order is tuned for Tyler's autocomplete-driven name index:
        real per-keystroke send_keys MUST run first so Tyler's keyup listeners
        fire and `li.acItem` suggestions render. Pure-JS fill is last-resort
        only — it bypasses autocomplete event listeners.
        """
        # Strategy 1: JavaScript focus + click (to scroll into view + focus),
        # then Selenium send_keys with real per-keystroke typing.
        # This is the only path that reliably fires Tyler's autocomplete-on-keyup
        # listeners, so it runs FIRST.
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); "
                "arguments[0].focus(); arguments[0].click();",
                field
            )
            time.sleep(0.3)
            field.send_keys(Keys.CONTROL + "a")
            field.send_keys(Keys.DELETE)
            field.send_keys(text)
            return
        except Exception:
            pass

        # Strategy 2: Standard Selenium (works for normal inputs).
        # Fallback if Strategy 1's JS focus/click hits an exception.
        try:
            field.clear()
            field.send_keys(text)
            return
        except Exception:
            pass

        # Strategy 3: ActionChains (types to wherever focus is)
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); "
                "arguments[0].focus(); arguments[0].click(); "
                "arguments[0].value = '';",
                field
            )
            time.sleep(0.3)
            ActionChains(self.driver).send_keys(text).perform()
            return
        except Exception:
            pass

        # Strategy 4: Full JavaScript (last resort).
        # Last-resort only; bypasses autocomplete event listeners — use only
        # when prior strategies cannot interact with the element.
        self.driver.execute_script("""
            var field = arguments[0];
            var value = arguments[1];
            field.scrollIntoView({block: 'center'});
            field.focus();
            field.value = '';
            field.value = value;
            field.dispatchEvent(new Event('input', {bubbles: true}));
            field.dispatchEvent(new Event('change', {bubbles: true}));
            field.dispatchEvent(new Event('keyup', {bubbles: true}));
        """, field, text)
        print(f"  (used JavaScript to set field value)")

    def _enter_name(self, name: str):
        """
        Enter the name to search for.

        Handles two form layouts:
        1. Split fields: separate Last Name / First Name inputs
        2. Combined field: single "Name" or "BothNames" input (Tyler DOCSEARCH pages)

        If split fields are not found, automatically falls back to combined field.
        Uses Selenium send_keys for proper autocomplete/suggest trigger.
        """
        try:
            name_entered = False
            # Track what was actually typed (combined-name branch may truncate
            # 3+ token names to LAST FIRST for Tyler BothNames — Bug #15).
            typed_name = name

            # 2026-05-26 Orange FL: clear any chips left over from a previous
            # search (cblist-input-list widget). Without this, the second
            # search would AND its name onto the first one's chip — returning
            # zero results because no single document matches both names.
            try:
                cleared = self.driver.execute_script("""
                    var holder = document.getElementById('field_BothNamesID-holder');
                    if (!holder) return 0;
                    var chips = holder.querySelectorAll('li.cblist-input-list');
                    var n = 0;
                    chips.forEach(function(li) { li.remove(); n++; });
                    return n;
                """)
                if cleared:
                    print(f"  Cleared {cleared} stale cblist chip(s) from prior search")
            except Exception:
                pass

            if self.name_format == "split":
                # Split name into last/first
                parts = name.split()
                if len(parts) >= 2:
                    last_name = parts[0]
                    first_name = " ".join(parts[1:])
                else:
                    last_name = name
                    first_name = ""

                # Try split Last/First fields via XPath
                try:
                    last_field = self.driver.find_element(By.XPATH, self.selectors["last_name_field"])
                    self._safe_clear_and_type(last_field, last_name)
                    print(f"  Entered last name: {last_name}")
                    name_entered = True

                    if first_name:
                        try:
                            first_field = self.driver.find_element(By.XPATH, self.selectors["first_name_field"])
                            self._safe_clear_and_type(first_field, first_name)
                            print(f"  Entered first name: {first_name}")
                        except NoSuchElementException:
                            print(f"  Warning: First name field not found")
                except NoSuchElementException:
                    pass

            # If split fields not found (or name_format is "combined"), use combined field
            if not name_entered:
                if self.name_format == "split":
                    print("  Split name fields not found, trying combined name field...")

                # Bug #15 (Riverside FINKELSTEIN): Tyler's combined-name field
                # ("BothNames") only matches "LAST FIRST" (2 tokens). A 3-part
                # name like "FINKELSTEIN DEBORAH ELLEN" returns zero results
                # because Tyler does an AND-match on all tokens including the
                # middle name. Drop tokens past the first two for combined
                # searches.
                # 2026-05-26 Orange FL: portals with common surnames (e.g.
                # GREER) need the middle initial to stay under the result-count
                # cap. Counties can opt out of truncation via
                # config.keep_middle_initial: true.
                keep_middle_initial = bool(self.config.get("keep_middle_initial"))
                # Strip stray commas — some sources (e.g. workflow_config
                # GREER, DIANA V) deliver names with a comma between last and
                # first; Tyler treats commas as literal characters and zeroes
                # the match.
                combined_name = name.replace(",", " ")
                # Collapse multi-space
                combined_name = " ".join(combined_name.split())
                tokens = combined_name.split()
                if not keep_middle_initial and len(tokens) > 2:
                    combined_name = " ".join(tokens[:2])
                    print(
                        f"  Combined name search: truncating "
                        f"'{name}' -> '{combined_name}' "
                        f"(Tyler BothNames only supports LAST FIRST)"
                    )
                elif keep_middle_initial and combined_name != name:
                    print(
                        f"  Combined name search: normalised "
                        f"'{name}' -> '{combined_name}' "
                        f"(keep_middle_initial=True)"
                    )
                typed_name = combined_name

                # Strategy 1: Find by Tyler-specific ID pattern (field_BothNamesID)
                name_field = None
                try:
                    name_field = self.driver.find_element(By.CSS_SELECTOR,
                        "input[id*='BothNames'], input[id*='bothnames'], input[id*='NameID']")
                    self._safe_clear_and_type(name_field, combined_name)
                    print(f"  Entered name (BothNames field): {combined_name}")
                    name_entered = True

                    # 2026-05-26 Orange FL: IMMEDIATELY commit chip via real
                    # Selenium Keys.RETURN while the field is still focused.
                    # Tyler's `selfservice.suggest.autocomplete` JS listens
                    # for the Enter key on the visible input and commits the
                    # typed value as a chip in
                    # #field_BothNamesID-holder. Probe (2026-05-26) proved
                    # this path works for Orange FL.
                    #
                    # Use ActionChains (sends keys to whichever element has
                    # focus). The element-ref-based name_field.send_keys may
                    # raise 'element not interactable' here because the
                    # suggest XHR re-renders the parent UL between
                    # _safe_clear_and_type's last send_keys and ours.
                    if self.config.get("commit_chip_with_enter", True):
                        try:
                            from selenium.webdriver.common.keys import Keys
                            # Re-focus via JS, then dispatch Enter via
                            # ActionChains so we don't depend on the (possibly
                            # stale) element handle.
                            self.driver.execute_script(
                                "var f = document.getElementById('field_BothNamesID');"
                                "if (f) { f.focus(); }"
                            )
                            time.sleep(0.3)
                            ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                            time.sleep(0.8)
                            committed = self.driver.execute_script(
                                "var h = document.getElementById('field_BothNamesID-holder');"
                                "if (!h) return null;"
                                "var inp = h.querySelector('input[id*=\"searchInput\"]');"
                                "return inp ? inp.value : null;"
                            )
                            if committed:
                                print(f"  Committed chip via Enter: {committed!r}")
                            else:
                                # Fallback: try element-ref send_keys with a
                                # re-find before giving up.
                                try:
                                    fresh = self.driver.find_element(
                                        By.ID, "field_BothNamesID"
                                    )
                                    fresh.send_keys(Keys.RETURN)
                                    time.sleep(0.8)
                                    committed = self.driver.execute_script(
                                        "var h = document.getElementById('field_BothNamesID-holder');"
                                        "if (!h) return null;"
                                        "var inp = h.querySelector('input[id*=\"searchInput\"]');"
                                        "return inp ? inp.value : null;"
                                    )
                                    if committed:
                                        print(f"  Committed chip via Enter (refind): {committed!r}")
                                    else:
                                        print(
                                            "  [chip-commit] warning: no chip "
                                            "created after both ActionChains "
                                            "and re-find paths"
                                        )
                                except Exception as _e2:
                                    print(f"  [chip-commit] fallback failed: {_e2}")
                        except Exception as _enter_err:
                            print(f"  [chip-commit] failed: {_enter_err}")
                except Exception:
                    pass

                # Strategy 2: Find any visible text input labeled "Name"
                if not name_entered:
                    try:
                        field_id = self.driver.execute_script("""
                            var labels = document.querySelectorAll('label');
                            for (var i = 0; i < labels.length; i++) {
                                var text = labels[i].textContent.trim().toLowerCase();
                                if (text === 'name' || text === 'search name' || text === 'owner name') {
                                    var forId = labels[i].getAttribute('for');
                                    if (forId) return forId;
                                }
                            }
                            return null;
                        """)
                        if field_id:
                            name_field = self.driver.find_element(By.ID, field_id)
                            self._safe_clear_and_type(name_field, combined_name)
                            print(f"  Entered name (label lookup): {combined_name}")
                            name_entered = True
                    except (NoSuchElementException, Exception):
                        pass

                # Strategy 3: Try XPath for generic combined name field
                if not name_entered:
                    try:
                        name_field = self.driver.find_element(By.XPATH, self.selectors["name_field"])
                        self._safe_clear_and_type(name_field, combined_name)
                        print(f"  Entered name: {combined_name}")
                        name_entered = True
                    except NoSuchElementException:
                        pass

            if not name_entered:
                print(f"  ERROR: Could not find any name field on the page")

            # Handle autocomplete suggestion list (Tyler DOCSEARCH pages).
            # For Orange FL cblist-input-list widget, the chip was already
            # committed inline above (Strategy 1) via real Keys.RETURN. Other
            # Tyler portals (Fresno, Riverside) may still need to click an
            # autocomplete item via this helper.
            if name_entered:
                # If chip is already committed (Orange FL path), skip the
                # 6-second autocomplete poll — it would be a no-op.
                chip_exists = False
                try:
                    chip_exists = bool(self.driver.execute_script(
                        "var h = document.getElementById('field_BothNamesID-holder');"
                        "if (!h) return null;"
                        "var inp = h.querySelector('input[id*=\"searchInput\"]');"
                        "return inp ? inp.value : null;"
                    ))
                except Exception:
                    pass
                if not chip_exists:
                    self._select_autocomplete_suggestion(typed_name)

            time.sleep(0.5)

        except Exception as e:
            print(f"  Error entering name: {e}")
            raise

    def _select_autocomplete_suggestion(self, name: str):
        """
        Wait for autocomplete/suggest dropdown and click the best match.

        Tyler DOCSEARCH pages show a suggestion list (li.acItem) after typing.
        A name must be selected from this list for the search to work.

        2026-05-26 Orange FL: portal uses `cblist-input-list` widget where the
        visible text input is a *filter* and the actual party-name search
        criteria must be added as chips into `#field_BothNamesID-holder`. The
        autocomplete suggest XHR can be slow (>2s), so this helper now polls
        up to 6s, and also detects already-added chips so the second-name
        search doesn't re-block on stale UI state.

        Uses JavaScript to find and click the suggestion to avoid stale element
        references (the autocomplete list is dynamically rendered and can change
        between find_elements() and click()).
        """
        try:
            # Poll for autocomplete items to render (up to ~6 seconds)
            clicked_text = None
            for _ in range(6):
                clicked_text = self.driver.execute_script("""
                    var nameQuery = arguments[0].trim().toLowerCase();

                    // Find all autocomplete suggestion items
                    var items = document.querySelectorAll('li.acItem');
                    if (!items.length) {
                        items = document.querySelectorAll('ul[id$="-aclist"] li');
                    }
                    if (!items.length) return null;  // No autocomplete on this page

                    var bestMatch = null;
                    var firstVisible = null;

                    for (var i = 0; i < items.length; i++) {
                        var item = items[i];
                        // Check if visible (offsetParent !== null for displayed elements)
                        if (item.offsetParent === null && item.style.display === 'none') continue;

                        var itemText = (item.textContent || '').trim();
                        if (!itemText) continue;

                        if (!firstVisible) firstVisible = item;

                        // Check for exact match
                        if (itemText.toLowerCase() === nameQuery) {
                            bestMatch = item;
                            break;
                        }
                    }

                    var target = bestMatch || firstVisible;
                    if (target) {
                        target.scrollIntoView({block: 'center'});
                        target.click();
                        return (target.textContent || '').trim();
                    }
                    return null;
                """, name)
                if clicked_text:
                    break
                time.sleep(1)

            if clicked_text:
                print(f"  Selected autocomplete: {clicked_text}")
                time.sleep(1)
            else:
                print("  No autocomplete suggestions found (may not be required)")

        except Exception as e:
            print(f"  Warning: Autocomplete handling: {e}")

    def _check_empty_search_error(self):
        """Surface Tyler's 'Empty searches are not allowed' / similar form errors.

        Tyler shows this either as an inline error block or a modal dialog when
        the search form is submitted with no terms. The pipeline should treat
        this as a non-terminal failure (RetryableSubmitError) — the caller can
        either correct the form and retry, or surface a `needs_human` checkpoint
        to the UI.
        """
        try:
            from titlepro.automation.checkpoints import RetryableSubmitError
        except Exception:
            return
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            return
        markers = (
            "empty searches are not allowed",
            "please enter at least one search criterion",
            "please enter a search criterion",
            "no search criteria",
        )
        lower = body_text.lower()
        for marker in markers:
            if marker in lower:
                raise RetryableSubmitError(
                    f"{self.county_name}: '{marker}'. Provide a name/date/instrument criterion and retry.",
                    county=self.county_name,
                    step="recorder_search_submit",
                )

    def _click_search(self):
        """Click the search button and wait for results.

        Handles multiple button types:
        - Standard <button> elements
        - <input type="submit"> elements
        - Tyler DOCSEARCH <a id="searchButton"> elements
        """
        # Handle CAPTCHA if required (pre-click)
        if not self._handle_captcha():
            raise Exception("CAPTCHA solving required but failed")

        # If manual-CAPTCHA mode already advanced the page (URL changed off the
        # search form to a results / details URL), there's nothing left to click.
        # Try to detect this and bail out gracefully so extract_results() runs.
        try:
            current_url = (self.driver.current_url or "").lower()
            if any(marker in current_url for marker in ("searchresult", "/results", "searchresults")):
                print(f"  Already on results page ({self.driver.current_url}); skipping search-button click")
                return
        except Exception:
            pass

        # Strategy 1: Standard XPath selector (button/input)
        try:
            search_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.selectors["search_button"]))
            )
            search_button.click()
            print("  Clicked search button")
            time.sleep(3)
            return
        except (TimeoutException, NoSuchElementException):
            pass

        # Strategy 2: Tyler DOCSEARCH <a id="searchButton"> or <a role="button">
        try:
            search_link = self.driver.find_element(By.CSS_SELECTOR,
                "a#searchButton, a[id*='searchButton'], a[role='button'][href*='searchResult']")
            search_link.click()
            print("  Clicked search button (anchor link)")
            # jQuery Mobile SPA page transition needs extra time to load results
            time.sleep(5)
            return
        except NoSuchElementException:
            pass

        # Strategy 3: JavaScript - find any clickable element with "Search" text
        try:
            clicked = self.driver.execute_script("""
                var elements = document.querySelectorAll(
                    'a#searchButton, button#searchButton, input[type="submit"], ' +
                    'a[role="button"], button[type="submit"], ' +
                    'a.ui-btn, button.ui-btn'
                );
                for (var i = 0; i < elements.length; i++) {
                    var el = elements[i];
                    var text = (el.textContent || el.value || '').trim().toLowerCase();
                    if (text === 'search' || el.id === 'searchButton') {
                        el.scrollIntoView({block: 'center'});
                        el.click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                print("  Clicked search button (JS fallback)")
                time.sleep(3)
                return
        except Exception:
            pass

        print("  ERROR: Could not find search button")
        raise Exception("Search button not found on page")

    def perform_search(self, name: str, party_type: str = "Grantor/Grantee") -> List[DocumentRecord]:
        """
        Perform a name search on the Tyler Technologies platform.

        Args:
            name: Name to search (use "Last First" format, e.g., "Smith John")
            party_type: One of "All", "Grantor", "Grantee", "Grantor/Grantee"

        Returns:
            List of DocumentRecord objects
        """
        print(f"\n  Performing search:")
        print(f"    Name: {name}")
        print(f"    Party Type: {party_type}")
        print(f"    County: {self.county_name}")

        # Tag the current search unit so any CAPTCHA checkpoint raised below
        # carries case/job/search-unit context for the orchestrator.
        self._current_search_unit = f"{name} / {party_type}"

        # Set up search parameters
        self._set_party_type(party_type)
        self._enter_name(name)
        self._set_dates()

        # Execute search (this calls _handle_captcha pre-click and can raise
        # CaptchaCheckpointRequired)
        try:
            self._click_search()
        except CaptchaCheckpointRequired as cp:
            # Stamp the search unit so the orchestrator knows which unit to
            # resume after the human solves the puzzle.
            cp.details.setdefault("search_unit", self._current_search_unit)
            cp.search_unit = self._current_search_unit
            checkpoint_sessions.update_details(
                cp.resume_token,
                {"search_unit": self._current_search_unit},
            )
            raise

        # Some Tyler pages re-render CAPTCHA AFTER submit (rate-limit / second
        # challenge). Re-check now so the orchestrator gets another resumable
        # checkpoint instead of an extract_results false-negative.
        try:
            self._handle_captcha()
        except CaptchaCheckpointRequired as cp:
            cp.details.setdefault("search_unit", self._current_search_unit)
            cp.search_unit = self._current_search_unit
            checkpoint_sessions.update_details(
                cp.resume_token,
                {"search_unit": self._current_search_unit, "phase_substep": "post_click"},
            )
            raise

        # Tyler may show "Empty searches are not allowed" instead of CAPTCHA
        # when the form was submitted bare. Surface that as a retryable error.
        self._check_empty_search_error()

        # Check for no results
        try:
            no_results = self.driver.find_element(By.XPATH, self.selectors["no_results"])
            if no_results and no_results.is_displayed():
                print("  No results found")
                return []
        except NoSuchElementException:
            pass

        return self.extract_results()

    def extract_results(self) -> List[DocumentRecord]:
        """Extract document records from Tyler Technologies results.

        Handles three result layouts:
        1. jQuery Mobile listview (Tyler DOCSEARCH pages)
        2. HTML tables (standard Tyler)
        3. Text-based fallback (parse doc numbers from page text)

        Scopes extraction to the active jQuery Mobile page to avoid
        reading elements from hidden/cached SPA pages.
        """
        documents = []

        try:
            # Wait for results to load - jQuery Mobile AJAX can take time
            time.sleep(3)

            # Wait until the page has result-like content (doc numbers in text)
            import re
            for attempt in range(5):
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                if re.search(r'\d{4}-\d+|\d{7,13}', page_text):
                    break
                if any(msg in page_text.lower() for msg in ['no records', 'no results', '0 records', '0 total']):
                    break
                time.sleep(2)
                print(f"  Waiting for results to load... (attempt {attempt + 1})")

            page_text = self.driver.find_element(By.TAG_NAME, "body").text

            # Check for no results message
            if any(msg in page_text.lower() for msg in ['no records', 'no results', '0 records', '0 total']):
                print("  No results found for this search")
                return []

            # Try to count results
            expected_count = 0
            match = re.search(r'(\d+)\s*(?:total\s*)?(?:record|result)', page_text.lower())
            if match:
                expected_count = int(match.group(1))
                print(f"  Found {expected_count} record(s)")

            # JavaScript extraction
            # KEY INSIGHT: Tyler DOCSEARCH pages use jQuery Mobile SPA.
            # - Results load in a new ui-page-active div via AJAX
            # - Tyler internal IDs (13-digit numbers) are NOT real doc numbers
            # - Real doc numbers are in YYYY-NNNNNNN format
            # - If YYYY format isn't shown in the list, we must click each result
            extract_script = """
            var results = [];
            var seenDocNums = {};

            // Scope to active jQuery Mobile page
            var scope = document.querySelector('.ui-page-active') ||
                        document.querySelector('[data-role="page"]:last-of-type') ||
                        document.body;

            // Doc number extraction: supports two formats:
            // 1. Dashed:   YYYY-NNNNN (e.g., 2014-2023)
            // 2. Undashed: YYYYNNNNN  (e.g., 202302811, 7-12 digits)
            // Tyler internal IDs (13+ digits) are excluded.
            // Undashed numbers are converted: 202302811 → 2023-02811
            function extractDocNum(text) {
                var dashed = text.match(/(\\d{4}-\\d+)/);
                if (dashed) return dashed[1];
                var undashed = text.match(/(?:^|[^\\d])(\\d{7,13})(?=[^\\d]|$)/);
                if (undashed) {
                    var num = undashed[1];
                    if (num.length === 13) {
                        var prefix = num.substring(0, 2);
                        if (prefix !== '19' && prefix !== '20') return null;
                    }
                    return num.substring(0, 4) + '-' + num.substring(4);
                }
                return null;
            }

            // ============================================================
            // Strategy 1: Find all result <li> items on the active page
            // and extract doc numbers in YYYY-NNNNN format.
            // ============================================================
            var allLists = scope.querySelectorAll(
                'ul.ss-listview, ul[data-role="listview"], ul.ui-listview'
            );

            // Find the RESULTS list using priority-based selection:
            // Priority 1: List containing "N total" counter (definitive results list)
            // Priority 2: List with items containing dates (likely results)
            // Priority 3: Fallback to list with most items
            var resultList = null;
            var resultItems = [];

            // Priority 1: Find the list that has a "N total" counter item
            for (var u = 0; u < allLists.length; u++) {
                var ul = allLists[u];
                if (ul.classList.contains('ss-utility-box')) continue;
                var items = ul.querySelectorAll('li');
                for (var i = 0; i < items.length; i++) {
                    var txt = (items[i].textContent || '').trim().toLowerCase();
                    if (txt.match(/^\\d+\\s*total/)) {
                        resultList = ul;
                        resultItems = items;
                        break;
                    }
                }
                if (resultList) break;
            }

            // Priority 2: List with items that have dates (MM/DD/YYYY) and long text
            if (!resultList) {
                for (var u = 0; u < allLists.length; u++) {
                    var ul = allLists[u];
                    if (ul.classList.contains('ss-utility-box')) continue;
                    var items = ul.querySelectorAll('li');
                    var dateCount = 0;
                    for (var i = 0; i < items.length; i++) {
                        var txt = (items[i].textContent || '').trim();
                        if (txt.length > 30 && txt.match(/\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}/)) dateCount++;
                    }
                    if (dateCount >= 2) {
                        resultList = ul;
                        resultItems = items;
                        break;
                    }
                }
            }

            // Priority 3: Fallback — list with most items (old behavior)
            if (!resultList) {
                var maxItems = 0;
                for (var u = 0; u < allLists.length; u++) {
                    var ul = allLists[u];
                    if (ul.classList.contains('ss-utility-box')) continue;
                    var items = ul.querySelectorAll('li');
                    if (items.length > maxItems) {
                        maxItems = items.length;
                        resultList = ul;
                        resultItems = items;
                    }
                }
            }

            if (resultList && resultItems.length > 0) {
                for (var i = 0; i < resultItems.length; i++) {
                    var li = resultItems[i];
                    var liText = (li.textContent || '').trim();

                    // Skip header/count/divider items
                    if (liText.match(/^\\d+\\s*total/i) || liText.match(/^\\s*$/) ||
                        li.getAttribute('data-role') === 'list-divider' ||
                        li.classList.contains('ss-listview-internal')) {
                        continue;
                    }

                    var result = {
                        document_number: '',
                        grantors: '',
                        grantees: '',
                        grantor_grantees: '',
                        document_type: '',
                        recording_date: '',
                        pages: ''
                    };

                    // Extract doc number (dashed YYYY-N+ or undashed 7-12 digits)
                    result.document_number = extractDocNum(liText) || '';

                    // Also check <a> href for doc number
                    var link = li.querySelector('a');
                    if (!result.document_number && link) {
                        var href = link.getAttribute('href') || '';
                        result.document_number = extractDocNum(href) || '';
                    }

                    // Parse Tyler DOCSEARCH list format:
                    // "T 202302811 • TRUST DEED Recording Date 09/07/2023 ..."
                    if (result.document_number) {
                        var bulletIdx = liText.indexOf('\u2022');
                        if (bulletIdx >= 0) {
                            var afterBullet = liText.substring(bulletIdx + 1).trim();
                            var rdIdx = afterBullet.search(/Recording Date/i);
                            if (rdIdx >= 0 && !result.document_type) {
                                result.document_type = afterBullet.substring(0, rdIdx).trim();
                            }
                        }
                    }

                    var container = link || li;

                    // Extract doc type from title element
                    var titleEl = container.querySelector(
                        '[class*="searchResult-title"], [class*="title"], ' +
                        'h1, h2, h3, h4, h5, h6, strong, b'
                    );
                    if (titleEl) {
                        var titleText = titleEl.textContent.trim();
                        if (result.document_number) {
                            result.document_type = titleText
                                .replace(result.document_number, '')
                                .replace(/^[\\s\\-–—]+|[\\s\\-–—]+$/g, '')
                                .trim();
                        } else {
                            result.document_type = titleText;
                        }
                    }

                    // Extract metadata from child elements
                    var valueEls = container.querySelectorAll(
                        '[class*="searchResult-value"], [class*="value"], ' +
                        '[class*="detail"], p, span'
                    );
                    var processedTexts = {};
                    for (var v = 0; v < valueEls.length; v++) {
                        var el = valueEls[v];
                        if (el === titleEl) continue;
                        if (el.querySelector('[class*="value"], p')) continue;
                        var valText = el.textContent.trim();
                        if (!valText || valText.length < 3 || processedTexts[valText]) continue;
                        processedTexts[valText] = true;
                        var lower = valText.toLowerCase();

                        if ((lower.includes('recording date') || lower.includes('rec date') ||
                             lower.includes('recorded')) && !result.recording_date) {
                            var dm = valText.match(/(\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})/);
                            if (dm) result.recording_date = dm[1];
                        } else if (lower.includes('grantor') && !result.grantors) {
                            result.grantors = valText.replace(/^.*grantor[s]?[:\\s]*/i, '').trim();
                        } else if (lower.includes('grantee') && !result.grantees) {
                            result.grantees = valText.replace(/^.*grantee[s]?[:\\s]*/i, '').trim();
                        } else if ((lower.includes('name') || lower.includes('party')) &&
                                   !result.grantor_grantees && !lower.includes('search')) {
                            result.grantor_grantees = valText.replace(/^.*(name|party)[s]?[:\\s]*/i, '').trim();
                        } else if (lower.includes('page') && !result.pages) {
                            result.pages = valText.replace(/^.*page[s]?[:\\s]*/i, '').trim();
                        } else if ((lower.includes('doc type') || lower.includes('document type')) &&
                                   !result.document_type) {
                            result.document_type = valText.replace(/^.*doc(?:ument)?\\s*type[:\\s]*/i, '').trim();
                        } else if (lower.includes('instrument') || lower.includes('doc #') ||
                                   lower.includes('document #') || lower.includes('book')) {
                            // Try to extract doc number from labeled field
                            if (!result.document_number) {
                                var extracted = extractDocNum(valText);
                                if (extracted) result.document_number = extracted;
                            }
                        }
                    }

                    // Fallback: date from full li text
                    if (!result.recording_date) {
                        var dm2 = liText.match(/(\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})/);
                        if (dm2) result.recording_date = dm2[1];
                    }

                    if (result.document_number && !seenDocNums[result.document_number]) {
                        seenDocNums[result.document_number] = true;
                        results.push(result);
                    }
                }
            }

            // ============================================================
            // Strategy 2: HTML table extraction (standard Tyler)
            // ============================================================
            if (results.length === 0) {
                var tables = scope.querySelectorAll('table');
                for (var t = 0; t < tables.length; t++) {
                    var table = tables[t];
                    var rows = table.querySelectorAll('tbody tr, tr');
                    for (var i = 0; i < rows.length; i++) {
                        var cells = rows[i].querySelectorAll('td');
                        if (cells.length < 5) continue;
                        var docNum = null;
                        for (var c = 0; c < Math.min(cells.length, 3); c++) {
                            var text = cells[c].innerText.trim();
                            var extracted = extractDocNum(text);
                            if (extracted) { docNum = extracted; break; }
                        }
                        if (docNum && !seenDocNums[docNum]) {
                            seenDocNums[docNum] = true;
                            var result = { document_number: docNum, grantors: '', grantees: '',
                                grantor_grantees: '', document_type: '', recording_date: '', pages: '' };
                            for (var c = 1; c < cells.length; c++) {
                                var text = cells[c].innerText.trim();
                                if (text.match(/\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}/)) {
                                    result.recording_date = text; break;
                                }
                            }
                            results.push(result);
                        }
                    }
                    if (results.length > 0) break;
                }
            }

            // ============================================================
            // Strategy 3: Text-based fallback using YYYY-NNNNN pattern.
            //
            // This is the most lenient strategy and trips on page footers
            // (e.g. "© 2014-2025 Tyler Technologies"). Defensive filters:
            //   (a) reject lines containing copyright/footer/nav phrases
            //   (b) require a date OR an explicit party/doc label in the
            //       same line or within a 5-line context window
            //   (c) reject 4-digit document_numbers when YYYY-YYYY (date-range
            //       footer) — at least one '-' segment must be 5+ digits OR
            //       text must contain a clear doc-context word
            // ============================================================
            var FOOTER_PATTERNS = /©|\\(c\\)|copyright|all rights reserved|tyler technologies|powered by|version\\s*\\d|terms of (use|service)|privacy/i;
            var DOC_CONTEXT = /grantor|grantee|recording date|rec\\.?\\s*date|recorded|doc(?:ument)?\\s*type|instrument|book\\b|page\\b|trust deed|deed of trust|mortgage|lien|reconveyance|assignment|notice of/i;

            if (results.length === 0) {
                var pageText = scope.innerText || document.body.innerText;
                var lines = pageText.split('\\n');
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.length < 6) continue;
                    if (FOOTER_PATTERNS.test(line)) continue;

                    var docNum = extractDocNum(line);
                    if (!docNum || seenDocNums[docNum]) continue;

                    // Build a 5-line context window for date/label evidence
                    var ctx = '';
                    for (var j = Math.max(0, i - 2); j <= Math.min(lines.length - 1, i + 4); j++) {
                        var cl = lines[j] || '';
                        if (FOOTER_PATTERNS.test(cl)) continue;
                        ctx += cl + ' ';
                    }
                    var hasDate = /\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}/.test(ctx);
                    var hasDocContext = DOC_CONTEXT.test(ctx);

                    // Reject YYYY-YYYY ranges that look like copyright spans
                    var rangeLooksLikeYearSpan = /^\\d{4}-\\d{4}$/.test(docNum) &&
                        parseInt(docNum.slice(0, 4), 10) > 1990 &&
                        parseInt(docNum.slice(-4), 10) > parseInt(docNum.slice(0, 4), 10);
                    if (rangeLooksLikeYearSpan && !hasDocContext) continue;

                    // Require at least one positive signal nearby
                    if (!hasDate && !hasDocContext) continue;

                    seenDocNums[docNum] = true;
                    var result = { document_number: docNum, grantors: '', grantees: '',
                        grantor_grantees: '', document_type: '', recording_date: '', pages: '' };
                    var rawMatch = line.match(/(\\d{4}-\\d+)/) || line.match(/(?:^|[^\\d])(\\d{7,13})(?=[^\\d]|$)/);
                    var rawNum = rawMatch ? rawMatch[1] : docNum;
                    var beforeDoc = line.substring(0, Math.max(line.indexOf(rawNum), 0)).trim();
                    if (beforeDoc && !FOOTER_PATTERNS.test(beforeDoc)) {
                        result.document_type = beforeDoc.replace(/[\\-–—]+$/, '').trim();
                    }
                    var dm = ctx.match(/(\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})/);
                    if (dm) result.recording_date = dm[1];
                    results.push(result);
                }
            }

            // ============================================================
            // Debug: comprehensive page dump if nothing found
            // ============================================================
            var debugInfo = {};
            if (results.length === 0) {
                var bodyText = (scope.innerText || document.body.innerText);
                debugInfo.pageText = bodyText.substring(0, 1200);
                debugInfo.url = window.location.href;

                // Dump all <li> items from all lists
                var liDump = '';
                var allLi = scope.querySelectorAll('ul li');
                for (var x = 0; x < Math.min(allLi.length, 8); x++) {
                    var liHtml = allLi[x].outerHTML.substring(0, 400);
                    liDump += '--- LI[' + x + '] ---\\n' + liHtml + '\\n';
                }
                debugInfo.liDump = liDump;

                // Dump all <a> hrefs that might contain doc info
                var linkDump = '';
                var allLinks = scope.querySelectorAll('a[href*="document"], a[href*="detail"], a[href*="search"]');
                for (var x = 0; x < Math.min(allLinks.length, 10); x++) {
                    linkDump += allLinks[x].href + ' -> ' + (allLinks[x].textContent || '').substring(0, 80).trim() + '\\n';
                }
                debugInfo.linkDump = linkDump;
            }

            var format = results.length > 0 ? (resultList ? 'listview' : 'text') : 'none';
            debugInfo.activePage = scope.tagName + (scope.id ? '#' + scope.id : '');
            debugInfo.totalLists = allLists ? allLists.length : 0;
            debugInfo.resultItems = resultItems ? resultItems.length : 0;
            debugInfo.totalResults = results.length;

            return { results: results, format: format, debug: debugInfo };
            """

            js_data = self.driver.execute_script(extract_script, self.doc_number_pattern)

            if js_data:
                results_list = js_data.get('results', []) or []
                result_format = js_data.get('format', 'unknown')
                found_count = len(results_list)

                # Always dump page state when the result looks suspicious so we
                # can fix selectors offline:
                #   - 0 results extracted (might be a real 0, or a selector miss)
                #   - text-fallback mode (strategies 1+2 missed)
                #   - found fewer than the page-reported expected_count
                #   - the only "doc number" extracted looks like a year span
                _suspicious = (
                    found_count == 0
                    or result_format == 'text'
                    or (expected_count and found_count < expected_count)
                    or any(
                        isinstance(r, dict)
                        and isinstance(r.get('document_number'), str)
                        and r.get('document_number', '').count('-') == 1
                        and len(r['document_number'].split('-')[-1]) == 4
                        for r in results_list
                    )
                )
                if _suspicious:
                    self._dump_search_page_state(
                        reason=f"found={found_count} expected={expected_count} format={result_format}",
                        js_data=js_data,
                        expected_count=expected_count,
                    )

                # Decision: use list results whenever we found any.
                # Detail page fallback (clicking into each result) is fragile on
                # jQuery Mobile SPAs — DOM changes on back-navigation break re-indexing.
                # It's better to have 6 of 7 results from the list than 1 of 7 from
                # detail pages. Only fall back when list extraction finds 0 results.
                use_list = found_count > 0

                if use_list:
                    if expected_count > 0 and found_count < expected_count:
                        print(f"  Extracted {found_count}/{expected_count} document(s) via JavaScript ({result_format} format)")
                    else:
                        print(f"  Extracted {found_count} document(s) via JavaScript ({result_format} format)")
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
                    # List extraction got too few results — fall back to detail pages
                    if found_count > 0:
                        print(f"  List view found only {found_count}/{expected_count} doc numbers in list")
                    else:
                        debug = js_data.get('debug', {})
                        print(f"  No YYYY-NNNNN doc numbers in list view "
                              f"(resultItems={debug.get('resultItems', 0)}, "
                              f"lists={debug.get('totalLists', 0)})")
                        page_text_dump = debug.get('pageText', '')
                        if page_text_dump:
                            print(f"  Page text:\n{page_text_dump[:500]}")

                    print(f"  Falling back to detail page extraction...")
                    documents = self._extract_results_via_detail_pages()

        except Exception as e:
            print(f"  Error extracting results: {e}")
            import traceback
            traceback.print_exc()

        # ----------------------------------------------------------------
        # Result-count cap detection
        # ----------------------------------------------------------------
        # Tyler shows a "result-count cap" message when too many docs match.
        # Decision matrix:
        #   - documents extracted AND no cap        -> return documents
        #   - documents extracted AND cap message   -> return documents + warn
        #   - no documents AND cap message          -> warn + dump + return []
        #                                              (avoid false-positive
        #                                               footer matches)
        try:
            cap_phrases = (
                "more documents than the maximum allowed",
                "more records than the maximum",
                "result limit",
                "too many results",
            )
            page_text_for_cap = ""
            try:
                page_text_for_cap = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                page_text_for_cap = ""
            page_text_lower = page_text_for_cap.lower()
            hit_phrase = next((p for p in cap_phrases if p in page_text_lower), None)
            if hit_phrase:
                # Build a short context snippet around the matched phrase
                idx = page_text_lower.find(hit_phrase)
                start = max(0, idx - 80)
                end = min(len(page_text_for_cap), idx + len(hit_phrase) + 120)
                snippet = page_text_for_cap[start:end].replace("\n", " ").strip()
                print(f"  [results-cap] Tyler returned a result-count cap — refine the date range. Page text snippet: {snippet}")
                if not documents:
                    try:
                        self._dump_search_page_state(
                            reason="results_cap",
                            js_data={"cap_phrase": hit_phrase, "snippet": snippet},
                            expected_count=0,
                        )
                    except Exception:
                        pass
                    return []
                # 2026-05-26 Orange FL fix: when the cap fires AND the only
                # "documents" extracted have empty doc_type + empty recording_date,
                # the listview the JS picked up is Tyler's Document-Types
                # aggregation panel (e.g. "Deed 1040158", "Mortgage 496385"), not
                # real search results. The aggregation counts get parsed as
                # YYYY-NNNNN by the dashed-number regex. Reject these.
                suspicious = [
                    d for d in documents
                    if not (d.document_type or "").strip()
                    and not (d.recording_date or "").strip()
                    and not (d.grantors or "").strip()
                    and not (d.grantees or "").strip()
                ]
                if suspicious and len(suspicious) == len(documents):
                    print(
                        f"  [results-cap] All {len(documents)} extracted 'documents' "
                        f"have empty metadata (likely Document-Types aggregation "
                        f"counts, not real records). Discarding and returning []."
                    )
                    return []
                # documents were extracted alongside the cap message — keep them
        except Exception as _cap_err:
            # Never let cap-detection break extraction
            print(f"  [results-cap] cap-detection error (non-fatal): {_cap_err}")

        # ------------------------------------------------------------
        # CAPTCHA-on-results guard
        # ------------------------------------------------------------
        # Tyler sometimes returns to the search form (with CAPTCHA visible)
        # after a submit that we thought succeeded. If we extracted 0 docs
        # AND the page still contains the recaptcha iframe AND there is no
        # explicit "no results" message, treat this as "we never got past
        # CAPTCHA" and raise a resumable checkpoint instead of returning
        # an empty list.
        try:
            if not documents and self.captcha_required:
                still_has_captcha = bool(
                    self.driver.find_elements(By.XPATH, self.selectors["recaptcha_frame"])
                )
                if still_has_captcha:
                    try:
                        page_text = (self.driver.find_element(By.TAG_NAME, "body").text or "").lower()
                    except Exception:
                        page_text = ""
                    explicit_no_results = any(
                        msg in page_text for msg in ("no records found", "0 records", "no results")
                    )
                    if not explicit_no_results:
                        message = (
                            f"{self.county_name} returned 0 docs but the CAPTCHA frame is still "
                            "present — search did not complete. Solve CAPTCHA and click Resume."
                        )
                        unit = getattr(self, "_current_search_unit", "initial")
                        try:
                            current_url = self.driver.current_url
                        except Exception:
                            current_url = None
                        session = checkpoint_sessions.create(
                            checkpoint_type="captcha",
                            county=self.county_name,
                            step="recorder_search_extract",
                            message=message,
                            resource=self,
                            details={
                                "captcha_type": self.captcha_type,
                                "url": current_url,
                                "search_unit": unit,
                                "phase_substep": "post_extract",
                                "manual_only": True,
                            },
                            timeout_seconds=self.manual_captcha_timeout_seconds,
                        )
                        raise CaptchaCheckpointRequired(
                            resume_token=session.resume_token,
                            county=self.county_name,
                            step="recorder_search_extract",
                            message=message,
                            details=session.public_payload()["details"],
                        )
        except CaptchaCheckpointRequired:
            raise
        except Exception as _captcha_guard_err:
            print(f"  [captcha-guard] non-fatal error: {_captcha_guard_err}")

        return documents

    def _find_results_list_js(self):
        """JavaScript snippet to find the correct results list.

        Uses priority-based selection:
        1. List containing "N total" counter (definitive results list)
        2. List with items containing dates and long text
        3. Fallback: list with most items
        Returns: { resultList, clickableItems[] }
        """
        return """
        function findResultsList(scope) {
            var allLists = scope.querySelectorAll(
                'ul.ss-listview, ul[data-role="listview"], ul.ui-listview'
            );

            var resultList = null;

            // Priority 1: List with a "N total" counter item
            for (var u = 0; u < allLists.length; u++) {
                var ul = allLists[u];
                if (ul.classList.contains('ss-utility-box')) continue;
                var items = ul.querySelectorAll('li');
                for (var i = 0; i < items.length; i++) {
                    var txt = (items[i].textContent || '').trim().toLowerCase();
                    if (txt.match(/^\\d+\\s*total/)) {
                        resultList = ul;
                        break;
                    }
                }
                if (resultList) break;
            }

            // Priority 2: List with items that have dates + long text
            if (!resultList) {
                for (var u = 0; u < allLists.length; u++) {
                    var ul = allLists[u];
                    if (ul.classList.contains('ss-utility-box')) continue;
                    var items = ul.querySelectorAll('li');
                    var dateCount = 0;
                    for (var i = 0; i < items.length; i++) {
                        var txt = (items[i].textContent || '').trim();
                        if (txt.length > 30 && txt.match(/\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}/)) dateCount++;
                    }
                    if (dateCount >= 2) { resultList = ul; break; }
                }
            }

            // Priority 3: Fallback — most items
            if (!resultList) {
                var maxItems = 0;
                for (var u = 0; u < allLists.length; u++) {
                    var ul = allLists[u];
                    if (ul.classList.contains('ss-utility-box')) continue;
                    var items = ul.querySelectorAll('li');
                    if (items.length > maxItems) { maxItems = items.length; resultList = ul; }
                }
            }

            if (!resultList) return null;

            // Filter to clickable result items (skip dividers, counters, empty)
            var clickable = [];
            var items = resultList.querySelectorAll('li');
            for (var i = 0; i < items.length; i++) {
                var li = items[i];
                var liText = (li.textContent || '').trim();
                if (liText.match(/^\\d+\\s*total/i) || liText.match(/^\\s*$/) ||
                    li.getAttribute('data-role') === 'list-divider' ||
                    li.classList.contains('ss-listview-internal')) {
                    continue;
                }
                clickable.push(li);
            }
            return { list: resultList, items: clickable };
        }
        """

    def _extract_results_via_detail_pages(self) -> List[DocumentRecord]:
        """
        Extract document records by clicking into each result's detail page.

        Uses priority-based list selection (finds list with "N total" counter)
        and clicks each item by index. After each detail page, navigates back
        and waits for the results list to reappear before clicking the next item.
        """
        documents = []
        seen = set()

        find_list_fn = self._find_results_list_js()

        # Step 1: Count clickable result items
        item_info = self.driver.execute_script(find_list_fn + """
            var scope = document.querySelector('.ui-page-active') || document.body;
            var found = findResultsList(scope);
            if (!found) return { count: 0, debug: 'No result list found' };

            var clickable = found.items;
            var debug = 'items=' + clickable.length;
            if (clickable.length > 0) {
                var first = clickable[0];
                var a = first.querySelector('a');
                var firstText = (first.textContent || '').replace(/\\s+/g, ' ').trim();
                debug += ' first=[' + firstText.substring(0, 80) + ']';
                debug += ' hasLink=' + !!a;
            }
            return { count: clickable.length, debug: debug };
        """)

        if not item_info or item_info.get('count', 0) == 0:
            debug_msg = item_info.get('debug', 'N/A') if item_info else 'script returned None'
            print(f"  No clickable result items found ({debug_msg})")
            return documents

        total = item_info['count']
        print(f"  Clicking into {total} result(s) to extract doc numbers...")
        print(f"    Debug: {item_info.get('debug', '')}")
        results_url = self.driver.current_url

        for idx in range(total):
            try:
                # Re-find items on the active page and click the idx-th one
                click_result = self.driver.execute_script(find_list_fn + """
                    var scope = document.querySelector('.ui-page-active') || document.body;
                    var found = findResultsList(scope);
                    if (!found) return null;

                    var targetIdx = arguments[0];
                    if (targetIdx >= found.items.length) return null;

                    var target = found.items[targetIdx];
                    var a = target.querySelector('a');
                    var clickEl = a || target;
                    clickEl.scrollIntoView({block: 'center'});
                    clickEl.click();
                    return (target.textContent || '').replace(/\\s+/g, ' ').substring(0, 200).trim();
                """, idx)

                if click_result is None:
                    print(f"    [{idx+1}/{total}] Item not found at index {idx}, trying to recover...")
                    # Try to navigate back to results URL and continue
                    try:
                        self.driver.get(results_url)
                        time.sleep(3)
                    except Exception:
                        pass
                    continue

                # Wait for detail page to load (jQuery Mobile AJAX transition)
                time.sleep(3)

                # Extract document details from the detail page
                detail = self.driver.execute_script("""
                    var scope = document.querySelector('.ui-page-active') || document.body;
                    var text = scope.innerText || '';
                    var result = {
                        document_number: '',
                        document_type: '',
                        recording_date: '',
                        grantors: '',
                        grantees: '',
                        grantor_grantees: '',
                        pages: ''
                    };

                    // Approach A: Parse labeled fields from page text
                    var lines = text.split('\\n');
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line) continue;
                        var lower = line.toLowerCase();

                        if (!result.document_number &&
                            (lower.startsWith('instrument') || lower.startsWith('doc #') ||
                             lower.startsWith('document #') || lower.startsWith('recording #') ||
                             lower.startsWith('doc. #') || lower.startsWith('instrument #') ||
                             lower.startsWith('document number') || lower.startsWith('recording number'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            if (value) result.document_number = value;
                        }

                        if (!result.recording_date &&
                            (lower.startsWith('recording date') || lower.startsWith('rec date') ||
                             lower.startsWith('recorded') || lower.startsWith('date recorded'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            var dm = (value || line).match(/(\\d{1,2}\\/\\d{1,2}\\/\\d{2,4})/);
                            if (dm) result.recording_date = dm[1];
                        }

                        if (!result.document_type &&
                            (lower.startsWith('doc type') || lower.startsWith('document type') ||
                             lower.startsWith('type:'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            if (value) result.document_type = value;
                        }

                        if (!result.grantors &&
                            (lower.startsWith('grantor') || lower.startsWith('direct name'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            if (value) result.grantors = value;
                        }

                        if (!result.grantees &&
                            (lower.startsWith('grantee') || lower.startsWith('reverse name'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            if (value) result.grantees = value;
                        }

                        if (!result.pages &&
                            (lower.startsWith('pages') || lower.startsWith('page count') ||
                             lower.startsWith('# of pages'))) {
                            var colonIdx = line.indexOf(':');
                            var value = colonIdx >= 0 ? line.substring(colonIdx + 1).trim() : '';
                            if (!value && i + 1 < lines.length) value = lines[i + 1].trim();
                            if (value) result.pages = value;
                        }
                    }

                    // Approach B: Structured key-value pairs (dl/dt/dd)
                    if (!result.document_number) {
                        var dtElements = scope.querySelectorAll(
                            'dt, th, .label, .field-label, [class*="label"]'
                        );
                        for (var d = 0; d < dtElements.length; d++) {
                            var dt = dtElements[d];
                            var dtText = (dt.textContent || '').trim().toLowerCase();
                            if (dtText.includes('instrument') || dtText.includes('doc #') ||
                                dtText.includes('document #') || dtText.includes('recording #') ||
                                dtText.includes('document number')) {
                                var dd = dt.nextElementSibling;
                                if (dd) {
                                    var ddText = dd.textContent.trim();
                                    if (ddText) { result.document_number = ddText; break; }
                                }
                            }
                        }
                    }

                    // Approach C: Doc number from page text (dashed or undashed)
                    if (!result.document_number) {
                        var dashed = text.match(/(\\d{4}-\\d+)/);
                        if (dashed) {
                            result.document_number = dashed[1];
                        } else {
                            var undashed = text.match(/(?:^|[^\\d])(\\d{7,13})(?=[^\\d]|$)/);
                            if (undashed) {
                                var num = undashed[1];
                                if (num.length === 13) {
                                    var prefix = num.substring(0, 2);
                                    if (prefix !== '19' && prefix !== '20') num = null;
                                }
                                if (num) {
                                    result.document_number = num.substring(0, 4) + '-' + num.substring(4);
                                }
                            }
                        }
                    }

                    // Approach D: Tyler searchResult-value elements
                    if (!result.document_number) {
                        var valueEls = scope.querySelectorAll(
                            '[class*="searchResult-value"], [class*="ss-searchResult"]'
                        );
                        for (var v = 0; v < valueEls.length; v++) {
                            var valText = valueEls[v].textContent.trim();
                            var lower = valText.toLowerCase();
                            if (lower.includes('instrument') || lower.includes('doc #') ||
                                lower.includes('recording #')) {
                                var numMatch = valText.match(/(\\d{4}-\\d{4,}|\\d{7,})/);
                                if (numMatch) { result.document_number = numMatch[1]; break; }
                            }
                        }
                    }

                    // Debug: page text if no doc number found
                    if (!result.document_number) {
                        result._debug_text = text.substring(0, 500);
                    }

                    return result;
                """)

                if detail:
                    doc_num = detail.get('document_number', '').strip()
                    if doc_num and doc_num not in seen:
                        seen.add(doc_num)
                        doc = DocumentRecord(
                            document_number=doc_num,
                            grantors=detail.get('grantors', ''),
                            grantees=detail.get('grantees', ''),
                            grantor_grantees=detail.get('grantor_grantees', ''),
                            document_type=detail.get('document_type', ''),
                            recording_date=detail.get('recording_date', ''),
                            pages=detail.get('pages', '')
                        )
                        documents.append(doc)
                        print(f"    [{idx+1}/{total}] #{doc_num} - {doc.document_type}")
                    else:
                        debug_text = detail.get('_debug_text', '')
                        if debug_text and not doc_num:
                            print(f"    [{idx+1}/{total}] No doc# found. Page: {debug_text[:200]}...")
                        elif doc_num:
                            print(f"    [{idx+1}/{total}] Duplicate: #{doc_num}")

            except Exception as e:
                print(f"    [{idx+1}/{total}] Error: {e}")

            # Navigate back to results page and wait for results list to reappear
            try:
                self.driver.back()
                time.sleep(2)
                # Wait for the results list to be available again
                for wait_attempt in range(5):
                    has_results = self.driver.execute_script("""
                        var scope = document.querySelector('.ui-page-active') || document.body;
                        var text = (scope.innerText || '').toLowerCase();
                        return text.includes('total record') || text.includes('total result') ||
                               text.includes('record(s)') || text.includes('total');
                    """)
                    if has_results:
                        break
                    time.sleep(1)
            except Exception:
                try:
                    self.driver.get(results_url)
                    time.sleep(3)
                except Exception:
                    pass

        print(f"  Extracted {len(documents)} document(s) from detail pages")
        return documents

    def set_partial_match(self, enabled: bool):
        """
        Set partial match mode for name searches.

        Note: Tyler Technologies platform typically uses partial matching by default.
        This method is provided for compatibility with the workflow interface.

        Args:
            enabled: Whether to enable partial matching
        """
        self.partial_match = enabled
        # Tyler platforms generally use partial matching by default
        # No UI toggle needed in most cases
        pass

    def return_to_search(self):
        """Navigate back to search form for another search.

        Tries multiple strategies:
        1. Click Back/New Search link on the active page
        2. Tyler DOCSEARCH "New Search" link via JS on active page
        3. Browser back button (works for jQuery Mobile SPA transitions)
        4. Navigate to resolved search URL
        5. Re-run full navigation from disclaimer
        After each strategy, verifies the name field is present.
        """
        def _verify_search_form():
            """Check if the active page has a name input field."""
            time.sleep(2)
            try:
                return self.driver.execute_script("""
                    var scope = document.querySelector('.ui-page-active') || document.body;
                    var inputs = scope.querySelectorAll(
                        'input[id*="BothNames"], input[id*="LastName"], ' +
                        'input[id*="Name"], input[type="search"]'
                    );
                    for (var i = 0; i < inputs.length; i++) {
                        if (inputs[i].offsetParent !== null) return true;
                    }
                    return false;
                """)
            except Exception:
                return False

        def _dismiss_keepalive_modal():
            """Bug #14 (Riverside): a session-keepalive modal-overlay
            intercepts clicks on the back link. Dismiss any visible modal
            first via JS to avoid ElementClickInterceptedException.
            """
            try:
                self.driver.execute_script(
                    """
                    var clicked = false;
                    // Common Tyler session-keepalive 'Yes - Continue' buttons
                    var candidates = document.querySelectorAll(
                        "button[id*='session-continue'], " +
                        "button[id*='SelfService'][id*='continue'], " +
                        "button[id*='Continue'], a[id*='Continue'], " +
                        ".modal-overlay-button, .modal .btn-primary, " +
                        ".modal button.close, .modal .close, " +
                        "button[data-dismiss='modal']"
                    );
                    for (var i = 0; i < candidates.length; i++) {
                        var el = candidates[i];
                        if (el && el.offsetParent !== null) {
                            try { el.click(); clicked = true; break; } catch(e){}
                        }
                    }
                    // Last resort: force-hide any visible modal-overlay so
                    // subsequent clicks aren't intercepted.
                    var overlays = document.querySelectorAll(
                        '.modal-overlay, .ui-popup-screen, .modal-backdrop'
                    );
                    for (var j = 0; j < overlays.length; j++) {
                        try {
                            overlays[j].style.display = 'none';
                            overlays[j].style.visibility = 'hidden';
                            overlays[j].style.pointerEvents = 'none';
                        } catch(e){}
                    }
                    return clicked;
                    """
                )
                time.sleep(0.5)
            except Exception:
                pass

        # Strategy 1: Standard back link (XPath)
        try:
            back_link = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, self.selectors["back_to_search"]))
            )
            # Dismiss any blocking modal-overlay (Riverside keepalive popup)
            _dismiss_keepalive_modal()
            try:
                back_link.click()
            except ElementClickInterceptedException:
                # Modal still in the way — fall back to JS click which ignores
                # overlay z-index hit-testing.
                print("  Back-link native click intercepted; using JS click")
                self.driver.execute_script("arguments[0].click();", back_link)
            if _verify_search_form():
                print("  Returned to search form")
                return
        except TimeoutException:
            pass

        # Strategy 2: Tyler DOCSEARCH "New Search" link via JS on active page
        try:
            clicked = self.driver.execute_script("""
                var scope = document.querySelector('.ui-page-active') || document.body;
                var links = scope.querySelectorAll('a, button');
                for (var i = 0; i < links.length; i++) {
                    var text = (links[i].textContent || '').trim().toLowerCase();
                    if (text === 'new search' || text === 'back to search' ||
                        text === 'modify search' || text === 'search again') {
                        links[i].click();
                        return true;
                    }
                }
                return false;
            """)
            if clicked:
                if _verify_search_form():
                    print("  Returned to search form (JS click)")
                    return
        except Exception:
            pass

        # Strategy 3: Browser back button (jQuery Mobile SPA transition)
        try:
            self.driver.back()
            if _verify_search_form():
                print("  Returned to search form (browser back)")
                return
        except Exception:
            pass

        # Strategy 4: Navigate to the resolved search URL
        if self._resolved_search_url:
            print(f"  Navigating back to: {self._resolved_search_url}")
            self.driver.get(self._resolved_search_url)
            if _verify_search_form():
                print("  Returned to search form (direct URL)")
                return
            else:
                print("  Search form not found at resolved URL, re-navigating...")

        # Strategy 5: Re-run full navigation from scratch
        print("  Re-running full navigation to search page")
        self._disclaimer_accepted = False
        self.navigate_to_search()
        print("  Returned to search form (full re-navigation)")
