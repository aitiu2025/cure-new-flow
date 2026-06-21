"""Volusia County (FL) HTTP-First Recorder Adapter — app02.clerk.org/or_m/.

Platform: PROPRIETARY in-house ASP.NET WebForms app ("or_m" = Official Records
mobile/modern UI) run by the Volusia Clerk (Laura E. Roth). NOT Landmark, NOT
AcclaimWeb, NOT Tyler — closest sibling in this repo is the bare-WebForms
shape (VIEWSTATE/doPostBack) that no other FL county currently uses.

Probe provenance (2026-06-10, GUILD case)
-----------------------------------------
clerk.org **geo-blocks non-US egress IPs at the TCP layer** (connection
refused in ~300ms from a 49.x Jio IP while vcpa.vcgov.org + county-taxes.net
connect fine). The live form could therefore NOT be probed directly this
session. Request/response shapes below come from the Internet Archive
snapshot of https://app02.clerk.org/or_m/inquiry.aspx (2026-01-13 capture,
saved at tests/fixtures/volusia/or_m_inquiry_wayback_20260113.html) which
includes BOTH the populated search form AND a live results grid.

Form contract (from the snapshot)
---------------------------------
* ``GET  /or_m/inquiry.aspx``  → harvest ``__VIEWSTATE``,
  ``__VIEWSTATEGENERATOR``, ``__EVENTVALIDATION`` hidden fields.
* ``POST /or_m/inquiry.aspx`` (same URL, classic WebForms postback) with
  ``__EVENTTARGET=ctl00$ContentPlaceHolder1$search`` and form fields:
    - ``ctl00$ContentPlaceHolder1$name``         — "LAST FIRST" (no comma)
    - ``ctl00$ContentPlaceHolder1$nameType``     — BOTH | DIRECT | REVERSE
    - ``ctl00$ContentPlaceHolder1$doctype``      — RIGHT-PADDED 20-char value
      (e.g. ``"DEED                "``) or empty for all types
    - ``ctl00$ContentPlaceHolder1$fromDateTxt`` / ``toDateTxt`` — MM/DD/YYYY
    - ``ctl00$ContentPlaceHolder1$instrument`` / ``book`` / ``tb_page`` /
      ``caseNum`` / ``parcel`` — alternate search keys
    - ``ctl00$ContentPlaceHolder1$Grid$ctl01$MaxRows`` — 25|50|100|200|500
* Results grid: one ``<tr>`` per PARTY (not per document) with cells
  [View, Instrument, Date, Book/Page, DocType(abbrev w/ popover full name),
  Name, Legal, Status, Direction(D|R)]. D = direct/grantor, R = reverse/
  grantee. Rows for the same instrument must be merged.
* Direct retrieval by instrument:
  ``GET /or_m/Default.aspx?s=orapr&i={instrument}`` — the VCPA sale-history
  rows link to exactly this URL, satisfying Broward-Standard item #4.
* NO reCAPTCHA anywhere.

Wave-2 LIVE VALIDATION (2026-06-10, US egress 149.22.88.175)
------------------------------------------------------------
All snapshot-derived shapes confirmed live, with these corrections/additions:

1. **Disclaimer/session gate DOES exist** (the Wayback capture was taken
   mid-session): a cold POST to inquiry.aspx returns a 700-byte "Your session
   has expired" page. Flow: ``GET Default.aspx?s=orapr`` → ``POST`` same URL
   with hidden fields + ``ctl00$ContentPlaceHolder1$accept=Accept`` → the
   ASP.NET_SessionId cookie is marked accepted; inquiry.aspx postbacks work.
2. **Name search is prefix-based**: "GUILD MARYKE" matches both
   "GUILD MARYKE" and "GUILD MARYKE Y" index entries.
3. **Name-search grids list only the matching party's row(s)** per
   instrument (Direction D|R says which side); the opposing party requires
   the image pull. (The Wayback grid showed both sides because it was a
   range search.)
4. **PDF download** (resolved live): the grid's PDF icon calls
   ``viewDoc('<hexid>', 'r', '<pages>', 'p')``. Recipe:
     a. ``GET viewImage.aspx?ID={hexid}&t=r&f=p&n={pages}&s=1&e={pages}``
        → "Processing..." page with an ASP.NET AJAX Timer;
     b. poll: async postback ``__EVENTTARGET=UpdateTimer`` with
        ``ScriptManager1=tTimedPanel|UpdateTimer`` + ``__ASYNCPOST=true`` +
        header ``X-MicrosoftAjax: Delta=true`` every ~4s;
     c. ready delta contains ``pageRedirect||%2for_m%2fload_Redact.aspx``;
     d. ``GET load_Redact.aspx`` → ``application/pdf`` (FL §119.0714 redacted).
5. **MaxRows select** (``...$Grid$ctl01$MaxRows``: 25/50/100/200/500) only
   exists on pages WITH a grid; first search returns max 25 rows. To expand,
   postback ``__EVENTTARGET=...$Grid$ctl01$MaxRows`` with value 500 using
   the RESULT page's hidden fields.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


DEFAULT_IMPERSONATE = "chrome120"

_P = "ctl00$ContentPlaceHolder1"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
}


class VolusiaOrMAdapter(BaseRecorderSearch):
    """HTTP-only adapter for Volusia's or_m WebForms portal."""

    def __init__(
        self,
        config: Dict[str, Any],
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self._config = config or {}
        self._base = (
            self._config.get("base_url") or "https://app02.clerk.org/or_m/"
        )
        if not self._base.endswith("/"):
            self._base += "/"
        self._inquiry_url = urljoin(self._base, "inquiry.aspx")
        self._direct_tmpl = self._config.get(
            "direct_instrument_url_template",
            urljoin(self._base, "Default.aspx?s=orapr&i={instrument}"),
        )
        self._impersonate = self._config.get(
            "impersonate_profile", DEFAULT_IMPERSONATE
        )
        self._max_rows = str(self._config.get("record_cap", "500"))
        self._doc_type_map = self._config.get("doc_type_map", {})
        self._entry_url = urljoin(self._base, "Default.aspx?s=orapr")
        self._view_image_url = urljoin(self._base, "viewImage.aspx")
        self._load_redact_url = urljoin(self._base, "load_Redact.aspx")
        self._session: Optional[Any] = None
        self._accepted = False
        self._hidden_fields: Dict[str, str] = {}
        self._last_html: str = ""
        # Rich per-row capture (book/page, legal, viewDoc args) — the
        # DocumentRecord dataclass is narrower than the grid; the exam
        # pipeline reads this side-channel for artifacts.
        self.last_rows: List[Dict[str, str]] = []

    # ----------------------------------------------------------- plumbing

    @property
    def county_name(self) -> str:
        return self._config.get("county_name", "Volusia")

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def session(self):
        if self._session is None:
            s = _cffi_requests.Session(impersonate=self._impersonate)
            s.headers.update(EXTRA_HEADERS)
            self._session = s
        return self._session

    @session.setter
    def session(self, value):
        self._session = value
        self._accepted = False

    def setup_driver(self):
        """HTTP adapter — no browser. Kept for interface parity."""
        return None

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    # ----------------------------------------------------------- navigation

    @staticmethod
    def _is_session_expired(html: str) -> bool:
        return "Your session has expired" in (html or "")

    def _accept_disclaimer(self) -> None:
        """Mint an accepted session: GET entry page → POST Accept.

        Live-validated 2026-06-10: without this, every inquiry.aspx postback
        returns a 'Your session has expired' page."""
        resp = self.session.get(self._entry_url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"or_m entry GET returned HTTP {resp.status_code}"
            )
        payload = self._harvest_hidden_fields(resp.text)
        payload[f"{_P}$accept"] = "Accept"
        resp = self.session.post(
            self._entry_url,
            data=payload,
            headers={"Referer": self._entry_url},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"or_m disclaimer Accept POST returned HTTP {resp.status_code}"
            )
        self._accepted = True

    def navigate_to_search(self):
        """Accept the disclaimer (once per session), then GET the inquiry
        page and harvest WebForms hidden fields."""
        if not self._accepted:
            self._accept_disclaimer()
        resp = self.session.get(self._inquiry_url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"or_m inquiry.aspx GET returned HTTP {resp.status_code}"
            )
        if self._is_session_expired(resp.text):
            # Session lapsed server-side — re-accept once and retry.
            self._accept_disclaimer()
            resp = self.session.get(self._inquiry_url, timeout=30)
        self._hidden_fields = self._harvest_hidden_fields(resp.text)
        if "__VIEWSTATE" not in self._hidden_fields:
            raise RuntimeError(
                "or_m inquiry.aspx did not contain __VIEWSTATE — page shape "
                "changed or request was challenged"
            )
        return resp.text

    def return_to_search(self):
        """WebForms VIEWSTATE is single-use per postback — force a fresh GET
        before every search (state-contamination guard; see the
        [N, 0, 0, 0, 0, 0] diagnostic signature in CLAUDE.md)."""
        return self.navigate_to_search()

    @staticmethod
    def _harvest_hidden_fields(html: str) -> Dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        out: Dict[str, str] = {}
        for inp in soup.find_all("input", attrs={"type": "hidden"}):
            name = inp.get("name")
            if name:
                out[name] = inp.get("value") or ""
        return out

    # ----------------------------------------------------------- search

    def _pad_doctype(self, doc_type: str) -> str:
        """or_m option values are right-padded to 20 chars."""
        if not doc_type:
            return ""
        mapped = self._doc_type_map.get(doc_type.upper(), doc_type.upper())
        return mapped.ljust(20)[:20] if len(mapped) < 20 else mapped

    @staticmethod
    def _normalize_name(name: str) -> str:
        """``"GUILD, MARYKE Y"`` → ``"GUILD MARYKE Y"`` (no-comma form)."""
        return re.sub(r"\s+", " ", (name or "").replace(",", " ")).strip().upper()

    def _party_type_value(self, party_type: str) -> str:
        m = self._config.get("party_type_map", {})
        return m.get(party_type, m.get("Both", "BOTH"))

    def build_search_payload(
        self,
        name: str,
        party_type: str = "Grantor/Grantee",
        doc_type: str = "",
    ) -> Dict[str, str]:
        """Assemble the full WebForms postback body for a name search."""
        payload = dict(self._hidden_fields)
        payload.update(
            {
                "__EVENTTARGET": f"{_P}$search",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                f"{_P}$name": self._normalize_name(name),
                f"{_P}$book": "",
                f"{_P}$tb_page": "",
                f"{_P}$instrument": "",
                f"{_P}$fromDateTxt": self.start_date,
                f"{_P}$toDateTxt": self.end_date or "",
                f"{_P}$doctype": self._pad_doctype(doc_type),
                f"{_P}$caseNum": "",
                f"{_P}$parcel": "",
                f"{_P}$nameType": self._party_type_value(party_type),
                f"{_P}$Grid$ctl01$MaxRows": self._max_rows,
            }
        )
        return payload

    def perform_search(
        self, name: str, party_type: str = "Grantor/Grantee", doc_type: str = ""
    ) -> List[DocumentRecord]:
        # Fresh VIEWSTATE per search — never reuse postback state.
        self.navigate_to_search()
        payload = self.build_search_payload(name, party_type, doc_type)
        resp = self.session.post(
            self._inquiry_url,
            data=payload,
            headers={"Referer": self._inquiry_url},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"or_m search POST returned HTTP {resp.status_code} for {name!r}"
            )
        if self._is_session_expired(resp.text):
            # Session lapsed mid-flow — re-accept + retry ONCE.
            self._accepted = False
            self.navigate_to_search()
            payload = self.build_search_payload(name, party_type, doc_type)
            resp = self.session.post(
                self._inquiry_url,
                data=payload,
                headers={"Referer": self._inquiry_url},
                timeout=30,
            )
        html = resp.text
        # Default grid page size is 25. If a pager is present, expand to the
        # configured cap via the MaxRows postback (uses the RESULT page's
        # hidden fields — live-validated shape).
        if self._grid_has_pager(html):
            html = self._expand_max_rows(html) or html
        self._last_html = html
        return self.extract_results(html)

    @staticmethod
    def _grid_has_pager(html: str) -> bool:
        return bool(re.search(r"Viewing\s*\d+\s*To\s*\d+", html or "", re.I))

    def _expand_max_rows(self, html: str) -> Optional[str]:
        """Re-postback with MaxRows={record_cap} so one page carries all rows."""
        fields = self._harvest_hidden_fields(html)
        if "__VIEWSTATE" not in fields:
            return None
        payload = dict(fields)
        payload.update(
            {
                "__EVENTTARGET": f"{_P}$Grid$ctl01$MaxRows",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                f"{_P}$Grid$ctl01$MaxRows": self._max_rows,
            }
        )
        resp = self.session.post(
            self._inquiry_url,
            data=payload,
            headers={"Referer": self._inquiry_url},
            timeout=30,
        )
        if resp.status_code != 200 or self._is_session_expired(resp.text):
            return None
        return resp.text

    # ----------------------------------------------------------- parse

    def extract_results(self, html: Optional[str] = None) -> List[DocumentRecord]:
        """Parse the results grid. One ``<tr>`` per PARTY; merge rows sharing
        an instrument number into a single DocumentRecord with D-rows as
        grantors and R-rows as grantees."""
        html = html if html is not None else self._last_html
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        grid = soup.find(id=re.compile(r"Grid", re.I))
        if grid is None:
            return []

        merged: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        self.last_rows = []
        for tr in grid.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 9:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            instrument = cells[1].strip()
            if not re.match(r"^\d{6,}$", instrument):
                continue  # header / pager / malformed rows
            date = cells[2].strip()
            book_page = cells[3].strip()
            # The doctype cell shows an abbreviation; the full name rides in
            # the popover's data-content attribute.
            dt_link = tds[4].find(attrs={"data-content": True})
            doc_type = (
                dt_link["data-content"].strip()
                if dt_link is not None
                else cells[4].strip()
            )
            party = cells[5].strip()
            legal = cells[6].strip()
            direction = cells[8].strip().upper()

            # viewDoc args from the PDF-icon cell (image-download key).
            view_a = tds[0].find("a", id="selectVB") or tds[0].find("a")
            vd = re.search(
                r"viewDoc\('([0-9a-f]+)','(\w)','(\d+)','(\w)'",
                (view_a.get("onclick") or "") if view_a else "",
            )
            self.last_rows.append(
                {
                    "instrument": instrument,
                    "date": date,
                    "book_page": book_page,
                    "doc_type": doc_type,
                    "party": party,
                    "legal": legal,
                    "status": cells[7].strip(),
                    "direction": direction,
                    "viewdoc_hexid": vd.group(1) if vd else "",
                    "viewdoc_pages": vd.group(3) if vd else "",
                }
            )

            if instrument not in merged:
                merged[instrument] = {
                    "date": date,
                    "book_page": book_page,
                    "doc_type": doc_type,
                    "legal": legal,
                    "grantors": [],
                    "grantees": [],
                }
                order.append(instrument)
            bucket = merged[instrument]
            if direction.startswith("D"):
                if party and party not in bucket["grantors"]:
                    bucket["grantors"].append(party)
            elif direction.startswith("R"):
                if party and party not in bucket["grantees"]:
                    bucket["grantees"].append(party)
            elif party:
                # Unknown direction — keep the party rather than dropping it
                # (Tony directive #5: never silently drop indexed data).
                if party not in bucket["grantors"]:
                    bucket["grantors"].append(party)

        records: List[DocumentRecord] = []
        for inst in order:
            b = merged[inst]
            grantors = "; ".join(b["grantors"])
            grantees = "; ".join(b["grantees"])
            records.append(
                DocumentRecord(
                    document_number=inst,
                    grantors=grantors,
                    grantees=grantees,
                    grantor_grantees=" | ".join(
                        x for x in (grantors, grantees) if x
                    ),
                    document_type=b["doc_type"],
                    recording_date=b["date"],
                    pages="",
                )
            )
        return records

    # ----------------------------------------------------------- retrieval

    def direct_instrument_url(self, instrument: str) -> str:
        """Direct-retrieval endpoint (Broward-Standard item #4). Pattern
        confirmed by the VCPA sale-history hyperlinks:
        ``https://app02.clerk.org/or_m/Default.aspx?s=orapr&i={instrument}``."""
        return self._direct_tmpl.format(instrument=str(instrument).strip())

    def pull_detail(self, doc_num: str) -> Dict[str, Any]:
        url = self.direct_instrument_url(doc_num)
        resp = self.session.get(url, timeout=30)
        return {
            "document_number": doc_num,
            "url": url,
            "status_code": resp.status_code,
            "html": resp.text if resp.status_code == 200 else "",
        }

    # ----------------------------------------------------------- PDF download

    def download_pdf(
        self,
        hexid: str,
        pages: str,
        dest_path: Any,
        *,
        poll_attempts: int = 15,
        poll_interval: float = 4.0,
    ) -> Dict[str, Any]:
        """Download the redacted document PDF (live-validated 2026-06-10).

        ``hexid``/``pages`` come from the grid row's
        ``viewDoc('<hexid>','r','<pages>','p')`` onclick (see
        ``last_rows[i]['viewdoc_hexid'/'viewdoc_pages']``).

        Recipe: GET viewImage.aspx → poll UpdateTimer async postbacks until
        the MicrosoftAjax delta carries ``pageRedirect||...load_Redact.aspx``
        → GET load_Redact.aspx → %PDF bytes.
        """
        import time as _time
        from pathlib import Path as _Path

        dest_path = _Path(dest_path)
        if not self._accepted:
            self._accept_disclaimer()

        n = str(pages or "1")
        url = (
            f"{self._view_image_url}?ID={hexid}&t=r&f=p&n={n}&s=1&e={n}"
        )
        resp = self.session.get(
            url, timeout=30, headers={"Referer": self._inquiry_url}
        )
        if resp.status_code != 200:
            return {"ok": False, "error": f"viewImage GET HTTP {resp.status_code}", "url": url}

        fields = self._harvest_hidden_fields(resp.text)
        viewstate = fields.get("__VIEWSTATE", "")
        vsgen = fields.get("__VIEWSTATEGENERATOR", "")
        ready = False
        for _ in range(poll_attempts):
            _time.sleep(poll_interval)
            poll = self.session.post(
                url,
                data={
                    "ScriptManager1": "tTimedPanel|UpdateTimer",
                    "__EVENTTARGET": "UpdateTimer",
                    "__EVENTARGUMENT": "",
                    "__VIEWSTATE": viewstate,
                    "__VIEWSTATEGENERATOR": vsgen,
                    "__ASYNCPOST": "true",
                },
                headers={
                    "Referer": url,
                    "X-MicrosoftAjax": "Delta=true",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=30,
            )
            body = poll.text
            if "pageRedirect" in body:
                ready = True
                break
            mv = re.search(r"\|hiddenField\|__VIEWSTATE\|([^|]*)\|", body)
            if mv:
                viewstate = mv.group(1)
        if not ready:
            return {"ok": False, "error": "render poll timed out", "url": url}

        pdf = self.session.get(
            self._load_redact_url, timeout=30, headers={"Referer": url}
        )
        if pdf.status_code != 200 or pdf.content[:4] != b"%PDF":
            return {
                "ok": False,
                "error": f"load_Redact HTTP {pdf.status_code}, magic {pdf.content[:8]!r}",
                "url": self._load_redact_url,
            }
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(pdf.content)
        return {
            "ok": True,
            "path": str(dest_path),
            "bytes": len(pdf.content),
            "source_url": url,
        }
