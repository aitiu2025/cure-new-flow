"""
AcclaimWeb (older Telerik-based) HTTP Adapter — Santa Rosa County FL.

This adapter covers the **older generation of AcclaimWeb** that uses
Telerik RadGrid 2012.1.214 and a Telerik TreeView for name disambiguation.
It is distinct from the Kendo-based AcclaimWeb used by Broward/Saint Lucie
(``acclaimweb_http_adapter.py``).

Portal: https://acclaim.srccol.com/AcclaimWeb/  (Santa Rosa)

Three-step search flow
-----------------------
1. **Disclaimer** — POST to ``/AcclaimWeb/Search/Disclaimer?st=/AcclaimWeb/search/SearchTypeName``
   with ``{disclaimer: true}``.  Sets a session cookie that bypasses the
   disclaimer page on subsequent requests.

2. **Name search (Step 1)** — POST to ``/AcclaimWeb/search/SearchTypeName?Length=6``
   with form fields (name, date range, doc types).  Returns an HTML page containing
   a Telerik TreeView of matching indexed name variants.

3. **Name selection (Step 2)** — POST to ``/AcclaimWeb/Search/SearchTypePreName``
   with the TreeView checked-node structure (selecting specific name variants) plus
   all hidden context fields carried over from Step 1.  The server stores results
   in session state and the Telerik RadGrid renders an empty skeleton.

Result extraction via ExportCsv
---------------------------------
After Step 2, the session holds the result set.  A simple GET to
``/AcclaimWeb/Search/ExportCsv`` returns a CSV with all results:

    Consideration,Party,Name,CrossPartyName,InstrumentNumber,RecordDate,
    DocTypeDescription,BookType,BookPage,DocLink,CaseNumber,Comments

No pagination needed — ExportCsv delivers all rows in one shot.

Doctype filtering
------------------
DocTypes is sent as an integer ID (e.g., ``79`` for DEED(D)).  Pass ``all``
to retrieve all document types.  See ``DOCTYPE_CODES`` for the mapping.

No Cloudflare, no Akamai
--------------------------
acclaim.srccol.com is plain ASP.NET/IIS with no anti-bot layer.
``curl_cffi`` with safari17_2_ios impersonation is used for consistency,
but any impersonation profile works.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord

# ---------------------------------------------------------------------------
# DocType IDs — from the DocTypeGroupDropDown of acclaim.srccol.com
# (Santa Rosa-specific; other Telerik AcclaimWeb tenants may differ)
# ---------------------------------------------------------------------------
DOCTYPE_CODES: Dict[str, str] = {
    # Integer IDs
    "DEED": "79",
    "D": "79",
    "WARRANTY DEED": "79",
    "WD": "79",
    "MORTGAGE": "91",
    "MTG": "91",
    "SATISFACTION": "122",
    "SAT": "122",
    "RELEASE": "119",
    "REL": "119",
    "LIEN": "85",          # FINANCING STATEMENT
    "FIN": "85",
    "JUDGMENT": "88",
    "J": "88",
    "AGREEMENT": "68",
    "AGD": "68",
    "QCD": "109",
    "QUIT CLAIM DEED": "109",
    "EASEMENT": "83",
    "EAS": "83",
    "TIMESHARE DEED": "130",
    "TSD": "130",
    "TAX DEED": "127",
    "TD": "127",
    # Catch-all
    "ALL": "all",
    "": "all",
}


class AcclaimWebTelerikHTTPAdapter(BaseRecorderSearch):
    """
    Pure-HTTP adapter for the older Telerik-based AcclaimWeb portal.

    Tested against Santa Rosa County FL (acclaim.srccol.com, 2026-06-18).
    Should work for any Telerik-era AcclaimWeb tenant with the same form
    layout (Telerik 2012.1.214, three-step name search).
    """

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2000",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config
        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "").rstrip("/") + "/"

        self._disclaimer_path = config.get(
            "disclaimer_path", "Search/Disclaimer"
        )
        self._step1_path = config.get(
            "step1_path", "search/SearchTypeName"
        )
        self._step2_path = config.get(
            "step2_path", "Search/SearchTypePreName"
        )
        self._export_csv_path = config.get(
            "export_csv_path", "Search/ExportCsv"
        )
        self._instrument_path = config.get(
            "instrument_path", "search/SearchTypeInstrumentNumber"
        )

        self._doctype_deed_code = config.get("doctype_deed_code", "79")
        self._book_types = config.get("book_types_code", "All")

        impersonate = config.get("impersonate_profile", "safari17_2_ios")
        self.session = _cffi_requests.Session(impersonate=impersonate)
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

        self._disclaimer_accepted: bool = False
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
    # Public API
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
        Search by name.  Returns all matching DocumentRecord objects.

        Parameters
        ----------
        name:
            Searcher name.  Accepts "LAST FIRST", "LAST,FIRST", or just "LAST".
        party_type:
            ``"Both"`` | ``"Direct"`` (grantor) | ``"Reverse"`` (grantee).
        doc_type:
            Doctype filter.  ``"DEED"`` / ``"D"`` for deed-first; ``None`` for all.
        start_date, end_date:
            ``MM/DD/YYYY``.
        """
        self.last_failure = None

        # Build compressed name (LAST,FIRST)
        formatted_name = self._format_name(name)
        dt_code = self._resolve_doctype(doc_type)
        sd = start_date or self.start_date or "01/01/1982"
        ed = end_date or self.end_date or datetime.today().strftime("%m/%d/%Y")
        party = party_type if party_type in ("Both", "Direct", "Reverse") else "Both"

        # Step 0: Accept disclaimer (once per session)
        if not self._disclaimer_accepted:
            ok = self._accept_disclaimer()
            if not ok:
                return []

        # Step 1: Name search → name tree
        name_tree, context = self._step1_name_search(
            formatted_name, party, dt_code, sd, ed
        )
        if name_tree is None:
            return []

        # Step 2: Select matching leaf names → store results in session.
        # NOTE: Santa Rosa's Telerik server returns HTTP 500 when MORE THAN ONE
        # leaf is selected in a single POST with a doctype filter active.
        # Fix (Tony directive #3 — run ALL name variants): loop one ExportCsv
        # search per matching leaf and union the results, deduplicating by
        # document_number.  This avoids the 500 while honoring all name variants.
        matching_leaves = self._select_leaf_names(name_tree, formatted_name)
        if not matching_leaves:
            # No match for full name; try surname-only prefix
            surname = name.split(",")[0].split()[0]
            matching_leaves = self._select_leaf_names(name_tree, surname)
        if not matching_leaves:
            # Last resort: first available leaf
            leaves = [v for _, v, t in name_tree if t == "leaf"]
            matching_leaves = leaves[:1]

        # Loop one leaf at a time; union + dedup by document_number.
        all_records: List[DocumentRecord] = []
        seen_nums: set = set()
        for leaf in matching_leaves:
            ok2 = self._step2_select_names(name_tree, [leaf], leaf, context)
            if not ok2:
                # If this leaf triggers a 500, log and skip (don't abort the whole search)
                self.last_failure = (
                    self.last_failure or f"step2_failed_for_leaf:{leaf}"
                )
                print(
                    f"  [telerik/{self._county_name}] step2 failed for leaf "
                    f"'{leaf}' — skipping (last_failure={self.last_failure})"
                )
                continue
            leaf_records = self._export_csv(name)
            for r in leaf_records:
                if r.document_number and r.document_number not in seen_nums:
                    seen_nums.add(r.document_number)
                    all_records.append(r)

        return all_records

    def search_deed_first(
        self,
        name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Deed-first search (Tony Directive 2): DEED first, then all docs."""
        deeds = self.perform_search(name, doc_type="DEED", start_date=start_date, end_date=end_date)
        all_docs = self.perform_search(name, doc_type=None, start_date=start_date, end_date=end_date)
        seen = {d.document_number for d in deeds}
        extra = [d for d in all_docs if d.document_number not in seen]
        return deeds + extra

    # ------------------------------------------------------------------
    # Step 0: Disclaimer
    # ------------------------------------------------------------------

    def _accept_disclaimer(self) -> bool:
        """POST the disclaimer form to set the session cookie."""
        url = self._base_url + self._disclaimer_path
        target = self._base_url + self._step1_path
        # The server's redirect target uses the full server path (e.g.
        # /AcclaimWeb/search/SearchTypeName), not just /search/SearchTypeName.
        # Derive the base path from base_url (strip scheme+host to get /AcclaimWeb/).
        from urllib.parse import urlparse
        parsed = urlparse(self._base_url)
        base_path = parsed.path.rstrip("/")   # e.g. '/AcclaimWeb'
        st_param = base_path + "/" + self._step1_path.lstrip("/")
        try:
            r = self.session.post(
                url,
                params={"st": st_param},
                data={"disclaimer": "true"},
                headers={"Referer": target},
                allow_redirects=True,
                timeout=20,
            )
            if r.status_code in (200, 302):
                self._disclaimer_accepted = True
                return True
            self.last_failure = f"disclaimer_http_{r.status_code}"
            return False
        except Exception as exc:
            self.last_failure = f"disclaimer_error:{exc}"
            return False

    # ------------------------------------------------------------------
    # Step 1: Name search → Telerik TreeView
    # ------------------------------------------------------------------

    def _step1_name_search(
        self,
        formatted_name: str,
        party_type: str,
        dt_code: str,
        sd: str,
        ed: str,
    ) -> Tuple[Optional[List[Tuple[str, str, str]]], Dict[str, str]]:
        """
        POST to SearchTypeName to get the name disambiguation tree.

        Returns
        -------
        (name_tree, context)
        name_tree: list of (index_str, leaf_value, parent_value) tuples
        context: dict of hidden context fields for Step 2
        """
        url = self._base_url + self._step1_path + "?Length=6"
        data = {
            "IsParsedName": "False",
            "PartyType": party_type,
            "SearchOnName": formatted_name,
            "DateRangeList": " ",
            "DocTypes": dt_code,
            "DocTypesDisplay-input": dt_code if dt_code != "all" else "All",
            "DocTypesDisplay": dt_code if dt_code != "all" else "",
            "RecordDateFrom": sd,
            "BookTypesDisplay": "All",
            "BookTypes": self._book_types,
            "BookTypeInfoCheckBox": ["2", "3"],
            "RecordDateTo": ed,
        }
        if dt_code != "all":
            data["DocTypeInfoCheckBox"] = dt_code

        try:
            r = self.session.post(
                url,
                data=data,
                headers={
                    "Referer": self._base_url + self._step1_path,
                    "X-Requested-With": "XMLHttpRequest",
                },
                allow_redirects=True,
                timeout=30,
            )
        except Exception as exc:
            self.last_failure = f"step1_error:{exc}"
            return None, {}

        if r.status_code != 200:
            self.last_failure = f"step1_http_{r.status_code}"
            return None, {}

        if "exceeded the maximum limit" in r.text.lower():
            self.last_failure = "too_many_results"
            return None, {}
        if "ShowError" in r.text or "no recordings" in r.text.lower():
            return [], {}

        return self._parse_name_tree(r.text), self._extract_context(r.text, dt_code, party_type, formatted_name, sd, ed)

    def _parse_name_tree(self, html: str) -> List[Tuple[str, str, str]]:
        """
        Parse the Telerik TreeView HTML and return (index_path, item_value, type) tuples.

        type = 'parent' for group nodes (e.g. 'WHITE (17)'), 'leaf' for specific names.
        """
        soup = BeautifulSoup(html, "html.parser")
        tree = soup.find(id="NameListTreeView")
        if not tree:
            return []

        results = []
        for li in tree.find_all("li"):
            idx_inp = li.find("input", {"name": "NameListTreeView_checkedNodes.Index"})
            val_inp = li.find("input", {"name": "itemValue"})
            if not idx_inp or not val_inp:
                continue
            idx = idx_inp.get("value", "")
            val = val_inp.get("value", "")
            # leaf nodes have index like "0:0", "0:1"; parent = "0"
            node_type = "leaf" if ":" in idx else "parent"
            results.append((idx, val, node_type))
        return results

    def _extract_context(
        self,
        html: str,
        dt_code: str,
        party_type: str,
        formatted_name: str,
        sd: str,
        ed: str,
    ) -> Dict[str, str]:
        """Extract hidden context fields from Step 1 response for Step 2 POST."""
        soup = BeautifulSoup(html, "html.parser")
        ctx: Dict[str, str] = {}

        # Prefer the hidden div fields if present
        hidden_div = soup.find("div", style="display:none;")
        if hidden_div:
            for inp in hidden_div.find_all("input"):
                n = inp.get("name", "")
                v = inp.get("value", "")
                if n:
                    ctx[n] = v
        # Fallback: set from known values
        ctx.setdefault("PartyType", party_type)
        ctx.setdefault("RecordDateFrom", sd + " 12:00:00 AM")
        ctx.setdefault("RecordDateTo", ed + " 12:00:00 AM")
        ctx.setdefault("BookTypes", self._book_types)
        ctx.setdefault("DocTypes", dt_code)
        ctx.setdefault("SearchOnName", formatted_name)
        ctx.setdefault("SearchOnLastOrBusinessName", "")
        ctx.setdefault("SearchOnFirstName", "")
        ctx.setdefault("ShowAllNames", "")
        ctx.setdefault("ShowAllLegals", "")
        return ctx

    # ------------------------------------------------------------------
    # Step 2: Select names → POST to SearchTypePreName
    # ------------------------------------------------------------------

    def _select_leaf_names(
        self,
        name_tree: List[Tuple[str, str, str]],
        target_name_prefix: str,
    ) -> List[str]:
        """
        From the name tree, return leaf names that match target_name_prefix.

        Strategy (avoids the multi-leaf 500 bug on Santa Rosa's Telerik server):
        1. Try exact match first (e.g. 'WHITE TIMOTHY' == 'WHITE TIMOTHY').
        2. If no exact match, fall back to prefix match (for partial first names).

        Normalises whitespace and commas for comparison.
        """
        normalized = target_name_prefix.upper().strip().replace(",", " ")
        # Collapse multiple spaces
        while "  " in normalized:
            normalized = normalized.replace("  ", " ")

        leaves = [val for idx, val, ntype in name_tree if ntype == "leaf"]

        # 1. Exact match
        exact = [v for v in leaves if v.upper() == normalized]
        if exact:
            return exact

        # 2. Prefix match (caller may have supplied surname only, e.g. "WHITE")
        prefix_matches = [v for v in leaves if v.upper().startswith(normalized)]
        return prefix_matches

    def _step2_select_names(
        self,
        name_tree: List[Tuple[str, str, str]],
        selected_names: List[str],
        name_list_str: str,
        context: Dict[str, str],
    ) -> bool:
        """
        POST to SearchTypePreName selecting the specified leaf names.
        The server stores results in session; retrieve via ExportCsv.
        """
        url = self._base_url + self._step2_path
        selected_set = set(selected_names)

        # Build multipart POST body as list of (key, value) pairs to allow
        # repeated keys (required for NameListTreeView_checkedNodes.Index etc.)
        post_data = [("NameList", name_list_str)]

        for idx, val, node_type in name_tree:
            post_data.append(("NameListTreeView_checkedNodes.Index", idx))
            # Construct checked key
            checked_key = f"NameListTreeView_checkedNodes[{idx}].Checked"
            is_selected = node_type == "leaf" and val in selected_set
            post_data.append((checked_key, "True" if is_selected else "False"))
            post_data.append(("itemValue", val))

        # Append context fields
        for k, v in context.items():
            post_data.append((k, v))

        try:
            r = self.session.post(
                url,
                data=post_data,
                headers={
                    "Referer": self._base_url + self._step1_path,
                    "X-Requested-With": "XMLHttpRequest",
                },
                allow_redirects=True,
                timeout=30,
            )
        except Exception as exc:
            self.last_failure = f"step2_error:{exc}"
            return False

        if r.status_code != 200:
            self.last_failure = f"step2_http_{r.status_code}"
            return False

        if "ShowError" in r.text:
            self.last_failure = "step2_server_error"
            return False

        return True

    # ------------------------------------------------------------------
    # Result extraction via ExportCsv
    # ------------------------------------------------------------------

    def _export_csv(self, name_searched: str) -> List[DocumentRecord]:
        """
        GET /AcclaimWeb/Search/ExportCsv — returns all result rows as CSV.

        CSV columns:
            Consideration, Party, Name, CrossPartyName, InstrumentNumber,
            RecordDate, DocTypeDescription, BookType, BookPage, DocLink,
            CaseNumber, Comments
        """
        url = self._base_url + self._export_csv_path
        try:
            r = self.session.get(url, timeout=30)
        except Exception as exc:
            self.last_failure = f"csv_error:{exc}"
            return []

        if r.status_code != 200:
            self.last_failure = f"csv_http_{r.status_code}"
            return []

        return self._parse_csv(r.text, name_searched)

    def _parse_csv(self, csv_text: str, name_searched: str) -> List[DocumentRecord]:
        """Parse ExportCsv response into DocumentRecord list."""
        # Strip BOM
        text = csv_text.lstrip("﻿").lstrip()
        reader = csv.DictReader(io.StringIO(text))
        records: List[DocumentRecord] = []

        for row in reader:
            party = row.get("Party", "").strip()     # 'From' or 'To'
            name = row.get("Name", "").strip()        # Searched party
            cross = row.get("CrossPartyName", "").strip()

            if party.lower() == "from":
                grantor = name
                grantee = cross
            else:
                grantor = cross
                grantee = name

            # InstrumentNumber is the canonical document_number
            doc_num = row.get("InstrumentNumber", "").strip()
            rec_date_raw = row.get("RecordDate", "").strip()
            # Normalise date: "M/D/YYYY HH:MM:SS AM" → "MM/DD/YYYY"
            rec_date = self._normalize_date(rec_date_raw)
            doc_type = row.get("DocTypeDescription", "").strip()
            book_page = row.get("BookPage", "").strip()
            comments = row.get("Comments", "").strip()

            records.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=grantor,
                    grantees=grantee,
                    grantor_grantees=f"{grantor} / {grantee}",
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages="",  # not in CSV
                )
            )
        return records

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_name(self, name: str) -> str:
        """
        Convert name to the format accepted by SearchOnName field:
        "LAST,FIRST" or just "LAST".
        """
        n = name.strip().upper()
        # Replace 'LAST FIRST' → 'LAST,FIRST'
        n = re.sub(r",\s+", ",", n)          # normalise comma+space
        # If no comma, insert one at first space boundary
        if "," not in n:
            parts = n.split(None, 1)
            if len(parts) == 2:
                n = parts[0] + "," + parts[1]
        return n

    def _resolve_doctype(self, doc_type: Optional[str]) -> str:
        """Return the integer doctype ID string or 'all'."""
        if not doc_type:
            return "all"
        upper = doc_type.strip().upper()
        return DOCTYPE_CODES.get(upper, "all")

    def _normalize_date(self, raw: str) -> str:
        """Convert '1/13/2015 3:13:16 PM' → '01/13/2015'."""
        if not raw:
            return raw
        try:
            # Strip time component
            date_part = raw.split(" ")[0]
            # Parse M/D/YYYY
            dt = datetime.strptime(date_part, "%m/%d/%Y")
            return dt.strftime("%m/%d/%Y")
        except ValueError:
            return raw

    def extract_results(self) -> List[DocumentRecord]:
        """Compat shim — results returned directly from perform_search."""
        return []

    # ------------------------------------------------------------------ download_pdf

    def download_pdf(self, doc_num: str, dest_path: "Path") -> Dict[str, Any]:
        """Download a document PDF from Santa Rosa AcclaimWeb via Selenium.

        The older Telerik AcclaimWeb uses Atala WebDocumentViewer which
        requires a real browser to trigger the TIFF-to-PDF conversion
        (the Atala image server won't serve PDFs via pure HTTP because the
        conversion is triggered client-side via JS). We spin up a headless
        Chrome session, navigate to the detail page, wait for the Atala
        conversion to complete, then download from the WebAtalaCache URL.

        Strategy (in order):
        1. Accept disclaimer (sets session cookie in the Selenium browser).
        2. Navigate to Image/DocumentImage1/{doc_num} (the viewer iframe URL).
           This page's JS includes a `WebAtalaCache/` path with the PDF URL.
        3. Parse the `WebAtalaCache/{hash}_{doc_num}_docPdf.pdf` path from
           the page source. The Atala viewer JS triggers conversion after 4.5 s.
        4. Wait up to 45 s for the WebAtalaCache URL to return a valid PDF
           (retry with 3s backoff).
        5. If the WebAtalaCache URL still fails, try
           Image/DocumentPdfAllPages/{doc_num} directly.
        6. If all attempts fail, return a graceful engineering-ticket error so
           the pipeline can continue with strict_downloads=false.

        Returns the standard adapter contract dict:
          success: {"status": "success", "size": int, "src_via": str}
          failure: {"status": "error", "error": str, "phase": str}
        """
        from pathlib import Path as _Path
        import time as _time
        import tempfile as _tempfile
        import shutil as _shutil
        import os as _os
        import re as _re
        from urllib.parse import urlparse as _urlparse

        dest_path = _Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "import_selenium",
                "error": (
                    f"Selenium not installed: {exc}. Engineering ticket "
                    "SR-DOWNLOAD-001: Santa Rosa Atala WebDocumentViewer "
                    "requires browser-JS triggered PDF conversion."
                ),
            }

        base = self._base_url.rstrip("/")
        # Derive the base path prefix (e.g. '/AcclaimWeb') from the URL.
        parsed = _urlparse(base)
        base_path = parsed.path.rstrip("/")  # e.g. '/AcclaimWeb'
        # Disclaimer redirect target — full server path, not just the page name.
        st_param = base_path + "/search/SearchTypeName"

        download_dir = _tempfile.mkdtemp(prefix="sr_dl_")
        try:
            chrome_prefs = {
                "download.default_directory": download_dir,
                "download.prompt_for_download": False,
                "plugins.always_open_pdf_externally": True,
            }
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1280,900")
            opts.add_experimental_option("prefs", chrome_prefs)
            opts.add_experimental_option("excludeSwitches", ["enable-logging"])

            try:
                driver = webdriver.Chrome(options=opts)
            except Exception as exc:
                return {
                    "status": "error",
                    "doc": doc_num,
                    "phase": "launch_selenium",
                    "error": (
                        f"ChromeDriver failed to start: {exc}. Engineering ticket "
                        "SR-DOWNLOAD-001: implement Selenium-based download for "
                        "Santa Rosa Atala WebDocumentViewer."
                    ),
                }

            try:
                # Step 1: Accept disclaimer (sets the session cookie in the browser).
                disclaimer_url = f"{base}/Search/Disclaimer?st={st_param}"
                driver.get(disclaimer_url)
                _time.sleep(0.5)
                # Submit the disclaimer form if it exists.
                try:
                    form = driver.find_element("css selector", "form")
                    driver.execute_script(
                        """
                        var f = arguments[0];
                        var inp = document.createElement('input');
                        inp.type = 'hidden'; inp.name = 'disclaimer'; inp.value = 'true';
                        f.appendChild(inp);
                        f.submit();
                        """,
                        form,
                    )
                    _time.sleep(1)
                except Exception:
                    pass  # may have already redirected

                # Step 2: Navigate to the Atala image viewer iframe URL.
                # This page embeds the WebAtalaCache PDF path in a JS setTimeout.
                # The Atala viewer starts converting TIFF→PDF when the JS runs.
                img_url = f"{base}/Image/DocumentImage1/{doc_num}"
                driver.get(img_url)
                # Wait for page to fully load (the Atala JS is in a $(document).ready).
                _time.sleep(2)

                # Step 3: Parse the WebAtalaCache path from the page source.
                # Expected pattern: WebAtalaCache/<hash>_<doc_num>_docPdf.pdf
                page_src = driver.page_source or ""
                atala_match = _re.search(
                    r"WebAtalaCache/([^'\"]+_docPdf\.pdf)", page_src
                )
                atala_cache_path: Optional[str] = None
                if atala_match:
                    atala_cache_path = atala_match.group(0)  # e.g. WebAtalaCache/xxx_docPdf.pdf

                # Step 4: Wait for the Atala setTimeout (4500 ms) + conversion time.
                # The JS calls printJS after 4.5 s; we wait 6 s then retry the cache URL.
                _time.sleep(6)

                # Step 5a: Try the WebAtalaCache URL if we found it.
                atala_succeeded = False
                if atala_cache_path:
                    atala_url = f"{base}/{atala_cache_path}"
                    for _attempt in range(8):  # up to ~24 s of retries
                        try:
                            r = self.session.get(atala_url, timeout=15)
                            if r.status_code == 200 and r.content[:4] == b"%PDF":
                                dest_path.write_bytes(r.content)
                                return {
                                    "status": "success",
                                    "size": len(r.content),
                                    "src_via": "http_acclaimweb_telerik_atala_cache",
                                    "pdf_url": atala_url,
                                }
                            # Not a PDF yet (404 or 500) — still converting.
                        except Exception:
                            pass
                        _time.sleep(3)

                # Step 5b: Navigate Selenium to DocumentPdfAllPages and wait for download.
                pdf_url = f"{base}/Image/DocumentPdfAllPages/{doc_num}"
                driver.get(pdf_url)
                deadline = _time.time() + 30
                pdf_file = None
                while _time.time() < deadline:
                    candidates = [
                        f for f in _os.listdir(download_dir)
                        if f.endswith(".pdf") and not f.endswith(".crdownload")
                    ]
                    if candidates:
                        pdf_file = _os.path.join(download_dir, candidates[0])
                        _time.sleep(0.5)
                        break
                    _time.sleep(1)

                if pdf_file and _os.path.exists(pdf_file):
                    with open(pdf_file, "rb") as fh:
                        content = fh.read()
                    if content[:4] == b"%PDF":
                        _shutil.copy2(pdf_file, dest_path)
                        return {
                            "status": "success",
                            "size": len(content),
                            "src_via": "selenium_acclaimweb_telerik_pdf_all_pages",
                            "pdf_url": pdf_url,
                        }
                    snippet = content[:256].decode("utf-8", errors="replace")
                    return {
                        "status": "error",
                        "doc": doc_num,
                        "phase": "pdf_magic_check",
                        "error": (
                            f"Download was not a PDF (magic={content[:8]!r}). "
                            f"Snippet: {snippet!r}. Engineering ticket SR-DOWNLOAD-001."
                        ),
                    }

                # All attempts exhausted — graceful failure (non-fatal with strict_downloads=false).
                return {
                    "status": "error",
                    "doc": doc_num,
                    "phase": "atala_pdf_conversion",
                    "error": (
                        "Santa Rosa AcclaimWeb Atala WebDocumentViewer: PDF did not "
                        "materialise. WebAtalaCache="
                        + (atala_cache_path or "not found in page source")
                        + ". Engineering ticket SR-DOWNLOAD-001: the Atala conversion "
                        "may require the full three-step search → grid-click → detail "
                        "page navigation to trigger. Proceeding without this document "
                        "image (strict_downloads=false)."
                    ),
                }
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
        finally:
            _shutil.rmtree(download_dir, ignore_errors=True)
