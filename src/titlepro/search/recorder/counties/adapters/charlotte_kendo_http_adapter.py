"""Charlotte County (FL) HTTP-First Recorder Adapter — recording.charlotteclerk.com.

Platform: PROPRIETARY ASP.NET Core MVC + Kendo UI (Roger D. Eaton, Clerk)
Not AcclaimWeb, not Tyler, not PublicSoft — a custom build by the county.

Probe provenance (2026-06-18, US datacenter egress 149.40.62.65)
-----------------------------------------------------------------
Portal fully reachable via curl_cffi safari17_2_ios (Cloudflare present but passes).
reCAPTCHA v3 is the only gate — site key 6LeA9DIpAAAAAJ51BtGfYnFHLkYc1w6EaNv29ED0
Verified: fake tokens return {"verified": false}; real 2Captcha tokens required.
After Verify succeeds, the Kendo grid POST returns JSON with no further CF challenge.

Search flow (reverse-engineered from searchName.js + renderViewDocuments.js,
kendo-deferred-scripts-*.js, 2026-06-18):
-----------------------------------------
1. ``GET /Search/Name``
   Harvest CSRF anti-forgery token + siteKey from page HTML.

2. ``GET /Home/Verify?token=<reCAPTCHA_v3_token>``  (action: ``search/name``)
   Returns JSON ``true`` or ``false``. Must be ``true`` to proceed.

3. ``GET /Render/ViewDocuments?inFromSearch=NAME&inLastName=…&inFirstName=…
       &inCompressedName=…&inDirectReverse=0&inFilterCriteria=0
       &inBusinessPersonal=P&inStartDate=MM/DD/YYYY&inEndDate=MM/DD/YYYY
       &inDocumentTypeIds=24,109,…``
   Loads the Kendo-grid page; extracts the per-page search params as ``data-message``
   attributes on hidden divs. A second reCAPTCHA execute (action ``render/viewdocument``)
   fires client-side, then the Kendo DataSource calls step 4.

4. ``POST /Render/GetDocumentView``  (Content-Type: application/x-www-form-urlencoded)
   Kendo MVC-AJAX transport payload (from ``additionalParmDocumentView()`` + paging):
   - ``__RequestVerificationToken``     anti-forgery token
   - ``inFromSearch``                   "NAME"
   - ``inDirectReverse``                "0"=Both "1"=Direct "2"=Reverse
   - ``inFilterCriteria``               "0"=StartsWith "1"=Contains "2"=Equals
   - ``inCompressedName``               LastName+FirstName (special-chars+spaces stripped)
   - ``inBookType``, ``inBook``, ``inPage``, ``inCaseNumber``, ``inInstrumentNumber``,
     ``inLegal``, ``inDocumentTypeIds``
   - ``inStartDate``, ``inEndDate``     MM/DD/YYYY
   - ``inToken``                        reCAPTCHA v3 token (action ``render/viewdocument``)
   - ``take``, ``skip``, ``page``, ``pageSize``  Kendo paging (default pageSize 25)
   - ``sort``, ``group``, ``filter``, ``aggregate``  (empty strings)

   Response: JSON ``{"Data":[...], "Total":N, "Errors":null}``

Result row fields (from kendo-deferred-scripts ``columns`` definition):
   DocumentId, PageCount, Direct (grantors), Reverse (grantees), DirectReverse,
   BookNumber, PageNumber, ClerkFileNumber, RecordDate (date), DocTypeDescription,
   Legal, Parcel, Consideration, Status, CaseNumber, County, TypeConstruction,
   RoadName, SectionName, ProjectName

Direct retrieval:
   ``POST /Render/GetDocumentIdFromInstrument`` — body: CSRF + inInstrument
   ``POST /Render/GetDocumentIdFromBookPage``   — body: CSRF + inBookType + inBook + inPage
   ``POST /Render/GetDocumentById``             — body: CSRF + inDocumentId

Document type IDs (from ``GET /Search/GetDocumentTypesCodeDesc``):
   D=24, DB=109, AGD=5 (deed family) — see config for full map.

reCAPTCHA v3 strategy:
   - Solved via 2Captcha API (same pattern as tyler_http_adapter.py).
   - CAPTCHA_API_KEY env-var → inline 2Captcha call.
   - Injected CaptchaSolverBase → ``solve_recaptcha_v3(sitekey, page_url, action)``.
   - Token cached for up to 110 s (reCAPTCHA v3 tokens expire in ~120 s).
   - We solve once per search page (action ``render/viewdocument``) and reuse
     across paged reads within the same session.
"""

