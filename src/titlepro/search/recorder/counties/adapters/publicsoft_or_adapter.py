"""PublicSoft "BrowserView OR" — HTTP-First Recorder Adapter.

Pure-Python (``curl_cffi`` + ``cryptography``) adapter for the PublicSoft /
Kofile **BrowserView** official-records platform. First production target is
**Polk County, FL** (``apps.polkcountyclerk.net/browserviewor/``); the same code
path should unlock other PublicSoft BrowserView counties with a per-county JSON
config swap.

Platform fingerprints (reverse-engineered 2026-06-10 from the SPA's archived JS
bundle — the live host ``apps.polkcountyclerk.net`` is firewall/geo-fenced and
was TCP-unreachable from the build egress; see
``.../Polk_BUNKER_v1/phase0_probe_recorder.md``):

* AngularJS 1.x SPA: ``angular.module('Main', ['agGrid','ui.bootstrap',
  'checklist-model'])`` with ``MainController`` / ``searchcontroller`` /
  ``resultscontroller`` / ``documentcontroller`` / ``documentService``.
* Tenant config: ``GET api/search/clientinfo`` → ``{name, logo, description,
  encryptData, showParty, showBookPage, verifyDate, authentication, ...}``.
* **Field-level RSA encryption**: when ``clientinfo.encryptData`` is truthy
  (PublicSoft default), every user-supplied criterion value is RSA **PKCS#1 v1.5**
  encrypted client-side (JSEncrypt) with a hard-coded 1024-bit public key and
  base64-encoded. Integer fields get a leading space prepended before encryption,
  and are encrypted only when ``> 0``.
* Name search: ``POST api/search`` with ``{Party, DocTypes, FromDate, ToDate,
  MaxRows, RowsPerPage, StartRow}`` (each value encrypted when encryptData).
  Dates are ``YYYYMMDD`` (compact) BEFORE encryption.
* Response: JSON array of row dicts; row[0] carries ``_total_rows`` /
  ``_start_row`` / ``_end_row`` / ``_max_rows`` / ``_IsUseSelectCount``.
* Direct retrieval: file# via ``{FileNumber}`` to ``api/search``; doc detail /
  image via ``POST api/document`` ``{ID|Book/PageNumber/BookType}``; server-side
  PDF via ``POST api/pdf`` ``{ID, StartPage, Pages}``.
* No reCAPTCHA, no disclaimer interstitial in the SPA flow — the only gate is the
  host firewall (a Wave-2 egress concern, not an adapter concern).

Design (mirrors ``landmark_adapter.py`` / ``hillsborough_http_adapter.py``):
  * Subclasses ``BaseRecorderSearch`` so registry plumbing is unchanged.
  * All Selenium/Playwright ABC methods collapse to no-ops (Tony directive #1).
  * URLs/field names/result-row mapping come from the JSON config — adding
    another PublicSoft BrowserView county is a config-only task.
  * Per Tony directive #2 (deed-first): call ``perform_search(name,
    doc_type="DEED")`` first, NLP-extract the APN from the vesting deed image,
    then re-search by parcel for completeness.

NOTE: per-row document field names could NOT be confirmed against the live host.
``result_field_map`` in the config provides PublicSoft-typical defaults with
tolerant multi-key fallback; **confirming the exact row keys is the #1 Wave-2
task** (capture one live ``api/search`` 200 body).
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# PublicSoft BrowserView is plain IIS/ASP.NET behind (for Polk) a host firewall;
# no Cloudflare challenge was observed. safari17_2_ios is the project default for
# FL hosts and is the safest fingerprint to lead with.
DEFAULT_IMPERSONATE = "safari17_2_ios"

# The 1024-bit RSA public key embedded in the BrowserView SPA's
# Scripts/app/services.js (Polk tenant, captured 2026-06-10). Overridable per
# county via config["rsa_public_key"] in case another tenant ships a different
# key.
_POLK_RSA_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDXBPCKXRqaD74rYrPXU/DA4Z5H"
    "mJbNivwCYijae6QXu/QLqS3GbyGrxkrEmdODbYWOLJfWBvaQSALcolSyKQUvtkjz"
    "g61bJC2/xNk4HTHFrA4uAMMvC+49RlSgtEm5dI10+YOp0TGId1d4E0Ey0RDQxNWa"
    "ev2TeleyipADuctnqwIDAQAB\n"
    "-----END PUBLIC KEY-----\n"
)

# PublicSoft-typical per-row field-name candidates. Each canonical key maps to an
# ordered list of candidate JSON keys; the first present (non-empty) wins. This is
# deliberately tolerant because the live row shape is unconfirmed.
_DEFAULT_RESULT_FIELD_MAP: Dict[str, List[str]] = {
    "document_number": ["doc_number", "document_number", "instrument", "instrument_number",
                         "file_number", "fileNumber", "docnumber", "DocumentNumber"],
    "grantors": ["grantor", "grantors", "direct_name", "party1", "from_party", "Grantor"],
    "grantees": ["grantee", "grantees", "reverse_name", "party2", "to_party", "Grantee"],
    "document_type": ["doc_type", "document_type", "doctype", "type", "DocType", "instrument_type"],
    "recording_date": ["record_date", "recording_date", "recorded_date", "rec_date",
                        "file_date", "RecordDate", "date_recorded"],
    "pages": ["pages", "page_count", "num_pages", "img_pg_cnt", "PageCount"],
    "book": ["book", "book_number", "Book"],
    "page": ["page", "page_number", "Page"],
    "book_type": ["book_type", "bookType", "BookType"],
    "legal": ["legal", "legal_desc", "legal_description", "Legal"],
    "doc_id": ["id", "doc_id", "document_id", "ID", "DocID", "RowID", "row_id"],
}

# Meta keys on row[0].
_META_TOTAL_ROWS = "_total_rows"
_META_START_ROW = "_start_row"
_META_END_ROW = "_end_row"
_META_MAX_ROWS = "_max_rows"


class PublicSoftORAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for the PublicSoft BrowserView OR platform."""

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        config: Dict[str, Any],
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Polk")
        self._base_url = config.get(
            "base_url", "https://apps.polkcountyclerk.net/browserviewor/"
        ).rstrip("/") + "/"
        # The SPA issues all api/* calls relative to the app root.
        self._api_root = (config.get("api_root") or self._base_url).rstrip("/") + "/"

        eps = config.get("publicsoft_endpoints", {})
        self._ep_clientinfo = eps.get("clientinfo", "api/search/clientinfo")
        self._ep_doctypes = eps.get("doctypes", "api/document/doctypes")
        self._ep_search = eps.get("search", "api/search")
        self._ep_document = eps.get("document", "api/document")
        self._ep_pdf = eps.get("pdf", "api/pdf")

        # Criterion field names in the api/search payload (per searchcontroller.js).
        ff = config.get("search_fields", {})
        self._field_party = ff.get("party", "Party")
        self._field_doctypes = ff.get("doc_types", "DocTypes")
        self._field_from_date = ff.get("from_date", "FromDate")
        self._field_to_date = ff.get("to_date", "ToDate")
        self._field_file_number = ff.get("file_number", "FileNumber")
        self._field_parcel = ff.get("parcel", "Parcel")
        self._field_max_rows = ff.get("max_rows", "MaxRows")
        self._field_rows_per_page = ff.get("rows_per_page", "RowsPerPage")
        self._field_start_row = ff.get("start_row", "StartRow")

        # Deed-first doc-type code. The exact code comes from api/document/doctypes
        # (Wave-2); "DEED" is the semantic default and is what we send until the
        # live doctype list is captured. Per-county overridable.
        self._doctype_deed_value = str(config.get("doctype_deed_value", "DEED"))
        self.doc_type_map = config.get("doc_type_map", {})

        # Result-row field mapping (tolerant). Config can override per-county.
        fm = dict(_DEFAULT_RESULT_FIELD_MAP)
        for k, v in (config.get("result_field_map") or {}).items():
            # allow a single string or a list in config
            fm[k] = [v] if isinstance(v, str) else list(v)
        self._result_field_map = fm

        # Result cap (StartRow/RowsPerPage/MaxRows). 0 => server default.
        self._max_rows = int(config.get("max_rows", 0) or 0)
        self._rows_per_page = int(config.get("rows_per_page", 0) or 0)

        # Date format the portal expects BEFORE encryption (compact YYYYMMDD).
        self._wire_date_format = config.get("wire_date_format", "%Y%m%d")

        # RSA encryption config.
        # encrypt_data: None => discover from clientinfo at warm time;
        #               True/False => force.
        self._encrypt_data_cfg = config.get("encrypt_data", None)
        self._encrypt_data: Optional[bool] = (
            None if self._encrypt_data_cfg is None else bool(self._encrypt_data_cfg)
        )
        self._rsa_public_key_pem = config.get("rsa_public_key", _POLK_RSA_PUBLIC_KEY)
        self._rsa_key = None  # lazy-loaded cryptography public-key object

        # Name format: "LAST FIRST" (PublicSoft convention).
        self._name_format = config.get("name_format", "last_first_no_comma")

        # Doc-number regex (Polk instrument numbers are typically the recording
        # sequence; tolerant default).
        self._doc_number_re = re.compile(config.get("doc_number_pattern", r"^[A-Za-z0-9\-]{4,}$"))

        # HTTP session.
        self._impersonate = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=self._impersonate)
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

        # Caches: doc_id by document_number for the downloader.
        self._doc_id_by_number: Dict[str, str] = {}

        self._session_warmed = False
        self._client_info: Dict[str, Any] = {}
        self.last_failure: Optional[str] = None

        # ABC compliance: parent expects self.driver — never used.
        self.driver = None

    # --------------------------------------------- BaseRecorderSearch props

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

    # ----------------------------------------------------------- RSA crypto

    def _get_rsa_key(self):
        if self._rsa_key is None:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            self._rsa_key = load_pem_public_key(self._rsa_public_key_pem.encode())
        return self._rsa_key

    def _encrypt_value(self, value: str) -> str:
        """Replicate JSEncrypt: RSA PKCS#1 v1.5, base64 output."""
        from cryptography.hazmat.primitives.asymmetric import padding
        ct = self._get_rsa_key().encrypt(str(value).encode("utf-8"), padding.PKCS1v15())
        return base64.b64encode(ct).decode("ascii")

    def _enc(self, value: str) -> str:
        """Encrypt a string field iff the tenant uses encryptData; else passthrough."""
        if self._encrypt_data:
            return self._encrypt_value(value)
        return str(value)

    def _enc_int(self, value: int) -> Any:
        """Encrypt an int field. Per documentService.Encrypt, ints get a leading
        space prepended; only encrypt when > 0 (0 is sent as the bare int)."""
        if value and value > 0:
            if self._encrypt_data:
                return self._encrypt_value(" " + str(value))
            return value
        return 0

    # ------------------------------------------------------ session warm-up

    def warm_session(self, *_args, **_kwargs) -> bool:
        """GET clientinfo to learn the tenant config (encryptData, verifyDate, ...).

        If the host is unreachable (the known Wave-1 egress block), this fails
        soft and records ``last_failure`` so the pipeline can branch to a manual
        checkpoint. When ``encrypt_data`` was forced via config we still mark the
        session warmed even if clientinfo is unreachable, so offline unit tests
        and fixture-driven runs work.
        """
        if self._session_warmed:
            return True
        url = self._api_root + self._ep_clientinfo
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                try:
                    self._client_info = resp.json() or {}
                except Exception:
                    self._client_info = {}
                if self._encrypt_data is None:
                    self._encrypt_data = _truthy(self._client_info.get("encryptData"))
                self._session_warmed = True
                return True
            self.last_failure = f"clientinfo_http_{resp.status_code}"
        except Exception as exc:
            self.last_failure = f"clientinfo_error: {exc}"

        # Host unreachable. If encryptData was forced via config we can still run
        # (fixtures / direct payloads); otherwise this is a hard block.
        if self._encrypt_data is not None:
            self._session_warmed = True
            return True
        return False

    # ----------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search against ``api/search`` (Party tab)."""
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] warm-up failed (host likely firewalled); "
                    f"last_failure={self.last_failure}"
                )
                return []

        payload = self.build_search_payload(
            name=name, doc_type=doc_type, date_from=date_from, date_to=date_to
        )
        rows = self._post_search(payload)
        if rows is None:
            return []
        return self._rows_to_documents(rows)

    def build_search_payload(
        self,
        name: Optional[str] = None,
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        file_number: Optional[str] = None,
        parcel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct an ``api/search`` JSON criteria dict (encrypted as needed).

        Pure function (no network) so it is fully unit-testable offline.
        """
        criteria: Dict[str, Any] = {}

        if file_number:
            criteria[self._field_file_number] = self._enc(file_number)
        elif parcel:
            criteria[self._field_parcel] = self._enc(parcel)
            criteria[self._field_party] = ""  # parcel tab sends empty Party
        else:
            normalized = self._normalize_name(name or "")
            criteria[self._field_party] = self._enc(normalized)

        # Deed-first: send a DocTypes filter when requested.
        if doc_type:
            dt_key = doc_type.strip().upper()
            mapped = self.doc_type_map.get(dt_key, self._doctype_deed_value
                                           if dt_key == "DEED" else doc_type)
            criteria[self._field_doctypes] = self._enc(mapped)

        df = self._to_wire_date(date_from or self.start_date)
        dt = self._to_wire_date(date_to or self.end_date)
        if df:
            criteria[self._field_from_date] = self._enc(df)
        if dt:
            criteria[self._field_to_date] = self._enc(dt)

        criteria[self._field_max_rows] = self._enc_int(self._max_rows)
        criteria[self._field_rows_per_page] = self._enc_int(self._rows_per_page)
        criteria[self._field_start_row] = self._enc_int(0)
        return criteria

    def _post_search(self, payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        url = self._api_root + self._ep_search
        try:
            resp = self.session.post(
                url,
                data=json.dumps(payload),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=60,
            )
        except Exception as exc:
            self.last_failure = f"search_http_error: {exc}"
            print(f"  [perform_search] HTTP error: {exc}")
            return None
        if resp.status_code != 200:
            self.last_failure = f"search_http_{resp.status_code}"
            print(f"  [perform_search] HTTP {resp.status_code} from api/search")
            return None
        try:
            data = resp.json()
        except Exception as exc:
            self.last_failure = f"search_json_decode: {exc}"
            return None
        if not isinstance(data, list):
            self.last_failure = "search_unexpected_shape"
            return []
        return data

    # ----------------------------------------------------- row → DocumentRecord

    def parse_search_results(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        """Public alias — map raw api/search rows to DocumentRecords (offline-testable)."""
        return self._rows_to_documents(rows)

    def _rows_to_documents(self, rows: List[Dict[str, Any]]) -> List[DocumentRecord]:
        documents: List[DocumentRecord] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            doc_num = self._pick(row, "document_number")
            if not doc_num:
                # Skip pure-meta or unusable rows but keep going.
                continue
            grantors = self._pick(row, "grantors")
            grantees = self._pick(row, "grantees")
            doc_type = self._pick(row, "document_type")
            rec_date = self._normalize_date_out(self._pick(row, "recording_date"))
            pages = self._pick(row, "pages")

            # PublicSoft (Polk) returns one matched party per row as a combined
            # ``party_name`` plus a ``party_code`` (D = Direct/grantor,
            # R = Reverse/grantee). When both grantor/grantee map to the same
            # ``party_name``, use the code to place the name on the correct side
            # so the index role is not lost; the counterparty is filled from the
            # deed image downstream.
            party_code = str(row.get("party_code") or "").strip().upper()
            if grantors and grantees and grantors == grantees and party_code in ("D", "R"):
                if party_code == "D":
                    grantees = ""
                else:
                    grantors = ""

            doc_id = self._pick(row, "doc_id")
            if doc_id:
                self._doc_id_by_number[str(doc_num)] = str(doc_id)

            documents.append(
                DocumentRecord(
                    document_number=str(doc_num),
                    grantors=str(grantors or ""),
                    grantees=str(grantees or ""),
                    grantor_grantees="; ".join(
                        s for s in [str(grantors or ""), str(grantees or "")] if s
                    ),
                    document_type=str(doc_type or ""),
                    recording_date=str(rec_date or ""),
                    pages=str(pages or ""),
                )
            )
        return documents

    @staticmethod
    def search_meta(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pull pagination meta from row[0] (the `[N,0,0,...]` contamination guard
        upstream reads `_total_rows`)."""
        if not rows or not isinstance(rows[0], dict):
            return {}
        r0 = rows[0]
        return {
            "total_rows": r0.get(_META_TOTAL_ROWS),
            "start_row": r0.get(_META_START_ROW),
            "end_row": r0.get(_META_END_ROW),
            "max_rows": r0.get(_META_MAX_ROWS),
        }

    def _pick(self, row: Dict[str, Any], canonical: str) -> Any:
        for key in self._result_field_map.get(canonical, []):
            if key in row and row[key] not in (None, ""):
                return row[key]
        return ""

    # ----------------------------------------------------- direct retrieval

    def build_document_detail_payload(
        self,
        doc_id: Optional[str] = None,
        book: Optional[str] = None,
        page: Optional[str] = None,
        book_type: Optional[str] = None,
        page_number: int = 1,
        convert: bool = True,
    ) -> Dict[str, Any]:
        """Construct an ``api/document`` payload (offline-testable).

        Per documentcontroller.js: ID path uses ``Encrypt(' '+id)``; Book/Page
        path uses ``Encrypt(' '+book)`` / ``Encrypt(' '+page)`` /
        ``Encrypt(' '+bookType)``; ``Page`` is the 1-based page index.
        """
        criteria: Dict[str, Any] = {}
        if convert:
            criteria["Convert"] = True
        if doc_id:
            criteria["ID"] = self._enc(" " + str(doc_id))
        elif book and page and book_type:
            criteria["Book"] = self._enc(" " + str(book))
            criteria["PageNumber"] = self._enc(" " + str(page))
            criteria["BookType"] = self._enc(" " + str(book_type))
        if page_number:
            criteria["Page"] = self._enc(str(page_number))
        return criteria

    def build_pdf_payload(self, doc_id: str, start_page: int = 1, pages: int = 1) -> Dict[str, Any]:
        """Construct an ``api/pdf`` payload (offline-testable)."""
        criteria: Dict[str, Any] = {"ID": self._enc(" " + str(doc_id))}
        criteria["StartPage"] = self._enc_int(start_page) if start_page > 0 else " 1"
        criteria["Pages"] = self._enc_int(pages) if pages > 0 else " 1"
        criteria["CurrentPage"] = criteria["StartPage"]
        return criteria

    def pull_pdf(self, doc_id: str, start_page: int = 1, pages: int = 1) -> Optional[bytes]:
        """Fetch a document PDF via ``api/pdf``. Returns raw bytes or None."""
        if not self._session_warmed and not self.warm_session():
            return None
        url = self._api_root + self._ep_pdf
        payload = self.build_pdf_payload(doc_id, start_page, pages)
        try:
            resp = self.session.post(
                url, data=json.dumps(payload),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=120,
            )
        except Exception as exc:
            self.last_failure = f"pdf_http_error: {exc}"
            return None
        if resp.status_code != 200:
            self.last_failure = f"pdf_http_{resp.status_code}"
            return None
        return resp.content

    def download_pdf(self, doc_num: str, dest_path, pages: int = 50) -> Dict[str, Any]:
        """Pipeline download contract: resolve ``doc_num`` → internal doc_id and
        write the server-rendered PDF to ``dest_path``.

        The download phase builds a fresh adapter and restores ``_doc_id_by_number``
        from ``recorder_internal_ids.json`` (written by the search phase). If the
        id is missing we fall back to a one-shot FileNumber search to learn it.
        ``pages`` is a generous upper bound — api/pdf returns the full document.
        """
        from pathlib import Path as _Path
        dest = _Path(dest_path)
        doc_id = self._doc_id_by_number.get(str(doc_num))
        if not doc_id:
            # Fall back: a FileNumber search populates the id cache as a side effect.
            try:
                rows = self._post_search(self.build_search_payload(file_number=str(doc_num)))
                self._rows_to_documents(rows or [])
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": f"file_number lookup raised {exc}"}
            doc_id = self._doc_id_by_number.get(str(doc_num))
        if not doc_id:
            return {"status": "error",
                    "message": f"no internal doc_id for document_number {doc_num}"}
        pdf = self.pull_pdf(str(doc_id), start_page=1, pages=pages)
        if not pdf or pdf[:4] != b"%PDF":
            head = pdf[:80] if pdf else None
            return {"status": "error",
                    "message": f"pull_pdf failed (last_failure={self.last_failure}, head={head!r})"}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pdf)
        return {"status": "success", "size": len(pdf), "src_via": "publicsoft_api_pdf"}

    # ----------------------------------------------------- abstract extract

    def extract_results(self) -> List[DocumentRecord]:
        """HTTP adapter returns results directly from perform_search; nothing to
        scrape from a page. Kept for ABC compliance."""
        return []

    # ----------------------------------------------------------- helpers

    def _normalize_name(self, name: str) -> str:
        """Normalize to PublicSoft 'LAST FIRST' (no comma)."""
        n = (name or "").strip()
        if not n:
            return n
        if "," in n:
            last, first = n.split(",", 1)
            n = f"{last.strip()} {first.strip()}".strip()
        return re.sub(r"\s+", " ", n).upper()

    def _to_wire_date(self, mmddyyyy: Optional[str]) -> str:
        """MM/DD/YYYY (project convention) → YYYYMMDD (portal wire format)."""
        if not mmddyyyy:
            return ""
        s = str(mmddyyyy).strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).strftime(self._wire_date_format)
            except ValueError:
                continue
        return ""

    @staticmethod
    def _normalize_date_out(value: Any) -> str:
        """Normalize a recording date to MM/DD/YYYY for DocumentRecord."""
        if not value:
            return ""
        s = str(value).strip()
        # ISO timestamps from PublicSoft moment fields, or compact YYYYMMDD.
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(s[:len(fmt) + 2] if "T" in fmt else s, fmt).strftime("%m/%d/%Y")
            except ValueError:
                continue
        # moment "M/D/YYYY"-ish — last-ditch: return as-is.
        return s


def _truthy(item: Any) -> bool:
    """Mirror documentService.convertToBool for the encryptData flag."""
    if item in (None, ""):
        return False
    if item is True:
        return True
    if item is False:
        return False
    if isinstance(item, str):
        return item.strip().upper() in {"Y", "A", "1", "T", "TRUE"}
    return bool(item)
