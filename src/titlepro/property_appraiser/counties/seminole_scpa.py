"""Seminole County Property Appraiser (SCPA / scpafl.org) HTTP adapter — Phase 1a anchor.

Derived from the 2026-06-10 Wave-1 probe (see the case folder
`0610/Seminole_PORTILLA_v1/phase0_probe_pa.md`).

## Why this adapter is parser-first

SCPA runs two front-ends over one parcel dataset:

  1. **Modern `scpafl.org/search/parcels/...`** — a **Blazor Server (Syncfusion)** SPA.
     Parcel data hydrates over a SignalR websocket; there is no plain REST/JSON GET to
     scrape. HOSTILE to HTTP-first scraping. NOT the adapter target.
  2. **Legacy `parceldetails.scpafl.org/DXB.axd?PID=<PID>`** — ASP.NET WebForms +
     DevExpress callback. Parseable but a custom format; status uncertain (may be
     deprecated).
  3. **GIS `map.scpafl.org`** — Esri ArcGIS web-app-viewer backed by an ArcGIS REST
     parcel FeatureServer. **This is the recommended HTTP-first source** — ArcGIS REST
     `query` returns clean JSON (owner, situs, parcel, DOR use, often sale book/page).

The exact ArcGIS FeatureServer URL could NOT be resolved during Wave-1 because every
`*.scpafl.org` host TCP-times-out from the build environment's (non-US) egress, and the
ArcGIS-Online discovery call was sandbox-denied. So this adapter is built **parser-first**:
the HTTP fetch is isolated behind `_query_arcgis()` / `_search_arcgis_by_address()` and the
ArcGIS-attribute → `PropertyAppraiserResult` mapping (`_parse_arcgis_feature`,
`_parse_sales`) is fully unit-tested against canned fixtures NOW. Wave-2 drops the live
FeatureServer URL into the config (`arcgis_query_url` / `arcgis_parcel_field` /
`arcgis_situs_field`) and runs PORTILLA end to end.

Field aliases are configurable (`field_map`) because ArcGIS layer schemas vary; sensible
SCPA defaults are baked in and overridable from county config.

Tony Roveda Phase-1a directive: the PA APN is the AUTHORITATIVE subject anchor and the
sale_history (newest-first) is the back-chain that name-only recorder searches can't recover.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "safari17_2_ios"  # scpafl.org / Esri behind a CDN; safari profile is safe default

# Default ArcGIS attribute aliases. LIVE-VALIDATED 2026-06-10 against the SCPA
# parcel layer `production/modal_map/MapServer/19` (portal-proxied at
# map.scpafl.org/gis/sharing/servers/b1408f8cfb614cd48305a419a7c705f5/...) — the
# live SCPA names are FIRST in each candidate list; legacy aliases kept for drift.
_DEFAULT_FIELD_MAP: Dict[str, List[str]] = {
    # canonical -> ordered list of candidate ArcGIS attribute names (first hit wins)
    "apn":            ["Parcel", "PARCEL", "PARCELID", "PARCEL_ID", "PARCELNO", "PIN", "PID", "STRAP"],
    "apn_formatted":  ["ParcelFormat"],
    "appr_id":        ["ApprId"],
    "owner":          ["OwnerName", "OWNER", "OWNER_NAME", "OWNERNAME", "OWNER1", "NAME"],
    "owner2":         ["OWNER2", "OWNER_NAME2", "COOWNER"],
    "situs":          ["PrimaryAddress", "SITE_ADDR", "SITUS", "SITUS_ADDRESS", "PROP_ADDR", "SITEADDRESS", "LOCATION"],
    "situs_city":     ["SITE_CITY", "SITUS_CITY", "PROP_CITY"],
    "situs_zip":      ["SITE_ZIP", "SITUS_ZIP", "PROP_ZIP"],
    "mailing":        ["MailingAddress", "MAIL_ADDR", "MAILING", "MAIL_ADDRESS", "MAILADDR1"],
    "mailing2":       ["MAIL_ADDR2", "MAILADDR2", "MAIL_CSZ"],
    "legal":          ["LegalDescription", "LEGAL", "LEGAL_DESC", "LEGALDESC", "S_LEGAL", "SHORT_LEGAL"],
    "subdivision":    ["Subdivision", "SUBDIVISION", "SUBDIV", "SUB_NAME"],
    "just_value":     ["TotalJustValue", "JUST", "JUST_VALUE", "JV", "JUSTVALUE", "MARKET_VAL"],
    "assessed_value": ["AssessedValue", "ASSESSED", "ASSD_VALUE", "AV", "ASSESSEDVALUE", "ASD_VAL"],
    "taxable_value":  ["TaxableValue"],
    "homestead":      ["HasHomestead", "HOMESTEAD", "HX", "HMSTD", "HOMESTEAD_FLAG", "HSTD"],
    "year_built":     ["YearBuilt", "YEAR_BUILT", "YRBLT", "ACT_YR_BLT", "YEARBUILT"],
    "living_area":    ["TotalLivingArea", "LIVING_AREA", "HEATED_SF", "TOT_LVG_AR", "BLDG_SQFT", "LIVAREA"],
    "dor_use":        ["DORCode", "DOR_UC", "DOR_USE", "USE_CODE", "PA_UC"],
    # SCPA layer 19 exposes only the most-recent sale as flat fields (no history).
    "last_sale_date": ["LastSaleDate"],
    "last_sale_amt":  ["LastSaleAmt"],
}

# Sale-history fields. ArcGIS parcel layers frequently expose up to N most-recent
# sales as flat suffixed columns (SALE_DATE1.., SALE_PRICE1.., OR_BOOK1.., OR_PAGE1..).
_DEFAULT_SALE_FIELD_MAP: Dict[str, List[str]] = {
    "date":      ["SALE_DATE{i}", "SALEDATE{i}", "SDATE{i}", "S_DATE{i}"],
    "price":     ["SALE_PRICE{i}", "SALEPRICE{i}", "SPRICE{i}", "S_AMT{i}"],
    "book":      ["OR_BOOK{i}", "BOOK{i}", "ORBOOK{i}", "S_BOOK{i}"],
    "page":      ["OR_PAGE{i}", "PAGE{i}", "ORPAGE{i}", "S_PAGE{i}"],
    "instrument":["INSTRUMENT{i}", "OR_INST{i}", "CFN{i}", "INST_NUM{i}"],
    "deed_type": ["DEED_TYPE{i}", "DEEDTYPE{i}", "SALE_TYPE{i}", "S_TYPE{i}", "INSTR_TYP{i}"],
    "qualified": ["QUAL{i}", "QUALIFIED{i}", "VI_CD{i}", "QUAL_CODE{i}"],
}
_MAX_SALES = 5


class SeminoleSCPA(AbstractPropertyAppraiser):
    """ArcGIS-REST adapter for Seminole County (FL) Property Appraiser (scpafl.org).

    HTTP fetch is isolated so unit tests can inject canned ArcGIS responses via
    `adapter.session = MagicMock()` / monkeypatching `_query_arcgis`.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.county_id = config.get("county_id", "fl_seminole")
        self.county_name = config.get("county_name", "Seminole")
        self.source_label = config.get(
            "description", "Seminole County Property Appraiser"
        )
        # ArcGIS FeatureServer/MapServer query layer (Wave-2: fill from live probe).
        # e.g. "https://services.arcgis.com/<org>/arcgis/rest/services/Parcels/FeatureServer/0/query"
        self._arcgis_query_url = config.get("arcgis_query_url", "")
        # Public landing-page base for source_url (modern Blazor detail page).
        self._detail_base = config.get(
            "detail_base_url", "https://www.scpafl.org/search/parcels/details/"
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        # Merge any config field-map overrides over the defaults.
        self._field_map = dict(_DEFAULT_FIELD_MAP)
        for k, v in (config.get("field_map") or {}).items():
            self._field_map[k] = v if isinstance(v, list) else [v]
        self._sale_field_map = dict(_DEFAULT_SALE_FIELD_MAP)
        for k, v in (config.get("sale_field_map") or {}).items():
            self._sale_field_map[k] = v if isinstance(v, list) else [v]

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

    # ----------------------------------------------------------- normalize

    @staticmethod
    def normalize_apn(apn: str) -> str:
        """SCPA PIDs are 17-char, MIXED alphanumeric (e.g. 2620305AR0D00003A or
        34213230000500000). Strip hyphens/dots/spaces but PRESERVE letters."""
        return re.sub(r"[^A-Za-z0-9]", "", apn or "").upper()

    # USPS suffix abbreviations — the live SCPA `PrimaryAddress` stores
    # abbreviated suffixes ("3136 SPLENDID STOWE LN LONGWOOD FL 32779"), so the
    # long form in the intake must be abbreviated for the prefix-LIKE to hit.
    _SUFFIX_ABBREV = {
        "LANE": "LN", "DRIVE": "DR", "STREET": "ST", "AVENUE": "AVE",
        "COURT": "CT", "ROAD": "RD", "BOULEVARD": "BLVD", "CIRCLE": "CIR",
        "PLACE": "PL", "TERRACE": "TER", "TRAIL": "TRL", "PARKWAY": "PKWY",
        "HIGHWAY": "HWY", "SQUARE": "SQ", "LOOP": "LOOP", "WAY": "WAY",
        "COVE": "CV", "POINT": "PT", "RIDGE": "RDG", "CROSSING": "XING",
    }

    @classmethod
    def normalize_address_for_lookup(cls, address: str) -> str:
        """Strip city/state/zip + ordinal suffixes and abbreviate the street
        suffix for ArcGIS LIKE matching (live-validated against PrimaryAddress).

        "3136 Splendid Stowe Lane, Longwood, FL 32779" -> "3136 SPLENDID STOWE LN"
        """
        addr = (address or "").upper()
        addr = addr.split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        addr = re.sub(r"\s+", " ", addr).strip()
        parts = addr.split(" ")
        if parts and parts[-1] in cls._SUFFIX_ABBREV:
            parts[-1] = cls._SUFFIX_ABBREV[parts[-1]]
        return " ".join(parts)

    # ----------------------------------------------------------- field helpers

    def _first(self, attrs: Dict[str, Any], canonical: str) -> Any:
        """Return the first present (non-empty) attribute value for a canonical key.

        Matching is case-insensitive against the configured candidate names AND a
        normalized form (strip non-alnum) so ArcGIS schema casing/underscore drift
        doesn't break the mapping.
        """
        candidates = self._field_map.get(canonical, [])
        # Build a normalized lookup of the feature attributes once.
        norm_attrs = { re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in attrs.items() }
        for cand in candidates:
            if cand in attrs and _nonempty(attrs[cand]):
                return attrs[cand]
            nk = re.sub(r"[^a-z0-9]", "", cand.lower())
            if nk in norm_attrs and _nonempty(norm_attrs[nk]):
                return norm_attrs[nk]
        return None

    # ----------------------------------------------------------- HTTP (Wave-2 wiring)

    def _query_arcgis(self, where: str) -> Dict[str, Any]:
        """Run an ArcGIS REST query. Raises on transport error; caller fails soft.

        Wave-2: requires `arcgis_query_url` to be configured. Until then this raises
        a clear RuntimeError so the failure surfaces as PA_FAILED with a useful note
        rather than a silent empty result.
        """
        if not self._arcgis_query_url:
            raise RuntimeError(
                "SCPA arcgis_query_url not configured — Wave-2 must resolve the "
                "Seminole parcel FeatureServer URL (see phase0_probe_pa.md)."
            )
        resp = self.session.get(
            self._arcgis_query_url,
            params={
                "where": where,
                "outFields": "*",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SCPA ArcGIS query HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    def _query_candidates(self, clause_template: str, field_candidates: List[str]):
        """Try each candidate field name in turn (one WHERE per field).

        ArcGIS returns ``{"error": {...}}`` (HTTP 200) for a WHERE referencing a
        nonexistent column — so OR-ing all aliases in one clause poisons the whole
        query (live-validated 2026-06-10). Returns (data, used_field) for the first
        candidate that yields features; (last_data, None) if none hit.
        """
        last_data: Dict[str, Any] = {}
        last_exc: Optional[Exception] = None
        got_valid_response = False
        for fname in field_candidates:
            try:
                data = self._query_arcgis(clause_template.format(field=fname))
            except Exception as exc:
                last_exc = exc
                continue
            if isinstance(data, dict) and data.get("error"):
                continue  # bad column / bad clause — try the next alias
            got_valid_response = True
            last_data = data
            if _features(data):
                return data, fname
        if not got_valid_response and last_exc is not None:
            # Every candidate transport-failed (e.g. HTTP 500) — surface it so the
            # caller reports PA_FAILED, not a misleading PA_NO_RESULTS.
            raise last_exc
        return last_data, None

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self.normalize_address_for_lookup(address)
        if not norm:
            return self._fail(f"empty address after normalize: {address!r}")
        if not self._arcgis_query_url:
            return self._fail(
                "SCPA arcgis_query_url not configured — Wave-2 must resolve the "
                "Seminole parcel FeatureServer URL (see phase0_probe_pa.md)."
            )
        situs_fields = self._field_map.get("situs", ["PrimaryAddress"])
        try:
            data, _used = self._query_candidates(
                "UPPER({field}) LIKE '" + _sql_escape(norm) + "%'", situs_fields
            )
        except Exception as exc:
            return self._fail(f"address query error: {type(exc).__name__}: {exc}")
        return self._result_from_features(data, context=f"address {norm!r}")

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        pid = self.normalize_apn(apn)
        if not pid:
            return self._fail(f"empty/invalid APN after normalize: {apn!r}")
        if not self._arcgis_query_url:
            return self._fail(
                "SCPA arcgis_query_url not configured — Wave-2 must resolve the "
                "Seminole parcel FeatureServer URL (see phase0_probe_pa.md).",
                apn=pid,
            )
        apn_fields = self._field_map.get("apn", ["Parcel"])
        try:
            data, _used = self._query_candidates(
                "UPPER({field}) = '" + _sql_escape(pid) + "'", apn_fields
            )
        except Exception as exc:
            return self._fail(f"APN query error: {type(exc).__name__}: {exc}", apn=pid)
        return self._result_from_features(data, context=f"APN {pid!r}")

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        owner_fields = self._field_map.get("owner", ["OwnerName"])
        name = _sql_escape((owner_name or "").upper().strip())
        if not name or not self._arcgis_query_url:
            return []
        try:
            data, _used = self._query_candidates(
                "UPPER({field}) LIKE '%" + name + "%'", owner_fields
            )
        except Exception:
            return []
        feats = _features(data)
        return [self._parse_arcgis_feature(f.get("attributes", {})) for f in feats[:25]]

    # ----------------------------------------------------------- result assembly

    def _result_from_features(self, data: Dict[str, Any], context: str) -> PropertyAppraiserResult:
        feats = _features(data)
        if not feats:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"SCPA ArcGIS returned no parcel for {context}",
                fetched_at=datetime.now().isoformat(),
            )
        if len(feats) > 1:
            # Try an exact-situs disambiguation before declaring ambiguous.
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"SCPA ArcGIS returned {len(feats)} candidates for {context}: "
                    + "; ".join(
                        str(self._first(f.get("attributes", {}), "apn") or "?")
                        for f in feats[:8]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_arcgis_feature(feats[0].get("attributes", {}))

    def _parse_arcgis_feature(self, attrs: Dict[str, Any]) -> PropertyAppraiserResult:
        apn = self.normalize_apn(str(self._first(attrs, "apn") or ""))
        owner = _str(self._first(attrs, "owner"))
        owner2 = _str(self._first(attrs, "owner2"))

        situs = _join_addr(
            _str(self._first(attrs, "situs")),
            _str(self._first(attrs, "situs_city")),
            _str(self._first(attrs, "situs_zip")),
        )
        mailing = _join_addr(
            _str(self._first(attrs, "mailing")),
            _str(self._first(attrs, "mailing2")),
        )
        result = PropertyAppraiserResult(
            apn=apn,
            pin=apn,
            owner_of_record=owner,
            co_owners=[owner2] if owner2 else [],
            situs_address=situs,
            mailing_address=mailing,
            legal_description=_str(self._first(attrs, "legal")),
            just_value=_safe_money(self._first(attrs, "just_value")),
            assessed_value=_safe_money(self._first(attrs, "assessed_value")),
            homestead_active=_homestead_active(self._first(attrs, "homestead")),
            year_built=_safe_int(self._first(attrs, "year_built")),
            living_area_sqft=_safe_int(self._first(attrs, "living_area")),
            source_url=(self._detail_base + f"?PID={apn}") if apn else self._detail_base,
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(attrs)
        return result

    def _parse_sales(self, attrs: Dict[str, Any]) -> List[SaleHistoryEntry]:
        """Pull up to _MAX_SALES flat suffixed sale columns, newest-first.

        Returns entries only for indices that carry a sale date. If the live layer
        instead nests sales in a related table (no suffixed columns), this returns []
        and Wave-2 wires a related-records query — the parser contract is unchanged.
        """
        norm_attrs = { re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in attrs.items() }

        def grab(key: str, i: int) -> Any:
            for tmpl in self._sale_field_map.get(key, []):
                name = tmpl.format(i=i)
                if name in attrs and _nonempty(attrs[name]):
                    return attrs[name]
                nk = re.sub(r"[^a-z0-9]", "", name.lower())
                if nk in norm_attrs and _nonempty(norm_attrs[nk]):
                    return norm_attrs[nk]
            return None

        sales: List[SaleHistoryEntry] = []
        for i in range(1, _MAX_SALES + 1):
            date = grab("date", i)
            if not _nonempty(date):
                continue
            book = _str(grab("book", i))
            page = _str(grab("page", i))
            book_page = f"{book} / {page}".strip(" /") if (book or page) else ""
            sales.append(
                SaleHistoryEntry(
                    sale_date=_fmt_date(date),
                    sale_price=_safe_money(grab("price", i)),
                    deed_doc_number=_str(grab("instrument", i)),
                    deed_book_page=book_page,
                    deed_type=_str(grab("deed_type", i)),
                    qualified=_qualified(grab("qualified", i)),
                    notes="",
                )
            )
        if sales:
            return sales
        # Live SCPA layer 19 carries only the MOST-RECENT sale (LastSaleDate /
        # LastSaleAmt). Emit it as a single entry so the PA anchor still gives
        # the reconciliation layer a vesting-deed cross-check. Full back-chain
        # comes from the recorder parcel re-search.
        last_date = self._first(attrs, "last_sale_date")
        if _nonempty(last_date):
            sales.append(
                SaleHistoryEntry(
                    sale_date=_fmt_date(last_date),
                    sale_price=_safe_money(self._first(attrs, "last_sale_amt")),
                    deed_doc_number="",
                    deed_book_page="",
                    deed_type="",
                    qualified=False,
                    notes="SCPA GIS layer exposes most-recent sale only; full chain from recorder parcel search",
                )
            )
        return sales

    # ----------------------------------------------------------- helpers

    def _fail(self, note: str, apn: str = "") -> PropertyAppraiserResult:
        return PropertyAppraiserResult(
            status="PA_FAILED",
            apn=apn,
            notes=note,
            fetched_at=datetime.now().isoformat(),
        )


# --------------------------------------------------------------- module helpers


def _features(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    feats = data.get("features")
    return feats if isinstance(feats, list) else []


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return s != "" and s.lower() not in ("null", "none")


def _str(v: Any) -> str:
    return str(v).strip() if _nonempty(v) else ""


def _sql_escape(s: str) -> str:
    return (s or "").replace("'", "''")


def _join_addr(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(round(float(re.sub(r"[^0-9.\-]", "", str(s)) or "0")))
    except Exception:
        return 0


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^0-9\-]", "", str(s)) or "0")
    except Exception:
        return 0


def _homestead_active(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    if s in ("Y", "YES", "TRUE", "1", "HX", "ACTIVE"):
        return True
    # numeric homestead exemption amount > 0 implies active
    n = _safe_money(v)
    return n > 0 and s not in ("N", "NO", "FALSE", "0", "NO HOMESTEAD")


def _qualified(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    return s in ("Q", "QUAL", "QUALIFIED", "Y", "YES", "01", "1")


def _fmt_date(v: Any) -> str:
    """Normalize ArcGIS sale dates to MM/DD/YYYY.

    ArcGIS date fields are epoch-milliseconds (int) or already-formatted strings.
    """
    if v is None:
        return ""
    # epoch-ms integer
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc).strftime("%m/%d/%Y")
        except Exception:
            return ""
    s = str(v).strip()
    if s.isdigit() and len(s) >= 12:  # epoch-ms as string
        try:
            return datetime.fromtimestamp(int(s) / 1000.0, tz=timezone.utc).strftime("%m/%d/%Y")
        except Exception:
            return s
    return s
