"""Lee County (FL) Property Appraiser HTTP adapter (Phase 1a anchor).

Implementation derived from the 2026-06-10 OSTIGUY probe (see the case-folder
phase0_probe_pa.md). The LeePA public site at https://www.leepa.org/ is a
classic ASP.NET WebForms app. Two endpoints carry everything Phase 1a needs:

  - ``/Search/PropertySearch.aspx`` (GET for tokens, POST for the search)
        ASP.NET postback. Site-address search via the ``AddressTextBox`` field
        with ``__EVENTTARGET = ...SubmitPropertySearch``. Returns an HTML
        results grid; each match exposes a STRAP (``29-44-24-C2-00101.0150``)
        and a numeric FolioID (``10176930``) plus owner + situs.
  - ``/Display/DisplayParcel.aspx?FolioID=<folio>`` (GET)
        The detail page is hydrated client-side from an inline FL DOR **NAL**
        (Name-Address-Legal) field dump (``F01:`` .. ``F92:``). We parse that
        dump server-side. Field map (corroborated against the live OSTIGUY
        parcel + the homestead-exemption arithmetic):
            F02  unformatted STRAP / parcel id
            F08  Just / Market value
            F11  Assessed value (Save-Our-Homes capped)
            F13  County taxable (= F11 - homestead)
            F44  1st year building on tax roll (year built proxy)
            F47  building area sq ft (best-effort)
            F51  owner name (primary only; co-owner comes from the search grid)
            F52/F54/F55/F56  mailing street / city / state / zip
            F65  short legal / subdivision
            F79/F81/F82  situs street / city / zip
            F90  exemption codes ("01;25000;02;25722" -> homestead $25,000)

Sale history
------------
LeePA renders the "Sales / Transactions" grid lazily and, for parcels whose
recorded instruments are flagged "not viewable by the general public" (the
OSTIGUY subject is one), shows no public sale rows at all. ``_parse_sales``
therefore returns whatever public rows are present and is empty-safe; the
authoritative deed back-chain for such parcels comes from the Lee Clerk
recorder (Akamai-gated — see the recorder probe), not from LeePA.

Why HTTP not Playwright
-----------------------
``curl_cffi`` (chrome120 impersonate) passes every LeePA endpoint cleanly:
no Cloudflare, no Akamai, no CAPTCHA on leepa.org (only the *recorder* host
or.leeclerk.org is Akamai-fronted). Matches Tony directive #1.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"

_STRAP_RE = re.compile(r"\b\d{2}-\d{2}-\d{2}-[A-Z0-9]{2}-\d{5}\.\d{4}\b")
# Hidden ASP.NET field id="__NAME" value="..."
_HIDDEN_RE = r'id="%s"\s+value="([^"]*)"'

# Prefix used by the LeePA WebForms control tree for the property-search tab.
_TMPL = "ctl00$BodyContentPlaceHolder$WebTab1$tmpl0$"


class LeeLeePA(AbstractPropertyAppraiser):
    """ASP.NET WebForms adapter for Lee County (FL) Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_lee"
        self.county_name = "Lee"
        self.source_label = config.get(
            "description", "Lee County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._search_url = endpoints.get(
            "property_search", "https://www.leepa.org/Search/PropertySearch.aspx"
        )
        self._parcel_url = endpoints.get(
            "parcel_display", "https://www.leepa.org/Display/DisplayParcel.aspx"
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

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
    def _normalize_strap(apn: str) -> str:
        """Return the digits/letters of a STRAP without separators.

        "29-44-24-C2-00101.0150" -> "294424C200101.0150"-ish; we keep it loose
        and only use it for comparison, not as a lookup key (FolioID is the key).
        """
        return re.sub(r"[\s]", "", (apn or "").upper())

    @staticmethod
    def _is_folio(value: str) -> bool:
        return bool(re.fullmatch(r"\d{6,9}", (value or "").strip()))

    # USPS street-suffix words -> the abbreviation LeePA indexes on.
    _SUFFIX_MAP = {
        "DRIVE": "DR", "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD",
        "COURT": "CT", "LANE": "LN", "ROAD": "RD", "PLACE": "PL", "TERRACE": "TER",
        "CIRCLE": "CIR", "PARKWAY": "PKWY", "TRAIL": "TRL", "WAY": "WAY",
        "HIGHWAY": "HWY", "PLAZA": "PLZ", "SQUARE": "SQ",
    }

    @classmethod
    def _normalize_address_for_search(cls, address: str) -> str:
        """Drop city/state/zip and abbreviate the street-type suffix.

        LeePA's AddressTextBox indexes USPS-abbreviated street lines:
        "2137 Coral Point Drive" must be searched as "2137 CORAL POINT DR".
        """
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)  # ordinals: 27TH->27
        tokens = addr.split()
        if tokens and tokens[-1] in cls._SUFFIX_MAP:
            tokens[-1] = cls._SUFFIX_MAP[tokens[-1]]
        addr = " ".join(tokens)
        return re.sub(r"\s+", " ", addr).strip()

    # ----------------------------------------------------------- HTTP

    def _get_tokens(self, html: str) -> Dict[str, str]:
        def hid(name: str) -> str:
            m = re.search(_HIDDEN_RE % re.escape(name), html)
            return m.group(1) if m else ""

        return {
            "__VIEWSTATE": hid("__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": hid("__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": hid("__EVENTVALIDATION"),
        }

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        street = self._normalize_address_for_search(address)
        try:
            page = self.session.get(self._search_url, timeout=40)
            tokens = self._get_tokens(page.text)
        except Exception as exc:  # pragma: no cover - network guard
            return self._failed(f"search page GET error: {type(exc).__name__}: {exc}")

        data = {
            **tokens,
            "__EVENTTARGET": f"{_TMPL}SubmitPropertySearch",
            "__EVENTARGUMENT": "",
            f"{_TMPL}AddressTextBox": street,
            f"{_TMPL}OwnerNameTextBox": "",
            f"{_TMPL}STRAPTextBox": "",
            f"{_TMPL}LegalTextBox": "",
            f"{_TMPL}ZIPCodeTextBox": "",
            f"{_TMPL}CountryDropDownList": "UNITED STATES OF AMERICA",
            f"{_TMPL}SearchSouceGroup": "SiteRadioButton",
        }
        try:
            resp = self.session.post(self._search_url, data=data, timeout=60)
        except Exception as exc:  # pragma: no cover - network guard
            return self._failed(f"address search POST error: {type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            return self._failed(
                f"address search returned HTTP {resp.status_code}: {resp.text[:160]}"
            )

        rows = self._parse_search_results(resp.text)
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"LeePA found no parcel matching address {street!r}",
                fetched_at=datetime.now().isoformat(),
            )
        if len(rows) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"LeePA returned {len(rows)} candidates for {street!r}: "
                    + "; ".join(
                        f"{r['strap']} (folio {r['folio']})" for r in rows[:6]
                    )
                ),
                fetched_at=datetime.now().isoformat(),
            )

        chosen = rows[0]
        result = self.lookup_by_apn(chosen["folio"])
        # The search grid carries BOTH owners; the DisplayParcel NAL dump only
        # carries the primary. Prefer the fuller search-grid owner data.
        if result.status == "PA_SUCCESS" and chosen.get("owners"):
            result.owner_of_record = chosen["owners"][0]
            result.co_owners = chosen["owners"][1:]
            if chosen.get("strap"):
                result.apn = chosen["strap"]
            if not result.situs_address and chosen.get("situs"):
                result.situs_address = chosen["situs"]
        return result

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        raw = (apn or "").strip()
        if not raw:
            return self._failed(f"empty/invalid APN: {apn!r}")

        if self._is_folio(raw):
            folio = raw
        else:
            # A STRAP was supplied — resolve it to a FolioID via STRAP search.
            folio = self._resolve_strap_to_folio(raw)
            if not folio:
                return self._failed(f"could not resolve STRAP {raw!r} to a FolioID")

        try:
            resp = self.session.get(
                self._parcel_url, params={"FolioID": folio}, timeout=60
            )
        except Exception as exc:  # pragma: no cover - network guard
            return self._failed(f"parcel GET error: {type(exc).__name__}: {exc}")
        if resp.status_code != 200:
            return self._failed(
                f"parcel display returned HTTP {resp.status_code} for folio={folio!r}"
            )

        model = self._parse_nal_model(resp.text)
        if not model:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"LeePA returned no NAL model for folio={folio!r}",
                folio=folio,
                fetched_at=datetime.now().isoformat(),
            )
        return self._build_result(folio, model, resp.text)

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Owner search is supported by the portal but returns many parcels for
        # common surnames; the canonical path is by address. Diagnostics-only.
        return []

    # ----------------------------------------------------------- resolve

    def _resolve_strap_to_folio(self, strap: str) -> str:
        try:
            page = self.session.get(self._search_url, timeout=40)
            tokens = self._get_tokens(page.text)
            data = {
                **tokens,
                "__EVENTTARGET": f"{_TMPL}SubmitPropertySearch",
                "__EVENTARGUMENT": "",
                f"{_TMPL}STRAPTextBox": strap,
                f"{_TMPL}AddressTextBox": "",
                f"{_TMPL}OwnerNameTextBox": "",
                f"{_TMPL}LegalTextBox": "",
                f"{_TMPL}ZIPCodeTextBox": "",
                f"{_TMPL}CountryDropDownList": "UNITED STATES OF AMERICA",
                f"{_TMPL}SearchSouceGroup": "SiteRadioButton",
            }
            resp = self.session.post(self._search_url, data=data, timeout=60)
            rows = self._parse_search_results(resp.text)
            return rows[0]["folio"] if rows else ""
        except Exception:  # pragma: no cover - network guard
            return ""

    # ----------------------------------------------------------- parse

    @staticmethod
    def _parse_search_results(html: str) -> List[Dict[str, Any]]:
        """Extract result rows from the PropertySearch grid.

        Each row exposes a STRAP + FolioID in adjacent ``<div class="item">``
        cells, then a bold owner block, then situs lines.
        """
        rows: List[Dict[str, Any]] = []
        # Split on the STRAP/folio cell which opens each row.
        for m in re.finditer(
            r'<div class="item">\s*(' + _STRAP_RE.pattern + r')\s*</div>\s*'
            r'<div class="item">\s*(\d{5,9})\s*</div>',
            html,
        ):
            strap, folio = m.group(1), m.group(2)
            tail = html[m.end(): m.end() + 1200]
            owners = re.findall(r'<div class="bold">([^<]+?)\s*</div>', tail)
            owners = [o.strip().rstrip("&").strip() for o in owners if o.strip()]
            # First plain <div> lines after the owner block are situs.
            situs_lines = re.findall(r'<div>([^<]+?)</div>', tail)
            situs = " ".join(s.strip() for s in situs_lines[:2] if s.strip())
            rows.append(
                {"strap": strap, "folio": folio, "owners": owners, "situs": situs}
            )
        # De-dup by folio (LeePA repeats the FolioID across map/links).
        seen = set()
        unique = []
        for r in rows:
            if r["folio"] in seen:
                continue
            seen.add(r["folio"])
            unique.append(r)
        return unique

    @staticmethod
    def _parse_nal_model(html: str) -> Dict[str, str]:
        """Parse the inline FL DOR NAL field dump (F01: .. F92:) into a map."""
        m = re.search(r"F01:.*?F9\d:[^<]*", html, re.S)
        if not m:
            return {}
        seg = m.group(0)
        pairs = re.findall(r"F(\d+):\s*([^<]*?)(?:<br\s*/?>|$)", seg)
        return {f"F{int(k):02d}": v.strip() for k, v in pairs}

    def _build_result(
        self, folio: str, model: Dict[str, str], html: str
    ) -> PropertyAppraiserResult:
        owner = model.get("F51", "").rstrip("&").strip()
        mailing = ", ".join(
            s for s in [
                model.get("F52", "").strip(),
                " ".join(
                    p for p in [
                        model.get("F54", "").strip(),
                        model.get("F55", "").strip(),
                        model.get("F56", "").strip(),
                    ] if p
                ),
            ] if s
        )
        situs = ", ".join(
            s for s in [
                model.get("F79", "").strip(),
                " ".join(
                    p for p in [
                        model.get("F81", "").strip(),
                        model.get("F82", "").strip(),
                    ] if p
                ),
            ] if s
        )
        homestead_amt = self._homestead_amount(model.get("F90", ""))
        result = PropertyAppraiserResult(
            apn=self._strap_from_model(model.get("F02", "")) or folio,
            folio=folio,
            owner_of_record=owner,
            situs_address=situs,
            mailing_address=mailing,
            legal_description=model.get("F65", "").strip(),
            just_value=_safe_int(model.get("F08")),
            assessed_value=_safe_int(model.get("F11")),
            homestead_active=homestead_amt > 0,
            homestead_amount=homestead_amt,
            year_built=_safe_int(model.get("F44")),
            living_area_sqft=_safe_int(model.get("F47")),
            source_url=f"{self._parcel_url}?FolioID={folio}",
            status="PA_SUCCESS",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(html)
        if not result.sale_history and "not viewable by the general public" in html:
            result.notes = (
                "LeePA flags this parcel's recorded instruments as "
                "'not viewable by the general public'; no public sale rows. "
                "Deed back-chain must come from the Lee Clerk recorder."
            )
        return result

    @staticmethod
    def _strap_from_model(f02: str) -> str:
        """Re-hyphenate the F02 unformatted STRAP into the display STRAP.

        "294424C2001010150" -> "29-44-24-C2-00101.0150".
        Falls back to the raw value if the length doesn't match.
        """
        s = (f02 or "").strip().upper()
        if len(s) == 17:
            return f"{s[0:2]}-{s[2:4]}-{s[4:6]}-{s[6:8]}-{s[8:13]}.{s[13:17]}"
        return s

    @staticmethod
    def _homestead_amount(f90: str) -> int:
        """F90 is ";"-delimited code/amount pairs, e.g. "01;25000;02;25722".

        Code 01 == Homestead. Return its dollar amount, else 0.
        """
        parts = [p.strip() for p in (f90 or "").split(";")]
        for i in range(0, len(parts) - 1, 2):
            if parts[i] == "01":
                return _safe_int(parts[i + 1])
        return 0

    @staticmethod
    def _parse_sales(html: str) -> List[SaleHistoryEntry]:
        """Best-effort parse of the Sales/Transactions grid.

        LeePA renders public sale rows as table rows with a leading
        MM/DD/YYYY sale date. Restricted parcels show none — returns [].
        """
        sales: List[SaleHistoryEntry] = []
        i = html.find('id="SalesDetails"')
        if i < 0:
            return sales
        seg = html[i: i + 9000]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
            cells = [
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            ]
            cells = [c for c in cells if c]
            if not cells:
                continue
            if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[0]):
                continue
            amount = next(
                (_safe_int(c) for c in cells[1:] if re.search(r"[\d,]{3,}", c)), 0
            )
            instr = next(
                (c for c in cells if re.fullmatch(r"\d{8,13}", c.replace(",", ""))), ""
            )
            sales.append(
                SaleHistoryEntry(
                    sale_date=cells[0],
                    sale_price=amount,
                    deed_doc_number=instr,
                    grantee=cells[-1] if len(cells) > 2 else "",
                )
            )
        return sales

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _failed(note: str) -> PropertyAppraiserResult:
        return PropertyAppraiserResult(
            status="PA_FAILED", notes=note, fetched_at=datetime.now().isoformat()
        )


def _safe_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s)) or "0")
    except Exception:
        return 0
