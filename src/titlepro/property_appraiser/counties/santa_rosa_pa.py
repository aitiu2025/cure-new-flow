"""Santa Rosa County (FL) Property Appraiser HTTP adapter.

Platform: Remix React SPA (search.srcpa.gov) + Astro SSR parcel detail
          (parcelview.srcpa.gov)
Cloudflare/bot protection: None — datacenter IP is fine, no TOU gate.

Two-step flow:
  1. **Search** — POST ``https://search.srcpa.gov/property/query`` with form
     fields: name (LAST FIRST), street, parcelId, plus required stubs
     quickSearchParam, useQuickSearch, parameterMatch.
     Response JSON: ``{results: [{parcelKey, parcelNumber, ownerName,
     situsAddress, homestead, vacantImproved, zoning, checked}]}``.

  2. **Detail** — GET
     ``https://parcelview.srcpa.gov/?parcel=<URL-encoded-parcelNumber>
     &baseUrl=http://srcpa.gov/``
     Returns 121 KB Remix / Astro HTML with all parcel data.  Parsed via
     ``soup.get_text("\\n")`` label → next-non-empty-line pattern.

Live-validated test case (2026-06-18):
  - TIMOTHY WHITE, 1009 RIN CT, MILTON, FL 32583
  - parcelNumber: 23-1S-28-0003-00A00-0170, parcelKey: 10097741
  - just_value: 248159, assessed_value: 156483, homestead: True
  - Sale 01/12/2015 $152,500 WD Book 3400/80 grantor=FEDERAL NATIONAL MORTGAGE
    ASSOCIATION grantee=WHITE TIMOTHY

HTTP-only via curl_cffi (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_SEARCH_BASE = "https://search.srcpa.gov"
_DEFAULT_DETAIL_BASE = "https://parcelview.srcpa.gov"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+(?:\.\d{2})?)\)?")


def _money(s: str) -> int:
    """Parse a dollar string like '$248,159' → 248159."""
    m = _MONEY_RE.search(s or "")
    if not m:
        return 0
    return int(m.group(1).replace(",", "").split(".")[0])


class SantaRosaPA(AbstractPropertyAppraiser):
    """Santa Rosa County (FL) Property Appraiser — Remix/Astro SPA adapter."""

    SOURCE_LABEL = "Santa Rosa County Property Appraiser"
    LIVE_PLATFORM = "santa_rosa_pa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_santa_rosa")
        self.county_name = self.config.get("county_name", "Santa Rosa")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        self._search_base = (
            self.config.get("base_url") or _DEFAULT_SEARCH_BASE
        ).rstrip("/")
        self._detail_base = (
            self.config.get("parcelview_url") or _DEFAULT_DETAIL_BASE
        ).rstrip("/")
        self._search_url = f"{self._search_base}/property/query"

    # ----------------------------------------------------------------- network

    def _session(self):
        from curl_cffi import requests as cffi  # local import; optional dep
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    def _detail_url(self, parcel_number: str) -> str:
        return (
            f"{self._detail_base}/?parcel={quote(parcel_number, safe='')}"
            f"&baseUrl=http://srcpa.gov/"
        )

    # --------------------------------------------------------------- parsing

    @staticmethod
    def _parse_search_json(data: dict) -> List[Dict[str, Any]]:
        """Normalize the /property/query JSON response into a list of dicts."""
        try:
            return list(data.get("results") or [])
        except Exception:
            return []

    @staticmethod
    def parse_detail_html(html: str) -> PropertyAppraiserResult:
        """Parse a parcelview.srcpa.gov detail page into a PropertyAppraiserResult.

        Side-effect-free for unit testing: accepts raw HTML, returns result.
        Parsing strategy: soup.get_text("\\n") → label → next-non-empty-line.
        """
        result = PropertyAppraiserResult()
        if not html or len(html) < 100:
            result.status = "PA_FAILED"
            result.notes = "parse_detail_html: empty or too-short response"
            result.fetched_at = datetime.now().isoformat()
            return result
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            full_text = soup.get_text("\n")
            lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]

            # ----------------------------------------------------------
            # Helper: return first non-empty line after a label match
            # ----------------------------------------------------------
            def _next_after(label: str, text_lines: List[str],
                            start: int = 0) -> str:
                for i in range(start, len(text_lines)):
                    if text_lines[i] == label:
                        for j in range(i + 1, min(i + 6, len(text_lines))):
                            val = text_lines[j]
                            if val and val != label:
                                return val
                return ""

            def _next_after_re(pattern: str, text_lines: List[str],
                               start: int = 0) -> str:
                for i in range(start, len(text_lines)):
                    if re.search(pattern, text_lines[i], re.I):
                        for j in range(i + 1, min(i + 6, len(text_lines))):
                            val = text_lines[j]
                            if val and not re.search(pattern, val, re.I):
                                return val
                return ""

            # ----------------------------------------------------------
            # Identity fields
            # ----------------------------------------------------------
            result.apn = _next_after("Parcel Number", lines)
            result.situs_address = _next_after("Situs/Physical Address", lines)

            # Owner: "Primary Owner" label → owner name on next line,
            # then address lines follow.
            primary_owner_idx = next(
                (i for i, ln in enumerate(lines) if ln == "Primary Owner"), -1
            )
            if primary_owner_idx != -1 and primary_owner_idx + 1 < len(lines):
                result.owner_of_record = lines[primary_owner_idx + 1]
                # Mailing address: next 1-2 lines after owner name
                mail_parts = []
                for j in range(primary_owner_idx + 2,
                               min(primary_owner_idx + 5, len(lines))):
                    val = lines[j]
                    # Stop at the next known section header
                    if re.match(
                        r"^(Parcel Number|Situs|Property Usage|Section|"
                        r"Acreage|Exemptions|Brief Legal|Just|Sales|Map)",
                        val, re.I
                    ):
                        break
                    mail_parts.append(val)
                result.mailing_address = ", ".join(mail_parts)

            result.legal_description = _next_after("Brief Legal Description", lines)

            # ----------------------------------------------------------
            # Homestead
            # ----------------------------------------------------------
            exemptions_idx = next(
                (i for i, ln in enumerate(lines) if ln == "Exemptions"), -1
            )
            if exemptions_idx != -1:
                for j in range(exemptions_idx + 1,
                               min(exemptions_idx + 6, len(lines))):
                    if re.search(r"homestead", lines[j], re.I):
                        result.homestead_active = True
                        break

            # ----------------------------------------------------------
            # Just (Market) Value — three year columns; take the last one
            # ----------------------------------------------------------
            jv_idx = next(
                (i for i, ln in enumerate(lines)
                 if ln == "Just (Market) Value"), -1
            )
            if jv_idx != -1:
                money_vals = []
                for j in range(jv_idx + 1, min(jv_idx + 10, len(lines))):
                    ln = lines[j]
                    if ln.startswith("$") or re.match(r"^\$?[\d,]+$", ln):
                        v = _money(ln)
                        if v > 0:
                            money_vals.append(v)
                    elif money_vals:
                        # Stop on first non-money line after we've seen values
                        break
                if money_vals:
                    result.just_value = money_vals[-1]  # last = most recent year

            # ----------------------------------------------------------
            # Co. Assessed Value — same three-column pattern
            # ----------------------------------------------------------
            av_idx = next(
                (i for i, ln in enumerate(lines)
                 if ln == "Co. Assessed Value"), -1
            )
            if av_idx != -1:
                money_vals = []
                for j in range(av_idx + 1, min(av_idx + 10, len(lines))):
                    ln = lines[j]
                    if ln.startswith("$") or re.match(r"^\$?[\d,]+$", ln):
                        v = _money(ln)
                        if v > 0:
                            money_vals.append(v)
                    elif money_vals:
                        break
                if money_vals:
                    result.assessed_value = money_vals[-1]

            # ----------------------------------------------------------
            # Sales section
            # Columns: Multi-Parcel | Sale Date | Sale Price | Instrument
            #          | Book / Page | Qualification | Sale Type | Grantor | Grantee
            # The "Multi-Parcel" column value is "N" or "Y".
            # Lines after "Sales" header up to "Map" header.
            # ----------------------------------------------------------
            sales_start = next(
                (i for i, ln in enumerate(lines) if ln == "Sales"), -1
            )
            sales_end = next(
                (i for i, ln in enumerate(lines)
                 if i > sales_start and re.match(r"^Map$", ln, re.I)),
                len(lines),
            ) if sales_start != -1 else -1

            if sales_start != -1:
                sale_lines = lines[sales_start + 1: sales_end]
                # Skip column-header lines (non-data)
                _HEADER_TOKENS = {
                    "Multi-Parcel", "Sale Date", "Sale Price", "Instrument",
                    "Book", "Page", "Qualification", "Sale Type", "Grantor",
                    "Grantee", "/",
                }
                # Each sale record: N/Y, date, price, deed_type, book, /, page,
                # book2, /, page2, qualified, sale_type, grantor, grantee
                sale_entries = []
                i = 0
                while i < len(sale_lines):
                    ln = sale_lines[i]
                    # Skip header tokens
                    if ln in _HEADER_TOKENS:
                        i += 1
                        continue
                    # Detect start of a sale record: "N" or "Y" for Multi-Parcel
                    if ln in ("N", "Y"):
                        multi = ln
                        i += 1
                        # Collect next tokens for this sale
                        entry_tokens = []
                        while i < len(sale_lines) and len(entry_tokens) < 13:
                            t = sale_lines[i]
                            # The next "N"/"Y" starts the next sale — stop
                            if t in ("N", "Y"):
                                break
                            if t not in _HEADER_TOKENS:
                                entry_tokens.append(t)
                            i += 1
                        # entry_tokens layout (expected):
                        # [0] = sale_date  (MM/DD/YYYY)
                        # [1] = sale_price ($xxx,xxx)
                        # [2] = deed_type  (WD, QCD, …)
                        # [3] = book       (e.g. "3400")
                        # [4] = page       (e.g. "80")
                        # [5] = book2      (duplicate — skip)
                        # [6] = page2      (duplicate — skip)
                        # [7] = qualified  (Q, U, etc.)
                        # [8] = sale_type  (I, V, etc.)
                        # [9] = grantor
                        # [10] = grantee
                        # (some entries may be shorter if data is missing)
                        def _tok(idx: int) -> str:
                            return entry_tokens[idx] if idx < len(entry_tokens) else ""

                        sale_date = _tok(0)
                        sale_price_raw = _tok(1)
                        deed_type = _tok(2)
                        book = _tok(3)
                        page = _tok(4)
                        # [5],[6] are duplicates; skip
                        qualified_raw = _tok(7)
                        # sale_type = _tok(8)  # not stored
                        grantor = _tok(9)
                        grantee = _tok(10)

                        if re.match(r"\d{1,2}/\d{1,2}/\d{4}", sale_date or ""):
                            bp = f"{book}/{page}" if book and page else ""
                            sale_entries.append(
                                SaleHistoryEntry(
                                    sale_date=sale_date,
                                    sale_price=_money(sale_price_raw),
                                    deed_book_page=bp,
                                    deed_type=deed_type,
                                    grantor=grantor,
                                    grantee=grantee,
                                    qualified=(qualified_raw.upper() == "Q"),
                                )
                            )
                        continue
                    i += 1
                result.sale_history = sale_entries  # already newest-first per portal

            result.status = "PA_SUCCESS"

        except Exception as exc:
            result.status = "PA_FAILED"
            result.notes = f"parse_detail_html error: {exc}"

        result.fetched_at = datetime.now().isoformat()
        return result

    # ---------------------------------------------------------------- public

    def _search(self, session, *, name: str = "", street: str = "",
                parcel_id: str = "-----") -> List[Dict[str, Any]]:
        """POST /property/query and return the results list."""
        payload = {
            "quickSearchParam": "",
            "useQuickSearch": "false",
            "parameterMatch": "intersect",
            "name": name,
            "street": street,
            "parcelId": parcel_id,
        }
        resp = session.post(self._search_url, data=payload, timeout=25)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception:
            data = {}
        return self._parse_search_json(data)

    def _fetch_detail(self, session, parcel_number: str) -> PropertyAppraiserResult:
        url = self._detail_url(parcel_number)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        result = self.parse_detail_html(resp.text)
        result.source_url = url
        return result

    # ----------------------------------- address

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Search by situs address.

        Parses "1009 RIN CT, MILTON, FL 32583" → street="1009 RIN" (number +
        street name without suffix).  Falls back to street name only if 0 results.
        """
        try:
            session = self._session()

            # Normalise: strip state + zip from end
            addr_clean = re.sub(
                r",?\s+FL\b.*$", "", address, flags=re.I
            ).strip()
            # Split on comma → street part
            street_part = addr_clean.split(",")[0].strip().upper()

            # Build search tokens: "1009 RIN CT" → number="1009", name="RIN", suffix="CT"
            tokens = street_part.split()
            # Candidate 1: number + first word of street name (omit suffix)
            if len(tokens) >= 3 and tokens[0].isdigit():
                street_query_1 = f"{tokens[0]} {tokens[1]}"
            elif len(tokens) >= 2 and tokens[0].isdigit():
                street_query_1 = street_part
            else:
                street_query_1 = street_part

            # Candidate 2: just the street name word (no number, no suffix)
            street_name_only = tokens[1] if len(tokens) >= 2 and tokens[0].isdigit() else tokens[0]

            results = self._search(session, street=street_query_1)
            if not results:
                results = self._search(session, street=street_name_only)
            if not results:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for address: {address}",
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )

            # Pick best match by address number
            house_num_m = re.match(r"^(\d+)\s", street_part)
            best = results[0]
            if house_num_m:
                house_num = house_num_m.group(1)
                for r in results:
                    situs = (r.get("situsAddress") or "").upper()
                    if situs.startswith(house_num + " ") or situs.startswith(house_num + ","):
                        best = r
                        break

            parcel_num = best.get("parcelNumber", "")
            if not parcel_num:
                return PropertyAppraiserResult(
                    status="PA_FAILED",
                    notes="Search result had no parcelNumber",
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )

            result = self._fetch_detail(session, parcel_num)
            if len(results) > 1:
                result.notes = (
                    (result.notes + "; " if result.notes else "")
                    + f"address search returned {len(results)} candidates; picked {parcel_num}"
                )
            return result

        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_address error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    # ----------------------------------- APN

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        """Search by parcel number (APN).

        POSTs with parcelId=<apn>.  If that returns 0 results (some portals
        ignore the field), fetches the detail page directly by parcel number.
        """
        try:
            session = self._session()
            apn_clean = apn.strip()

            # First try: POST with parcelId set
            results = self._search(session, parcel_id=apn_clean)
            if results:
                # Find exact match
                exact = next(
                    (r for r in results
                     if (r.get("parcelNumber") or "").strip() == apn_clean),
                    results[0],
                )
                parcel_num = exact.get("parcelNumber", apn_clean)
                return self._fetch_detail(session, parcel_num)

            # Fallback: hit the detail page directly with the APN
            result = self._fetch_detail(session, apn_clean)
            return result

        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_apn error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    # ----------------------------------- owner name

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search (LAST FIRST format). Returns up to 5 results."""
        try:
            session = self._session()
            results = self._search(session, name=owner_name.upper())
            if not results:
                return []
            out = []
            for item in results[:5]:
                parcel_num = item.get("parcelNumber", "")
                if not parcel_num:
                    continue
                try:
                    detail = self._fetch_detail(session, parcel_num)
                    out.append(detail)
                except Exception:
                    continue
            return out
        except Exception:
            return []
