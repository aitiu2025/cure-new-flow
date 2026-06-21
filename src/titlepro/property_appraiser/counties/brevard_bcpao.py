"""Brevard County Property Appraiser (BCPAO) HTTP adapter (Phase 1a anchor).

Mirrors ``broward_bcpa.py`` but targets BCPAO's documented REST JSON API
(``https://www.bcpao.us/api/v1/...``) rather than Broward's ASP.NET WebMethod
shape. BCPAO returns clean top-level JSON (no ``{"d": ...}`` wrapper).

Endpoints (BCPAO public API v1)
-------------------------------
  - GET /api/v1/search?address={addr}&activeonly=true&size={n}&page={n}
        → list of summary rows: [{account, parcelID, siteAddress, owners:[...]}, ...]
  - GET /api/v1/account/{accountNumber}
        → full parcel detail incl. salesList[], valueSummary, legalDescription.
  - GET /api/v1/search?parcel={pid}   (alternate key form)

⚠️  CLOUDFLARE BLOCKER (probed 2026-06-10, case Brevard_LEWIS_v1):
    www.bcpao.us is fronted by a Cloudflare MANAGED CHALLENGE that curl_cffi
    cannot pass for ANY impersonation profile (safari17_2_ios/safari18_0/
    chrome120-131/firefox133/edge101 all return 403 with the CF interstitial).
    This is a stronger posture than Broward's recorder (which safari17_2_ios
    passes). To go live, inject a browser-minted ``cf_clearance`` cookie via the
    ``cookies`` kwarg (TTL ~30d) — same playbook the Broward recorder uses. The
    adapter + tests are otherwise complete and exercise the BCPAO JSON contract
    on canned fixtures.

Tony Roveda Phase-1a: the PA anchor delivers the APN + owner-of-record +
sale-history back-chain that name-only recorder searches can't recover. For
LEWIS the recorder already surfaced the vesting deed (instr 1996067410); the
BCPAO sale-history is still required for the Title E2/E3 APN-anchor blocks.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


# BCPAO's Cloudflare is stricter than Broward — safari iOS is the best chance
# once a cf_clearance cookie is present; default to it.
_DEFAULT_IMPERSONATE = "safari17_2_ios"
_JSON_HEADERS = {"Accept": "application/json, text/plain, */*"}


class BrevardBCPAO(AbstractPropertyAppraiser):
    """REST JSON adapter for Brevard County Property Appraiser (bcpao.us)."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_brevard"
        self.county_name = "Brevard"
        self.source_label = config.get(
            "description", "Brevard County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._base = config.get("base_url", "https://www.bcpao.us/api/v1/").rstrip("/") + "/"
        self._warmup_url = config.get("warmup_url", "https://www.bcpao.us/PropertySearch/")
        self._url_search = endpoints.get("search", self._base + "search")
        self._url_account = endpoints.get("account", self._base + "account")
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)
        # Optional browser-minted CF clearance cookies (the live-run unblock).
        self._cf_cookies: Dict[str, str] = config.get("cf_cookies") or {}
        self._referer = config.get("referer", "https://www.bcpao.us/")

        self._session: Optional[Any] = None
        self._warmed = False

    # ----------------------------------------------------------- session

    @property
    def session(self):
        if self._session is None:
            self._session = _cffi_requests.Session(impersonate=self._impersonate)
            for name, value in self._cf_cookies.items():
                self._session.cookies.set(name, value)
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
            pass
        self._warmed = True

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._warm()
        resp = self.session.get(
            url,
            params=params,
            headers={**_JSON_HEADERS, "Referer": self._referer},
            timeout=30,
        )
        if resp.status_code != 200:
            snippet = (resp.text or "")[:160]
            hint = ""
            if "cloudflare" in snippet.lower() or resp.status_code == 403:
                hint = " (Cloudflare challenge — inject browser-minted cf_clearance via config['cf_cookies'])"
            raise RuntimeError(f"BCPAO {url} returned HTTP {resp.status_code}{hint}: {snippet}")
        return resp.json()

    # ----------------------------------------------------------- normalize

    # Street-type abbreviations so "AVENUE" and "AVE" compare equal. Applied
    # to BOTH the query and the BCPAO row site address before matching.
    _STREET_TYPE_ABBREV = {
        "AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR",
        "LANE": "LN", "BOULEVARD": "BLVD", "COURT": "CT", "PLACE": "PL",
        "CIRCLE": "CIR", "TERRACE": "TER", "TRAIL": "TRL", "PARKWAY": "PKWY",
        "HIGHWAY": "HWY", "SQUARE": "SQ", "WAY": "WAY",
    }

    @classmethod
    def _normalize_address_for_lookup(cls, address: str) -> str:
        """Strip city/state/zip and canonicalize street-type suffixes so the
        BCPAO indexed form matches regardless of AVE/AVENUE spelling. Example:
          "977 Hammacher Avenue SW, Palm Bay, FL 32908" → "977 HAMMACHER AVE SW"
        """
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"\s+", " ", addr).strip()
        tokens = [cls._STREET_TYPE_ABBREV.get(t, t) for t in addr.split(" ")]
        return " ".join(tokens).strip()

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """BCPAO 'account' is a numeric string; parcel IDs may be dotted/dashed.
        We strip non-alphanumerics for the account form but preserve the raw
        value when it isn't purely numeric (parcel-id form passes through).
        """
        raw = (apn or "").strip()
        digits = re.sub(r"[^0-9]", "", raw)
        # If the original was purely a hyphenated/spaced number, return digits.
        if raw and re.fullmatch(r"[0-9\-\. ]+", raw):
            return digits
        return raw

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        try:
            rows = self._get_json(
                self._url_search,
                {"address": norm, "activeonly": "true", "size": "20", "page": "1"},
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        rows = self._coerce_list(rows)
        rows = [r for r in rows if self._row_account(r)]
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"BCPAO found no parcel matching address {norm!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # Prefer a site-address match (street-type-canonicalized both sides).
        exact = [
            r for r in rows
            if self._normalize_address_for_lookup(self._row_site(r)).startswith(norm)
        ]
        if not exact and len(rows) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"BCPAO returned {len(rows)} candidates for {norm!r}: "
                    + "; ".join(
                        f"{self._row_site(r) or '?'} (acct {self._row_account(r)})"
                        for r in rows[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        chosen = (exact or rows)[0]
        return self.lookup_by_apn(self._row_account(chosen))

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        account = self._normalize_apn(apn)
        if not account:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            data = self._get_json(f"{self._url_account}/{account}")
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"account lookup error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        # BCPAO may return a single object or a one-element list.
        if isinstance(data, list):
            data = data[0] if data else {}
        if not data:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"BCPAO returned empty parcel for account={account!r}",
                apn=account,
                folio=account,
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_parcel(data, account)

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Diagnostics-only; BCPAO owner search needs disambiguation. Return [].
        return []

    # ----------------------------------------------------------- parse

    def _parse_parcel(self, p: Dict[str, Any], account_fallback: str) -> PropertyAppraiserResult:
        account = str(
            p.get("account") or p.get("accountNumber") or account_fallback or ""
        ).strip()
        parcel_id = str(p.get("parcelID") or p.get("parcelNo") or p.get("parcel") or "").strip()

        owners = self._parse_owners(p)
        owner_of_record = owners[0] if owners else ""
        co_owners = owners[1:] if len(owners) > 1 else []

        site = self._first_str(p, ["siteAddress", "siteAddressFull", "situs", "propertyAddress"])
        mailing = self._parse_mailing(p)
        legal = self._first_str(p, ["legalDescription", "legal", "shortLegal"])

        just_value, assessed_value = self._parse_values(p)
        hs_amount, hs_active = self._parse_homestead(p)

        result = PropertyAppraiserResult(
            apn=parcel_id or account,
            folio=account,
            pin=parcel_id,
            owner_of_record=owner_of_record,
            co_owners=co_owners,
            situs_address=site,
            mailing_address=mailing,
            legal_description=legal,
            just_value=just_value,
            assessed_value=assessed_value,
            homestead_amount=hs_amount,
            homestead_active=hs_active,
            year_built=_safe_int(self._first_str(p, ["yearBuilt", "actualYearBuilt"])),
            living_area_sqft=_safe_int(self._first_str(p, ["livingArea", "totalLivingArea", "underAirSqFt"])),
            source_url=f"https://www.bcpao.us/PropertySearch/#/parcel/{account}",
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(p)
        return result

    @staticmethod
    def _parse_owners(p: Dict[str, Any]) -> List[str]:
        # Live shape (2026-06-10): account detail carries `ownerNames`
        # [{ownerName, ownerSequence, primaryOwner}] plus a flat `owner` str;
        # search rows carry `owners` as a flat string.
        out: List[str] = []
        owner_names = p.get("ownerNames")
        if isinstance(owner_names, list):
            for o in owner_names:
                if isinstance(o, dict):
                    name = (o.get("ownerName") or o.get("name") or "").strip()
                    if name:
                        out.append(name)
        if not out:
            owners = p.get("owners")
            if isinstance(owners, list):
                for o in owners:
                    if isinstance(o, dict):
                        name = (o.get("name") or o.get("ownerName") or "").strip()
                    else:
                        name = str(o).strip()
                    if name:
                        out.append(name)
            elif isinstance(owners, str) and owners.strip():
                out.append(owners.strip())
        if not out:
            single = (p.get("ownerName") or p.get("owner") or "").strip()
            if single:
                out.append(single)
        return out

    @staticmethod
    def _parse_mailing(p: Dict[str, Any]) -> str:
        m = p.get("mailingAddress")
        if isinstance(m, dict):
            # Live shape carries a pre-built `formatted` string.
            if m.get("formatted"):
                return re.sub(r"\s+", " ", str(m["formatted"])).strip()
            parts = [m.get(k, "") for k in ("addressLine1", "addressLine2", "cityStateZip",
                                            "addr1", "addr2", "city", "state", "zip")]
            return ", ".join(s.strip() for s in parts if s and str(s).strip())
        if isinstance(m, list):
            return ", ".join(s.strip() for s in m if s and str(s).strip())
        return (m or "").strip() if isinstance(m, str) else ""

    @staticmethod
    def _parse_values(p: Dict[str, Any]) -> tuple[int, int]:
        # BCPAO value summary may be a list (per tax year, newest first) or flat.
        # Live field names (2026-06-10): marketVal / assessedVal (suffix 1/2 =
        # prior years). Fixture/back-compat names also accepted.
        vs = p.get("valueSummary") or p.get("valueSummaryList")
        if isinstance(vs, list) and vs:
            vs = vs[0]
        if isinstance(vs, dict):
            jv = _safe_money(
                vs.get("marketVal") or vs.get("marketValue")
                or vs.get("justValue") or vs.get("market")
            )
            av = _safe_money(
                vs.get("assessedVal") or vs.get("assessedValue") or vs.get("assessed")
            )
            if jv or av:
                return jv, av
        return (
            _safe_money(p.get("marketValue") or p.get("justValue")),
            _safe_money(p.get("assessedValue")),
        )

    @staticmethod
    def _parse_homestead(p: Dict[str, Any]) -> tuple[int, bool]:
        exemptions = p.get("exemptions")
        amount = 0
        active = False
        if isinstance(exemptions, list):
            for e in exemptions:
                if isinstance(e, dict):
                    desc = (e.get("description") or e.get("type") or e.get("code") or "").upper()
                    if "HOMESTEAD" in desc or desc.startswith("HEX"):
                        active = True
                        amount = max(amount, _safe_money(e.get("amount") or e.get("value")))
                elif isinstance(e, str) and "HOMESTEAD" in e.upper():
                    active = True
        # Live shape: dollar amounts live in valueSummary (homesteadEx +
        # addlHomesteadEx) rather than on the exemption rows.
        if active and not amount:
            vs = p.get("valueSummary") or p.get("valueSummaryList")
            if isinstance(vs, list) and vs:
                vs = vs[0]
            if isinstance(vs, dict):
                amount = _safe_money(vs.get("homesteadEx")) + _safe_money(vs.get("addlHomesteadEx"))
        flag = p.get("homestead")
        if isinstance(flag, bool):
            active = active or flag
        return amount, active

    @staticmethod
    def _format_sale_date(raw: str) -> str:
        """Normalize ISO ('1996-04-30T00:00:00') or US dates to MM/DD/YYYY."""
        raw = (raw or "").strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
        return raw

    def _parse_sales(self, p: Dict[str, Any]) -> List[SaleHistoryEntry]:
        sales_raw = (
            p.get("salesHistory") or p.get("salesList")
            or p.get("sales") or p.get("saleHistory") or []
        )
        sales: List[SaleHistoryEntry] = []
        if not isinstance(sales_raw, list):
            return sales
        for s in sales_raw:
            if not isinstance(s, dict):
                continue
            date = self._first_str(s, ["saleDate", "date", "dateOfSale"])
            if not date:
                continue
            book = self._first_str(s, ["book", "orBook"])
            page = self._first_str(s, ["page", "orPage"])
            instrument = self._first_str(s, ["orInstrument", "instrument", "cin", "instrumentNumber"])
            book_page = ""
            if book and page:
                book_page = f"{book}/{page}"
            qual_raw = s.get("qualified")
            if isinstance(qual_raw, bool):
                qualified = qual_raw
            else:
                qualified = str(
                    self._first_str(s, ["qualification", "saleQual", "qualified"])
                ).lower() in ("qualified", "qualified sale", "true", "q")
            sales.append(
                SaleHistoryEntry(
                    sale_date=self._format_sale_date(date),
                    sale_price=_safe_money(self._first_str(s, ["price", "salePrice", "amount"])),
                    deed_doc_number=instrument,
                    deed_book_page=book_page,
                    deed_type=self._first_str(s, ["deedCode", "deedType", "saleType", "type"]),
                    qualified=qualified,
                    notes=self._first_str(s, ["deedDesc", "qualification", "saleQual"]),
                )
            )
        return sales

    # ----------------------------------------------------------- row helpers

    @staticmethod
    def _coerce_list(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            # Some BCPAO search wrappers nest under 'results' / 'data'.
            for key in ("results", "data", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
            return [data]
        return []

    @staticmethod
    def _row_account(r: Dict[str, Any]) -> str:
        return str(r.get("account") or r.get("accountNumber") or r.get("parcelID") or "").strip()

    @staticmethod
    def _row_site(r: Dict[str, Any]) -> str:
        return str(r.get("siteAddress") or r.get("situs") or r.get("propertyAddress") or "").strip()

    @staticmethod
    def _first_str(d: Dict[str, Any], keys: List[str]) -> str:
        for k in keys:
            v = d.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""


# ----------------------------------------------------------- helpers


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        cleaned = re.sub(r"[^\d.]", "", str(s))
        if not cleaned:
            return 0
        return int(float(cleaned))
    except Exception:
        return 0


def _safe_int(s: Any) -> int:
    if s is None or s == "":
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0
