"""
Pasco County (FL) HTTP Recorder Adapter — Phase 1 CURE (Wave-1 scaffold).

Pure-Python HTTP adapter for the Pasco Clerk & Comptroller Official Records
search at ``app.pascoclerk.com`` — an in-house classic-ASP application on bare
Microsoft-IIS/10.0 (probed 2026-06-10; see the Pasco_RILEY_v1 case folder's
``phase0_probe_recorder.md``). No Cloudflare, no disclaimer gate, no CSRF
token, no CAPTCHA markup on the search page.

Endpoints (request shapes verified verbatim from the served form HTML; the
RESPONSE/result-row HTML shape is NOT yet live-verified — live POSTs carrying
party names require user approval per the No Assumptions Policy, so
``extract_results`` is a defensive table parser locked by a synthetic fixture
in ``tests/unit/test_pasco_http_adapter_scaffold.py``. Diff against the first
approved live response in Wave 2.):

  GET  https://app.pascoclerk.com/appdot-public-online-services-forms-or-search.asp
       (landing/search page — no cookies issued, used only as a warm-up ping)

  POST https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-name-search.asp
       form: name=<LAST FIRST, max 30>, fromdate=YYYY-MM-DD, todate=YYYY-MM-DD,
             docset=<verbatim docset label, default ALL>,
             namedir=<A|D|R>  (A=ALL, D=GRANTOR/PARTY 1, R=GRANTEE/PARTY 2),
             Submit=Search by Name

  POST https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-instrument-list.asp
       form: instrStart=<instrument #, max 10>, Submit=Search by Instrument

  POST https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-bookpage-list.asp
       form: book=<max 5>, page=<max 4>, Submit=Search by Book/Page

Design mirrors ``hillsborough_http_adapter.py`` (the other bare-IIS FL county):
  * Subclasses ``BaseRecorderSearch`` so registry/factory plumbing is unchanged.
  * Driver/browser methods collapse to no-ops (Tony directive #1 — no Selenium,
    no Playwright anywhere in this module).
  * Stateless: every ``perform_search`` builds a fresh form payload.

Per Tony's deed-first directive (#2), callers should invoke ``perform_search``
with ``doc_type="DEED"`` first (mapped to docset ``DEED / PROPERTY TRANSFER``)
to find the vesting deed → NLP-extract the APN → re-search for completeness.
Per directive #3, the RILEY case must run BOTH individual names AND the
trust/trustee variants.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# Pasco is bare IIS (no anti-bot observed on GET), but we default to the
# safari17_2_ios profile defensively — it is the only profile proven to pass
# every FL Cloudflare county, and it costs nothing on an unprotected host.
DEFAULT_IMPERSONATE = "safari17_2_ios"

DEFAULT_BASE = "https://app.pascoclerk.com/"
DEFAULT_LANDING = (
    "https://app.pascoclerk.com/appdot-public-online-services-forms-or-search.asp"
)
DEFAULT_NAME_SEARCH = (
    "https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-name-search.asp"
)
DEFAULT_INSTRUMENT_SEARCH = (
    "https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-instrument-list.asp"
)
DEFAULT_BOOKPAGE_SEARCH = (
    "https://app.pascoclerk.com/appdot-public-sup-svcs-results-or-bookpage-list.asp"
)

# Verbatim docset labels served by the portal (value == display text).
PASCO_DOCSET_ALL = "ALL"
PASCO_DOCSET_DEED = "DEED / PROPERTY TRANSFER"

# Pasco emits NON-zero-padded dates ("11/5/2012") — live-verified 2026-06-10.
_DATE_TOKEN_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$|^\d{4}-\d{2}-\d{2}$")

# Live-verified results-table header (2026-06-10, RILEY deed-first search):
#   Name | Cross-Party Name | <btn> | Instrument | Date | Time | Book | Page
#   | Document | Legal | <blank>
# The Instrument cell links to the GET detail endpoint below. Mirrored rows
# (same instrument listed under each indexed name) are deduped by instrument.
_HEADER_ALIASES = {
    "NAME": "name",
    "CROSS-PARTY NAME": "cross_party",
    "CROSS PARTY NAME": "cross_party",
    "INSTRUMENT": "instrument",
    "DATE": "date",
    "TIME": "time",
    "BOOK": "book",
    "PAGE": "page",
    "DOCUMENT": "document",
    "LEGAL": "legal",
}

DEFAULT_DETAIL_URL_TEMPLATE = (
    "https://app.pascoclerk.com/"
    "appdot-public-sup-svcs-results-or-instr-detail.asp?mdqs=1&tbqs={instrument}"
)
# Image flow (live-verified 2026-06-10): the detail page links to a
# "View Document" form gated by a Lanap BotDetect text captcha (6 chars):
#   GET  form-or-image-validate.asp?instrument={n}&pageCt={p}   (form page)
#   GET  includes/LanapBotDetect.asp?Command=CreateImage&...     (captcha img,
#        session-cookie bound)
#   POST results-or-image-validate.asp?instrument={n}&pageCt={p}
#        form: imagecode=<solved code>, Submit=Open Image        (→ PDF)
DEFAULT_IMAGE_FORM_TEMPLATE = (
    "https://app.pascoclerk.com/"
    "appdot-public-sup-svcs-form-or-image-validate.asp?instrument={instrument}&pageCt={page_ct}"
)
DEFAULT_IMAGE_POST_TEMPLATE = (
    "https://app.pascoclerk.com/"
    "appdot-public-sup-svcs-results-or-image-validate.asp?instrument={instrument}&pageCt={page_ct}"
)
DEFAULT_CAPTCHA_IMAGE_URL = (
    "https://app.pascoclerk.com/includes/LanapBotDetect.asp"
    "?Command=CreateImage&TextStyle=4&ImageWidth=250&imageHeight=50"
    "&CodeLength=6&CodeType=0"
)


class PascoHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP recorder adapter for Pasco County, FL (classic-ASP portal)."""

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        config: Dict[str, Any],
        start_date: str = "01/01/1990",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Pasco")
        self._base_url = config.get("base_url", DEFAULT_BASE).rstrip("/") + "/"
        self._search_url = config.get("search_url", DEFAULT_LANDING)
        ep = config.get("pasco_endpoints", {})
        self._landing_url = ep.get("landing", self._search_url)
        self._name_search_url = ep.get("name_search", DEFAULT_NAME_SEARCH)
        self._instrument_search_url = ep.get(
            "instrument_search", DEFAULT_INSTRUMENT_SEARCH
        )
        self._bookpage_search_url = ep.get("bookpage_search", DEFAULT_BOOKPAGE_SEARCH)

        # Semantic doc-type → verbatim Pasco docset label.
        self.doc_type_map = config.get(
            "doc_type_map",
            {
                "ALL": PASCO_DOCSET_ALL,
                "DEED": PASCO_DOCSET_DEED,
                "MORTGAGE": "MORTGAGE",
                "MTG": "MORTGAGE",
                "SATISFACTION": "SATISFACTION",
                "SAT": "SATISFACTION",
                "RELEASE": "RELEASE",
                "PARTIAL RELEASE": "PARTIAL RELEASE",
                "ASSIGNMENT": "ASSIGNMENT",
                "MODIFICATION": "MODIFICATION",
                "JUDGMENT": "JUDGMENT",
                "LIEN": "LIEN",
                "LIS PENDENS": "LIS PENDENS",
                "NOTICE OF COMMENCEMENT": "NOTICE OF COMMENCEMENT",
                "NOC": "NOTICE OF COMMENCEMENT",
                "FINANCING STATEMENT": "FINANCING STATEMENT",
                "UCC": "FINANCING STATEMENT",
                "AFFIDAVIT": "AFFIDAVIT",
                "AGREEMENT": "AGREEMENT",
                "TERMINATION": "TERMINATION",
            },
        )

        # Party direction: portal select `namedir` — A=ALL, D=GRANTOR, R=GRANTEE.
        self.party_type_map = config.get(
            "party_type_map",
            {
                "All": "A",
                "Both": "A",
                "Grantor/Grantee": "A",
                "Grantor": "D",
                "Grantee": "R",
                "Party 1": "D",
                "Party 2": "R",
            },
        )
        self.supported_party_types = config.get(
            "supported_party_types",
            ["All", "Both", "Grantor", "Grantee", "Grantor/Grantee"],
        )

        # Pasco instrument numbers: portal example "2001123456" (YYYY + serial,
        # 10 digits); legacy instruments may be shorter — accept 8-12.
        self._doc_number_re = re.compile(
            config.get("doc_number_pattern", r"^\d{8,12}$")
        )

        self._name_maxlength = int(config.get("name_maxlength", 30))

        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(
            {
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": config.get("http_referer", self._landing_url),
            }
        )

        # Result rows are expected to carry an <a href> per instrument (image /
        # detail link). We cache whatever href the row exposes so the download
        # phase can try it. UNVERIFIED until the first approved live search —
        # see module docstring.
        self._detail_href_by_number: Dict[str, str] = {}
        # Pipeline-sidecar-compatible alias (recorder_internal_ids.json).
        self._doc_id_by_number: Dict[str, str] = self._detail_href_by_number
        # OR book/page captured from the results table, keyed by instrument.
        self._book_page_by_number: Dict[str, str] = {}
        # Page-count captured from the detail page, keyed by instrument (used
        # by the captcha-gated image download to fill pageCt).
        self._page_count_by_number: Dict[str, str] = {}
        # 2Captcha key for the Lanap BotDetect image gate on document viewing.
        self._captcha_api_key: Optional[str] = config.get("captcha_api_key")

        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # ABC compliance: parent expects self.driver — we never use it.
        self.driver = None

    # --------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # --------------------------------------- ABC no-ops (browser-only contract)

    def setup_driver(self):
        """No-op — HTTP adapter has no browser driver."""
        return None

    def navigate_to_search(self):
        """No-op — every perform_search is stateless."""
        return None

    def return_to_search(self):
        """No-op — HTTP path is stateless between calls."""
        return None

    # ------------------------------------------------------ session warm-up

    def warm_session(self, *_args, **_kwargs) -> bool:
        """GET the landing page once to confirm connectivity.

        Pasco issues no cookies and has no disclaimer — this is purely a
        reachability check (and politeness: mirrors a human page-load before
        the form POST).
        """
        if self._session_warmed:
            return True
        try:
            resp = self.session.get(self._landing_url, timeout=30)
            if resp.status_code != 200:
                self.last_failure = f"landing_http_{resp.status_code}"
                return False
            self._session_warmed = True
            return True
        except Exception as exc:
            self.last_failure = f"landing_error: {exc}"
            return False

    # ----------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "All",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search (form POST → HTML results page).

        Name convention: ``"RILEY ROBERT S"`` (LAST FIRST MIDDLE, no comma,
        max 30 chars). A ``"LAST, FIRST"`` input is normalized transparently.
        Trust names go through verbatim (uppercased) — e.g. ``"RILEY TRUST"``.
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] session warm-up failed; "
                    f"last_failure={self.last_failure}"
                )
                return []

        payload = self.build_name_search_payload(
            name, party_type=party_type, doc_type=doc_type,
            date_from=date_from, date_to=date_to,
        )

        try:
            resp = self.session.post(
                self._name_search_url,
                data=payload,
                timeout=60,
            )
        except Exception as exc:
            print(f"  [perform_search] HTTP error: {exc}")
            self.last_failure = f"http_error: {exc}"
            return []

        if resp.status_code != 200:
            print(f"  [perform_search] HTTP {resp.status_code} from name-search")
            self.last_failure = f"http_{resp.status_code}"
            return []

        return self.extract_results(resp.text)

    def build_name_search_payload(
        self,
        name: str,
        party_type: str = "All",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build the verbatim form payload for the Pasco name-search POST.

        Exposed as a public helper so tests (and the Wave-2 live runner) can
        assert the exact wire shape without monkeypatching internals.
        """
        normalized = self._normalize_name(name)[: self._name_maxlength]

        namedir = self.party_type_map.get(party_type, "A")
        if namedir not in {"A", "D", "R"}:
            namedir = "A"

        docset = PASCO_DOCSET_ALL
        if doc_type:
            dt_key = doc_type.strip().upper()
            docset = self.doc_type_map.get(dt_key, doc_type.strip().upper())

        return {
            "name": normalized,
            "fromdate": self._to_iso_date(date_from or self.start_date),
            "todate": self._to_iso_date(date_to or self.end_date),
            "docset": docset,
            "namedir": namedir,
            "Submit": "Search by Name",
        }

    # ----------------------------------------------------------- extract_results

    def extract_results(self, payload: Any = None) -> List[DocumentRecord]:
        """Parse a Pasco results page (HTML) into DocumentRecord rows.

        HEADER-AWARE PARSER (live-verified 2026-06-10). The Pasco results
        table carries a header row whose labels map columns:
          Name | Cross-Party Name | <btn> | Instrument | Date | Time | Book
          | Page | Document | Legal | <blank>
        The portal lists each instrument once per indexed name (so a single
        recording appears as multiple mirrored rows with Name/Cross-Party
        swapped). We dedupe by instrument, keeping the FIRST occurrence —
        which, for a grantor-direction listing, carries the searched party in
        the Name column and the counterparty in Cross-Party Name.

        Falls back to a positional heuristic when no recognizable header is
        present (back-compat with the synthetic fixture).
        """
        if payload is None:
            return []
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        if not isinstance(payload, str) or not payload.strip():
            return []

        soup = BeautifulSoup(payload, "lxml")
        documents: List[DocumentRecord] = []
        seen: set = set()
        known_docsets = {v.upper() for v in self.doc_type_map.values()}
        known_docsets.add(PASCO_DOCSET_ALL)

        # Locate the results table by its header signature.
        col_index: Dict[str, int] = {}
        for table in soup.find_all("table"):
            header = table.find("tr")
            if header is None:
                continue
            ths = header.find_all(["th", "td"])
            labels = [th.get_text(" ", strip=True).upper() for th in ths]
            mapping = {
                _HEADER_ALIASES[lab]: idx
                for idx, lab in enumerate(labels)
                if lab in _HEADER_ALIASES
            }
            if "instrument" in mapping and ("name" in mapping or "document" in mapping):
                col_index = mapping
                rows = table.find_all("tr")[1:]
                self._parse_header_rows(rows, col_index, documents, seen)
                if documents:
                    return documents

        # --- positional fallback (synthetic fixture / unknown layout) -------
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]

            doc_num = ""
            doc_num_idx = -1
            for i, t in enumerate(texts):
                compact = t.replace(" ", "")
                if self._doc_number_re.match(compact):
                    doc_num = compact
                    doc_num_idx = i
                    break
            if not doc_num or doc_num in seen:
                continue
            seen.add(doc_num)

            rec_date = ""
            doc_type = ""
            book = ""
            page = ""
            party_cells: List[str] = []
            for i, t in enumerate(texts):
                if i == doc_num_idx or not t:
                    continue
                if not rec_date and _DATE_TOKEN_RE.match(t):
                    rec_date = self._to_mmddyyyy(t)
                    continue
                upper = t.upper()
                if not doc_type and upper in known_docsets:
                    doc_type = upper
                    continue
                bp = re.match(r"^(\d{1,5})\s*/\s*(\d{1,4})$", t)
                if bp and not book:
                    book, page = bp.group(1), bp.group(2)
                    continue
                if re.search(r"[A-Za-z]{2,}", t):
                    party_cells.append(t)

            link = row.find("a", href=True)
            if link:
                self._detail_href_by_number[doc_num] = urljoin(
                    self._base_url, link["href"]
                )

            grantors = party_cells[0] if party_cells else ""
            grantees = party_cells[1] if len(party_cells) > 1 else ""
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
                    pages="",
                )
            )
        return documents

    def _parse_header_rows(
        self,
        rows: List[Any],
        col: Dict[str, int],
        documents: List[DocumentRecord],
        seen: set,
    ) -> None:
        """Populate ``documents`` from header-mapped Pasco result rows."""
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]

            def at(key: str) -> str:
                idx = col.get(key, -1)
                return texts[idx] if 0 <= idx < len(texts) else ""

            doc_num = re.sub(r"\s", "", at("instrument"))
            if not doc_num or not self._doc_number_re.match(doc_num):
                continue
            if doc_num in seen:
                continue
            seen.add(doc_num)

            name = at("name")
            cross = at("cross_party")
            rec_date = self._to_mmddyyyy(at("date"))
            doc_type = at("document").upper()
            book = at("book")
            page = at("page")
            book_page = f"{book} / {page}" if book and page else ""
            # Surface OR book/page for downstream cross-ref without colliding
            # with the page-COUNT semantics of DocumentRecord.pages.
            self._book_page_by_number[doc_num] = book_page

            # Cache the Instrument-cell detail href (the GET detail endpoint).
            inst_idx = col.get("instrument", -1)
            href = ""
            if 0 <= inst_idx < len(cells):
                a = cells[inst_idx].find("a", href=True)
                if a:
                    href = urljoin(self._base_url, a["href"])
            if not href:
                href = DEFAULT_DETAIL_URL_TEMPLATE.format(instrument=doc_num)
            self._detail_href_by_number[doc_num] = href

            documents.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=name,
                    grantees=cross,
                    grantor_grantees=(
                        f"{name}; {cross}" if name and cross else (name or cross)
                    ),
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages="",
                )
            )

    # ------------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str) -> Dict[str, Any]:
        """Direct retrieval by instrument number (Broward Standard item #4).

        GETs the instrument-detail page (live-verified 2026-06-10):
        ``appdot-public-sup-svcs-results-or-instr-detail.asp?mdqs=1&tbqs={n}``.
        The page carries Book/Page, recording date, page count, recording fee,
        the short legal, AND the full ``Indexed Names`` table with Party-1 /
        Party-2 roles — which is the canonical source for ALL parties on a
        document (the results grid only shows one Name/Cross-Party pair).
        """
        if not self._session_warmed:
            self.warm_session()

        compact = re.sub(r"\D", "", str(doc_num))
        if not compact:
            return {"document_number": doc_num, "error": "non-numeric instrument"}

        url = self._detail_href_by_number.get(compact) or (
            DEFAULT_DETAIL_URL_TEMPLATE.format(instrument=compact)
        )
        try:
            resp = self.session.get(url, timeout=45)
        except Exception as exc:
            return {"document_number": doc_num, "error": f"network: {exc}"}
        if resp.status_code != 200:
            return {"document_number": doc_num, "error": f"HTTP {resp.status_code}"}

        return self._parse_detail_page(compact, resp.text, url)

    def _parse_detail_page(
        self, doc_num: str, html: str, url: str
    ) -> Dict[str, Any]:
        """Parse a Pasco instrument-detail page into a structured dict."""
        soup = BeautifulSoup(html, "lxml")

        def field(label: str) -> str:
            node = soup.find(
                lambda t: t.name in ("td", "th", "b", "strong", "span", "label")
                and t.get_text(strip=True).rstrip(":").upper() == label.upper()
            )
            if node is None:
                return ""
            cell = node.find_next(["td"])
            if cell is not None:
                val = cell.get_text(" ", strip=True)
                if val and val.rstrip(":").upper() != label.upper():
                    return val
            return ""

        book = field("Book")
        page = field("Page")
        book_page = f"{book} / {page}" if book and page else ""
        page_ct = field("# Pages") or field("Pages")
        if page_ct:
            self._page_count_by_number[doc_num] = re.sub(r"\D", "", page_ct) or page_ct

        # Indexed Names table → parties with roles.
        parties: List[Dict[str, str]] = []
        for row in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) == 2 and re.match(r"^Party\s*\d", cells[1], re.I):
                parties.append({"role": cells[1], "name": cells[0]})

        # Document-viewing form href (carries pageCt).
        image_href = ""
        a = soup.find("a", href=re.compile(r"image-validate", re.I))
        if a:
            image_href = urljoin(self._base_url, a["href"])

        return {
            "document_number": doc_num,
            "recording_date": self._to_mmddyyyy(field("Date")),
            "doc_type": field("Document"),
            "indexed_apn": "",
            "book_page": book_page or self._book_page_by_number.get(doc_num, ""),
            "page_count": self._page_count_by_number.get(doc_num, ""),
            "recording_fee": field("Recording Fee"),
            "legal": field("Legal"),
            "parties": parties,
            "detail_href": url,
            "image_form_href": image_href,
        }

    # --------------------------------------------------------------- download

    def download_pdf(
        self,
        doc_num: str,
        dest_path: Path,
        captcha_solver: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Download a document image via the captcha-gated image flow.

        Live-verified flow (2026-06-10):
          1. GET the detail page → page count + image-form href.
          2. GET the image-validate FORM page (binds the BotDetect session).
          3. GET the Lanap BotDetect captcha image (6-char text, session-bound).
          4. Solve it (``captcha_solver`` callable, else 2Captcha normal-image
             API if ``captcha_api_key`` is configured).
          5. POST ``results-or-image-validate.asp`` with ``imagecode`` →
             the watermarked PDF (or a redirect/link to it).

        ``captcha_solver`` may be a callable ``(image_bytes) -> str`` (e.g. a
        local OCR). Returns the standard success/error dict. When no solver and
        no API key are available, returns a structured error naming the gate
        (NOT a silent skip — Tony directive #5).
        """
        compact = re.sub(r"\D", "", str(doc_num))
        if not self._session_warmed:
            if not self.warm_session():
                return {
                    "status": "error", "doc": doc_num,
                    "message": f"session warm-up failed: {self.last_failure}",
                }

        # 1) detail page → page count + image form href.
        detail = self.pull_detail(compact)
        if "error" in detail:
            return {"status": "error", "doc": doc_num, "message": detail["error"]}
        page_ct = self._page_count_by_number.get(compact, "1")
        image_form_url = detail.get("image_form_href") or (
            DEFAULT_IMAGE_FORM_TEMPLATE.format(instrument=compact, page_ct=page_ct)
        )
        image_post_url = DEFAULT_IMAGE_POST_TEMPLATE.format(
            instrument=compact, page_ct=page_ct
        )

        # 2) GET the form page to bind the BotDetect session cookie.
        try:
            self.session.get(image_form_url, timeout=30)
        except Exception as exc:
            return {"status": "error", "doc": doc_num,
                    "message": f"image-form GET failed: {exc}",
                    "pdf_url": image_post_url}

        # 3) GET the captcha image.
        try:
            cap = self.session.get(DEFAULT_CAPTCHA_IMAGE_URL, timeout=30)
            captcha_bytes = cap.content or b""
        except Exception as exc:
            return {"status": "error", "doc": doc_num,
                    "message": f"captcha image GET failed: {exc}"}

        # 4) Solve.
        code = self._solve_captcha(captcha_bytes, captcha_solver)
        if not code:
            return {
                "status": "error", "doc": doc_num,
                "message": (
                    "Pasco document viewing is gated by a Lanap BotDetect 6-char "
                    "text captcha (includes/LanapBotDetect.asp). No captcha solver "
                    "available: pass captcha_solver=(bytes)->str or set "
                    "captcha_api_key (2Captcha) in the county config. Index data "
                    "(parties, dates, book/page, doc type, legal) is fully captured "
                    "from the search + detail pages without the image."
                ),
                "captcha_required": True,
                "image_post_url": image_post_url,
            }

        # 5) POST the solved code → PDF.
        try:
            resp = self.session.post(
                image_post_url,
                data={"imagecode": code, "Submit": "Open Image"},
                timeout=120,
            )
        except Exception as exc:
            return {"status": "error", "doc": doc_num,
                    "message": f"image POST failed: {exc}",
                    "pdf_url": image_post_url}

        content = resp.content or b""
        # The POST may return the PDF directly OR an HTML page linking to it.
        # Live-verified 2026-06-11 — on captcha SUCCESS the chain is:
        #   POST → "Redirecting you to the document..." META REFRESH →
        #   results-or-image-validate3.asp?instrument={n}&sid={hash} →
        #   FRAMESET whose second frame src is the actual PDF at
        #   /i3/{client-ip-dashed}IP{instrument}.pdf
        # Follow up to 3 HTML hops (meta-refresh, frame/href/src links).
        last_link = image_post_url
        for _hop in range(3):
            if content[:4] == b"%PDF":
                break
            link = ""
            try:
                html_text = content.decode("utf-8", errors="replace")
                m = re.search(
                    r"http-equiv=['\"]refresh['\"][^>]*?"
                    r"url=([^'\">]+)['\"]",
                    html_text, re.I,
                )
                if not m:
                    m = re.search(
                        r"(?:href|src)=['\"]([^'\"]*\.(?:pdf|tif|tiff)"
                        r"[^'\"]*)['\"]",
                        html_text, re.I,
                    )
                if not m:
                    m = re.search(
                        r"(?:href|src)=['\"]([^'\"]*image-validate3"
                        r"[^'\"]*)['\"]",
                        html_text, re.I,
                    )
                if m:
                    link = urljoin(
                        self._base_url, m.group(1).replace("&amp;", "&")
                    )
            except Exception:
                pass
            if not link:
                break
            try:
                resp = self.session.get(link, timeout=120)
                content = resp.content or b""
                last_link = link
            except Exception as exc:
                return {"status": "error", "doc": doc_num,
                        "message": f"PDF link GET failed: {exc}",
                        "pdf_url": link}
        if content[:4] != b"%PDF":
            return {
                "status": "error", "doc": doc_num,
                "message": (
                    f"image POST did not yield a PDF ({len(content)} bytes, "
                    f"first 4: {content[:4]!r}); captcha code may have been "
                    "rejected — retry."
                ),
                "pdf_url": last_link,
            }

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)
        return {
            "status": "success", "doc": doc_num,
            "file": str(dest_path), "size": len(content),
            "src_via": "image_validate_captcha", "pdf_url": image_post_url,
        }

    def _solve_captcha(
        self, image_bytes: bytes, captcha_solver: Optional[Any]
    ) -> Optional[str]:
        """Solve the BotDetect image. Order: explicit solver → 2Captcha."""
        if not image_bytes:
            return None
        if callable(captcha_solver):
            try:
                out = captcha_solver(image_bytes)
                return (out or "").strip() or None
            except Exception:
                return None
        if self._captcha_api_key:
            try:
                return self._solve_via_2captcha(image_bytes)
            except Exception:
                return None
        return None

    def _solve_via_2captcha(self, image_bytes: bytes) -> Optional[str]:
        import base64
        import time as _t

        import requests as _rq

        b64 = base64.b64encode(image_bytes).decode()
        sub = _rq.post(
            "https://2captcha.com/in.php",
            data={"key": self._captcha_api_key, "method": "base64",
                  "body": b64, "json": 1},
            timeout=30,
        ).json()
        if sub.get("status") != 1:
            return None
        cid = sub["request"]
        for _ in range(20):
            _t.sleep(5)
            res = _rq.get(
                "https://2captcha.com/res.php",
                params={"key": self._captcha_api_key, "action": "get",
                        "id": cid, "json": 1},
                timeout=30,
            ).json()
            if res.get("status") == 1:
                return res["request"].strip()
            if res.get("request") != "CAPCHA_NOT_READY":
                return None
        return None

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Accept "LAST, FIRST" or "LAST FIRST"; emit "LAST FIRST" (uppercase)."""
        s = (name or "").strip()
        if not s:
            return ""
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            s = f"{parts[0]} {parts[1]}".strip()
        return re.sub(r"\s+", " ", s).upper()

    @staticmethod
    def _to_iso_date(d: Optional[str]) -> str:
        """Portal date inputs are HTML ``type=date`` → wire format YYYY-MM-DD.

        Accepts MM/DD/YYYY (pipeline convention) or YYYY-MM-DD (pass-through).
        """
        if not d:
            return ""
        d = d.strip()
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", d)
        if m:
            return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return d
        try:
            return datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")
        except Exception:
            return d

    @staticmethod
    def _to_mmddyyyy(d: str) -> str:
        """Normalize a scraped date token to pipeline MM/DD/YYYY."""
        d = (d or "").strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", d)
        if m:
            return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
        return d


__all__ = ["PascoHTTPAdapter"]
