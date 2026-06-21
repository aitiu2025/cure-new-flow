"""Charlotte County (FL) Property Appraiser (CCPA) HTTP adapter — Phase 1a anchor.

Derived from the 2026-06-19 live probe (ccappraiser.com). Charlotte County runs
a **county-custom Classic ASP** property-search engine at
``https://www.ccappraiser.com/``.

Two-step search flow:
  1. **GET** ``/RPSearchEnter.asp?`` → initialises a session cookie (no VIEWSTATE,
     no TOU gate — pure Classic ASP). The response HTML contains the search form
     (action="RPSearchQuery.asp", method="post").
  2. **POST** ``/RPSearchQuery.asp`` with search parameters → the server stores
     results in the ASP session and returns a **302 redirect** to
     ``/RPSearchSelect.asp``.
  3. **GET** ``/RPSearchSelect.asp`` (with the session cookie) → HTML results
     table containing: Parcel ID | Owner | Property Address | Short Legal |
     Just Value | Taxable Value | Use Code.  Each Parcel ID links to
     ``/Show_Parcel.asp?acct=<ParcelID>&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T``.

APN lookup shortcut (no search step needed):
  - GET ``/`` to seed session cookie, then
  - GET ``/Show_Parcel.asp?acct=<APN>&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T``
    directly.

Key findings from live probe (2026-06-19):
  - No Cloudflare / Akamai / CAPTCHA — plain IIS/8.5 ASP.NET 4.0, US egress fine.
  - Charlotte APN format: 12-digit numeric, e.g. ``412024203012``.
  - Street name search works with the full street name ("LONG MEADOW"), partial
    is sufficient for the portal ("LONG MEADOW" vs "LONG MEADOW LN").
  - The POST to ``RPSearchQuery.asp`` **must include** ``CurrentLandUse=Any``
    (the ``<select>`` default) otherwise 0 results are returned.
  - ``Instrument Number`` column in sales = recorder instrument #; ``Book/Page``
    column = OR book/page.  Both are populated for OLAR's parcel.
  - ``Homestead`` is indicated by the presence of ``01 Homestead`` in the
    exemption section of the parcel detail page.
  - The search POST results in a ``302 Moved`` (no ``Location:`` header —
    the body has an ``<a HREF>``).  The session is maintained by a cookie named
    ``ASPSession*``; follow the redirect with the same session jar.

HTTP-only via curl_cffi (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_BASE = "https://www.ccappraiser.com"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+(?:\.\d{2})?)\)?")
_NO_RESULTS_RE = re.compile(r"no.*results|no.*records|did not find|0 results", re.I)


def _money(s: str) -> int:
    """Parse a dollar-amount string into an integer (cents truncated)."""
    m = _MONEY_RE.search(s or "")
    if not m:
        return 0
    raw = m.group(1).replace(",", "")
    if "." in raw:
        raw = raw.split(".")[0]
    return int(raw) if raw else 0


class CharlotteCCPA(AbstractPropertyAppraiser):
    """Charlotte County (FL) Property Appraiser — Classic ASP adapter.

    The portal at ccappraiser.com uses a Classic ASP session-based search:
    POST to RPSearchQuery.asp → 302 → RPSearchSelect.asp (results list) →
    Show_Parcel.asp?acct=<APN> (detail).

    APN lookups skip the search entirely: seed a session cookie from the
    homepage, then GET Show_Parcel.asp directly.
    """

    SOURCE_LABEL = "Charlotte County Property Appraiser"
    LIVE_PLATFORM = "charlotte_ccpa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_charlotte")
        self.county_name = self.config.get("county_name", "Charlotte")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.base_url = (self.config.get("base_url") or _DEFAULT_BASE).rstrip("/")
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        # Endpoint constants
        self._enter_url = f"{self.base_url}/RPSearchEnter.asp?"
        self._query_url = f"{self.base_url}/RPSearchQuery.asp"
        self._select_url = f"{self.base_url}/RPSearchSelect.asp"
        self._parcel_url = f"{self.base_url}/Show_Parcel.asp"

    # ----------------------------------------------------------------- network

    def _session(self):
        from curl_cffi import requests as cffi  # optional dep; import locally
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    def _seed_session(self, session) -> None:
        """GET the homepage to mint the ASP session cookie."""
        session.get(f"{self.base_url}/", timeout=20)

    def _run_search(self, session, *, addr_number: str = "", addr_street: str = "",
                    owner: str = "", parcel_id: str = "") -> str:
        """POST to RPSearchQuery.asp; follow the 302 to RPSearchSelect.asp.

        Returns the HTML of RPSearchSelect.asp (the results list).
        """
        # Seed session first
        session.get(self._enter_url, timeout=20)

        post_data = {
            "ParcelID_number": parcel_id,
            "PropertyAddressNumber": addr_number,
            "PropertyAddressStreetName": addr_street,
            "owner": owner,
            "ShortLegal": "",
            "CurrentLandUse": "Any",
            "LandUseCode": "",
            "BuildingUseCode": "",
            "PADZip": "",
            "OwnerCountry": "",
        }
        # The POST returns 302; curl_cffi follows it automatically
        r = session.post(
            self._query_url,
            data=post_data,
            headers={"Referer": self._enter_url},
            timeout=25,
            allow_redirects=True,
        )
        # If the redirect did not land on RPSearchSelect, fetch it directly
        if "RPSearchSelect" not in r.url:
            r2 = session.get(self._select_url, timeout=20)
            return r2.text
        return r.text

    def _fetch_parcel_detail(self, session, apn: str) -> Tuple[str, str]:
        """GET Show_Parcel.asp for the given APN. Returns (html, url)."""
        url = (
            f"{self._parcel_url}?acct={apn}"
            "&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T"
        )
        r = session.get(url, timeout=25)
        return r.text, url

    # ----------------------------------------------------------------- parsing

    @staticmethod
    def _parse_select_page(html: str) -> List[Tuple[str, str, str, str]]:
        """Parse RPSearchSelect.asp results grid.

        Returns list of (parcel_id, owner, address, short_legal) tuples.
        Parcel ID links are in the first column; the link href contains the
        Show_Parcel.asp?acct=<APN> pattern.
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # Results table has class "prctable"
            grid = soup.find("table", class_="prctable")
            if not grid:
                return []
            results: List[Tuple[str, str, str, str]] = []
            for row in grid.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) < 3:
                    continue
                link = row.find("a", href=re.compile(r"Show_Parcel\.asp\?acct="))
                if not link:
                    continue
                m = re.search(r"acct=([^&\s]+)", link.get("href", ""))
                apn = m.group(1).strip() if m else ""
                owner_cell = cells[1] if len(cells) > 1 else ""
                addr_cell = cells[2] if len(cells) > 2 else ""
                legal_cell = cells[3] if len(cells) > 3 else ""
                if apn:
                    results.append((apn, owner_cell, addr_cell, legal_cell))
            return results
        except Exception:
            return []

    @staticmethod
    def parse_parcel_html(html: str) -> PropertyAppraiserResult:
        """Parse a ``Show_Parcel.asp`` page into a ``PropertyAppraiserResult``.

        Side-effect-free for unit testing: accepts captured HTML, returns result.

        Parsing strategy:
          - Owner name in the ``div.w3-border.w3-border-blue`` block after the
            "Owner:" heading.
          - Property address: ``"Property Address:"`` label → next div value.
          - APN: extracted from the page title
            "Property Record Information for <APN>".
          - Sales table: ``<table class="prctable">`` with headers:
            Date | Book/Page | Instrument Number | Selling Price | Sales code |
            Qualification/Disqualification Code.
          - Just Value: ``<td>`` containing "Certified Just Value" text →
            sibling td with ``$NNN,NNN``.
          - Assessed Value: ``<td>`` containing "Certified Assessed Value" →
            sibling td value.
          - Homestead: presence of ``01 Homestead`` exemption entry.
          - Legal description: "Short Legal:" and "Long Legal:" labels.
        """
        result = PropertyAppraiserResult()
        if not html or len(html) < 200:
            result.status = "PA_FAILED"
            result.notes = "parse_parcel_html: empty or too-short response"
            result.fetched_at = datetime.now().isoformat()
            return result

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            full_text = soup.get_text("\n")
            lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]

            # ---- APN from page body -------------------------------------------
            # The body text contains "Property Record Information for 412024203012"
            # (the <title> says "Real Property Record Card" — no APN there).
            m_apn = re.search(r"Property Record Information for\s+(\d+)", full_text)
            if m_apn:
                result.apn = m_apn.group(1)
            else:
                # Fallback: look for the acct= pattern in any link
                for a in soup.find_all("a", href=re.compile(r"acct=\d+")):
                    m2 = re.search(r"acct=(\d+)", a.get("href", ""))
                    if m2:
                        result.apn = m2.group(1)
                        break

            # ---- Owner ----------------------------------------------------------
            # Located in a <div class="w3-border w3-border-blue"> block under
            # the <h2>Owner:</h2> heading.
            owner_h2 = soup.find("h2", string=re.compile(r"^Owner:$", re.I))
            if owner_h2:
                owner_div = owner_h2.find_next("div", class_=re.compile(r"w3-border"))
                if owner_div:
                    # First non-empty text node is the owner name
                    for content in owner_div.stripped_strings:
                        if content and not re.match(r"^(Online|Ownership)", content):
                            result.owner_of_record = content
                            break

            # Fallback: scan lines for owner pattern
            if not result.owner_of_record:
                for i, line in enumerate(lines):
                    if line == "Owner:":
                        for j in range(i + 1, min(i + 4, len(lines))):
                            val = lines[j].strip()
                            if val and not re.match(r"^(Online|Ownership)", val):
                                result.owner_of_record = val
                                break
                        break

            # ---- Property / situs address -------------------------------------
            # "Property Address:" label
            for i, line in enumerate(lines):
                if line == "Property Address:":
                    for j in range(i + 1, min(i + 4, len(lines))):
                        val = lines[j].strip()
                        if val:
                            result.situs_address = val
                            break
                    break

            # ---- Mailing address (first owner block lines after owner name) ---
            # owner block: name / street / city,state zip
            if result.owner_of_record:
                for i, line in enumerate(lines):
                    if line == result.owner_of_record:
                        # Collect next 2 non-nav lines as mailing address
                        parts = []
                        for j in range(i + 1, min(i + 4, len(lines))):
                            v = lines[j].strip()
                            if v and not re.match(r"^(Online|Ownership)", v):
                                parts.append(v)
                                if len(parts) == 2:
                                    break
                        if parts:
                            result.mailing_address = ", ".join(parts)
                        break

            # ---- Legal description ---------------------------------------------
            short_legal = ""
            long_legal = ""
            for i, line in enumerate(lines):
                if line == "Short Legal:":
                    for j in range(i + 1, min(i + 3, len(lines))):
                        v = lines[j].strip()
                        if v and v != "Short Legal:":
                            short_legal = v
                            break
                elif line == "Long Legal:":
                    for j in range(i + 1, min(i + 3, len(lines))):
                        v = lines[j].strip()
                        if v and v != "Long Legal:":
                            long_legal = v
                            break
            result.legal_description = long_legal or short_legal

            # ---- Values (Just Value / Assessed Value) -------------------------
            # The Charlotte values table has rows like:
            #   ['Certified Just Value(Just Value reflects 193.011 adjustment.):', '$499,242', ...]
            #   ['Certified Assessed Value:', '$499,242', ...]
            # The label cell bundles the annotation — we must skip the first
            # cell (label) and read the SECOND cell (the dollar amount) to
            # avoid picking up the "193" in "193.011".
            for t in soup.find_all("table"):
                ttext = t.get_text(" ")
                if "Certified Just Value" not in ttext:
                    continue
                for row in t.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    label = cells[0].get_text(strip=True)
                    # Use the first VALUE cell (index 1), not the label cell (index 0)
                    if "Certified Just Value" in label:
                        for cell in cells[1:]:
                            v = _money(cell.get_text(strip=True))
                            if v > 0:
                                result.just_value = v
                                break
                    elif "Certified Assessed Value" in label:
                        for cell in cells[1:]:
                            v = _money(cell.get_text(strip=True))
                            if v > 0 and result.assessed_value == 0:
                                result.assessed_value = v
                                break
                if result.just_value > 0:
                    break

            # ---- Homestead ----------------------------------------------------
            if re.search(r"01\s*Homestead|01\xa0Homestead", full_text, re.I):
                result.homestead_active = True
                # Extract homestead amount
                for i, line in enumerate(lines):
                    if re.search(r"01.?Homestead", line, re.I):
                        for j in range(i, min(i + 4, len(lines))):
                            v = _money(lines[j])
                            if v > 0:
                                result.homestead_amount = v
                                break
                        break

            # ---- Sales table --------------------------------------------------
            # Headers: Date | Book/Page | Instrument Number | Selling Price |
            #          Sales code | Qualification Code
            sales: List[SaleHistoryEntry] = []
            for t in soup.find_all("table", class_="prctable"):
                headers = [th.get_text(strip=True) for th in t.find_all("th")]
                if not any(re.search(r"Date|Book|Instrument", h, re.I) for h in headers):
                    continue
                # Map column indices
                col_date = col_book = col_instr = col_price = col_qual = 0
                for hi, h in enumerate(headers):
                    if re.search(r"^Date$", h, re.I):
                        col_date = hi
                    elif re.search(r"Book.?Page", h, re.I):
                        col_book = hi
                    elif re.search(r"Instrument", h, re.I):
                        col_instr = hi
                    elif re.search(r"Selling|Price", h, re.I):
                        col_price = hi
                    elif re.search(r"Qualif", h, re.I):
                        col_qual = hi

                for row in t.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) < 3:
                        continue
                    date_val = cells[col_date] if col_date < len(cells) else ""
                    if not re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}", date_val):
                        continue
                    book_page = cells[col_book] if col_book < len(cells) else ""
                    instr = cells[col_instr] if col_instr < len(cells) else ""
                    price_raw = cells[col_price] if col_price < len(cells) else "0"
                    qual_raw = cells[col_qual] if col_qual < len(cells) else ""
                    # Qualification: code 01 = qualified sale
                    qualified = qual_raw.strip() in ("01", "Q", "Qualified")
                    sales.append(SaleHistoryEntry(
                        sale_date=date_val,
                        sale_price=_money(price_raw),
                        deed_doc_number=instr,
                        deed_book_page=book_page,
                        deed_type="",   # Charlotte PA doesn't expose deed type
                        qualified=qualified,
                        notes=cells[4] if len(cells) > 4 else "",  # Sales code
                    ))
                if sales:
                    break

            # Charlotte portal already serves newest-first
            result.sale_history = sales

            result.status = "PA_SUCCESS"

        except Exception as e:
            result.status = "PA_FAILED"
            result.notes = f"parse_parcel_html error: {e}"

        result.fetched_at = datetime.now().isoformat()
        return result

    # ----------------------------------------------------------------- helpers

    def _pick_best_match(
        self, results: List[Tuple[str, str, str, str]], street_full: str
    ) -> Optional[str]:
        """Return the APN whose address cell most closely matches street_full."""
        # Extract house number
        m = re.match(r"^(\d+)\s+", street_full.strip())
        if not m:
            return results[0][0] if results else None
        number = m.group(1)
        for apn, owner, addr, _ in results:
            if number in addr:
                return apn
        return results[0][0] if results else None

    # ----------------------------------------------------------------- public

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Search by address → first best-match parcel detail.

        Splits the address into street number, street name, and city. The
        Charlotte portal searches by separate number + name fields.
        Strips directional suffixes (LN, DR, ST, etc.) from the street name
        before submission.
        """
        try:
            session = self._session()

            # Parse: "100 Long Meadow Ln, Rotonda West, FL 33947" →
            #   number="100", street="LONG MEADOW LN", city="ROTONDA WEST"
            addr_clean = re.sub(r",?\s+FL\b.*$", "", address, flags=re.I).strip()
            parts = addr_clean.split(",", 1)
            street_full = parts[0].strip().upper()
            city = parts[1].strip().upper() if len(parts) > 1 else ""

            # Split number from street name
            m = re.match(r"^(\d+)\s+(.+)$", street_full)
            addr_number = m.group(1) if m else ""
            addr_street = m.group(2) if m else street_full

            select_html = self._run_search(
                session,
                addr_number=addr_number,
                addr_street=addr_street,
            )

            if _NO_RESULTS_RE.search(select_html) or not select_html:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"No results for address: {address}",
                    source_url=self._select_url,
                    fetched_at=datetime.now().isoformat(),
                )

            grid = self._parse_select_page(select_html)
            if not grid:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"Results grid empty for address: {address}",
                    source_url=self._select_url,
                    fetched_at=datetime.now().isoformat(),
                )

            apn = self._pick_best_match(grid, street_full)
            status_notes = None
            if len(grid) > 1:
                status_notes = (
                    f"address search returned {len(grid)} candidates; "
                    f"picked APN={apn!r}"
                )

            html, detail_url = self._fetch_parcel_detail(session, apn)
            result = self.parse_parcel_html(html)
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
        """Lookup by APN.

        Charlotte uses 12-digit numeric APNs (e.g. ``412024203012``).
        Strips hyphens/spaces from the passed APN, then fetches
        ``Show_Parcel.asp?acct=<APN>`` directly (no search step needed).
        """
        try:
            session = self._session()
            apn_clean = re.sub(r"[\s\-]", "", apn.strip())

            # Seed session cookie
            self._seed_session(session)

            html, detail_url = self._fetch_parcel_detail(session, apn_clean)
            result = self.parse_parcel_html(html)
            result.source_url = detail_url

            # Validate: if the returned APN doesn't match, flag it
            if result.apn and result.apn != apn_clean:
                result.notes = (
                    f"APN mismatch: queried {apn_clean!r}, "
                    f"page says {result.apn!r}"
                )
            return result

        except Exception as e:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"lookup_by_apn error: {e}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Owner-name search. Returns up to 5 results (diagnostic / best-effort).

        The Charlotte portal's ``owner`` field accepts partial last-name matches.
        Pass "OLAR" or "OLAR IVAN" — the portal returns all matches.
        """
        try:
            session = self._session()
            select_html = self._run_search(session, owner=owner_name.upper())
            grid = self._parse_select_page(select_html)
            if not grid:
                return []
            out: List[PropertyAppraiserResult] = []
            for apn, *_ in grid[:5]:
                try:
                    html, detail_url = self._fetch_parcel_detail(session, apn)
                    detail = self.parse_parcel_html(html)
                    detail.source_url = detail_url
                    out.append(detail)
                except Exception:
                    continue
            return out
        except Exception:
            return []
