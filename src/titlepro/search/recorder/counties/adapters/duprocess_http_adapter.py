"""DuProcess Web Inquiry HTTP-First Recorder Adapter (FL — Seminole + sister counties).

Pure-Python adapter for the **DuProcess Web Inquiry** platform
(e.g. https://recording.seminoleclerk.org/DuProcessWebInquiry/). Built Wave-1
2026-06-10; the API contract was reverse-engineered from the live SPA JS bundle
(`assets/index.6bae0200.js`, capture 2026-02-11) because the live host geo-blocks the
build environment — see
`src/titlepro/api/downloaded_doc/0610/Seminole_PORTILLA_v1/phase0_probe_recorder.md`.

Platform contract (from the SPA `SearchAPI` object)
---------------------------------------------------
* **Vue 3 SPA + ASP.NET MVC JSON backend**, Infragistics igGrid result grid.
* **No Cloudflare, no reCAPTCHA, no disclaimer gate.** Anonymous search is allowed
  (`user_id=""`); login is only required for the cart/purchase (certified-copy) flow.
* All endpoints are **HTTP GET with query params** (axios `.get(url, {params})`); responses
  are JSON.
* Name/criteria search: `GET Home/CriteriaSearch?criteria_array=<json-string>&user_id=`
  where `criteria_array` is `JSON.stringify([{...}])` (a one-element array of a criteria
  object). Key fields: `direction` ('' = Both/All, 'F' = Grantor/From, 'T' = Grantee/To),
  `full_name` ("lastname, firstname"), `file_date_start`/`file_date_end` (MM/DD/YYYY),
  `inst_type` (comma-joined single-quoted instrument-type id list, e.g. `'DEED'`),
  `parcel_id` (APN search — Tony directive #2 re-search leg).
* Result rows carry `gin` (internal primary key), `inst_num`, `from_party`/`to_party`,
  `instrument_type`, `file_date`, `book_reel`/`page`, `num_pages`, `verified_status`, and
  the APN directly in `real_estate_id` / `parcel_number`.
* Effective date: `GET Home/GetVerifiedUntilDate` (MS-AJAX `/Date(...)/`).
* Detail: `GET Home/LoadInstrument/?access_key=<obfuscate(gin)>!<ipsum>-<min>-<sec>`.
* Related instruments (satisfaction↔mortgage): `GET Home/GetRelatedInstruments?gin=<gin>`.
* Direct retrieval: `GET Integration/QueryInstrumentID?book=&page=&book_type=&inst_num=&inst_sub=&location=`.
* Image: `GET Home/GetDocumentPage/{user_id},{obfuscate(gin)},{pageIndex}` ; full PDF:
  `GET Home/CreateDocument/{user_id},{access_key},{show_thumbnail}`.

GIN obfuscation cipher (verbatim from the bundle)
-------------------------------------------------
Per-digit substitution against the alphabet `"JABCDEFGHI"` — `0→J, 1→A, ... 9→I`. Applied
to `gin` (and `PrimaryKeyValue`) before LoadInstrument / GetNumberOfDocumentPages /
GetDocumentPage / CreateDocument.

WAVE-2 LIVE VALIDATION (2026-06-10, US egress) — confirmed deltas applied
-------------------------------------------------------------------------
1. **Session-token gate (NEW in live bundle `index.8bdd7d28.js`, app v26.4.27.2357):**
   every `/Home/*` + `/Lookup/*` call requires an `X-Api-Token` header minted via
   `GET /Home/GetSessionToken` -> `{"token": "<32-hex>"}`. Without it IIS returns
   403 "Access is denied". The SPA re-mints on any 403 — this adapter does the same
   (`_mint_token()` + one retry in `warm_session`/`perform_search`).
2. **criteria_array MUST include all 16 quarter flags (`q_NWNW`…`q_SESE`, default
   false) AND `max_rows`** (SPA default 200; server `WEB_ROW_LIMIT` custom default is
   2000). Omitting them -> HTTP 500.
3. DEED instrument-type ids (live `Lookup/InstrumentTypeLookup` returns a flat
   {label: id} map, 74 types): deed family = `'D','QCD','FA','AGD'` (Deed, Quit Claim
   Deed, Deed W/Assumption, Agreement For Deed).
4. `MINIMUM_SEARCH_DATE` = 1/1/1913 (Seminole). `GET /Bootstrap/GetBootstrapData`
   carries verifiedDate, customDefaults (WEB_ROW_LIMIT), and dropdowns incl. the
   InstrumentType map.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


DEFAULT_IMPERSONATE = "safari17_2_ios"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# GIN obfuscation alphabet (digit d -> CIPHER[d]).
OBFUSCATION_CIPHER = "JABCDEFGHI"


def obfuscate_gin(value: Any) -> str:
    """Replicate the SPA `obfusicateValue`: map each decimal digit through
    ``"JABCDEFGHI"`` (0->J, 1->A, ... 9->I). Non-digit chars are passed through
    only if they index into the cipher; the SPA only ever feeds pure-digit gins.
    """
    out = []
    for ch in str(value):
        if ch.isdigit():
            out.append(OBFUSCATION_CIPHER[int(ch)])
        else:
            # SPA never feeds non-digits; preserve defensively.
            out.append(ch)
    return "".join(out)


def build_access_key(gin: Any, ip_address: str = "0", now: Optional[datetime] = None) -> str:
    """Replicate the SPA access_key recipe:
        obfuscate(gin) + "!" + ip_sum + "-" + minutes + "-" + seconds
    where ip_sum = sum of the dot-separated octets ("0" -> 0).
    """
    now = now or datetime.now()
    try:
        ip_sum = sum(int(p) for p in str(ip_address).split(".") if p != "")
    except ValueError:
        ip_sum = 0
    return f"{obfuscate_gin(gin)}!{ip_sum}-{now.minute}-{now.second}"


class DuProcessHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for DuProcess Web Inquiry (Seminole FL et al.)."""

    # ---------------------------------------------------------------- init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/1990",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config or {}

        self._county_name = self.config.get("county_name", "Seminole")
        self._app_root = (
            self.config.get("app_root")
            or self.config.get("base_url")
            or "https://recording.seminoleclerk.org/DuProcessWebInquiry/"
        )
        if not self._app_root.endswith("/"):
            self._app_root += "/"

        ep = self.config.get("duprocess_endpoints", {})
        self._ep_verified = ep.get("verified_until_date", "Home/GetVerifiedUntilDate")
        self._ep_version = ep.get("application_version", "Home/GetApplicationVersion")
        self._ep_search = ep.get("criteria_search", "Home/CriteriaSearch")
        self._ep_load = ep.get("load_instrument", "Home/LoadInstrument/")
        self._ep_numpages = ep.get("num_pages", "Home/GetNumberOfDocumentPages")
        self._ep_docpage = ep.get("document_page", "Home/GetDocumentPage/")
        self._ep_createdoc = ep.get("create_document", "Home/CreateDocument/")
        self._ep_legals = ep.get("instrument_legals", "Home/GetInstrumentLegals")
        self._ep_related = ep.get("related_instruments", "Home/GetRelatedInstruments")
        self._ep_queryid = ep.get("query_instrument_id", "Integration/QueryInstrumentID")
        self._ep_insttype_lookup = ep.get("instrument_type_lookup", "Lookup/InstrumentTypeLookup")
        self._ep_custom_default = ep.get("custom_default", "Lookup/GetCustomDefault")
        # Live-validated 2026-06-10: X-Api-Token session gate + bootstrap endpoint.
        self._ep_session_token = ep.get("session_token", "Home/GetSessionToken")
        self._ep_bootstrap = ep.get("bootstrap", "Bootstrap/GetBootstrapData")

        self._user_id = str(self.config.get("anonymous_user_id", ""))
        self._date_format = self.config.get("date_format", "MM/DD/YYYY")
        self._min_search_date = self.config.get("minimum_search_date_default", "01/01/1900")

        # direction radio: '' Both, 'F' Grantor/From, 'T' Grantee/To.
        self.party_type_map = self.config.get(
            "party_type_map",
            {"All": "", "Both": "", "Grantor/Grantee": "", "Grantor": "F", "Grantee": "T"},
        )
        self.supported_party_types = self.config.get(
            "supported_party_types", ["All", "Grantor", "Grantee"]
        )

        # Deed-first: literal instrument-type id list for criteria_array.inst_type.
        # Live-validated Seminole deed family: Deed, Quit Claim Deed, Deed
        # W/Assumption, Agreement For Deed.
        self._deed_inst_type_id = self.config.get(
            "deed_instrument_type_id", "'D','QCD','FA','AGD'"
        )
        # criteria_array.max_rows — server WEB_ROW_LIMIT custom default is 2000.
        self._max_rows = int(self.config.get("max_rows", 2000))

        # Result-column key map (igGrid DefaultColumnList keys).
        rc = self.config.get("result_columns", {})
        self._col_id = rc.get("internal_id", "gin")
        self._col_docnum = rc.get("document_number", "inst_num")
        self._col_grantor = rc.get("grantor", "from_party")
        self._col_grantee = rc.get("grantee", "to_party")
        self._col_party = rc.get("party_name", "party_name")
        self._col_type = rc.get("document_type", "instrument_type")
        self._col_date = rc.get("recording_date", "file_date")
        self._col_book = rc.get("book", "book_reel")
        self._col_page = rc.get("page", "page")
        self._col_pages = rc.get("pages", "num_pages")
        self._col_apn = rc.get("apn", "real_estate_id")
        self._col_parcel = rc.get("parcel_number", "parcel_number")

        impersonate_profile = self.config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)

        self._session_warmed = False
        self.last_failure: Optional[str] = None
        self.verified_until_date: Optional[str] = None  # County Effective Date

        # Instrument # -> gin map for downstream image retrieval.
        self._gin_by_number: Dict[str, str] = {}
        # APN harvested off the most recent result set (deed-first → parcel re-search).
        self.last_apn_by_number: Dict[str, str] = {}

        self.driver = None  # ABC compliance; never used.

    # -------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._app_root

    # ------------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        # DuProcess is stateless JSON GETs — nothing to reset between searches.
        return None

    # ----------------------------------------------------------- helpers

    def _url(self, endpoint: str) -> str:
        return urljoin(self._app_root, endpoint)

    def _origin(self) -> str:
        # scheme://host of the app root
        from urllib.parse import urlsplit
        s = urlsplit(self._app_root)
        return f"{s.scheme}://{s.netloc}"

    # ----------------------------------------------------------- session warm-up

    def _mint_token(self) -> Optional[str]:
        """GET Home/GetSessionToken -> {"token": "<32-hex>"} and install it as the
        ``X-Api-Token`` session header (live-validated 2026-06-10; without it every
        /Home/* + /Lookup/* call returns IIS 403)."""
        resp = self.session.get(self._url(self._ep_session_token), timeout=30)
        if resp.status_code != 200:
            return None
        try:
            token = resp.json().get("token")
        except Exception:
            return None
        if token:
            self.session.headers["X-Api-Token"] = token
        return token

    def warm_session(self) -> bool:
        """GET the app root, mint the X-Api-Token, capture the County Effective Date.

        DuProcess has no disclaimer / captcha gate, but the live app (v26.4.27+)
        requires a session token header on every API call.
        """
        try:
            self.session.get(self._app_root, timeout=30)
        except Exception as exc:
            self.last_failure = f"landing GET failed: {exc}"
            return False
        try:
            if not self._mint_token():
                self.last_failure = "GetSessionToken failed"
                return False
        except Exception as exc:
            self.last_failure = f"GetSessionToken error: {exc}"
            return False
        # Best-effort effective date.
        try:
            self.verified_until_date = self.get_verified_until_date()
        except Exception:
            self.verified_until_date = None
        self._session_warmed = True
        return True

    def get_bootstrap(self) -> Any:
        """GET Bootstrap/GetBootstrapData — verifiedDate, customDefaults
        (MINIMUM_SEARCH_DATE, WEB_ROW_LIMIT), dropdowns (InstrumentType map)."""
        try:
            resp = self.session.get(self._url(self._ep_bootstrap), timeout=30)
            return _loads(resp.text)
        except Exception as exc:
            return {"error": str(exc)}

    def get_verified_until_date(self) -> Optional[str]:
        """County Effective Date. DuProcess returns MS-AJAX ``/Date(ms)/``."""
        resp = self.session.get(self._url(self._ep_verified), timeout=30)
        if resp.status_code != 200:
            return None
        # Live server returns the JSON string '"\\/Date(1780891200000)\\/"' —
        # strip quotes AND the JSON-escaped backslashes before parsing.
        raw = (resp.text or "").strip().strip('"').replace("\\/", "/")
        if "/Date(" in raw:
            try:
                ms = int(raw.replace("/Date(", "").replace(")/", "").split("+")[0].split("-")[0] or "0")
                dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
                return dt.strftime("%m/%d/%Y")
            except Exception:
                return raw
        return raw

    def resolve_deed_instrument_type_id(self) -> str:
        """Best-effort: resolve the DEED instrument-type id(s) from the lookup.

        Returns the single-quoted, comma-joined id string suitable for
        ``criteria_array.inst_type``. Seminole default (live-validated 2026-06-10):
        ``"'D','QCD','FA','AGD'"``. Sister DuProcess counties may differ — the
        live ``Lookup/InstrumentTypeLookup`` returns a flat ``{label: id}`` map.
        """
        if self._deed_inst_type_id:
            return self._deed_inst_type_id
        try:
            resp = self.session.get(
                self._url(self._ep_insttype_lookup), params={"filter": ""}, timeout=30
            )
            data = _loads(resp.text)
            # Live shape: flat {"Deed": "D", "Quit Claim Deed": "QCD", ...} map.
            if isinstance(data, dict) and data and all(
                isinstance(v, str) for v in data.values()
            ):
                ids = [v for k, v in data.items() if "DEED" in k.upper()]
                if ids:
                    return ",".join(f"'{i}'" for i in ids)
            rows = _rows(data)
            for r in rows:
                label = " ".join(
                    str(r.get(k, "")) for k in ("Description", "Name", "Value", "text")
                ).upper()
                rid = r.get("id") or r.get("Value") or r.get("value") or r.get("Code")
                if rid and label.strip() == "DEED":
                    return f"'{rid}'"
            # Fall back to any type whose label contains DEED.
            for r in rows:
                label = " ".join(
                    str(r.get(k, "")) for k in ("Description", "Name", "Value", "text")
                ).upper()
                rid = r.get("id") or r.get("Value") or r.get("value") or r.get("Code")
                if rid and "DEED" in label:
                    return f"'{rid}'"
        except Exception:
            pass
        return ""

    # ---------------------------------------------------------------- search

    def build_criteria_array(
        self,
        name: str = "",
        direction: str = "",
        inst_type: str = "",
        parcel_id: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> str:
        """Build the JSON ``criteria_array`` string for CriteriaSearch.

        Emits the full field set the SPA sends (empty strings for unused fields)
        wrapped in a one-element array, matching ``getCriteriaSearchResult``.
        """
        sd = date_from or self.start_date or self._min_search_date
        ed = date_to or self.end_date or datetime.now().strftime("%m/%d/%Y")
        criteria = {
            "direction": direction or "",
            "name_direction": False,
            "full_name": (name or "").replace("'", ""),
            "file_date_start": sd,
            "file_date_end": ed,
            "inst_type": inst_type or "",
            "inst_book_type_id": "",
            "location_id": "",
            "book_reel": "",
            "page_image": "",
            "greater_than_page": False,
            "inst_num": "",
            "description": "",
            "consideration_value_min": "",
            "consideration_value_max": "",
            "parcel_id": parcel_id or "",
            "legal_section": "",
            "legal_township": "",
            "legal_range": "",
            "legal_square": "",
            "subdivision_code": "",
            "block": "",
            "lot_from": "",
            # All 16 quarter-quarter flags are REQUIRED (live server returns
            # HTTP 500 if any is missing). Default false.
            **{
                f"q_{a}{b}": False
                for a in ("NW", "NE", "SW", "SE")
                for b in ("NW", "NE", "SW", "SE")
            },
            # MUST be boolean false (live server 500s on the Wave-1 guess of "").
            "q_q_search_type": False,
            "address_street": "",
            "address_number": "",
            "address_parcel": "",
            "address_ppin": "",
            "patent_number": "",
            # REQUIRED by the live server (HTTP 500 if missing). WEB_ROW_LIMIT=2000.
            "max_rows": self._max_rows,
        }
        # Compact separators to byte-match JS JSON.stringify.
        return json.dumps([criteria], separators=(",", ":"))

    def perform_search(
        self,
        name: str,
        party_type: str = "All",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        parcel_id: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP DuProcess CriteriaSearch.

        Args:
            name: Party name "lastname, firstname" (the SPA placeholder format).
            party_type: "All"|"Grantor"|"Grantee" → criteria `direction` ''/'F'/'T'.
            doc_type: "DEED" triggers deed-first inst_type resolution; pass a literal
                      single-quoted id list (e.g. "'5'") to forward as-is.
            parcel_id: APN re-search leg (Tony directive #2). When set, `name` may be "".

        Returns a list of DocumentRecord. Empty on session/transport failure.
        """
        if not self._session_warmed and not self.warm_session():
            print(f"  [duprocess] session not warmed; last_failure={self.last_failure}")
            return []

        direction = self.party_type_map.get(party_type, "")

        inst_type = ""
        if doc_type:
            if doc_type.upper() == "DEED":
                inst_type = self.resolve_deed_instrument_type_id()
            elif doc_type.strip().startswith("'") or doc_type.strip().isdigit():
                inst_type = doc_type if doc_type.startswith("'") else f"'{doc_type}'"
            else:
                inst_type = doc_type

        criteria_array = self.build_criteria_array(
            name=name,
            direction=direction,
            inst_type=inst_type,
            parcel_id=parcel_id or "",
            date_from=date_from or "",
            date_to=date_to or "",
        )

        try:
            resp = self.session.get(
                self._url(self._ep_search),
                params={"criteria_array": criteria_array, "user_id": self._user_id},
                headers={"Referer": self._app_root},
                timeout=60,
            )
        except Exception as exc:
            self.last_failure = f"CriteriaSearch network: {exc}"
            print(f"  [duprocess] {self.last_failure}")
            return []

        # Token expiry surfaces as 403 — re-mint once and retry (mirrors the
        # SPA's registerTokenInterceptor behavior).
        if resp.status_code == 403:
            print("  [duprocess] 403 — re-minting X-Api-Token and retrying once")
            try:
                self._mint_token()
                resp = self.session.get(
                    self._url(self._ep_search),
                    params={"criteria_array": criteria_array, "user_id": self._user_id},
                    headers={"Referer": self._app_root},
                    timeout=60,
                )
            except Exception as exc:
                self.last_failure = f"CriteriaSearch retry network: {exc}"
                print(f"  [duprocess] {self.last_failure}")
                return []

        if resp.status_code != 200:
            self.last_failure = f"CriteriaSearch HTTP {resp.status_code}"
            print(f"  [duprocess] {self.last_failure}")
            return []

        return self.extract_results(resp.text)

    # ------------------------------------------------------------- extract

    def extract_results(self, payload: Any) -> List[DocumentRecord]:
        """Parse a CriteriaSearch response into DocumentRecord rows.

        Handles three response envelopes defensively (Wave-2 confirms which):
        bare JSON array, ``{"d": [...]}``, or ``{"Records": [...]}``.
        """
        data = _loads(payload)
        rows = _rows(data)
        records: List[DocumentRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            doc_num = _s(row.get(self._col_docnum))
            gin = _s(row.get(self._col_id))
            if gin and doc_num:
                self._gin_by_number[doc_num] = gin
            apn = _s(row.get(self._col_apn)) or _s(row.get(self._col_parcel))
            if doc_num and apn:
                self.last_apn_by_number[doc_num] = apn

            grantor = _s(row.get(self._col_grantor)) or _s(row.get(self._col_party))
            grantee = _s(row.get(self._col_grantee))
            records.append(
                DocumentRecord(
                    document_number=doc_num or gin,
                    grantors=grantor,
                    grantees=grantee,
                    grantor_grantees=" / ".join(p for p in (grantor, grantee) if p),
                    document_type=_s(row.get(self._col_type)),
                    recording_date=_fmt_msajax_date(row.get(self._col_date)),
                    pages=_s(row.get(self._col_pages)),
                )
            )
        return records

    # ------------------------------------------------------------- detail

    def get_related_instruments(self, gin: str) -> Any:
        """GET Home/GetRelatedInstruments?gin=<gin> — satisfaction↔mortgage chain.

        Load-bearing for the released-mortgage linker.
        """
        try:
            resp = self.session.get(
                self._url(self._ep_related), params={"gin": gin}, timeout=30
            )
            return _loads(resp.text)
        except Exception as exc:
            return {"error": str(exc)}

    def load_instrument(self, gin: str) -> Any:
        """GET Home/LoadInstrument/?access_key=<...> — full instrument detail."""
        access_key = build_access_key(gin)
        try:
            resp = self.session.get(
                self._url(self._ep_load), params={"access_key": access_key}, timeout=30
            )
            return _loads(resp.text)
        except Exception as exc:
            return {"error": str(exc)}

    def query_instrument_id(
        self,
        book: str = "",
        page: str = "",
        book_type: str = "",
        inst_num: str = "",
        inst_sub: str = "",
        location: str = "",
    ) -> Any:
        """Direct retrieval: GET Integration/QueryInstrumentID → gin for a known
        book/page or instrument number (Broward-Standard item #4)."""
        try:
            resp = self.session.get(
                self._url(self._ep_queryid),
                params={
                    "book": book,
                    "page": page,
                    "book_type": book_type,
                    "inst_num": inst_num,
                    "inst_sub": inst_sub,
                    "location": location,
                },
                timeout=30,
            )
            return _loads(resp.text)
        except Exception as exc:
            return {"error": str(exc)}

    def pull_detail(self, doc_num: str) -> Dict:
        """Return instrument detail for a recorder instrument number.

        Resolves the gin (from the cached search result, else via
        Integration/QueryInstrumentID) then LoadInstrument.
        """
        if not self._session_warmed:
            self.warm_session()
        gin = self._gin_by_number.get(doc_num)
        if not gin:
            qid = self.query_instrument_id(inst_num=doc_num)
            gin = _s(qid) if not isinstance(qid, (dict, list)) else _first_gin(qid)
        if not gin:
            return {"document_number": doc_num, "error": "gin unresolved"}
        detail = self.load_instrument(gin)
        return {"document_number": doc_num, "gin": gin, "detail": detail}

    @property
    def _path_user_id(self) -> str:
        """user_id token for path-style URLs. LIVE-VALIDATED: an empty string
        yields 'Invalid ID supplied to CreateDocument function' — anonymous
        sessions must pass the literal string 'undefined' (matches the SPA's
        behavior when SearchAPI.user_id is unset)."""
        return self._user_id or "undefined"

    def document_image_urls(self, gin: str, num_pages: int = 1) -> List[str]:
        """Build per-page image URLs: Home/GetDocumentPage/{user},{obfuscate(gin)},{i}."""
        base = self._url(self._ep_docpage)
        og = obfuscate_gin(gin)
        return [f"{base}{self._path_user_id},{og},{i}" for i in range(max(1, num_pages))]

    def pdf_document_url(self, gin: str, show_thumbnail: bool = False) -> str:
        """Full-PDF URL: Home/CreateDocument/{user},{access_key},{show_thumbnail}."""
        base = self._url(self._ep_createdoc)
        access_key = build_access_key(gin)
        return f"{base}{self._path_user_id},{access_key},{str(show_thumbnail).lower()}"

    def _prime_document(self, gin: str) -> None:
        """Register the instrument server-side before CreateDocument.

        LIVE-VERIFIED 2026-06-18 (Seminole KNOLL): hitting Home/CreateDocument
        cold returns HTTP 200 with a JSON ``"Error"`` body (no PDF). The SPA
        always primes the session first with LoadInstrument + a numeric
        GetNumberOfDocumentPages (``?id=<obfuscate(gin)>``); after that prime,
        CreateDocument returns ``%PDF``. Best-effort — failures here are
        non-fatal; the CreateDocument GET reports the real error.
        """
        try:
            self.session.get(
                self._url(self._ep_load),
                params={"access_key": build_access_key(gin)},
                timeout=30,
            )
        except Exception:
            pass
        try:
            self.session.get(
                self._url(self._ep_numpages),
                params={"id": obfuscate_gin(gin)},
                timeout=30,
            )
        except Exception:
            pass

    def download_pdf(self, gin: str = None, dest_path: str = None,
                     doc_num: str = None) -> Dict[str, Any]:
        """Download the full instrument PDF. Accepts a gin OR an instrument
        number — resolve to the internal gin first, since the access-key cipher
        and the image endpoints key off the numeric gin, not the printed
        instrument #.

        The pipeline download phase calls this as
        ``download_pdf(doc_num=<instrument#>, dest_path=<path>)`` and expects a
        Tyler/AcclaimWeb-style result dict (``{"status": "success", "size": N,
        "src_via": ...}`` on success). Standalone callers may pass a positional
        ``gin``. We accept both and normalize the return contract.
        """
        if gin is None:
            gin = doc_num
        if not self._session_warmed:
            self.warm_session()
        # Resolve instrument-number → gin when needed.
        # NOTE: Seminole instrument numbers are purely numeric (e.g. "2026043534")
        # AND gins are also purely numeric but much shorter (7-8 digits). We
        # CANNOT rely on isdigit() to distinguish them — always resolve via
        # QueryInstrumentID unless we already have the gin cached from a prior
        # search (in _gin_by_number). The old "if not isdigit" guard was the bug
        # that caused every post-1999 Seminole download to silently fail: they
        # have no hyphens, so the code treated the instrument# as if it were
        # already a gin, and sent it to the wrong CreateDocument slot.
        resolved = self._gin_by_number.get(str(gin))
        if not resolved:
            try:
                qid = self.query_instrument_id(inst_num=str(gin))
                resolved = _s(qid) if not isinstance(qid, (dict, list)) else _first_gin(qid)
            except Exception:
                resolved = None
        if resolved:
            gin = resolved
        last_err = None
        # Always prime FIRST (LoadInstrument + GetNumberOfDocumentPages) — a
        # cold CreateDocument returns a JSON "Error" body, and a cold-then-prime
        # retry can desync the access-key minute/second window. Prime, then
        # CreateDocument, with one re-prime retry for robustness.
        for attempt in range(2):
            self._prime_document(gin)
            url = self.pdf_document_url(gin)
            try:
                resp = self.session.get(url, timeout=120)
            except Exception as exc:
                last_err = f"network: {exc}"
                continue
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                with open(dest_path, "wb") as fh:
                    fh.write(resp.content)
                size = len(resp.content)
                # Dual contract: pipeline reads status/size/src_via; standalone
                # callers/tests read ok/gin/path/bytes.
                return {"status": "success", "size": size, "src_via": "createdocument",
                        "ok": True, "gin": gin, "path": str(dest_path), "bytes": size}
            last_err = f"HTTP {resp.status_code} / magic {resp.content[:8]!r}"
        return {"status": "error", "message": last_err,
                "ok": False, "gin": gin, "error": last_err}


# --------------------------------------------------------------- module helpers


def _loads(payload: Any) -> Any:
    """Tolerant JSON loader. DuProcess sometimes wraps JSON in a `.data` string."""
    if isinstance(payload, (dict, list)):
        return payload
    if payload is None:
        return None
    s = str(payload).strip()
    if not s:
        return None
    try:
        val = json.loads(s)
    except Exception:
        return s
    # Some Lookup endpoints return {"data": "<json-string>"} — unwrap once.
    if isinstance(val, dict) and "data" in val and isinstance(val["data"], str):
        try:
            return json.loads(val["data"])
        except Exception:
            return val
    return val


def _rows(data: Any) -> List[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("d", "Records", "records", "Results", "results", "rows", "data"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    return []


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _first_gin(obj: Any) -> str:
    if isinstance(obj, dict):
        for k in ("gin", "Gin", "GIN", "PrimaryKeyValue"):
            if obj.get(k):
                return str(obj[k])
    if isinstance(obj, list) and obj:
        return _first_gin(obj[0])
    return ""


def _fmt_msajax_date(v: Any) -> str:
    """Normalize a DuProcess file_date to MM/DD/YYYY.

    Accepts MS-AJAX ``/Date(ms)/``, epoch-ms ints, or already-formatted strings.
    """
    if v is None:
        return ""
    s = str(v).strip()
    if "/Date(" in s:
        try:
            ms = int(s.replace("/Date(", "").replace(")/", "").split("+")[0].split("-")[0] or "0")
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%m/%d/%Y")
        except Exception:
            return s
    if s.isdigit() and len(s) >= 12:
        try:
            return datetime.fromtimestamp(int(s) / 1000.0, tz=timezone.utc).strftime("%m/%d/%Y")
        except Exception:
            return s
    # Trim a trailing time component ("06/15/2018 12:00:00 AM" → "06/15/2018").
    return s.split(" ")[0] if " " in s else s
