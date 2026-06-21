"""Volusia County Property Appraiser (VCPA) HTTP adapter — Phase 1a anchor.

Implementation derived from the 2026-06-10 live probe (see the GUILD case dir
`src/titlepro/api/downloaded_doc/0610/Volusia_GUILD_v1/phase0_probe_pa.md`):

The VCPA portal at https://vcpa.vcgov.org/ is a server-rendered Bootstrap site
with two endpoints we use:

  1. ``POST /api/search/real-property`` — DataTables server-side search.
     Form body: ``draw=1&start=0&length=10&search[value]=<query>``.
     Accepts Name (LAST FIRST), street address, Alt Key, or Parcel ID.
     Returns JSON ``{"data": [{"altkey", "parcel", "owner", "street", "pc"}]}``
     — one row PER OWNER (a joint-tenancy parcel returns 2+ rows that share
     the same ``altkey``).

  2. ``GET /parcel/summary/?altkey=<altkey>`` — full parcel page (server-side
     rendered) gated only by a ``acceptedNewDisclaimer=true`` cookie. Carries
     owners + manner-of-holding, situs, short legal, value history, and the
     full Sales History table (Book/Page + Instrument No. + Deed Type +
     Qualified flag + price). Sale rows even hyperlink to the recorder's
     direct-retrieval endpoint
     (``https://app02.clerk.org/or_m/Default.aspx?s=orapr&i=<instrument>``).

NO anti-bot of any kind — plain HTTP with a desktop UA returns 200.

Like BCPA, this delivers the back-chain anchor: for GUILD it surfaces the
12/20/2016 WD 7343/1336 (current vesting) AND the 12/15/1996 WD 4160/2999
prior-owner acquisition that defines the two-owner search window.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"

_DISCLAIMER_COOKIE = ("acceptedNewDisclaimer", "true")

_FORM_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


class VolusiaVCPA(AbstractPropertyAppraiser):
    """HTTP adapter for the Volusia County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_volusia"
        self.county_name = "Volusia"
        self.source_label = config.get(
            "description", "Volusia County Property Appraiser"
        )
        base = (config.get("base_url") or "https://vcpa.vcgov.org/").rstrip("/")
        endpoints = config.get("endpoints", {})
        self._url_search = endpoints.get(
            "search_real_property", f"{base}/api/search/real-property"
        )
        self._url_summary_tmpl = endpoints.get(
            "parcel_summary", f"{base}/parcel/summary/?altkey={{altkey}}"
        )
        self._referer = config.get("referer", f"{base}/search/real-property")
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        # Lazily created so unit tests can inject `adapter.session = MagicMock()`.
        self._session: Optional[Any] = None

    # ----------------------------------------------------------- session

    @property
    def session(self):
        if self._session is None:
            s = _cffi_requests.Session(impersonate=self._impersonate)
            # The parcel-summary page renders only the disclaimer shell until
            # this cookie is present (probed live 2026-06-10).
            s.cookies.set(_DISCLAIMER_COOKIE[0], _DISCLAIMER_COOKIE[1])
            self._session = s
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """``"435 Elsie Avenue, Holly Hill, FL 32117"`` → ``"435 ELSIE AVE"``.

        The VCPA search is a prefix match against ``street`` (street + city,
        no commas), so we strip the city/state/zip tail and normalize common
        street-type suffixes the way the index stores them.
        """
        addr = (address or "").upper()
        addr = addr.split(",", 1)[0].strip()
        # Ordinal suffixes: "27TH" → "27"
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        # Street-type abbreviations used by the VCPA index.
        suffix_map = {
            "AVENUE": "AVE", "STREET": "ST", "DRIVE": "DR", "ROAD": "RD",
            "BOULEVARD": "BLVD", "LANE": "LN", "COURT": "CT", "CIRCLE": "CIR",
            "PLACE": "PL", "TERRACE": "TER", "TRAIL": "TRL", "HIGHWAY": "HWY",
            "PARKWAY": "PKWY",
        }
        words = addr.split()
        words = [suffix_map.get(w, w) for w in words]
        return re.sub(r"\s+", " ", " ".join(words)).strip()

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """Volusia Parcel ID is unhyphenated numeric (e.g. ``533705070110``);
        the 7-digit Alternate Key is also accepted by the search endpoint."""
        return re.sub(r"[^0-9]", "", apn or "")

    # ----------------------------------------------------------- HTTP

    def _search(self, query: str) -> List[Dict[str, str]]:
        """POST the DataTables search; returns the raw row dicts."""
        resp = self.session.post(
            self._url_search,
            data={
                "draw": "1",
                "start": "0",
                "length": "25",
                "search[value]": query,
                "search[regex]": "false",
            },
            headers={**_FORM_HEADERS, "Referer": self._referer},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"VCPA search returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        payload = resp.json()
        return list(payload.get("data") or [])

    def _fetch_summary(self, altkey: str) -> str:
        url = self._url_summary_tmpl.format(altkey=altkey)
        resp = self.session.get(
            url, headers={"Referer": self._referer}, timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"VCPA parcel summary returned HTTP {resp.status_code} for altkey={altkey}"
            )
        return resp.text

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        if not norm:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty address after normalize: {address!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            rows = self._search(norm)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        # One row per owner — collapse to distinct parcels by altkey.
        by_altkey: Dict[str, Dict[str, str]] = {}
        for r in rows:
            ak = (r.get("altkey") or "").strip()
            if ak and ak not in by_altkey:
                by_altkey[ak] = r
        if not by_altkey:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"VCPA found no parcel matching address {norm!r}",
                fetched_at=datetime.now().isoformat(),
            )
        if len(by_altkey) > 1:
            # Prefer rows whose street starts with our normalized form.
            exact = {
                ak: r
                for ak, r in by_altkey.items()
                if (r.get("street") or "").upper().startswith(norm)
            }
            if len(exact) == 1:
                by_altkey = exact
            else:
                return PropertyAppraiserResult(
                    status="PA_AMBIGUOUS",
                    notes=(
                        f"VCPA returned {len(by_altkey)} candidate parcels for {norm!r}: "
                        + "; ".join(
                            f"{r.get('street','?')} (altkey {ak}, parcel {r.get('parcel','?')})"
                            for ak, r in list(by_altkey.items())[:6]
                        )
                    ),
                    fetched_at=datetime.now().isoformat(),
                )
        altkey = next(iter(by_altkey))
        return self._lookup_by_altkey(altkey)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        norm = self._normalize_apn(apn)
        if not norm:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid APN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            rows = self._search(norm)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"APN search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        match = next(
            (
                r
                for r in rows
                if self._normalize_apn(r.get("parcel") or "") == norm
                or (r.get("altkey") or "").strip() == norm
            ),
            None,
        )
        if match is None:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"VCPA found no parcel matching APN/altkey {norm!r}",
                apn=norm,
                fetched_at=datetime.now().isoformat(),
            )
        return self._lookup_by_altkey((match.get("altkey") or "").strip())

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Best-effort owner search (LAST FIRST) — diagnostics only."""
        try:
            rows = self._search((owner_name or "").upper().strip())
        except Exception:
            return []
        out: List[PropertyAppraiserResult] = []
        seen: set = set()
        for r in rows:
            ak = (r.get("altkey") or "").strip()
            if not ak or ak in seen:
                continue
            seen.add(ak)
            out.append(
                PropertyAppraiserResult(
                    apn=(r.get("parcel") or "").strip(),
                    folio=ak,
                    owner_of_record=(r.get("owner") or "").strip(),
                    situs_address=(r.get("street") or "").strip(),
                    status="PA_SUCCESS",
                    notes="owner-name search preview row (summary not fetched)",
                    fetched_at=datetime.now().isoformat(),
                )
            )
        return out

    # ----------------------------------------------------------- internals

    def _lookup_by_altkey(self, altkey: str) -> PropertyAppraiserResult:
        try:
            html = self._fetch_summary(altkey)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                folio=altkey,
                notes=f"parcel summary error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        return self._parse_summary(html, altkey)

    # ----------------------------------------------------------- parse

    def _parse_summary(self, html: str, altkey: str) -> PropertyAppraiserResult:
        soup = BeautifulSoup(html, "html.parser")

        apn = _kv(soup, "Parcel ID:")
        alt = _kv(soup, "Alternate Key:") or altkey
        situs = _kv(soup, "Physical Address:")
        legal = _kv(soup, "Short Description:")
        homestead_raw = _kv(soup, "Homestead Property:")
        mailing = _kv(soup, "Mailing Address On File:")
        # Strip the "Update Mailing Address" trailing link text if present.
        mailing = re.sub(r"\s*Update Mailing Address\s*$", "", mailing).strip()

        owners = _parse_owners(soup)
        if not apn and not owners:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                folio=altkey,
                notes=(
                    "VCPA summary page did not contain parcel fields — the "
                    "acceptedNewDisclaimer cookie was likely not honored"
                ),
                fetched_at=datetime.now().isoformat(),
            )

        just_value, value_year = _parse_latest_just_value(soup)

        result = PropertyAppraiserResult(
            apn=apn,
            folio=alt,
            owner_of_record=owners[0] if owners else "",
            co_owners=owners[1:],
            situs_address=situs,
            mailing_address=mailing,
            legal_description=legal,
            just_value=just_value,
            homestead_active=homestead_raw.strip().upper().startswith("YES"),
            year_built=_parse_year_built(soup),
            source_url=self._url_summary_tmpl.format(altkey=alt),
            status="PA_SUCCESS",
            notes=f"just_value from VCPA value column {value_year!r}" if value_year else "",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = _parse_sales(soup)
        return result


# ----------------------------------------------------------- module helpers


def _kv(soup: BeautifulSoup, label: str) -> str:
    """VCPA layout: ``<div class=col-sm-5><strong>Label:</strong></div>``
    followed by a sibling ``<div class=col-sm-7>value</div>``."""
    node = soup.find(string=re.compile(re.escape(label)))
    if not node:
        return ""
    parent = node.find_parent("div")
    if not parent:
        return ""
    sib = parent.find_next_sibling("div")
    if not sib:
        return ""
    # First line only for labels that carry trailing modal/help text.
    text = sib.get_text("\n", strip=True)
    if label in ("Homestead Property:", "Agriculture Classification:"):
        return text.split("\n", 1)[0].strip()
    if label == "Short Description:":
        return " ".join(t.strip() for t in text.split("\n") if t.strip())
    if label == "Mailing Address On File:":
        return ", ".join(
            t.strip() for t in text.split("\n") if t.strip()
        )
    return text.split("\n", 1)[0].strip()


def _parse_owners(soup: BeautifulSoup) -> List[str]:
    """Owners render one per ``<br>`` as
    ``GUILD MARYKE Y - JT - Joint Tenancy with Right of Survivorship - 100%``.
    Returns the bare names, order preserved."""
    node = soup.find(string=re.compile(r"Owner\(s\):"))
    if not node:
        return []
    parent = node.find_parent("div")
    sib = parent.find_next_sibling("div") if parent else None
    if not sib:
        return []
    owners: List[str] = []
    for line in sib.get_text("\n", strip=True).split("\n"):
        line = line.strip()
        if not line:
            continue
        name = line.split(" - ", 1)[0].strip()
        if name and name not in owners:
            owners.append(name)
    return owners


def _parse_latest_just_value(soup: BeautifulSoup) -> tuple:
    """``div#section-values .nomobile`` renders one label column followed by
    one column per tax year (newest first): year / method / improvement /
    land / just-market, joined by ``<br>``. Returns ``(just_value, year_label)``
    for the newest column."""
    sec = soup.find("div", id="section-values")
    if not sec:
        return 0, ""
    nomobile = sec.find("div", class_="nomobile") or sec
    label_seen = False
    for col in nomobile.find_all("div", class_=re.compile(r"col-sm-\d")):
        lines = [t.strip() for t in col.get_text("\n", strip=True).split("\n") if t.strip()]
        if not lines:
            continue
        if lines[0].startswith("Tax Year"):
            label_seen = True
            continue
        if label_seen and len(lines) >= 5 and re.match(r"^\d{4}\b", lines[0]):
            return _money_to_int(lines[4]), lines[0]
    return 0, ""


def _parse_year_built(soup: BeautifulSoup) -> int:
    """Building table headers: Section / Yr Built / Area / RCN / ..."""
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "Yr Built" not in headers:
            continue
        idx = headers.index("Yr Built")
        for tr in tbl.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) > idx:
                m = re.search(r"\d{4}", tds[idx].get_text(strip=True))
                if m:
                    return int(m.group(0))
    return 0


def _parse_sales(soup: BeautifulSoup) -> List[SaleHistoryEntry]:
    """Sales History rows live in ``div#section-sales .nomobile`` as
    bootstrap rows of 7 columns: Book/Page | Instrument No. | Sale Date |
    Deed Type | Qualified/Unqualified | Vacant/Improved | Sale Price.
    Newest-first on the page; order preserved."""
    sec = soup.find("div", id="section-sales")
    if not sec:
        return []
    nomobile = sec.find("div", class_="nomobile") or sec
    sales: List[SaleHistoryEntry] = []
    for row in nomobile.find_all("div", class_="row"):
        cols = [
            c.get_text(" ", strip=True)
            for c in row.find_all("div", class_=re.compile(r"col-sm-\d"))
        ]
        if len(cols) < 7:
            continue
        if cols[0].startswith("Book/Page"):  # header row
            continue
        date = cols[2].strip()
        if not re.match(r"^\d{2}/\d{2}/\d{4}$", date):
            continue
        book_page = cols[0].strip()
        instrument = re.sub(r"[^\d]", "", cols[1]) if cols[1].strip() else ""
        sales.append(
            SaleHistoryEntry(
                sale_date=date,
                sale_price=_money_to_int(cols[6]),
                deed_doc_number=instrument,
                deed_book_page=book_page if "/" in book_page else "",
                deed_type=cols[3].strip(),
                qualified=cols[4].strip().upper() == "QUALIFIED",
                notes=cols[5].strip(),
            )
        )
    return sales


def _money_to_int(s: Any) -> int:
    if s is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(s).split(".")[0]) or "0")
    except Exception:
        return 0
