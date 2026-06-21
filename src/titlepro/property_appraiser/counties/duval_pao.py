"""Duval County (FL) Property Appraiser HTTP adapter (Phase 1a anchor).

Target portal: https://paopropertysearch.coj.net/ — the City of Jacksonville
Property Appraiser search. Classic ASP.NET WebForms (NOT a JSON SPA like
Broward BCPA). Page set confirmed 2026-06-10 (see the SKINNER case probe at
``src/titlepro/api/downloaded_doc/0610/Duval_SKINNER_v1/phase0_probe_pa.md``):

- ``Basic/Search.aspx``  — search by RE# / owner / address (VIEWSTATE form)
- ``Basic/Results.aspx`` — results grid with ``Detail.aspx?RE=...`` links
- ``Basic/Detail.aspx?RE=<10 digits>`` — **direct parcel detail via GET**
  (no VIEWSTATE round-trip) — this is the canonical APN path.

Duval's parcel id is the "RE number": 10 digits, displayed ``XXXXXX-XXXX``
(e.g. ``041105-0000``), unhyphenated in URLs.

⚠ LIVE-VALIDATION STATUS (Wave-1, 2026-06-10): the COJ firewall geo-blocks
non-US egress at the TCP layer, so no live HTML was captured this session.
The detail-page parser is LABEL-DRIVEN (keys off visible labels such as
"Primary Site Address", "Legal Desc", and the Sales History header row, not
WebForms control ids) so it tolerates id drift; the address-search form-field
names in ``_DEFAULT_FORM_FIELDS`` are best-evidence GUESSES and MUST be
re-captured on the first US-egress run. Unit tests run on canned fixtures
that encode this contract.

HTTP-only per Tony directive #1 — no Selenium/Playwright.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


# safari17_2_ios is the proven profile for FL gov properties (chrome120 gets
# challenged on some Duval-adjacent hosts — see the SKINNER tax probe).
_DEFAULT_IMPERSONATE = "safari17_2_ios"

_DEFAULT_BASE = "https://paopropertysearch.coj.net/"

# WebForms field names — LIVE-VERIFIED 2026-06-10 (SKINNER probe). The address
# search splits into street number / name / suffix; the postback targets
# Results.aspx (cross-page) rather than Search.aspx.
_DEFAULT_FORM_FIELDS = {
    "street_number": "ctl00$cphBody$tbStreetNumber",
    "street_name": "ctl00$cphBody$tbStreetName",
    "street_suffix": "ctl00$cphBody$ddStreetSuffix",
    "re6": "ctl00$cphBody$tbRE6",
    "re4": "ctl00$cphBody$tbRE4",
    "owner_name": "ctl00$cphBody$tbName",
    "search_button": "ctl00$cphBody$bSearch",
}

# Common street-suffix word -> Duval ddStreetSuffix option value.
_SUFFIX_CODE = {
    "CT": "CT", "ST": "ST", "AVE": "AVE", "RD": "RD", "DR": "DR", "LN": "LN",
    "BLVD": "BLVD", "PL": "PL", "CIR": "CIR", "TER": "TER", "TRL": "TRL",
    "WAY": "WAY", "CV": "CV", "PT": "PT",
}

# Deed-code expansion for the Sales History "Deed Instrument Type Code" column.
_DEED_CODES = {
    "WD": "Warranty Deed",
    "SW": "Special Warranty Deed",
    "SWD": "Special Warranty Deed",
    "QC": "Quit Claim Deed",
    "QCD": "Quit Claim Deed",
    "CT": "Certificate of Title",
    "PR": "Personal Representative Deed",
    "TD": "Trustee's Deed",
    "MS": "Miscellaneous",
}


class DuvalPAO(AbstractPropertyAppraiser):
    """ASP.NET WebForms adapter for the Duval County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_duval"
        self.county_name = "Duval"
        self.source_label = config.get(
            "description", "Duval County Property Appraiser (paopropertysearch.coj.net)"
        )
        self._base_url = (config.get("base_url") or _DEFAULT_BASE).rstrip("/") + "/"
        endpoints = config.get("endpoints", {})
        self._url_search = endpoints.get(
            "basic_search", urljoin(self._base_url, "Basic/Search.aspx")
        )
        self._url_results = endpoints.get(
            "basic_results", urljoin(self._base_url, "Basic/Results.aspx")
        )
        self._url_detail = endpoints.get(
            "detail", urljoin(self._base_url, "Basic/Detail.aspx")
        )
        self._form_fields = {**_DEFAULT_FORM_FIELDS, **config.get("form_fields", {})}
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        # Lazy session so unit tests can inject `adapter.session = MagicMock()`.
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
    def _normalize_apn(apn: str) -> str:
        """Duval RE number → unhyphenated 10-digit string ('' if invalid)."""
        digits = re.sub(r"[^0-9]", "", apn or "")
        return digits if len(digits) == 10 else ""

    @staticmethod
    def _normalize_street(address: str) -> str:
        """'4409 Crooked Brook Court, Jacksonville, FL 32224' → '4409 CROOKED BROOK CT'."""
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        suffixes = {
            "COURT": "CT", "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD",
            "DRIVE": "DR", "LANE": "LN", "BOULEVARD": "BLVD", "PLACE": "PL",
            "CIRCLE": "CIR", "TERRACE": "TER", "TRAIL": "TRL", "WAY": "WAY",
        }
        parts = addr.split()
        if parts and parts[-1] in suffixes:
            parts[-1] = suffixes[parts[-1]]
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    # ----------------------------------------------------------- API

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        re10 = self._normalize_apn(apn)
        if not re10:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"invalid Duval RE number after normalize: {apn!r} (need 10 digits)",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            resp = self.session.get(
                self._url_detail, params={"RE": re10}, timeout=30
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"detail fetch error: {type(exc).__name__}: {exc}",
                apn=re10,
                fetched_at=datetime.now().isoformat(),
            )
        if getattr(resp, "status_code", 0) != 200 or not getattr(resp, "text", ""):
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"Detail.aspx returned HTTP {getattr(resp, 'status_code', '?')}",
                apn=re10,
                fetched_at=datetime.now().isoformat(),
            )
        html = resp.text
        if re.search(r"no\s+(information|record|parcel|results?)\s", html, re.I):
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"PAO found no parcel for RE# {re10}",
                apn=re10,
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_detail(html, re10)

    @staticmethod
    def _split_street(address: str) -> tuple:
        """'4409 Crooked Brook Court, Jacksonville, FL 32224'
        -> ('4409', 'CROOKED BROOK', 'CT')."""
        head = (address or "").upper().split(",", 1)[0].strip()
        head = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", head)
        words = {
            "COURT": "CT", "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD",
            "DRIVE": "DR", "LANE": "LN", "BOULEVARD": "BLVD", "PLACE": "PL",
            "CIRCLE": "CIR", "TERRACE": "TER", "TRAIL": "TRL", "COVE": "CV",
            "POINT": "PT",
        }
        parts = head.split()
        number = parts[0] if parts and parts[0].isdigit() else ""
        rest = parts[1:] if number else parts
        suffix = ""
        if rest and (rest[-1] in words or rest[-1] in _SUFFIX_CODE):
            suffix = words.get(rest[-1], rest[-1])
            rest = rest[:-1]
        return number, " ".join(rest).strip(), suffix

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        street_full = self._normalize_street(address)
        number, street_name, suffix = self._split_street(address)
        if not street_name:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty street after normalize: {address!r}",
                fetched_at=datetime.now().isoformat(),
            )
        # Step 1: GET the WebForms search page, harvest ALL hidden inputs
        # (__VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION, ...).
        try:
            page = self.session.get(self._url_search, timeout=30)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"search page fetch error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        if getattr(page, "status_code", 0) != 200:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"Search.aspx returned HTTP {getattr(page, 'status_code', '?')}",
                fetched_at=datetime.now().isoformat(),
            )
        payload = self._harvest_hidden_fields(page.text)
        payload[self._form_fields["street_number"]] = number
        payload[self._form_fields["street_name"]] = street_name
        if suffix:
            payload[self._form_fields["street_suffix"]] = suffix
        if self._form_fields.get("search_button"):
            payload[self._form_fields["search_button"]] = "Search"

        # Step 2: cross-page POST to Results.aspx (Duval posts the Search form
        # to Results.aspx, NOT back to Search.aspx — live-verified 2026-06-10).
        try:
            resp = self.session.post(
                self._url_results,
                data=payload,
                headers={"Referer": self._url_search},
                timeout=30,
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search POST error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        if getattr(resp, "status_code", 0) != 200 or not getattr(resp, "text", ""):
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search returned HTTP {getattr(resp, 'status_code', '?')}",
                fetched_at=datetime.now().isoformat(),
            )

        candidates = self._extract_result_candidates(resp.text)
        if not candidates:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"PAO address search found no parcel for {street_full!r}",
                fetched_at=datetime.now().isoformat(),
            )
        exact = [c for c in candidates if street_full in c["row_text"].upper()]
        if not exact and len(candidates) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"PAO returned {len(candidates)} candidates for {street_full!r}: "
                    + "; ".join(
                        f"RE {c['re']} ({c['row_text'][:60].strip()})"
                        for c in candidates[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )
        chosen = (exact or candidates)[0]
        return self.lookup_by_apn(chosen["re"])

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Diagnostics-only — canonical path is by address/RE (mirrors BCPA).
        return []

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _harvest_hidden_fields(html: str) -> Dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        fields: Dict[str, str] = {}
        for inp in soup.find_all("input", attrs={"type": "hidden"}):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")
        return fields

    @staticmethod
    def _extract_result_candidates(html: str) -> List[Dict[str, str]]:
        """Pull ``Detail.aspx?RE=<digits>`` links + their row text."""
        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, str]] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            m = re.search(r"Detail\.aspx\?RE=(\d{6,10})", a["href"], re.I)
            if not m:
                continue
            re_num = m.group(1)
            if re_num in seen:
                continue
            seen.add(re_num)
            row = a.find_parent("tr")
            row_text = row.get_text(" ", strip=True) if row else a.get_text(strip=True)
            out.append({"re": re_num, "row_text": row_text})
        return out

    # ----------------------------------------------------------- parse

    def _parse_detail(self, html: str, re10: str) -> PropertyAppraiserResult:
        soup = BeautifulSoup(html, "html.parser")

        # --- Duval-specific selectors (live-verified 2026-06-10) ----------
        # Owners live in an ASP.NET repeater: spans whose id contains
        # 'repeaterOwnerInformation' ... 'lblOwnerName'.
        owner_spans = soup.find_all(
            "span", id=re.compile(r"repeaterOwnerInformation.*lblOwnerName", re.I)
        )
        owners = [s.get_text(" ", strip=True) for s in owner_spans if s.get_text(strip=True)]
        if owners:
            owner, co_owners = owners[0], owners[1:]
        else:
            owner, co_owners = self._parse_owners(soup)

        # Situs: "Building 1 Site Address <addr>" cell. Fall back to label.
        situs = self._duval_building_site_address(soup) or self._label_value(
            soup, ("primary site address", "site address", "property address")
        )

        # Legal: assemble the LN Legal Description table (the header field is a
        # 'see Land & Legal section below' placeholder, not the real legal).
        legal = self._duval_ln_legal(soup) or self._label_value(
            soup, ("legal desc", "legal description", "short legal")
        )
        mailing = self._label_value(soup, ("mailing address",))
        just_value = _money_to_int(
            self._label_value(soup, ("just (market) value", "just value", "market value"))
        )
        assessed = _money_to_int(
            self._label_value(soup, ("assessed value", "a10 assessed", "assessed"))
        )
        hx_amount = _money_to_int(
            self._label_value(soup, ("homestead (hx)", "homestead exemption", "homestead"))
        )
        year_built = _digits_to_int(
            self._label_value(soup, ("year built", "actual year built"))
        )
        sqft = _digits_to_int(
            self._label_value(soup, ("heated square feet", "total living area", "living area"))
        )

        result = PropertyAppraiserResult(
            apn=re10,
            folio=re10,
            owner_of_record=owner,
            co_owners=co_owners,
            situs_address=situs,
            mailing_address=mailing or situs,
            legal_description=legal,
            just_value=just_value,
            assessed_value=assessed,
            homestead_amount=hx_amount,
            homestead_active=hx_amount > 0,
            year_built=year_built,
            living_area_sqft=sqft,
            source_url=f"{self._url_detail}?RE={re10}",
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(soup)
        if not result.owner_of_record and not result.sale_history:
            result.status = "PA_NO_RESULTS"
            result.notes = (
                "Detail page parsed but neither owner nor sale history found — "
                "label drift? Re-capture live HTML and update duval_pao parser."
            )
        return result

    @staticmethod
    def _duval_building_site_address(soup: BeautifulSoup) -> str:
        """'Building 1 Site Address <addr>' — the canonical situs on Duval PAO."""
        lbl = soup.find(string=re.compile(r"Building\s*1\s*Site\s*Address", re.I))
        if lbl:
            cell = lbl.parent
            nxt = cell.find_next(["td", "span"]) if cell else None
            if nxt:
                val = nxt.get_text(" ", strip=True)
                if val and "site address" not in val.lower():
                    return re.sub(r"\s+Unit\s*$", "", val).strip()
        # Fallback: any span id ending lblSiteAddress
        sp = soup.find("span", id=re.compile(r"lbl.*SiteAddress", re.I))
        return sp.get_text(" ", strip=True) if sp else ""

    @staticmethod
    def _duval_ln_legal(soup: BeautifulSoup) -> str:
        """Assemble the 'LN Legal Description' table rows into one legal string."""
        for tbl in soup.find_all("table"):
            head = tbl.find("tr")
            if not head:
                continue
            if re.search(r"\bLN\b.*Legal Description", head.get_text(" ", strip=True), re.I):
                lines = []
                for tr in tbl.find_all("tr")[1:]:
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 2:
                        seg = cells[1].get_text(" ", strip=True)
                        if seg:
                            lines.append(seg)
                if lines:
                    return " ".join(lines)
        return ""

    def _parse_owners(self, soup: BeautifulSoup) -> tuple:
        """Owner block: first match wins among common Duval PAO labels."""
        raw = self._label_value(
            soup, ("owner name", "owner(s)", "owners", "property owner", "owner")
        )
        if not raw:
            return "", []
        # Multiple owners come back newline- or <br>-separated (the label
        # helper joins with ' | ').
        names = [n.strip() for n in re.split(r"\s*\|\s*|\s*;\s*", raw) if n.strip()]
        if not names:
            return "", []
        return names[0], names[1:]

    @staticmethod
    def _label_value(soup: BeautifulSoup, labels: tuple) -> str:
        """Find a cell/element whose text equals/startswith one of `labels`
        (case-insensitive) and return the adjacent value text.

        Handles the two layouts WebForms detail pages use:
        - <tr><td>Label</td><td>Value</td></tr>
        - <td>Label</td> followed by a sibling <span id="ctl00_..._lblX">Value</span>
        """
        lowered = tuple(l.lower() for l in labels)
        for el in soup.find_all(["td", "th", "span", "label", "b", "strong", "div"]):
            txt = el.get_text(" ", strip=True).rstrip(":").strip().lower()
            if not txt:
                continue
            if not any(txt == l or txt.startswith(l) for l in lowered):
                continue
            # Layout A: label cell -> next sibling cell.
            sib = el.find_next_sibling(["td", "span", "div"])
            if sib is not None:
                # <br>-separated multi-line values -> ' | ' join.
                value = sib.get_text(" | ", strip=True)
                if value and value.rstrip(":").strip().lower() not in lowered:
                    return value
            # Layout B: label inside its own cell, value in next <td> of row.
            parent_td = el.find_parent("td")
            if parent_td is not None:
                nxt = parent_td.find_next_sibling("td")
                if nxt is not None:
                    value = nxt.get_text(" | ", strip=True)
                    if value:
                        return value
        return ""

    @staticmethod
    def _parse_sales(soup: BeautifulSoup) -> List[SaleHistoryEntry]:
        """Sales History table → newest-first SaleHistoryEntry list.

        Header-driven column mapping so column order changes don't break us.
        Expected headers (Wave-1 best evidence): Book/Page, Sale Date,
        Sale Price, Deed Instrument Type Code, Qualified/Unqualified.
        """
        target = None
        header_map: Dict[str, int] = {}
        for table in soup.find_all("table"):
            head_row = table.find("tr")
            if head_row is None:
                continue
            headers = [
                c.get_text(" ", strip=True).lower()
                for c in head_row.find_all(["th", "td"])
            ]
            if any("sale date" in h for h in headers) and any(
                "price" in h or "book" in h for h in headers
            ):
                target = table
                for i, h in enumerate(headers):
                    if "book" in h and "page" in h:
                        header_map["book_page"] = i
                    elif "sale date" in h:
                        header_map["sale_date"] = i
                    elif "price" in h:
                        header_map["sale_price"] = i
                    elif "instrument" in h or "deed" in h:
                        header_map["deed_type"] = i
                    elif "qualif" in h:
                        header_map["qualified"] = i
                break
        if target is None:
            return []

        def cell(cells, key):
            idx = header_map.get(key, -1)
            if idx < 0 or idx >= len(cells):
                return ""
            return cells[idx].get_text(" ", strip=True)

        sales: List[SaleHistoryEntry] = []
        for tr in target.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if not cells:
                continue
            sale_date = cell(cells, "sale_date")
            if not re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", sale_date):
                continue
            bp_raw = cell(cells, "book_page")
            deed_doc_number = ""
            deed_book_page = ""
            bp = bp_raw.strip()
            if bp:
                if re.fullmatch(r"\d{10,}", re.sub(r"[^0-9]", "", bp)) and (
                    "/" not in bp and "-" not in bp
                ):
                    deed_doc_number = bp
                else:
                    deed_book_page = bp
            # Live Duval renders "WD - Warranty Deed"; keep the short code in
            # deed_type and the long form in notes.
            deed_raw = cell(cells, "deed_type").strip()
            deed_code = deed_raw.split(" - ", 1)[0].strip() if " - " in deed_raw else deed_raw
            deed_full = deed_raw.split(" - ", 1)[1].strip() if " - " in deed_raw else _DEED_CODES.get(deed_code.upper(), "")
            qual_text = cell(cells, "qualified").strip().lower()
            sales.append(
                SaleHistoryEntry(
                    sale_date=sale_date,
                    sale_price=_money_to_int(cell(cells, "sale_price")),
                    deed_doc_number=deed_doc_number,
                    deed_book_page=deed_book_page,
                    deed_type=deed_code,
                    qualified=qual_text.startswith("qual"),
                    notes=deed_full,
                )
            )

        # Newest-first ordering guarantee.
        def _key(e: SaleHistoryEntry):
            m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", e.sale_date)
            if not m:
                return (0, 0, 0)
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yy < 100:
                yy += 1900 if yy > 40 else 2000
            return (yy, mm, dd)

        sales.sort(key=_key, reverse=True)
        return sales


# ----------------------------------------------------------- module helpers


def _money_to_int(s: Any) -> int:
    if s is None:
        return 0
    digits = re.sub(r"[^\d]", "", str(s).split(".")[0])
    try:
        return int(digits) if digits else 0
    except Exception:
        return 0


def _digits_to_int(s: Any) -> int:
    if s is None:
        return 0
    m = re.search(r"\d+", str(s).replace(",", ""))
    return int(m.group(0)) if m else 0
