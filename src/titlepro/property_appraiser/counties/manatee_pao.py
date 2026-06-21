"""Manatee County (FL) Property Appraiser HTTP adapter (Phase 1a anchor).

Implementation derived from the 2026-05-27 probe (see /tmp/manateepao_probe.md).
The MCPAO public site at https://www.manateepao.gov/ ships a WordPress + Frontier
child theme. The parcel-detail page (`/prg/parcel/?parid=<P>`) is an empty shell
that the browser hydrates via per-purpose ``models/pao-model-*.php`` endpoints.
All endpoints return either JSON (`{cols, rows}` shape) or HTML fragments.

Critical endpoints used here
----------------------------
- ``models/pao-model-parcel-search-results.php`` (POST)
    payload: ``SearchQ=<JSON array of {name,value}>``, ``VisitorIP=<ip>``
    returns ``{cols, rows}`` with [Parcel ID, Property Type, Owner(s),
    Situs Address, Postal City] columns. Field names mirror the JSON spec at
    ``models/pao-model-parcel-search-form.php``: ``ParcelId``, ``Address``,
    ``OwnLast``, ``OwnFirst``, ``RollType``, ``Subdiv``, etc.
- ``models/pao-model-owner.php`` (POST)
    payload: ``data=<JSON {parid, ownerType, visitorIP, parcel_type}>``
    returns HTML fragment with labeled rows: Parcel ID, Ownership, Owner Type,
    Mailing Address, Situs Address, Tax District, Sec/Twp/Rge, Neighborhood,
    Subdivision, Short Description, FEMA Value, Land Use, Land Size,
    Building Area, Living Units.
- ``models/pao-model-sales.php?parid=<P>`` (GET)
    returns JSON with 11-col rows: Sale Date | BOOK | PAGE | Instrument Type |
    Vacant/Improved | Qualification Code | Sale Price | Grantee | qual_desc |
    instr_desc | InstrNo. Newest-first by Sale Date. ``BOOK/PAGE`` and
    ``InstrNo`` are both populated for modern conveyances; older deeds
    (pre-instrument-numbering) only have Book/Page.
- ``models/pao-model-value-history.php?parid=<P>`` (GET)
    returns JSON with per-year just/assessed values. Newest year is first.
- ``models/pao-model-exemptions.php?parid=<P>`` (GET)
    returns JSON; Homestead presence indicated by row with Description
    starting with "1010 HOMESTEAD".

Why HTTP not Playwright
-----------------------
``curl_cffi`` (chrome120 impersonate) passes every endpoint cleanly:
no Cloudflare, no CAPTCHA, no rate-limit observed in probe runs. This
matches Tony Roveda's directive #1 (no Selenium/Playwright in Phase 1).

For FERNANDEZ subject (PARID 1697719559) the live sale-history rows are:
  - 2018-02-28 WD Book 2716/2565 ($272,000) -> FERNANDEZ/ROZANES (vesting)
  - 2002-10-31 WD Book 1781/4691 ($187,000) -> TOIVANEN
  - 2000-11-15 SW Book 1657/4044 ($149,000) -> CIRRITO

This is exactly the back-chain the recorder-only path could not recover
(Manatee's electronic indexing starts 2007-01-02; the 2002 + 2000 deeds
are pre-window). PA exposes them via the assessor's sales table.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"

_BASE = (
    "https://www.manateepao.gov/wp-content/themes/frontier-child/models"
)
_DEFAULT_VISITOR_IP = "1.2.3.4"  # opaque per probe; portal does not validate

_INSTR_TYPE_FULL = {
    "WD": "Warranty Deed",
    "SW": "Special Warranty Deed",
    "QC": "Quit Claim Deed",
    "QCD": "Quit Claim Deed",
    "CT": "Certificate of Title",
    "PR": "Personal Representative Deed",
    "TD": "Trustee's Deed",
    "ED": "Executor's Deed",
}


class ManateePAO(AbstractPropertyAppraiser):
    """WordPress/Frontier-backed HTTP adapter for Manatee FL Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_manatee"
        self.county_name = "Manatee"
        self.source_label = config.get(
            "description", "Manatee County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._warmup_url = config.get(
            "warmup_url", "https://www.manateepao.gov/search/"
        )
        self._url_search = endpoints.get(
            "search_results",
            f"{_BASE}/pao-model-parcel-search-results.php",
        )
        self._url_owner = endpoints.get(
            "owner",
            f"{_BASE}/pao-model-owner.php",
        )
        self._url_sales = endpoints.get(
            "sales",
            f"{_BASE}/pao-model-sales.php",
        )
        self._url_addresses = endpoints.get(
            "addresses",
            f"{_BASE}/pao-model-addresses.php",
        )
        self._url_value_history = endpoints.get(
            "value_history",
            f"{_BASE}/pao-model-value-history.php",
        )
        self._url_exemptions = endpoints.get(
            "exemptions",
            f"{_BASE}/pao-model-exemptions.php",
        )

        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)
        self._visitor_ip = config.get("visitor_ip", _DEFAULT_VISITOR_IP)
        self._parcel_referer_tmpl = config.get(
            "parcel_referer_tmpl",
            "https://www.manateepao.gov/prg/parcel/?parid={parid}",
        )

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
            pass
        self._warmed = True

    def _ajax_headers(self, parid: Optional[str] = None) -> Dict[str, str]:
        ref = (
            self._parcel_referer_tmpl.format(parid=parid)
            if parid
            else self._warmup_url
        )
        return {
            "Referer": ref,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """MCPAO PARID is unhyphenated 10-digit numeric."""
        return re.sub(r"[^0-9]", "", apn or "")

    @staticmethod
    def _normalize_address_for_search(address: str) -> str:
        """Strip city/state/zip and ordinal suffixes for the Address typeahead."""
        addr = (address or "").upper()
        addr = addr.split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        # Drop street-type suffix — MCPAO Address search treats it as
        # part of the street and partial matches do better without it.
        # E.g. "4837 SABAL HARBOUR DR" -> "4837 SABAL HARBOUR" matched 1 row.
        addr = re.sub(r"\s+", " ", addr)
        return addr.strip()

    # ----------------------------------------------------------- helpers

    def _post_search(self, criteria: List[Dict[str, str]]) -> Dict[str, Any]:
        self._warm()
        body = {
            "SearchQ": json.dumps(criteria),
            "VisitorIP": self._visitor_ip,
        }
        resp = self.session.post(
            self._url_search,
            data=body,
            headers=self._ajax_headers(),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"MCPAO search returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"MCPAO search returned non-JSON: {exc}; first 200 chars: {resp.text[:200]!r}"
            )

    def _get_json(self, url: str, parid: str) -> Dict[str, Any]:
        resp = self.session.get(
            url,
            params={"parid": parid},
            headers=self._ajax_headers(parid),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"MCPAO {url} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        if not resp.text:
            return {"cols": [], "rows": []}
        try:
            return resp.json()
        except Exception:
            return {"cols": [], "rows": [], "_raw_text": resp.text}

    def _post_owner(self, parid: str) -> str:
        """POST the owner endpoint; returns HTML fragment."""
        payload = {
            "parid": parid,
            "ownerType": "",
            "visitorIP": self._visitor_ip,
            "parcel_type": "real_property",
        }
        body = {"data": json.dumps(payload)}
        headers = self._ajax_headers(parid)
        headers["Accept"] = "text/html, */*; q=0.01"
        resp = self.session.post(
            self._url_owner, data=body, headers=headers, timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"MCPAO owner returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.text or ""

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_search(address)
        try:
            results = self._post_search(
                [
                    {"name": "Address", "value": norm},
                    {"name": "RollType", "value": "REAL PROPERTY"},
                ]
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        rows = results.get("rows") or []
        cols = [c.get("title", "") for c in (results.get("cols") or [])]
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"MCPAO found no parcel matching address {norm!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # Prefer an exact street-match (situs cell embedded in column 3).
        situs_idx = cols.index("Situs Address") if "Situs Address" in cols else 3
        exact = [
            r for r in rows
            if isinstance(r[situs_idx], str) and norm in r[situs_idx].upper()
        ]
        if not exact and len(rows) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"MCPAO returned {len(rows)} candidates for {norm!r}: "
                    + "; ".join(
                        f"{r[situs_idx]} (parid {r[0]})"
                        for r in rows[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        chosen = (exact or rows)[0]
        parid = str(chosen[0])
        return self.lookup_by_apn(parid)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        parid = self._normalize_apn(apn)
        if not parid:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid PARID after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )

        try:
            owner_html = self._post_owner(parid)
            sales = self._get_json(self._url_sales, parid)
            addresses = self._get_json(self._url_addresses, parid)
            value_history = self._get_json(self._url_value_history, parid)
            exemptions = self._get_json(self._url_exemptions, parid)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"endpoint error: {type(exc).__name__}: {exc}",
                apn=parid,
                fetched_at=datetime.now().isoformat(),
            )

        if not owner_html.strip():
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"MCPAO owner endpoint returned empty for parid={parid!r}",
                apn=parid,
                fetched_at=datetime.now().isoformat(),
            )

        return self._build_result(
            parid=parid,
            owner_html=owner_html,
            sales=sales,
            addresses=addresses,
            value_history=value_history,
            exemptions=exemptions,
        )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search → list of results (capped at 25 to avoid runaways)."""
        if not owner_name:
            return []
        # Take last name as the primary key — the form treats OwnLast as
        # "Owner Last Name or Entity" and matches partial.
        last = owner_name.split(",", 1)[0].strip().split()[0]
        try:
            results = self._post_search(
                [
                    {"name": "OwnLast", "value": last.upper()},
                    {"name": "RollType", "value": "REAL PROPERTY"},
                ]
            )
        except Exception:
            return []
        rows = (results.get("rows") or [])[:25]
        out: List[PropertyAppraiserResult] = []
        for r in rows:
            try:
                parid = str(r[0])
                out.append(self.lookup_by_apn(parid))
            except Exception:
                continue
        return out

    # ----------------------------------------------------------- parsing

    @staticmethod
    def _owner_label_value(text: str, label: str) -> str:
        """Pull `<label>:` followed by a value line from the owner HTML text."""
        # Owner HTML is rendered with labels on one line and values on the
        # next. Tolerate both inline (`<label>: <val>`) and stacked layouts.
        patterns = [
            rf"{re.escape(label)}\s*:\s*\n\s*([^\n]+)",
            rf"{re.escape(label)}\s*:\s*([^\n]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                val = m.group(1).strip()
                # Drop any "Go to ... details on ... in a new tab" tail.
                val = re.split(r"\bGo to\b", val)[0].strip()
                return val
        return ""

    def _build_result(
        self,
        *,
        parid: str,
        owner_html: str,
        sales: Dict[str, Any],
        addresses: Dict[str, Any],
        value_history: Dict[str, Any],
        exemptions: Dict[str, Any],
    ) -> PropertyAppraiserResult:
        soup = BeautifulSoup(owner_html, "html.parser")
        owner_text = soup.get_text("\n", strip=True)

        ownership = self._owner_label_value(owner_text, "Ownership")
        # "FERNANDEZ, PABLO;  ROZANES, DANIELA"  -> primary + co-owners
        primary, co_owners = self._split_owners(ownership)

        situs = self._owner_label_value(owner_text, "Situs Address")
        # Addresses endpoint provides the canonical situs if owner block missed it.
        if not situs:
            addr_rows = addresses.get("rows") or []
            if addr_rows:
                situs = str(addr_rows[0][0]).strip()
        mailing = self._owner_label_value(owner_text, "Mailing Address")

        legal_short = self._owner_label_value(owner_text, "Short Description")
        subdivision = self._owner_label_value(owner_text, "Subdivision")
        if subdivision and not legal_short:
            legal_short = subdivision
        elif subdivision and subdivision not in legal_short:
            legal_short = f"{legal_short}  |  {subdivision}".strip("  |  ")

        # Value history: most recent year is row 0.
        vh_rows = value_history.get("rows") or []
        vh_cols = [c.get("title", "") for c in (value_history.get("cols") or [])]
        just_value = 0
        assessed_value = 0
        if vh_rows:
            r0 = vh_rows[0]
            just_value = _safe_money(_cell(r0, vh_cols, "Just/Market Value"))
            # Prefer Non-School Assessed Value (more conservative).
            assessed_value = _safe_money(_cell(r0, vh_cols, "Non-School Assessed Value"))
            if not assessed_value:
                assessed_value = _safe_money(_cell(r0, vh_cols, "School Assessed Value"))

        # Building Area: "2,381 SqFt Under Roof / 1,873 SqFt Living ..."
        liv_sqft = 0
        m = re.search(r"([\d,]+)\s*SqFt Living", owner_text, re.I)
        if m:
            liv_sqft = _safe_int(m.group(1))

        # Year built lives in buildings table; owner HTML's "Year Built" is the
        # primary residential block. Try owner text first, then 0.
        year_built = 0
        m = re.search(r"Year\s*Built\s*:?\s*\n?\s*(\d{4})", owner_text, re.I)
        if m:
            year_built = int(m.group(1))

        # Exemption detection: Homestead row with Description starting "1010 HOMESTEAD"
        exem_rows = exemptions.get("rows") or []
        exem_cols = [c.get("title", "") for c in (exemptions.get("cols") or [])]
        homestead_active = False
        homestead_amount = 0
        for r in exem_rows:
            desc = str(_cell(r, exem_cols, "Description") or "")
            if desc.strip().upper().startswith("1010 HOMESTEAD"):
                homestead_active = True
                homestead_amount = _safe_money(_cell(r, exem_cols, "cty"))
                break
        # Owner HTML also exposes "Homestead Exemption: Yes" in some renderings;
        # use as fallback signal.
        if not homestead_active:
            m = re.search(r"Homestead\s*Exemption\s*:?\s*\n?\s*Yes", owner_text, re.I)
            if m:
                homestead_active = True

        sale_history = self._parse_sales(sales)

        return PropertyAppraiserResult(
            apn=parid,
            folio=parid,
            owner_of_record=primary,
            co_owners=co_owners,
            situs_address=situs,
            mailing_address=mailing,
            legal_description=legal_short,
            just_value=just_value,
            assessed_value=assessed_value,
            homestead_active=homestead_active,
            homestead_amount=homestead_amount,
            year_built=year_built,
            living_area_sqft=liv_sqft,
            sale_history=sale_history,
            source_url=self._parcel_referer_tmpl.format(parid=parid),
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _split_owners(ownership: str) -> tuple:
        if not ownership:
            return "", []
        # MCPAO uses ';' (sometimes with extra spaces) as the owner separator.
        parts = [p.strip() for p in re.split(r";\s*", ownership) if p.strip()]
        if not parts:
            return "", []
        return parts[0], parts[1:]

    @staticmethod
    def _parse_sales(sales: Dict[str, Any]) -> List[SaleHistoryEntry]:
        cols = [c.get("title", "") for c in (sales.get("cols") or [])]
        rows = sales.get("rows") or []
        out: List[SaleHistoryEntry] = []
        for r in rows:
            date_raw = str(_cell(r, cols, "Sale Date") or "").strip()
            # MCPAO returns "2018-02-28 00:00:00" — normalize to MM/DD/YYYY.
            date_fmt = ""
            try:
                if date_raw:
                    dt = datetime.strptime(date_raw[:10], "%Y-%m-%d")
                    date_fmt = dt.strftime("%m/%d/%Y")
            except Exception:
                date_fmt = date_raw
            book = str(_cell(r, cols, "BOOK") or "").strip()
            page = str(_cell(r, cols, "PAGE") or "").strip()
            instr_no = str(_cell(r, cols, "InstrNo") or "").strip()
            instr_type = str(_cell(r, cols, "Instrument Type") or "").strip()
            instr_desc = str(_cell(r, cols, "instr_desc") or "").strip()
            qual_desc = str(_cell(r, cols, "qual_desc") or "").strip()
            price = _safe_money(_cell(r, cols, "Sale Price"))
            grantee = str(_cell(r, cols, "Grantee") or "").strip()
            deed_book_page = f"{book} / {page}" if (book and page) else ""
            deed_type_full = (
                instr_desc.title()
                if instr_desc
                else _INSTR_TYPE_FULL.get(instr_type.upper(), instr_type)
            )
            out.append(
                SaleHistoryEntry(
                    sale_date=date_fmt,
                    sale_price=price,
                    deed_doc_number=instr_no,
                    deed_book_page=deed_book_page,
                    deed_type=deed_type_full,
                    grantee=grantee,
                    qualified=("qualified" in qual_desc.lower()),
                    notes=qual_desc,
                )
            )
        # MCPAO returns newest-first per probe; do not reorder.
        return out


# ----------------------------------------------------------- helpers


def _cell(row: List[Any], cols: List[str], header: str) -> Any:
    """Return row cell by column header (case-insensitive)."""
    if not row or not cols:
        return None
    h_norm = header.lower().strip()
    for i, c in enumerate(cols):
        if str(c).lower().strip() == h_norm:
            return row[i] if i < len(row) else None
    return None


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(float(re.sub(r"[^\d.\-]", "", str(s)) or "0"))
    except Exception:
        return 0


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0


__all__ = ["ManateePAO"]
