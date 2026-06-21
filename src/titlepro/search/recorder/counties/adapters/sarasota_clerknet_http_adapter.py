"""
Sarasota County (FL) HTTP Recorder Adapter — Phase 1 CURE (Wave-1 scaffold).

Pure-Python HTTP adapter for the Sarasota Clerk of the Circuit Court Official
Records portal at ``secure.sarasotaclerk.com/OfficialRecords.aspx``. The
portal is Sarasota's custom in-house "ClerkNet" ASP.NET **WebForms** app with
Telerik RadControls (NOT Landmark / AcclaimWeb / Benchmark / Tyler).

Portal contract (probed 2026-06-10 — see
``src/titlepro/api/downloaded_doc/0610/Sarasota_BRUNO_v1/phase0_probe_recorder.md``)
------------------------------------------------------------------------------
* Server ``Microsoft-IIS/10.0`` — **no Cloudflare, no CAPTCHA, no disclaimer
  gate**. Cold GET serves the full search form.
* Classic WebForms single-page flow:
    1. GET ``OfficialRecords.aspx`` → scrape ``__VIEWSTATE`` +
       ``__VIEWSTATEGENERATOR`` + ``__EVENTVALIDATION`` hidden fields.
    2. POST the same URL with the search fields + the scraped hidden fields.
    3. Results render into Telerik RadGrid ``ctl00_cphBody_rgCaseList`` on
       the SAME page (``rgRow`` / ``rgAltRow`` rows).
    4. **Every** subsequent POST must carry the hidden fields re-scraped from
       the PREVIOUS response (WebForms rotates VIEWSTATE per response) —
       this is exactly the state-contamination shape that produced the
       ``[N, 0, 0, 0, 0, 0]`` signature on Broward, so ``_webforms_state``
       is refreshed from every response unconditionally.
* Form fields (verbatim):
    ``ctl00$cphBody$tbParty``               last or business name
    ``ctl00$cphBody$tbPartyFirst``          first name
    ``ctl00$cphBody$tbLic``                 Instrument # (direct retrieval)
    ``ctl00$cphBody$rdAppFrom$dateInput``   record date from (M/D/YYYY)
    ``ctl00$cphBody$rdAppTo$dateInput``     record date to
    ``ctl00$cphBody$tbBook`` / ``tbPage``   book/page retrieval
    ``ctl00$cphBody$cbDocType$<idx>``       277 doc-type checkboxes; a checked
                                            box posts ``name=<value-code>``
                                            (e.g. ``...$71=D`` for DEED)
    ``ctl00$cphBody$bSearch_input=Search``  submit
* Doc-type universe is captured in ``config/fl/sarasota.json``
  (``doctype_codes``); the index↔code map is ALSO re-derived at warm-up from
  the live page so a clerk-side reorder cannot silently break filtering.

UNVERIFIED (first operator-approved live POST happens in Wave 2):
  * result-grid column order — mitigated: ``extract_results`` builds the
    column map from header-cell TEXT, not position;
  * paging behaviour of the RadGrid;
  * per-row document-image href pattern (``pull_pdf`` raises until captured).

Per Tony Roveda's directives:
  #1 no Selenium/Playwright anywhere in this module (curl_cffi only);
  #2 deed-first — call ``perform_search(..., doc_type="DEED")`` first
     (Sarasota has a single ``D`` deed code; no WD/QCD split at index level);
  #3 the portal has a single party-name field returning both sides — ALL
     provided names must be run by the caller, party_type is post-filtered.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# safari17_2_ios kept for parity with the FL Cloudflare counties; Sarasota has
# no anti-bot (verified 2026-06-10: bare IIS, GET 200 cold) so any profile works.
DEFAULT_IMPERSONATE = "safari17_2_ios"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
}

# The WebForms hidden fields that must round-trip on every POST.
WEBFORMS_HIDDEN_FIELDS = (
    "__EVENTTARGET",
    "__EVENTARGUMENT",
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "ToolkitScriptManager1_HiddenField",
)

# Matches one doc-type checkbox input. The live page renders them as
#   <input ... name="ctl00$cphBody$cbDocType$71" ... value="D" ...>
_DOCTYPE_INPUT_RE = re.compile(
    r'name="ctl00\$cphBody\$cbDocType\$(\d+)"[^>]*value="([^"]*)"',
    re.IGNORECASE,
)

# Header-text → DocumentRecord field. LIVE-VALIDATED 2026-06-10 (Wave-2 POST
# #1, capture at the BRUNO case dir): RadGrid columns are exactly
#   Image | Instrument Number | Book-Page | Date Recorded | Document Type |
#   Name | Legal Description
# ``Name`` holds ALL parties (<br>-separated, both sides, no role marker) —
# the combined block goes into ``grantor_grantees``; per-side split happens
# at OCR/classification. ``Legal Description`` + ``Book-Page`` are stashed in
# ``_row_extras_by_number`` (DocumentRecord has no fields for them).
_HEADER_FIELD_MAP = [
    (("instrument", "doc #", "document #", "clerk file"), "document_number"),
    (("book-page", "book/page"), "_book_page"),
    (("date recorded", "record date", "recorded"), "recording_date"),
    (("document type", "doc type", "instrument type"), "document_type"),
    (("legal",), "_legal"),
    (("name", "parties", "party"), "_parties"),
    (("first party", "grantor", "direct"), "grantors"),
    (("second party", "grantee", "indirect", "reverse"), "grantees"),
    (("pages", "pgs", "page count"), "pages"),
]

# Image-column href (live-validated 2026-06-10):
#   <a target=_blank href=/viewTiff.aspx?intrnum=2013021460>View Image</a>
_VIEWTIFF_HREF_RE = re.compile(r"viewTiff\.aspx\?intrnum=(\d+)", re.IGNORECASE)

# RadGrid pager banner: "500 items in 42 pages" (live-validated).
_PAGER_ITEMS_RE = re.compile(r"(\d+)\s*items?\s*in\s*(\d+)\s*pages?", re.IGNORECASE)

# Business-name markers — names containing these are NOT split into
# last/first for the tbParty/tbPartyFirst pair.
_BUSINESS_MARKERS = (
    "TRUST", "LLC", "INC", "BANK", "CORP", "ASSOC", "COMPANY", "CO.",
    "REVOCABLE", "MORTGAGE", "CREDIT UNION", "HOA", "CHURCH", "LP", "LLP",
)


class SarasotaClerkNetHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for Sarasota County FL Clerk official records."""

    # ---------------------------------------------------------------- init

    def __init__(
        self,
        config: Dict[str, Any],
        start_date: str = "01/01/1990",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Sarasota")
        self._base_url = config.get(
            "base_url", "https://secure.sarasotaclerk.com/OfficialRecords.aspx"
        )
        self._search_url = config.get("search_url", self._base_url)
        self._post_search_url = config.get("post_search_url", self._search_url)

        ff = config.get("webforms_form_fields", {})
        self._field_party_last = ff.get("party_last", "ctl00$cphBody$tbParty")
        self._field_party_first = ff.get("party_first", "ctl00$cphBody$tbPartyFirst")
        self._field_instrument = ff.get("instrument", "ctl00$cphBody$tbLic")
        self._field_date_from = ff.get("date_from", "ctl00$cphBody$rdAppFrom$dateInput")
        self._field_date_to = ff.get("date_to", "ctl00$cphBody$rdAppTo$dateInput")
        self._field_book = ff.get("book", "ctl00$cphBody$tbBook")
        self._field_page = ff.get("page", "ctl00$cphBody$tbPage")
        self._doctype_prefix = ff.get("doc_type_prefix", "ctl00$cphBody$cbDocType$")
        self._field_search_button = ff.get("search_button", "ctl00$cphBody$bSearch_input")
        self._search_button_value = ff.get("search_button_value", "Search")

        self._hidden_field_names = tuple(
            config.get("webforms_hidden_fields", WEBFORMS_HIDDEN_FIELDS)
        )
        self._result_grid_id = config.get("result_grid_id", "ctl00_cphBody_rgCaseList")
        self._result_row_classes = tuple(
            config.get("result_row_classes", ["rgRow", "rgAltRow"])
        )

        # Semantic label → portal value-code ("DEED" → "D"). The checkbox
        # POST key needs the INDEX though, so we keep a code→index map that
        # is (a) seeded from nothing, (b) populated by warm_session from the
        # live page, so a clerk-side reorder can't break filtering.
        self._doctype_codes: Dict[str, str] = {
            k.upper(): v for k, v in (config.get("doctype_codes") or {}).items()
        }
        self._doctype_index_by_code: Dict[str, int] = {}

        pat = config.get("doc_number_pattern") or r"^\d{10,12}$"
        self._doc_number_re = re.compile(pat)

        self.party_type_map = config.get(
            "party_type_map",
            {"Both": "Both", "All": "Both", "Grantor": "Both", "Grantee": "Both"},
        )
        self.supported_party_types = config.get(
            "supported_party_types", ["Both", "Grantor", "Grantee"]
        )

        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)

        # WebForms round-trip state — refreshed from EVERY response.
        self._webforms_state: Dict[str, str] = {}
        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # Instrument → image URL (viewTiff.aspx?intrnum=N, live-validated).
        self._doc_id_by_number: Dict[str, str] = {}
        # Instrument → {book_page, legal, parties_raw} extras from the grid.
        self._row_extras_by_number: Dict[str, Dict[str, str]] = {}

        # Pause between consecutive POSTs (pager fetches) — live-testing
        # etiquette. The e2e driver additionally spaces whole searches.
        self._post_delay = float(config.get("post_delay_seconds", 30))
        # Safety cap on pager walking (500-item/42-page dumps mean the name
        # filter did NOT apply — never blind-walk those).
        self._max_pages = int(config.get("max_result_pages", 8))

        # ABC compliance — never used (no browser in Phase 1, Tony #1).
        self.driver = None

    # ------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # --------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        return None

    # ------------------------------------------------------ session warm-up

    def warm_session(
        self,
        browser_minted_cookies: Optional[Dict] = None,
        cookie_jar_path: Optional[str] = None,
    ) -> bool:
        """Bootstrap: GET the search page, harvest the WebForms hidden fields
        and the live doc-type index map. Returns True on success."""
        if browser_minted_cookies:
            for name, value in browser_minted_cookies.items():
                self.session.cookies.set(name, value)

        try:
            resp = self.session.get(self._search_url, timeout=30)
        except Exception as exc:
            self.last_failure = f"warm_session network error: {exc}"
            return False
        if resp.status_code != 200:
            self.last_failure = f"warm_session HTTP {resp.status_code}"
            return False

        self._refresh_webforms_state(resp.text)
        self._refresh_doctype_indices(resp.text)

        if not self._webforms_state.get("__VIEWSTATE"):
            self.last_failure = "warm_session: __VIEWSTATE not found on search page"
            return False

        self._session_warmed = True
        return True

    # ------------------------------------------------------ WebForms state

    def _refresh_webforms_state(self, html: str) -> None:
        """Scrape the round-trip hidden fields from a response. WebForms
        rotates __VIEWSTATE/__EVENTVALIDATION per response — stale values are
        the Sarasota analogue of the Broward state-contamination bug, so this
        runs on EVERY response, including search results."""
        if not html:
            return
        for name in self._hidden_field_names:
            m = re.search(
                r'(?:id|name)="%s"[^>]*value="([^"]*)"' % re.escape(name), html
            )
            if m:
                self._webforms_state[name] = m.group(1)
            else:
                self._webforms_state.setdefault(name, "")

    def _refresh_doctype_indices(self, html: str) -> None:
        """Re-derive the doc-type checkbox index for every value-code from the
        live page (the POST key is ``cbDocType$<idx>``, the value is the code)."""
        for idx, code in _DOCTYPE_INPUT_RE.findall(html or ""):
            if code:
                self._doctype_index_by_code[code.upper()] = int(idx)

    # ------------------------------------------------------------- payload

    def _resolve_doctype_code(self, doc_type: Optional[str]) -> Optional[str]:
        """Semantic label ('DEED') or raw code ('D') → portal value-code."""
        if not doc_type:
            return None
        upper = doc_type.upper().strip()
        if upper in self._doctype_codes:
            return self._doctype_codes[upper]
        # Already a raw code the portal knows?
        if upper in self._doctype_index_by_code:
            return upper
        # Pass through — server-side EVENTVALIDATION will reject junk loudly.
        return upper

    @staticmethod
    def _normalize_date(value: Optional[str]) -> str:
        """Pipeline dates arrive MM/DD/YYYY; the RadDatePicker text input
        accepts M/D/YYYY. Strip leading zeros defensively; pass through
        anything unrecognized."""
        if not value:
            return ""
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value.strip())
        if m:
            return f"{int(m.group(1))}/{int(m.group(2))}/{m.group(3)}"
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", value.strip())
        if m:
            return f"{int(m.group(2))}/{int(m.group(3))}/{m.group(1)}"
        return value.strip()

    @staticmethod
    def _radinput_client_state(value: str) -> str:
        """Telerik RadInput posts its value through a ``<id>_ClientState``
        hidden JSON; the SERVER reads ``valueAsString`` from it. LIVE-PROVEN
        2026-06-10: posting only the plain text input leaves the field EMPTY
        server-side (POST #1 returned an unfiltered 500-item dump and echoed
        ``value=""`` back)."""
        v = (value or "").replace('"', '\\"')
        return (
            '{"enabled":true,"emptyMessage":"","validationText":"%s",'
            '"valueAsString":"%s","lastSetTextBoxValue":"%s"}' % (v, v, v)
        )

    @staticmethod
    def _raddate_client_state(mdy: str) -> str:
        """RadDateInput ClientState. ``validationText``/``valueAsString`` use
        the Telerik ``yyyy-MM-dd-00-00-00`` wire format."""
        if not mdy:
            return (
                '{"enabled":true,"emptyMessage":"","validationText":"",'
                '"valueAsString":"","lastSetTextBoxValue":""}'
            )
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", mdy.strip())
        wire = (
            f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}-00-00-00"
            if m
            else ""
        )
        return (
            '{"enabled":true,"emptyMessage":"","validationText":"%s",'
            '"valueAsString":"%s","lastSetTextBoxValue":"%s"}' % (wire, wire, mdy)
        )

    @staticmethod
    def _client_state_key(field_name: str) -> str:
        """``ctl00$cphBody$tbParty`` → ``ctl00_cphBody_tbParty_ClientState``
        (Telerik renders the hidden with underscores)."""
        return field_name.replace("$", "_") + "_ClientState"

    def build_search_payload(
        self,
        name: str = "",
        first_name: str = "",
        instrument: str = "",
        book: str = "",
        page: str = "",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, str]:
        """Assemble the WebForms POST body. Public so the scaffold tests can
        assert the exact request shape without network access."""
        payload: Dict[str, str] = {}
        for hidden in self._hidden_field_names:
            payload[hidden] = self._webforms_state.get(hidden, "")

        df = self._normalize_date(
            date_from if date_from is not None else (self.start_date if not instrument else "")
        )
        dt = self._normalize_date(
            date_to if date_to is not None else (self.end_date if not instrument else "")
        )

        # RadInput text + ClientState pairs (ClientState is LOAD-BEARING —
        # the server reads valueAsString, not the bare text input).
        for field, value in (
            (self._field_party_last, name or ""),
            (self._field_party_first, first_name or ""),
            (self._field_instrument, instrument or ""),
            (self._field_book, book or ""),
            (self._field_page, page or ""),
        ):
            payload[field] = value
            payload[self._client_state_key(field)] = self._radinput_client_state(value)

        # RadDatePicker: text input + ClientState + the hidden picker field
        # (``ctl00$cphBody$rdAppFrom``) in yyyy-MM-dd.
        for date_field, mdy in ((self._field_date_from, df), (self._field_date_to, dt)):
            payload[date_field] = mdy
            payload[self._client_state_key(date_field)] = self._raddate_client_state(mdy)
            hidden_picker = date_field.rsplit("$", 1)[0]  # strip "$dateInput"
            m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", mdy or "")
            payload[hidden_picker] = (
                f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""
            )

        code = self._resolve_doctype_code(doc_type)
        if code:
            idx = self._doctype_index_by_code.get(code.upper())
            if idx is None:
                raise ValueError(
                    f"doc-type code {code!r} has no checkbox index — warm_session "
                    "must run against the live page before doc-type filtering "
                    "(or the code is not in the portal's 277-type list)"
                )
            payload[f"{self._doctype_prefix}{idx}"] = code

        payload[self._field_search_button] = self._search_button_value
        return payload

    @staticmethod
    def split_subject_name(combined: str) -> tuple:
        """'BRUNO EMELIA M' → ('BRUNO', 'EMELIA M'); business/trust names are
        NOT split (full string goes to the last-or-business-name field)."""
        s = (combined or "").strip()
        upper = s.upper()
        if any(marker in upper for marker in _BUSINESS_MARKERS):
            return s, ""
        parts = s.split()
        if len(parts) < 2:
            return s, ""
        return parts[0], " ".join(parts[1:])

    # ---------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search.

        Args:
            name: "BRUNO EMELIA M" style (last-first, no comma) — goes into
                  the single tbParty field. The portal matches either side.
            party_type: post-filter semantics only (portal returns both sides).
            doc_type: semantic label ("DEED") or raw portal code ("D").
            date_from/date_to: MM/DD/YYYY (pipeline) or YYYY-MM-DD.
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] session not warmed; "
                    f"last_failure={self.last_failure}"
                )
                return []

        last, first = self.split_subject_name(name)
        try:
            payload = self.build_search_payload(
                name=last, first_name=first, doc_type=doc_type,
                date_from=date_from, date_to=date_to,
            )
        except ValueError as exc:
            self.last_failure = str(exc)
            print(f"  [perform_search] {exc}")
            return []

        resp = self._post(payload)
        if resp is None:
            return []

        documents = self.extract_results(resp.text)
        documents = self._walk_pager(resp.text, payload, documents)
        return documents

    # ----------------------------------------------------------- pagination

    def _pager_info(self, html: str) -> tuple:
        """→ (total_items, total_pages) from the RadGrid banner; (n, 1) if
        no banner."""
        m = _PAGER_ITEMS_RE.search(html or "")
        if m:
            return int(m.group(1)), int(m.group(2))
        return 0, 1

    @staticmethod
    def _find_pager_target(html: str, page_num: int) -> Optional[str]:
        """Locate the __doPostBack target for the numeric pager link
        ``<a href="javascript:__doPostBack('<target>','')"><span>N</span></a>``."""
        soup = BeautifulSoup(html or "", "lxml")
        for a in soup.find_all("a", href=True):
            span = a.find("span")
            if span and span.get_text(strip=True) == str(page_num):
                m = re.search(r"__doPostBack\('([^']+)'", a["href"])
                if m:
                    return m.group(1)
        return None

    def _walk_pager(
        self,
        first_page_html: str,
        search_payload: Dict[str, str],
        documents: List[DocumentRecord],
    ) -> List[DocumentRecord]:
        """Fetch pages 2..N of the RadGrid result set (≥`_post_delay`s apart).

        Hard-stops at ``_max_pages`` — a 42-page dump means the name filter
        did not apply (live-proven failure shape) and must surface as an
        error, not be blind-walked."""
        items, pages = self._pager_info(first_page_html)
        if pages <= 1:
            return documents
        if pages > self._max_pages:
            self.last_failure = (
                f"result set too large ({items} items / {pages} pages) — "
                "name filter likely not applied; refusing to blind-walk pager"
            )
            print(f"  [perform_search] {self.last_failure}")
            return documents

        current_html = first_page_html
        for page_num in range(2, pages + 1):
            target = self._find_pager_target(current_html, page_num)
            if not target:
                self.last_failure = f"pager link for page {page_num} not found"
                print(f"  [perform_search] {self.last_failure}")
                break
            time.sleep(self._post_delay)
            page_payload = dict(search_payload)
            # Pager is a __doPostBack, not a button submit.
            page_payload.pop(self._field_search_button, None)
            page_payload["__EVENTTARGET"] = target
            page_payload["__EVENTARGUMENT"] = ""
            for hidden in self._hidden_field_names:
                if hidden not in ("__EVENTTARGET", "__EVENTARGUMENT"):
                    page_payload[hidden] = self._webforms_state.get(hidden, "")
            resp = self._post(page_payload)
            if resp is None:
                break
            current_html = resp.text
            seen = {d.document_number for d in documents}
            for d in self.extract_results(current_html):
                if d.document_number not in seen:
                    documents.append(d)
        return documents

    def search_by_instrument(self, doc_num: str) -> List[DocumentRecord]:
        """Direct retrieval by Instrument # (the tbLic field)."""
        if not self._session_warmed and not self.warm_session():
            return []
        payload = self.build_search_payload(instrument=str(doc_num))
        resp = self._post(payload)
        if resp is None:
            return []
        return self.extract_results(resp.text)

    def search_by_book_page(self, book: str, page: str) -> List[DocumentRecord]:
        if not self._session_warmed and not self.warm_session():
            return []
        payload = self.build_search_payload(book=str(book), page=str(page))
        resp = self._post(payload)
        if resp is None:
            return []
        return self.extract_results(resp.text)

    def _post(self, payload: Dict[str, str]):
        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self._search_url,
            "Origin": "https://secure.sarasotaclerk.com",
        }
        try:
            resp = self.session.post(
                self._post_search_url,
                data=payload,
                headers=post_headers,
                timeout=60,
                allow_redirects=True,
            )
        except Exception as exc:
            self.last_failure = f"POST network error: {exc}"
            print(f"  [perform_search] {self.last_failure}")
            return None

        if resp.status_code != 200:
            self.last_failure = f"POST HTTP {resp.status_code}"
            print(f"  [perform_search] {self.last_failure}")
            # A stale EVENTVALIDATION typically yields HTTP 500 — re-warm once.
            if self.warm_session():
                for hidden in self._hidden_field_names:
                    payload[hidden] = self._webforms_state.get(hidden, "")
                try:
                    resp = self.session.post(
                        self._post_search_url, data=payload,
                        headers=post_headers, timeout=60,
                    )
                except Exception as exc:
                    self.last_failure = f"retry POST network error: {exc}"
                    return None
                if resp.status_code != 200:
                    self.last_failure = f"retry POST HTTP {resp.status_code}"
                    return None
            else:
                return None

        # CRITICAL: rotate the WebForms state from THIS response before the
        # caller can issue the next POST (anti-[N,0,0,0,0,0] discipline).
        self._refresh_webforms_state(resp.text)
        return resp

    # ------------------------------------------------------ extract_results

    def extract_results(self, html: str) -> List[DocumentRecord]:
        """Parse the RadGrid result HTML into DocumentRecord rows.

        Column ORDER is unverified until Wave 2, so the column map is built
        from header-cell text (``_HEADER_FIELD_MAP`` substring match) instead
        of fixed positions. Rows are ``tr.rgRow`` / ``tr.rgAltRow`` inside
        ``div#ctl00_cphBody_rgCaseList`` (falls back to a page-wide scan).
        """
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        grid = soup.find(id=self._result_grid_id)
        scope = grid if grid is not None else soup

        # Single document-order pass (per-class find_all would interleave
        # rgRow/rgAltRow out of DOM order).
        wanted = set(self._result_row_classes)
        rows = [
            tr for tr in scope.find_all("tr")
            if wanted.intersection(tr.get("class") or [])
        ]
        if not rows:
            return []

        # Build the header → field map from the grid's header row.
        col_fields: Dict[int, str] = {}
        header_row = None
        for tr in scope.find_all("tr"):
            cells = tr.find_all("th") or (
                tr.find_all("td") if "rgHeader" in " ".join(tr.get("class") or []) else []
            )
            if cells:
                header_row = cells
                break
        if header_row:
            for i, th in enumerate(header_row):
                text = th.get_text(" ", strip=True).lower()
                for keys, field in _HEADER_FIELD_MAP:
                    if any(k in text for k in keys) and field not in col_fields.values():
                        col_fields[i] = field
                        break

        documents: List[DocumentRecord] = []
        seen = set()

        for row in rows:
            tds = row.find_all("td")
            if not tds:
                continue
            values = {"document_number": "", "grantors": "", "grantees": "",
                      "document_type": "", "recording_date": "", "pages": "",
                      "_book_page": "", "_legal": "", "_parties": ""}
            parties_list: List[str] = []
            if col_fields:
                for i, td in enumerate(tds):
                    field = col_fields.get(i)
                    if not field:
                        continue
                    if field == "_parties":
                        # <br>-separated multi-party cell — keep each name.
                        parties_list = [
                            s.strip()
                            for s in td.get_text("\n", strip=True).split("\n")
                            if s.strip()
                        ]
                        values[field] = "; ".join(parties_list)
                    else:
                        values[field] = td.get_text(" ", strip=True)
            else:
                # No header captured — best-effort positional fallback:
                # find the first cell that looks like an instrument number.
                texts = [td.get_text(" ", strip=True) for td in tds]
                inst = next((t for t in texts if self._doc_number_re.match(t)), "")
                values["document_number"] = inst

            # Image link (live shape: /viewTiff.aspx?intrnum=N).
            doc_no = values["document_number"]
            for a in row.find_all("a", href=True):
                m = _VIEWTIFF_HREF_RE.search(a["href"])
                if m:
                    key = doc_no or m.group(1)
                    self._doc_id_by_number[key] = urljoin(self._base_url, a["href"])
                    break

            if not doc_no or doc_no in seen:
                continue
            seen.add(doc_no)

            self._row_extras_by_number[doc_no] = {
                "book_page": values["_book_page"],
                "legal": values["_legal"],
                "parties": parties_list,
                "image_url": self._doc_id_by_number.get(doc_no, ""),
            }

            documents.append(
                DocumentRecord(
                    document_number=doc_no,
                    grantors=values["grantors"],
                    grantees=values["grantees"],
                    # Sarasota's grid does not mark grantor vs grantee — the
                    # combined Name cell goes here; OCR classifies sides.
                    grantor_grantees=values["_parties"]
                    or " / ".join(
                        v for v in (values["grantors"], values["grantees"]) if v
                    ),
                    document_type=values["document_type"],
                    recording_date=values["recording_date"],
                    pages=values["pages"],
                )
            )
        return documents

    # ----------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str) -> Dict:
        """Instrument # → detail dict via the tbLic direct-retrieval field."""
        records = self.search_by_instrument(doc_num)
        match = next(
            (r for r in records if r.document_number == str(doc_num)), None
        )
        if not match:
            return {
                "document_number": doc_num,
                "error": self.last_failure or "instrument not found",
            }
        extras = self._row_extras_by_number.get(str(doc_num), {})
        return {
            "document_number": match.document_number,
            "recording_date": match.recording_date,
            "doc_type": match.document_type,
            "indexed_apn": "",
            "book_page": extras.get("book_page", ""),
            "legal": extras.get("legal", ""),
            "parties": [
                {"role": "Party", "name": p} for p in extras.get("parties", [])
            ]
            or [
                {"role": "Grantor", "name": match.grantors},
                {"role": "Grantee", "name": match.grantees},
            ],
            "doc_id": self._doc_id_by_number.get(str(doc_num), ""),
        }

    # ------------------------------------------------------------- pull_pdf

    def pull_pdf(self, doc_num: str) -> bytes:
        """Document image via the live-validated direct endpoint
        ``GET /viewTiff.aspx?intrnum=<instrument>`` (same session).

        LIVE-PROVEN session contract (2026-06-10): a cold session gets an
        EMPTY HTML shell back; after ANY search POST in the same session,
        viewTiff serves the binary (a real PDF despite the name) for ANY
        instrument — even ones outside the search's result set. So if we hit
        the empty-shell shape, we establish context with one instrument
        search and retry once.

        Returns the raw binary (PDF or TIFF — sniff the magic).
        Raises RuntimeError on HTTP failure or a persistent HTML response."""
        url = self._doc_id_by_number.get(
            str(doc_num),
            f"https://secure.sarasotaclerk.com/viewTiff.aspx?intrnum={doc_num}",
        )

        def _get() -> Optional[bytes]:
            resp = self.session.get(
                url, timeout=30, headers={"Referer": self._search_url}
            )
            if resp.status_code != 200:
                raise RuntimeError(f"viewTiff HTTP {resp.status_code} for {doc_num}")
            body = resp.content
            if body[:4] == b"%PDF" or body[:4] in (b"II*\x00", b"MM\x00*"):
                return body
            return None

        body = _get()
        if body is None:
            # Empty-shell HTML → no search context yet. Establish it.
            self.search_by_instrument(doc_num)
            body = _get()
        if body is None:
            raise RuntimeError(
                f"viewTiff returned HTML (no binary) for {doc_num} even after "
                "establishing search context"
            )
        return body
