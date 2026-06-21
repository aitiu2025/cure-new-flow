"""Escambia County (FL) Property Appraiser (ESCPA) HTTP adapter — Phase 1a anchor.

Derived from the 2026-06-14 live probe (see
docs/FL/source/landmark_pa_probe/fl_escambia/probe_observed.md). ESCPA at
https://www.escpa.org/ is an ASP.NET WebForms app. Two endpoints carry
everything Phase 1a needs:

  - ``/CAMA/Search.aspx``  (GET for VIEWSTATE tokens, POST to search)
        Single search box ``ctl00$MasterPlaceHolder$txtValue`` (address /
        owner "Last First" / 16-digit Parcel ID / 9-digit Account). Check
        ``ctl00$MasterPlaceHolder$chkSubParcels`` to get the per-parcel grid.
        Submit = ``ctl00$MasterPlaceHolder$btnSubmit`` -> 302 ->
        ``SearchResultList.aspx`` whose grid rows expose Account + 16-digit
        Parcel ID + owner + situs.
  - ``/CAMA/Detail_a.aspx?s=<16-digit-ParcelID>``  (GET)
        **Direct, parcel-keyed** detail page (no postback/session). Renders
        General Information (Owners/Mail/Situs/Use Code), an Assessments table
        (Year/Land/Imprv/Total/Cap Val), a Sales Data table (Sale Date/Book/
        Page/Value/Type -- newest first; the deed back-chain), Certified Roll
        Exemptions, Legal Description, and Acreage.

Parsing strategy: ESCPA renders server-side, so the values are in the HTML
text. We parse ``BeautifulSoup.get_text("\\n")`` by section labels rather than
brittle table selectors -- resilient to exact markup, and what the unit-test
fixtures (captured live) validate.

HTTP-only via curl_cffi (Tony directive #1 -- no Selenium/Playwright). ESCPA has
no Cloudflare/Akamai/CAPTCHA, but is only reachable from a US residential egress.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "chrome120"
_PARCEL_RE = re.compile(r"\b(\d{3}[A-Z0-9]\d{12})\b")  # e.g. 000S009007003004
_MONEY_RE = re.compile(r"\$?([\d,]+)")


def _money(s: str) -> int:
    m = _MONEY_RE.search(s or "")
    return int(m.group(1).replace(",", "")) if m else 0


class EscambiaPA(AbstractPropertyAppraiser):
    """ASP.NET WebForms adapter for Escambia County (FL) Property Appraiser."""

    SOURCE_LABEL = "Escambia County Property Appraiser"
    LIVE_PLATFORM = "escambia_pa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_escambia")
        self.county_name = self.config.get("county_name", "Escambia")
        self.source_label = self.SOURCE_LABEL
        self.base_url = (self.config.get("base_url") or "https://www.escpa.org/").rstrip("/")
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        self.search_url = f"{self.base_url}/CAMA/Search.aspx"
        self.detail_url = f"{self.base_url}/CAMA/Detail_a.aspx"

    # ------------------------------------------------------------------ net
    def _session(self):
        from curl_cffi import requests as cffi  # local import; optional dep
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    @staticmethod
    def _hidden(html: str, name: str) -> str:
        m = re.search(
            r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html
        ) or re.search(
            r'value="([^"]*)"[^>]*name="%s"' % re.escape(name), html
        )
        return m.group(1) if m else ""

    def _resolve_parcel_id_by_address(self, session, address: str) -> Optional[str]:
        """Search by address; return the first 16-digit Parcel ID in the grid."""
        get = session.get(self.search_url)
        form = {
            "__VIEWSTATE": self._hidden(get.text, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": self._hidden(get.text, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": self._hidden(get.text, "__EVENTVALIDATION"),
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$MasterPlaceHolder$txtValue": address,
            "ctl00$MasterPlaceHolder$chkSubParcels": "on",
            "ctl00$MasterPlaceHolder$btnSubmit": "Search",
        }
        res = session.post(self.search_url, data=form)
        m = _PARCEL_RE.search(res.text)
        return m.group(1) if m else None

    # -------------------------------------------------------------- parsing
    @staticmethod
    def _html_to_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(html, "html.parser").get_text("\n")
        except Exception:
            return re.sub(r"<[^>]+>", "\n", html)

    # General-Information labels whose value the live page renders on the NEXT
    # line (each table cell is its own get_text() line). We re-join them so the
    # downstream label parsers see "Label: value" -- the captured-fixture shape.
    _GI_LABELS = ("Parcel ID:", "Account:", "Owners:", "Mail:",
                  "Situs:", "Use Code:", "Taxing")
    _ASSESS_HEADER = ("Year", "Land", "Imprv", "Total", "Cap Val")
    _SALES_HEADER = ("Sale Date", "Book", "Page", "Value", "Type")

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Collapse the live per-cell-per-line layout into the single-line-row
        shape the captured-fixture parsers already handle.

        The live ESCPA detail page (BeautifulSoup.get_text) renders every table
        cell and every General-Information value on its own line, plus a
        "Nav. Mode" preamble that emits bare ``Account`` / ``Parcel ID`` labels
        BEFORE the real General Information section. The hand-cleaned unit-test
        fixtures, by contrast, put each logical row on one line and carry no
        preamble. Normalizing both into the same shape keeps the fixture tests
        green while fixing the live parse. Idempotent: fixture text passes
        through essentially unchanged.
        """
        raw = [ln.strip() for ln in text.splitlines()]
        # Drop everything before the real "General Information" section header
        # (kills the Nav. Mode bare-label preamble that poisons after()).
        for i, ln in enumerate(raw):
            if ln == "General Information":
                raw = raw[i:]
                break
        # Drop blank lines; per-cell rows are reconstructed positionally.
        lines = [ln for ln in raw if ln]

        out: List[str] = []
        i = 0
        n = len(lines)
        money = re.compile(r"^\$?[\d,]+$")
        date = re.compile(r"^\d{1,2}/\d{4}$")
        while i < n:
            ln = lines[i]

            # 1) "Label:" alone -> join with the following value line(s).
            if ln.endswith(":") and any(
                ln == lab or ln.startswith(lab) for lab in cls._GI_LABELS
            ):
                vals = []
                j = i + 1
                while j < n and not lines[j].endswith(":") \
                        and lines[j] not in ("Assessments", "Sales Data"):
                    # Owners/Mail wrap onto a couple of lines; stop at next label.
                    vals.append(lines[j])
                    j += 1
                    # Single-value labels take exactly one line.
                    if ln in ("Parcel ID:", "Account:", "Situs:", "Use Code:"):
                        break
                out.append(f"{ln} {' '.join(vals)}".rstrip())
                i = j
                continue

            # 2) Assessment header -> emit header + reconstruct YEAR-led rows.
            if ln == "Year" and i + 4 < n and lines[i + 1] == "Land":
                out.append(" ".join(cls._ASSESS_HEADER))
                i += len(cls._ASSESS_HEADER)
                while i + 4 < n and re.fullmatch(r"\d{4}", lines[i]) \
                        and money.match(lines[i + 1]):
                    out.append(" ".join(lines[i:i + 5]))
                    i += 5
                continue

            # 3) Sales header -> emit header + reconstruct DATE-led rows.
            if ln == "Sale Date" and i + 1 < n and lines[i + 1] == "Book":
                # Header spans Sale Date/Book/Page/Value/Type/Multi Parcel/Records
                hdr_end = i + 1
                while hdr_end < n and not date.match(lines[hdr_end]):
                    hdr_end += 1
                out.append("Sale Date Book Page Value Type Multi Parcel Records")
                i = hdr_end
                while i + 5 < n and date.match(lines[i]) \
                        and money.match(lines[i + 3]):
                    # date book page value type multi
                    out.append(" ".join(lines[i:i + 6]))
                    i += 6
                continue

            out.append(ln)
            i += 1

        return "\n".join(out)

    def parse_detail_text(self, text: str) -> PropertyAppraiserResult:
        """Parse ESCPA detail page text -> PropertyAppraiserResult.

        Side-effect-free + public so unit tests feed captured fixtures.
        """
        text = self._normalize_text(text)
        lines = [ln.rstrip() for ln in text.splitlines()]

        def after(label: str) -> str:
            for i, ln in enumerate(lines):
                if ln.strip().startswith(label):
                    rest = ln.strip()[len(label):].strip(" :").strip()
                    if rest:
                        return rest
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip():
                            return lines[j].strip()
            return ""

        res = PropertyAppraiserResult()
        res.apn = after("Parcel ID")
        res.folio = after("Account")
        res.source_url = f"{self.detail_url}?s={res.apn}" if res.apn else ""

        # Owners: capture line(s) after "Owners:" up to the "Mail" label.
        owner_lines: List[str] = []
        capt = False
        for ln in lines:
            s = ln.strip()
            if s.startswith("Owners"):
                capt = True
                rest = s.split(":", 1)[1].strip() if ":" in s else ""
                if rest:
                    owner_lines.append(rest)
                continue
            if capt:
                if not s or s.startswith("Mail"):
                    break
                owner_lines.append(s)
        res.owner_of_record = " ".join(owner_lines).strip()

        res.situs_address = after("Situs")
        res.legal_description = self._section_after(lines, "Legal Description")

        # Assessments: first data row after "Year ... Cap Val" header.
        for i, ln in enumerate(lines):
            if ln.strip().startswith("Year") and "Cap Val" in ln:
                for j in range(i + 1, len(lines)):
                    cells = lines[j].split()
                    if len(cells) >= 5 and re.fullmatch(r"\d{4}", cells[0]):
                        res.just_value = _money(cells[3])       # Total
                        res.assessed_value = _money(cells[-1])  # Cap Val
                        break
                break

        exempt = self._section_after(lines, "Certified Roll Exemptions")
        res.homestead_active = "HOMESTEAD" in exempt.upper()

        res.sale_history = self._parse_sales(lines)
        res.status = "PA_SUCCESS" if res.apn else "PA_NO_RESULTS"
        res.fetched_at = datetime.now().isoformat()
        return res

    @staticmethod
    def _section_after(lines: List[str], header: str) -> str:
        for i, ln in enumerate(lines):
            if ln.strip() == header or ln.strip().startswith(header):
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        return lines[j].strip()
        return ""

    @staticmethod
    def _parse_sales(lines: List[str]) -> List[SaleHistoryEntry]:
        sales: List[SaleHistoryEntry] = []
        start = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("Sale Date") and "Book" in s and "Value" in s:
                start = i + 1
                break
        if start is None:
            return sales
        row_re = re.compile(
            r"^(\d{1,2}/\d{4})\s+(\S+)\s+(\S+)\s+\$?([\d,]+)\s+([A-Z]{1,3})\s+([YN])"
        )
        for ln in lines[start:]:
            s = ln.strip()
            if s.startswith(("Official Records", "Certified", "Legal Description")):
                break
            m = row_re.match(s)
            if m:
                date, book, page, value, dtype, _multi = m.groups()
                sales.append(SaleHistoryEntry(
                    sale_date=date,
                    sale_price=int(value.replace(",", "")),
                    deed_book_page=f"{book}/{page}",
                    deed_type=dtype,
                ))
        return sales

    # --------------------------------------------------------- entry points
    def _fetch_detail(self, parcel_id: str) -> PropertyAppraiserResult:
        try:
            session = self._session()
            r = session.get(self.detail_url, params={"s": parcel_id})
            if r.status_code != 200 or "Parcel ID" not in r.text:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"ESCPA detail returned {r.status_code} for parcel {parcel_id}",
                    fetched_at=datetime.now().isoformat(),
                )
            return self.parse_detail_text(self._html_to_text(r.text))
        except Exception as exc:  # fail soft per base contract
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"ESCPA detail fetch error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        parcel = re.sub(r"[^0-9A-Za-z]", "", apn or "").upper()
        return self._fetch_detail(parcel)

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        try:
            session = self._session()
            parcel = self._resolve_parcel_id_by_address(session, address)
            if not parcel:
                return PropertyAppraiserResult(
                    status="PA_NO_RESULTS",
                    notes=f"ESCPA address search returned no parcel for {address!r}",
                    fetched_at=datetime.now().isoformat(),
                )
            return self._fetch_detail(parcel)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"ESCPA address lookup error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        try:
            session = self._session()
            parcel = self._resolve_parcel_id_by_address(session, owner_name)
            return [self._fetch_detail(parcel)] if parcel else []
        except Exception:
            return []
