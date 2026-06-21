"""
Hillsborough County (FL) HTTP Recorder Adapter — Phase 1 CURE.

Pure-Python HTTP adapter for the Hillsborough Clerk of Circuit Courts Official
Records portal at ``publicaccess.hillsclerk.com``. Unlike Broward (Cloudflare-
fronted), Hillsborough is plain Microsoft-IIS / ASP.NET — no anti-bot, no JS
challenge, no Cloudflare. A single JSON POST returns a structured ``ResultList``
that we map to ``DocumentRecord`` instances; the watermarked PDF for any
indexed instrument is then a single GET against the ``OverlayWatermark`` API.

Endpoints (verified 2026-05-26 against live portal):

  POST https://publicaccess.hillsclerk.com/Public/ORIUtilities/DocumentSearch/api/Search
    Body: ``{"PartyName":["FROMER MICHAEL"]}``
          or ``{"Instrument":[2025214758]}``
          or ``{"BookNum":"2411","PageNum":"752","BookType":"O"}``
          plus optional ``{"DocType":["(D) DEED"], "RecordDateFrom":"01/01/2010",
                            "RecordDateTo":"05/26/2026"}``
    Response: ``{"Success": true, "ResultList": [{...}], ...}``
    Row shape: ``Instrument`` (int), ``PartiesOne`` (list[str]),
              ``PartiesTwo`` (list[str]), ``RecordDate`` (Unix epoch seconds),
              ``DocType`` (``"(D) DEED"`` style), ``BookType`` (``"O"``),
              ``BookNum`` (int|null), ``PageNum`` (int|null),
              ``Legal`` (str), ``ID`` (opaque base64-ish), ``UUID``,
              ``PageCount`` (int)

  GET  https://publicaccess.hillsclerk.com/Public/ORIUtilities/OverlayWatermark/api/Watermark/{url_quoted_ID}
    Header: ``Referer: https://publicaccess.hillsclerk.com/oripublicaccess/``
    Returns watermarked PDF binary.

Design (mirrors ``acclaimweb_http_adapter.py``):
  * Subclasses ``BaseRecorderSearch`` so registry/factory plumbing is unchanged.
  * Driver/browser methods collapse to no-ops.
  * Stateless: every ``perform_search`` builds a fresh JSON payload.
  * Per Tony Roveda's directive #1: no Selenium, no Playwright, no
    undetected-chromedriver anywhere in this module.
  * ``pull_pdf(doc_id)`` bonus method — handy because Hillsborough doc IDs are
    opaque server-issued tokens (not the Instrument number), so the pipeline's
    download phase will need them. The recorder records the ID alongside each
    DocumentRecord via the ``hillsborough_id`` attribute (stashed on the dict).

Per Tony's deed-first directive (#2), callers should invoke ``perform_search``
with ``doc_type="DEED"`` first to find the vesting deed → NLP-extract the APN
→ optionally re-search by Book/Page or Instrument to map the chain of title.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# Default impersonation profile. Hillsborough has NO anti-bot (verified 2026-05-26
# via `curl -sI`: Server: Microsoft-IIS/10.0, no cf-ray), so any profile passes.
# chrome120 mirrors what the co-developer's `urllib.request` UA string conveyed,
# and keeps parity with the Grant Street tax adapter.
DEFAULT_IMPERSONATE = "chrome120"

# Reasonable default request headers. ``Referer`` is mandatory ONLY for the
# OverlayWatermark PDF endpoint (verified 2026-05-26 — fetching without
# Referer returns 200 with an empty body); we set it on the session so it
# applies to every subsequent GET/POST without per-call repetition.
DEFAULT_REFERER = "https://publicaccess.hillsclerk.com/oripublicaccess/"


class HillsboroughHTTPAdapter(BaseRecorderSearch):
    """Pure-HTTP recorder adapter for Hillsborough County, FL.

    Uses the Hillsborough Clerk's documented ``/api/Search`` and
    ``/api/Watermark/{id}`` REST endpoints. No browser, no anti-bot bypass.
    """

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        config: Dict[str, Any],
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Hillsborough")
        self._base_url = config.get(
            "base_url",
            "https://publicaccess.hillsclerk.com/oripublicaccess/",
        ).rstrip("/") + "/"
        self._search_url = config.get("search_url", self._base_url)
        self._http_search_endpoint = config.get(
            "http_search_endpoint",
            "https://publicaccess.hillsclerk.com/Public/ORIUtilities/DocumentSearch/api/Search",
        )
        self._pdf_endpoint_template = config.get(
            "http_pdf_endpoint_template",
            "https://publicaccess.hillsclerk.com/Public/ORIUtilities/OverlayWatermark/api/Watermark/{id}",
        )

        ff = config.get("http_form_fields", {})
        self._field_name = ff.get("name", "PartyName")
        self._field_doc_type = ff.get("doc_type", "DocType")
        self._field_date_from = ff.get("date_from", "RecordDateFrom")
        self._field_date_to = ff.get("date_to", "RecordDateTo")
        self._field_instrument = ff.get("instrument", "Instrument")
        self._field_book_num = ff.get("book_num", "BookNum")
        self._field_page_num = ff.get("page_num", "PageNum")
        self._field_book_type = ff.get("book_type", "BookType")

        # Doc-type label → Hillsborough code. Hillsborough returns labels like
        # ``"(D) DEED"`` and ``"(MTG) MORTGAGE"``. Filtering accepts the SAME
        # parenthesized form. Allow callers to pass semantic names ("DEED",
        # "MORTGAGE") and translate.
        self.doc_type_map = config.get(
            "doc_type_map",
            {
                "DEED": "(D) DEED",
                "MORTGAGE": "(MTG) MORTGAGE",
                "MTG": "(MTG) MORTGAGE",
                "SATISFACTION": "(SAT) SATISFACTION",
                "SAT": "(SAT) SATISFACTION",
                "RELEASE": "(REL) RELEASE",
                "DISCHARGE": "(DIS) DISCHARGE",
                "AGREEMENT": "(AGR) AGREEMENT",
                "MODIFICATION": "(MOD) MODIFICATION",
            },
        )
        self._doctype_deed_value = config.get("doctype_deed_value", "(D) DEED")

        # Party-type mapping: Hillsborough's /api/Search does NOT split party
        # filtering at the endpoint level — every query returns parties on
        # both sides (PartiesOne / PartiesTwo) and the caller can post-filter.
        # We honor party_type semantically for parity with the pipeline (the
        # county is registered as ``combined_name_search`` so the search-phase
        # loop collapses to one call per name and tags every party_type
        # downstream).
        self.party_type_map = config.get(
            "party_type_map",
            {
                "Grantor": "All",
                "Grantee": "All",
                "Grantor/Grantee": "All",
                "Both": "All",
                "All": "All",
            },
        )
        self.supported_party_types = config.get(
            "supported_party_types", ["All", "Grantor", "Grantee", "Grantor/Grantee"]
        )

        # Doc-number regex (Hillsborough Instrument is a 10-digit number like
        # 2026161803, or a legacy 8-digit like 90018829).
        self._doc_number_re = re.compile(
            config.get("doc_number_pattern", r"^\d{7,12}$")
        )

        # HTTP session
        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(
            {
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": config.get("http_referer", DEFAULT_REFERER),
            }
        )

        # Caches the opaque server IDs for each Instrument we've seen — so a
        # downstream downloader can request the PDF without re-issuing the
        # search. Populated by every ``perform_search`` call.
        # ``_doc_id_by_number`` is the canonical name the pipeline's
        # ``recorder_internal_ids.json`` sidecar rehydrates (see Tyler
        # adapter / pipeline._download_via_adapter). ``_id_cache`` is kept
        # as a back-compat alias for older callers / tests.
        self._doc_id_by_number: Dict[str, str] = {}
        self._id_cache: Dict[str, str] = self._doc_id_by_number
        # Same for UUID (useful as a doc-detail key).
        self._uuid_cache: Dict[str, str] = {}

        # Recipe-style doc-image URL config (mirrors Tyler / Broward). Tokens:
        #   {id} → the opaque, URL-encoded server ID cached during search.
        pattern_cfg = config.get("doc_image_url_pattern", {})
        self._dip_pdf_url_template = pattern_cfg.get(
            "pdf_url_template",
            self._pdf_endpoint_template,
        )
        # PDF magic-bytes check is the only validation Hillsborough needs;
        # the response is a flat PDF on success. Configurable for parity.
        self._dip_assert_pdf_magic = bool(pattern_cfg.get("assert_pdf_magic", True))

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
        """Bootstrap the session.

        Hillsborough's IIS portal has no disclaimer, no CSRF token, no
        cookies — a single GET on the landing page is sufficient to confirm
        connectivity. We do that and mark the session warmed.

        Extra args are ignored for API parity with the AcclaimWeb adapter
        (which accepts ``browser_minted_cookies`` and ``cookie_jar_path``).
        """
        if self._session_warmed:
            return True
        try:
            resp = self.session.get(self._base_url, timeout=30)
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
        """Pure-HTTP name search.

        Hillsborough name format per Tony's notes + co-developer's reference:
        ``"FROMER MICHAEL"`` (Last First, no comma). We pre-normalize a
        ``"LAST, FIRST"`` input to ``"LAST FIRST"`` so callers that follow the
        AcclaimWeb convention work transparently.
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] session warm-up failed; "
                    f"last_failure={self.last_failure}"
                )
                return []

        normalized = self._normalize_name(name)

        # party_type is recorded but not sent — Hillsborough doesn't split.
        mapped_party = self.party_type_map.get(party_type, "All")
        if mapped_party not in {"All", "Grantor", "Grantee", "Grantor/Grantee"}:
            mapped_party = "All"

        payload: Dict[str, Any] = {self._field_name: [normalized]}

        if doc_type:
            dt_key = doc_type.strip().upper()
            payload[self._field_doc_type] = [self.doc_type_map.get(dt_key, doc_type)]

        df = date_from or self.start_date
        dt = date_to or self.end_date
        if df:
            payload[self._field_date_from] = df
        if dt:
            payload[self._field_date_to] = dt

        try:
            resp = self.session.post(
                self._http_search_endpoint,
                data=json.dumps(payload),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=60,
            )
        except Exception as exc:
            print(f"  [perform_search] HTTP error: {exc}")
            self.last_failure = f"http_error: {exc}"
            return []

        if resp.status_code != 200:
            print(f"  [perform_search] HTTP {resp.status_code} from /api/Search")
            self.last_failure = f"http_{resp.status_code}"
            return []

        try:
            data = resp.json()
        except Exception as exc:
            print(f"  [perform_search] JSON decode failed: {exc}")
            self.last_failure = f"json_decode: {exc}"
            return []

        if not data.get("Success", True):
            print(
                f"  [perform_search] API reported error: "
                f"{data.get('ErrorMessage', 'unknown')}"
            )

        rows = data.get("ResultList") or []
        documents = self._rows_to_documents(rows)

        # Optional party_type post-filter: if caller asked for Grantor /
        # Grantee specifically (not All / Both), drop rows where the searched
        # name is NOT in the requested party-side list. This keeps the
        # pipeline's per-party-type accounting honest even though the API
        # itself is combined.
        if party_type in {"Grantor", "Grantee"}:
            documents = self._filter_by_party_side(documents, rows, normalized, party_type)

        return documents

    def _rows_to_documents(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        """Map JSON rows from Hillsborough's API to DocumentRecord objects."""
        documents: List[DocumentRecord] = []
        for row in rows:
            inst = row.get("Instrument")
            if inst is None:
                continue
            doc_num = str(inst)
            grantors = "; ".join(row.get("PartiesOne") or [])
            grantees = "; ".join(row.get("PartiesTwo") or [])
            doc_type = row.get("DocType", "") or ""
            rec_date = self._epoch_to_mmddyyyy(row.get("RecordDate"))
            pages = str(row.get("PageCount") or "")

            # Cache the opaque ID + UUID so a downloader / detail-puller can
            # use them without re-issuing the search. ``_id_cache`` aliases
            # ``_doc_id_by_number`` (see __init__) so this single write
            # populates both names + the pipeline sidecar key in one shot.
            if row.get("ID"):
                self._doc_id_by_number[doc_num] = row["ID"]
            if row.get("UUID"):
                self._uuid_cache[doc_num] = row["UUID"]

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
                    pages=pages,
                )
            )
        return documents

    @staticmethod
    def _filter_by_party_side(
        documents: List[DocumentRecord],
        rows: List[Dict[str, Any]],
        searched_name: str,
        side: str,
    ) -> List[DocumentRecord]:
        """Drop rows where the searched name is NOT in the requested side."""
        wanted_field = "PartiesOne" if side == "Grantor" else "PartiesTwo"
        keep_inst: set[str] = set()
        upper_search = searched_name.upper()
        for row in rows:
            inst = row.get("Instrument")
            if inst is None:
                continue
            parties = row.get(wanted_field) or []
            joined = " ".join(p.upper() for p in parties)
            # Substring match: tokens of the search name should all appear in
            # ANY single party string. (Hillsborough stores "FROMER MICHAEL A"
            # while the search was "FROMER MICHAEL".)
            tokens = [t for t in re.split(r"\s+", upper_search) if t]
            for party in parties:
                pu = party.upper()
                if all(tok in pu for tok in tokens):
                    keep_inst.add(str(inst))
                    break
        return [d for d in documents if d.document_number in keep_inst]

    # ------------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str) -> Dict[str, Any]:
        """Re-fetch a single document by its Instrument number.

        Hillsborough has no separate "detail page" — the search response IS
        the detail. We re-issue an Instrument-keyed search and return the
        single row as a dict.
        """
        if not self._session_warmed:
            self.warm_session()

        try:
            inst_int = int(doc_num)
        except ValueError:
            return {"document_number": doc_num, "error": "non-integer Instrument"}

        try:
            resp = self.session.post(
                self._http_search_endpoint,
                data=json.dumps({self._field_instrument: [inst_int]}),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=45,
            )
        except Exception as exc:
            return {"document_number": doc_num, "error": f"network: {exc}"}

        if resp.status_code != 200:
            return {"document_number": doc_num, "error": f"HTTP {resp.status_code}"}

        try:
            data = resp.json()
        except Exception as exc:
            return {"document_number": doc_num, "error": f"json_decode: {exc}"}

        rows = data.get("ResultList") or []
        if not rows:
            return {"document_number": doc_num, "error": "no result"}

        row = rows[0]
        # Cache the doc ID for the downloader (``_id_cache`` aliases
        # ``_doc_id_by_number`` so this one write populates both names).
        if row.get("ID"):
            self._doc_id_by_number[doc_num] = row["ID"]
        if row.get("UUID"):
            self._uuid_cache[doc_num] = row["UUID"]

        # Build indexed APN from Book/Page if present (Hillsborough's "indexed
        # APN" surrogate; the real folio comes from HCPA Property Appraiser
        # lookups handled elsewhere).
        book = row.get("BookNum")
        page = row.get("PageNum")
        book_type = row.get("BookType") or ""
        book_page = (
            f"{book_type} BK {book} PG {page}"
            if book and page
            else ""
        )

        parties: List[Dict[str, str]] = []
        for p in row.get("PartiesOne") or []:
            parties.append({"role": "Grantor", "name": p})
        for p in row.get("PartiesTwo") or []:
            parties.append({"role": "Grantee", "name": p})

        return {
            "document_number": doc_num,
            "instrument": row.get("Instrument"),
            "recording_date": self._epoch_to_mmddyyyy(row.get("RecordDate")),
            "doc_type": row.get("DocType", ""),
            "indexed_apn": "",  # not present in Clerk index; use HCPA folio
            "book_page": book_page,
            "legal": row.get("Legal", ""),
            "parties": parties,
            "id": row.get("ID", ""),
            "uuid": row.get("UUID", ""),
            "page_count": row.get("PageCount"),
        }

    # --------------------------------------------------------------- pull_pdf

    def _resolve_doc_id(self, doc_num: str) -> Optional[str]:
        """Resolve the opaque Hillsborough server ID for an Instrument.

        Order of lookup:
          1. ``_doc_id_by_number`` (canonical cache; pipeline sidecar
             populates this on rehydrate, ``perform_search`` populates it
             in-process).
          2. ``_id_cache`` (back-compat alias — kept defensively in case a
             test or external caller writes to it directly and the alias
             link was broken by reassignment).
        Returns the ID string, or None if not cached anywhere.
        """
        if doc_num in self._doc_id_by_number:
            return self._doc_id_by_number[doc_num]
        if self._id_cache is not self._doc_id_by_number and doc_num in self._id_cache:
            return self._id_cache[doc_num]
        return None

    def download_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Direct-portal PDF download — canonical pipeline entry point.

        Mirrors the Tyler ``download_pdf`` contract. Returns:

        Success: ``{"status": "success", "size": int, "src_via": str,
                    "pdf_url": str, "doc": str, "file": str}``
        Failure: ``{"status": "error", "doc": str, "message": str,
                    "pdf_url"?: str}``

        Flow:
          1. Resolve opaque server ID from cache (``perform_search`` /
             ``pull_detail`` populate it; pipeline's
             ``recorder_internal_ids.json`` rehydrate also populates it).
          2. If not cached, re-issue ``pull_detail`` to refresh it.
          3. GET ``self._dip_pdf_url_template.format(id=quote(doc_id))``
             with the session's default Referer.
          4. Validate ``%PDF`` magic bytes (if configured), write to disk.
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
            # Fall back to a re-issued search by Instrument.
            detail = self.pull_detail(doc_num)
            if "error" in detail:
                return {
                    "status": "error",
                    "doc": doc_num,
                    "message": detail["error"],
                }
            doc_id = self._resolve_doc_id(doc_num)
        if not doc_id:
            return {
                "status": "error",
                "doc": doc_num,
                "message": "no opaque document ID available (search cache empty + pull_detail returned no ID)",
            }

        url = self._dip_pdf_url_template.format(
            id=urllib.parse.quote(doc_id, safe="")
        )
        try:
            resp = self.session.get(url, timeout=120)
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
            "src_via": "watermark_api",
            "pdf_url": url,
            # legacy alias retained for any pre-existing callers.
            "url": url,
        }

    # Back-compat alias — older callers / tests invoked ``pull_pdf``. The
    # canonical pipeline entry point is ``download_pdf``.
    def pull_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Deprecated alias for :meth:`download_pdf` — kept for back-compat."""
        return self.download_pdf(doc_num, dest_path)

    # ----------------------------------------------------------- extract_results

    def extract_results(self, payload: Any = None) -> List[DocumentRecord]:
        """Parse a ResultList payload into DocumentRecord rows.

        Accepts either:
          * the raw JSON string body of an /api/Search response,
          * the decoded dict ``{"ResultList": [...]}``,
          * the inner list directly,
          * or an HTML fragment (back-compat with the AcclaimWeb-style API;
            the JSON shape is the canonical one for Hillsborough).
        """
        if payload is None:
            return []
        # JSON string
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            stripped = payload.strip()
            if not stripped:
                return []
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    payload = json.loads(stripped)
                except Exception:
                    return self._extract_results_from_html(stripped)
            else:
                return self._extract_results_from_html(stripped)

        if isinstance(payload, dict):
            rows = payload.get("ResultList") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            return []
        return self._rows_to_documents(rows)

    @staticmethod
    def _extract_results_from_html(html: str) -> List[DocumentRecord]:
        """Fallback HTML grid parser — only used if the portal ever switches
        from JSON back to a grid. Current portal returns JSON exclusively.
        """
        documents: List[DocumentRecord] = []
        if not html:
            return documents
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("tr.jsgrid-row, tr.jsgrid-alt-row, tbody tr")
        seen: set[str] = set()
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            # First cell usually holds the doc number (Hillsborough Instrument
            # is 7-12 digits).
            doc_num = ""
            for c in cells:
                if re.match(r"^\d{7,12}$", c):
                    doc_num = c
                    break
            if not doc_num or doc_num in seen:
                continue
            seen.add(doc_num)
            documents.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=cells[1] if len(cells) > 1 else "",
                    grantees=cells[2] if len(cells) > 2 else "",
                    grantor_grantees=";".join(cells[1:3]),
                    document_type=cells[3] if len(cells) > 3 else "",
                    recording_date=cells[4] if len(cells) > 4 else "",
                    pages=cells[5] if len(cells) > 5 else "",
                )
            )
        return documents

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Accept "LAST, FIRST" or "LAST FIRST"; emit "LAST FIRST" (uppercase).

        Hillsborough's /api/Search expects ``"FROMER MICHAEL"`` (space-
        delimited, last-first). Per Tony's hint: "Enter Last name first name".
        """
        s = (name or "").strip()
        if not s:
            return ""
        if "," in s:
            parts = [p.strip() for p in s.split(",", 1)]
            s = f"{parts[0]} {parts[1]}".strip()
        # Collapse internal whitespace + uppercase
        s = re.sub(r"\s+", " ", s).upper()
        return s

    @staticmethod
    def _epoch_to_mmddyyyy(epoch: Any) -> str:
        """Hillsborough's RecordDate is Unix epoch seconds. Convert to MM/DD/YYYY."""
        if epoch is None:
            return ""
        try:
            dt = datetime.utcfromtimestamp(int(epoch))
            return dt.strftime("%m/%d/%Y")
        except Exception:
            return str(epoch)


__all__ = ["HillsboroughHTTPAdapter"]
