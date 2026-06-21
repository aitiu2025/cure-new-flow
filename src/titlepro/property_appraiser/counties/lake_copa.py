"""Lake County (FL) Property Appraiser (LCOPA) HTTP adapter — Phase 1a anchor.

Derived from the 2026-06-18 live probe (lakecopropappr.com). Lake County runs
a **county-custom ASP.NET WebForms** property-search engine at
``https://www.lakecopropappr.com/``.

Three-step flow:
  1. **TOU gate** — GET ``/property-search.aspx`` → a Terms-of-Use page (ASP.NET
     VIEWSTATE, 16 KB). POST ``/property-disclaimer.aspx?to=%2fproperty-search.aspx%3f``
     with the TOU page's VIEWSTATE + imgBtnSubmit.x/y coordinates. Server sets a
     ``TermsOfUse`` cookie valid for the session. On success the response IS the
     real search page (41 KB).
  2. **Search** — POST ``/property-search.aspx`` with the search form VIEWSTATE
     (harvested from the TOU response) + search fields + ``btnSearch=Search``.
     Searches by ``txtOwnerName`` (owner, format: "LAST FIRST") OR ``txtStreet``
     (street name only — omit number) + optional ``txtCity``. Returns results in
     ``table#cphMain_gvParcels`` with rows: Owner | Parcel Number | Alternate Key |
     City | Property Use.  Each row's ``view`` link goes to
     ``property-details.aspx?AltKey=<AltKey>``.
  3. **Detail** — GET ``/property-details.aspx?AltKey=<AltKey>``. Server-rendered
     HTML with: General Information (Name, Parcel Number, Property Location, Legal
     Description), Sales History table (Book/Page | Sale Date | Instrument |
     Qualified/Unqualified | Vacant/Improved | Sale Price), and
     Values & Estimated Ad Valorem Taxes table.

Key findings from live probe (2026-06-18):
  - ``ctl00$cphMain$txtStreet`` requires ONLY the street name (e.g., "BELLAND"),
    not the full address — "3513 BELLAND" returns 0 results; "BELLAND" returns all.
  - ``ctl00$cphMain$txtOwnerName`` uses "LAST FIRST" format and accepts partial matches.
  - ``ctl00$cphMain$rblRealTangible`` must be "Real" (default) for real-property search.
  - The ``TermsOfUse`` cookie is required on all subsequent requests — the session
    maintains it automatically after the TOU POST.
  - No Cloudflare / Akamai / CAPTCHA — plain IIS, US egress only (datacenter OK).
  - Detail page AltKey is a 7-digit number (e.g., 3904456) distinct from Parcel ID
    (format: ``03-23-26-0109-000-012C0``).

HTTP-only via curl_cffi (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_BASE = "https://www.lakecopropappr.com"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+(?:\.\d{2})?)\)?")
_NO_RESULTS_RE = re.compile(r"no results|did not find|no records? found", re.I)


def _money(s: str) -> int:
    m = _MONEY_RE.search(s or "")
    if not m:
        return 0
    return int(m.group(1).replace(",", "").replace(".00", "").replace(".", ""))


def _hidden(html: str, name: str) -> str:
    """Extract a hidden input value by name from HTML."""
    m = re.search(
        r'name="%s"\s+[^>]*value="([^"]*)"' % re.escape(name), html
    ) or re.search(
        r'value="([^"]*)"\s+[^>]*name="%s"' % re.escape(name), html
    )
    return m.group(1) if m else ""


class LakeCOPA(AbstractPropertyAppraiser):
    """Lake County (FL) Property Appraiser — custom ASP.NET WebForms adapter."""

    SOURCE_LABEL = "Lake County Property Appraiser"
    LIVE_PLATFORM = "lake_copa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_lake")
        self.county_name = self.config.get("county_name", "Lake")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.base_url = (self.config.get("base_url") or _DEFAULT_BASE).rstrip("/")
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        # Endpoint constants
        self._search_url = f"{self.base_url}/property-search.aspx"
        self._tou_url = f"{self.base_url}/property-disclaimer.aspx"
        self._detail_url = f"{self.base_url}/property-details.aspx"

    # ----------------------------------------------------------------- network
    def _session(self):
        from curl_cffi import requests as cffi  # local import; optional dep
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    def _harvest_inputs(self, html: str) -> Dict[str, str]:
        """Extract all hidden/form inputs from HTML."""
        return {
            m.group(1): m.group(2)
            for m in re.finditer(
                r'<input[^>]+name="([^"]+)"[^>]*value="([^"]*)"', html, re.I
            )
        }

    def _accept_tou(self, session) -> Tuple[str, Dict[str, str]]:
        """GET the TOU page, POST acceptance → returns (search_page_html, viewstate_dict).

        The server sets a ``TermsOfUse`` cookie in the session after the POST.
        The POST response IS the real search page (the server 302s + rerenders).
        """
        r1 = session.get(self._search_url, timeout=20)
        tou_inputs = self._harvest_inputs(r1.text)

        # The TOU page has an image submit button — send .x/.y coordinates
        tou_post = dict(tou_inputs)
        if "ctl00$cphMain$imgBtnSubmit" in tou_post:
            del tou_post["ctl00$cphMain$imgBtnSubmit"]
        tou_post["ctl00$cphMain$imgBtnSubmit.x"] = "79"
        tou_post["ctl00$cphMain$imgBtnSubmit.y"] = "23"

        disclaimer_url = f"{self._tou_url}?to=%2fproperty-search.aspx%3f"
        r2 = session.post(disclaimer_url, data=tou_post, timeout=20)
        # The response IS the search page (cookie set, content served inline)
        return r2.text, self._harvest_inputs(r2.text)

    # --------------------------------------------------------------- parsing
    @staticmethod
    def _parse_results_grid(html: str) -> List[Tuple[str, str, str, str]]:
        """Parse the gvParcels results table.

        Returns a list of (alt_key, owner, parcel_number, city) tuples.
        ``alt_key`` is the 7-digit number used as the detail URL key.
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            grid = soup.find("table", id="cphMain_gvParcels")
            if not grid:
                return []
            results = []
            for row in grid.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 3:
                    continue
                # Find the property-details link for the AltKey
                link = row.find("a", href=re.compile(r"property-details\.aspx\?AltKey=\d+"))
                if not link:
                    continue
                m = re.search(r"AltKey=(\d+)", link.get("href", ""))
                alt_key = m.group(1) if m else ""
                # cells[0] = '' (view), cells[1] = owner+address, cells[2] = parcel#, etc.
                owner_cell = cells[1] if len(cells) > 1 else ""
                parcel_cell = cells[2] if len(cells) > 2 else ""
                city_cell = cells[3] if len(cells) > 3 else ""
                results.append((alt_key, owner_cell, parcel_cell, city_cell))
            return results
        except Exception:
            return []

    @staticmethod
    def parse_detail_html(html: str) -> PropertyAppraiserResult:
        """Parse a ``property-details.aspx`` page into a ``PropertyAppraiserResult``.

        Side-effect-free for unit testing: accepts captured HTML, returns result.
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

            # --- General Information table ---
            # The detail page has labelled rows: Name, Alternate Key, Mailing Address,
            # Parcel Number, Property Location, Property Description, etc.
            # We scan all text and find values by preceding label.
            full_text = soup.get_text("\n")
            lines = [l.strip() for l in full_text.split("\n") if l.strip()]

            def _next_after(label_pattern: str, text_lines: List[str]) -> str:
                """Return the first non-empty line that follows a label match."""
                for i, line in enumerate(text_lines):
                    if re.search(label_pattern, line, re.I):
                        for j in range(i + 1, min(i + 5, len(text_lines))):
                            val = text_lines[j].strip()
                            if val and val != line.strip():
                                return val
                return ""

            # Extract from page text
            result.owner_of_record = _next_after(r"^Name:$", lines)
            parcel_raw = _next_after(r"^Parcel Number:$", lines)
            result.apn = parcel_raw
            alt_key_raw = _next_after(r"^Alternate Key:$", lines)
            result.pin = alt_key_raw  # store AltKey as pin

            # Property Location is the situs address
            result.situs_address = _next_after(r"^Property Location:$", lines)
            # Legal description
            result.legal_description = _next_after(r"^Property Description:$", lines)

            # --- Values table ---
            # Look for "Market Value" in table rows
            for row in soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                # Market Value row typically looks like: [authority, market_val, assessed_val, taxable_val, millage, taxes]
                # We want the first numeric Market Value
                if cells and len(cells) >= 2:
                    if any("Market Value" in c for c in cells):
                        for c in cells:
                            v = _money(c)
                            if v > 0:
                                result.just_value = v
                                break
                    elif any("Assessed Value" in c or "Total Certified" in c for c in cells):
                        for c in cells:
                            v = _money(c)
                            if v > 0 and result.assessed_value == 0:
                                result.assessed_value = v
                                break

            # Also scan for Total market value / Just Value from the "Total:" row
            # or from the Values section
            # Approach: find the values table by looking for the "Total:" row
            for t in soup.find_all("table"):
                ttext = t.get_text(" ")
                if "Market Value" in ttext and "Assessed Value" in ttext:
                    rows = t.find_all("tr")
                    for row in rows:
                        cells_el = row.find_all(["td", "th"])
                        cells = [el.get_text(strip=True) for el in cells_el]
                        if not cells or len(cells) < 4:
                            continue
                        # Skip header rows
                        if "Market Value" in cells[0] or "Assessed Value" in cells[0]:
                            continue
                        # Data row: authority | market | assessed | taxable | millage | taxes
                        # Only take the first real data row for just_value
                        if result.just_value == 0 and cells[1]:
                            v = _money(cells[1])
                            if v > 0:
                                result.just_value = v
                        if result.assessed_value == 0 and len(cells) > 2 and cells[2]:
                            v = _money(cells[2])
                            if v > 0:
                                result.assessed_value = v
                    break

            # Homestead check
            if "Homestead Exemption" in full_text and "✓" in full_text or "checked" in html.lower():
                result.homestead_active = True

            # --- Sales History table ---
            # "Book/Page | Sale Date | Instrument | Qualified/Unqualified | Vacant/Improved | Sale Price"
            sales = []
            for t in soup.find_all("table"):
                headers = [th.get_text(strip=True) for th in t.find_all("th")]
                if any("Sale Date" in h or "Book/Page" in h for h in headers):
                    for row in t.find_all("tr"):
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        # Row format: Book/Page | Sale Date | Instrument | Q | V | Sale Price
                        if len(cells) >= 5:
                            book_page = cells[0] if cells[0] else ""
                            sale_date = cells[1] if len(cells) > 1 else ""
                            instrument = cells[2] if len(cells) > 2 else ""
                            qualified = cells[3] if len(cells) > 3 else ""
                            vacant = cells[4] if len(cells) > 4 else ""
                            price_raw = cells[5] if len(cells) > 5 else ""
                            price = _money(price_raw)
                            if sale_date and re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}", sale_date):
                                entry = SaleHistoryEntry(
                                    sale_date=sale_date,
                                    sale_price=price,
                                    deed_book_page=book_page,
                                    deed_type=instrument,
                                    qualified=(qualified.lower() == "qualified"),
                                    notes=f"{vacant}" if vacant else "",
                                )
                                sales.append(entry)
            result.sale_history = sales  # already newest-first per the page

            result.status = "PA_SUCCESS"
        except Exception as e:
            result.status = "PA_FAILED"
            result.notes = f"parse_detail_html error: {e}"

        result.fetched_at = datetime.now().isoformat()
        return result

    # ---------------------------------------------------------------- public
    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Search by address → first matching parcel detail.

        Splits the address into street name and city; uses street name only
        (omit number per Lake County portal requirement: "Enter only the
        number and name. Omit words like Drive.").
        """
        try:
            session = self._session()
            search_html, viewstate = self._accept_tou(session)

            # Parse address: "3513 BELLAND CIR UNIT D, CLERMONT, FL"
            # Strip unit suffix and state
            addr_clean = re.sub(r",?\s+FL\b.*$", "", address, flags=re.I).strip()
            # Split on first comma for city
            parts = addr_clean.split(",", 1)
            street_full = parts[0].strip()
            city = parts[1].strip() if len(parts) > 1 else ""
            # Extract just street name (drop house number)
            m = re.match(r"^\d+\s+(.+?)(?:\s+UNIT\s+\S+)?$", street_full, re.I)
            street_name = m.group(1).strip() if m else street_full

            # Also strip directional suffix (CIR, DR, ST, etc.) NOT the street name itself
            # Lake portal works best with just the street name word e.g. "BELLAND"
            # Leave it as-is: "BELLAND CIR" also works

            post_data = dict(viewstate)
            post_data["ctl00$cphMain$txtStreet"] = street_name
            if city:
                post_data["ctl00$cphMain$txtCity"] = city
            post_data["ctl00$cphMain$rblRealTangible"] = "Real"
            post_data["ctl00$cphMain$btnSearch"] = "Search"

            r = session.post(self._search_url, data=post_data, timeout=25)
            search_html_result = r.text

            if _NO_RESULTS_RE.search(search_html_result):
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for address: {address}",
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )

            results = self._parse_results_grid(search_html_result)
            if not results:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"Grid parse returned 0 rows for address: {address}",
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )

            # Pick best match: exact address number match first, else first result
            alt_key = self._pick_best_match(results, street_full)
            if not alt_key:
                alt_key = results[0][0]

            # Disambiguate: if many results warn
            status_notes = None
            if len(results) > 1:
                status_notes = f"address search returned {len(results)} candidates; picked AltKey={alt_key}"

            detail_url = f"{self._detail_url}?AltKey={alt_key}"
            r2 = session.get(detail_url, timeout=25)
            result = self.parse_detail_html(r2.text)
            result.source_url = detail_url
            if status_notes:
                result.notes = status_notes
            return result

        except Exception as e:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_address error: {e}",
                fetched_at=datetime.now().isoformat(),
            )

    def _pick_best_match(self, results: List[Tuple], street_full: str) -> Optional[str]:
        """Return the AltKey whose owner cell contains the address number+street."""
        # Extract house number from the full street address
        m = re.match(r"^(\d+)\s+", street_full)
        if not m:
            return None
        number = m.group(1)
        for alt_key, owner_cell, parcel_num, city in results:
            if number in owner_cell:
                return alt_key
        return None

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        r"""Lookup by AltKey (7-digit number) or Parcel ID.

        Lake County uses 7-digit 'Alternate Key' numbers on the portal.
        If the passed APN matches \d{7}, treat it directly as AltKey.
        Otherwise try a Parcel ID search via owner-name workaround.
        """
        try:
            session = self._session()
            # If 7-digit alt key, go direct to detail
            apn_clean = apn.strip().replace("-", "").replace(" ", "")
            if re.fullmatch(r"\d{7}", apn_clean):
                detail_url = f"{self._detail_url}?AltKey={apn_clean}"
                # Need TOU cookie first
                self._accept_tou(session)
                r = session.get(detail_url, timeout=25)
                result = self.parse_detail_html(r.text)
                result.source_url = detail_url
                return result

            # For standard Parcel ID (format: XX-XX-XX-XXXX-XXX-XXXXXX), try
            # using the AltKey field in the search form.
            # IMPORTANT: only use the AltKey path when the cleaned APN is
            # ≤7 digits (i.e. it really IS an AltKey in disguise).
            # Standard FL Parcel IDs are 17 chars; truncating to 7 would produce
            # a wrong/random AltKey that matches a completely different parcel.
            if len(apn_clean) > 7:
                # Long APN — cannot use AltKey path; fall back to address search.
                # Callers should use lookup_by_address for non-AltKey APNs.
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=(
                        f"lookup_by_apn: APN '{apn}' is not a 7-digit AltKey. "
                        "Lake COPA portal uses 7-digit AltKey numbers; standard "
                        "FL Parcel IDs (17 chars) must be resolved via "
                        "lookup_by_address or a manual AltKey lookup."
                    ),
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )
            search_html, viewstate = self._accept_tou(session)
            post_data = dict(viewstate)
            post_data["ctl00$cphMain$txtAltKey"] = apn_clean
            post_data["ctl00$cphMain$rblRealTangible"] = "Real"
            post_data["ctl00$cphMain$btnSearch"] = "Search"
            r = session.post(self._search_url, data=post_data, timeout=25)
            results = self._parse_results_grid(r.text)
            if not results:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for APN/AltKey: {apn}",
                    source_url=self._search_url,
                    fetched_at=datetime.now().isoformat(),
                )
            alt_key = results[0][0]
            detail_url = f"{self._detail_url}?AltKey={alt_key}"
            r2 = session.get(detail_url, timeout=25)
            result = self.parse_detail_html(r2.text)
            result.source_url = detail_url
            return result

        except Exception as e:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_apn error: {e}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search. Returns up to 5 results (diagnostic/best-effort).

        Portal format: "LAST FIRST" — caller should pass last name first.
        """
        try:
            session = self._session()
            search_html, viewstate = self._accept_tou(session)
            post_data = dict(viewstate)
            post_data["ctl00$cphMain$txtOwnerName"] = owner_name.upper()
            post_data["ctl00$cphMain$rblRealTangible"] = "Real"
            post_data["ctl00$cphMain$btnSearch"] = "Search"
            r = session.post(self._search_url, data=post_data, timeout=25)
            grid_results = self._parse_results_grid(r.text)
            if not grid_results:
                return []
            out = []
            for alt_key, owner_cell, parcel_num, city in grid_results[:5]:
                try:
                    detail_url = f"{self._detail_url}?AltKey={alt_key}"
                    r2 = session.get(detail_url, timeout=25)
                    detail = self.parse_detail_html(r2.text)
                    detail.source_url = detail_url
                    out.append(detail)
                except Exception:
                    continue
            return out
        except Exception:
            return []
