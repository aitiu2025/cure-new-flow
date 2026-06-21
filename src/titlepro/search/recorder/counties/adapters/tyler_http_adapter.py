"""
Tyler Technologies "Self-Service" HTTP-First Adapter (Phase 1 CURE restructure).

A pure-Python replacement for ``tyler_adapter.py`` (which is Selenium-based).
Targets the modern Tyler Self-Service portal pattern used by Orange County FL
(`selfservice.or.occompt.com/ssweb/`) and the 14 reCAPTCHA-enabled CA Tyler
tenants once each county's sitekey is added to its config JSON.

Per Tony Roveda's 2026-05-22 directives, Phase 1 search MUST be 100% HTTP — no
Selenium / Playwright / undetected-chromedriver anywhere in the search path.
2Captcha API calls are explicitly allowed (Tony directive #1 + RecaptchaSolver
already used elsewhere): it's an external HTTP API, not browser automation.

End-to-end portal contract (verified live 2026-05-21 against Orange FL)
-----------------------------------------------------------------------
1. GET  ``{base_url}/user/disclaimer``                  → bootstraps JSESSIONID
2. POST ``https://2captcha.com/in.php``                 → submit reCAPTCHA task
3. Poll ``https://2captcha.com/res.php``                → 30-130 sec to a token
4. POST ``{base_url}/user/disclaimer``                  → body: g-recaptcha-response=<token>
                                                          → body "true" unlocks session
5. GET  ``{base_url}/search/{search_path}``             → warms the search form (no longer 302's to disclaimer)
6. POST ``{base_url}/searchPost/{search_path}``         → body: form fields; **headers must include
                                                          Accept: application/json AND X-Requested-With: XMLHttpRequest**
                                                          → returns JSON: {validationMessages, totalPages, currentPage}
7. GET  ``{base_url}/searchResults/{search_path}?page=N`` → returns HTML grid fragment with ss-search-row LIs
8. GET  ``{base_url}/document/{doc_id}?search={search_path}`` → full document detail page

reCAPTCHA token lifetime
------------------------
The disclaimer-accept call sets a per-session flag on the server. Once accepted,
the JSESSIONID alone authorizes all subsequent search/result pages — the
recaptcha token is NOT re-required per search. We therefore solve ONCE per
session and cache that the session is warmed.

State independence
------------------
Every ``perform_search()`` call builds a fresh form payload — no state is
carried between calls. This is the explicit anti-pattern Tony called out in
the Broward review (Kendo/bfcache races in the legacy browser adapter).

Failure semantics
-----------------
* If 2Captcha can't be reached or the token is rejected, ``warm_session()``
  raises ``RuntimeError`` and the orchestrator marks the search as failed.
* If the JSON response includes ``validationMessages``, the adapter surfaces
  the message via ``self.last_failure`` so the pipeline can branch on it
  (e.g., chunk a >5-year date range).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# Browser fingerprint that consistently passes Tyler's session and TLS checks.
DEFAULT_IMPERSONATE = "chrome120"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}

# 2Captcha endpoints (also used by RecaptchaSolver but inlined here so the
# adapter is self-contained and easier to unit-test with mocks).
_2CAPTCHA_SUBMIT = "https://2captcha.com/in.php"
_2CAPTCHA_RESULT = "https://2captcha.com/res.php"


class TylerHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for Tyler Self-Service portals.

    Subclass of ``BaseRecorderSearch`` so the registry / factory plumbing is
    unchanged. Browser-only ABC methods (``setup_driver``, ``navigate_to_search``,
    ``return_to_search``) collapse to no-ops.
    """

    # --------------------------------------------------------------------- init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Unknown Tyler")
        # base_url in legacy config points at the disclaimer URL; we want the
        # portal root so we can build relative URLs cleanly.
        raw_base = config.get("base_url", "")
        if "/user/disclaimer" in raw_base:
            raw_base = raw_base.split("/user/disclaimer")[0]
        if "/search/" in raw_base:
            raw_base = raw_base.split("/search/")[0]
        # If the legacy config gave us ``…/ssweb`` keep it; otherwise normalize.
        self._base_url = raw_base.rstrip("/") + "/"

        # Standard Tyler endpoints.
        self._disclaimer_url = config.get(
            "disclaimer_url", urljoin(self._base_url, "user/disclaimer")
        )
        # Search URL must contain the DOCSEARCH path component. We derive the
        # path so we can build searchPost / searchResults URLs from it.
        self._search_url = config.get(
            "search_url", urljoin(self._base_url, "search/DOCSEARCH2950S1")
        )
        m = re.search(r"/search/([A-Za-z0-9_]+)", self._search_url)
        self._search_path = m.group(1) if m else "DOCSEARCH2950S1"

        self._search_post_url = config.get(
            "search_post_url",
            urljoin(self._base_url, f"searchPost/{self._search_path}"),
        )
        self._search_results_url = config.get(
            "search_results_url",
            urljoin(self._base_url, f"searchResults/{self._search_path}"),
        )
        self._document_detail_base = config.get(
            "document_detail_base", urljoin(self._base_url, "document/")
        )
        # PDF URL is scraped from the detail page's `selfservice.document.pdfJsUrl`
        # JS assignment — see `download_pdf()`. No per-county pattern override is
        # consulted by the current code; if a tenant hides that JS variable we
        # will need to add a config-driven fallback here.

        # Form-field map. Override per tenant in JSON if Tyler renames any of
        # these (Orange FL uses the default names — verified 2026-05-21).
        ff = config.get("http_form_fields", {})
        self._field_start = ff.get("date_from", "field_RecordingDateID_DOT_StartDate")
        self._field_end = ff.get("date_to", "field_RecordingDateID_DOT_EndDate")
        self._field_doc_id = ff.get("document_id", "field_DocumentID")
        self._field_both = ff.get("both_names", "field_BothNamesID")
        self._field_grantor = ff.get("grantor", "field_GrantorID")
        self._field_grantee = ff.get("grantee", "field_GranteeID")
        self._field_book = ff.get("book", "field_BookPageID_DOT_Book")
        self._field_page = ff.get("page", "field_BookPageID_DOT_Page")
        self._field_doctype = ff.get("doc_types", "field_selfservice_documentTypes")

        # Combined-name behaviour. Orange FL has ``combined_name_search: true``
        # (single ``field_BothNamesID`` field). Most CA Tyler tenants have it too.
        self._combined_name_search = bool(config.get("combined_name_search", True))

        # Party-type vocabulary. The combined-name field has no party-type filter
        # baked in (the search returns docs where the name appears as either),
        # so we post-filter on the result rows when the caller asks for a
        # specific role.
        self.party_type_map = config.get(
            "party_type_map",
            {
                "Grantor/Grantee": "Both",
                "Both": "Both",
                "All": "Both",
                "Grantor": "Grantor",
                "Grantee": "Grantee",
            },
        )
        self.supported_party_types = ["Both", "Grantor", "Grantee"]

        # Doc-number heuristic — Tyler's docs are 10-12 digit integers.
        pat = config.get("http_doc_number_pattern", r"^\d{8,14}$")
        self._doc_number_re = re.compile(pat)

        # CAPTCHA config.
        self._captcha_required = bool(config.get("captcha_required", True))
        self._recaptcha_sitekey: Optional[str] = config.get("recaptcha_sitekey")
        # Sitekey can also be auto-scraped from the disclaimer page (the
        # ``data-sitekey="…"`` attribute). We try the configured value first
        # but fall back to scrape if the live page rotates it.
        self._recaptcha_pageurl = config.get(
            "recaptcha_pageurl", self._disclaimer_url
        )
        # Max time to wait for 2Captcha (seconds).
        self._captcha_timeout = int(config.get("captcha_timeout_seconds", 180))
        # API key — read from env (the same env var the legacy solver uses).
        self._captcha_api_key: Optional[str] = os.environ.get("CAPTCHA_API_KEY")
        # An optional pre-injected captcha solver (for tests / DI).
        self._captcha_solver = None
        # Token cache (defensive; Tyler currently only needs the token once
        # per session at the disclaimer step).
        self._cached_token: Optional[str] = None
        self._cached_token_minted_at: float = 0.0
        self._token_max_age = int(config.get("recaptcha_token_max_age_seconds", 110))

        # HTTP session.
        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)
        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # ABC compliance: parent expects self.driver, but we never use it.
        self.driver = None

        # Page-range — Tyler caps date ranges at 5 years on most tenants.
        self._max_date_range_years = int(config.get("max_date_range_years", 5))

        # Misc.
        self._results_per_page = int(config.get("http_results_per_page", 100))

    # --------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # ----------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):  # pragma: no cover - trivial
        return None

    def navigate_to_search(self):  # pragma: no cover - trivial
        return None

    def return_to_search(self):  # pragma: no cover - trivial
        return None

    # ---------------------------------------------------- captcha solver wiring

    def set_captcha_solver(self, solver) -> None:
        """Inject a CaptchaSolverBase instance (DI for tests / registry wiring)."""
        self._captcha_solver = solver

    # ---------------------------------------------------- recaptcha (HTTP API)

    def _scrape_sitekey(self, html: str) -> Optional[str]:
        """Return the first ``data-sitekey="..."`` value in ``html``, or None."""
        m = re.search(r'data-sitekey="([^"]+)"', html)
        return m.group(1) if m else None

    def _solve_recaptcha(self, page_url: Optional[str] = None) -> Optional[str]:
        """Solve the disclaimer-page reCAPTCHA via 2Captcha.

        Returns the ``g-recaptcha-response`` token, or None on failure.
        Caches the token for ``_token_max_age`` seconds. Tyler's server
        actually only needs the token at the disclaimer-accept step, but we
        keep a TTL in case a tenant variant re-verifies on POST.
        """
        # Reuse cached token while fresh.
        if (
            self._cached_token
            and (time.time() - self._cached_token_minted_at) < self._token_max_age
        ):
            return self._cached_token

        # Strategy A: caller provided a CaptchaSolverBase (used by tests + the
        # registry-wired solver). Calls ``solve_recaptcha_v2(sitekey, page_url)``.
        sitekey = self._recaptcha_sitekey
        if not sitekey:
            # Try to scrape from a fresh disclaimer GET.
            try:
                landing = self.session.get(self._disclaimer_url, timeout=30)
                sitekey = self._scrape_sitekey(landing.text)
            except Exception as exc:
                print(f"  [captcha] sitekey scrape failed: {exc}")
                self.last_failure = "captcha_sitekey_missing"
                return None
        if not sitekey:
            print("  [captcha] no sitekey configured and could not scrape one")
            self.last_failure = "captcha_sitekey_missing"
            return None

        page_url = page_url or self._recaptcha_pageurl

        if self._captcha_solver is not None:
            token = self._captcha_solver.solve_recaptcha_v2(sitekey, page_url)
            if token:
                self._cached_token = token
                self._cached_token_minted_at = time.time()
            else:
                self.last_failure = "captcha_solver_failed"
            return token

        # Strategy B: inline 2Captcha API call (when no solver injected).
        if not self._captcha_api_key:
            print("  [captcha] CAPTCHA_API_KEY not set — cannot solve via 2Captcha")
            self.last_failure = "captcha_api_key_missing"
            return None

        try:
            import requests as _vanilla_requests  # local import — keeps test
            # isolation clean (the requests module never touches the Tyler
            # session — it just talks to 2Captcha).

            sub = _vanilla_requests.post(
                _2CAPTCHA_SUBMIT,
                data={
                    "key": self._captcha_api_key,
                    "method": "userrecaptcha",
                    "googlekey": sitekey,
                    "pageurl": page_url,
                    "json": 1,
                },
                timeout=30,
            )
            js = sub.json()
            if js.get("status") != 1:
                print(f"  [captcha] 2Captcha submit error: {js}")
                self.last_failure = "captcha_submit_failed"
                return None
            task_id = js["request"]
            print(f"  [captcha] 2Captcha task_id={task_id}")

            t0 = time.time()
            while (time.time() - t0) < self._captcha_timeout:
                time.sleep(5)
                pr = _vanilla_requests.get(
                    _2CAPTCHA_RESULT,
                    params={
                        "key": self._captcha_api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1,
                    },
                    timeout=30,
                )
                j = pr.json()
                if j.get("status") == 1:
                    token = j["request"]
                    print(f"  [captcha] solved in {time.time()-t0:.0f}s")
                    self._cached_token = token
                    self._cached_token_minted_at = time.time()
                    return token
                if j.get("request") != "CAPCHA_NOT_READY":
                    print(f"  [captcha] 2Captcha result error: {j}")
                    self.last_failure = "captcha_solve_failed"
                    return None
            print("  [captcha] 2Captcha solve timed out")
            self.last_failure = "captcha_solve_timeout"
            return None
        except Exception as exc:
            print(f"  [captcha] 2Captcha API exception: {exc}")
            self.last_failure = f"captcha_exception:{exc}"
            return None

    # ----------------------------------------------------- session cookie repair

    def _restore_disclaimer_cookie(self) -> None:
        """Force the ``disclaimerAccepted`` cookie back to ``true`` in the
        local jar.

        Tyler's server emits ``Set-Cookie: disclaimerAccepted=false`` on most
        state-changing endpoints (searchPost, document GET, PDF GET) even
        when the request succeeded. The next request that depends on a warm
        session — typically ``searchResults`` or ``document-image-pdfjs`` —
        will then be served the landing/disclaimer page instead of the
        expected content. Calling this method after every state-changing
        request keeps the local cookie jar in the state the server expects
        for *reads*. The server-side disclaimer-accept flag (keyed by
        JSESSIONID) is independent of this cookie and remains valid for the
        whole session, so re-asserting the local cookie is safe.

        Only acts if the cookie is currently ``false``; no-op otherwise.
        """
        try:
            jar = self.session.cookies
            # curl_cffi's session.cookies behaves like requests.cookies — has
            # .get() and .set(). The domain/path must match the original
            # Set-Cookie or the GET won't include it.
            current = None
            for c in jar.jar:
                if c.name == "disclaimerAccepted":
                    current = c.value
                    break
            if current == "true":
                return
            # Derive domain/path from the disclaimer URL so this works for
            # any Tyler tenant (orange.occompt.com, tylerhost.net, etc.).
            from urllib.parse import urlparse
            parsed = urlparse(self._disclaimer_url)
            domain = parsed.netloc
            # Tyler always serves under /ssweb on Orange FL; default to that
            # but fall back to a path that matches the search URL prefix if
            # ssweb isn't present.
            path = "/ssweb" if "/ssweb" in (parsed.path or "") else "/"
            jar.set(
                "disclaimerAccepted",
                "true",
                domain=domain,
                path=path,
            )
        except Exception:
            # Cookie restoration is best-effort; don't block the request flow.
            pass

    # ------------------------------------------------------- session warm-up

    def warm_session(self) -> bool:
        """Bootstrap the session: load disclaimer, solve reCAPTCHA, accept.

        Returns True on success. Sets ``self.last_failure`` and returns False
        on any failure.
        """
        if self._session_warmed:
            return True

        # 1. GET disclaimer landing (mints JSESSIONID, scrapes sitekey if needed).
        try:
            landing = self.session.get(self._disclaimer_url, timeout=30)
        except Exception as exc:
            print(f"  [warm_session] landing GET failed: {exc}")
            self.last_failure = "landing_get_failed"
            return False
        if landing.status_code != 200:
            print(f"  [warm_session] landing returned {landing.status_code}")
            self.last_failure = f"landing_http_{landing.status_code}"
            return False

        # Auto-scrape sitekey if not pre-configured.
        if not self._recaptcha_sitekey:
            scraped = self._scrape_sitekey(landing.text)
            if scraped:
                self._recaptcha_sitekey = scraped
                print(f"  [warm_session] scraped recaptcha sitekey: {scraped[:20]}...")

        # 2. Solve reCAPTCHA. If CAPTCHA isn't required (e.g., a Tyler tenant
        # without it), skip this step.
        token = None
        if self._captcha_required:
            token = self._solve_recaptcha(page_url=self._disclaimer_url)
            if not token:
                # last_failure already set by _solve_recaptcha.
                return False

        # 3. POST the disclaimer-accept (with token if captcha was required).
        try:
            data = {}
            if token:
                data["g-recaptcha-response"] = token
            accept = self.session.post(
                self._disclaimer_url,
                data=data,
                timeout=30,
                headers={"Referer": self._disclaimer_url},
            )
        except Exception as exc:
            print(f"  [warm_session] disclaimer POST failed: {exc}")
            self.last_failure = "disclaimer_post_failed"
            return False

        # Tyler returns "true" (literal text) on success.
        if accept.status_code != 200 or "true" not in (accept.text or "").lower():
            print(
                f"  [warm_session] disclaimer-accept rejected: "
                f"{accept.status_code} body={accept.text[:120]!r}"
            )
            self.last_failure = "disclaimer_rejected"
            return False

        # 4. Verify search route is now accessible (no 302 to disclaimer).
        try:
            verify = self.session.get(
                self._search_url, timeout=30, allow_redirects=False
            )
        except Exception as exc:
            print(f"  [warm_session] verify GET failed: {exc}")
            self.last_failure = "verify_get_failed"
            return False
        if verify.status_code == 302 and "disclaimer" in (
            verify.headers.get("Location", "")
        ).lower():
            print(f"  [warm_session] session still 302's to disclaimer — accept failed")
            self.last_failure = "session_not_warmed"
            return False

        # 4a. CRITICAL: the verify GET above (and EVERY authenticated GET on a
        # Tyler tenant) emits ``Set-Cookie: disclaimerAccepted=false``. The
        # very first searchPost after warm-up would otherwise see a "cold"
        # cookie and serve HTML instead of JSON. Force the cookie back to
        # ``true`` to keep the first search aligned with subsequent ones.
        self._restore_disclaimer_cookie()

        self._session_warmed = True
        return True

    # ------------------------------------------------------ search

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search.

        State-independent: every call builds a fresh form payload and submits
        it. The recaptcha token is reused across calls (warm_session sets it
        once per process).

        Returns a list of DocumentRecord. Optionally filters by ``party_type``
        post-hoc (Tyler's combined-name field doesn't support a server-side
        party-type filter).
        """
        if not self._session_warmed and not self.warm_session():
            print(f"  [perform_search] session not warmed; last_failure={self.last_failure}")
            return []

        # Map party-type to Tyler vocab + clamp to supported set.
        mapped_party = self.party_type_map.get(party_type, party_type)
        if mapped_party not in self.supported_party_types:
            mapped_party = "Both"

        # Build form payload. Tyler is picky about order — the form's
        # serializeArray() emits fields in DOM order, so we replicate that.
        df = date_from or self.start_date
        dt = date_to or self.end_date

        payload: List = []
        payload.append((self._field_start, df))
        payload.append((self._field_end, dt))
        payload.append((self._field_doc_id, ""))

        if self._combined_name_search:
            # Single combined-name field; party-type filtering happens client-side.
            payload.append((self._field_both, name))
            payload.append((self._field_grantor, ""))
            payload.append((self._field_grantee, ""))
        else:
            # Older Tyler variant — separate Grantor/Grantee fields.
            payload.append((self._field_both, ""))
            if mapped_party in ("Both", "Grantor"):
                payload.append((self._field_grantor, name))
            else:
                payload.append((self._field_grantor, ""))
            if mapped_party in ("Both", "Grantee"):
                payload.append((self._field_grantee, name))
            else:
                payload.append((self._field_grantee, ""))

        payload.append((self._field_book, ""))
        payload.append((self._field_page, ""))
        payload.append((self._field_doctype, doc_type or ""))

        ajax_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": self._search_url,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self._base_url.rstrip("/"),
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        # 1. POST searchPost — Tyler stores the search on the session.
        try:
            sp = self.session.post(
                self._search_post_url,
                data=payload,
                headers=ajax_headers,
                timeout=60,
            )
        except Exception as exc:
            print(f"  [perform_search] searchPost exception: {exc}")
            self.last_failure = "search_post_exception"
            return []

        # 1a. CRITICAL: Tyler's `searchPost` response sets a `Set-Cookie:
        # disclaimerAccepted=false` header even on success. This invalidates
        # the subsequent `searchResults` GET — Tyler will serve the landing
        # page (with no result rows) instead of the result grid. Force the
        # cookie back to `true` immediately so downstream GETs see a "warm"
        # session. (Verified live against Orange FL 2026-05-26: without this
        # restoration, searchResults returns 0 ss-search-row elements; with
        # it, returns the full grid.) The server-side accept flag persists
        # in the JSESSIONID regardless of cookie state, so this is safe.
        self._restore_disclaimer_cookie()

        if sp.status_code != 200:
            print(f"  [perform_search] searchPost HTTP {sp.status_code}")
            self.last_failure = f"search_post_http_{sp.status_code}"
            return []

        # Parse JSON response.
        try:
            js = sp.json()
        except Exception:
            print(f"  [perform_search] searchPost non-JSON response: {sp.text[:200]!r}")
            self.last_failure = "search_post_not_json"
            return []

        validation = js.get("validationMessages") or {}
        if validation:
            print(f"  [perform_search] validation errors: {validation}")
            # Surface the first message for the caller.
            first_key = next(iter(validation))
            self.last_failure = f"validation:{first_key}:{validation[first_key]}"
            return []

        total_pages = int(js.get("totalPages", 1) or 1)

        # 2. GET results page(s).
        documents: List[DocumentRecord] = []
        for page in range(1, total_pages + 1):
            try:
                sr = self.session.get(
                    f"{self._search_results_url}?page={page}",
                    headers={
                        "Accept": "text/html, */*; q=0.01",
                        "Referer": self._search_url,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=60,
                )
            except Exception as exc:
                print(f"  [perform_search] searchResults GET exception: {exc}")
                break
            # Defensive: re-assert cookie after every server interaction.
            self._restore_disclaimer_cookie()
            if sr.status_code != 200:
                print(f"  [perform_search] searchResults HTTP {sr.status_code}")
                break
            documents.extend(self.extract_results(sr.text))

        # Post-filter on party-type when caller asks for a specific role and
        # we used combined-name search (Tyler's API doesn't filter by role).
        if self._combined_name_search and mapped_party in ("Grantor", "Grantee"):
            filtered = []
            search_name_norm = self._normalize_name(name)
            for d in documents:
                role_field = d.grantors if mapped_party == "Grantor" else d.grantees
                if self._name_in_field(search_name_norm, role_field):
                    filtered.append(d)
            documents = filtered

        return documents

    # ----------------------------------------------------------- pull_detail

    def pull_detail(self, doc_id: str) -> Dict:
        """Fetch the document-detail page for ``doc_id`` (Tyler internal id).

        Returns a dict with: document_number, recording_date, doc_type,
        indexed_apn, book_page, parties, raw_html_snippet. APN is typically
        absent on Orange FL — must be OCR'd from the deed image per Tony
        directive #2.
        """
        if not self._session_warmed and not self.warm_session():
            return {"document_id": doc_id, "error": "session_not_warmed"}

        url = f"{self._document_detail_base}{doc_id}?search={self._search_path}"
        try:
            resp = self.session.get(
                url,
                headers={"Referer": self._search_url},
                timeout=60,
            )
        except Exception as exc:
            return {"document_id": doc_id, "error": f"network: {exc}"}
        if resp.status_code != 200:
            return {"document_id": doc_id, "error": f"HTTP {resp.status_code}"}
        return self._parse_detail_html(resp.text, doc_id)

    @staticmethod
    def _parse_detail_html(html: str, doc_id: str) -> Dict:
        """Parse Tyler's document/{doc_id} detail page."""
        soup = BeautifulSoup(html, "lxml")
        # Tyler renders detail as a sequence of labeled blocks. We look for
        # specific labels in the body text and pull the adjacent value.

        def field_after(label: str) -> str:
            label_re = re.compile(re.escape(label) + r"\s*:?\s*", re.IGNORECASE)
            for el in soup.find_all(["dt", "th", "label", "h2", "h3", "strong", "b"]):
                txt = (el.get_text(strip=True) or "")
                if label_re.match(txt):
                    nxt = el.find_next(["dd", "td", "span", "p", "div"])
                    if nxt:
                        return nxt.get_text(strip=True)
            # Fallback: text scan
            body_text = soup.get_text(" ", strip=True)
            m = re.search(re.escape(label) + r":\s*([A-Za-z0-9/\-\s,]+?)(?=\s{2,}|$)", body_text)
            return m.group(1).strip() if m else ""

        doc_number = field_after("Document #") or field_after("Doc #")
        recording_date = field_after("Recording Date") or field_after("Date Recorded")
        doc_type = field_after("Document Type")

        # APN — Orange FL doesn't index it; some CA Tyler tenants do.
        indexed_apn = (
            field_after("APN")
            or field_after("Parcel ID")
            or field_after("Parcel Number")
            or field_after("Property ID")
        )

        book_page = field_after("Book Page") or field_after("Book/Page")

        # Parties — Tyler shows separate Grantor / Grantee blocks with name lists.
        parties: List[Dict[str, str]] = []
        for role in ("Grantor", "Grantee"):
            for el in soup.find_all(string=re.compile(rf"^{role}\b", re.IGNORECASE)):
                # Look for sibling <li>/<p>/<b> with names.
                parent = el.parent if el and hasattr(el, "parent") else None
                if parent is None:
                    continue
                container = parent.find_next("ul") or parent.find_parent("div")
                if container:
                    for li in container.find_all(["li", "b", "strong"]):
                        nm = li.get_text(strip=True)
                        if nm and nm.lower() not in (role.lower(), f"{role.lower()}:"):
                            parties.append({"role": role, "name": nm})

        return {
            "document_id": doc_id,
            "document_number": doc_number,
            "recording_date": recording_date,
            "doc_type": doc_type,
            "indexed_apn": indexed_apn,
            "book_page": book_page,
            "parties": parties,
            "raw_html_snippet": html[:2000],
        }

    # ----------------------------------------------------------- download_pdf

    # ---------------------------------------------------------------- helpers
    def _reaffirm_disclaimer(self) -> bool:
        """Re-POST the disclaimer-accept body so ``disclaimerAccepted=true`` is
        present on the NEXT request.

        Tyler responds to every non-disclaimer GET with
        ``Set-Cookie: disclaimerAccepted=false`` — and the per-document detail
        / PDF endpoints inspect that cookie at request time, returning a
        stripped skeleton when it's ``false``. The only way to keep the
        session healthy across multiple doc fetches is to re-affirm the
        disclaimer (cheap: server takes the cached g-recaptcha-response token
        and flips the cookie back to true) before every authenticated GET.

        Returns True iff the server returned ``"true"``.
        """
        token = self._cached_token
        try:
            r = self.session.post(
                self._disclaimer_url,
                data={"g-recaptcha-response": token} if token else {},
                headers={"Referer": self._disclaimer_url},
                timeout=30,
            )
        except Exception as exc:
            print(f"  [download_pdf] reaffirm disclaimer failed: {exc}")
            return False
        return r.status_code == 200 and "true" in (r.text or "").lower()

    @staticmethod
    def _extract_real_pdf_path(pdfjs_wrapper_html: str) -> Optional[str]:
        """Extract the actual PDF URL from the pdf.js wrapper page.

        The pdfJsUrl in the detail page points at a ~620-byte HTML wrapper
        whose only useful content is an iframe pointing at the real PDF.
        Wrapper contains:
          <button data-href="/ssweb/document-image-pdf/<doc_id>//<doc_num>-1.pdf?index=1" ...>
          <iframe data-href="...same.../" src='/ssweb/resources/pdfjs/web/tylerPdfJsViewer.html?file=/ssweb/document/servepdf/SCALED-...'>
        We prefer the ``data-href`` (raw watermarked image) over the SCALED
        viewer-internal stream because it's the same bytes the legacy
        Selenium adapter captured.
        """
        # Prefer data-href .pdf links (these point at the watermark-baked image)
        m = re.search(r'data-href=["\']([^"\']+\.pdf[^"\']*)["\']', pdfjs_wrapper_html)
        if m:
            return m.group(1)
        # Fallback: the iframe src= attribute with file= query param
        m = re.search(r'src=["\'][^"\']*tylerPdfJsViewer\.html\?file=([^"&\']+)', pdfjs_wrapper_html)
        if m:
            return m.group(1)
        # Last resort: any /document/servepdf/ or /document-image-pdf/ URL
        m = re.search(r'(/ssweb/(?:document-image-pdf|document/servepdf)[^"\'\s]+\.pdf[^"\'\s]*)', pdfjs_wrapper_html)
        if m:
            return m.group(1)
        return None

    def _absolute_url(self, path_or_url: str) -> str:
        """Resolve a possibly-relative URL against the portal origin."""
        if not path_or_url:
            return path_or_url
        if path_or_url.startswith("http"):
            return path_or_url
        if path_or_url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(self._base_url)
            return f"{parsed.scheme}://{parsed.netloc}{path_or_url}"
        return urljoin(self._base_url, path_or_url)

    # ----------------------------------------------------------- download_pdf

    def download_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Download the watermarked PDF for ``doc_num`` directly from the
        county portal. Used by the pipeline's download phase when
        ``use_titlepro=False`` (FL counties).

        Flow (verified live 2026-05-26 against Orange FL Self-Service):
          1. Resolve the internal Tyler doc_id from the cached search-results
             ``_doc_id_by_number`` map (populated by extract_results).
          2. Re-affirm disclaimer (Tyler sets ``disclaimerAccepted=false`` on
             every page response — we must flip it back before each GET).
          3. GET the detail page; scrape ``pdfJsUrl`` (the pdf.js wrapper URL).
          4. Re-affirm disclaimer, GET the pdf.js wrapper, extract the REAL
             PDF URL from the wrapper's ``<iframe data-href=...>`` attribute.
          5. Re-affirm disclaimer, GET the real PDF URL, write bytes.

        Why "re-affirm disclaimer" three times? Tyler's session keeps a
        per-request ``disclaimerAccepted`` cookie that the server stomps to
        ``false`` on every authenticated GET response. The detail and PDF
        endpoints check that cookie at request time and serve a stripped
        skeleton when it's false. Re-POSTing the disclaimer-accept (cached
        captcha token, no new solve) flips it back to true cheaply.
        """
        if not self._session_warmed and not self.warm_session():
            return {"status": "error", "error": "session_not_warmed"}

        doc_id = self._doc_id_by_number.get(doc_num) if hasattr(self, "_doc_id_by_number") else None
        if not doc_id:
            return {
                "status": "error",
                "error": f"no Tyler doc_id cached for instrument {doc_num} — run perform_search first or seed the cache",
            }

        # Step 2: restore disclaimer cookie before detail GET.
        # (Replaced the heavy `_reaffirm_disclaimer` HTTP POST with a local
        # cookie-jar restore — 2026-05-26 verified that Tyler accepts the
        # locally-restored cookie just as well, but at zero captcha cost.
        # `_reaffirm_disclaimer` re-uses a 2Captcha token which Tyler may
        # treat as single-use; multiple reaffirms in a row also amplify
        # rate-limit risk. The cookie-restore is purely client-side.)
        self._restore_disclaimer_cookie()

        # Step 3: fetch detail page; scrape pdfJsUrl (pdf.js wrapper URL)
        detail_url = f"{self._document_detail_base}{doc_id}?search={self._search_path}"
        try:
            detail_resp = self.session.get(
                detail_url,
                headers={"Referer": self._disclaimer_url},
                timeout=60,
            )
        except Exception as exc:
            return {"status": "error", "error": f"detail network: {exc}"}
        self._restore_disclaimer_cookie()
        if detail_resp.status_code != 200:
            return {"status": "error", "error": f"detail HTTP {detail_resp.status_code}"}

        # Tyler embeds the pdf.js wrapper URL in a JS assignment:
        #   selfservice.document.pdfJsUrl = '/ssweb/document-image-pdfjs/<doc_id>/<uuid>/<doc_number>.pdf?...'
        m = re.search(
            r"pdfJsUrl\s*=\s*['\"]([^'\"]+\.pdf[^'\"]*)['\"]",
            detail_resp.text,
        )
        if not m:
            return {
                "status": "error",
                "error": f"pdfJsUrl not found in detail page (body_len={len(detail_resp.text)}) — "
                         f"detail page likely returned a skeleton; disclaimer cookie may have been reset.",
            }
        pdfjs_url = self._absolute_url(m.group(1))

        # Step 4: GET pdf.js wrapper, extract real PDF URL
        try:
            wrapper_resp = self.session.get(
                pdfjs_url,
                headers={"Referer": detail_url, "Accept": "text/html,*/*"},
                timeout=60,
            )
        except Exception as exc:
            return {"status": "error", "error": f"pdfjs wrapper network: {exc}"}
        self._restore_disclaimer_cookie()
        if wrapper_resp.status_code != 200:
            return {"status": "error", "error": f"pdfjs wrapper HTTP {wrapper_resp.status_code}"}

        real_pdf_path = self._extract_real_pdf_path(wrapper_resp.text)
        if not real_pdf_path:
            return {
                "status": "error",
                "error": f"real PDF URL not found in pdf.js wrapper (wrapper_len={len(wrapper_resp.text)})",
                "pdfjs_url": pdfjs_url,
            }
        real_pdf_url = self._absolute_url(real_pdf_path)

        # Step 5: GET the actual PDF bytes
        try:
            pdf_resp = self.session.get(
                real_pdf_url,
                headers={"Referer": pdfjs_url, "Accept": "application/pdf,*/*"},
                timeout=120,
            )
        except Exception as exc:
            return {"status": "error", "error": f"pdf network: {exc}"}
        if pdf_resp.status_code != 200:
            return {"status": "error", "error": f"pdf HTTP {pdf_resp.status_code}"}
        content = pdf_resp.content
        if not content.startswith(b"%PDF"):
            return {
                "status": "error",
                "error": f"response is not a PDF (first 4 bytes: {content[:4]!r}, len={len(content)})",
                "pdfjs_url": pdfjs_url,
                "real_pdf_url": real_pdf_url,
            }

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)
        return {
            "status": "success",
            "size": len(content),
            "pdf_url": real_pdf_url,
            "pdfjs_url": pdfjs_url,
            "src_via": "pdfjs_wrapper_data_href",
        }

    # ----------------------------------------------------------- extract_results

    def extract_results(self, html: str) -> List[DocumentRecord]:
        """Parse the Tyler searchResults HTML fragment.

        Each row is ``<li class="ss-search-row" data-documentid="..." ...>``.
        """
        documents: List[DocumentRecord] = []
        if not html:
            return documents
        soup = BeautifulSoup(html, "lxml")

        # Ensure the doc_id cache exists on the instance.
        if not hasattr(self, "_doc_id_by_number"):
            self._doc_id_by_number: Dict[str, str] = {}

        seen = set()
        for li in soup.select("li.ss-search-row"):
            doc_id = li.get("data-documentid", "")
            href = li.get("data-href", "")

            # The <h1> holds the public doc#, doc type, and recording datetime.
            h1 = li.find("h1")
            h1_text = (h1.get_text(" ", strip=True) if h1 else "")

            # Parse h1 — looks like "20220421546 Satisfaction 07/11/2022 10:57 AM"
            doc_num = ""
            m = re.match(r"^\s*(\S+)", h1_text)
            if m and self._doc_number_re.match(m.group(1)):
                doc_num = m.group(1)

            # Cache the internal Tyler doc_id by instrument number so
            # download_pdf() can resolve it without re-searching.
            if doc_num and doc_id:
                self._doc_id_by_number[doc_num] = doc_id

            # Recording date — find first MM/DD/YYYY in h1.
            rec_date = ""
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", h1_text)
            if m:
                rec_date = m.group(1)

            # Doc type — between doc# and date.
            doc_type = ""
            if doc_num and rec_date:
                middle = h1_text.replace(doc_num, "", 1).replace(rec_date, "", 1)
                doc_type = re.sub(r"\s+", " ", middle).strip()
                # Strip times like "10:57 AM" or "10:57:04 AM"
                doc_type = re.sub(r"\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?", "", doc_type, flags=re.I).strip()
            elif doc_num:
                doc_type = re.sub(r"\s+", " ", h1_text.replace(doc_num, "", 1)).strip()

            if not doc_num or doc_num in seen:
                continue
            seen.add(doc_num)

            # Parse the four ``searchResultFourColumn`` blocks: Grantor / Grantee / Legal / BookPage
            grantors: List[str] = []
            grantees: List[str] = []
            book_page = ""

            for col in li.select("div.searchResultFourColumn"):
                ul = col.find("ul")
                if not ul:
                    continue
                lis = ul.find_all("li")
                if not lis:
                    continue
                header = lis[0].get_text(strip=True).lower()
                names = [
                    sub.get_text(strip=True)
                    for sub in lis[1:]
                    if sub.get_text(strip=True)
                ]
                if header.startswith("grantor"):
                    grantors.extend(names)
                elif header.startswith("grantee"):
                    grantees.extend(names)
                elif header.startswith("bookpage") or header.startswith("book"):
                    book_page = " ".join(names)

            grantors_str = "; ".join(grantors)
            grantees_str = "; ".join(grantees)

            documents.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=grantors_str,
                    grantees=grantees_str,
                    grantor_grantees=(
                        f"{grantors_str} | {grantees_str}"
                        if grantors_str and grantees_str
                        else (grantors_str or grantees_str)
                    ),
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages=book_page,
                )
            )

        return documents

    # ----------------------------------------------------- name-match helpers

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Lower-case, strip punctuation/extra spaces."""
        return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()

    def _name_in_field(self, needle: str, haystack: str) -> bool:
        """Soft-match needle against a "; "-joined party-list field."""
        if not needle or not haystack:
            return False
        h = self._normalize_name(haystack)
        # All tokens of needle must appear in haystack (order-independent).
        return all(tok in h for tok in needle.split() if tok)

    # ------------------------------------------------------------- cleanup

    def close(self):  # pragma: no cover - trivial
        # curl_cffi.Session has no explicit close, but we clear the dict.
        try:
            self.session.cookies.clear()
        except Exception:
            pass
