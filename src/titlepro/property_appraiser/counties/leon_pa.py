"""Leon County (FL) Property Appraiser HTTP adapter — Phase 1a anchor.

Derived from the 2026-06-19 live-probe specification for search.leonpa.gov.
Leon County runs an **ASP.NET MVC + DataTables serverSide** property-search
portal at ``https://search.leonpa.gov``.

Three-step flow:
  1. **TOU gate** — GET ``/Terms?requestedAction=Property`` → extract
     ``__RequestVerificationToken`` → POST ``/Terms/Agree`` with
     ``{redirectTarget: "Property", __RequestVerificationToken: <token>}``.
     Server sets a TOU session cookie.
  2. **Search CSRF** — GET ``/Search/Property`` → extract a fresh
     ``__RequestVerificationToken`` for the search form.
  3. **DataTables serverSide search** — POST
     ``/Search/ExecutePropertySearch`` with DataTables boilerplate +
     one of ``Address``, ``ParcelId``, or ``OwnerName`` fields +
     ``X-Requested-With: XMLHttpRequest`` header + the search CSRF token.
     Response JSON: ``{draw, recordsTotal, recordsFiltered,
     data: [{ParcelId, Owners, Address, PropertyUse, Acreage}]}``.
  4. **Detail page** — GET ``/Property/Details/<URL-encoded-ParcelId>``.
     Returns ~2.6 MB HTML; parsed via BeautifulSoup + text-line scanning.

Key findings from live-probe specification (2026-06-19):
  - ParcelId may contain spaces (e.g., "210575  C0070") — URL-encode with %20.
  - Address search accepts ``"4828 EASY"`` (number + street name is fine).
  - No Cloudflare / Akamai / CAPTCHA — datacenter IP is fine.
  - Sales table header: Sale Date | Sale Price | Book/Page | Instrument Type |
    Improved/Vacant → parse into SaleHistoryEntry (newest-first).
  - Homestead: "Homestead Information" section row for current year → "Yes".
  - Just Value: "Total Market" row, column 3 (most-recent-year value).

HTTP-only via curl_cffi (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_BASE = "https://search.leonpa.gov"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+(?:\.\d{2})?)\)?")
_NO_RESULTS_RE = re.compile(r"no results|did not find|no records? found|0 records", re.I)

# DataTables serverSide boilerplate — constant columns definition
_DT_COLUMNS = [
    ("ParcelId", "true", "true"),
    ("Owners", "true", "false"),
    ("Address", "true", "false"),
    ("PropertyUse", "true", "false"),
    ("Acreage", "true", "false"),
]


def _money(s: str) -> int:
    """Parse a dollar-amount string into an integer (cents truncated)."""
    m = _MONEY_RE.search(s or "")
    if not m:
        return 0
    raw = m.group(1).replace(",", "")
    # Strip decimal cents
    if "." in raw:
        raw = raw.split(".")[0]
    return int(raw) if raw else 0


def _extract_rvt(html: str) -> str:
    """Extract __RequestVerificationToken from hidden input in HTML."""
    m = re.search(
        r'<input[^>]+name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        html, re.I
    ) or re.search(
        r'<input[^>]+value="([^"]+)"[^>]*name="__RequestVerificationToken"',
        html, re.I
    )
    return m.group(1) if m else ""


def _build_dt_payload(
    *,
    address: str = "",
    parcel_id: str = "",
    owner_name: str = "",
    csrf_token: str = "",
) -> Dict[str, str]:
    """Build the DataTables serverSide POST payload for ExecutePropertySearch."""
    payload: Dict[str, str] = {
        "draw": "1",
        "start": "0",
        "length": "25",
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "0",
        "order[0][dir]": "asc",
        # Search fields
        "Address": address,
        "ParcelId": parcel_id,
        "OwnerName": owner_name,
        "SubDivision": "",
        "SquareFootageFrom": "",
        "SquareFootageTo": "",
        "YearBuiltFrom": "",
        "YearBuiltTo": "",
        "NumberOfAcresFrom": "",
        "NumberOfAcresTo": "",
        "__RequestVerificationToken": csrf_token,
    }
    # Add DataTables columns boilerplate
    for idx, (col_data, searchable, orderable) in enumerate(_DT_COLUMNS):
        payload[f"columns[{idx}][data]"] = col_data
        payload[f"columns[{idx}][name]"] = ""
        payload[f"columns[{idx}][searchable]"] = searchable
        payload[f"columns[{idx}][orderable]"] = orderable
        payload[f"columns[{idx}][search][value]"] = ""
        payload[f"columns[{idx}][search][regex]"] = "false"
    return payload


class LeonPA(AbstractPropertyAppraiser):
    """Leon County (FL) Property Appraiser — ASP.NET MVC + DataTables adapter."""

    SOURCE_LABEL = "Leon County Property Appraiser"
    LIVE_PLATFORM = "leon_pa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_leon")
        self.county_name = self.config.get("county_name", "Leon")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.base_url = (self.config.get("base_url") or _DEFAULT_BASE).rstrip("/")
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        # Endpoint constants
        self._tou_page_url = f"{self.base_url}/Terms?requestedAction=Property"
        self._tou_agree_url = f"{self.base_url}/Terms/Agree"
        self._search_page_url = f"{self.base_url}/Search/Property"
        self._search_exec_url = f"{self.base_url}/Search/ExecutePropertySearch"
        self._detail_base_url = f"{self.base_url}/Property/Details"

    # ----------------------------------------------------------------- network

    def _session(self):
        from curl_cffi import requests as cffi  # optional dep; import locally
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    def _accept_tou(self, session) -> None:
        """Step 1: GET TOU page, POST acceptance → session gets TOU cookie."""
        r1 = session.get(self._tou_page_url, timeout=20)
        token = _extract_rvt(r1.text)
        tou_post = {
            "redirectTarget": "Property",
            "__RequestVerificationToken": token,
        }
        session.post(self._tou_agree_url, data=tou_post, timeout=20)

    def _get_search_csrf(self, session) -> str:
        """Step 2: GET the search page → return the CSRF token for the search form."""
        r = session.get(self._search_page_url, timeout=20)
        return _extract_rvt(r.text)

    def _execute_search(self, session, csrf_token: str, **kwargs) -> List[Dict]:
        """Step 3: POST to ExecutePropertySearch → return list of result dicts.

        kwargs are forwarded to _build_dt_payload (address, parcel_id, owner_name).
        Returns the ``data`` array from the DataTables JSON response.
        """
        payload = _build_dt_payload(csrf_token=csrf_token, **kwargs)
        headers = {"X-Requested-With": "XMLHttpRequest"}
        r = session.post(
            self._search_exec_url,
            data=payload,
            headers=headers,
            timeout=25,
        )
        try:
            j = r.json()
            return j.get("data") or []
        except Exception:
            return []

    def _fetch_detail(self, session, parcel_id: str) -> Tuple[str, str]:
        """Step 4: GET detail page for parcel_id → (html, detail_url)."""
        encoded = quote(parcel_id, safe="")
        detail_url = f"{self._detail_base_url}/{encoded}"
        r = session.get(detail_url, timeout=30)
        return r.text, detail_url

    # ----------------------------------------------------------------- parsing

    @staticmethod
    def _next_after(label_pattern: str, lines: List[str]) -> str:
        """Return the first non-empty line that follows a label-matching line."""
        for i, line in enumerate(lines):
            if re.search(label_pattern, line, re.I):
                for j in range(i + 1, min(i + 6, len(lines))):
                    val = lines[j].strip()
                    if val and val != line.strip():
                        return val
        return ""

    @staticmethod
    def _lines_after_until(
        label_pattern: str,
        stop_pattern: str,
        lines: List[str],
        max_lines: int = 10,
    ) -> List[str]:
        """Collect non-empty lines after a label match, stopping at a stop pattern."""
        result: List[str] = []
        collecting = False
        for line in lines:
            if not collecting:
                if re.search(label_pattern, line, re.I):
                    collecting = True
                continue
            if re.search(stop_pattern, line, re.I):
                break
            stripped = line.strip()
            if stripped:
                result.append(stripped)
            if len(result) >= max_lines:
                break
        return result

    @staticmethod
    def parse_detail_html(html: str) -> PropertyAppraiserResult:
        """Parse a ``/Property/Details/<ParcelId>`` page into a PropertyAppraiserResult.

        Side-effect-free for unit testing: accepts captured HTML, returns result.

        Parsing strategy:
          - Scans soup.get_text("\\n") lines for label-then-value patterns.
          - Sales table: 5-cell rows under "Sales Information" header.
          - Values: "Total Market" row, column 3 = just_value.
          - Homestead: current-year "Yes" in "Homestead Information" section.
        """
        result = PropertyAppraiserResult()
        if not html or len(html) < 200:
            result.status = "PA_FAILED"
            result.notes = "parse_detail_html: empty or too-short response"
            result.fetched_at = datetime.now().isoformat()
            return result

        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            full_text = soup.get_text("\n")
            lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]

            # ---- Core sidebar fields (label on one line, value on next) ------

            result.apn = LeonPA._next_after(r"^Parcel\s+ID\s*:?$", lines)
            result.situs_address = LeonPA._next_after(r"^Location\s*:?$", lines)
            result.owner_of_record = LeonPA._next_after(r"^Owner\(s\)\s*:?$", lines)

            # Subdivision name → store in notes
            subdivision = LeonPA._next_after(r"^Subdivision\s+Name\s*:?$", lines)

            # Legal description: collect lines after the label until we hit
            # "Acreage:" or a blank section header (OR XXXX/XXXX suffix already
            # included in the block).
            legal_parts = LeonPA._lines_after_until(
                r"^(?:Full\s+)?Parcel\s+Description\s*:?$",
                r"^(?:Acreage|Sales\s+Information|Certified\s+Value|Taxing\s+Auth)",
                lines,
                max_lines=12,
            )
            result.legal_description = " ".join(legal_parts)

            # Acreage (float stored as string in notes; not a result field)
            acreage_str = LeonPA._next_after(r"^Acreage\s*:?$", lines)

            # Build notes
            notes_parts = []
            if subdivision:
                notes_parts.append(f"Subdivision: {subdivision}")
            if acreage_str:
                notes_parts.append(f"Acreage: {acreage_str}")
            if notes_parts:
                result.notes = "; ".join(notes_parts)

            # ---- Sales table ------------------------------------------------
            # Header: Sale Date | Sale Price | Book/Page | Instrument Type | Improved/Vacant
            sales: List[SaleHistoryEntry] = []
            for t in soup.find_all("table"):
                headers = [th.get_text(strip=True) for th in t.find_all("th")]
                if not any(re.search(r"Sale\s+Date|Book[/]?Page", h, re.I) for h in headers):
                    continue
                # Determine column indices from header row
                col_sale_date = 0
                col_sale_price = 1
                col_book_page = 2
                col_instr_type = 3
                col_impr_vac = 4
                for hi, h in enumerate(headers):
                    if re.search(r"Sale\s+Date", h, re.I):
                        col_sale_date = hi
                    elif re.search(r"Sale\s+Price", h, re.I):
                        col_sale_price = hi
                    elif re.search(r"Book[/\s]?Page", h, re.I):
                        col_book_page = hi
                    elif re.search(r"Instrument\s+Type", h, re.I):
                        col_instr_type = hi
                    elif re.search(r"Improved|Vacant", h, re.I):
                        col_impr_vac = hi

                for row in t.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) < 3:
                        continue
                    sale_date_val = cells[col_sale_date] if col_sale_date < len(cells) else ""
                    # Must look like a date
                    if not re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}", sale_date_val):
                        continue
                    sale_price_val = cells[col_sale_price] if col_sale_price < len(cells) else "0"
                    book_page_val = cells[col_book_page] if col_book_page < len(cells) else ""
                    instr_type_val = cells[col_instr_type] if col_instr_type < len(cells) else ""
                    notes_val = cells[col_impr_vac] if col_impr_vac < len(cells) else ""

                    entry = SaleHistoryEntry(
                        sale_date=sale_date_val,
                        sale_price=_money(sale_price_val),
                        deed_book_page=book_page_val,
                        deed_type=instr_type_val,
                        qualified=False,
                        notes=notes_val,
                    )
                    sales.append(entry)
                # Parsed the first matching sales table; stop
                break

            # Portal returns newest-first already
            result.sale_history = sales

            # ---- Values (Certified Value History) ---------------------------
            # The "Certified Value History" table has column headers in <th> elements:
            # Tax Year | Land | Building | Total Market | Homestead Savings | Classified Use
            # Data rows have: year | land$ | building$ | total_market$ | ...
            # We locate the "Total Market" column index from the header row, then read
            # the first data row (= most recent year).
            for t in soup.find_all("table"):
                ttext = t.get_text(" ")
                if "Total Market" not in ttext:
                    continue
                # Find header row to get column index of "Total Market"
                total_market_col = None
                assessed_col = None
                for header_row in t.find_all("tr"):
                    ths = header_row.find_all("th")
                    if not ths:
                        continue
                    header_texts = [th.get_text(strip=True) for th in ths]
                    for ci, ht in enumerate(header_texts):
                        if re.search(r"Total\s+Market", ht, re.I):
                            total_market_col = ci
                        if re.search(r"Assessed", ht, re.I):
                            assessed_col = ci
                    if total_market_col is not None:
                        break

                if total_market_col is None:
                    # Fallback: "Total Market" in first cell of a data row (other layouts)
                    for row in t.find_all("tr"):
                        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                        if not cells:
                            continue
                        if re.search(r"Total\s+Market", cells[0], re.I):
                            for ci in range(1, min(4, len(cells))):
                                v = _money(cells[ci])
                                if v > 0:
                                    result.just_value = v
                                    break
                            break
                else:
                    # Read first <td>-only row (skip header rows)
                    for row in t.find_all("tr"):
                        tds = row.find_all("td")
                        if not tds or len(tds) <= total_market_col:
                            continue
                        cells = [td.get_text(strip=True) for td in tds]
                        jv = _money(cells[total_market_col])
                        if jv > 0:
                            result.just_value = jv
                        # Assessed value from the same row if there's an Assessed column
                        if assessed_col is not None and len(cells) > assessed_col:
                            av = _money(cells[assessed_col])
                            if av > 0:
                                result.assessed_value = av
                        break

                if result.just_value > 0:
                    break

            # Assessed value fallback: "Assessed" column in "2025 Certified Taxable Values" table
            if result.assessed_value == 0:
                for t in soup.find_all("table"):
                    ttext = t.get_text(" ")
                    if "Taxable" not in ttext or "Assessed" not in ttext:
                        continue
                    # Find the Assessed column index
                    assessed_col_idx = None
                    for header_row in t.find_all("tr"):
                        ths = header_row.find_all(["th", "td"])
                        if not ths:
                            continue
                        htexts = [h.get_text(strip=True) for h in ths]
                        for ci, ht in enumerate(htexts):
                            if ht.strip().lower() == "assessed":
                                assessed_col_idx = ci
                                break
                        if assessed_col_idx is not None:
                            break
                    if assessed_col_idx is None:
                        continue
                    # Read first data row
                    for row in t.find_all("tr"):
                        tds = row.find_all("td")
                        if not tds or len(tds) <= assessed_col_idx:
                            continue
                        cells = [td.get_text(strip=True) for td in tds]
                        av = _money(cells[assessed_col_idx])
                        if av > 0:
                            result.assessed_value = av
                            break
                    if result.assessed_value > 0:
                        break

            # ---- Homestead --------------------------------------------------
            # "Homestead Information" section — if current year row says "Yes"
            for i, line in enumerate(lines):
                if re.search(r"Homestead\s+Information", line, re.I):
                    # Scan the next 15 lines for "Yes"
                    window = lines[i + 1 : i + 16]
                    if any(re.fullmatch(r"Yes", w, re.I) for w in window):
                        result.homestead_active = True
                    break

            result.status = "PA_SUCCESS"

        except Exception as e:
            result.status = "PA_FAILED"
            result.notes = f"parse_detail_html error: {e}"

        result.fetched_at = datetime.now().isoformat()
        return result

    # ----------------------------------------------------------------- helpers

    def _pick_best_parcel_id(
        self, rows: List[Dict], address_fragment: str
    ) -> Optional[str]:
        """Return the ParcelId whose Address column best matches address_fragment.

        Normalises both strings to uppercase with collapsed whitespace before
        comparing. Falls back to the first row.
        """
        if not rows:
            return None

        def _norm(s: str) -> str:
            return re.sub(r"\s+", " ", s.upper().strip())

        target = _norm(address_fragment)
        for row in rows:
            row_addr = _norm(row.get("Address", ""))
            if target and target in row_addr:
                return row.get("ParcelId", "")
        # Fallback: first row
        return rows[0].get("ParcelId", "")

    def _setup_and_csrf(self, session) -> str:
        """Run TOU acceptance and return the search-page CSRF token."""
        self._accept_tou(session)
        return self._get_search_csrf(session)

    # ----------------------------------------------------------------- public

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Search by address → first best-match parcel detail.

        The Leon PA ``Address`` field accepts ``"4828 EASY"`` (number + street).
        We pass the raw address string as-is (or strip city/state suffix so the
        search is less strict).  If multiple results come back we pick the one
        whose Address column most closely matches the input.
        """
        try:
            session = self._session()
            csrf = self._setup_and_csrf(session)

            # Strip city/state suffix: "4828 EASY ST, Tallahassee, FL" → "4828 EASY ST"
            # Leon PA's Address field rejects anything with a comma (city/state suffix).
            # Safest approach: strip everything from the first comma onward.
            addr_clean = address.split(",")[0].strip()
            # Also strip state abbreviation if no comma was present
            addr_clean = re.sub(r"\s+FL\b.*$", "", addr_clean, flags=re.I).strip()

            rows = self._execute_search(session, csrf, address=addr_clean)

            if not rows:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for address: {address}",
                    source_url=self._search_exec_url,
                    fetched_at=datetime.now().isoformat(),
                )

            parcel_id = self._pick_best_parcel_id(rows, addr_clean)
            if not parcel_id:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"Could not resolve ParcelId from search results for: {address}",
                    source_url=self._search_exec_url,
                    fetched_at=datetime.now().isoformat(),
                )

            status_notes = None
            if len(rows) > 1:
                status_notes = (
                    f"address search returned {len(rows)} candidates; "
                    f"picked ParcelId={parcel_id!r}"
                )

            html, detail_url = self._fetch_detail(session, parcel_id)
            result = self.parse_detail_html(html)
            result.source_url = detail_url
            if status_notes:
                existing = result.notes or ""
                result.notes = f"{existing}; {status_notes}".lstrip("; ")
            return result

        except Exception as e:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_address error: {e}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        """Lookup by Parcel ID.

        Leon County ParcelIds can contain spaces (e.g., "210575  C0070").
        We search via the ``ParcelId`` field in the DataTables call, then
        fetch the detail page.  If the search returns multiple rows, we try
        an exact-APN match on the ParcelId column.
        """
        try:
            session = self._session()
            csrf = self._setup_and_csrf(session)

            apn_clean = apn.strip()
            rows = self._execute_search(session, csrf, parcel_id=apn_clean)

            if not rows:
                # Try direct detail URL as a fallback (some portals serve detail
                # even when search returns nothing for the raw parcel id)
                html, detail_url = self._fetch_detail(session, apn_clean)
                if "ParcelId" in html or "Parcel ID" in html:
                    result = self.parse_detail_html(html)
                    result.source_url = detail_url
                    return result
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for APN: {apn}",
                    source_url=self._search_exec_url,
                    fetched_at=datetime.now().isoformat(),
                )

            # Try exact match first
            exact_row = next(
                (r for r in rows if r.get("ParcelId", "").strip() == apn_clean),
                None,
            )
            chosen_row = exact_row or rows[0]
            parcel_id = chosen_row.get("ParcelId", apn_clean)

            html, detail_url = self._fetch_detail(session, parcel_id)
            result = self.parse_detail_html(html)
            result.source_url = detail_url
            return result

        except Exception as e:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_apn error: {e}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search. Returns up to 5 results (diagnostic / best-effort).

        Leon PA ``OwnerName`` field accepts partial "LAST FIRST" format.
        """
        try:
            session = self._session()
            csrf = self._setup_and_csrf(session)
            rows = self._execute_search(session, csrf, owner_name=owner_name.upper())
            if not rows:
                return []
            out: List[PropertyAppraiserResult] = []
            for row in rows[:5]:
                parcel_id = row.get("ParcelId", "")
                if not parcel_id:
                    continue
                try:
                    html, detail_url = self._fetch_detail(session, parcel_id)
                    detail = self.parse_detail_html(html)
                    detail.source_url = detail_url
                    out.append(detail)
                except Exception:
                    continue
            return out
        except Exception:
            return []
