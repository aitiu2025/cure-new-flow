"""Miami-Dade County Property Appraiser (MDCPA) HTTP adapter — Phase 1a anchor.

LIVE-VALIDATED 2026-06-17 (US egress). See the probe at
``docs/FL/source/miami_dade_pa_probe.md`` for the captured request/response
shapes; raw fixtures are in ``tests/unit/fixtures/miami_dade/``.

The official PA Property Search SPA (Angular) at
``https://www.miamidade.gov/Apps/PA/PropertySearch/`` redirects to the canonical
host ``https://apps.miamidadepa.gov/PropertySearch/`` and reads ALL data from a
single public proxy (no auth / no CAPTCHA / no Cloudflare):

    GET https://apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx
            ?Operation=<Op>&clientAppName=PropertySearch&<op params>

⚠️ NOT the recorder. The Miami-Dade *Clerk Official Records* (recorder) at
``miamidadeclerk.gov`` is a SEPARATE, paywalled system (see
``docs/FL/miami_dade_probe.md``). This adapter is the public Property Appraiser.

Operations used:
  - GetAddress                →  address → list of {Strap, Owner1..3, SiteAddress}
                                 (one row per unit; `Strap` is the hyphenated folio)
  - GetPropertySearchByFolio  →  folioNumber(13-digit) → full parcel + SalesInfos[]

Miami-Dade folio (the county APN) is 13 digits, display ``NN-NNNN-NNN-NNNN``
(e.g. ``30-4035-047-2550``). The folio-detail call keys on the unhyphenated
13-digit string.

Notable real-schema facts (drove the parse logic below):
  * Owners are ``OwnerInfos[].Name`` (objects, key is ``Name`` not ``Owner``).
  * ``SiteAddress`` is a LIST; ``[0].Address`` is the full one-line situs string.
  * ``MailingAddress`` is a single object (Address1/City/State/ZipCode).
  * Assessment values live under ``Assessment.AssessmentInfos[0]`` (newest year).
  * Homestead is a ``Benefit.BenefitInfos[]`` row Type=="Exemption",
    Description startswith "Homestead".
  * ``SalesInfos`` is a bare list returned OLDEST-FIRST; ``SaleId`` 1 = newest, so
    we sort by SaleId ascending to honor the newest-first sale_history contract.
  * There is NO DeedType in the PA feed (recorder cross-ref fills it).

Tony Roveda Phase-1a: this delivers the BACK-CHAIN that name-only recorder
searches can't recover (same role BCPA plays for Broward) + the SIMMONS
subject-address gate.

HTTP-only via curl_cffi (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"
_CLIENT_APP = "PropertySearch"


class MiamiDadeMDCPA(AbstractPropertyAppraiser):
    """REST/JSON adapter for the Miami-Dade County Property Appraiser.

    Mirrors BrowardBCPA's structure: lazily-created injectable session, a JSON
    GET helper that adds the ``Operation``/``clientAppName`` params, and parse-
    only methods (``parse_parcel`` / ``_extract_address_candidates``) so the
    parse logic is unit-testable on canned response strings.
    """

    SOURCE_LABEL = "Miami-Dade County Property Appraiser"
    LIVE_PLATFORM = "mdcpa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_miami_dade")
        self.county_name = self.config.get("county_name", "Miami-Dade")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self._base = (
            self.config.get("base_url") or "https://apps.miamidadepa.gov/"
        ).rstrip("/")
        endpoints = self.config.get("endpoints", {})
        # Both operations hit the same proxy endpoint; the Operation param
        # selects the call. Default to the live-validated proxy URL.
        self._proxy_url = endpoints.get(
            "proxy",
            f"{self._base}/PApublicServiceProxy/PaServicesProxy.ashx",
        )
        self._referer = self.config.get(
            "referer", "https://apps.miamidadepa.gov/PropertySearch/"
        )
        self._impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        self._public_search_url_tmpl = self.config.get(
            "public_detail_pattern",
            "https://www.miamidade.gov/Apps/PA/PropertySearch/#/report/detail/{folio}",
        )

        # Lazily created so unit tests can inject `adapter.session = MagicMock()`.
        self._session: Optional[Any] = None

    # ----------------------------------------------------------- session

    @property
    def session(self):
        if self._session is None:
            self._session = _cffi_requests.Session(impersonate=self._impersonate)
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    def _proxy_get(self, operation: str, params: Dict[str, Any]) -> Any:
        """GET the PA proxy for ``operation`` with the given extra params."""
        query = {"Operation": operation, "clientAppName": _CLIENT_APP, **params}
        headers = {"Accept": "application/json"}
        if self._referer:
            headers["Referer"] = self._referer
        resp = self.session.get(
            self._proxy_url, params=query, headers=headers, timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"MDCPA {operation} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """Strip city/state/zip + ordinal suffixes so the MDCPA ``myAddress``
        param matches the canonical indexed form.

        Examples:
          "10630 SW 128TH TERRACE, MIAMI, FL"   → "10630 SW 128 TERRACE"
          "111 NW 1st St, Miami"                → "111 NW 1 ST"
        """
        addr = (address or "").upper()
        # Drop everything after the first comma (city, state, zip).
        addr = addr.split(",", 1)[0].strip()
        # Drop ordinal suffixes: "128TH" → "128", "1ST" → "1".
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        # Collapse multiple spaces.
        addr = re.sub(r"\s+", " ", addr)
        return addr.strip()

    @staticmethod
    def _normalize_folio(apn: str) -> str:
        """Miami-Dade folio is the 13-digit numeric string (hyphens stripped)."""
        return re.sub(r"[^0-9]", "", apn or "")

    @staticmethod
    def _format_folio_display(folio: str) -> str:
        """13-digit folio → canonical hyphenated display ``NN-NNNN-NNN-NNNN``."""
        digits = re.sub(r"[^0-9]", "", folio or "")
        if len(digits) != 13:
            return digits
        return f"{digits[0:2]}-{digits[2:6]}-{digits[6:9]}-{digits[9:13]}"

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        try:
            ac = self._proxy_get(
                "GetAddress",
                {"myAddress": norm, "myUnit": "", "from": 1, "to": 200},
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"MDCPA address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        candidates = self._extract_address_candidates(ac)
        if not candidates:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"MDCPA found no parcel matching address {norm!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # Prefer an exact street-match (normalized) over fuzzy. A single street
        # can return many units → exact-match collapses condo buildings; if more
        # than one still matches (true multi-unit), surface as ambiguous.
        exact = [
            c for c in candidates
            if self._normalize_address_for_lookup(c.get("address", "")) == norm
        ]
        pool = exact if exact else candidates
        if len(pool) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"MDCPA returned {len(pool)} candidates for {norm!r}: "
                    + "; ".join(
                        f"{c.get('address','?')}"
                        + (f" #{c['unit']}" if c.get("unit") else "")
                        + f" (folio {c.get('folio','?')})"
                        for c in pool[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        chosen = pool[0]
        folio = chosen.get("folio", "")
        if not folio:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"MDCPA address match for {norm!r} carried no folio",
                fetched_at=datetime.now().isoformat(),
            )
        return self.lookup_by_apn(folio)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        folio = self._normalize_folio(apn)
        if not folio:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid folio after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            data = self._proxy_get(
                "GetPropertySearchByFolio", {"folioNumber": folio}
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"MDCPA parcelInfo error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        return self.parse_parcel(data, folio)

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # GetOwners exists but is paginated + ambiguous; the canonical Phase-1a
        # path is by address/folio. Diagnostics-only — return [] (mirrors BCPA).
        return []

    # ----------------------------------------------------------- parse

    @staticmethod
    def _extract_address_candidates(payload: Any) -> List[Dict[str, str]]:
        """Normalize the GetAddress response into
        ``[{"address", "folio", "unit"}, ...]``.

        Real wrapper key is ``MinimumPropertyInfos`` (rows carry ``Strap`` =
        hyphenated folio, ``SiteAddress``, ``SiteUnit``, ``Owner1..3``). We also
        tolerate a bare list / a few alternate wrapper keys for resilience.
        """
        rows: List[Any] = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key in ("MinimumPropertyInfos", "Completions", "Results", "d", "data"):
                v = payload.get(key)
                if isinstance(v, list):
                    rows = v
                    break
        out: List[Dict[str, str]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            address = r.get("SiteAddress") or r.get("Address") or r.get("address") or ""
            folio = (
                r.get("Strap")            # real field
                or r.get("Folio")
                or r.get("FolioNumber")
                or r.get("folio")
                or ""
            )
            out.append({
                "address": str(address).strip(),
                "folio": MiamiDadeMDCPA._normalize_folio(str(folio)),
                "unit": str(r.get("SiteUnit") or "").strip(),
            })
        return out

    def parse_parcel(self, payload: Any, folio_hint: str = "") -> PropertyAppraiserResult:
        """Parse the GetPropertySearchByFolio response → PropertyAppraiserResult.

        Side-effect-free + public so unit tests can feed captured JSON.
        """
        parcel = payload if isinstance(payload, dict) else {}
        property_info = parcel.get("PropertyInfo")
        if not isinstance(property_info, dict):
            property_info = {}

        folio_raw = property_info.get("FolioNumber") or folio_hint
        folio = self._normalize_folio(folio_raw)

        # "Empty parcel" = no PropertyInfo AND no owners (a miss / blank folio).
        owners = self._owner_names(parcel)
        if not property_info and not owners:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"MDCPA returned empty parcel for folio={folio!r}",
                apn=self._format_folio_display(folio) if folio else "",
                folio=folio,
                fetched_at=datetime.now().isoformat(),
            )

        assess = self._first_assessment(parcel)

        result = PropertyAppraiserResult(
            apn=self._format_folio_display(folio) if folio else "",
            folio=folio,
            owner_of_record=owners[0] if owners else "",
            co_owners=owners[1:] if len(owners) > 1 else [],
            situs_address=self._situs(parcel),
            mailing_address=self._mailing(parcel),
            legal_description=self._legal(parcel),
            just_value=_safe_money(assess.get("TotalValue")),
            assessed_value=_safe_money(assess.get("AssessedValue")),
            homestead_active=self._homestead_active(parcel),
            homestead_amount=0,  # not separately exposed; exemption value is in Taxable
            year_built=_safe_int(property_info.get("YearBuilt")),
            living_area_sqft=_nonneg_int(property_info.get("BuildingHeatedArea")),
            source_url=self._public_search_url_tmpl.format(folio=folio),
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(parcel)
        return result

    # ----- field extractors (each isolated for testability/resilience) -----

    @staticmethod
    def _owner_names(parcel: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        infos = parcel.get("OwnerInfos")
        if isinstance(infos, list):
            for o in infos:
                if isinstance(o, dict):
                    n = _clean(o.get("Name") or o.get("Owner"))
                else:
                    n = _clean(o)
                if n:
                    names.append(n)
        return names

    @staticmethod
    def _situs(parcel: Dict[str, Any]) -> str:
        site = parcel.get("SiteAddress")
        if isinstance(site, list) and site and isinstance(site[0], dict):
            return _clean(site[0].get("Address"))
        if isinstance(site, dict):
            return _clean(site.get("Address"))
        return _clean(site)

    @staticmethod
    def _mailing(parcel: Dict[str, Any]) -> str:
        mail = parcel.get("MailingAddress")
        if isinstance(mail, dict):
            parts = [
                _clean(mail.get("Address1")),
                _clean(mail.get("Address2")),
                _clean(mail.get("City")),
                _clean(mail.get("State")),
                _clean(mail.get("ZipCode")),
            ]
            return ", ".join(p for p in parts if p)
        return _clean(mail)

    @staticmethod
    def _legal(parcel: Dict[str, Any]) -> str:
        legal = parcel.get("LegalDescription")
        if isinstance(legal, dict):
            return _clean(legal.get("Description"))
        return _clean(legal)

    @staticmethod
    def _first_assessment(parcel: Dict[str, Any]) -> Dict[str, Any]:
        a = parcel.get("Assessment")
        if isinstance(a, dict):
            infos = a.get("AssessmentInfos")
            if isinstance(infos, list) and infos and isinstance(infos[0], dict):
                # Newest year is index 0 (live-observed); be defensive and pick
                # the max Year if present.
                best = max(
                    (x for x in infos if isinstance(x, dict)),
                    key=lambda x: _safe_int(x.get("Year")),
                    default=infos[0],
                )
                return best
        return {}

    @staticmethod
    def _homestead_active(parcel: Dict[str, Any]) -> bool:
        b = parcel.get("Benefit")
        infos = b.get("BenefitInfos") if isinstance(b, dict) else b
        if isinstance(infos, list):
            for e in infos:
                if not isinstance(e, dict):
                    continue
                typ = _clean(e.get("Type")).upper()
                desc = _clean(e.get("Description")).upper()
                if typ == "EXEMPTION" and desc.startswith("HOMESTEAD"):
                    return True
        return False

    @staticmethod
    def _parse_sales(parcel: Dict[str, Any]) -> List[SaleHistoryEntry]:
        """Parse SalesInfos[] → newest-first SaleHistoryEntry list.

        The API returns rows OLDEST-FIRST with ``SaleId`` 1 == newest, so we
        sort by SaleId ascending. There is no DeedType in the feed.
        """
        raw = parcel.get("SalesInfos")
        if isinstance(raw, dict):
            raw = raw.get("SalesInfo") or raw.get("d") or []
        if not isinstance(raw, list):
            return []
        rows = [r for r in raw if isinstance(r, dict) and _clean(r.get("DateOfSale"))]
        # Newest-first: SaleId 1 is newest. Rows without a SaleId fall to the end.
        rows.sort(key=lambda r: _safe_int(r.get("SaleId")) or 10**9)

        sales: List[SaleHistoryEntry] = []
        for s in rows:
            book = _clean(s.get("OfficialRecordBook"))
            page = _clean(s.get("OfficialRecordPage"))
            cin = _clean(s.get("SaleInstrument"))
            deed_doc_number = ""
            deed_book_page = ""
            if book and page:
                deed_book_page = f"{book} / {page}"
            elif cin:
                deed_doc_number = cin
            qual_flag = _clean(s.get("QualifiedFlag")).upper()
            grantor = _join_names(s.get("GrantorName1"), s.get("GrantorName2"))
            grantee = _join_names(s.get("GranteeName1"), s.get("GranteeName2"))
            sales.append(
                SaleHistoryEntry(
                    sale_date=_clean(s.get("DateOfSale")),
                    sale_price=_safe_money(s.get("SalePrice")),
                    deed_type="",  # MDCPA does not expose deed type
                    deed_doc_number=deed_doc_number,
                    deed_book_page=deed_book_page,
                    grantor=grantor,
                    grantee=grantee,
                    qualified=qual_flag == "Q",
                    notes=_clean(s.get("QualificationDescription")),
                )
            )
        return sales


# ----------------------------------------------------------- helpers


def _clean(s: Any) -> str:
    if s is None:
        return ""
    # Strip stray NUL bytes the feed uses as empty-flag sentinels.
    return str(s).replace("\x00", "").strip()


def _join_names(*names: Any) -> str:
    parts = [_clean(n) for n in names if _clean(n)]
    return " ".join(parts)


def _safe_money(s: Any) -> int:
    if s is None or s == "":
        return 0
    try:
        return int(re.sub(r"[^\d-]", "", str(s).split(".")[0]) or "0")
    except Exception:
        return 0


def _safe_int(s: Any) -> int:
    if s is None or s == "":
        return 0
    try:
        m = re.search(r"-?\d+", str(s))
        return int(m.group(0)) if m else 0
    except Exception:
        return 0


def _nonneg_int(s: Any) -> int:
    """Like _safe_int but maps the MDCPA ``-1`` unknown-sentinel to 0."""
    v = _safe_int(s)
    return v if v > 0 else 0
