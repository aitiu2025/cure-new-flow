"""Broward County Property Appraiser HTTP adapter (Phase 1a anchor).

Implementation derived from the 2026-05-26 probe (see /tmp/bcpa_probe.md):
the BCPA SPA at web.bcpa.net/bcpaclient/ is backed by ASP.NET WebMethod
endpoints at search.aspx/<method>. Returns are wrapped in `{"d": ...}`.

Critical endpoints used here:
  - GetAutoCompleteDataBySiteAddress   →  canonical indexed address form
  - GetDataBySiteAddress               →  address → list of folios
  - getParcelInformationData           →  folio → full parcel + 5-deep sale history
                                          (saleDate1..5, deedType1..5, bookAndPageOrCin1..5)

Tony Roveda 2026-05-26: this adapter delivers the BACK-CHAIN that name-only
recorder searches can't recover. For ANAND it surfaces the Regent Bank
Certificate of Title (03/16/2011, Book 47826/Page 836); for SIMMONS it
surfaces the Sai Chhaya acquisition (instr 112404453, 07/07/2014).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"
_JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}

# BCPA returns a trailing sentinel row with folioNumber="1" to mark end-of-list.
_SENTINEL_FOLIO = "1"


class BrowardBCPA(AbstractPropertyAppraiser):
    """ASP.NET WebMethod adapter for Broward County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_broward"
        self.county_name = "Broward"
        self.source_label = config.get(
            "description", "Broward County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._warmup_url = config.get(
            "warmup_url", "https://web.bcpa.net/bcpaclient/searchsub.aspx"
        )
        self._url_autocomplete = endpoints.get(
            "autocomplete_address",
            "https://web.bcpa.net/bcpaclient/search.aspx/GetAutoCompleteDataBySiteAddress",
        )
        self._url_search_addr = endpoints.get(
            "search_by_address",
            "https://web.bcpa.net/bcpaclient/search.aspx/GetDataBySiteAddress",
        )
        self._url_search_owner = endpoints.get(
            "search_by_owner",
            "https://web.bcpa.net/bcpaclient/search.aspx/GetDataByOwnerNamesByCity",
        )
        self._url_parcel = endpoints.get(
            "parcel_info",
            "https://web.bcpa.net/bcpaclient/search.aspx/getParcelInformationData",
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)
        self._tax_year = str(config.get("tax_year") or (datetime.now().year - 1))

        # Sessions are created lazily so unit tests can inject mocks via
        # `adapter.session = MagicMock()` before any HTTP call.
        self._session: Optional[Any] = None
        self._warmed = False

    # ----------------------------------------------------------- session

    @property
    def session(self):
        if self._session is None:
            self._session = _cffi_requests.Session(impersonate=self._impersonate)
        return self._session

    @session.setter
    def session(self, value):
        self._session = value
        # Resetting the session invalidates any warm-up cookies.
        self._warmed = False

    def _warm(self) -> None:
        if self._warmed:
            return
        try:
            self.session.get(self._warmup_url, timeout=30)
        except Exception:
            # warm-up is best-effort — main calls will still try and either
            # succeed (BCPA often doesn't require the cookie) or surface the
            # underlying error.
            pass
        self._warmed = True

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._warm()
        resp = self.session.post(
            url, json=payload, headers=_JSON_HEADERS, timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"BCPA {url} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """Strip city/state/zip + ordinal suffixes so the BCPA autocomplete
        will find the canonical indexed form.

        Examples:
          "2856 NE 27TH ST, FORT LAUDERDALE, FL 33306"   → "2856 NE 27 ST"
          "2151 NW 93rd Ave, Pembroke Pines, FL"         → "2151 NW 93 AVE"
        """
        addr = address.upper()
        # Drop everything after the first comma (city, state, zip).
        addr = addr.split(",", 1)[0].strip()
        # Drop ordinal suffixes: "27TH" → "27", "93RD" → "93", "1ST" → "1".
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        # Collapse multiple spaces.
        addr = re.sub(r"\s+", " ", addr)
        return addr.strip()

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """BCPA folio is unhyphenated 12-digit numeric."""
        return re.sub(r"[^0-9]", "", apn or "")

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        # Step 1: autocomplete → canonical indexed form (best-effort).
        canonical = norm
        try:
            ac_resp = self._post_json(self._url_autocomplete, {"siteAddress": norm})
            ac_list = ac_resp.get("d") or []
            if ac_list:
                # Pick the first one whose start matches our normalized input.
                preferred = next(
                    (s for s in ac_list if s.upper().startswith(norm)), ac_list[0]
                )
                # The BCPA indexed form is "<street>, <city>"; the search
                # endpoint only takes the street portion.
                canonical = preferred.split(",", 1)[0].strip()
        except Exception as exc:
            # If autocomplete fails we still try the main search with the
            # normalized input.
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"autocomplete error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        # Step 2: address → folios.
        try:
            results = self._post_json(
                self._url_search_addr,
                {
                    "startAddress": canonical,
                    "order": "0",
                    "pageNum": "1",
                    "pageCount": "20",
                },
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        rows = [r for r in (results.get("d") or []) if r.get("folioNumber") and r["folioNumber"] != _SENTINEL_FOLIO]
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"BCPA found no parcel matching address {canonical!r}",
                fetched_at=datetime.now().isoformat(),
            )
        # Prefer an exact street-match (case-insensitive) over fuzzy.
        exact = [r for r in rows if r.get("siteAddress1", "").strip().upper() == canonical.upper()]
        if not exact and len(rows) > 1:
            # Ambiguous — surface to caller for resolution.
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"BCPA returned {len(rows)} candidates for {canonical!r}: "
                    + "; ".join(
                        f"{r.get('siteAddress1','?')} (folio {r.get('folioNumber','?')})"
                        for r in rows[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        chosen = (exact or rows)[0]
        return self.lookup_by_apn(chosen["folioNumber"])

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        folio = self._normalize_apn(apn)
        if not folio:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            data = self._post_json(
                self._url_parcel,
                {"folioNumber": folio, "taxyear": self._tax_year},
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"parcelInfo error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        rows = data.get("d") or []
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"BCPA returned empty parcel for folio={folio!r}",
                apn=folio,
                folio=folio,
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_parcel(rows[0])

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Owner search requires a city — without one the portal asks the user
        # to pick. We return [] rather than guessing — diagnostics-only API.
        return []

    # ----------------------------------------------------------- parse

    def _parse_parcel(self, p: Dict[str, Any]) -> PropertyAppraiserResult:
        folio = (p.get("folioNumber") or "").strip()
        result = PropertyAppraiserResult(
            apn=folio,
            folio=folio,
            owner_of_record=(p.get("ownerName1") or "").strip(),
            co_owners=[s.strip() for s in [p.get("ownerName2")] if s and s.strip()],
            situs_address=", ".join(
                s.strip() for s in [p.get("mailingAddress1"), p.get("mailingAddress2")] if s and s.strip()
            ),
            mailing_address=", ".join(
                s.strip() for s in [p.get("mailingAddress1"), p.get("mailingAddress2")] if s and s.strip()
            ),
            legal_description=(p.get("legal") or "").strip(),
            just_value=_safe_money(p.get("justValue")),
            assessed_value=_safe_money(p.get("assessedLastYearValue")),
            homestead_amount=_safe_money(p.get("he1Amount")),
            homestead_active=(p.get("homesteadFlag") or "").strip().upper().endswith(", Y"),
            year_built=_safe_int(p.get("actualAge")),
            living_area_sqft=_safe_int(p.get("bldgUnderAirFootage") or p.get("bldgSqFT")),
            source_url=f"https://web.bcpa.net/bcpaclient/#/Record-Search?fnumber={folio}",
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(p)
        return result

    @staticmethod
    def _parse_sales(p: Dict[str, Any]) -> List[SaleHistoryEntry]:
        sales: List[SaleHistoryEntry] = []
        for i in range(1, 6):
            date = (p.get(f"saleDate{i}") or "").strip()
            if not date:
                continue
            bp = (p.get(f"bookAndPageOrCin{i}") or "").strip()
            deed_doc_number = ""
            deed_book_page = ""
            if bp:
                if "/" in bp:
                    deed_book_page = bp
                else:
                    deed_doc_number = bp
            sales.append(
                SaleHistoryEntry(
                    sale_date=date,
                    deed_type=(p.get(f"deedType{i}") or "").strip(),
                    deed_doc_number=deed_doc_number,
                    deed_book_page=deed_book_page,
                    qualified=(p.get(f"saleVerification{i}") or "").strip().lower() == "qualified sale",
                    notes=(p.get(f"saleVerification{i}") or "").strip(),
                )
            )
        return sales


# ----------------------------------------------------------- helpers


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0
