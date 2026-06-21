"""
Leon County FL Official Records — lforms.leonclerk.com HTTP Adapter.

Leon County runs a proprietary classic-ASP search portal at
``lforms.leonclerk.com/official_records/``.  The portal has a Google
reCAPTCHA widget on the search form, but the server-side handler at
``search.asp?action=mainsearch`` does NOT validate the reCAPTCHA token
— the check is purely client-side JavaScript.  This adapter calls the
search endpoint directly via GET, no captcha token needed.

Search endpoint (GET):
    https://lforms.leonclerk.com/official_records/search.asp
    ?action=mainsearch
    &compressedname=LAST,FIRST   (spaces stripped, no ampersands)
    &xxbooktype=OR
    &xxdoctypekey=D              (doctype code; empty = all)
    &start_date=MM/DD/YYYY       (optional)
    &end_date=MM/DD/YYYY         (optional)
    &subnet=public
    &myUniqueID=1
    &SubscriberCode=510

Results:
    HTML page with <table id="example"> (DataTables).
    Columns: Grantor | Grantee | Doc Type | Record Date | Comments | Book/Page
    Book/Page cell: <a href="document_info.asp?documentid=NNNNN&...">BBBB/PPPPP</a>

Document detail:
    GET document_info.asp?documentid={ID}&myUniqueID=1&subnet='public'&SubscriberCode=510
    Returns HTML with full grantor/grantee lists, doc type, book/page, page count, record date.

PDF images:
    Gated behind clerkecertify.com (SubscriberCode 510 = paid purchase).
    Free download NOT available; set download_pdf to None / raise NotImplementedError.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord

_BASE = "https://lforms.leonclerk.com/official_records/"
_SEARCH_URL = _BASE + "search.asp"
_DETAIL_URL = _BASE + "document_info.asp"
_MY_UNIQUE_ID = "1"
_SUBSCRIBER_CODE = "510"

# Max results the server returns in one call (DataTables paging is client-side;
# server renders all rows — empirically up to 250 at a time).
_MAX_ROWS_PER_PAGE = 250

# Doctype code mapping (Leon uses short codes, not integers).
_DOCTYPE_MAP: Dict[str, str] = {
    "DEED": "D",
    "D": "D",
    "MORTGAGE": "MTG",
    "MTG": "MTG",
    "SATISFACTION": "SAT",
    "SAT": "SAT",
    "RELEASE": "REL",
    "REL": "REL",
    "LIEN": "LN",
    "LN": "LN",
    "FEDERAL LIEN": "FL",
    "FL": "FL",
    "ASSIGNMENT": "ASG",
    "ASG": "ASG",
    "CIVIL": "CIV",
    "CIV": "CIV",
}


class LeonLformsHTTPAdapter(BaseRecorderSearch):
    """
    Pure-HTTP adapter for Leon County FL official records (lforms.leonclerk.com).

    No Selenium, no Cloudflare, no captcha validation needed server-side.
    Extends BaseRecorderSearch to integrate with the pipeline registry.
    """

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/1985",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config
        self._county_name = config.get("county_name", "Leon")
        self._base_url = config.get("base_url", _BASE)
        self._search_url = config.get("search_url", _SEARCH_URL)
        self._detail_url = config.get("detail_url", _DETAIL_URL)
        self._my_unique_id = config.get("my_unique_id", _MY_UNIQUE_ID)
        self._subscriber_code = config.get("subscriber_code", _SUBSCRIBER_CODE)
        self._doctype_deed_code = config.get("doctype_deed_code", "D")

        impersonate = config.get("impersonate_profile", "safari17_2_ios")
        self.session = _cffi_requests.Session(impersonate=impersonate)
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})
        self.last_failure: Optional[str] = None

    # ------------------------------------------------------------------
    # BaseRecorderSearch ABC implementations
    # ------------------------------------------------------------------

    @property
    def county_name(self) -> str:  # type: ignore[override]
        return self._county_name

    @property
    def base_url(self) -> str:  # type: ignore[override]
        return self._base_url

    def setup_driver(self):
        pass

    def navigate_to_search(self):
        pass

    def return_to_search(self):
        pass

    # ------------------------------------------------------------------
    # Core search
    # ------------------------------------------------------------------

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """
        Search Leon County official records by name.

        Parameters
        ----------
        name:
            Full name to search. Accepts "LAST FIRST" or "LAST,FIRST" or just "LAST".
        party_type:
            Ignored for this portal (no party-type filtering on the search URL).
        doc_type:
            Optional doctype filter. Pass ``"DEED"`` or ``"D"`` for deed-first search.
            Pass ``None`` or ``""`` for all doc types.
        start_date, end_date:
            Date range in ``MM/DD/YYYY`` format.  Defaults to instance values.

        Returns
        -------
        List[DocumentRecord]
        """
        self.last_failure = None

        # Normalise name → compressed (no spaces, no ampersands)
        compressed = self._compress_name(name)
        # Map doctype
        dt_code = self._resolve_doctype(doc_type)
        sd = start_date or self.start_date or ""
        ed = end_date or self.end_date or ""

        params = {
            "action": "mainsearch",
            "compressedname": compressed,
            "xxbooktype": "OR",
            "xxdoctypekey": dt_code,
            "start_date": sd,
            "end_date": ed,
            "subnet": "public",
            "myUniqueID": self._my_unique_id,
            "SubscriberCode": self._subscriber_code,
        }

        try:
            resp = self.session.get(
                self._search_url,
                params=params,
                timeout=30,
                allow_redirects=True,
            )
        except Exception as exc:
            self.last_failure = f"request_error:{exc}"
            return []

        if resp.status_code != 200:
            self.last_failure = f"http_{resp.status_code}"
            return []

        return self._parse_results(resp.text, name)

    # ------------------------------------------------------------------
    # Deed-first helper (Tony's Directive 2)
    # ------------------------------------------------------------------

    def search_deed_first(
        self,
        name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """
        Perform deed-first search (Directive 2).
        Returns DEED docs only in the first call, then falls back to all docs
        for a second pass if needed.
        """
        deeds = self.perform_search(
            name, doc_type="D", start_date=start_date, end_date=end_date
        )
        all_docs = self.perform_search(
            name, doc_type=None, start_date=start_date, end_date=end_date
        )
        # Merge: deeds first, then the rest deduplicated by document_number
        seen = {d.document_number for d in deeds}
        extra = [d for d in all_docs if d.document_number not in seen]
        return deeds + extra

    # ------------------------------------------------------------------
    # Document detail
    # ------------------------------------------------------------------

    def fetch_detail(self, document_id: str) -> Dict[str, Any]:
        """
        Fetch metadata from document_info.asp for the given documentid.

        Returns a dict with keys: grantors (list), grantees (list),
        doc_type, book_page, pages, record_date, consideration.
        """
        params = {
            "documentid": document_id,
            "myUniqueID": self._my_unique_id,
            "subnet": "'public'",
            "SubscriberCode": self._subscriber_code,
            "cust_name": "''",
            "cust_email": "''",
        }
        try:
            r = self.session.get(self._detail_url, params=params, timeout=30)
        except Exception as exc:
            return {"error": str(exc)}

        if r.status_code != 200:
            return {"error": f"http_{r.status_code}"}

        return self._parse_detail(r.text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compress_name(self, name: str) -> str:
        """Convert 'LAST FIRST' or 'LAST, FIRST' → 'LAST,FIRST' (no spaces, no &)."""
        # Replace comma+space → comma; strip &
        n = name.strip().upper()
        n = re.sub(r",\s+", ",", n)
        n = n.replace("&", "")
        n = re.sub(r"\s+", ",", n, count=1)  # first space → comma (last,first)
        return n

    def _resolve_doctype(self, doc_type: Optional[str]) -> str:
        """Return the Leon doctype code string; '' means all types."""
        if not doc_type:
            return ""
        upper = doc_type.strip().upper()
        return _DOCTYPE_MAP.get(upper, upper)

    def _parse_results(self, html: str, name_searched: str) -> List[DocumentRecord]:
        """
        Parse the search.asp response HTML table into DocumentRecord objects.

        Table #example columns (0-based):
            0 Grantor
            1 Grantee
            2 Doc Type
            3 Record Date (MM/DD/YYYY)
            4 Comments
            5 Book/Page   → contains <a href="document_info.asp?documentid=NNNNN&...">
        """
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="example")
        if not table:
            # Check for error messages
            if "no recordings for your search criteria" in html.lower():
                return []
            if "exceeded the maximum limit" in html.lower():
                # Too many results — log but return empty; caller should narrow search
                self.last_failure = "too_many_results"
                return []
            self.last_failure = "no_table_found"
            return []

        records: List[DocumentRecord] = []
        tbody = table.find("tbody")
        if not tbody:
            return records

        rows = tbody.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue
            grantor = cells[0].get_text(separator=" ", strip=True)
            grantee = cells[1].get_text(separator=" ", strip=True)
            doc_type = cells[2].get_text(strip=True)
            rec_date = cells[3].get_text(strip=True)
            # Book/Page cell contains the link with documentid
            bp_cell = cells[5]
            bp_text = bp_cell.get_text(strip=True)
            link = bp_cell.find("a", href=True)
            doc_id = ""
            if link:
                m = re.search(r"documentid=(\d+)", link["href"])
                if m:
                    doc_id = m.group(1)

            records.append(
                DocumentRecord(
                    document_number=doc_id or bp_text,
                    grantors=grantor,
                    grantees=grantee,
                    grantor_grantees=f"{grantor} / {grantee}",
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages="",
                )
            )
        return records

    def _parse_detail(self, html: str) -> Dict[str, Any]:
        """Parse document_info.asp HTML into a metadata dict."""
        soup = BeautifulSoup(html, "html.parser")
        result: Dict[str, Any] = {
            "grantors": [],
            "grantees": [],
            "doc_type": "",
            "book_page": "",
            "pages": "",
            "record_date": "",
            "consideration": "",
        }
        tables = soup.find_all("table")
        if not tables:
            return result

        # Table 0: grantor/grantee names
        if len(tables) >= 1:
            cells = tables[0].find_all("td")
            if len(cells) >= 2:
                result["grantors"] = [
                    n.strip()
                    for n in cells[0].get_text("\n").split("\n")
                    if n.strip()
                ]
                result["grantees"] = [
                    n.strip()
                    for n in cells[1].get_text("\n").split("\n")
                    if n.strip()
                ]

        # Table 1: doc type, book/page, pages, record date, consideration
        if len(tables) >= 2:
            row = tables[1].find("tr", class_=None)
            # Find the data row (second tr)
            data_rows = tables[1].find_all("tr")
            if len(data_rows) >= 2:
                data_cells = data_rows[1].find_all("td")
                keys = ["doc_type", "book_page", "pages", "record_date", "consideration"]
                for i, key in enumerate(keys):
                    if i < len(data_cells):
                        result[key] = data_cells[i].get_text(strip=True)

        return result

    # ------------------------------------------------------------------
    # extract_results compat shim (called by pipeline harness)
    # ------------------------------------------------------------------

    def extract_results(self) -> List[DocumentRecord]:
        """Compat shim — results are returned directly from perform_search."""
        return []
