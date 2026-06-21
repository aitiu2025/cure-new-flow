"""
AcclaimWeb HTTP-First Adapter (Phase 1 CURE restructure).

A pure-Python replacement for the Selenium-based ``acclaimweb_adapter.py``
search path. Designed initially for Broward County (FL), which is fronted by
Cloudflare. Uses ``curl_cffi`` (BoringSSL + Chrome TLS/JA3 fingerprint
impersonation) so the session passes Cloudflare's challenge layer without
any browser involvement. The adapter never imports Selenium, Playwright, or
undetected-chromedriver.

Per Tony Roveda's 2026-05 Broward review, Phase 1 must be 100% HTTP — no
browser fallback anywhere in the search path. Live testing (2026-05-22)
confirmed that plain ``requests`` is blocked by Cloudflare with
``cf-mitigated: challenge``, while ``curl_cffi.Session(impersonate="chrome120")``
returns 200 OK with the real Broward HTML on the first GET. That's the only
auth layer this adapter needs.

Design highlights
-----------------
* Subclasses ``BaseRecorderSearch`` so the registry/factory plumbing is
  unchanged. ABC methods that are browser-only (``setup_driver``,
  ``navigate_to_search``, ``return_to_search``) collapse to no-ops.
* Cloudflare clearance via ``curl_cffi`` TLS fingerprint impersonation —
  no browser cookie minting required.
* Anti-forgery token: GET the search page, scrape ``__RequestVerificationToken``
  from the first <input> we find, POST it back. On 403 we refresh once.
* State independence: every ``perform_search()`` call is fully independent.
  No form state is cached between calls — this is the explicit anti-pattern
  that broke the old browser adapter (Kendo + bfcache races).
* Failure mode: if HTTP search fails with 403 and an anti-forgery refresh
  doesn't rescue it, ``self.last_failure = "needs_session_token"`` is set
  and an empty list is returned so the pipeline can branch on it.

A cookie-jar load/save is retained as defense-in-depth (cookies from a prior
warmed session can be reloaded across process restarts), but it is NOT the
primary auth strategy — the impersonated session is.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# Default impersonation profile — safari17_2_ios passes Broward's Cloudflare
# layer cleanly for BOTH GETs and POSTs as of 2026-05-22. Chrome profiles
# (chrome120/124/131) pass GET but get JS-challenged on POST; Safari iOS
# fingerprint is allowed through (Cloudflare permits mobile Safari POSTs more
# leniently). Override via config["impersonate_profile"] if a tenant's CF
# config shifts.
DEFAULT_IMPERSONATE = "safari17_2_ios"

# Optional cookie-jar location (defense-in-depth across process restarts).
DEFAULT_COOKIE_JAR = "~/.titlepro/cookie_jar/broward.json"

# Extra Accept-Language hint (curl_cffi already sets full Chrome header set
# via the impersonation profile, but we override AL in case the user prefers
# a non-US locale).
EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}


class AcclaimWebHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for AcclaimWeb (Broward in particular)."""

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "").rstrip("/") + "/"
        self._search_url = config.get(
            "search_url",
            self._base_url + "search/SearchTypeName",
        )
        self._http_search_endpoint = config.get(
            "http_search_endpoint",
            self._base_url + "search/SearchByName",
        )

        # Form-field name mapping (matches Broward's MVC model binders).
        ff = config.get("http_form_fields", {})
        self._field_name = ff.get("name", "SearchOnName")
        self._field_date_from = ff.get("date_from", "RecordDateFrom")
        self._field_date_to = ff.get("date_to", "RecordDateTo")
        self._field_doc_type = ff.get("doc_type", "DocTypes")

        self._antiforgery_field = config.get(
            "antiforgery_token_field", "__RequestVerificationToken"
        )
        self._cloudflare_required = bool(config.get("cloudflare_required", False))
        self._doctype_deed_value = config.get("doctype_deed_value", "DEED")

        # Party-type mapping for AcclaimWeb (radios on Broward, dropdown elsewhere).
        self.party_type_map = config.get(
            "party_type_map",
            {
                "Grantor/Grantee": "All",
                "Both": "All",
                "All": "All",
                "Grantor": "Grantor",
                "Grantee": "Grantee",
            },
        )
        self.supported_party_types = config.get(
            "supported_party_types", ["All", "Grantor", "Grantee"]
        )

        # Doc-number pattern (combined regex, OR-joined).
        pat = config.get("doc_number_pattern") or r"^\d{4}-\d{6,12}$|^\d{8,}$"
        self._doc_number_re = re.compile(pat)

        # Cookie jar path (expand ~). Defense-in-depth — primary auth is TLS
        # fingerprint, this is a fast-restart cache.
        jar_cfg = config.get("cookie_jar_path", DEFAULT_COOKIE_JAR)
        self._cookie_jar_path = Path(os.path.expanduser(jar_cfg))

        # HTTP session + state flags. curl_cffi.Session passes Cloudflare via
        # Chrome TLS/JA3 impersonation — no browser cookie minting required.
        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)
        self._antiforgery_token: Optional[str] = None
        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # Recipe-style doc-image URL pattern (mirrors Tyler). Configurable in
        # county JSON. The Broward AcclaimWeb flow is multi-step:
        #   1. GET {base_url}{jump_url}                  → response holds a
        #      transaction token in `hdnTransactionItemId` (form input) or in
        #      a `DocumentImage1/<token>` substring.
        #   2. GET {base_url}{start_image_retrieval}     → warms the cache.
        #   3. GET {base_url}{viewer_url}                → viewer HTML contains
        #      the absolute `WebAtalaCache/<hash>_<txn>_docPdf.pdf` URL.
        #   4. GET that absolute PDF URL → binary PDF bytes.
        # All tokens are expressed via {placeholders} so a sibling AcclaimWeb
        # tenant can override the route shape if it differs.
        pattern_cfg = config.get("doc_image_url_pattern", {})
        self._dip_jump_url = pattern_cfg.get(
            "jump_url", "details/JumpToInstrumentNumber/{record_type}/{doc_num}"
        )
        self._dip_start_image_retrieval = pattern_cfg.get(
            "start_image_retrieval", "Image/StartImageRetrieval/{token}/0"
        )
        self._dip_viewer_url = pattern_cfg.get(
            "viewer_url", "Image/DocumentImage1/{token}"
        )
        self._dip_record_type = int(pattern_cfg.get("record_type", 27))
        # Per-tenant token regexes (ordered; first non-empty wins). Defaults
        # capture the Broward shape verified 2026-05 via the bulk-downloader
        # reference (/tmp/broward_bulk_downloader.py).
        self._dip_token_regex_options: List[re.Pattern] = [
            re.compile(p)
            for p in pattern_cfg.get(
                "token_regex_options",
                [
                    r'id\s*=\s*[\'"]hdnTransactionItemId[\'"]\s+value\s*=\s*[\'"]([A-Za-z0-9_\-]+)[\'"]',
                    r'value\s*=\s*[\'"]([A-Za-z0-9_\-]{40,80})[\'"]\s+[^>]*id\s*=\s*[\'"]hdnTransactionItemId[\'"]',
                    r"DocumentImage1/([A-Za-z0-9_\-]+)",
                    r'"Token"\s*:\s*"([A-Za-z0-9_\-]+)"',
                    r"StartImageRetrieval/([A-Za-z0-9_\-]+)",
                ],
            )
        ]
        # Regex applied against the viewer HTML to lift the absolute (relative)
        # WebAtalaCache PDF URL.
        self._dip_pdf_href_regex = re.compile(
            pattern_cfg.get(
                "pdf_href_regex",
                r"['\"]([^'\"]*WebAtalaCache/[A-Za-z0-9_\-]+_\d+_docPdf\.pdf)['\"]",
            )
        )
        # Brief delay between viewer HTML and PDF GET — the Atala backend
        # needs a moment to materialize the cached blob (verified 5.5s in the
        # bulk-downloader reference).
        self._dip_pre_pdf_delay_seconds = float(
            pattern_cfg.get("pre_pdf_delay_seconds", 5.5)
        )
        self._dip_pdf_fetch_retries = int(pattern_cfg.get("pdf_fetch_retries", 3))
        self._dip_pdf_retry_delay_seconds = float(
            pattern_cfg.get("pdf_retry_delay_seconds", 3.0)
        )
        # Some AcclaimWeb tenants (Duval/OnCore, 2026-06-18) key the image flow
        # off an OPAQUE per-session token in the jump-detail page's
        # `hdnTransactionItemId`, NOT the numeric `TransactionItemId` returned
        # in the search grid. Using the grid's numeric token against
        # Image/DocumentImage1 500s on those tenants. When this flag is set we
        # skip the grid-cache fast path and always do the jump-detail GET so
        # `_extract_token` harvests the correct opaque token.
        self._dip_image_token_from_detail = bool(
            pattern_cfg.get("image_token_from_detail", False)
        )

        # ------------------------------------------------------------------
        # Three-step JSON search flow (Brevard tenant shape, 2026-06-10).
        # search_flow="three_step_json" switches perform_search() from the
        # Broward single-POST+HTML-scrape to the Brevard chain:
        #   1. POST search/SearchTypeName?Length=6  → name-picker treeview
        #   2. POST Search/SearchTypePreName        → commits selected names
        #   3. POST Search/GridResults              → JSON result rows
        # Defaults preserve the legacy Broward behavior ("single_post").
        # ------------------------------------------------------------------
        self._search_flow = config.get("search_flow", "single_post")
        self._doctype_deed_display = config.get("doctype_deed_display", "DEED (D)")
        self._doctype_numeric_map = config.get("doctype_numeric_map", {})
        self._default_book_type = str(config.get("default_book_type_numeric", "3"))
        # Inter-POST politeness delay for the live chain (tests set 0).
        self._three_step_post_delay = float(
            config.get("three_step_post_delay_seconds", 30.0)
        )
        # Per-row extras captured from the GridResults JSON, keyed by
        # document number: TransactionItemId (image token), BookPage,
        # legal description, consideration, party direction.
        self.row_extras: Dict[str, Dict[str, Any]] = {}

        # ABC compliance: parent expects self.driver, but we never use it.
        self.driver = None

    # --------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # --------------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):
        """No-op — HTTP adapter has no browser driver."""
        return None

    def navigate_to_search(self):
        """No-op — every perform_search() pulls the search page fresh."""
        return None

    def return_to_search(self):
        """No-op — HTTP path is stateless between calls."""
        return None

    # ------------------------------------------------------ session warm-up

    def warm_session(
        self,
        browser_minted_cookies: Optional[Dict] = None,
        cookie_jar_path: Optional[str] = None,
    ) -> bool:
        """Bootstrap the session for Phase 1 searches.

        Cloudflare clearance is handled at the TLS layer by curl_cffi's Chrome
        impersonation — no cookie minting is required for the primary path.
        This method:
          1. Optionally pre-loads cookies from a caller-supplied dict (test
             injection) or a saved jar (fast-restart across process boundaries).
          2. Hits the AcclaimWeb landing page so the session picks up any
             tenant-issued cookies that the disclaimer flow requires.
          3. Accepts the disclaimer (POST) to unlock the search route.
          4. Harvests the ``__RequestVerificationToken`` from the search form.

        Returns True/False; on False, ``self.last_failure`` is set.
        """
        # Optional: pre-seed cookies from caller or saved jar (defense-in-depth).
        if browser_minted_cookies:
            for name, value in browser_minted_cookies.items():
                self.session.cookies.set(name, value)
            self._session_warmed = True

        if not self._session_warmed:
            jar = Path(os.path.expanduser(cookie_jar_path)) if cookie_jar_path else self._cookie_jar_path
            if jar.exists():
                try:
                    with jar.open("r") as f:
                        payload = json.load(f)
                    if not self._cookies_expired(payload):
                        for c in payload.get("cookies", []):
                            self.session.cookies.set(
                                c.get("name"),
                                c.get("value"),
                                domain=c.get("domain"),
                                path=c.get("path", "/"),
                            )
                        self._session_warmed = True
                        print(f"  [warm_session] loaded {len(payload.get('cookies', []))} cookies from {jar}")
                except Exception as exc:
                    print(f"  [warm_session] failed to read jar {jar}: {exc}")

        # Primary auth path: hit the landing + accept the disclaimer using the
        # curl_cffi impersonated session. This is what unlocks the search route.
        if not self._session_warmed:
            try:
                self._handshake_disclaimer()
                self._session_warmed = True
            except Exception as exc:
                print(f"  [warm_session] disclaimer handshake failed: {exc}")
                self.last_failure = "needs_session_token"
                return False

        # Harvest anti-forgery token from the search page.
        try:
            self._refresh_antiforgery_token()
        except Exception as exc:
            print(f"  [warm_session] anti-forgery token harvest failed: {exc}")
            # Not fatal — some Acclaim tenants don't require it. We'll find out on POST.

        return self._session_warmed

    def _handshake_disclaimer(self) -> None:
        """Pure-HTTP disclaimer accept. Loads the landing page, posts the
        I-Accept form, follows redirects to the search route. Raises on any
        non-200 response so warm_session can mark the session unusable.
        """
        landing = self.session.get(self._base_url, timeout=30)
        if landing.status_code != 200:
            raise RuntimeError(f"landing GET returned {landing.status_code}")

        soup = BeautifulSoup(landing.text, "lxml")
        form = soup.find("form")
        if not form:
            # No disclaimer present — some tenants skip it. Treat as success.
            return
        action = form.get("action") or "/"
        if action.startswith("/"):
            # Resolve relative URL against the configured base scheme/host.
            from urllib.parse import urljoin
            action_url = urljoin(self._base_url, action.lstrip("/"))
        else:
            action_url = action

        fields = {
            inp.get("name"): inp.get("value", "")
            for inp in form.find_all("input")
            if inp.get("name")
        }
        # Most AcclaimWeb tenants use btnButton="I accept the conditions above."
        fields.setdefault("btnButton", "I accept the conditions above.")

        accept = self.session.post(
            action_url,
            data=fields,
            timeout=30,
            allow_redirects=True,
            headers={"Referer": self._base_url},
        )
        if accept.status_code not in (200, 302):
            raise RuntimeError(
                f"disclaimer POST returned {accept.status_code}; cannot reach search route"
            )

    # --------------------------------------------------------- antiforgery

    def _refresh_antiforgery_token(self) -> Optional[str]:
        """GET the search page and scrape the __RequestVerificationToken input."""
        resp = self.session.get(self._search_url, timeout=30)
        if resp.status_code == 403:
            self.last_failure = "needs_session_token"
            raise RuntimeError("403 fetching search page — Cloudflare cookies stale")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        token_input = soup.find("input", attrs={"name": self._antiforgery_field})
        if token_input and token_input.get("value"):
            self._antiforgery_token = token_input["value"]
            return self._antiforgery_token
        return None

    # ----------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "All",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search.

        State-independent: builds a fresh form payload on every call. Does NOT
        carry form state from previous searches (the explicit anti-pattern
        Tony's review called out).
        """
        if not self._session_warmed:
            # Try a lazy warm-up from the default cookie jar.
            if not self.warm_session():
                print(f"  [perform_search] session not warmed; last_failure={self.last_failure}")
                return []

        # Map party-type label to the tenant vocabulary (radio value).
        mapped_party = self.party_type_map.get(party_type, party_type)
        if mapped_party not in self.supported_party_types:
            fallback = self.supported_party_types[0] if self.supported_party_types else "All"
            print(
                f"  [perform_search] party_type '{party_type}' not in supported "
                f"{self.supported_party_types}; defaulting to '{fallback}'"
            )
            mapped_party = fallback

        # Brevard-shape tenants: three-step JSON chain.
        if self._search_flow == "three_step_json":
            return self._perform_search_three_step(
                name=name,
                mapped_party=mapped_party,
                doc_type=doc_type,
                date_from=date_from or self.start_date,
                date_to=date_to or self.end_date,
            )

        payload = {
            self._field_name: name,
            self._field_date_from: date_from or self.start_date,
            self._field_date_to: date_to or self.end_date,
            "PartyType": mapped_party,
        }
        if doc_type:
            # Translate semantic label → tenant value if config provides it.
            if doc_type.upper() == "DEED":
                payload[self._field_doc_type] = self._doctype_deed_value
            else:
                payload[self._field_doc_type] = doc_type
        if self._antiforgery_token:
            payload[self._antiforgery_field] = self._antiforgery_token

        post_headers = {
            "Referer": self._search_url,
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self.session.post(
            self._http_search_endpoint,
            data=payload,
            headers=post_headers,
            timeout=60,
            allow_redirects=True,
        )

        if resp.status_code == 403:
            # One retry: refresh cookies + token, then re-post.
            print("  [perform_search] 403 — refreshing session and retrying once")
            try:
                self._refresh_antiforgery_token()
                if self._antiforgery_token:
                    payload[self._antiforgery_field] = self._antiforgery_token
                resp = self.session.post(
                    self._http_search_endpoint,
                    data=payload,
                    headers=post_headers,
                    timeout=60,
                )
            except Exception as exc:
                print(f"  [perform_search] refresh failed: {exc}")

            if resp.status_code == 403:
                self.last_failure = "needs_session_token"
                return []

        if resp.status_code != 200:
            print(f"  [perform_search] HTTP {resp.status_code} from search endpoint")
            return []

        return self.extract_results(resp.text)

    # ------------------------------------------- three-step JSON search (Brevard)

    def _three_step_doctype_values(self, doc_type: Optional[str]) -> tuple:
        """Map a semantic doc-type label to the tenant's (numeric, display) pair.

        None → ("all", "All") — the tenant's hidden-textarea default.
        "DEED" → (doctype_deed_value, doctype_deed_display), e.g. ("80", "DEED (D)").
        Other labels go through doctype_numeric_map; unmapped values pass through.
        """
        if not doc_type:
            return ("all", "All")
        label = str(doc_type).strip()
        if label.upper() == "DEED":
            return (self._doctype_deed_value, self._doctype_deed_display)
        mapped = self._doctype_numeric_map.get(label.upper()) or self._doctype_numeric_map.get(label)
        if mapped:
            return (str(mapped), label)
        return (label, label)

    @staticmethod
    def _parse_name_tree(html: str) -> List[str]:
        """Extract LEAF names from the step-1 name-picker treeview.

        Two tenant renderings are supported:

        * Legacy Telerik: leaves are ``<input name="itemValue">`` hidden
          inputs. Parent (surname-group) nodes carry a trailing ``(N)`` count
          (e.g. ``LEWIS (1)``); leaf nodes carry the clean indexed name.
        * Kendo TreeView (Duval/OnCore, observed 2026-06-18): leaves live in a
          ``kendo.syncReady(...kendoTreeView({"dataSource":[...]}))`` script
          block. Both parent and leaf node ``text`` values carry a ``(N)``
          count; leaves are the nodes WITHOUT a child ``items`` array. We strip
          the count off the text and treat childless nodes as leaves.

        Returns the leaves, de-duplicated, in document order.
        """
        if not html:
            return []
        leaves: List[str] = []
        seen = set()

        # --- Path 1: legacy Telerik hidden inputs --------------------------
        soup = BeautifulSoup(html, "lxml")
        for inp in soup.find_all("input", attrs={"name": "itemValue"}):
            val = (inp.get("value") or "").strip()
            if not val or re.search(r"\(\d+\)$", val):
                continue  # parent/group node or empty
            if val not in seen:
                seen.add(val)
                leaves.append(val)
        if leaves:
            return leaves

        # --- Path 2: Kendo TreeView JSON dataSource ------------------------
        # The kendoTreeView({...}) config object also contains JS expressions
        # (e.g. template: jQuery('#treeview').html()) that are NOT valid JSON,
        # so we can't json.loads the whole config. Extract just the
        # "dataSource":[...] array via balanced-bracket scanning (quote-aware)
        # and parse that.
        def _balanced(text: str, start: int, open_ch: str, close_ch: str):
            depth = 0
            k = start
            instr = False
            esc = False
            while k < len(text):
                c = text[k]
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = not instr
                elif not instr:
                    if c == open_ch:
                        depth += 1
                    elif c == close_ch:
                        depth -= 1
                        if depth == 0:
                            return text[start:k + 1]
                k += 1
            return None

        def _walk(nodes):
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                items = n.get("items")
                if items:
                    _walk(items)
                    continue
                txt = re.sub(r"\s*\(\d+\)\s*$", "", str(n.get("text", ""))).strip()
                if txt and txt not in seen:
                    seen.add(txt)
                    leaves.append(txt)

        for m in re.finditer(r'"dataSource"\s*:\s*\[', html):
            bracket = html.find("[", m.start())
            if bracket == -1:
                continue
            arr_txt = _balanced(html, bracket, "[", "]")
            if not arr_txt:
                continue
            try:
                data = json.loads(arr_txt)
            except Exception:
                continue
            _walk(data)
        return leaves

    @staticmethod
    def _normalize_party_name(name: str) -> str:
        """Canonicalize a party name for cross-format leaf matching.

        Treats commas as whitespace and collapses internal runs of whitespace,
        uppercasing. So all three AcclaimWeb / Kendo index forms of the SAME
        identity map to the same string:
          ``"LEWIS, ANGELA D"`` (Telerik comma-space),
          ``"LEWIS,ANGELA D"``  (Telerik comma-no-space), and
          ``"LEWIS ANGELA D"``  (Kendo TreeView, comma-less — Duval/OnCore).
        The middle-name token that distinguishes different people
        (``"LEWIS ANGELA H"`` stays distinct from ``"LEWIS ANGELA D"``) is
        preserved, so a startswith match on the searched prefix still excludes
        unrelated parties.
        """
        s = (name or "").strip().upper()
        s = s.replace(",", " ")
        s = re.sub(r"\s+", " ", s)
        return s

    @staticmethod
    def _parse_ms_date(raw: str) -> str:
        """Convert ASP.NET ``/Date(830186974000)/`` to ``MM/DD/YYYY``."""
        m = re.search(r"/Date\((-?\d+)\)/", str(raw or ""))
        if not m:
            return str(raw or "")
        try:
            ts = int(m.group(1)) / 1000.0
            return datetime.fromtimestamp(ts).strftime("%m/%d/%Y")
        except Exception:
            return str(raw)

    def _three_step_sleep(self) -> None:
        if self._three_step_post_delay > 0:
            time.sleep(self._three_step_post_delay)

    def _perform_search_three_step(
        self,
        name: str,
        mapped_party: str,
        doc_type: Optional[str],
        date_from: str,
        date_to: str,
    ) -> List[DocumentRecord]:
        """Brevard-shape AcclaimWeb search: names POST → prename POST → JSON grid.

        Verified live against Brevard 2026-06-10 (case Brevard_LEWIS_v1).
        Selected names default to leaves that START WITH the searched name
        (normalized); if none match, ALL leaves are selected and a warning is
        printed so the examiner sees the over-inclusion (Tony directive #5 —
        better to over-include and itemize than silently drop).
        """
        doctype_numeric, doctype_display = self._three_step_doctype_values(doc_type)
        referer = self._search_url

        # ---- Step 1: name resolution -------------------------------------
        step1_payload = {
            mapped_party: mapped_party,            # checked radio (Both/Direct/Reverse)
            "PartyType": mapped_party,
            "SearchOnName": name,
            "DateRangeList": " ",
            "DocTypes": doctype_numeric,
            "DocTypesDisplay-input": doctype_display,
            "DocTypesDisplay": "",
            "RecordDateFrom": date_from,
            "RecordDateTo": date_to,
            "BookTypesDisplay": "OR",
            "BookTypes": self._default_book_type,
            "IsParsedName": "False",
        }
        post_headers = {"Referer": referer, "X-Requested-With": "XMLHttpRequest"}
        try:
            r1 = self.session.post(
                self._search_url + "?Length=6",
                data=step1_payload,
                headers=post_headers,
                timeout=30,
            )
        except Exception as exc:
            print(f"  [three_step] step-1 network error: {exc}")
            self.last_failure = "three_step_step1_network"
            return []
        if r1.status_code != 200:
            print(f"  [three_step] step-1 HTTP {r1.status_code}")
            self.last_failure = f"three_step_step1_http_{r1.status_code}"
            return []
        body1 = r1.text or ""
        if "Error in getting list of names" in body1:
            print("  [three_step] step-1 returned pre-name-search error (check "
                  "numeric DocTypes/BookTypes + IsParsedName=False payload)")
            self.last_failure = "three_step_prename_error"
            return []

        leaves = self._parse_name_tree(body1)
        if not leaves:
            # Legit zero-match (name not in index for window/doctype).
            print(f"  [three_step] no indexed names matched '{name}'")
            return []

        # Leaf-match must be PUNCTUATION/WHITESPACE-NORMALIZED. AcclaimWeb
        # tenants store BOTH "LEWIS, ANGELA D" (comma-space) and
        # "LEWIS,ANGELA D" (comma-no-space) forms — Brevard switched indexing
        # format ~2007, so a space-sensitive startswith silently drops every
        # post-format-change document (the LEWIS 2026 Truist-mortgage miss).
        # Normalize away comma-spacing + collapse internal whitespace before
        # comparing so both forms of the SAME identity are selected, while
        # different middle names (ANGELA H, ANGELA SUE, …) are still excluded.
        norm = self._normalize_party_name(name)
        selected = [v for v in leaves if self._normalize_party_name(v).startswith(norm)]
        if not selected:
            print(
                f"  [three_step] WARNING: no leaf normalize-matches '{name}'; "
                f"selecting ALL {len(leaves)} leaves for completeness: {leaves[:8]}"
            )
            selected = leaves
        namelist = "|||".join(selected)

        # ---- Step 2: prename commit ---------------------------------------
        self._three_step_sleep()
        prename_payload = {
            "NameList": namelist,
            "PartyType": mapped_party,
            "RecordDateFrom": f"{date_from} 12:00:00 AM",
            "RecordDateTo": f"{date_to} 12:00:00 AM",
            "BookTypes": self._default_book_type,
            "DocTypes": doctype_numeric,
            "SearchOnName": name,
            "SearchOnLastOrBusinessName": "",
            "SearchOnFirstName": "",
        }
        prename_url = urljoin(self._base_url, "Search/SearchTypePreName")
        try:
            r2 = self.session.post(
                prename_url, data=prename_payload, headers=post_headers, timeout=30
            )
        except Exception as exc:
            print(f"  [three_step] step-2 network error: {exc}")
            self.last_failure = "three_step_step2_network"
            return []
        if r2.status_code != 200:
            print(f"  [three_step] step-2 HTTP {r2.status_code}")
            self.last_failure = f"three_step_step2_http_{r2.status_code}"
            return []

        # ---- Step 3: JSON grid (paginated) --------------------------------
        grid_url = urljoin(self._base_url, "Search/GridResults")
        documents: List[DocumentRecord] = []
        page = 1
        total: Optional[int] = None
        seen_keys = set()
        while True:
            self._three_step_sleep()
            try:
                r3 = self.session.post(
                    grid_url,
                    data={
                        "page": str(page),
                        "size": "200",
                        "orderBy": "",
                        "groupBy": "",
                        "filter": "",
                    },
                    headers=post_headers,
                    timeout=30,
                )
            except Exception as exc:
                print(f"  [three_step] grid page {page} network error: {exc}")
                self.last_failure = "three_step_grid_network"
                break
            if r3.status_code != 200:
                print(f"  [three_step] grid page {page} HTTP {r3.status_code}")
                self.last_failure = f"three_step_grid_http_{r3.status_code}"
                break
            try:
                payload = r3.json()
            except Exception:
                print(f"  [three_step] grid page {page} returned non-JSON "
                      f"({(r3.text or '')[:120]!r})")
                self.last_failure = "three_step_grid_not_json"
                break
            # Kendo/Telerik MVC grids return PascalCase ("Data"/"Total");
            # older AcclaimWeb tenants returned camelCase ("data"/"total").
            # Duval/OnCore switched to PascalCase (observed 2026-06-18) — accept
            # both so a casing flip can't silently zero out the result set.
            rows = payload.get("Data")
            if rows is None:
                rows = payload.get("data") or []
            _total = payload.get("Total", payload.get("total"))
            if _total is not None:
                total = _total
            for row in rows:
                rec = self._row_to_record(row)
                if rec is None:
                    continue
                key = (rec.document_number, rec.grantors, rec.grantees, rec.document_type)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                documents.append(rec)
            if total is None or len(documents) >= int(total) or not rows:
                break
            page += 1
            if page > 50:  # hard safety stop
                print("  [three_step] pagination safety stop at page 50")
                break

        print(
            f"  [three_step] '{name}' ({mapped_party}, doctype={doctype_numeric}) "
            f"→ {len(documents)} documents (grid total={total})"
        )
        return documents

    def _row_to_record(self, row: Dict[str, Any]) -> Optional[DocumentRecord]:
        """Convert one GridResults JSON row into a DocumentRecord.

        Party semantics (verified live): ``Party=="To"`` means the indexed
        ``Name`` is the To-party / reverse-index side (grantee); the
        ``CrossPartyName`` is then the grantor. ``Party=="From"`` is the
        inverse. Extras (TransactionItemId image token, BookPage, legal,
        consideration) are cached in ``self.row_extras`` keyed by doc number.
        """
        if not isinstance(row, dict):
            return None
        doc_num = str(row.get("InstrumentNumber") or "").strip()
        if not doc_num:
            return None
        name_side = (row.get("Name") or "").strip()
        cross_side = (row.get("CrossPartyName") or "").strip()
        party = (row.get("Party") or "").strip().upper()
        if party.startswith("T"):       # "To" — indexed name is grantee
            grantors, grantees = cross_side, name_side
        elif party.startswith("F"):     # "From" — indexed name is grantor
            grantors, grantees = name_side, cross_side
        else:                            # unknown direction — keep both visible
            grantors, grantees = cross_side, name_side

        rec = DocumentRecord(
            document_number=doc_num,
            grantors=grantors,
            grantees=grantees,
            grantor_grantees=(
                f"{grantors}; {grantees}" if grantors and grantees else (grantors or grantees)
            ),
            document_type=(row.get("DocTypeDescription") or "").strip(),
            recording_date=self._parse_ms_date(row.get("RecordDate")),
            pages="",
        )
        extras = {
            "transaction_item_id": row.get("TransactionItemId"),
            "book_type": (row.get("BookType") or "").strip(),
            "book_page": (row.get("BookPage") or "").strip(),
            "consideration": row.get("Consideration"),
            "legal_description": (row.get("DocLegalDescription") or "").strip(),
            "case_number": (row.get("CaseNumber") or "") or "",
            "party_direction": party,
        }
        # Merge (a doc can appear once per party row); keep first non-empty values.
        prev = self.row_extras.get(doc_num, {})
        for k, v in extras.items():
            if not prev.get(k) and v not in (None, ""):
                prev[k] = v
        self.row_extras[doc_num] = prev
        return rec

    # -------------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str) -> Dict:
        """Fetch the document-detail page for ``doc_num``.

        Returns a dict with:
            document_number, recording_date, doc_type, indexed_apn,
            book_page, parties (list of {role, name}), raw_html (truncated).

        Network failure / 403 returns ``{"document_number": doc_num, "error": ...}``.
        """
        if not self._session_warmed:
            self.warm_session()

        detail_url = self._base_url + f"details/{doc_num}"
        try:
            resp = self.session.get(detail_url, timeout=45)
        except Exception as exc:
            return {"document_number": doc_num, "error": f"network: {exc}"}

        if resp.status_code == 403:
            self.last_failure = "needs_session_token"
            return {"document_number": doc_num, "error": "403 — needs_session_token"}
        if resp.status_code != 200:
            return {"document_number": doc_num, "error": f"HTTP {resp.status_code}"}

        return self._parse_detail_html(resp.text, doc_num)

    @staticmethod
    def _parse_detail_html(html: str, doc_num: str) -> Dict:
        """Parse the AcclaimWeb detail page into structured fields."""
        soup = BeautifulSoup(html, "lxml")

        def find_field(label_substring: str) -> str:
            """Heuristic: find a <td>/<dt> matching label, return adjacent value."""
            label_re = re.compile(label_substring, re.IGNORECASE)
            # Pattern A: <td>Label</td><td>Value</td>
            for td in soup.find_all(["td", "th", "dt", "div", "span"]):
                if td.string and label_re.search(td.string):
                    nxt = td.find_next_sibling(["td", "dd", "div", "span"])
                    if nxt:
                        return (nxt.get_text(strip=True) or "")
            return ""

        # APN / parcel id — Broward shows this as "Parcel ID" on indexed detail.
        indexed_apn = (
            find_field(r"Parcel.?ID")
            or find_field(r"\bAPN\b")
            or find_field(r"Property.?ID")
        )

        recording_date = find_field(r"Record(ed|ing) Date") or find_field(r"Date Recorded")
        doc_type = find_field(r"Doc.?Type") or find_field(r"Document Type")
        book_page = find_field(r"Book.?\/.?Page") or find_field(r"Book\s*Page")

        # Parties — Broward renders a table with role + name columns.
        parties: List[Dict[str, str]] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if any("party" in h or "role" in h for h in headers):
                for row in table.find_all("tr")[1:]:
                    tds = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(tds) >= 2:
                        parties.append({"role": tds[0], "name": tds[1]})

        return {
            "document_number": doc_num,
            "recording_date": recording_date,
            "doc_type": doc_type,
            "indexed_apn": indexed_apn,
            "book_page": book_page,
            "parties": parties,
            "raw_html_snippet": html[:2000],
        }

    # ----------------------------------------------------------- download_pdf

    def _extract_token(self, html: str) -> Optional[str]:
        """Apply the configured token-regex options against ``html``.

        Returns the first non-empty capture group or None. Pattern order
        matches the bulk-downloader reference (hdn input wins; viewer href
        fallback last).
        """
        if not html:
            return None
        for rx in self._dip_token_regex_options:
            m = rx.search(html)
            if m:
                return m.group(1)
        return None

    def download_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Direct-portal download for a Broward AcclaimWeb instrument.

        Mirrors the Tyler ``download_pdf`` contract — returns:

        Success: ``{"status": "success", "size": int, "src_via": str,
                    "pdf_url": str, "token": str}``
        Failure: ``{"status": "error", "error": str, "phase": str,
                    "pdf_url"|"token"?: str}``

        The flow (verified against Broward via /tmp/broward_bulk_downloader.py):

        1. GET ``{base_url}{jump_url}``      — extract the transaction token.
        2. GET ``{base_url}{start_image_retrieval}`` — warm the cache (response
           body discarded; non-200 is non-fatal but logged).
        3. GET ``{base_url}{viewer_url}``    — scrape ``WebAtalaCache/...``
           absolute PDF URL.
        4. Sleep ``pre_pdf_delay_seconds`` (Atala backend materialization).
        5. GET the PDF URL up to ``pdf_fetch_retries`` times; assert
           ``%PDF`` magic on the body; write to ``dest_path``.

        All URL parts come from ``self.config['doc_image_url_pattern']`` (with
        sensible defaults) so a sibling AcclaimWeb tenant can override.
        """
        # Warm session lazily — Broward's disclaimer must be accepted before
        # the JumpToInstrumentNumber route resolves.
        if not self._session_warmed:
            if not self.warm_session():
                return {
                    "status": "error",
                    "doc": doc_num,
                    "phase": "warm_session",
                    "error": self.last_failure or "session warm-up failed",
                }

        # Fast path: the three-step JSON grid already returned the
        # TransactionItemId (== the image token) — skip the jump GET.
        # Disabled on tenants whose image flow needs the opaque jump-detail
        # token (Duval/OnCore) — there the numeric grid token 500s.
        if not self._dip_image_token_from_detail:
            cached_token = (self.row_extras.get(doc_num) or {}).get("transaction_item_id")
            if cached_token:
                token = str(cached_token)
                src_via = "grid_cache"
                return self._download_pdf_with_token(doc_num, token, src_via, dest_path)

        # Step 1 — jump endpoint, harvest token.
        jump_path = self._dip_jump_url.format(
            record_type=self._dip_record_type, doc_num=doc_num
        )
        # Cache-buster mirrors the bulk-downloader reference (Broward IIS
        # otherwise serves a stale shell on a hot session).
        jump_url = urljoin(self._base_url, jump_path) + (
            ("&" if "?" in jump_path else "?") + f"_={int(time.time() * 1000)}"
        )
        try:
            jr = self.session.get(jump_url, timeout=45)
        except Exception as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "jump",
                "error": f"network: {exc}",
            }
        if jr.status_code != 200:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "jump",
                "error": f"HTTP {jr.status_code}",
            }
        token = self._extract_token(jr.text)
        if not token:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "token_extract",
                "error": "no token found in jump response",
            }
        src_via = "jump_response"
        return self._download_pdf_with_token(doc_num, token, src_via, dest_path)

    def _download_pdf_with_token(
        self, doc_num: str, token: str, src_via: str, dest_path: Path
    ) -> Dict[str, Any]:
        """Steps 2–5 of the Atala image flow, given a transaction token."""
        # Step 2 — warm the image cache (best-effort).
        sir_path = self._dip_start_image_retrieval.format(token=token)
        sir_url = urljoin(self._base_url, sir_path)
        try:
            self.session.get(sir_url, timeout=30)
        except Exception as exc:
            # Non-fatal — viewer GET often works without this warm-up. Log
            # the issue in the error payload only if downstream phases fail.
            print(f"  [download_pdf] start_image_retrieval warning: {exc}")

        # Step 3 — viewer HTML; scrape the WebAtalaCache PDF href.
        viewer_path = self._dip_viewer_url.format(token=token)
        viewer_url = urljoin(self._base_url, viewer_path)
        try:
            vr = self.session.get(viewer_url, timeout=60)
        except Exception as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "viewer",
                "error": f"network: {exc}",
                "token": token,
            }
        if vr.status_code != 200:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "viewer",
                "error": f"HTTP {vr.status_code}",
                "token": token,
            }
        m = self._dip_pdf_href_regex.search(vr.text)
        if not m:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "extract_pdf_url",
                "error": "WebAtalaCache PDF href not found in viewer HTML",
                "token": token,
            }
        cache_path = m.group(1).lstrip("/")
        # PDF URL is rooted at the tenant origin (NOT the AcclaimWeb path).
        from urllib.parse import urlparse
        parsed = urlparse(self._base_url)
        pdf_url = f"{parsed.scheme}://{parsed.netloc}/{cache_path}"

        # Step 4 — backend materialization delay.
        if self._dip_pre_pdf_delay_seconds > 0:
            time.sleep(self._dip_pre_pdf_delay_seconds)

        # Step 5 — fetch PDF bytes with retry.
        last_status = None
        for attempt in range(1, self._dip_pdf_fetch_retries + 1):
            try:
                pr = self.session.get(
                    pdf_url,
                    headers={
                        "Referer": viewer_url,
                        "Accept": "application/pdf,*/*",
                    },
                    timeout=120,
                )
            except Exception as exc:
                last_status = f"network: {exc}"
                if attempt < self._dip_pdf_fetch_retries:
                    time.sleep(self._dip_pdf_retry_delay_seconds)
                continue
            last_status = pr.status_code
            content = pr.content or b""
            if pr.status_code == 200 and content[:4] == b"%PDF":
                dest_path = Path(dest_path)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(content)
                return {
                    "status": "success",
                    "size": len(content),
                    "src_via": src_via,
                    "pdf_url": pdf_url,
                    "token": token,
                }
            if attempt < self._dip_pdf_fetch_retries:
                time.sleep(self._dip_pdf_retry_delay_seconds)
        return {
            "status": "error",
            "doc": doc_num,
            "phase": "fetch_pdf",
            "error": f"PDF fetch failed (last status={last_status})",
            "pdf_url": pdf_url,
            "token": token,
        }

    # ----------------------------------------------------------- extract_results

    def extract_results(self, html: str) -> List[DocumentRecord]:
        """Parse a Kendo / Telerik grid HTML fragment into DocumentRecord rows.

        Broward (Telerik MVC skin on AcclaimWeb) emits one ``<tr class="t-row">``
        per result. CA San Diego AcclaimWeb uses ``tr.k-master-row``. We accept
        either.
        """
        documents: List[DocumentRecord] = []
        if not html:
            return documents

        soup = BeautifulSoup(html, "lxml")

        rows = soup.select(
            "tr.t-row, tr.t-alt, tr.k-master-row, tr.k-alt"
        )

        # Fallback: any <tbody> rows under a <table> with grid-like class.
        if not rows:
            for tbl in soup.find_all("table"):
                cls = " ".join(tbl.get("class", []))
                if "grid" in cls.lower() or "t-grid" in cls or "k-grid" in cls:
                    rows = tbl.select("tbody tr")
                    if rows:
                        break

        seen = set()
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue

            # Locate the doc-number cell. Prefer regex match; fall back to first
            # cell text or any <a> with a doc-number-looking string.
            doc_num = ""
            doc_idx = -1
            for i, txt in enumerate(cells):
                if txt and self._doc_number_re.match(txt):
                    doc_num = txt
                    doc_idx = i
                    break
            if not doc_num:
                # Look for an <a> inside any cell whose text matches.
                for i, td in enumerate(row.find_all("td")):
                    a = td.find("a")
                    if a:
                        a_txt = a.get_text(strip=True)
                        if a_txt and self._doc_number_re.match(a_txt):
                            doc_num = a_txt
                            doc_idx = i
                            break
            if not doc_num or doc_num in seen:
                continue
            seen.add(doc_num)

            # Heuristic column scan (same shape as Selenium adapter).
            rec_date = doc_type = grantors = grantees = pages = ""
            for i, txt in enumerate(cells):
                if i == doc_idx or not txt:
                    continue
                if not rec_date and re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", txt):
                    rec_date = txt
                elif not pages and re.match(r"^\d{1,3}$", txt) and int(txt) <= 500:
                    pages = txt
                elif (
                    not doc_type
                    and 2 < len(txt) < 60
                    and re.search(r"[A-Za-z]", txt)
                    and "," not in txt
                    and ";" not in txt
                ):
                    doc_type = txt
                elif len(txt) >= 2:
                    if not grantors:
                        grantors = txt
                    elif not grantees:
                        grantees = txt

            documents.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=grantors,
                    grantees=grantees,
                    grantor_grantees=(
                        f"{grantors}; {grantees}"
                        if grantors and grantees
                        else (grantors or grantees)
                    ),
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages=pages,
                )
            )

        return documents

    # ------------------------------------------------------------- jar helpers

    @staticmethod
    def _cookies_expired(payload: Dict) -> bool:
        """Return True if the jar payload has an `expires_at` in the past."""
        exp = payload.get("expires_at")
        if not exp:
            return False
        try:
            return datetime.fromisoformat(exp) < datetime.now()
        except Exception:
            return False

    def _save_cookie_jar(self, cookies: Dict[str, str]) -> None:
        """Persist freshly-minted cookies for future runs."""
        try:
            self._cookie_jar_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "minted_at": datetime.now().isoformat(),
                "cookies": [
                    {"name": k, "value": v, "domain": "officialrecords.broward.org", "path": "/"}
                    for k, v in cookies.items()
                ],
            }
            with self._cookie_jar_path.open("w") as f:
                json.dump(payload, f, indent=2)
            print(f"  [warm_session] persisted cookies to {self._cookie_jar_path}")
        except Exception as exc:
            print(f"  [warm_session] failed to persist cookie jar: {exc}")


# ---------------------------------------------------------------------------
# Legacy compatibility shim — kept solely to satisfy any old test imports.
# Browser-based cookie minting is NO LONGER USED — Cloudflare clearance is
# handled at the TLS layer by curl_cffi's Chrome impersonation profile.
# ---------------------------------------------------------------------------

def mint_broward_cookies() -> Dict[str, str]:  # pragma: no cover
    """Deprecated. Returns empty dict so legacy callers don't crash.

    This function used to spin up undetected-chromedriver to mint Cloudflare
    cookies. As of 2026-05-22, ``curl_cffi.Session(impersonate="chrome120")``
    passes Cloudflare's TLS challenge layer directly — no browser involved.
    Existing call sites should be removed; this shim is kept only to avoid
    breaking any import that hasn't been updated yet.
    """
    return {}
