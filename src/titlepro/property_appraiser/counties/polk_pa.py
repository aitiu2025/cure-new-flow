"""Polk County Property Appraiser HTTP adapter (Phase 1a anchor).

Platform: **custom ASP.NET WebForms CAMA** (Grizzly-Logic-style) at
``www.polkpa.org``. Unlike Broward (BCPA WebMethod JSON API) or Orange
(Azure SPA), Polk serves server-rendered HTML — parcel data is scraped from
``CamaDisplay.aspx`` and search uses an ``AdvancedQuerySearch.aspx``
``__VIEWSTATE`` round-trip.

Reverse-engineered 2026-06-10 from the Wayback snapshot of polkpa.org (the live
host is firewall/geo-fenced and was TCP-unreachable from the Wave-1 build egress;
see ``.../Polk_BUNKER_v1/phase0_probe_pa.md``). Because no live CamaDisplay.aspx
HTML could be captured, the **parser is label-driven and unit-tested against a
representative canned WebForms fixture**; the live HTTP flow is wired but returns
``PA_FAILED``/probe-pending until a real parcel page is captured Wave-2.

Mirrors ``broward_bcpa.py``:
  * Subclass of ``AbstractPropertyAppraiser`` (HTTP-only, fail-soft).
  * Returns a ``PropertyAppraiserResult`` with a valid status on every path.
  * Sale history newest-first (index 0 == most recent / vesting deed).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "safari17_2_ios"

# Label → canonical field. CamaDisplay.aspx renders parcel attributes as
# label/value pairs; we match on the visible label text (case-insensitive,
# whitespace-collapsed). Override per-deployment via config["field_labels"].
_FIELD_LABELS: Dict[str, List[str]] = {
    "owner_of_record": ["owner", "owner name", "owner of record", "primary owner"],
    "situs_address": ["site address", "situs address", "property address", "physical address"],
    "mailing_address": ["mailing address", "owner mailing address"],
    "legal_description": ["legal description", "brief legal", "short legal", "legal"],
    "just_value": ["just value", "just/market value", "market value", "total just value"],
    "assessed_value": ["assessed value", "total assessed value", "assessed"],
    "apn": ["parcel id", "parcel number", "parcel", "pin", "strap", "property id"],
}


class PolkPA(AbstractPropertyAppraiser):
    """ASP.NET WebForms HTML-scrape adapter for Polk County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_polk"
        self.county_name = "Polk"
        self.source_label = config.get("description", "Polk County Property Appraiser")

        self._base_url = config.get("base_url", "https://www.polkpa.org/").rstrip("/") + "/"
        endpoints = config.get("endpoints", {})
        self._url_cama_display = endpoints.get(
            "cama_display", "https://www.polkpa.org/CamaDisplay.aspx"
        )
        self._url_advanced_search = endpoints.get(
            "advanced_search", "https://www.polkpa.org/AdvancedQuerySearch.aspx"
        )
        # CamaDisplay parcel-detail querystring template. The exact param names
        # are probe-pending (Wave-2); this is the Grizzly-typical form.
        self._cama_parcel_tmpl = endpoints.get(
            "cama_parcel_template",
            "https://www.polkpa.org/CamaDisplay.aspx?OutputMode=Display&SearchType=RealEstate&ParcelID={apn}",
        )

        self._field_labels = {**_FIELD_LABELS, **(config.get("field_labels") or {})}
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)
        self._tax_year = str(config.get("tax_year") or (datetime.now().year - 1))

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
            self.session.get(self._base_url, timeout=30)
        except Exception:
            pass  # best-effort
        self._warmed = True

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """Polk strap is typically ``NN-NN-NN-NNNNNN-NNNNNN``. Keep hyphens but
        strip surrounding whitespace; collapse internal runs of spaces."""
        return re.sub(r"\s+", "", (apn or "").strip())

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        return re.sub(r"\s+", " ", addr).strip()

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Address search via AdvancedQuerySearch.aspx (WebForms __VIEWSTATE POST).

        The live POST handshake is probe-pending (host unreachable Wave-1), so
        this surfaces PA_AMBIGUOUS with the search landing URL — callers should
        resolve the APN from the recorder/PA Wave-2 and use ``lookup_by_apn``.
        """
        norm = self._normalize_address_for_lookup(address)
        return PropertyAppraiserResult(
            status="PA_AMBIGUOUS",
            notes=(
                "Polk PA address search requires an ASP.NET __VIEWSTATE POST to "
                f"{self._url_advanced_search} that is not yet reverse-engineered "
                f"(host firewall-blocked from Wave-1 egress). Normalized address: "
                f"{norm!r}. Use lookup_by_apn() with the parcel strap once resolved."
            ),
            situs_address=norm,
            source_url=self._url_advanced_search,
            fetched_at=datetime.now().isoformat(),
        )

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        strap = self._normalize_apn(apn)
        if not strap:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )
        self._warm()
        url = self._cama_parcel_tmpl.format(apn=strap)
        try:
            resp = self.session.get(url, timeout=30)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                apn=strap,
                notes=f"CamaDisplay GET error ({type(exc).__name__}): {exc}. "
                      f"Host likely firewall-blocked (Wave-1) — retry from US egress.",
                source_url=url,
                fetched_at=datetime.now().isoformat(),
            )
        if resp.status_code != 200:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                apn=strap,
                notes=f"CamaDisplay returned HTTP {resp.status_code}",
                source_url=url,
                fetched_at=datetime.now().isoformat(),
            )
        return self.parse_parcel_html(resp.text, apn=strap, source_url=url)

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Owner search also requires the WebForms POST handshake — diagnostics
        # only; return [] rather than guess.
        return []

    # ----------------------------------------------------------- parse

    def parse_parcel_html(
        self, html: str, apn: str = "", source_url: str = ""
    ) -> PropertyAppraiserResult:
        """Parse a CamaDisplay.aspx parcel page into a PropertyAppraiserResult.

        Label-driven and tolerant of the exact WebForms markup — matches
        label/value pairs and a sales-history table. Fully offline-testable.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        fields = self._extract_label_values(soup)

        resolved_apn = self._normalize_apn(fields.get("apn") or apn)
        result = PropertyAppraiserResult(
            apn=resolved_apn,
            folio=resolved_apn,
            owner_of_record=(fields.get("owner_of_record") or "").strip(),
            situs_address=(fields.get("situs_address") or "").strip(),
            mailing_address=(fields.get("mailing_address") or "").strip(),
            legal_description=(fields.get("legal_description") or "").strip(),
            just_value=_safe_money(fields.get("just_value")),
            assessed_value=_safe_money(fields.get("assessed_value")),
            source_url=source_url or self._cama_parcel_tmpl.format(apn=resolved_apn),
            status="PA_SUCCESS" if (resolved_apn or fields.get("owner_of_record")) else "PA_NO_RESULTS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales_html(soup)
        if result.status == "PA_NO_RESULTS":
            result.notes = "CamaDisplay HTML parsed but no owner/APN fields matched the label map."
        return result

    def _extract_label_values(self, soup) -> Dict[str, str]:
        """Walk the document collecting label→value pairs.

        Handles two common WebForms layouts:
        (a) ``<td class="label">Owner</td><td class="value">SMITH JOHN</td>``
        (b) ``<span id="...Label">Owner:</span><span id="...Value">SMITH JOHN</span>``
        """
        out: Dict[str, str] = {}

        def match_canonical(label_text: str) -> Optional[str]:
            lt = re.sub(r"\s+", " ", (label_text or "").strip().rstrip(":").lower())
            for canonical, labels in self._field_labels.items():
                if lt in labels:
                    return canonical
            # prefix/substring fallback for slightly different phrasings
            for canonical, labels in self._field_labels.items():
                for lab in labels:
                    if lt == lab or lt.startswith(lab + " "):
                        return canonical
            return None

        # Layout (a): table rows with two cells.
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) == 2:
                canonical = match_canonical(cells[0].get_text(" ", strip=True))
                if canonical and canonical not in out:
                    out[canonical] = cells[1].get_text(" ", strip=True)

        # Layout (b): adjacent label/value spans/divs.
        labelish = soup.find_all(["span", "div", "label"])
        for i, el in enumerate(labelish):
            txt = el.get_text(" ", strip=True)
            canonical = match_canonical(txt)
            if canonical and canonical not in out:
                # value is the next sibling element with text
                sib = el.find_next(["span", "div", "td"])
                if sib is not None:
                    val = sib.get_text(" ", strip=True)
                    if val and val.lower() != txt.lower():
                        out[canonical] = val
        return out

    def _parse_sales_html(self, soup) -> List[SaleHistoryEntry]:
        """Extract a sales-history table. Looks for a table whose header row
        mentions a sale date + a deed/book-page column. Newest-first."""
        sales: List[SaleHistoryEntry] = []
        for table in soup.find_all("table"):
            header = table.find("tr")
            if not header:
                continue
            heads = [h.get_text(" ", strip=True).lower() for h in header.find_all(["th", "td"])]
            if not heads:
                continue
            joined = " ".join(heads)
            if "sale" not in joined and "date" not in joined:
                continue
            if not any(k in joined for k in ("deed", "book", "page", "instrument", "or ")):
                continue
            idx = _column_index(heads)
            for tr in header.find_next_siblings("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not cells or len(cells) < 2:
                    continue
                date = _col(cells, idx.get("date"))
                if not date or not re.search(r"\d", date):
                    continue
                bp = _col(cells, idx.get("book_page"))
                deed_doc_number, deed_book_page = "", ""
                if bp:
                    if "/" in bp or re.search(r"\bpg\b|\bpage\b", bp.lower()):
                        deed_book_page = bp
                    else:
                        deed_doc_number = bp
                sales.append(
                    SaleHistoryEntry(
                        sale_date=date,
                        sale_price=_safe_money(_col(cells, idx.get("price"))),
                        deed_type=_col(cells, idx.get("deed_type")),
                        deed_doc_number=deed_doc_number,
                        deed_book_page=deed_book_page,
                        grantor=_col(cells, idx.get("grantor")),
                        notes="",
                    )
                )
            if sales:
                break  # first matching sales table wins
        return sales


# ----------------------------------------------------------- helpers


def _column_index(heads: List[str]) -> Dict[str, int]:
    """Map semantic columns to indices from a sales-table header row."""
    idx: Dict[str, int] = {}
    for i, h in enumerate(heads):
        if "date" in h and "date" not in idx:
            idx["date"] = i
        elif ("price" in h or "amount" in h or "consideration" in h) and "price" not in idx:
            idx["price"] = i
        elif ("deed" in h or "instrument" in h or "type" in h) and "deed_type" not in idx:
            idx["deed_type"] = i
        elif ("book" in h or "page" in h or "or " in h or "cin" in h) and "book_page" not in idx:
            idx["book_page"] = i
        elif ("grantor" in h or "seller" in h or "from" in h) and "grantor" not in idx:
            idx["grantor"] = i
    return idx


def _col(cells: List[str], i: Optional[int]) -> str:
    if i is None or i >= len(cells):
        return ""
    return cells[i].strip()


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0
