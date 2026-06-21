"""Pasco County Property Appraiser HTTP adapter (Phase 1a anchor — Wave-1 scaffold).

Derived from the 2026-06-10 probe (see
``src/titlepro/api/downloaded_doc/0610/Pasco_RILEY_v1/phase0_probe_pa.md``):
``search.pascopa.com`` is an in-house ASP.NET WebForms app on bare
Microsoft-IIS/10.0 — no anti-bot, no captcha — and every search form is a
**plain GET with querystring** (no viewstate round-trip):

  Address:    GET /default.aspx?pid=add&key=GLI&add1={num}&add2={street}&add=Submit
  Owner name: GET /default.aspx?pid=nam&key=GLI&nam={name}&nams=Submit   (max 20)
  OR Book/Pg: GET /default.aspx?pid=orb&key=GLI&orb={book}&orp={page}&orsearch=Submit
  Parcel:     GET /parcel.aspx?sec=..&twn=..&rng=..&sbb=....&blk=.....&lot=....

The Pasco parcel key is six segments — Section(2) Township(2) Range(2)
Subdivision(4) Block(5) Lot(4) — canonical display ``SS-TT-RR-SSSS-BBBBB-LLLL``.

IMPORTANT WAVE-1 CAVEAT: the request shapes above are verified verbatim from
the served form HTML, but the RESULT/parcel-page HTML was not live-captured
(queries carrying subject data require user approval per the No Assumptions
Policy). ``_parse_parcel_page`` is therefore a label-keyed defensive parser
locked by the synthetic fixture in
``tests/unit/test_property_appraiser_pasco_pa.py`` — diff it against the first
approved live response in Wave 2.

Class structure mirrors ``broward_bcpa.py`` (lazy session for mock injection,
fail-soft status codes, sale-history newest-first).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "safari17_2_ios"

_PARCEL_ID_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{2})-(\d{4})-(\d{5})-(\d{4})\b")

# Street-suffix tokens dropped from add2 (maxlength 20; portal indexes by
# street NAME — e.g. "CHRISTIAN" for "36700 Christian Road").
_STREET_SUFFIXES = {
    "RD", "ROAD", "ST", "STREET", "AVE", "AVENUE", "DR", "DRIVE", "LN", "LANE",
    "CT", "COURT", "BLVD", "BOULEVARD", "HWY", "HIGHWAY", "TER", "TERRACE",
    "PL", "PLACE", "CIR", "CIRCLE", "WAY", "TRL", "TRAIL", "PKWY", "PARKWAY",
    "LOOP",
}

_MONEY_RE = re.compile(r"\$?-?[\d,]+(?:\.\d+)?")
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")


class PascoPA(AbstractPropertyAppraiser):
    """GET/HTML adapter for the Pasco County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_pasco"
        self.county_name = "Pasco"
        self.source_label = config.get(
            "description", "Pasco County Property Appraiser"
        )
        endpoints = config.get("endpoints", {})
        self._base = config.get("base_url", "https://search.pascopa.com/").rstrip("/")
        self._warmup_url = config.get("warmup_url", self._base + "/")
        self._url_default = endpoints.get(
            "search", f"{self._base}/default.aspx"
        )
        self._url_parcel = endpoints.get(
            "parcel", f"{self._base}/parcel.aspx"
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)

        # Lazy session so unit tests can inject `adapter.session = MagicMock()`.
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
            pass  # best-effort — Pasco issues no gate cookies
        self._warmed = True

    def _get(self, url: str, params: Dict[str, str]) -> str:
        self._warm()
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"pascopa {url} returned HTTP {resp.status_code}: "
                f"{getattr(resp, 'text', '')[:200]}"
            )
        return resp.text

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _split_address(address: str) -> tuple[str, str]:
        """``"36700 Christian Road, Dade City, FL 33523"`` → ``("36700", "CHRISTIAN")``.

        Pasco's form takes street NUMBER (add1, max 7) and street NAME
        (add2, max 20). City/state/zip and a trailing known suffix are dropped.
        """
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"\s+", " ", addr)
        m = re.match(r"^(\d+)\s+(.*)$", addr)
        if not m:
            return "", addr[:20]
        number, rest = m.group(1), m.group(2)
        tokens = rest.split(" ")
        if len(tokens) > 1 and tokens[-1] in _STREET_SUFFIXES:
            tokens = tokens[:-1]
        return number[:7], " ".join(tokens)[:20]

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """Any punctuation/spacing → canonical ``SS-TT-RR-SSSS-BBBBB-LLLL``.

        Returns "" when the input doesn't carry the 19 significant chars.
        """
        digits = re.sub(r"[^0-9A-Za-z]", "", apn or "").upper()
        if len(digits) != 19:
            return ""
        return (
            f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]}-"
            f"{digits[6:10]}-{digits[10:15]}-{digits[15:19]}"
        )

    @staticmethod
    def _apn_to_parcel_param(canonical: str) -> str:
        """Canonical display ``SS-TT-RR-SSSS-BBBBB-LLLL`` → the parcel.aspx
        ``parcel=`` querystring value.

        Live-verified 2026-06-10: the portal reorders the key to
        RNG + TWN + SEC + SUB + BLK + LOT (a single 19-digit param). E.g.
        display ``04-24-21-0000-00200-0050`` → ``2124040000002000050``.
        """
        p = canonical.split("-")
        if len(p) != 6:
            return ""
        sec, twn, rng, sbb, blk, lot = p
        return f"{rng}{twn}{sec}{sbb}{blk}{lot}"

    @staticmethod
    def _parcel_param_to_apn(param: str) -> str:
        """Inverse of :meth:`_apn_to_parcel_param` (RNG/TWN/SEC → display)."""
        d = re.sub(r"\D", "", param or "")
        if len(d) != 19:
            return ""
        rng, twn, sec, sbb, blk, lot = (
            d[0:2], d[2:4], d[4:6], d[6:10], d[10:15], d[15:19],
        )
        return f"{sec}-{twn}-{rng}-{sbb}-{blk}-{lot}"

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        add1, add2 = self._split_address(address)
        if not add1 or not add2:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"could not split address into number+street: {address!r}",
                fetched_at=datetime.now().isoformat(),
            )
        try:
            html = self._get(
                self._url_default,
                {"pid": "add", "key": "GLI", "add1": add1, "add2": add2,
                 "add": "Submit"},
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"address search error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        # The result page may BE a parcel page (single hit) or a hit list.
        if _PARCEL_ID_RE.search(html) and "parcel.aspx" not in html.lower():
            return self._parse_parcel_page(html)

        candidates = self._extract_parcel_links(html)
        if not candidates:
            # Single-hit servers sometimes render the parcel inline.
            if _PARCEL_ID_RE.search(html):
                return self._parse_parcel_page(html)
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"pascopa found no parcel for {add1} {add2!r}",
                fetched_at=datetime.now().isoformat(),
            )
        if len(candidates) > 1:
            return PropertyAppraiserResult(
                status="PA_AMBIGUOUS",
                notes=(
                    f"pascopa returned {len(candidates)} candidates for "
                    f"{add1} {add2!r}: " + "; ".join(candidates[:6])
                ),
                fetched_at=datetime.now().isoformat(),
            )
        return self.lookup_by_apn(candidates[0])

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        canonical = self._normalize_apn(apn)
        if not canonical:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=(
                    f"invalid Pasco parcel key {apn!r} — expected 19 chars as "
                    "SS-TT-RR-SSSS-BBBBB-LLLL"
                ),
                fetched_at=datetime.now().isoformat(),
            )
        parcel_param = self._apn_to_parcel_param(canonical)
        try:
            html = self._get(self._url_parcel, {"parcel": parcel_param})
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                apn=canonical,
                notes=f"parcel fetch error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        result = self._parse_parcel_page(html)
        if not result.apn:
            result.apn = canonical
        return result

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Diagnostics-only owner search (nam field max 20 chars).

        Returns lightweight results (APN only) for each parcel link found —
        callers should follow up with ``lookup_by_apn``.
        """
        name = re.sub(r"\s+", " ", (owner_name or "").upper().strip())[:20]
        if not name:
            return []
        try:
            html = self._get(
                self._url_default,
                {"pid": "nam", "key": "GLI", "nam": name, "nams": "Submit"},
            )
        except Exception:
            return []
        out: List[PropertyAppraiserResult] = []
        for apn in self._extract_parcel_links(html):
            out.append(
                PropertyAppraiserResult(
                    apn=apn,
                    status="PA_SUCCESS",
                    notes=f"owner-name hit for {name!r} (shallow — call lookup_by_apn)",
                    fetched_at=datetime.now().isoformat(),
                )
            )
        return out

    # ----------------------------------------------------------- parse

    def _extract_parcel_links(self, html: str) -> List[str]:
        """Collect canonical parcel ids from a hit-list / address-results page.

        Live shape (2026-06-10): hits link to ``parcel.aspx?parcel=<19digits>``
        (RNG/TWN/SEC order) and also print the display id ``04-24-21-...``
        nearby. We resolve both forms to the canonical display id.
        """
        soup = BeautifulSoup(html, "lxml")
        found: List[str] = []
        seen: set = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "parcel.aspx" not in href.lower():
                continue
            qs = parse_qs(urlparse(href).query)
            param = qs.get("parcel", [""])[0]
            canonical = self._parcel_param_to_apn(param)
            # Some links may carry separate segments — support that too.
            if not canonical:
                segs = [qs.get(k, [""])[0] for k in ("sec", "twn", "rng", "sbb", "blk", "lot")]
                if all(segs):
                    canonical = "-".join(segs)
            if canonical and canonical not in seen:
                seen.add(canonical)
                found.append(canonical)
        # Fallback: literal display tokens in page text.
        if not found:
            for m in _PARCEL_ID_RE.finditer(soup.get_text(" ")):
                canonical = m.group(0)
                if canonical not in seen:
                    seen.add(canonical)
                    found.append(canonical)
        return found

    def _parse_parcel_page(self, html: str) -> PropertyAppraiserResult:
        """Parse a live Pasco PA parcel page (search.pascopa.com/parcel.aspx).

        Live structure (2026-06-10): deeply-nested div/table layout. We
        flatten to whitespace-normalized text and key off the printed labels
        ``Parcel ID``, ``Owner:``, ``Physical Address``, ``Mailing Address``,
        ``Legal Description``, ``Just Value``, ``Assessed``, ``Homestead
        Exemption``, plus the ``Sales History`` block.
        """
        flat = self._flatten(html)

        apn = ""
        m = _PARCEL_ID_RE.search(flat)
        if m:
            apn = m.group(0)

        def after(label: str, pattern: str, default: str = "") -> str:
            mm = re.search(re.escape(label) + r"\s*" + pattern, flat, re.I)
            return mm.group(1).strip() if mm else default

        owner = after("Owner:", r"([A-Z0-9][^|]*?)\s*(?:Previous Owner|Sales History|Mailing|$)")
        # Physical (situs) address.
        situs = after(
            "Physical Address",
            r"([0-9][^|]*?(?:FL)\s*\d{5}(?:-\d{4})?)",
        )
        situs = re.sub(r"\s{2,}", " ", situs).strip(", ")
        # Mailing address block (owner mailing — multi-line).
        mailing = after(
            "Mailing Address",
            r"(.+?)\s*Physical Address",
        )
        mailing = re.sub(r"\s{2,}", " ", mailing).strip()
        # Legal description.
        legal = after(
            "Legal Description",
            r"(?:\(First \d+ characters\))?\s*([A-Z0-9][^|]*?)(?:Land Lines|Sales History|Building|Taxing|Section/Township|$)",
        )
        legal = re.sub(r"\s{2,}", " ", legal).strip()

        just_value = _money_to_int(after("Just Value", r"\$?\s*([\d,]+)"))
        assessed = _money_to_int(after("Assessed", r"\$?\s*([\d,]+)"))
        homestead_amt = _money_to_int(after("Homestead Exemption", r"-?\s*\$?\s*([\d,]+)"))

        result = PropertyAppraiserResult(
            apn=apn,
            folio=apn,
            owner_of_record=owner,
            situs_address=situs,
            mailing_address=mailing or situs,
            legal_description=legal,
            just_value=just_value,
            assessed_value=assessed,
            homestead_active=homestead_amt > 0,
            homestead_amount=homestead_amt,
            source_url=(
                f"{self._url_parcel}?parcel={self._apn_to_parcel_param(apn)}"
                if apn else self._url_parcel
            ),
            status="PA_SUCCESS" if (apn or owner) else "PA_NO_RESULTS",
            notes="" if (apn or owner) else "no parcel id or owner found on page",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(flat)
        return result

    @staticmethod
    def _flatten(html: str) -> str:
        flat = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
        flat = re.sub(r"<style.*?</style>", " ", flat, flags=re.S | re.I)
        flat = re.sub(r"<[^>]+>", " ", flat)
        flat = flat.replace("&nbsp;", " ").replace("&amp;", "&")
        return re.sub(r"\s+", " ", flat).strip()

    # Pasco PA deed-type display words → CURE short codes.
    _DEED_TYPE_CODE = {
        "QUIT CLAIM DEED": "QCD",
        "WARRANTY DEED": "WD",
        "SPECIAL WARRANTY DEED": "SWD",
        "CERTIFICATE OF TITLE": "CT",
        "TAX DEED": "TD",
        "PERSONAL REPRESENTATIVE DEED": "PRD",
        "TRUSTEE'S DEED": "TRD",
        "TRUSTEES DEED": "TRD",
        "CORRECTIVE DEED": "CD",
    }
    _DEED_TYPES_RE = (
        r"Quit Claim Deed|Special Warranty Deed|Warranty Deed|Certificate of Title|"
        r"Tax Deed|Personal Representative Deed|Trustee'?s Deed|Corrective Deed|Deed"
    )

    @classmethod
    def _parse_sales(cls, flat: str) -> List[SaleHistoryEntry]:
        """Parse the Sales History block (newest-first) from flattened text.

        Live row shape (2026-06-10):
          ``MM/YYYY ... Book <b> / and Page <p> <TypeWords> <DORcode?> ... $<amt>``
        """
        i = flat.find("Sales History")
        seg = flat[i:] if i >= 0 else flat
        # Stop at the JS block / next major section.
        for stop in ("When the user clicks", "Land Lines", "Building "):
            j = seg.find(stop)
            if j > 0:
                seg = seg[:j]
                break

        row_re = re.compile(
            r"(\d{1,2}/\d{4}).{0,60}?Book\s+(\d+)\s*/?\s*(?:and Page\s+)?(\d+)\s+"
            r"(" + cls._DEED_TYPES_RE + r")\s+(?:(\d{1,2})\s+)?"
            r"(?:- Opens PDF[^$]*?)?[A-Z]?\s*\$\s*([\d,]+)",
            re.I,
        )
        sales: List[SaleHistoryEntry] = []
        for mm, book, page, dtype, dor, amt in row_re.findall(seg):
            code = cls._DEED_TYPE_CODE.get(dtype.strip().upper(), dtype.strip())
            sales.append(
                SaleHistoryEntry(
                    sale_date=mm,  # MM/YYYY (PA granularity)
                    sale_price=_money_to_int(amt),
                    deed_book_page=f"{book} / {page}",
                    deed_type=code,
                    qualified=(dor or "").strip() in {"01", "02", "03"},
                    notes=f"DOR {dor}" if dor else "",
                )
            )

        def _key(s: SaleHistoryEntry):
            try:
                return datetime.strptime(s.sale_date, "%m/%Y")
            except Exception:
                return datetime.min

        sales.sort(key=_key, reverse=True)
        return sales


# ----------------------------------------------------------- helpers


def _money_to_int(s: Any) -> int:
    if s is None:
        return 0
    m = _MONEY_RE.search(str(s))
    if not m:
        return 0
    try:
        return int(float(m.group(0).replace("$", "").replace(",", "")))
    except Exception:
        return 0


__all__ = ["PascoPA"]
