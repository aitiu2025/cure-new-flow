"""
Manatee County (FL) HTTP-First Recorder Adapter.

Pure-Python adapter for records.manateeclerk.com (custom ASP.NET MVC backend).
Mirrors the design of ``acclaimweb_http_adapter.py`` but tuned for Manatee's
two-stage anti-forgery flow and HTML result-grid shape.

Portal contract (verified live 2026-05-26)
------------------------------------------
* No Cloudflare.
* No CAPTCHA.
* Two anti-forgery token values must be present on the POST:
    1. ``__RequestVerificationToken`` *cookie* — set by the first GET response.
    2. ``__RequestVerificationToken`` *hidden form input* — scraped from the
       same GET's HTML. The two values differ — ASP.NET MVC's standard
       double-submit pattern. Both are required.
* POST endpoint: ``/OfficialRecords/Search/DoSearch`` returns full HTML page
  (not a JSON fragment) with the result table at ``<table id="results">``.
* Each result row is ``<tr class="data-row">`` with these cells:
    0. View icon  → ``<a href="/OfficialRecords/DisplayInstrument/{doc_id}">``
    1. Instrument number
    2. From (grantor) — ``<ol><li>...</li></ol>``
    3. To (grantee) — ``<ol><li>...</li></ol>``
    4. Type
    5. Book
    6. Page
    7. Price
    8. Legal
    9. Record date (MM-DD-YYYY)
   10. Pages count

Implementation notes
--------------------
* Uses ``curl_cffi.Session(impersonate="chrome120")`` for parity with the
  other HTTP adapters; chrome120 works fine against Manatee (no CF challenge).
* Anti-forgery refresh happens on 403, but Manatee has not produced 403s in
  any probe so far — kept defensively.
* No local-cache reads: this adapter is the LIVE path. The
  ``manatee_cache.db`` SQLite file is intentionally not consulted here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


DEFAULT_IMPERSONATE = "chrome120"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
}

# Matches __RequestVerificationToken hidden input regardless of attribute order.
_TOKEN_RE_A = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.IGNORECASE
)
_TOKEN_RE_B = re.compile(
    r'value="([^"]+)"[^>]*name="__RequestVerificationToken"', re.IGNORECASE
)

# Matches "/OfficialRecords/DisplayInstrument/<doc_id>" hrefs.
_DOC_ID_HREF_RE = re.compile(
    r'href=["\'](?:/OfficialRecords)?/DisplayInstrument/(\d+)["\']', re.IGNORECASE
)


class ManateeHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for Manatee County FL Clerk records."""

    # ---------------------------------------------------------------- init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Manatee")
        self._base_url = config.get(
            "base_url", "https://records.manateeclerk.com/OfficialRecords/Search"
        ).rstrip("/")
        self._search_url = config.get(
            "search_url",
            "https://records.manateeclerk.com/OfficialRecords/Search/Party",
        )
        self._search_url_instrument = config.get(
            "search_url_instrument",
            "https://records.manateeclerk.com/OfficialRecords/Search/InstrumentNumber",
        )
        self._search_url_bookpage = config.get(
            "search_url_bookpage",
            "https://records.manateeclerk.com/OfficialRecords/Search/InstrumentBookPage",
        )
        self._post_search_url = config.get(
            "post_search_url",
            "https://records.manateeclerk.com/OfficialRecords/Search/DoSearch",
        )
        self._download_base_url = config.get(
            "download_base_url",
            "https://records.manateeclerk.com/OfficialRecords/DisplayInstrument/InstrumentResultFile/",
        )

        ff = config.get("http_form_fields", {})
        self._field_name = ff.get("name", "SearchInputs.Party")
        self._field_date_from = ff.get("date_from", "SearchInputs.StartDate")
        self._field_date_to = ff.get("date_to", "SearchInputs.EndDate")
        self._field_doc_type = ff.get("doc_type", "SearchInputs.InstrumentTypeId")
        self._field_instrument = ff.get("instrument", "SearchInputs.InstrumentNumber")
        self._field_book = ff.get("book", "SearchInputs.BookNumber")
        self._field_page = ff.get("page", "SearchInputs.PageNumber")
        self._field_page_num = ff.get("page_num", "SearchInputs.Page")
        self._field_page_size = ff.get("page_size", "SearchInputs.PageSize")
        self._field_search_type = ff.get("search_type", "SearchInputs.SearchType")

        self._antiforgery_field = config.get(
            "antiforgery_token_field", "__RequestVerificationToken"
        )
        self._doctype_codes = config.get(
            "doctype_codes",
            {"DEED": "11", "MORTGAGE": "21", "SATISFACTION": "30"},
        )

        # Date format on Manatee is yyyy-mm-dd. start_date / end_date arrive
        # from the pipeline as MM/DD/YYYY — convert on the fly.
        self._date_format = config.get("date_format", "yyyy-mm-dd")

        # Doc-number pattern (12-15 digits typical: 201841020434, 202641040260).
        pat = config.get("doc_number_pattern") or r"^\d{12,15}$"
        self._doc_number_re = re.compile(pat)

        # Party-type mapping. Manatee's UI uses a single party-name text input;
        # the doc-type filter is the InstrumentTypeId code. Party-type semantics
        # ("Grantor" / "Grantee" / "Both") are honored in the result-filter
        # layer (the pipeline), not at the HTTP layer (since the portal returns
        # both sides for any party name match).
        self.party_type_map = config.get(
            "party_type_map",
            {
                "Both": "Party",
                "All": "Party",
                "Grantor": "Party",
                "Grantee": "Party",
                "Party": "Party",
            },
        )
        self.supported_party_types = config.get(
            "supported_party_types", ["Party", "Grantor", "Grantee"]
        )

        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)

        self._antiforgery_token: Optional[str] = None
        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # Recipe-style doc-image URL pattern (mirrors Tyler / Broward).
        # Manatee's image URL is a static template: the only token is
        # ``{doc_id}`` (opaque Clerk DocID from the result row's view-icon
        # ``<a href="/OfficialRecords/DisplayInstrument/{doc_id}">``).
        pattern_cfg = config.get("doc_image_url_pattern", {})
        self._dip_pdf_url_template = pattern_cfg.get(
            "pdf_url_template",
            self._download_base_url.rstrip("/") + "/{doc_id}/1/1",
        )
        self._dip_assert_pdf_magic = bool(pattern_cfg.get("assert_pdf_magic", True))

        # Per-Instrument → opaque DocID cache. Canonical key name
        # ``_doc_id_by_number`` matches the pipeline's
        # ``recorder_internal_ids.json`` rehydrate target (see Tyler
        # adapter + pipeline._download_via_adapter).
        self._doc_id_by_number: Dict[str, str] = {}

        # ABC compliance: BaseRecorderSearch expects self.driver; we never use it.
        self.driver = None

    # -------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        return None

    # ----------------------------------------------------- session warm-up

    def warm_session(
        self,
        browser_minted_cookies: Optional[Dict] = None,
        cookie_jar_path: Optional[str] = None,
    ) -> bool:
        """Bootstrap the Manatee session.

        1. (Optional) pre-seed cookies from caller.
        2. GET the Party search page — this sets the
           ``__RequestVerificationToken`` cookie AND surfaces the matching
           hidden form-input value.
        3. Cache the form-input value on ``self._antiforgery_token``.

        Returns True on success; on False, ``self.last_failure`` is set.
        """
        if browser_minted_cookies:
            for name, value in browser_minted_cookies.items():
                self.session.cookies.set(name, value)

        try:
            token = self._refresh_antiforgery_token()
        except Exception as exc:
            print(f"  [warm_session] anti-forgery harvest failed: {exc}")
            self.last_failure = "needs_session_token"
            return False

        if not token:
            # Some Manatee responses have surfaced without the form-input value
            # (rare). Treat as warmable but mark the issue.
            print("  [warm_session] WARNING: token cookie present but form value missing")
        self._session_warmed = True
        return True

    # ----------------------------------------------------------- antiforgery

    def _refresh_antiforgery_token(self) -> Optional[str]:
        """GET the Party search page and scrape the hidden form input value.

        Side effect: the session cookie ``__RequestVerificationToken`` is
        established by the GET response itself (curl_cffi.Session keeps it).
        """
        resp = self.session.get(self._search_url, timeout=30)
        if resp.status_code == 403:
            self.last_failure = "needs_session_token"
            raise RuntimeError("403 fetching Party search page")
        resp.raise_for_status()

        html = resp.text
        m = _TOKEN_RE_A.search(html) or _TOKEN_RE_B.search(html)
        token = m.group(1) if m else None
        self._antiforgery_token = token
        return token

    # ---------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "Party",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search against Manatee Clerk records.

        Args:
            name: Party name (last-first, no comma). E.g. "FERNANDEZ PABLO".
            party_type: Cosmetic only — the portal returns both sides.
            doc_type: Optional semantic label ("DEED", "MORTGAGE", "SATISFACTION")
                      which is mapped to ``InstrumentTypeId``. Pass the raw
                      numeric code (e.g. "11") to forward as-is.
            date_from / date_to: MM/DD/YYYY (pipeline format) or YYYY-MM-DD.

        Returns a list of DocumentRecord. Empty on session failure.
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] session not warmed; "
                    f"last_failure={self.last_failure}"
                )
                return []

        mapped_party = self.party_type_map.get(party_type, "Party")
        # Currently used cosmetically: Manatee returns full party set regardless.
        del mapped_party

        sd = self._normalize_date(date_from or self.start_date)
        ed = self._normalize_date(date_to or self.end_date)

        # Translate semantic doc_type → InstrumentTypeId code.
        instrument_type_id = ""
        if doc_type:
            upper = doc_type.upper()
            if upper in self._doctype_codes:
                instrument_type_id = self._doctype_codes[upper]
            else:
                # Pass through (e.g. caller already gave numeric code).
                instrument_type_id = doc_type

        payload = {
            self._antiforgery_field: self._antiforgery_token or "",
            self._field_page_num: "1",
            self._field_page_size: "100",
            self._field_search_type: "Party",
            self._field_name: name,
            self._field_date_from: sd,
            self._field_date_to: ed,
            self._field_doc_type: instrument_type_id,
        }

        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self._search_url,
            "Origin": self._origin(),
        }

        resp = self.session.post(
            self._post_search_url,
            data=payload,
            headers=post_headers,
            timeout=60,
            allow_redirects=True,
        )

        if resp.status_code == 403:
            print("  [perform_search] 403 — refreshing token and retrying once")
            try:
                self._refresh_antiforgery_token()
                payload[self._antiforgery_field] = self._antiforgery_token or ""
                resp = self.session.post(
                    self._post_search_url,
                    data=payload,
                    headers=post_headers,
                    timeout=60,
                )
            except Exception as exc:
                print(f"  [perform_search] token refresh failed: {exc}")

            if resp.status_code == 403:
                self.last_failure = "needs_session_token"
                return []

        if resp.status_code != 200:
            print(
                f"  [perform_search] HTTP {resp.status_code} from DoSearch"
            )
            return []

        return self.extract_results(resp.text)

    # ------------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str) -> Dict:
        """Fetch the Manatee detail page for a given instrument number.

        Manatee's primary index already exposes most of what AcclaimWeb only
        shows on its detail page (parties, doc type, date, book/page, legal),
        so this method returns what it can from the View-image landing.

        We resolve the detail link by issuing a fresh Party search for the
        same instrument via the InstrumentNumber endpoint and then GETting
        the first matching row's DisplayInstrument page.
        """
        if not self._session_warmed:
            self.warm_session()

        sd = self._normalize_date(self.start_date)
        ed = self._normalize_date(self.end_date)
        payload = {
            self._antiforgery_field: self._antiforgery_token or "",
            self._field_page_num: "1",
            self._field_page_size: "10",
            self._field_search_type: "InstrumentNumber",
            self._field_instrument: doc_num,
            self._field_date_from: sd,
            self._field_date_to: ed,
        }
        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self._search_url_instrument,
            "Origin": self._origin(),
        }
        try:
            # Re-warm with the InstrumentNumber form to keep referers tidy.
            self.session.get(self._search_url_instrument, timeout=20)
            resp = self.session.post(
                self._post_search_url,
                data=payload,
                headers=post_headers,
                timeout=45,
            )
        except Exception as exc:
            return {"document_number": doc_num, "error": f"network: {exc}"}

        if resp.status_code != 200:
            return {
                "document_number": doc_num,
                "error": f"HTTP {resp.status_code}",
            }

        records = self.extract_results(resp.text)
        # Find the exact instrument match.
        match = next(
            (r for r in records if r.document_number == str(doc_num)), None
        )
        if not match:
            return {
                "document_number": doc_num,
                "error": "instrument not found in InstrumentNumber search",
            }

        # Pull the DocID for image download via the same row scrape.
        soup = BeautifulSoup(resp.text, "lxml")
        doc_id = ""
        for row in soup.select("tr.data-row"):
            if doc_num in row.get_text():
                a = row.find("a", href=_DOC_ID_HREF_RE)
                if a:
                    m = _DOC_ID_HREF_RE.search(a.get("href", ""))
                    if m:
                        doc_id = m.group(1)
                break

        return {
            "document_number": match.document_number,
            "recording_date": match.recording_date,
            "doc_type": match.document_type,
            "indexed_apn": "",  # Manatee Clerk does not index APN in records search
            "book_page": "/".join(
                v for v in [self._extract_book(resp.text, doc_num),
                            self._extract_page(resp.text, doc_num)] if v
            ),
            "parties": [
                {"role": "Grantor", "name": match.grantors},
                {"role": "Grantee", "name": match.grantees},
            ],
            "doc_id": doc_id,
            "raw_html_snippet": resp.text[:2000],
        }

    @staticmethod
    def _extract_book(html: str, doc_num: str) -> str:
        # Lightweight helper — not strictly required.
        return ""

    @staticmethod
    def _extract_page(html: str, doc_num: str) -> str:
        return ""

    # --------------------------------------------------------- extract_results

    def extract_results(self, html: str) -> List[DocumentRecord]:
        """Parse the Manatee result-table HTML into DocumentRecord rows.

        The Manatee result HTML uses ``<table id="results">`` with one
        ``<tr class="data-row">`` per record. Columns are fixed-order
        (see module docstring).
        """
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        results_tbl = soup.find("table", id="results")
        rows = []
        if results_tbl:
            rows = results_tbl.find_all("tr", class_="data-row")
        if not rows:
            rows = soup.find_all("tr", class_="data-row")

        documents: List[DocumentRecord] = []
        seen = set()

        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 11:
                continue

            # Cell 0: view icon → href contains doc_id
            doc_id = ""
            a = tds[0].find("a", href=True)
            if a:
                href_val = a["href"] or ""
                # First try the original "href=..."-anchored pattern (works
                # against raw HTML); fall back to a bare-path scan when
                # BeautifulSoup has already stripped the attribute quoting.
                m = _DOC_ID_HREF_RE.search(href_val)
                if not m:
                    m = re.search(
                        r"(?:/OfficialRecords)?/DisplayInstrument/(\d+)",
                        href_val,
                        re.IGNORECASE,
                    )
                if m:
                    doc_id = m.group(1)

            inst_no = tds[1].get_text(strip=True)
            if not inst_no or inst_no in seen:
                continue
            if not self._doc_number_re.match(inst_no):
                # Still keep it — Manatee may surface short instrument numbers
                # for older records — but flag.
                pass
            seen.add(inst_no)

            grantors = self._extract_list_cell(tds[2])
            grantees = self._extract_list_cell(tds[3])
            doc_type = tds[4].get_text(strip=True)
            book = tds[5].get_text(strip=True)
            page = tds[6].get_text(strip=True)
            # tds[7] = price, tds[8] = legal description (not in DocumentRecord)
            rec_date_raw = tds[9].get_text(strip=True)
            rec_date = self._normalize_recdate(rec_date_raw)
            pages = tds[10].get_text(strip=True)

            documents.append(
                DocumentRecord(
                    document_number=inst_no,
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
            # Cache the opaque DocID per-Instrument so download_pdf() can
            # resolve the image URL without re-issuing the search. The
            # pipeline's ``recorder_internal_ids.json`` sidecar reads this
            # exact attribute name.
            if inst_no and doc_id:
                self._doc_id_by_number[inst_no] = doc_id

        return documents

    @staticmethod
    def _extract_list_cell(td) -> str:
        """Manatee renders party lists as <ol><li>...</li></ol>. Flatten."""
        items = td.find_all("li")
        if items:
            return "; ".join(li.get_text(strip=True) for li in items)
        return td.get_text(strip=True)

    # ---------------------------------------------------- image-download URL

    def image_download_url(self, doc_id: str) -> str:
        """Compose the binary-image download URL for a given DocID.

        Uses the recipe-style ``doc_image_url_pattern.pdf_url_template`` from
        the county config (falls back to the legacy ``download_base_url`` +
        ``/{doc_id}/1/1`` concatenation if no template was configured).
        """
        if "{doc_id}" in self._dip_pdf_url_template:
            return self._dip_pdf_url_template.format(doc_id=doc_id)
        # Legacy back-compat — no token in template means caller wants
        # urljoin behaviour.
        return urljoin(self._download_base_url.rstrip("/") + "/",
                       f"{doc_id}/1/1")

    # -------------------------------------------------------------- download_pdf

    def _resolve_doc_id(self, doc_num: str) -> Optional[str]:
        """Resolve the opaque DocID for an Instrument number.

        Order of lookup:
          1. ``_doc_id_by_number`` (canonical cache; pipeline rehydrates from
             ``recorder_internal_ids.json``, ``extract_results`` populates).
        Falls back to a fresh ``pull_detail`` call if not cached.
        """
        if doc_num in self._doc_id_by_number:
            return self._doc_id_by_number[doc_num]
        return None

    def download_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Direct-portal PDF download — canonical pipeline entry point.

        Mirrors the Tyler / AcclaimWeb / Hillsborough contract. Returns:

        Success: ``{"status": "success", "size": int, "src_via": str,
                    "pdf_url": str, "doc": str, "file": str}``
        Failure: ``{"status": "error", "doc": str, "message": str,
                    "pdf_url"?: str}``

        Flow:
          1. Resolve opaque DocID from ``_doc_id_by_number`` cache
             (populated by ``extract_results`` during search; pipeline's
             ``recorder_internal_ids.json`` rehydrate also populates it).
          2. If not cached, fall back to ``pull_detail`` (re-issues an
             InstrumentNumber-keyed search to refresh the DocID).
          3. Compose URL via ``image_download_url(doc_id)`` (recipe template).
          4. GET the URL with the warmed session.
          5. Assert ``%PDF`` magic bytes, write to disk.
        """
        if not self._session_warmed:
            if not self.warm_session():
                return {
                    "status": "error",
                    "doc": doc_num,
                    "message": f"session warm-up failed: {self.last_failure}",
                }

        doc_id = self._resolve_doc_id(doc_num)
        if not doc_id:
            # Fall back: pull_detail re-issues the Instrument-keyed search
            # and writes the DocID into the cache as a side effect.
            detail = self.pull_detail(doc_num)
            if "error" in detail:
                return {
                    "status": "error",
                    "doc": doc_num,
                    "message": detail["error"],
                }
            scraped = detail.get("doc_id")
            if scraped:
                self._doc_id_by_number[doc_num] = scraped
                doc_id = scraped
        if not doc_id:
            return {
                "status": "error",
                "doc": doc_num,
                "message": "no opaque DocID available (search cache empty + pull_detail returned no doc_id)",
            }

        url = self.image_download_url(doc_id)
        try:
            resp = self.session.get(
                url,
                headers={
                    "Referer": self._search_url,
                    "Accept": "application/pdf,*/*",
                },
                timeout=120,
            )
        except Exception as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "message": f"network: {exc}",
                "pdf_url": url,
            }

        if resp.status_code != 200:
            return {
                "status": "error",
                "doc": doc_num,
                "message": f"HTTP {resp.status_code}",
                "pdf_url": url,
            }
        content = resp.content or b""
        if self._dip_assert_pdf_magic and content[:4] != b"%PDF":
            return {
                "status": "error",
                "doc": doc_num,
                "message": f"non-PDF response ({len(content)} bytes, first 4 bytes: {content[:4]!r})",
                "pdf_url": url,
            }

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)
        return {
            "status": "success",
            "doc": doc_num,
            "file": str(dest_path),
            "size": len(content),
            "src_via": "instrument_result_file",
            "pdf_url": url,
        }

    # --------------------------------------------------------------- helpers

    def _origin(self) -> str:
        # https://records.manateeclerk.com
        from urllib.parse import urlparse
        u = urlparse(self._search_url)
        return f"{u.scheme}://{u.netloc}"

    def _normalize_date(self, d: Optional[str]) -> str:
        """Accept MM/DD/YYYY or YYYY-MM-DD; emit YYYY-MM-DD (Manatee format)."""
        if not d:
            return ""
        s = d.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
        if m:
            mo, da, yr = m.groups()
            return f"{yr}-{int(mo):02d}-{int(da):02d}"
        return s

    @staticmethod
    def _normalize_recdate(d: str) -> str:
        """Manatee renders record date as MM-DD-YYYY; normalize to MM/DD/YYYY
        for parity with the rest of the pipeline."""
        if not d:
            return ""
        m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", d)
        if m:
            return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        return d
