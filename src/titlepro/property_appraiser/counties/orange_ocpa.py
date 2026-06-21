"""Orange County (FL) Property Appraiser HTTP adapter (Phase 1a anchor).

Implementation derived from the 2026-05-26 probe of the OCPA SPA
(https://ocpaweb.ocpafl.org/parcelsearch). The SPA is Angular, backed by
an Azure-Front-Door-fronted REST API at
`https://ocpa-mainsite-afd-standard.azurefd.net/api/`. Authentication is
a single header `x-user-key: <static GUID>` that the SPA injects via an
Angular HttpInterceptor (interceptor calls `gatewayService.getAuthToken()`
which returns the GUID literal from the bundled JS).

The Azure Front Door layer also TLS-fingerprints requests — plain
`requests` returns 403 with an HTML "request is blocked" page. Only
`curl_cffi.Session(impersonate="chrome120")` (or similar real-Chrome
profile) passes. This matches the Broward / Hillsborough adapter pattern.

Critical endpoints used here:
  - QuickSearch/GetSearchInfoByAddress   →  address → parcelId + ownerName
  - QuickSearch/GetSearchInfoByParcel    →  pid     → parcelId + ownerName
  - PRC/GetPRCGeneralInfo                →  pid     → owner + mailing + parcel header
  - PRC/GetPRCPropFeatLegal              →  pid     → short legal description
  - PRC/GetPRCSales                      →  pid     → sale history (newest-first)
  - PRC/GetPRCTotalTaxes                 →  pid     → 2025 total ad valorem + non-ad-valorem
  - PRC/GetPRCCertifiedTaxes             →  pid     → per-authority millage + homestead flag
  - PRC/GetPRCNonAdValorem               →  pid     → CDD / stormwater / streetlight assessments
  - PRC/GetPRCPropertyValues             →  pid     → assessed/market/SOH values
  - PRCLocation/GetPRCLocationInfo       →  pid     → HOA name + schools (we use HOA)

OCPA returns parcelId in **S-T-R-Subdivision-Block-Lot** order, NOT the
Comptroller-recorder convention (whose deed indexer often inverts the
section/township pair). Concretely, for the MIRANDA subject:
    OCPA parcelId       = 27-23-33-5458-02-830     (Sec 27 Twp 23 Rng 33)
    LLM-fabricated APN  = 33-23-27-5458-02-830     (wrong — caught here)
The PA anchor IS authoritative for APN; recorder deeds and tax-bill APNs
should be aligned to the PA value before report rendering.

Tony Roveda 2026-05-26: this adapter closes the MIRANDA-class APN-inversion
gap and provides the back-chain anchor (where the only sale-history entry
proves there is no individual prior owner — subject is a 2017 new-build
from Pulte). For cases where the PA shows pre-recorder-window sales the
adapter's `sale_history` rows feed directly into Tyler HTTP's instrument-
number direct-fetch path (per Tony directive #2: deed-first + back-chain
beyond the digital-index window).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"
# The static x-user-key the OCPA SPA injects via Angular HttpInterceptor.
# Extracted from the bundled JS — public-by-design (no PII gate behind it).
_DEFAULT_USER_KEY = "a5250bb5-c321-4926-a966-9e907f560f31"
_DEFAULT_BASE_URL = "https://ocpa-mainsite-afd-standard.azurefd.net"


class OrangeOCPA(AbstractPropertyAppraiser):
    """Azure-fronted REST adapter for Orange County (FL) Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_orange"
        self.county_name = "Orange (FL)"
        self.source_label = config.get(
            "description", "Orange County Property Appraiser (Florida)"
        )
        endpoints = config.get("endpoints", {})
        self._base_url = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        self._user_key = config.get("user_key", _DEFAULT_USER_KEY)
        self._origin = config.get("origin_url", "https://ocpaweb.ocpafl.org")
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        self._ep_search_address = endpoints.get(
            "search_by_address", "api/QuickSearch/GetSearchInfoByAddress"
        )
        self._ep_search_parcel = endpoints.get(
            "search_by_parcel", "api/QuickSearch/GetSearchInfoByParcel"
        )
        self._ep_search_owner = endpoints.get(
            "search_by_owner", "api/QuickSearch/GetSearchByOwnerName"
        )
        self._ep_general = endpoints.get(
            "general_info", "api/PRC/GetPRCGeneralInfo"
        )
        self._ep_legal = endpoints.get(
            "legal", "api/PRC/GetPRCPropFeatLegal"
        )
        self._ep_sales = endpoints.get("sales", "api/PRC/GetPRCSales")
        self._ep_total_taxes = endpoints.get(
            "total_taxes", "api/PRC/GetPRCTotalTaxes"
        )
        self._ep_certified_taxes = endpoints.get(
            "certified_taxes", "api/PRC/GetPRCCertifiedTaxes"
        )
        self._ep_non_ad_valorem = endpoints.get(
            "non_ad_valorem", "api/PRC/GetPRCNonAdValorem"
        )
        self._ep_property_values = endpoints.get(
            "property_values", "api/PRC/GetPRCPropertyValues"
        )
        self._ep_location = endpoints.get(
            "location", "api/PRCLocation/GetPRCLocationInfo"
        )

        # Lazy session.
        self._session: Optional[Any] = None

    # ----------------------------------------------------------- session

    @property
    def session(self):
        if self._session is None:
            self._session = _cffi_requests.Session(impersonate=self._impersonate)
            self._session.headers.update(
                {
                    "x-user-key": self._user_key,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": self._origin,
                    "Referer": self._origin + "/",
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                }
            )
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    def _get_json(self, endpoint: str, params: Dict[str, str]) -> Any:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OCPA {endpoint} HTTP {resp.status_code}: {resp.text[:200]}"
            )
        if not resp.text:
            return None
        try:
            return resp.json()
        except Exception:
            return None

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """Strip city/state/zip + ordinal suffixes for the OCPA address search.

        Examples:
          "7313 Twilight Bay Dr, Winter Garden, FL 34787" → "7313 TWILIGHT BAY DR"
          "1234 W 5TH ST"                                  → "1234 W 5 ST"
        """
        addr = (address or "").upper()
        addr = addr.split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        addr = re.sub(r"\s+", " ", addr)
        return addr.strip()

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """OCPA parcelId is unhyphenated 15-digit numeric.

        The portal validates `pid` to a max length of 15; passing a hyphenated
        APN returns HTTP 400 with `"The field pid must be a string with a
        maximum length of '15'"`. We strip everything non-numeric.
        """
        return re.sub(r"[^0-9]", "", apn or "")

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        try:
            rows = self._get_json(
                self._ep_search_address,
                {"address": norm, "streetType": "", "dorCode": ""},
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"OCPA address-search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"OCPA found no parcel matching address {norm!r}",
                fetched_at=datetime.now().isoformat(),
            )

        if len(rows) > 1:
            # Prefer exact (street-number + first street word) match.
            head = norm.split(" ", 2)
            head_prefix = " ".join(head[:2]).upper()
            exact = [
                r for r in rows
                if (r.get("propertyAddress") or "").strip().upper().startswith(head_prefix)
            ]
            if len(exact) == 1:
                rows = exact
            else:
                return PropertyAppraiserResult(
                    status="PA_AMBIGUOUS",
                    notes=(
                        f"OCPA returned {len(rows)} candidates for {norm!r}: "
                        + "; ".join(
                            f"{r.get('propertyAddress','?').strip()} (pid {r.get('parcelId','?')})"
                            for r in rows[:6]
                        )
                    ),
                    fetched_at=datetime.now().isoformat(),
                )

        chosen = rows[0]
        pid = chosen.get("parcelId") or ""
        if not pid:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"OCPA address-search result missing parcelId: {chosen!r}",
                fetched_at=datetime.now().isoformat(),
            )
        return self.lookup_by_apn(pid)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        pid = self._normalize_apn(apn)
        if not pid or len(pid) > 15:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r} -> {pid!r}",
                fetched_at=datetime.now().isoformat(),
            )

        try:
            general = self._get_json(self._ep_general, {"pid": pid}) or {}
            if not general:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"OCPA returned empty parcel for pid={pid!r}",
                    apn=pid,
                    fetched_at=datetime.now().isoformat(),
                )
            legal = self._get_json(self._ep_legal, {"pid": pid}) or {}
            sales = self._get_json(self._ep_sales, {"pid": pid}) or []
            total_tax = self._get_json(self._ep_total_taxes, {"pid": pid}) or {}
            certified_tax = self._get_json(self._ep_certified_taxes, {"pid": pid}) or []
            non_ad_valorem = self._get_json(self._ep_non_ad_valorem, {"pid": pid}) or []
            property_values = self._get_json(self._ep_property_values, {"pid": pid}) or []
            location = self._get_json(self._ep_location, {"pid": pid}) or {}
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"OCPA fetch error for pid={pid!r}: {type(exc).__name__}: {exc}",
                apn=pid,
                fetched_at=datetime.now().isoformat(),
            )

        return self._build_result(
            pid,
            general,
            legal,
            sales,
            total_tax,
            certified_tax,
            non_ad_valorem,
            property_values,
            location,
        )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Owner search endpoint exists but returns paged result envelopes that
        # require selecting a city. We return [] (diagnostics-only) rather than
        # guessing — the canonical path is by address or APN.
        return []

    # ----------------------------------------------------------- parse

    def _build_result(
        self,
        pid: str,
        general: Dict[str, Any],
        legal: Dict[str, Any],
        sales: List[Dict[str, Any]],
        total_tax: Dict[str, Any],
        certified_tax: List[Dict[str, Any]],
        non_ad_valorem: List[Dict[str, Any]],
        property_values: List[Dict[str, Any]],
        location: Dict[str, Any],
    ) -> PropertyAppraiserResult:
        # Owner of record — OCPA stuffs co-owners into a single comma-separated
        # string, e.g. " MIRANDA RAMON, MIRANDA LEONORA MATTOS MENESES".
        owner_full = (general.get("ownerName") or "").strip().strip(",").strip()
        owners = [o.strip() for o in owner_full.split(",") if o.strip()]
        owner_of_record = owners[0] if owners else ""
        co_owners = owners[1:] if len(owners) > 1 else []

        situs_parts = [
            (general.get("propertyAddress") or "").strip(),
            (general.get("propertyCity") or "").strip(),
            (general.get("propertyState") or "").strip(),
            (general.get("propertyZip") or "").strip(),
        ]
        situs = " ".join(p for p in situs_parts if p)

        mail_parts = [
            (general.get("mailAddress") or "").strip(),
            (general.get("mailCity") or "").strip(),
            (general.get("mailState") or "").strip(),
            (general.get("mailZip") or "").strip(),
        ]
        mail = " ".join(p for p in mail_parts if p)

        # Property values — usually a single most-recent-year row.
        pv = property_values[0] if property_values else {}
        assessed = _safe_money(pv.get("assessedValue"))
        market = _safe_money(pv.get("marketValue"))
        soh = _safe_money(pv.get("sohCap"))
        homestead_amount = _safe_money(pv.get("originalHx")) + _safe_money(pv.get("additionalHx"))
        homestead_active = (
            str(pv.get("isHomestead") or "").upper().startswith("T")
            or any(
                str(r.get("isHomestead") or "").upper().startswith("T")
                for r in certified_tax
            )
        )

        # Source URL — the PRC tab on the SPA, deep-linked by pid.
        source_url = f"https://ocpaweb.ocpafl.org/parcelsearch/Parcel?pid={pid}"

        # Format pid back into the canonical OCPA APN form NN-NN-NN-NNNN-NN-NNN
        # (15 chars, but the underlying string is `STR + Subdiv + Block + Lot`).
        canonical_apn = self._format_canonical_apn(pid)

        result = PropertyAppraiserResult(
            apn=canonical_apn or pid,
            folio=pid,
            pin=pid,
            owner_of_record=owner_of_record,
            co_owners=co_owners,
            situs_address=situs,
            mailing_address=mail,
            legal_description=(legal.get("propertyDescription") or "").strip(),
            just_value=market if market > 0 else 0,
            assessed_value=assessed if assessed > 0 else 0,
            homestead_active=homestead_active,
            homestead_amount=homestead_amount if homestead_amount > 0 else 0,
            year_built=_safe_int(pv.get("yearBuilt")),
            living_area_sqft=0,  # OCPA returns this in PropFeatBldg — not pulled here
            source_url=source_url,
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )

        result.sale_history = self._parse_sales(sales)

        # Augment notes with HOA + tax + SOH info so the report-prompt sees them.
        community = (location or {}).get("community") or {}
        hoa_name = (community.get("communityName") or "").strip()
        notes_parts: List[str] = []
        if hoa_name:
            hoa_mandatory = (community.get("isMandatory") or "").strip()
            hoa_gated = (community.get("isGated") or "").strip()
            notes_parts.append(
                f"HOA: {hoa_name}"
                + (f" (mandatory={hoa_mandatory})" if hoa_mandatory else "")
                + (f" (gated={hoa_gated})" if hoa_gated else "")
            )

        gross_tax = _safe_float(total_tax.get("grossTaxes"))
        ad_val = _safe_float(total_tax.get("adValoremTaxes"))
        non_ad_val_total = _safe_float(total_tax.get("nonAdValoremTaxes"))
        if gross_tax > 0:
            tax_year = total_tax.get("taxYear") or ""
            notes_parts.append(
                f"Tax(certified-roll year={tax_year}): "
                f"gross=${gross_tax:,.2f} "
                f"adValorem=${ad_val:,.2f} "
                f"nonAdValorem=${non_ad_val_total:,.2f}"
            )

        # Non-ad-valorem line-items (CDD candidates, stormwater, garbage, etc.)
        if non_ad_valorem:
            line_items = "; ".join(
                f"{(r.get('description') or '').strip()}=${_safe_float(r.get('assessment')):,.2f}"
                for r in non_ad_valorem
            )
            notes_parts.append(f"Non-ad-valorem: {line_items}")

        # Surface SOH cap so the title examiner can flag any pending re-set
        if soh > 0:
            notes_parts.append(f"Save Our Homes cap={soh:,}")

        if notes_parts:
            result.notes = " | ".join(notes_parts)

        return result

    @staticmethod
    def _parse_sales(sales: List[Dict[str, Any]]) -> List[SaleHistoryEntry]:
        out: List[SaleHistoryEntry] = []
        for s in sales or []:
            date_raw = (s.get("saleDate") or "").strip()
            # OCPA returns ISO timestamps like "2017-05-08T00:00:00".
            date_display = ""
            if date_raw:
                try:
                    parsed = datetime.fromisoformat(date_raw.replace("Z", ""))
                    date_display = parsed.strftime("%m/%d/%Y")
                except Exception:
                    date_display = date_raw[:10]
            book = (s.get("book") or "").strip()
            page = (s.get("page") or "").strip()
            book_page = ""
            if book and page:
                book_page = f"{book}/{page}"
            elif book:
                book_page = book
            out.append(
                SaleHistoryEntry(
                    sale_date=date_display,
                    sale_price=_safe_money(s.get("saleAmt")),
                    deed_doc_number=(s.get("instrNum") or "").strip(),
                    deed_book_page=book_page,
                    deed_type=(s.get("deedDesc") or "").strip(),
                    grantor=(s.get("seller") or "").strip(),
                    grantee=(s.get("buyer") or "").strip(),
                    qualified=(s.get("vacImpCode") or "").strip().lower() == "improved",
                    notes=(s.get("vacImpCode") or "").strip(),
                )
            )
        return out

    @staticmethod
    def _format_canonical_apn(pid: str) -> str:
        """Convert the 15-char numeric parcelId back to the canonical
        Orange-FL APN form: ``NN-NN-NN-NNNN-NN-NNN`` (Sec-Twp-Rng-Subdiv-Block-Lot).

        Example: ``272333545802830`` → ``27-23-33-5458-02-830``.

        Returns the original `pid` if it isn't a 15-digit numeric string.
        """
        if len(pid) != 15 or not pid.isdigit():
            return pid
        return (
            f"{pid[0:2]}-{pid[2:4]}-{pid[4:6]}-{pid[6:10]}-{pid[10:12]}-{pid[12:15]}"
        )


# ----------------------------------------------------------- helpers


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(float(re.sub(r"[^\d.-]", "", str(s)) or "0"))
    except Exception:
        return 0


def _safe_float(s: Any) -> float:
    if s is None:
        return 0.0
    try:
        return float(re.sub(r"[^\d.-]", "", str(s)) or "0")
    except Exception:
        return 0.0


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0
