"""Hillsborough County Property Appraiser HTTP adapter (Phase 1a anchor).

Implementation derived from the 2026-05-26 probe (see
docs/FL/source/hillsborough_probe/) and the live SPA JS bundle at
https://gis.hcpafl.org/propertysearch/viewmodel/viewModels.js (see lines
1484, 2036, 31918, 154839, 159597+ for the endpoint contract).

HCPA is a Knockout SPA backed by a plain REST/JSON service at
`https://gis.hcpafl.org/CommonServices/property/search/`. Endpoints:

  - Autocomplete?value=<text>&table=<address|name|folio|...>
        →  list[str] — jQuery-UI autocomplete suggestion strings
  - BasicSearch?address=<addr> | folio=<folio> | name=<owner>
        →  list[parcel-summary] with folio/pin/owner/saleDate/salePrice
        each row also carries totalCount so callers can detect "more".
  - ParcelData?pin=<pin>
        →  full parcel JSON with `salesHistory[]`, `propertyCard.*`,
        `valueSummary[]`, `fullLegal[]`, `buildings[]`, `mailingAddress`,
        homestead amount, year built, heated/gross sqft, etc.

Tony Roveda 2026-05-26: Hillsborough is the second county built to the
Broward Standard. The PA anchor for FROMER (folio `1151460000`) gives us:
  - canonical APN (1151460000) + PIN (1829213LS000012000040A)
  - owner of record (FROMER MICHAEL A; FROMER ALANA)
  - vesting deed (QCD #2025214758, 05/15/2025)
  - PRE-recorder-window chain root (Book 2411 Page 752, 1971-01-01)
    — exactly the kind of back-chain that the recorder's 01/01/2010
    digital-index window can't reach.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"


class HillsboroughHCPA(AbstractPropertyAppraiser):
    """REST/JSON adapter for Hillsborough County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_hillsborough"
        self.county_name = "Hillsborough"
        self.source_label = config.get(
            "description", "Hillsborough County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._warmup_url = config.get(
            "warmup_url", "https://gis.hcpafl.org/propertysearch/"
        )
        self._url_autocomplete = endpoints.get(
            "autocomplete",
            "https://gis.hcpafl.org/CommonServices/property/search/Autocomplete",
        )
        self._url_basic_search = endpoints.get(
            "basic_search",
            "https://gis.hcpafl.org/CommonServices/property/search/BasicSearch",
        )
        self._url_parcel_data = endpoints.get(
            "parcel_data",
            "https://gis.hcpafl.org/CommonServices/property/search/ParcelData",
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        # Sessions lazily created so unit tests can inject mocks.
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
        self._warmed = False

    def _warm(self) -> None:
        if self._warmed:
            return
        try:
            self.session.get(self._warmup_url, timeout=30)
        except Exception:
            # Best-effort — HCPA generally doesn't require warm-up cookies.
            pass
        self._warmed = True

    def _get_json(self, url: str, params: Dict[str, Any]) -> Any:
        self._warm()
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"HCPA {url} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        # HCPA returns either a JSON list (search) or JSON object (parcel-data).
        return resp.json()

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """Strip city/state/zip + ordinal suffixes so BasicSearch hits the
        canonical indexed form.

        Examples:
          "4004 W North B St, Tampa, FL 33609"   → "4004 W NORTH B ST"
          "13519 Westshire Dr, Tampa, FL 33618"  → "13519 WESTSHIRE DR"
          "100 1st Avenue, Tampa"                → "100 1 AVENUE"
        """
        addr = (address or "").upper()
        addr = addr.split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        addr = re.sub(r"\s+", " ", addr)
        return addr.strip()

    @staticmethod
    def _normalize_folio(apn: str) -> str:
        """HCPA folio is 10-digit numeric, no hyphens.

        Accepts hyphenated tax-roll display form ("115146-0000"), bare digits
        ("1151460000"), and the strap/PIN form (passed through as-is).
        Returns either folio digits or empty string if input is unparseable.
        """
        s = (apn or "").strip()
        if not s:
            return ""
        # Strap/PIN form: "A-21-29-18-3LS-000012-00004.0" — return as-is for
        # callers that intend to use PIN-based lookup; we treat folio as
        # purely numeric so non-numeric input falls back to PIN handling.
        digits = re.sub(r"[^0-9]", "", s)
        return digits

    @staticmethod
    def _is_pin(value: str) -> bool:
        """HCPA PIN format is alphanumeric with no dashes when stored
        internally (e.g., "1829213LS000012000040A"). Display form is
        hyphenated ("A-21-29-18-3LS-000012-00004.0").
        """
        if not value:
            return False
        s = value.strip().upper()
        # PIN contains letters; folio is digits-only.
        return any(c.isalpha() for c in s)

    @staticmethod
    def _normalize_pin(pin: str) -> str:
        """Strip dashes/dots from display PIN so it matches the wire format."""
        return re.sub(r"[^0-9A-Z]", "", (pin or "").strip().upper())

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        if not norm:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty address after normalize: {address!r}",
                fetched_at=datetime.now().isoformat(),
            )

        try:
            rows = self._get_json(self._url_basic_search, {"address": norm})
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"BasicSearch address error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"HCPA BasicSearch found no parcel for address={norm!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # Prefer an exact street-match (case-insensitive) over fuzzy.
        norm_no_city = norm.upper()
        exact = [
            r
            for r in rows
            if (r.get("address", "") or "").split(",", 1)[0].strip().upper()
            == norm_no_city
        ]
        candidates = exact or rows

        if len(candidates) > 1 and not exact:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"HCPA returned {len(rows)} candidates for {norm!r}: "
                    + "; ".join(
                        f"{r.get('address','?')} (folio {r.get('folio','?')})"
                        for r in rows[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )

        chosen = candidates[0]
        pin = chosen.get("pin") or ""
        if not pin:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"HCPA address-search row missing 'pin': {chosen!r}",
                fetched_at=datetime.now().isoformat(),
            )
        # ParcelData wants the bare PIN — use what we got from BasicSearch.
        return self._lookup_by_pin_raw(pin, summary_row=chosen)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        """APN here can be either a folio (numeric) or a PIN (alphanumeric).

        Folio path: BasicSearch?folio=<X> → grabs the canonical PIN, then
        ParcelData. PIN path: ParcelData directly.
        """
        if not apn or not apn.strip():
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )

        if self._is_pin(apn):
            return self._lookup_by_pin_raw(self._normalize_pin(apn))

        folio = self._normalize_folio(apn)
        if not folio:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # folio → BasicSearch → grab PIN → ParcelData
        try:
            rows = self._get_json(self._url_basic_search, {"folio": folio})
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"BasicSearch folio error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"HCPA BasicSearch found no parcel for folio={folio!r}",
                apn=folio,
                folio=folio,
                fetched_at=datetime.now().isoformat(),
            )
        chosen = rows[0]
        pin = chosen.get("pin") or ""
        if not pin:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"HCPA folio-search row missing 'pin': {chosen!r}",
                apn=folio,
                folio=folio,
                fetched_at=datetime.now().isoformat(),
            )
        return self._lookup_by_pin_raw(pin, summary_row=chosen)

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search is a diagnostics convenience — main path is by
        address. Returns a (possibly empty) list of PA results, one per
        matching parcel.
        """
        if not owner_name or not owner_name.strip():
            return []
        try:
            rows = self._get_json(
                self._url_basic_search, {"name": owner_name.strip().upper()}
            )
        except Exception:
            return []
        out: List[PropertyAppraiserResult] = []
        for row in rows[:10]:  # cap defensive
            pin = row.get("pin") or ""
            if not pin:
                continue
            out.append(self._lookup_by_pin_raw(pin, summary_row=row))
        return out

    # ----------------------------------------------------------- parse

    def _lookup_by_pin_raw(
        self, pin: str, summary_row: Optional[Dict[str, Any]] = None
    ) -> PropertyAppraiserResult:
        try:
            data = self._get_json(self._url_parcel_data, {"pin": pin})
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"ParcelData error: {type(exc).__name__}: {exc}",
                pin=pin,
                fetched_at=datetime.now().isoformat(),
            )
        if not isinstance(data, dict) or not data:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"HCPA ParcelData returned empty payload for pin={pin!r}",
                pin=pin,
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_parcel(data, summary_row=summary_row)

    def _parse_parcel(
        self, p: Dict[str, Any], summary_row: Optional[Dict[str, Any]] = None
    ) -> PropertyAppraiserResult:
        card = p.get("propertyCard") or {}
        folio = (card.get("folio") or "").strip()
        pin = (p.get("pin") or "").strip()
        display_folio = (card.get("displayFolio") or "").strip()
        display_pin = (card.get("displayStrap") or "").strip()

        owner_raw = (p.get("owner") or summary_row.get("owner", "") if summary_row else (p.get("owner") or "")).strip()
        owner_parts = [o.strip() for o in owner_raw.split(";") if o.strip()]
        owner_of_record = owner_parts[0] if owner_parts else ""
        co_owners = owner_parts[1:] if len(owner_parts) > 1 else []

        full_legal_list = p.get("fullLegal") or []
        legal_description = (
            full_legal_list[0]
            if full_legal_list
            else (card.get("legalDescription") or "").strip()
        )

        mailing = p.get("mailingAddress") or {}
        mailing_address = ", ".join(
            x
            for x in [
                (mailing.get("addr1") or "").strip(),
                (mailing.get("addr2") or "").strip(),
                ", ".join(
                    x
                    for x in [
                        (mailing.get("city") or "").strip(),
                        (mailing.get("state") or "").strip(),
                        (mailing.get("zip") or "").strip(),
                    ]
                    if x
                ),
            ]
            if x
        )
        situs_address = (
            (p.get("siteAddress") or "").strip()
            or (summary_row.get("address", "").strip() if summary_row else "")
        )

        value_summary = p.get("valueSummary") or []
        county_row = next(
            (v for v in value_summary if (v.get("taxDist") or "").upper() == "COUNTY"),
            value_summary[0] if value_summary else {},
        )
        just_value = _safe_int(county_row.get("marketVal"))
        assessed_value = _safe_int(county_row.get("assessedVal"))
        homestead_amount = _safe_int(card.get("homestead"))
        homestead_active = homestead_amount > 0

        buildings = p.get("buildings") or []
        year_built = _safe_int(buildings[0].get("yearBuilt")) if buildings else 0
        heated_area = _safe_int(buildings[0].get("heatedArea")) if buildings else 0

        result = PropertyAppraiserResult(
            apn=folio or self._normalize_folio(display_folio),
            folio=folio or self._normalize_folio(display_folio),
            pin=pin or display_pin,
            owner_of_record=owner_of_record,
            co_owners=co_owners,
            situs_address=situs_address,
            mailing_address=mailing_address,
            legal_description=legal_description,
            just_value=just_value,
            assessed_value=assessed_value,
            homestead_active=homestead_active,
            homestead_amount=homestead_amount,
            year_built=year_built,
            living_area_sqft=heated_area,
            source_url=f"https://gis.hcpafl.org/PropertySearch/#/nav/Details/Folio/{folio}",
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(p.get("salesHistory") or [])
        return result

    @staticmethod
    def _parse_sales(sales_rows: List[Dict[str, Any]]) -> List[SaleHistoryEntry]:
        out: List[SaleHistoryEntry] = []
        # HCPA returns newest-first by `sequence` ASC; we trust the source order.
        for s in sales_rows:
            date_iso = (s.get("saleDate") or "").strip()
            if not date_iso:
                continue
            # Convert "YYYY-MM-DD" → "MM/DD/YYYY" to match SaleHistoryEntry contract.
            try:
                y, m, d = date_iso.split("-")
                sale_date = f"{m}/{d}/{y}"
            except ValueError:
                sale_date = date_iso

            docnum = (s.get("docnum") or "").strip()
            book = (s.get("book") or "").strip()
            page = (s.get("page") or "").strip()
            deed_book_page = ""
            deed_doc_number = ""
            if docnum:
                deed_doc_number = docnum
            if book and page:
                # Book/Page form mirrors BCPA's "<book> / <page>" convention.
                deed_book_page = f"{book} / {page}"
            elif book:
                deed_book_page = book

            deed_type_raw = (s.get("deedType") or "").strip()

            out.append(
                SaleHistoryEntry(
                    sale_date=sale_date,
                    sale_price=_safe_int(s.get("salePrice")),
                    deed_doc_number=deed_doc_number,
                    deed_book_page=deed_book_page,
                    deed_type=deed_type_raw,
                    qualified=(s.get("qualified") or "").strip().lower() == "qualified",
                    notes=(s.get("qualified") or "").strip(),
                )
            )
        return out


# ----------------------------------------------------------- helpers


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(float(re.sub(r"[^\d.]", "", str(s)) or "0"))
    except Exception:
        return 0
