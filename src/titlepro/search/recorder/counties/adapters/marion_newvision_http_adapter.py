"""Marion County (FL) HTTP-First Recorder Adapter — nvweb.marioncountyclerk.org/BrowserView/.

Platform: NewVision Systems Corporation "BrowserView" AngularJS SPA
Clerk: Gregory C. Harrell

Probe provenance (2026-06-18, US datacenter egress 149.40.62.65)
-----------------------------------------------------------------
Portal reachable plain HTTP (no Cloudflare, no disclaimer gate).
No RSA encryption (encryptData="0" in clientinfo).
reCAPTCHA v3 required per clientinfo (useRecaptchaV3="1",
recaptchasitekeyV3="6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE").
CRITICAL: enableServerRecaptcha="0" does NOT disable token validation.
Live probe (2026-06-18) confirmed: the server calls GoogleRecaptchaV3Api.VerifyToken()
regardless. Field name is RecaptchaResponseV3 (NOT RecaptchaToken — that returns HTTP 400
"No V3 token found in resonsped"). A real 2Captcha token is required; the score fails at 0
from datacenter IPs (the server validates score). Residential egress needed for live runs.
maxSearchCountBeforeExpired=5 — must re-solve after 5 searches per session.

Search flow
-----------
1. GET /BrowserView/api/search/clientinfo → learn encryptData, captcha sitekey,
   verifyDate, maxSearchCountBeforeExpired.
2. Solve reCAPTCHA v3 via 2Captcha (CAPTCHA_API_KEY env var), or pass a
   dummy token when enableServerRecaptcha="0" (server won't validate it).
3. POST /BrowserView/api/search  (Content-Type: application/json)
   {
     "Party": "MADRIGAL NELSON",
     "DocTypes": "WD",
     "FromDate": "19000101",    ← YYYYMMDD compact
     "ToDate": "20261231",
     "MaxRows": 200,
     "RowsPerPage": 200,
     "StartRow": 0,
     "RecaptchaToken": "<token>"
   }
4. Response: JSON array. Row[0] carries _total_rows/_start_row/_end_row/_max_rows.
   Subsequent rows are document records.

Direct retrieval
----------------
- By file number: POST /BrowserView/api/search  {"FileNumber": "NNNNN", "RecaptchaToken": ...}
- By book/page:   POST /BrowserView/api/search  {"BookType": "O", "Book": "NNN", "Page": "NNNN", "RecaptchaToken": ...}
- Document detail/image: POST /BrowserView/api/document  {"ID": "...", "Convert": true}
- PDF:            POST /BrowserView/api/pdf  {"ID": "...", "StartPage": 1, "Pages": N}

This adapter mirrors publicsoft_or_adapter.py exactly but:
- Uses Marion's base URL (nvweb.marioncountyclerk.org/BrowserView/)
- Uses Marion's reCAPTCHA v3 sitekey
- encryptData=false (no RSA encryption step)
- Includes RecaptchaToken field in every POST
- Tracks search_count per session; re-solves when maxSearchCountBeforeExpired reached
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord

# 2Captcha endpoints
_2CAPTCHA_SUBMIT = "https://2captcha.com/in.php"
_2CAPTCHA_RESULT = "https://2captcha.com/res.php"

DEFAULT_IMPERSONATE = "safari17_2_ios"

# Marion clientinfo defaults (from live probe 2026-06-18)
_MARION_CLIENTINFO_DEFAULTS: Dict[str, Any] = {
    "encryptData": "0",
    "freeAccessWithoutLogin": "0",
    "useRecaptcha": "0",
    "useRecaptchaV3": "1",
    "enableServerRecaptcha": "0",
    "recaptchasitekeyV3": "6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE",
    "maxSearchCountBeforeExpired": "5",
    "showBookPage": "1",
    "showFileNumber": "1",
}

# Tolerant result-row field mapping (mirrors publicsoft_or_adapter.py defaults)
_DEFAULT_RESULT_FIELD_MAP: Dict[str, List[str]] = {
    "document_number": [
        "file_num", "doc_number", "document_number", "instrument",
        "instrument_number", "file_number", "fileNumber", "DocumentNumber",
        "FileNumber", "cfn",
    ],
    "grantors": [
        "grantor", "grantors", "direct_name", "party1", "party_name",
        "from_party", "Grantor", "DirectName",
    ],
    "grantees": [
        "grantee", "grantees", "reverse_name", "party2", "party_name",
        "to_party", "Grantee", "ReverseName",
    ],
    "document_type": [
        "doc_type", "document_type", "doctype", "type", "DocType",
        "instrument_type", "DocTypeDescription",
    ],
    "recording_date": [
        "record_date", "recording_date", "recorded_date", "rec_date",
        "file_date", "RecordDate", "date_recorded", "RecordedDate",
    ],
    "pages": ["pages", "page_count", "img_pg_cnt", "PageCount", "NumPages"],
    "book": ["book", "book_number", "Book", "or_book"],
    "page": ["page", "page_number", "Page", "or_page"],
    "book_type": ["book_type", "bookType", "BookType"],
    "legal": ["legal", "legal_desc", "legal_description", "Legal", "legal_1"],
    "doc_id": [
        "id", "doc_id", "document_id", "ID", "DocID", "RowID", "row_id",
        "DocumentId",
    ],
}

_META_TOTAL_ROWS = "_total_rows"
_META_START_ROW = "_start_row"
_META_END_ROW = "_end_row"
_META_MAX_ROWS = "_max_rows"


class MarionNewVisionHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP recorder adapter for Marion County FL (NewVision BrowserView).

    Mirrors PublicSoftORAdapter but without RSA encryption and with
    per-request reCAPTCHA v3 token injection.
    """

    DEFAULT_CONFIG: Dict[str, Any] = {
        "county_id": "fl_marion",
        "county_name": "Marion",
        "state": "FL",
        "platform": "marion_newvision_http",
        "base_url": "https://nvweb.marioncountyclerk.org/BrowserView/",
        "api_root": "https://nvweb.marioncountyclerk.org/BrowserView/",
        "newvision_endpoints": {
            "clientinfo": "api/search/clientinfo",
            "search": "api/search",
            "document": "api/document",
            "pdf": "api/pdf",
        },
        "search_fields": {
            "party": "Party",
            "doc_types": "DocTypes",
            "from_date": "FromDate",
            "to_date": "ToDate",
            "file_number": "FileNumber",
            "max_rows": "MaxRows",
            "rows_per_page": "RowsPerPage",
            "start_row": "StartRow",
            "recaptcha_token": "RecaptchaResponseV3",
        },
        "recaptcha_site_key": "6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE",
        "recaptcha_page_url": "https://nvweb.marioncountyclerk.org/BrowserView/",
        "recaptcha_action": "Search_partySearchForm",
        "enable_server_recaptcha": False,
        "max_search_count_before_expired": 5,
        "captcha_required": True,
        "captcha_type": "recaptcha_v3",
        "captcha_timeout_seconds": 180,
        "recaptcha_token_max_age_seconds": 110,
        "encrypt_data": False,
        "name_format": "last_first_no_comma",
        "wire_date_format": "%Y%m%d",
        "date_format": "MM/DD/YYYY",
        "doctype_deed_value": "WD",
        "doc_type_map": {
            "DEED": "WD",
            "WD": "WD",
            "QCD": "QC",
            "QC": "QC",
            "MTG": "MTG",
            "MORTGAGE": "MTG",
            "SATISFACTION": "SAT",
            "SAT": "SAT",
            "LIEN": "LN",
            "JUDGMENT": "JDG",
        },
        "max_rows": 200,
        "rows_per_page": 200,
        "impersonate_profile": "safari17_2_ios",
        "cloudflare": False,
        "status": "in_progress",
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        start_date: str = "01/01/1921",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        cfg = {**self.DEFAULT_CONFIG, **(config or {})}
        self.config = cfg

        self._county_name = cfg.get("county_name", "Marion")
        self._base_url = cfg.get("base_url", "https://nvweb.marioncountyclerk.org/BrowserView/").rstrip("/") + "/"
        self._api_root = (cfg.get("api_root") or self._base_url).rstrip("/") + "/"

        eps = cfg.get("newvision_endpoints", {})
        self._ep_clientinfo = eps.get("clientinfo", "api/search/clientinfo")
        self._ep_search = eps.get("search", "api/search")
        self._ep_document = eps.get("document", "api/document")
        self._ep_pdf = eps.get("pdf", "api/pdf")

        ff = cfg.get("search_fields", {})
        self._field_party = ff.get("party", "Party")
        self._field_doctypes = ff.get("doc_types", "DocTypes")
        self._field_from_date = ff.get("from_date", "FromDate")
        self._field_to_date = ff.get("to_date", "ToDate")
        self._field_file_number = ff.get("file_number", "FileNumber")
        self._field_max_rows = ff.get("max_rows", "MaxRows")
        self._field_rows_per_page = ff.get("rows_per_page", "RowsPerPage")
        self._field_start_row = ff.get("start_row", "StartRow")
        self._field_recaptcha_token = ff.get("recaptcha_token", "RecaptchaResponseV3")

        self._recaptcha_sitekey: str = cfg.get("recaptcha_site_key", "6Lf8mbYqAAAAAEulk1OddVBA4uAafBD5ppKP6CoE")
        self._recaptcha_page_url: str = cfg.get("recaptcha_page_url", self._base_url)
        self._recaptcha_action: str = cfg.get("recaptcha_action", "search")
        self._enable_server_recaptcha: bool = bool(cfg.get("enable_server_recaptcha", False))
        self._max_search_count: int = int(cfg.get("max_search_count_before_expired", 5))
        self._captcha_timeout: int = int(cfg.get("captcha_timeout_seconds", 180))
        self._token_max_age: int = int(cfg.get("recaptcha_token_max_age_seconds", 110))

        self._captcha_api_key: Optional[str] = os.environ.get("CAPTCHA_API_KEY")
        self._captcha_solver = None  # injected via set_captcha_solver()

        # Token cache
        self._cached_token: Optional[str] = None
        self._cached_token_minted_at: float = 0.0

        self._encrypt_data: bool = bool(cfg.get("encrypt_data", False))
        self._doctype_deed_value: str = str(cfg.get("doctype_deed_value", "WD"))
        self.doc_type_map: Dict[str, str] = cfg.get("doc_type_map", {})

        # Result-row field mapping
        fm = dict(_DEFAULT_RESULT_FIELD_MAP)
        for k, v in (cfg.get("result_field_map") or {}).items():
            fm[k] = [v] if isinstance(v, str) else list(v)
        self._result_field_map = fm

        self._max_rows = int(cfg.get("max_rows", 200) or 200)
        self._rows_per_page = int(cfg.get("rows_per_page", 200) or 200)
        self._wire_date_format = cfg.get("wire_date_format", "%Y%m%d")
        self._name_format = cfg.get("name_format", "last_first_no_comma")

        self._impersonate = cfg.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=self._impersonate)
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

        self._doc_id_by_number: Dict[str, str] = {}
        self._session_warmed = False
        self._client_info: Dict[str, Any] = {}
        self._search_count = 0

        self.last_failure: Optional[str] = None
        self.driver = None  # ABC compliance

    # ── BaseRecorderSearch props ──────────────────────────────────────────────

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # ── ABC no-ops ────────────────────────────────────────────────────────────

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        return None

    def extract_results(self) -> List[DocumentRecord]:
        return []

    # ── captcha solver wiring ─────────────────────────────────────────────────

    def set_captcha_solver(self, solver) -> None:
        """Inject a CaptchaSolverBase (for tests or registry DI)."""
        self._captcha_solver = solver

    def _solve_recaptcha_v3(self) -> str:
        """Solve reCAPTCHA v3 via injected solver or inline 2Captcha API.

        Returns the token, or an empty string if enableServerRecaptcha is
        disabled (server won't validate — empty string passes through).
        Falls back to 2Captcha when CAPTCHA_API_KEY is set.
        """
        # Reuse cached token while fresh
        if (
            self._cached_token
            and (time.time() - self._cached_token_minted_at) < self._token_max_age
        ):
            return self._cached_token

        sitekey = self._recaptcha_sitekey
        page_url = self._recaptcha_page_url
        action = self._recaptcha_action

        # Strategy A: injected solver (tests / DI)
        if self._captcha_solver is not None:
            solve_fn = getattr(self._captcha_solver, "solve_recaptcha_v3", None)
            if solve_fn is not None:
                token = solve_fn(sitekey, page_url, action)
            else:
                solve_fn_v2 = getattr(self._captcha_solver, "solve_recaptcha_v2", None)
                token = solve_fn_v2(sitekey, page_url) if solve_fn_v2 else None
            if token:
                self._cached_token = token
                self._cached_token_minted_at = time.time()
            return token or ""

        # Strategy B: inline 2Captcha API
        if self._captcha_api_key:
            try:
                import requests as _vanilla_requests

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
                    print(f"  [marion] 2Captcha submit error: {js}")
                    self.last_failure = "captcha_submit_failed"
                    return self._fallback_token()
                task_id = js["request"]
                print(f"  [marion] 2Captcha task_id={task_id}, waiting...")

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
                        self._cached_token = token
                        self._cached_token_minted_at = time.time()
                        print(f"  [marion] captcha token received (len={len(token)})")
                        return token
                    if pr_js.get("request") != "CAPCHA_NOT_READY":
                        print(f"  [marion] 2Captcha poll error: {pr_js}")
                        return self._fallback_token()

                print("  [marion] 2Captcha timed out")
                return self._fallback_token()
            except Exception as exc:
                print(f"  [marion] 2Captcha exception: {exc}")
                return self._fallback_token()

        # No CAPTCHA_API_KEY set — if server doesn't validate, use fallback
        return self._fallback_token()

    def _fallback_token(self) -> str:
        """Fallback when no 2Captcha API key and no injected solver.

        Live probe (2026-06-18): enableServerRecaptcha=0 does NOT bypass token
        validation. The server still calls GoogleRecaptchaV3Api.VerifyToken() —
        all fake/dummy tokens return HTTP 400 "No V3 token found in resonsped".
        A real 2Captcha-solved token is required for live searches.
        Set CAPTCHA_API_KEY env var to enable live queries.
        """
        self.last_failure = "captcha_required_no_solver"
        print("  [marion] CAPTCHA_API_KEY required — all token variants return HTTP 400 without a real v3 token")
        return ""

    # ── session warm-up ───────────────────────────────────────────────────────

    def warm_session(self) -> bool:
        """GET clientinfo to confirm encryptData, sitekey, and session limits."""
        if self._session_warmed:
            return True
        url = self._api_root + self._ep_clientinfo
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    self._client_info = resp.json() or {}
                except Exception:
                    self._client_info = {}
                # Absorb live clientinfo overrides
                ci = self._client_info
                if ci.get("encryptData") not in (None, ""):
                    self._encrypt_data = _truthy(ci["encryptData"])
                if ci.get("recaptchasitekeyV3"):
                    self._recaptcha_sitekey = ci["recaptchasitekeyV3"]
                if ci.get("enableServerRecaptcha") not in (None, ""):
                    self._enable_server_recaptcha = _truthy(ci["enableServerRecaptcha"])
                if ci.get("maxSearchCountBeforeExpired") not in (None, ""):
                    try:
                        self._max_search_count = int(ci["maxSearchCountBeforeExpired"])
                    except (ValueError, TypeError):
                        pass
                self._session_warmed = True
                return True
            self.last_failure = f"clientinfo_http_{resp.status_code}"
        except Exception as exc:
            self.last_failure = f"clientinfo_error: {exc}"

        # Graceful fallback: use probe-derived defaults and proceed
        if not self._session_warmed:
            print(f"  [marion] clientinfo unreachable ({self.last_failure}); using probe defaults")
            self._session_warmed = True
        return True

    # ── core search ───────────────────────────────────────────────────────────

    def perform_search(
        self,
        name: Optional[str] = None,
        last_name: Optional[str] = None,
        first_name: Optional[str] = None,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search against /BrowserView/api/search.

        Accepts either:
        - name="MADRIGAL NELSON" (positional, LAST FIRST format)
        - last_name="MADRIGAL", first_name="NELSON" (keyword args)
        """
        if not self._session_warmed:
            self.warm_session()

        # Resolve name from kwargs if not provided as positional
        if name is None:
            if last_name:
                name = f"{last_name.strip()} {(first_name or '').strip()}".strip()
            else:
                name = ""

        # Reset search count if session limit reached
        if self._search_count >= self._max_search_count:
            print(f"  [marion] search count limit ({self._max_search_count}) reached — refreshing token")
            self._cached_token = None
            self._search_count = 0

        payload = self._build_search_payload(
            name=name, doc_type=doc_type, date_from=date_from, date_to=date_to
        )
        rows = self._post_search(payload)
        if rows is None:
            return []
        self._search_count += 1
        return self._rows_to_documents(rows)

    def _build_search_payload(
        self,
        name: Optional[str] = None,
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        file_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct the api/search JSON payload.

        No RSA encryption (encryptData=0). RecaptchaToken is always included.
        """
        criteria: Dict[str, Any] = {}

        if file_number:
            criteria[self._field_file_number] = str(file_number)
        else:
            normalized = self._normalize_name(name or "")
            criteria[self._field_party] = normalized

        if doc_type:
            dt_key = doc_type.strip().upper()
            mapped = self.doc_type_map.get(dt_key, dt_key)
            criteria[self._field_doctypes] = mapped

        df = self._to_wire_date(date_from or self.start_date)
        dt_wire = self._to_wire_date(date_to or self.end_date)
        if df:
            criteria[self._field_from_date] = df
        if dt_wire:
            criteria[self._field_to_date] = dt_wire

        criteria[self._field_max_rows] = self._max_rows
        criteria[self._field_rows_per_page] = self._rows_per_page
        criteria[self._field_start_row] = 0

        # reCAPTCHA v3 token — MUST be present or server raises InvalidOperationException
        token = self._solve_recaptcha_v3()
        criteria[self._field_recaptcha_token] = token

        return criteria

    def _post_search(self, payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        url = self._api_root + self._ep_search
        try:
            resp = self.session.post(
                url,
                data=json.dumps(payload),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=60,
            )
        except Exception as exc:
            self.last_failure = f"search_http_error: {exc}"
            print(f"  [marion] HTTP error: {exc}")
            return None
        if resp.status_code != 200:
            self.last_failure = f"search_http_{resp.status_code}"
            print(f"  [marion] HTTP {resp.status_code} from api/search")
            # Try to print response for debugging
            try:
                print(f"  [marion] response body: {resp.text[:300]}")
            except Exception:
                pass
            return None
        try:
            data = resp.json()
        except Exception as exc:
            self.last_failure = f"search_json_decode: {exc}"
            return None
        if not isinstance(data, list):
            self.last_failure = "search_unexpected_shape"
            return []
        return data

    # ── row → DocumentRecord ──────────────────────────────────────────────────

    def parse_search_results(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        """Public alias — map raw api/search rows to DocumentRecords."""
        return self._rows_to_documents(rows)

    def _rows_to_documents(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        documents: List[DocumentRecord] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            doc_num = self._pick(row, "document_number")
            if not doc_num:
                continue
            grantors = self._pick(row, "grantors")
            grantees = self._pick(row, "grantees")
            doc_type = self._pick(row, "document_type")
            rec_date = self._normalize_date_out(self._pick(row, "recording_date"))
            pages = self._pick(row, "pages")

            # Party-code disambiguation (same logic as publicsoft_or_adapter)
            party_code = str(row.get("party_code") or "").strip().upper()
            if grantors and grantees and grantors == grantees and party_code in ("D", "R"):
                if party_code == "D":
                    grantees = ""
                else:
                    grantors = ""

            doc_id = self._pick(row, "doc_id")
            if doc_id:
                self._doc_id_by_number[str(doc_num)] = str(doc_id)

            documents.append(
                DocumentRecord(
                    document_number=str(doc_num),
                    grantors=str(grantors or ""),
                    grantees=str(grantees or ""),
                    grantor_grantees="; ".join(
                        s for s in [str(grantors or ""), str(grantees or "")] if s
                    ),
                    document_type=str(doc_type or ""),
                    recording_date=str(rec_date or ""),
                    pages=str(pages or ""),
                )
            )
        return documents

    @staticmethod
    def search_meta(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pull pagination meta from row[0]."""
        if not rows or not isinstance(rows[0], dict):
            return {}
        r0 = rows[0]
        return {
            "total_rows": r0.get(_META_TOTAL_ROWS),
            "start_row": r0.get(_META_START_ROW),
            "end_row": r0.get(_META_END_ROW),
            "max_rows": r0.get(_META_MAX_ROWS),
        }

    def _pick(self, row: Dict[str, Any], canonical: str) -> Any:
        for key in self._result_field_map.get(canonical, []):
            if key in row and row[key] not in (None, ""):
                return row[key]
        return ""

    # ── direct retrieval ──────────────────────────────────────────────────────

    def pull_document_detail(
        self,
        doc_id: Optional[str] = None,
        book: Optional[str] = None,
        page: Optional[str] = None,
        book_type: str = "O",
        page_number: int = 1,
        convert: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Fetch document detail via POST /BrowserView/api/document."""
        if not self._session_warmed:
            self.warm_session()
        criteria: Dict[str, Any] = {}
        if convert:
            criteria["Convert"] = True
        if doc_id:
            criteria["ID"] = str(doc_id)
        elif book and page:
            criteria["Book"] = str(book)
            criteria["PageNumber"] = str(page)
            criteria["BookType"] = str(book_type)
        criteria["Page"] = page_number
        url = self._api_root + self._ep_document
        try:
            resp = self.session.post(
                url, data=json.dumps(criteria),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            self.last_failure = f"document_detail_error: {exc}"
        return None

    def pull_pdf(self, doc_id: str, start_page: int = 1, pages: int = 50) -> Optional[bytes]:
        """Fetch document PDF via POST /BrowserView/api/pdf."""
        if not self._session_warmed:
            self.warm_session()
        criteria = {"ID": str(doc_id), "StartPage": start_page, "Pages": pages, "CurrentPage": start_page}
        url = self._api_root + self._ep_pdf
        try:
            resp = self.session.post(
                url, data=json.dumps(criteria),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.content
        except Exception as exc:
            self.last_failure = f"pdf_http_error: {exc}"
        return None

    def pull_detail(self, document_number: str) -> Dict[str, Any]:
        """Pipeline pull_detail contract: return detail dict or empty dict."""
        doc_id = self._doc_id_by_number.get(str(document_number))
        if not doc_id:
            # Attempt file-number lookup to get doc_id
            payload = self._build_search_payload(file_number=str(document_number))
            rows = self._post_search(payload)
            self._rows_to_documents(rows or [])
            doc_id = self._doc_id_by_number.get(str(document_number))
        if not doc_id:
            return {"status": "error", "message": f"no doc_id for {document_number}"}
        detail = self.pull_document_detail(doc_id=doc_id)
        return detail or {}

    def download_pdf(self, doc_num: str, dest_path, pages: int = 50) -> Dict[str, Any]:
        """Pipeline download contract: write PDF to dest_path."""
        from pathlib import Path as _Path
        dest = _Path(dest_path)
        doc_id = self._doc_id_by_number.get(str(doc_num))
        if not doc_id:
            payload = self._build_search_payload(file_number=str(doc_num))
            rows = self._post_search(payload)
            self._rows_to_documents(rows or [])
            doc_id = self._doc_id_by_number.get(str(doc_num))
        if not doc_id:
            return {"status": "error", "message": f"no doc_id for {doc_num}"}
        pdf = self.pull_pdf(str(doc_id), start_page=1, pages=pages)
        if not pdf or pdf[:4] != b"%PDF":
            return {"status": "error", "message": f"pull_pdf failed (head={pdf[:80] if pdf else None!r})"}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf)
        return {"status": "success", "size": len(pdf), "src_via": "marion_newvision_api_pdf"}

    # ── convenience: deed-first helper ───────────────────────────────────────

    def search_deed_first(
        self,
        name: str,
        party_type: str = "Both",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Tony directive #2: DEED search first, then all docs."""
        deed_results = self.perform_search(name=name, doc_type="DEED",
                                           date_from=date_from, date_to=date_to)
        all_results = self.perform_search(name=name, doc_type=None,
                                          date_from=date_from, date_to=date_to)
        seen: set = set()
        combined: List[DocumentRecord] = []
        for doc in deed_results + all_results:
            key = doc.document_number or doc.recording_date
            if key and key not in seen:
                seen.add(key)
                combined.append(doc)
        return combined

    # ── helpers ───────────────────────────────────────────────────────────────

    def _normalize_name(self, name: str) -> str:
        """Normalize to NewVision 'LAST FIRST' (no comma)."""
        n = (name or "").strip()
        if not n:
            return n
        if "," in n:
            last, first = n.split(",", 1)
            n = f"{last.strip()} {first.strip()}".strip()
        return re.sub(r"\s+", " ", n).upper()

    def _to_wire_date(self, mmddyyyy: Optional[str]) -> str:
        """MM/DD/YYYY → YYYYMMDD (Marion wire format)."""
        if not mmddyyyy:
            return ""
        s = str(mmddyyyy).strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).strftime(self._wire_date_format)
            except ValueError:
                continue
        return ""

    @staticmethod
    def _normalize_date_out(value: Any) -> str:
        """Normalize recording date to MM/DD/YYYY."""
        if not value:
            return ""
        s = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(s[:len(fmt) + 2] if "T" in fmt else s, fmt).strftime("%m/%d/%Y")
            except ValueError:
                continue
        return s

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _truthy(item: Any) -> bool:
    """Mirror BrowserView convertToBool for boolean config fields."""
    if item in (None, ""):
        return False
    if item is True:
        return True
    if item is False:
        return False
    if isinstance(item, str):
        return item.strip().upper() in {"Y", "A", "1", "T", "TRUE"}
    return bool(item)