from __future__ import annotations

import os
import re
import time
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlencode, quote

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord

# ── 2Captcha endpoints ──────────────────────────────────────────────────────
_2CAPTCHA_SUBMIT = "https://2captcha.com/in.php"
_2CAPTCHA_RESULT = "https://2captcha.com/res.php"

DEFAULT_IMPERSONATE = "safari17_2_ios"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _strip_name(s: str) -> str:
    """Strip special characters and spaces — Charlotte's ``removeSpecialCharacters``."""
    s = re.sub(r"[&/\\#,+()$~%.'\":;*?<>{}]", "", s)
    s = re.sub(r"\s", "", s)
    return s


class CharlotteKendoHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP adapter for Charlotte County FL official records (recording.charlotteclerk.com).

    Two search types supported (per Tony directive #2 deed-first):
    - Name search (primary)
    - Parcel/APN search (via inCaseNumber field which accepts parcel IDs)
    """

    # ── class-level constants ────────────────────────────────────────────────
    DEFAULT_CONFIG: Dict[str, Any] = {
        "county_id": "fl_charlotte",
        "county_name": "Charlotte",
        "state": "FL",
        "platform": "charlotte_kendo_http",
        "base_url": "https://recording.charlotteclerk.com/",
        "search_page_url": "https://recording.charlotteclerk.com/Search/Name",
        "verify_url": "https://recording.charlotteclerk.com/Home/Verify",
        "view_documents_url": "https://recording.charlotteclerk.com/Render/ViewDocuments",
        "get_document_view_url": "https://recording.charlotteclerk.com/Render/GetDocumentView",
        "get_doc_types_url": "https://recording.charlotteclerk.com/Search/GetDocumentTypesCodeDesc",
        "get_doc_by_instrument_url": "https://recording.charlotteclerk.com/Render/GetDocumentIdFromInstrument",
        "get_doc_by_bookpage_url": "https://recording.charlotteclerk.com/Render/GetDocumentIdFromBookPage",
        "recaptcha_site_key": "6LeA9DIpAAAAAJ51BtGfYnFHLkYc1w6EaNv29ED0",
        "recaptcha_action_search": "search/name",
        "recaptcha_action_view": "render/viewdocument",
        "recaptcha_page_url": "https://recording.charlotteclerk.com/Search/Name",
        "captcha_required": True,
        "captcha_type": "recaptcha_v3",
        "captcha_timeout_seconds": 180,
        "recaptcha_token_max_age_seconds": 110,
        # Deed-first doc type IDs (from GetDocumentTypesCodeDesc, live 2026-06-18)
        # D:24, DB:109, AGD:5, QC: (Quit Claim Deed — confirm live), TD:201
        "deed_doc_type_ids": [24, 109, 5],
        "all_doc_type_ids": [],  # empty = all types
        # Search params
        "start_date": "01/01/1921",  # portal's minimum date
        "name_filter_criteria": "0",  # StartsWith
        "page_size": 25,
        "impersonate_profile": "safari17_2_ios",
        "status": "in_progress",
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        start_date: str = "01/01/1990",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        cfg = {**self.DEFAULT_CONFIG, **(config or {})}
        # ctor-level dates take precedence over config defaults when explicitly provided
        if start_date != "01/01/1990":
            cfg["start_date"] = start_date
        if end_date is not None:
            cfg["end_date"] = end_date
        self._cfg = cfg

        self._base_url: str = cfg["base_url"]
        self._search_page_url: str = cfg["search_page_url"]
        self._verify_url: str = cfg["verify_url"]
        self._view_documents_url: str = cfg["view_documents_url"]
        self._get_document_view_url: str = cfg["get_document_view_url"]

        self._recaptcha_sitekey: str = cfg["recaptcha_site_key"]
        self._recaptcha_page_url: str = cfg["recaptcha_page_url"]
        self._recaptcha_action_search: str = cfg.get("recaptcha_action_search", "search/name")
        self._recaptcha_action_view: str = cfg["recaptcha_action_view"]
        self._captcha_timeout: int = int(cfg.get("captcha_timeout_seconds", 180))
        self._token_max_age: int = int(cfg.get("recaptcha_token_max_age_seconds", 110))

        self._captcha_api_key: Optional[str] = os.environ.get("CAPTCHA_API_KEY")
        self._captcha_solver = None  # injected via set_captcha_solver()

        # Token caches (v3 tokens expire ~120 s; we cache for max 110 s)
        # Two separate caches: one for search/name (Verify step), one for render/viewdocument (POST step)
        self._cached_token: Optional[str] = None
        self._cached_token_minted_at: float = 0.0
        self._cached_search_token: Optional[str] = None
        self._cached_search_token_minted_at: float = 0.0
        self._session_verified: bool = False  # True once /Home/Verify returned true

        # Session state
        self._csrf_token: Optional[str] = None
        self._session = _cffi_requests.Session(impersonate=cfg.get("impersonate_profile", DEFAULT_IMPERSONATE))
        self._session.headers.update(EXTRA_HEADERS)

        self.last_failure: Optional[str] = None

    # ── BaseRecorderSearch ABC stubs ─────────────────────────────────────────
    @property
    def county_name(self) -> str:
        return self._cfg.get("county_name", "Charlotte")

    @property
    def base_url(self) -> str:
        return self._base_url

    def setup_driver(self):
        pass  # No Selenium — Tony directive #1

    def navigate_to_search(self):
        pass

    def extract_results(self) -> List[DocumentRecord]:
        return []

    def return_to_search(self):
        pass

    # ── captcha solver wiring ────────────────────────────────────────────────
    def set_captcha_solver(self, solver) -> None:
        """Inject a CaptchaSolverBase (for tests or registry DI)."""
        self._captcha_solver = solver

    def _solve_recaptcha_v3(self, action: str) -> Optional[str]:
        """Solve reCAPTCHA v3 via injected solver or inline 2Captcha API.

        Returns the reCAPTCHA v3 token, or None on failure.
        Tokens are cached **per action** so a search/name token is never
        reused for a render/viewdocument POST (different action → different
        Google score context; reusing stale/wrong-action tokens silently fails
        the server-side score check).

        * action == ``self._recaptcha_action_search``  → cache: _cached_search_token
        * any other action                             → cache: _cached_token
        """
        # Select the per-action cache slot
        use_search_cache = (action == self._recaptcha_action_search)
        if use_search_cache:
            cached = self._cached_search_token
            minted_at = self._cached_search_token_minted_at
        else:
            cached = self._cached_token
            minted_at = self._cached_token_minted_at

        # Reuse cached token while fresh
        if cached and (time.time() - minted_at) < self._token_max_age:
            return cached

        sitekey = self._recaptcha_sitekey
        page_url = self._recaptcha_page_url

        def _store(token: str) -> None:
            """Write token into the correct cache slot."""
            if use_search_cache:
                self._cached_search_token = token
                self._cached_search_token_minted_at = time.time()
            else:
                self._cached_token = token
                self._cached_token_minted_at = time.time()

        # Strategy A: injected solver (tests / DI)
        if self._captcha_solver is not None:
            solve_fn = getattr(self._captcha_solver, "solve_recaptcha_v3", None)
            if solve_fn is None:
                # Fall back to v2 solver if v3 not available
                solve_fn_v2 = getattr(self._captcha_solver, "solve_recaptcha_v2", None)
                if solve_fn_v2:
                    token = solve_fn_v2(sitekey, page_url)
                else:
                    token = None
            else:
                token = solve_fn(sitekey, page_url, action)
            if token:
                _store(token)
            else:
                self.last_failure = "captcha_solver_failed"
            return token

        # Strategy B: inline 2Captcha API
        if not self._captcha_api_key:
            print("  [captcha] CAPTCHA_API_KEY not set — cannot solve via 2Captcha")
            self.last_failure = "captcha_api_key_missing"
            return None

        try:
            import requests as _vanilla_requests

            # Submit reCAPTCHA v3 task
            sub = _vanilla_requests.post(
                _2CAPTCHA_SUBMIT,
                data={
                    "key": self._captcha_api_key,
                    "method": "userrecaptcha",
                    "version": "v3",
                    "action": action,
                    "min_score": "0.3",
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
            print(f"  [captcha] 2Captcha task_id={task_id}, waiting for token…")

            t0 = time.time()
            while (time.time() - t0) < self._captcha_timeout:
                time.sleep(5)
                pr = _vanilla_requests.get(
                    _2CAPTCHA_RESULT,
                    params={"key": self._captcha_api_key, "action": "get", "id": task_id, "json": 1},
                    timeout=15,
                )
                pr_js = pr.json()
                if pr_js.get("status") == 1:
                    token = pr_js["request"]
                    _store(token)
                    print(f"  [captcha] token received (len={len(token)})")
                    return token
                if pr_js.get("request") != "CAPCHA_NOT_READY":
                    print(f"  [captcha] 2Captcha poll error: {pr_js}")
                    self.last_failure = "captcha_poll_failed"
                    return None

            print("  [captcha] 2Captcha timed out")
            self.last_failure = "captcha_timeout"
            return None
        except Exception as exc:
            print(f"  [captcha] 2Captcha exception: {exc}")
            self.last_failure = f"captcha_exception:{exc}"
            return None

    # ── session / CSRF ───────────────────────────────────────────────────────
    def _refresh_csrf(self) -> Optional[str]:
        """GET /Search/Name and extract the anti-forgery token."""
        try:
            r = self._session.get(self._search_page_url, timeout=20)
            r.raise_for_status()
            tokens = re.findall(
                r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text
            )
            if tokens:
                self._csrf_token = tokens[0]
                return self._csrf_token
            print("  [charlotte] no CSRF token found in Search/Name page")
            return None
        except Exception as exc:
            print(f"  [charlotte] CSRF refresh failed: {exc}")
            return None

    def warm_session(self) -> bool:
        """Establish session (CSRF token). Returns True on success."""
        csrf = self._refresh_csrf()
        return csrf is not None

    def _call_verify(self, token: str) -> bool:
        """GET /Home/Verify?token=<v3_token> — must return JSON true.

        Per the documented search flow (Step 2), this must succeed before
        GetDocumentView will return JSON. Without it the Kendo POST returns HTML
        (the session is not flagged as verified by the server).
        """
        try:
            r = self._session.get(
                self._verify_url,
                params={"token": token},
                timeout=20,
                headers={"Accept": "application/json, text/plain, */*"},
            )
            if r.status_code == 200:
                text = r.text.strip().lower()
                # Server returns JSON true or "true" string
                if text in ("true", "1", '"true"') or text.startswith("true"):
                    self._session_verified = True
                    print("  [charlotte] /Home/Verify returned true — session verified")
                    return True
                print(f"  [charlotte] /Home/Verify returned: {r.text[:80]!r}")
            else:
                print(f"  [charlotte] /Home/Verify HTTP {r.status_code}")
        except Exception as exc:
            print(f"  [charlotte] /Home/Verify failed: {exc}")
        return False

    # ── core search ──────────────────────────────────────────────────────────
    def perform_search(
        self,
        name: Optional[str] = None,
        doc_type: str = "DEED",
        party_type: str = "Both",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        parcel_id: Optional[str] = None,
        doc_type_ids: Optional[List[int]] = None,
        last_name: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Search Charlotte recorder. Implements Tony's deed-first directive.

        Args:
            name: "LASTNAME FIRSTNAME" or "LASTNAME" — handles both.
            last_name / first_name: alternative kwargs (assembled to name internally).
            doc_type: "DEED" (uses deed_doc_type_ids), "" / "ALL" (uses all types),
                      or any other string (currently maps to all types).
            party_type: "Both", "Direct" (grantor), or "Reverse" (grantee).
            start_date: MM/DD/YYYY — defaults to 01/01/1921.
            end_date: MM/DD/YYYY — defaults to today.
            parcel_id: APN/parcel for re-search (Tony directive #2). Sent as
                       inCaseNumber (the portal's multi-use search field).
            doc_type_ids: Override the DocumentTypeId list sent to GetDocumentView.
        """
        self.last_failure = None

        # Resolve name from last_name/first_name kwargs if not provided as positional
        if name is None:
            if last_name:
                name = f"{last_name.strip()} {(first_name or '').strip()}".strip()
            else:
                name = ""

        # Ensure CSRF token
        if not self._csrf_token:
            if not self.warm_session():
                self.last_failure = "session_warmup_failed"
                return []

        # Build name parts from assembled name
        parts = (name or "").strip().split(None, 1)
        last_name = parts[0] if parts else ""
        first_name = parts[1] if len(parts) > 1 else ""
        compressed_name = _strip_name(last_name) + _strip_name(first_name)

        # Date defaults
        s_date = start_date or self._cfg.get("start_date", "01/01/1921")
        e_date = end_date or datetime.now().strftime("%m/%d/%Y")

        # Party type mapping
        party_map = {"Both": "0", "Direct": "1", "Grantor": "1", "Reverse": "2", "Grantee": "2"}
        direct_reverse = party_map.get(party_type, "0")

        # Doc type IDs
        if doc_type_ids is not None:
            ids_str = ",".join(str(i) for i in doc_type_ids)
        elif doc_type.upper() in ("DEED", "D"):
            ids_str = ",".join(str(i) for i in self._cfg.get("deed_doc_type_ids", [24, 109, 5]))
        else:
            ids_str = ""  # all types

        # Step 1a: Solve reCAPTCHA v3 for the Verify gate (action: search/name)
        # This must happen before loading ViewDocuments — Verify "unlocks" the session
        # so GetDocumentView returns JSON instead of HTML.
        if not self._session_verified:
            verify_token = self._solve_recaptcha_v3(self._recaptcha_action_search)
            if verify_token:
                self._call_verify(verify_token)
                # Note: we don't abort on verify failure — some tokens still work
            else:
                print("  [charlotte] verify token unavailable — GetDocumentView may return HTML")

        # Step 1b: Load ViewDocuments page to get fresh CSRF + page-state
        view_params = {
            "inFromSearch": "NAME",
            "inDirectReverse": direct_reverse,
            "inFilterCriteria": self._cfg.get("name_filter_criteria", "0"),
            "inBusinessPersonal": "P",
            "inBusinessName": "",
            "inLastName": last_name,
            "inFirstName": first_name,
            "inMiddleName": "",
            "inSuffix": "",
            "inCompressedName": compressed_name,
            "inBookType": "",
            "inBook": "",
            "inPage": "",
            "inStartDate": s_date,
            "inEndDate": e_date,
            "inCaseNumber": parcel_id or "",
            "inInstrumentNumber": "",
            "inLegal": "",
            "inDocumentTypeIds": ids_str,
        }
        try:
            r_view = self._session.get(
                self._view_documents_url, params=view_params, timeout=25
            )
            r_view.raise_for_status()
        except Exception as exc:
            print(f"  [charlotte] ViewDocuments GET failed: {exc}")
            self.last_failure = f"view_documents_get_failed:{exc}"
            return []

        # Refresh CSRF from the ViewDocuments page
        tokens_view = re.findall(
            r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r_view.text
        )
        if tokens_view:
            self._csrf_token = tokens_view[0]

        # Step 2: Solve reCAPTCHA v3 for the grid data read
        token = self._solve_recaptcha_v3(self._recaptcha_action_view)
        if not token:
            print("  [charlotte] reCAPTCHA v3 solve failed — CAPTCHA_API_KEY required")
            self.last_failure = self.last_failure or "captcha_required"
            return []

        # Step 3: POST to GetDocumentView — paginate until all results fetched
        page_size = int(self._cfg.get("page_size", 25))
        all_docs: List[DocumentRecord] = []
        skip = 0
        page_num = 1
        total_expected = None

        while True:
            post_data = {
                "__RequestVerificationToken": self._csrf_token or "",
                "inFromSearch": "NAME",
                "inDirectReverse": direct_reverse,
                "inFilterCriteria": self._cfg.get("name_filter_criteria", "0"),
                "inCompressedName": compressed_name,
                "inBookType": "",
                "inBook": "",
                "inPage": "",
                "inStartDate": s_date,
                "inEndDate": e_date,
                "inCaseNumber": parcel_id or "",
                "inInstrumentNumber": "",
                "inLegal": "",
                "inDocumentTypeIds": ids_str,
                "inToken": token,
                # Kendo MVC-AJAX paging params
                "take": str(page_size),
                "skip": str(skip),
                "page": str(page_num),
                "pageSize": str(page_size),
                "sort": "",
                "group": "",
                "filter": "",
                "aggregate": "",
            }
            self._session.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": r_view.url,
            })
            try:
                r_data = self._session.post(
                    self._get_document_view_url, data=post_data, timeout=30
                )
            except Exception as exc:
                print(f"  [charlotte] GetDocumentView POST failed: {exc}")
                self.last_failure = f"get_document_view_failed:{exc}"
                break

            if r_data.status_code != 200:
                print(f"  [charlotte] GetDocumentView returned {r_data.status_code}")
                self.last_failure = f"get_document_view_status:{r_data.status_code}"
                break

            # Expect JSON — if HTML returned, reCAPTCHA verify failed
            ct = r_data.headers.get("Content-Type", "")
            if "json" not in ct.lower():
                print(f"  [charlotte] GetDocumentView returned HTML (not JSON) — captcha may have expired")
                self.last_failure = "get_document_view_returned_html"
                break

            try:
                payload = r_data.json()
            except Exception as exc:
                print(f"  [charlotte] JSON parse error: {exc}")
                self.last_failure = "json_parse_error"
                break

            if payload.get("Errors"):
                print(f"  [charlotte] server error: {payload['Errors']}")
                self.last_failure = f"server_error:{payload['Errors']}"
                break

            data_rows = payload.get("Data") or []
            if total_expected is None:
                total_expected = payload.get("Total", 0)
                print(f"  [charlotte] total={total_expected}, page_size={page_size}")

            docs = self._rows_to_documents(data_rows)
            all_docs.extend(docs)

            skip += page_size
            page_num += 1
            if skip >= (total_expected or 0) or not data_rows:
                break

        print(f"  [charlotte] fetched {len(all_docs)} documents for '{name}'")
        return all_docs

    # ── result row → DocumentRecord ──────────────────────────────────────────
    def _rows_to_documents(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        """Convert Kendo grid result rows to DocumentRecord objects.

        Charlotte grid row keys (from kendo-deferred-scripts columns definition):
        DocumentId, PageCount, Direct (grantors), Reverse (grantees), DirectReverse,
        BookNumber, PageNumber, ClerkFileNumber, RecordDate, DocTypeDescription,
        Legal, Parcel, Consideration, Status, CaseNumber, County.
        """
        docs: List[DocumentRecord] = []
        for row in rows:
            # Document number — prefer ClerkFileNumber; fall back to DocumentId
            doc_num = str(
                row.get("ClerkFileNumber")
                or row.get("CaseNumber")
                or row.get("DocumentId")
                or ""
            ).strip()

            grantors = str(row.get("Direct") or "").strip()
            grantees = str(row.get("Reverse") or "").strip()
            grantor_grantees = str(row.get("DirectReverse") or f"{grantors} / {grantees}").strip()
            doc_type = str(row.get("DocTypeDescription") or "").strip()

            # RecordDate arrives as "/Date(ms)/" or "YYYY-MM-DDTHH:MM:SS"
            rec_raw = row.get("RecordDate") or ""
            recording_date = self._parse_date(rec_raw)

            pages = str(row.get("PageCount") or "").strip()
            book = str(row.get("BookNumber") or "").strip()
            page_val = str(row.get("PageNumber") or "").strip()
            if book or page_val:
                if not doc_num:
                    doc_num = f"{book}/{page_val}"

            docs.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=grantors,
                    grantees=grantees,
                    grantor_grantees=grantor_grantees,
                    document_type=doc_type,
                    recording_date=recording_date,
                    pages=pages,
                )
            )
        return docs

    @staticmethod
    def _parse_date(raw: str) -> str:
        """Parse '/Date(ms)/' or ISO date strings to MM/DD/YYYY."""
        if not raw:
            return ""
        # Kendo /Date(ms)/ format
        m = re.search(r"/Date\((\d+)\)/", raw)
        if m:
            ts = int(m.group(1)) / 1000
            return datetime.utcfromtimestamp(ts).strftime("%m/%d/%Y")
        # ISO format
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:19], fmt).strftime("%m/%d/%Y")
            except ValueError:
                pass
        return raw

    # ── convenience: deed-first helper ───────────────────────────────────────
    def search_deed_first(
        self,
        name: str,
        party_type: str = "Both",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Tony directive #2: first search DEEDs only, then all docs.

        Returns all documents from the deed-first + full sweep combined,
        deduplicated by document number.
        """
        deed_results = self.perform_search(
            name, doc_type="DEED", party_type=party_type,
            start_date=start_date, end_date=end_date,
        )
        all_results = self.perform_search(
            name, doc_type="ALL", party_type=party_type,
            start_date=start_date, end_date=end_date,
        )
        seen: set = set()
        combined: List[DocumentRecord] = []
        for doc in deed_results + all_results:
            key = doc.document_number or doc.recording_date
            if key and key not in seen:
                seen.add(key)
                combined.append(doc)
        return combined

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
