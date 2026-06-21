"""
OneCare / AcclaimWeb HTTP-First Recorder Adapter (FL — Lake, Pinellas, etc.).

"OneCare" is the county-facing branding for the Harris/Conduent AcclaimWeb
Official Records platform. Under the hood it is the same ASP.NET MVC +
Telerik MVC / Kendo UI stack used by Broward, Brevard, and Duval — just an
older tenant configuration (Telerik 2012, not the newer Kendo OnCore build
that Duval received in 2022).

Lake County Clerk (FL) was probed live 2026-06-18 (US datacenter egress,
no Cloudflare, no anti-bot). Pinellas County Clerk is Cloudflare-403 from
datacenter; it needs a residential IP / user-minted cf_clearance to reach
(same pattern as Broward's hard block).

Search flow (THREE-STEP, identical structure to Brevard but with key deltas):
    Step 1  POST /search/SearchTypeName?Length=6
               → Telerik HTML treeview of name matches (itemValue inputs)
               → RecordDateFrom/To in response already carry "H:MM:SS AM"
    Step 2  POST /Search/SearchTypePreName
               → HTML shell page; tGrid js init always says total:0 (empty init)
               → data is NOT embedded; grid calls step-3 via ajax on load
    Step 3  POST /Search/GridResults
               REQUIRED HEADER: X-Requested-With: XMLHttpRequest
               → JSON {"data": [...], "total": N}  (camelCase, not PascalCase)

Delta vs Brevard (three_step_json):
    - Step-3 needs the XMLHttpRequest header or the server 500s / blocks
    - JSON uses camelCase keys "data"/"total" (Brevard has camelCase too;
      Duval/OnCore has PascalCase "Data"/"Total")
    - BookType ID for Official Records = 1 on Lake (vs 3 on Brevard)
    - Deed numeric doc-type = 26 on Lake (vs 80 on Brevard)
    - PDF download: /Image/DocumentPdfAllPages/{TransactionItemId}
      (not the WebAtalaCache flow — that's the inline viewer only)
    - Detail: /details/JumpToInstrumentNumber/1/{instr_num}
      (record_type=1 = Official Records on Lake)

Tony Roveda directives honoured:
    1. Pure HTTP — no Selenium/Playwright.
    2. Deed-first: default doc_type for perform_search is "DEED".
    3. All names: caller iterates names; no filtering inside the adapter.
    4–6. Address verification, full-exam, satisfaction linkage are pipeline-level
         concerns — this adapter returns ALL indexed documents for the requested
         name/date-range/doctype.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# ─────────────────────────────────────────────────────────────── constants ──

DEFAULT_IMPERSONATE = "safari17_2_ios"

# Headers added on every session; curl_cffi already sets the full Chrome/Safari
# JA3 fingerprint via impersonation, so only the application-level extras here.
EXTRA_HEADERS: Dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
}

# Headers required on the GridResults (step-3) AJAX POST.
GRID_AJAX_HEADERS: Dict[str, str] = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# MS-AJAX /Date(epoch_ms)/ pattern from AcclaimWeb JSON responses.
_MS_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")

# itemValue hidden inputs inside the Telerik treeview (step-1 response).
_ITEM_VALUE_RE = re.compile(
    r'name="itemValue"\s+type="hidden"\s+value="([^"]+)"'
)

# RecordDate hidden inputs already have " 12:00:00 AM" appended by the server.
_DATE_FROM_RE = re.compile(r'name="RecordDateFrom"[^>]+value="([^"]*)"')
_DATE_TO_RE = re.compile(r'name="RecordDateTo"[^>]+value="([^"]*)"')

# hdnTransactionItemId in the detail page.
_HDN_TXN_RE = re.compile(
    r'hdnTransactionItemId[^"]*"\s+value="([^"]+)"', re.I
)


# ──────────────────────────────────────────────────────── helper functions ──

def _parse_ms_date(raw: str) -> str:
    """Convert /Date(epoch_ms)/ → MM/DD/YYYY.  Returns raw string on failure."""
    m = _MS_DATE_RE.search(str(raw or ""))
    if not m:
        return str(raw or "")
    try:
        ts = int(m.group(1)) / 1000.0
        return datetime.fromtimestamp(ts).strftime("%m/%d/%Y")
    except Exception:
        return str(raw)


def _normalize_name(name: str) -> str:
    """Upper-case, strip commas/extra-whitespace — normalises both
    "SMITH, JOHN" (comma-space) and "SMITH JOHN" (space only) to the same form
    so startswith-matching works across index-format variations."""
    s = (name or "").strip().upper()
    s = s.replace(",", " ")
    return re.sub(r"\s+", " ", s)


# ─────────────────────────────────────────────────────────────── adapter ────

class OneCareHTTPAdapter(BaseRecorderSearch):
    """
    Pure-HTTP search adapter for the AcclaimWeb / OneCare clerk platform.

    Designed against Lake County FL (probed live 2026-06-18).
    Config-driven so the same class handles Pinellas (and any other
    OneCare tenant) once they are reachable from a residential IP.

    Config keys (with Lake defaults shown):
        base_url            "https://officialrecords.lakecountyclerk.org/"
        county_name         "Lake"
        cloudflare_required false
        impersonate_profile "safari17_2_ios"
        default_book_type_numeric  "1"   (Lake OR=1; Brevard OR=3)
        doctype_deed_value  "26"  (Lake DEED(D)=26; may differ per tenant)
        doctype_numeric_map  {...}
        record_type_official_records  1  (for JumpToInstrumentNumber)
    """

    # ────────────────────────────────────────────────────────────── init ──

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/1985",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name: str = config.get("county_name", "Unknown")
        self._base_url: str = config.get("base_url", "").rstrip("/") + "/"

        # Core URLs derived from base — all AcclaimWeb tenants share these routes.
        self._disclaimer_url: str = urljoin(self._base_url, "search/Disclaimer")
        self._search_url: str = urljoin(self._base_url, "search/SearchTypeName")
        self._prename_url: str = urljoin(self._base_url, "Search/SearchTypePreName")
        self._grid_url: str = urljoin(self._base_url, "Search/GridResults")
        self._jump_url_tmpl: str = urljoin(
            self._base_url,
            "details/JumpToInstrumentNumber/{record_type}/{doc_num}",
        )
        self._pdf_url_tmpl: str = urljoin(
            self._base_url, "Image/DocumentPdfAllPages/{txn_id}"
        )

        # AcclaimWeb record_type constant for Official Records (1 on Lake).
        self._record_type_or: int = int(
            config.get("record_type_official_records", 1)
        )

        # Numeric BookType ID for Official Records (1 on Lake; 3 on Brevard).
        self._default_book_type: str = str(
            config.get("default_book_type_numeric", "1")
        )

        # Numeric DocType for DEED (26 on Lake).
        self._doctype_deed_value: str = str(
            config.get("doctype_deed_value", "26")
        )
        # Display label shown in DocTypesDisplay-input (must match tenant list).
        self._doctype_deed_display: str = config.get(
            "doctype_deed_display", "DEED (D)"
        )
        # Map from semantic names → numeric codes for non-DEED search.
        self._doctype_numeric_map: Dict[str, str] = config.get(
            "doctype_numeric_map", {}
        )

        # Party-type radio values for this AcclaimWeb tenant.
        self._party_type_map: Dict[str, str] = config.get(
            "party_type_map",
            {"Both": "Both", "All": "Both", "Grantor": "Direct", "Grantee": "Reverse"},
        )

        # Cloudflare flag (informational — caller decides to skip or pass cookies).
        self._cloudflare_required: bool = bool(
            config.get("cloudflare_required", False)
        )

        # Inter-step politeness delay (set 0 in tests).
        self._step_delay: float = float(config.get("step_delay_seconds", 1.0))

        # HTTP session.
        impersonate = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate)
        self.session.headers.update(EXTRA_HEADERS)

        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # ABC compliance — HTTP adapter never uses a browser driver.
        self.driver = None

        # Per-row extras captured from the GridResults JSON, keyed by
        # InstrumentNumber: TransactionItemId, BookPage, legal description, etc.
        self.row_extras: Dict[str, Dict[str, Any]] = {}

    # ──────────────────────────────────────── BaseRecorderSearch properties ──

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # ──────────────────────────────────── ABC no-ops (Selenium-only contract) ──

    def setup_driver(self):  # type: ignore[override]
        return None

    def navigate_to_search(self):  # type: ignore[override]
        return None

    def return_to_search(self):  # type: ignore[override]
        return None

    # ─────────────────────────────────────────────── session warm-up ──

    def warm_session(
        self,
        browser_minted_cookies: Optional[Dict] = None,
    ) -> bool:
        """Accept the disclaimer to unlock the search route.

        For Cloudflare-blocked tenants (Pinellas), the caller should supply
        browser_minted_cookies containing cf_clearance before calling this.
        """
        if browser_minted_cookies:
            for name, value in browser_minted_cookies.items():
                self.session.cookies.set(name, value)
            self._session_warmed = True

        if not self._session_warmed:
            try:
                self._handshake_disclaimer()
                self._session_warmed = True
            except Exception as exc:
                print(f"  [warm_session] disclaimer handshake failed: {exc}")
                self.last_failure = "disclaimer_failed"
                return False
        return True

    def _handshake_disclaimer(self) -> None:
        """POST the disclaimer form to unlock the search route."""
        # GET the landing page first (sets ASP.NET_SessionId).
        self.session.get(self._base_url, timeout=15, allow_redirects=True)
        # POST the disclaimer — AcclaimWeb redirects to SearchTypeName on success.
        r = self.session.post(
            self._disclaimer_url,
            data={"Disclaimer": "disclaimer"},
            timeout=15,
            allow_redirects=True,
        )
        if r.status_code not in (200, 302):
            raise RuntimeError(
                f"Disclaimer POST returned HTTP {r.status_code}"
            )
        # GET the Name search page to set any additional tenant cookies.
        self.session.get(self._search_url, timeout=15)

    # ─────────────────────────────────────────────── doctype helpers ──

    def _resolve_doctype(self, doc_type: Optional[str]) -> tuple[str, str]:
        """Return (numeric_code, display_label) for the requested doc_type string.

        Accepts:
            None / "DEED" / "DEED (D)"  → tenant DEED numeric code
            Any key in doctype_numeric_map → mapped value
            A bare numeric string → pass through as-is
        """
        if not doc_type or doc_type.upper().startswith("DEED"):
            return self._doctype_deed_value, self._doctype_deed_display
        up = doc_type.upper()
        if up in self._doctype_numeric_map:
            code = self._doctype_numeric_map[up]
            return code, doc_type
        # Assume caller passed a numeric code directly.
        return doc_type, doc_type

    # ─────────────────────────────────────────────── main search ──

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = "DEED",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        parcel_id: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Execute the three-step AcclaimWeb name search.

        Args:
            name:        Party name (e.g. "BROWN LAURENCE" or "BROWN").
            party_type:  "Both", "Grantor", or "Grantee".
            doc_type:    Semantic type ("DEED") or numeric code ("26").
                         Pass None or "" to search all doc types.
            date_from:   Start date (M/D/YYYY).  Defaults to self.start_date.
            date_to:     End date (M/D/YYYY).  Defaults to today/self.end_date.

        Returns:
            List of DocumentRecord, one per unique row in the result grid.
        """
        self.last_failure = None

        if not self._session_warmed:
            if not self.warm_session():
                print(f"  [perform_search] session warm failed; returning empty")
                return []

        mapped_party = self._party_type_map.get(party_type, party_type)
        doctype_num, doctype_display = self._resolve_doctype(doc_type)
        d_from = date_from or self.start_date
        d_to = date_to or (self.end_date or datetime.now().strftime("%m/%d/%Y"))

        # ── Step 1: name resolution ──────────────────────────────────────
        step1_payload: Dict[str, Any] = {
            mapped_party: mapped_party,       # radio button echo
            "PartyType": mapped_party,
            "SearchOnName": name,
            "DateRangeList": " ",
            "DocTypes": doctype_num,
            "DocTypesDisplay-input": doctype_display,
            "DocTypesDisplay": doctype_num,
            "RecordDateFrom": d_from,
            "RecordDateTo": d_to,
            "BookTypesDisplay": "OR",
            "BookTypes": self._default_book_type,
            "IsParsedName": "False",
        }
        post_headers = {
            "Referer": self._search_url,
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            r1 = self.session.post(
                self._search_url + "?Length=6",
                data=step1_payload,
                headers=post_headers,
                timeout=30,
            )
        except Exception as exc:
            print(f"  [step1] network error: {exc}")
            self.last_failure = "step1_network_error"
            return []

        if r1.status_code != 200:
            print(f"  [step1] HTTP {r1.status_code}")
            self.last_failure = f"step1_http_{r1.status_code}"
            return []

        body1 = r1.text or ""
        if "Error in getting list of names" in body1:
            print(
                "  [step1] pre-name-search error — check DocTypes/BookTypes/IsParsedName"
            )
            self.last_failure = "step1_prename_error"
            return []
        if "No names found" in body1:
            print(f"  [step1] no names indexed for '{name}' in the requested window")
            return []

        # Parse the Telerik HTML treeview for itemValue nodes.
        leaves = _ITEM_VALUE_RE.findall(body1)
        # Filter out the root "SURNAME (N)" aggregate node.
        leaves = [v for v in leaves if "(" not in v or not v.endswith(")")]

        if not leaves:
            print(f"  [step1] no leaf names matched '{name}'")
            return []

        # Select names that START WITH the normalised search prefix.
        # Normalise to handle both "SMITH, JOHN" and "SMITH JOHN" variants.
        norm = _normalize_name(name)
        selected = [v for v in leaves if _normalize_name(v).startswith(norm)]
        if not selected:
            print(
                f"  [step1] WARNING: no leaf normalize-matches '{name}'; "
                f"selecting ALL {len(leaves)} leaves so no document is silently dropped"
            )
            selected = leaves

        namelist = "|||".join(selected)

        # Capture dates WITH the "12:00:00 AM" suffix that the server appended
        # to the hidden inputs in the step-1 response (avoids the "Invalid date"
        # error from step-2 if we re-add the suffix ourselves).
        d_from_full = (_DATE_FROM_RE.search(body1) or type("", (), {"group": lambda *_: d_from + " 12:00:00 AM"})()).group(1)
        d_to_full = (_DATE_TO_RE.search(body1) or type("", (), {"group": lambda *_: d_to + " 12:00:00 AM"})()).group(1)

        # ── Step 2: prename commit ───────────────────────────────────────
        if self._step_delay > 0:
            time.sleep(self._step_delay)

        step2_payload: Dict[str, Any] = {
            "NameList": namelist,
            "PartyType": mapped_party,
            "RecordDateFrom": d_from_full,
            "RecordDateTo": d_to_full,
            "BookTypes": self._default_book_type,
            "DocTypes": doctype_num,
            "SearchOnName": name,
            "SearchOnLastOrBusinessName": name.split()[0] if name else "",
            "SearchOnFirstName": "",
        }

        try:
            r2 = self.session.post(
                self._prename_url,
                data=step2_payload,
                headers=post_headers,
                timeout=30,
            )
        except Exception as exc:
            print(f"  [step2] network error: {exc}")
            self.last_failure = "step2_network_error"
            return []

        if r2.status_code != 200:
            print(f"  [step2] HTTP {r2.status_code}")
            self.last_failure = f"step2_http_{r2.status_code}"
            return []

        body2 = r2.text or ""
        if "ShowError" in body2 or body2.startswith("ShowError"):
            err_match = re.search(r"ShowError\(\s*'([^']+)'", body2)
            print(f"  [step2] ShowError: {err_match.group(1) if err_match else body2[:120]}")
            self.last_failure = "step2_show_error"
            return []

        # ── Step 3: JSON grid (paginated) ───────────────────────────────
        if self._step_delay > 0:
            time.sleep(self._step_delay)

        documents: List[DocumentRecord] = []
        seen_keys: set = set()
        page = 1
        total_known: Optional[int] = None

        ajax_post_headers = {**post_headers, **GRID_AJAX_HEADERS}
        ajax_post_headers["Referer"] = self._prename_url

        while True:
            try:
                r3 = self.session.post(
                    self._grid_url,
                    data={
                        "page": str(page),
                        "size": "200",
                        "orderBy": "",
                        "groupBy": "",
                        "filter": "",
                    },
                    headers=ajax_post_headers,
                    timeout=30,
                )
            except Exception as exc:
                print(f"  [step3] page {page} network error: {exc}")
                self.last_failure = "step3_network_error"
                break

            if r3.status_code != 200:
                print(f"  [step3] page {page} HTTP {r3.status_code}")
                self.last_failure = f"step3_http_{r3.status_code}"
                break

            try:
                payload = r3.json()
            except Exception:
                print(
                    f"  [step3] page {page} non-JSON "
                    f"({(r3.text or '')[:80]!r})"
                )
                self.last_failure = "step3_not_json"
                break

            # Lake uses camelCase "data"/"total"; Duval/OnCore PascalCase "Data"/"Total".
            rows: List[Dict] = payload.get("data") or payload.get("Data") or []
            _total = payload.get("total", payload.get("Total"))
            if _total is not None:
                total_known = int(_total)

            for row in rows:
                rec = self._row_to_record(row)
                if rec is None:
                    continue
                key = (rec.document_number, rec.document_type)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                documents.append(rec)

            fetched_so_far = len(documents)
            if total_known is not None and fetched_so_far >= total_known:
                break
            if not rows:
                break
            page += 1
            if page > 50:
                print("  [step3] pagination safety stop at page 50")
                break
            if self._step_delay > 0:
                time.sleep(self._step_delay)

        print(
            f"  [step3] '{name}' party={mapped_party} doctype={doctype_num}: "
            f"{len(documents)} documents (total_known={total_known})"
        )
        return documents

    # ─────────────────────────────────────────────── row parsing ──

    def _row_to_record(self, row: Dict) -> Optional[DocumentRecord]:
        """Convert a GridResults JSON row to a DocumentRecord."""
        try:
            instr = str(row.get("InstrumentNumber") or "").strip()
            if not instr:
                return None

            txn_id = str(row.get("TransactionItemId") or "")
            party_direction = str(row.get("Party") or "")  # "To" or "From"

            name = str(row.get("Name") or "")
            cross_name = str(row.get("CrossPartyName") or "")

            if party_direction == "From":
                grantor = name
                grantee = cross_name
            elif party_direction == "To":
                grantor = cross_name
                grantee = name
            else:
                grantor = name
                grantee = cross_name

            grantor_grantee = f"{grantor} / {grantee}" if grantor or grantee else name

            rec_date = _parse_ms_date(row.get("RecordDate", ""))
            doc_type = str(row.get("DocType") or "")
            book_page = str(row.get("BookPage") or "")
            legal = str(row.get("DocLegalDescription") or "")
            consideration = str(row.get("Consideration") or "")

            # Cache extras for pull_detail / download_pdf callers.
            self.row_extras[instr] = {
                "TransactionItemId": txn_id,
                "BookPage": book_page,
                "DocLegalDescription": legal,
                "Consideration": consideration,
                "Party": party_direction,
                "Name": name,
                "CrossPartyName": cross_name,
            }

            return DocumentRecord(
                document_number=instr,
                grantors=grantor,
                grantees=grantee,
                grantor_grantees=grantor_grantee,
                document_type=doc_type,
                recording_date=rec_date,
                pages=str(row.get("NumericPage") or ""),
            )
        except Exception as exc:
            print(f"  [row_to_record] parse error: {exc} row={row}")
            return None

    # ─────────────────────────────────────────────── detail + download ──

    def pull_detail(self, document_number: str) -> Dict[str, Any]:
        """Fetch the AcclaimWeb detail page and return key fields.

        Returns a dict with at least:
            document_number, book_page, grantors, grantees,
            recording_date, document_type, legal_description,
            TransactionItemId (numeric token for PDF download).
        """
        if not self._session_warmed:
            self.warm_session()

        record_type = self._record_type_or
        url = self._jump_url_tmpl.format(
            record_type=record_type, doc_num=document_number
        )
        try:
            r = self.session.get(url, timeout=20, allow_redirects=True)
        except Exception as exc:
            print(f"  [pull_detail] network error for {document_number}: {exc}")
            return {"document_number": document_number, "error": str(exc)}

        if r.status_code != 200:
            return {
                "document_number": document_number,
                "error": f"HTTP {r.status_code}",
            }

        text = r.text
        result: Dict[str, Any] = {"document_number": document_number}

        # Extract hdnTransactionItemId (needed for PDF download).
        hdn_m = _HDN_TXN_RE.search(text)
        result["TransactionItemId"] = hdn_m.group(1) if hdn_m else ""

        # Extract structured fields from the Telerik detail page.
        def _field(label: str) -> str:
            m = re.search(
                rf"{re.escape(label)}[^:]*:</td[^>]*>\s*<td[^>]*>([^<]+)<",
                text, re.I
            )
            return m.group(1).strip() if m else ""

        result["book_page"] = _field("Book/Page")
        result["recording_date"] = _field("Record Date")
        result["document_type"] = _field("Doc Type")
        result["consideration"] = _field("Consideration")

        # Grantors / grantees — AcclaimWeb lists them in a table.
        grantors_raw = re.findall(
            r'<td[^>]*>\s*(.*?)\s*</td>\s*<td[^>]*>\s*(?:Grantor|From)\s*</td>',
            text, re.I | re.DOTALL
        )
        grantees_raw = re.findall(
            r'<td[^>]*>\s*(.*?)\s*</td>\s*<td[^>]*>\s*(?:Grantee|To)\s*</td>',
            text, re.I | re.DOTALL
        )
        result["grantors"] = "; ".join(
            re.sub(r"<[^>]+>", "", g).strip() for g in grantors_raw if g.strip()
        )
        result["grantees"] = "; ".join(
            re.sub(r"<[^>]+>", "", g).strip() for g in grantees_raw if g.strip()
        )

        # Legal description — look for a "Legal Description" section.
        legal_m = re.search(
            r"Legal Description[^<]*</[^>]+>\s*<[^>]+>([^<]+)", text, re.I
        )
        result["legal_description"] = legal_m.group(1).strip() if legal_m else ""

        return result

    def download_pdf(
        self,
        doc_num: str = None,
        dest_path: str = None,
        transaction_item_id: Optional[str] = None,
        document_number: str = None,  # legacy alias accepted by the pipeline
    ) -> bool:
        """Download the full-document PDF to ``dest_path``.

        Uses the ``/Image/DocumentPdfAllPages/{TransactionItemId}`` endpoint
        discovered in AcclaimDetailPages.js (getPdfSrc function).

        Args:
            doc_num:              Instrument number string (pipeline-standard kwarg).
            dest_path:            Local path to write the PDF bytes.
            transaction_item_id:  If None, looks up the cached value from
                                  ``row_extras`` or fetches the detail page.
            document_number:      Legacy alias for doc_num (accepted for compat).
        Returns:
            True on success, False on error.
        """
        # Normalise: pipeline passes doc_num=; legacy callers may pass document_number=
        document_number = doc_num or document_number
        if not document_number:
            print("  [download_pdf] no document_number supplied")
            return False

        if not self._session_warmed:
            self.warm_session()

        txn_id = transaction_item_id
        if not txn_id:
            extras = self.row_extras.get(document_number, {})
            txn_id = extras.get("TransactionItemId")
        if not txn_id:
            # Fall back to detail page.
            detail = self.pull_detail(document_number)
            txn_id = detail.get("TransactionItemId")
        if not txn_id:
            print(f"  [download_pdf] no TransactionItemId for {document_number}")
            return False

        pdf_url = self._pdf_url_tmpl.format(txn_id=txn_id)
        try:
            r = self.session.get(pdf_url, timeout=60)
        except Exception as exc:
            print(f"  [download_pdf] network error: {exc}")
            return False

        if r.status_code != 200:
            print(f"  [download_pdf] HTTP {r.status_code} for {document_number}")
            return False

        content_type = r.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and r.content[:4] != b"%PDF":
            print(
                f"  [download_pdf] unexpected content-type '{content_type}' "
                f"for {document_number}"
            )
            return False

        try:
            dest_path = str(dest_path)
            with open(dest_path, "wb") as fh:
                fh.write(r.content)
            print(
                f"  [download_pdf] saved {len(r.content)} bytes → {dest_path}"
            )
            return True
        except OSError as exc:
            print(f"  [download_pdf] write error: {exc}")
            return False

    # ─────────────────────────────────────────────── legacy ABC stubs ──

    def extract_results(self, *args, **kwargs):  # type: ignore[override]
        """No-op — results are extracted inside perform_search()."""
        return []
