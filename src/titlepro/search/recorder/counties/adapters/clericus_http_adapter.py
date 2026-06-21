"""MyFloridaCounty.com / Clericus Official Records HTTP Adapter (FL — 23 counties).

Pure-Python adapter for the **Clericus** (myfloridacounty.com) platform used by 23 FL
counties (De Soto, Franklin, Nassau, Sumter, and 19 others). The canonical URL pattern is:

    https://www.myfloridacounty.com/orisearch/<county_id>

where ``county_id`` is a 2-digit numeric code (e.g. 14 = De Soto, 19 = Franklin,
45 = Nassau, 60 = Sumter).

Platform Contract (reverse-engineered 2026-06-18, live-validated against Nassau/45)
------------------------------------------------------------------------------------
* **JSP server** (backend: ``x-powered-by: JSP/2.3``); session-based with JSESSIONID.
* **Landing page** (GET ``/orisearch/<county_id>``): Returns an HTML form with:
    - ``county`` hidden input (county numeric ID)
    - ``name`` text input (party name, supports ``*`` wildcards)
    - ``partyType`` radio: ``B`` (Both), ``T`` (From/Grantor), ``F`` (To/Grantee)
    - ``documentTypeID`` multi-select (0 = ALL, 10 = DEED, etc.)
    - ``instrumentTypeID`` multi-select (0 = ALL, plus per-county instrument codes)
    - ``startDate`` / ``endDate`` text (MM/DD/YYYY format)
    - ``instrumentNumber``, ``book``, ``page`` for direct retrieval
    - Form action: ``/orisearch/s/search;jsessionid=<JSESSIONID>?q1=<q1_token>``
    - ``q1`` is a STATIC site-wide token (``PUekI0zIOB3tlIGH1rpZaA``); it appears
      the same across all requests for the same county and serves as an opaque
      session correlation ID.
* **Cloudflare Turnstile** (interactive widget, sitekey ``0x4AAAAAAA64PTBePmuGbrkR``):
    Every search POST triggers a Turnstile challenge. After the user (or 2captcha)
    provides a valid ``cf-turnstile-response`` token, the server grants a JSESSIONID-
    bound search session. **Subsequent pagination GETs do NOT need a new token** —
    only the initial search POST does.
* **Search POST** to ``/orisearch/s/search?q1=<q1_token>`` returns an HTML page with:
    - ``<table id="ori_results">`` carrying rows:
        ``Party Name | Party Type | Date | Document Type | Instrument Number |
        Book/Page | Pages | Consideration Amount | Description``
      where the Description cell also contains a ``View Image`` link:
        ``<a href="/orisearch/s/image?q1=<q1>&q2=<q2_hash>">View Image</a>``
    - Pagination links: ``search?q1=<q1>&d-8001259-p=<page>``
      accessible via GET (no Turnstile required for page 2+).
    - Effective date shown in ``<div>Instruments verified through <date></div>``
      on the landing page (not repeated on results).
* **Document types**: The ``documentTypeID`` select uses numeric codes. The DEED
  standard doc type is **10**. Full list available at ``/orisearch/s/filterInstrument``.
* **Image / PDF download**: GET ``/orisearch/s/image?q1=<q1>&q2=<q2_hash>``
  returns ``application/pdf`` directly — no second redirect or login step.
* **Instrument detail**: NOT a separate endpoint in this JSP platform. All indexing
  data is in the search result row (party name, party type, date, doc type, instrument
  number, book/page, pages, consideration, short legal/description).
* **No Parcel-ID search** — name search only (Tony's guide v2 confirms this).

2Captcha Turnstile Integration
-------------------------------
The adapter uses 2captcha to solve Turnstile (``method=turnstile`` in the API).
It requires ``CAPTCHA_API_KEY`` in the environment (same key used by Tyler + Landmark
adapters). The JSON config can set ``captcha_api_key`` directly to override the env var.
Turnstile solving costs 0.002 USD per solve (per 2captcha pricing). The token is valid
for a single search POST; subsequent paginations within the same JSESSIONID session do
NOT re-trigger Turnstile and do NOT require another solve.

Deed-First Strategy
--------------------
Tony's directive #2: first search with ``documentTypeID=10`` (DEED) to find the vesting
deed. Then caller runs a second all-docs search for completeness. This adapter exposes
``doc_type="DEED"`` in ``perform_search`` which sets ``documentTypeID=["10"]``.

Result-Grouping Note
---------------------
Clericus lists each indexed party name as a separate row for the same instrument. For
example, a 4-party deed will appear 4 times. The adapter de-duplicates by instrument
number, keeping the FIRST occurrence as the primary record. All parties from duplicate
rows are collected into the DocumentRecord's ``grantors`` / ``grantees`` using F/T
party-type codes (F = From/Grantor, T = To/Grantee).

Live-Validated 2026-06-18
--------------------------
- Nassau (county_id=45): KELLY search — 25 rows page 1, pagination worked without
  Turnstile, PDF download via /orisearch/s/image confirmed (117 KB PDF).
- Turnstile sitekey ``0x4AAAAAAA64PTBePmuGbrkR`` is the same for all 4 counties.
- q1 token ``PUekI0zIOB3tlIGH1rpZaA`` is constant across sessions for Nassau.
  Other counties have different q1 tokens (De Soto: ``jViYcWwo_plUFA0aD1ETNA``).
  The q1 token is extracted from the landing page action URL at warm-up time.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE = "https://www.myfloridacounty.com"
DEFAULT_IMPERSONATE = "safari17_2_ios"
TURNSTILE_SITEKEY = "0x4AAAAAAA64PTBePmuGbrkR"

# Document type numeric IDs (Standard Document Type select options)
DOCTYPE_ALL = "0"
DOCTYPE_DEED = "10"
DOCTYPE_MORTGAGE = "21"
DOCTYPE_SATISFACTION = "33"
DOCTYPE_RELEASE = "31"
DOCTYPE_LIS_PENDENS = "17"
DOCTYPE_JUDGMENT = "15"
DOCTYPE_LIEN = "16"
DOCTYPE_NOC = "23"
DOCTYPE_UCC = "13"

# Party-type radio values — sent in the search POST ``partyType`` field.
# Confirmed live (Nassau/Sumter 2026-06-18): the server uses T for the
# "From" (Grantor/Direct) filter and F for the "To" (Grantee/Reverse) filter.
#
# NOTE: result-row Party Type column has the *opposite* F/T semantics:
#   result row F  → Grantor/From  (parse logic: party_type_code == "F" → grantors)
#   result row T  → Grantee/To    (parse logic: party_type_code == "T" → grantees)
# Do NOT conflate the radio-value constants below with the result-row parse logic.
PARTY_BOTH = "B"
PARTY_FROM = "T"     # Search radio: T = filter by From/Grantor party
PARTY_TO = "F"       # Search radio: F = filter by To/Grantee party

# Result-row party-type codes (used in _parse_results_page, NOT in _party_map).
# Distinct from the search radio values above.
_RESULT_ROW_GRANTOR_CODE = "F"   # result row Party Type == "F"  → Grantor (From)
_RESULT_ROW_GRANTEE_CODE = "T"   # result row Party Type == "T"  → Grantee (To)

# 2Captcha API
_2CAPTCHA_SUBMIT = "https://2captcha.com/in.php"
_2CAPTCHA_RESULT = "https://2captcha.com/res.php"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ClericusHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for myfloridacounty.com (Clericus platform).

    All 23 FL Clericus counties share the same host and differ only in their
    numeric ``county_id`` (e.g. 14 = De Soto, 19 = Franklin, 45 = Nassau,
    60 = Sumter). The config JSON must supply ``clericus_county_id``.
    """

    # ---------------------------------------------------------------- init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/1990",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config or {}

        self._county_name: str = self.config.get("county_name", "Unknown")
        self._county_id: str = str(self.config.get("clericus_county_id", ""))
        if not self._county_id:
            raise ValueError(
                f"ClericusHTTPAdapter: 'clericus_county_id' is required in config "
                f"(county {self._county_name})"
            )

        self._base: str = self.config.get("base_url", DEFAULT_BASE).rstrip("/")
        self._landing_url: str = f"{self._base}/orisearch/{self._county_id}"

        # Session-state: populated during warm_session()
        self._q1: Optional[str] = None          # Static session token from form action
        self._action_path: Optional[str] = None  # Full form action path (incl jsessionid)
        self._session_warmed: bool = False

        # Effective date from landing page
        self.verified_until_date: Optional[str] = None

        # 2Captcha key: config override → env var
        self._captcha_api_key: Optional[str] = (
            self.config.get("captcha_api_key")
            or os.environ.get("CAPTCHA_API_KEY")
        )
        self._captcha_timeout: int = int(self.config.get("captcha_timeout_seconds", 180))

        # Doc-type configuration
        self._doctype_deed: str = str(
            self.config.get("doctype_deed_value", DOCTYPE_DEED)
        )

        # Party-type map: canonical name → radio value
        self._party_map: Dict[str, str] = self.config.get(
            "party_type_map",
            {
                "All": PARTY_BOTH,
                "Both": PARTY_BOTH,
                "Grantor/Grantee": PARTY_BOTH,
                "Grantor": PARTY_FROM,
                "Grantee": PARTY_TO,
            },
        )

        # Search-window defaults
        self._default_start: str = self.config.get("default_start_date", "01/01/1990")
        self._default_end: str = self.config.get("default_end_date", "12/31/2099")

        # Page-size for results (server-side; we GET all pages)
        self._results_per_page: int = int(self.config.get("results_per_page", 25))

        # curl_cffi session
        impersonate = self.config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate)
        self.session.headers.update(EXTRA_HEADERS)

        # Q2 hash → instrument mapping (populated from search results for download)
        self._q2_by_instrument: Dict[str, str] = {}

        # Session state for cross-phase persistence (search → download).
        # These are set during warm_session/perform_search and can be restored
        # by the pipeline's _build_download_adapter via the
        # clericus_session_state.json sidecar file.
        self._session_cookies: Dict[str, str] = {}  # JSESSIONID + others
        self._session_state: Dict[str, str] = {}    # q1 + action_path

        self.last_failure: Optional[str] = None
        self.driver = None  # ABC compliance

    # ------------------------------------------ BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base

    # ------------------------------------------ ABC no-ops (browser contract)

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        # Stateless per-search; no browser reset needed.
        return None

    # ------------------------------------------ Session warm-up

    def warm_session(self) -> bool:
        """GET the landing page, extract q1 token + effective date.

        Must be called before perform_search. Re-entrant: calling twice is safe
        (only fetches once unless force=True is used).
        """
        try:
            r = self.session.get(self._landing_url, timeout=20)
        except Exception as exc:
            self.last_failure = f"landing GET failed: {exc}"
            return False

        if r.status_code != 200:
            self.last_failure = f"landing HTTP {r.status_code}"
            return False

        # Extract form action URL (carries jsessionid + q1)
        action_m = re.search(r'action="(/orisearch/s/search[^"]*)"', r.text)
        if not action_m:
            self.last_failure = "form action not found in landing page"
            return False
        self._action_path = action_m.group(1)

        # q1 from the action URL query string
        q1_m = re.search(r'\?q1=([A-Za-z0-9+/=_\-]+)', self._action_path)
        if q1_m:
            self._q1 = q1_m.group(1)
        else:
            # Fallback: q1 may appear elsewhere in the page
            q1_m2 = re.search(r'q1=([A-Za-z0-9+/=_\-]+)', r.text)
            self._q1 = q1_m2.group(1) if q1_m2 else None

        # Effective date (shown in the landing page body)
        eff_m = re.search(r'Instruments verified through\s+([0-9/]+)', r.text)
        self.verified_until_date = eff_m.group(1).strip() if eff_m else None

        self._session_warmed = True

        # Snapshot the session cookies and state for cross-phase persistence.
        # The pipeline can save these to clericus_session_state.json and restore
        # them in the download phase so the JSESSIONID remains valid.
        try:
            self._session_cookies = dict(self.session.cookies)
        except Exception:
            self._session_cookies = {}
        self._session_state = {
            "q1": self._q1 or "",
            "action_path": self._action_path or "",
        }

        return True

    # ------------------------------------------ Turnstile solving

    def _solve_turnstile(self, page_url: str) -> Optional[str]:
        """Solve Cloudflare Turnstile via 2captcha.

        Returns the ``cf-turnstile-response`` token or None if solving failed.
        Costs 0.002 USD per call.
        """
        if not self._captcha_api_key:
            self.last_failure = (
                "Turnstile solve required but CAPTCHA_API_KEY not set. "
                "Export CAPTCHA_API_KEY=<2captcha key> or add captcha_api_key to config."
            )
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return None

        print(f"  [clericus/{self._county_name}] Submitting Turnstile to 2captcha...")

        import requests as _req
        try:
            submit_resp = _req.post(
                _2CAPTCHA_SUBMIT,
                data={
                    "key": self._captcha_api_key,
                    "method": "turnstile",
                    "sitekey": TURNSTILE_SITEKEY,
                    "pageurl": page_url,
                    "json": 1,
                },
                timeout=30,
            ).json()
        except Exception as exc:
            self.last_failure = f"2captcha submit error: {exc}"
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return None

        if submit_resp.get("status") != 1:
            self.last_failure = f"2captcha submit rejected: {submit_resp}"
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return None

        task_id = submit_resp["request"]
        print(f"  [clericus/{self._county_name}] Turnstile task {task_id} — polling...")

        deadline = time.time() + self._captcha_timeout
        while time.time() < deadline:
            time.sleep(5)
            try:
                result = _req.get(
                    _2CAPTCHA_RESULT,
                    params={
                        "key": self._captcha_api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1,
                    },
                    timeout=30,
                ).json()
            except Exception as exc:
                print(f"  [clericus/{self._county_name}] poll error: {exc}")
                continue

            if result.get("status") == 1:
                token = result["request"]
                print(f"  [clericus/{self._county_name}] Turnstile solved.")
                return token
            if result.get("request") not in ("CAPCHA_NOT_READY", "ERROR_CAPTCHA_UNSOLVABLE"):
                self.last_failure = f"2captcha result error: {result}"
                print(f"  [clericus/{self._county_name}] {self.last_failure}")
                return None

        self.last_failure = "Turnstile solve timeout"
        print(f"  [clericus/{self._county_name}] {self.last_failure}")
        return None

    # ------------------------------------------ Search

    def perform_search(
        self,
        name: str,
        party_type: str = "All",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        parcel_id: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Search by party name with optional document-type filter.

        Solves Turnstile automatically via 2captcha for the initial search POST.
        Subsequent pages are fetched without a new Turnstile solve.

        Args:
            name: Party name to search. Use ``*`` wildcards for partial matches
                  (e.g. ``"KELLY*"``). ``Last First`` format per FL convention.
            party_type: ``"All"`` | ``"Grantor"`` | ``"Grantee"``.
            doc_type: ``"DEED"`` → ``documentTypeID=10``; ``None`` or ``"ALL"`` → all types.
                      Pass the raw numeric string (e.g. ``"10"``) to use directly.
            date_from: Start date MM/DD/YYYY (defaults to config default_start_date).
            date_to: End date MM/DD/YYYY (defaults to config default_end_date).
            parcel_id: Ignored (Clericus has no parcel-ID search per Tony's guide).

        Returns a deduplicated list of DocumentRecord (one per instrument number).
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [clericus/{self._county_name}] session warm failed; "
                    f"last_failure={self.last_failure}"
                )
                return []

        if parcel_id:
            print(
                f"  [clericus/{self._county_name}] WARNING: Clericus has no parcel-ID "
                f"search (Tony guide v2). Parcel ID '{parcel_id}' ignored."
            )

        # Build doc-type value
        doctype_val = self._resolve_doctype(doc_type)

        # Build party-type radio value
        party_radio = self._party_map.get(party_type, PARTY_BOTH)

        # Date window
        sd = date_from or self.start_date or self._default_start
        ed = date_to or self.end_date or self._default_end

        # Solve Turnstile for the initial search POST
        turnstile_token = self._solve_turnstile(self._landing_url)
        if turnstile_token is None:
            print(
                f"  [clericus/{self._county_name}] Turnstile failed — cannot search. "
                f"last_failure={self.last_failure}"
            )
            return []

        # Apply name_input_format from config.
        # "last_space_first" (Sumter default) requires "LAST FIRST" without comma.
        # Most callers pass "LAST, FIRST" — strip the comma when the format requires it.
        name_fmt = self.config.get("name_input_format", "last_space_first")
        formatted_name = name.strip()
        if name_fmt == "last_space_first" and "," in formatted_name:
            # "TEGGE, ROBERT L" → "TEGGE ROBERT L"
            formatted_name = formatted_name.replace(",", " ").split()
            formatted_name = " ".join(formatted_name)

        # POST the search form
        payload: Dict[str, Any] = {
            "county": self._county_id,
            "name": formatted_name,
            "partyType": party_radio,
            "legalDescription": "",
            "documentTypeID": [doctype_val],
            "instrumentTypeID": ["0"],
            "startDate": sd,
            "endDate": ed,
            "instrumentNumber": "",
            "book": "",
            "page": "",
            "filter": "false",
            "cf-turnstile-response": turnstile_token,
        }

        post_url = f"{self._base}{self._action_path}"
        try:
            r = self.session.post(
                post_url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": self._landing_url,
                },
                timeout=60,
            )
        except Exception as exc:
            self.last_failure = f"search POST error: {exc}"
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return []

        if r.status_code != 200:
            self.last_failure = f"search POST HTTP {r.status_code}"
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return []

        if "Please verify you are human" in r.text:
            self.last_failure = "Turnstile token rejected by server"
            print(f"  [clericus/{self._county_name}] {self.last_failure}")
            return []

        # Collect page 1
        all_records, seen = self._parse_results_page(r.text)

        # Collect additional pages (GET — no Turnstile needed)
        page_num = 2
        while True:
            next_link = self._next_page_url(r.text, page_num)
            if not next_link:
                break
            try:
                r = self.session.get(
                    f"{self._base}/orisearch/s/{next_link}",
                    headers={"Referer": post_url},
                    timeout=60,
                )
            except Exception as exc:
                print(f"  [clericus/{self._county_name}] page {page_num} GET error: {exc}")
                break

            if r.status_code != 200 or "Please verify" in r.text:
                break

            new_records, _ = self._parse_results_page(r.text, seen=seen)
            if not new_records:
                break
            all_records.extend(new_records)
            page_num += 1

        # CLIENT-SIDE DOC-TYPE FILTERING (LIVE-VERIFIED 2026-06-18):
        # The Clericus server does NOT honor the documentTypeID filter parameter —
        # it returns ALL document types regardless of what is posted. The doc_type
        # param is for the caller's intent; we apply the filter ourselves.
        # DEED family: "D", "QCD", "WD", "TD", "AGD", "FA" (same FL conventions as DuProcess)
        if doc_type and doc_type.strip().upper() not in ("ALL", ""):
            all_records = self._apply_doctype_filter(all_records, doc_type)

        print(
            f"  [clericus/{self._county_name}] '{name}' ({doc_type or 'ALL'}): "
            f"{len(all_records)} instruments across {page_num - 1} page(s)"
        )

        # Keep session cookie snapshot current after each search (JSESSIONID may rotate).
        try:
            self._session_cookies = dict(self.session.cookies)
        except Exception:
            pass

        return all_records

    # ------------------------------------------ Results parsing

    def extract_results(self, payload: Any = None) -> List[DocumentRecord]:
        """Parse a Clericus results HTML page into DocumentRecord rows.

        Wraps ``_parse_results_page`` for ABC compliance.
        """
        records, _ = self._parse_results_page(payload or "")
        return records

    def _parse_results_page(
        self,
        html: str,
        seen: Optional[set] = None,
    ) -> Tuple[List[DocumentRecord], set]:
        """Parse one results page.

        De-duplicates by instrument number across calls — same instrument may appear
        once per indexed party name. The first occurrence wins for document_type +
        recording_date + pages; all parties are merged into grantors / grantees.

        Returns (new_records, seen_instrument_numbers_set).
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            print(f"  [clericus] bs4 not available: {e}")
            return [], seen or set()

        if seen is None:
            seen = set()

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="ori_results")
        if table is None:
            return [], seen

        # Column indices from the header row
        # Expected: Party Name | Party Type | Date | Document Type | Instrument Number
        #           | Book/Page | Pages | Consideration Amount | Description
        header_row = table.find("tr")
        if header_row is None:
            return [], seen

        col_idx = {}
        for i, cell in enumerate(header_row.find_all(["th", "td"])):
            label = cell.get_text(" ", strip=True).upper().replace("/", " ").strip()
            col_idx[label] = i

        # Fallback column positions if header parsing fails
        IDX_PARTY_NAME = col_idx.get("PARTY NAME", 0)
        IDX_PARTY_TYPE = col_idx.get("PARTY TYPE", 1)
        IDX_DATE = col_idx.get("DATE", 2)
        IDX_DOC_TYPE = col_idx.get("DOCUMENT TYPE", 3)
        IDX_INSTR = col_idx.get("INSTRUMENT NUMBER", 4)
        IDX_BOOK_PAGE = col_idx.get("BOOK PAGE", 5)
        IDX_PAGES = col_idx.get("PAGES", 6)
        IDX_DESC = col_idx.get("DESCRIPTION", 8)

        # Accumulate parties per instrument before de-dup
        # instrument_num -> {grantor_names: [], grantee_names: [], record: DocumentRecord}
        instr_acc: Dict[str, Dict] = {}

        data_rows = table.find_all("tr")[1:]  # skip header
        new_instruments: List[str] = []

        for row in data_rows:
            cells = row.find_all("td")
            if not cells:
                continue

            def cell_text(idx: int) -> str:
                if idx < len(cells):
                    return cells[idx].get_text(" ", strip=True)
                return ""

            party_name = cell_text(IDX_PARTY_NAME)
            party_type_code = cell_text(IDX_PARTY_TYPE).upper()  # F or T
            recording_date = cell_text(IDX_DATE)
            doc_type = cell_text(IDX_DOC_TYPE)
            instr_num = cell_text(IDX_INSTR)
            book_page = cell_text(IDX_BOOK_PAGE)
            pages = cell_text(IDX_PAGES)

            # Description cell: strip the "View Image" link text
            desc_cell = cells[IDX_DESC] if IDX_DESC < len(cells) else None
            description = ""
            q2_hash = ""
            if desc_cell:
                img_link = desc_cell.find("a", href=re.compile(r"image"))
                if img_link:
                    q2_m = re.search(r'q2=([a-f0-9]+)', img_link.get("href", ""))
                    q2_hash = q2_m.group(1) if q2_m else ""
                # Remove the link text so we get just the description
                for a in desc_cell.find_all("a"):
                    a.extract()
                description = desc_cell.get_text(" ", strip=True)

            if not instr_num:
                continue

            # Cache q2 for download
            if q2_hash and instr_num:
                self._q2_by_instrument[instr_num] = q2_hash

            if instr_num in instr_acc:
                # Accumulate additional party names on duplicate rows.
                # Result-row Party Type: F = Grantor (From), T = Grantee (To).
                entry = instr_acc[instr_num]
                if party_type_code == _RESULT_ROW_GRANTOR_CODE:   # "F" = Grantor
                    if party_name and party_name not in entry["grantors"]:
                        entry["grantors"].append(party_name)
                elif party_type_code == _RESULT_ROW_GRANTEE_CODE:  # "T" = Grantee
                    if party_name and party_name not in entry["grantees"]:
                        entry["grantees"].append(party_name)
                else:
                    # B or unknown — add to both
                    if party_name and party_name not in entry["grantors"]:
                        entry["grantors"].append(party_name)
                    if party_name and party_name not in entry["grantees"]:
                        entry["grantees"].append(party_name)
            else:
                # First occurrence.
                # Result-row Party Type: F = Grantor, T = Grantee.
                grantors = []
                grantees = []
                if party_type_code == _RESULT_ROW_GRANTOR_CODE:   # "F"
                    grantors = [party_name] if party_name else []
                elif party_type_code == _RESULT_ROW_GRANTEE_CODE:  # "T"
                    grantees = [party_name] if party_name else []
                else:
                    grantors = [party_name] if party_name else []

                instr_acc[instr_num] = {
                    "grantors": grantors,
                    "grantees": grantees,
                    "doc_type": doc_type,
                    "recording_date": recording_date,
                    "pages": pages,
                    "book_page": book_page,
                    "description": description,
                    "q2": q2_hash,
                }
                if instr_num not in seen:
                    new_instruments.append(instr_num)

        # Build DocumentRecord list for genuinely new instruments only
        new_records: List[DocumentRecord] = []
        for instr_num in new_instruments:
            if instr_num in seen:
                continue
            seen.add(instr_num)
            entry = instr_acc[instr_num]

            grantors_str = " / ".join(entry["grantors"])
            grantees_str = " / ".join(entry["grantees"])
            all_parties = " / ".join(
                p for p in (grantors_str, grantees_str) if p
            )

            new_records.append(
                DocumentRecord(
                    document_number=instr_num,
                    grantors=grantors_str,
                    grantees=grantees_str,
                    grantor_grantees=all_parties,
                    document_type=entry["doc_type"],
                    recording_date=entry["recording_date"],
                    pages=entry["pages"],
                )
            )

        return new_records, seen

    # ------------------------------------------ Detail / download

    def pull_detail(self, doc_num: str) -> Dict[str, Any]:
        """Return indexing data for a known instrument number.

        Clericus does not have a separate instrument-detail endpoint; all data
        was captured in the search result row. This method returns the cached
        data for the instrument, or an error if it was never searched.
        """
        if not self._session_warmed:
            self.warm_session()
        # Best we can do without a separate endpoint is return what we have
        return {
            "document_number": doc_num,
            "note": "Clericus has no separate detail endpoint; data from search row.",
            "q2": self._q2_by_instrument.get(doc_num, ""),
        }

    def download_pdf(
        self,
        doc_num: str = None,
        dest_path: str = None,
        q2: str = None,
    ) -> Dict[str, Any]:
        """Download the instrument PDF via /orisearch/s/image?q1=<q1>&q2=<q2_hash>.

        The ``q2`` hash is extracted from the search result row's View-Image link.
        It must have been cached by a prior ``perform_search`` call for ``doc_num``,
        OR supplied directly via the ``q2`` argument.

        Args:
            doc_num: Instrument number (must have been in a prior search result).
            dest_path: File path to save the PDF.
            q2: Override the q2 hash (for direct download bypassing the cache).

        Returns a dict with ``status``, ``size``, ``src_via`` on success.
        """
        if not self._session_warmed:
            if not self.warm_session():
                return {"status": "error", "message": "session not warmed"}

        # Resolve q2
        q2_val = q2 or self._q2_by_instrument.get(str(doc_num), "")
        if not q2_val:
            return {
                "status": "error",
                "message": (
                    f"q2 hash not cached for instrument {doc_num}. "
                    "Run perform_search first to populate the q2 cache."
                ),
            }

        if not self._q1:
            return {"status": "error", "message": "q1 token not set (session not warmed)"}

        img_url = f"{self._base}/orisearch/s/image"
        try:
            r = self.session.get(
                img_url,
                params={"q1": self._q1, "q2": q2_val},
                headers={"Referer": f"{self._base}/orisearch/s/search?q1={self._q1}"},
                timeout=120,
            )
        except Exception as exc:
            return {"status": "error", "message": f"download GET error: {exc}"}

        if r.status_code != 200:
            return {"status": "error", "message": f"download HTTP {r.status_code}"}

        if r.content[:4] != b"%PDF":
            return {
                "status": "error",
                "message": f"expected PDF, got {r.content[:8]!r}",
            }

        if dest_path:
            import pathlib
            pathlib.Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as fh:
                fh.write(r.content)

        size = len(r.content)
        return {
            "status": "success",
            "size": size,
            "src_via": "orisearch_image",
            "ok": True,
            "path": str(dest_path) if dest_path else None,
            "bytes": size,
        }

    # ------------------------------------------ Helpers

    def _resolve_doctype(self, doc_type: Optional[str]) -> str:
        """Map a canonical doc-type name to the platform's numeric select value."""
        if not doc_type:
            return DOCTYPE_ALL
        dt = doc_type.strip().upper()
        if dt in ("ALL", ""):
            return DOCTYPE_ALL
        if dt in ("DEED", "D"):
            return self._doctype_deed  # default "10"
        if dt in ("MORTGAGE", "MTG"):
            return DOCTYPE_MORTGAGE
        if dt in ("SATISFACTION", "SAT"):
            return DOCTYPE_SATISFACTION
        if dt in ("RELEASE", "REL"):
            return DOCTYPE_RELEASE
        if dt in ("LIS PENDENS", "LP"):
            return DOCTYPE_LIS_PENDENS
        if dt in ("JUDGMENT", "JUD"):
            return DOCTYPE_JUDGMENT
        if dt == "LIEN":
            return DOCTYPE_LIEN
        if dt in ("NOTICE OF COMMENCEMENT", "NOC"):
            return DOCTYPE_NOC
        if dt in ("UCC", "FINANCING STATEMENT"):
            return DOCTYPE_UCC
        # If caller passes a raw numeric string, use it directly
        if dt.isdigit():
            return dt
        return DOCTYPE_ALL

    def _apply_doctype_filter(
        self, records: List[DocumentRecord], doc_type: str
    ) -> List[DocumentRecord]:
        """Client-side document-type filter (server does not honor the param).

        Maps canonical doc_type names to the short instrument codes used by
        the Clericus platform. DEED family: D, QCD, WD, TD, AGD.

        LIVE-VERIFIED 2026-06-18: server ignores documentTypeID POST param;
        all doc types returned regardless of selection.
        """
        dt = doc_type.strip().upper()
        if dt in ("ALL", ""):
            return records

        # Standard doc-type → set of Clericus instrument codes
        DOCTYPE_CODE_MAP: Dict[str, set] = {
            "DEED":         {"D", "QCD", "WD", "TD", "AGD", "FA", "DEED"},
            "D":            {"D", "QCD", "WD", "TD", "AGD", "FA", "DEED"},
            "MORTGAGE":     {"MTG", "MTG1", "MTG2", "MORTGAGE"},
            "MTG":          {"MTG", "MTG1", "MTG2", "MORTGAGE"},
            "SATISFACTION": {"SAT", "SATISFACTION"},
            "SAT":          {"SAT", "SATISFACTION"},
            "RELEASE":      {"REL", "RELEASE", "PR"},
            "REL":          {"REL", "RELEASE", "PR"},
            "PARTIAL RELEASE": {"PR", "PARTIAL RELEASE"},
            "LIS PENDENS":  {"LP", "LPC", "LIS PENDENS"},
            "LP":           {"LP", "LPC", "LIS PENDENS"},
            "JUDGMENT":     {"JUD", "CCJ", "JUDGMENT"},
            "JUD":          {"JUD", "CCJ", "JUDGMENT"},
            "LIEN":         {"LN", "LIEN"},
            "NOTICE OF COMMENCEMENT": {"NOC", "NOTICE OF COMMENCEMENT"},
            "NOC":          {"NOC", "NOTICE OF COMMENCEMENT"},
            "UCC":          {"FIN", "UCC", "FINANCING STATEMENT"},
            "FINANCING STATEMENT": {"FIN", "UCC", "FINANCING STATEMENT"},
            "ASSIGNMENT":   {"ASG", "ASSIGNMENT"},
            "MODIFICATION": {"MOD", "MODIFICATION"},
            "TERMINATION":  {"TER", "TERMINATION"},
            "AFFIDAVIT":    {"AFF", "AFFIDAVIT"},
            "EASEMENT":     {"EAS", "EASEMENT"},
        }

        allowed_codes = DOCTYPE_CODE_MAP.get(dt)
        if allowed_codes is None:
            # Unknown type — pass through without filtering
            print(
                f"  [clericus/{self._county_name}] WARNING: unknown doc_type "
                f"'{doc_type}' for client-side filter — returning all records"
            )
            return records

        return [r for r in records if r.document_type.strip().upper() in allowed_codes]

    def _next_page_url(self, html: str, page_num: int) -> Optional[str]:
        """Return the relative URL for the next page, or None if no more pages.

        Pagination links are of the form:
            ``search?q1=<q1>&d-8001259-p=<page>``
        They are found in the pagination widget (class "pagelinks").
        We look for the link to ``page_num`` specifically.
        """
        target = f"d-8001259-p={page_num}"
        if target not in html:
            return None
        # Find the href that contains the target
        m = re.search(
            r'href="(search\?q1=[^"]*d-8001259-p=' + str(page_num) + r')"',
            html,
        )
        return m.group(1) if m else None

    def get_filterinstrument(self, doc_type_ids: List[str] = None) -> List[Dict]:
        """Fetch the filtered instrument-type list for the given standard doc types.

        Uses the AJAX endpoint ``/orisearch/s/filterInstrument``.
        Returns a list of ``{"label": ..., "value": ...}`` dicts.
        """
        try:
            r = self.session.post(
                f"{self._base}/orisearch/s/filterInstrument",
                data={"documentTypeID": doc_type_ids or ["0"]},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                    "Referer": self._landing_url,
                },
                timeout=15,
            )
            import json
            data = r.json()
            return data.get("filteredSecondList", [])
        except Exception as exc:
            return [{"error": str(exc)}]
