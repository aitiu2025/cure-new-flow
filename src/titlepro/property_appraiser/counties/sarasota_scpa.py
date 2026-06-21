"""Sarasota County Property Appraiser HTTP adapter (Phase 1a anchor — Wave-1).

Implementation derived from the 2026-06-10 probe (see
``src/titlepro/api/downloaded_doc/0610/Sarasota_BRUNO_v1/phase0_probe_pa.md``):
the SC-PA search app at ``www.sc-pa.com/propertysearch/`` is a custom in-house
ASP.NET MVC application. Bare Microsoft-IIS/10.0 — no Cloudflare, no CAPTCHA,
no anti-forgery token on the search form.

Endpoints (search-form shape live-captured; result/detail HTML shapes are
fixture-driven pending the first operator-approved live query — Wave 2):

  POST https://www.sc-pa.com/propertysearch/Result
    Body: AddressKeywords=<street>            (address search)
          | OwnerKeywords=<owner>             (owner search)
          | Strap=<digits, maxlength 12>      (parcel/account search)
          plus optional Subdivision / MunicipalityName(0100..0500) / UseCode /
          SalesFrom / SalesTo / SaleAmountFrom / SaleAmountTo /
          InstrumentNumber / GrantorSeller / HasPool=false

The Result response is either a result LIST (rows linking to parcel-detail
pages whose href carries the strap) or — for a unique hit — the detail page
itself. The parser handles both. Detail parsing is label-driven (tolerant of
layout/order changes); the sales table feeds ``SaleHistoryEntry`` rows that
carry OR instrument / book-page cites for the BRUNO trust-chain back-chain.

Tony Roveda Phase-1a directives: PA APN is the AUTHORITATIVE subject anchor;
sale_history is newest-first; HTTP-only (no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as _cffi_requests

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry


_DEFAULT_IMPERSONATE = "chrome120"

# Hrefs that point at a parcel-detail page. The strap is the trailing token.
# Configurable via config["detail_href_pattern"].
_DEFAULT_DETAIL_HREF_RE = (
    r"(?:parcel/details|ParcelDetail|parcel\?|Parcel/Index)[^\"']*?([0-9]{7,12})"
)

# Instrument-number cite inside a sales row ("2013012345" / "2013 012345").
_INSTRUMENT_RE = re.compile(r"\b(\d{10,12})\b")
# "OR BK 2547 PG 1234" / "2547/1234" book-page cite.
_BOOK_PAGE_RE = re.compile(
    r"(?:OR\s*)?(?:BK|BOOK)?\s*(\d{3,5})\s*[/\-]\s*(?:PG|PAGE)?\s*(\d{1,5})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b")
_MONEY_RE = re.compile(r"\$?[\d,]+\.?\d*")


class SarasotaSCPA(AbstractPropertyAppraiser):
    """ASP.NET MVC HTML adapter for the Sarasota County Property Appraiser."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_sarasota"
        self.county_name = "Sarasota"
        self.source_label = config.get(
            "description", "Sarasota County Property Appraiser"
        )
        self._base_url = config.get("base_url", "https://www.sc-pa.com/propertysearch/")
        endpoints = config.get("endpoints", {})
        self._url_search = endpoints.get(
            "search_result", "https://www.sc-pa.com/propertysearch/Result"
        )
        self._warmup_url = config.get(
            "warmup_url", "https://www.sc-pa.com/propertysearch/"
        )
        self._detail_href_re = re.compile(
            config.get("detail_href_pattern", _DEFAULT_DETAIL_HREF_RE),
            re.IGNORECASE,
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
            pass  # best-effort — SC-PA serves the search without warm cookies
        self._warmed = True

    def _post_search(self, fields: Dict[str, str]):
        self._warm()
        payload = {
            "AddressKeywords": "",
            "OwnerKeywords": "",
            "Strap": "",
            "Subdivision": "",
            "UseCode": "",
            "SalesFrom": "",
            "SalesTo": "",
            "SaleAmountFrom": "",
            "SaleAmountTo": "",
            "InstrumentNumber": "",
            "GrantorSeller": "",
            "HasPool": "false",
        }
        payload.update(fields)
        resp = self.session.post(
            self._url_search,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": self._warmup_url,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SC-PA {self._url_search} returned HTTP {resp.status_code}"
            )
        return resp

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _normalize_address_for_lookup(address: str) -> str:
        """'1016 Scherer Way, Osprey, FL 34229' → '1016 SCHERER WAY'."""
        addr = (address or "").upper().split(",", 1)[0].strip()
        addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
        return re.sub(r"\s+", " ", addr).strip()

    @staticmethod
    def _normalize_apn(apn: str) -> str:
        """Sarasota strap/account is digits-only (form maxlength 12);
        '0142-15-0010' → '0142150010'."""
        return re.sub(r"[^0-9]", "", apn or "")

    # ----------------------------------------------------------- API

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        norm = self._normalize_address_for_lookup(address)
        if not norm:
            return self._failed(f"empty address after normalize: {address!r}")
        try:
            resp = self._post_search({"AddressKeywords": norm})
        except Exception as exc:
            return self._failed(f"address search error: {type(exc).__name__}: {exc}")
        return self._resolve_search_response(resp, query_desc=f"address {norm!r}")

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        strap = self._normalize_apn(apn)
        if not strap:
            return self._failed(f"empty/invalid APN after normalize: {apn!r}")
        try:
            resp = self._post_search({"Strap": strap})
        except Exception as exc:
            return self._failed(f"strap search error: {type(exc).__name__}: {exc}")
        return self._resolve_search_response(resp, query_desc=f"strap {strap!r}")

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        if not (owner_name or "").strip():
            return []
        try:
            resp = self._post_search({"OwnerKeywords": owner_name.strip().upper()})
        except Exception:
            return []
        html = resp.text or ""
        out: List[PropertyAppraiserResult] = []
        for strap, href in self._extract_detail_links(html)[:10]:
            r = self._fetch_detail(href)
            if r is not None:
                out.append(r)
        # Single-hit portals may return the detail page directly.
        if not out and self._looks_like_detail(html):
            parsed = self._parse_detail(html, str(getattr(resp, "url", "") or ""))
            if parsed.status == "PA_SUCCESS":
                out.append(parsed)
        return out

    # ----------------------------------------------------------- resolve

    def _resolve_search_response(self, resp, query_desc: str) -> PropertyAppraiserResult:
        html = resp.text or ""
        # Unique-match portals render the detail page straight from /Result.
        if self._looks_like_detail(html):
            return self._parse_detail(html, str(getattr(resp, "url", "") or ""))

        links = self._extract_detail_links(html)
        if not links:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"SC-PA found no parcel matching {query_desc}",
                fetched_at=datetime.now().isoformat(),
            )
        if len(links) > 1:
            straps = sorted({s for s, _ in links})
            if len(straps) > 1:
                return PropertyAppraiserResult(
                    status="PA_AMBIGUOUS",
                    notes=(
                        f"SC-PA returned {len(straps)} candidates for {query_desc}: "
                        + ", ".join(straps[:8])
                    ),
                    fetched_at=datetime.now().isoformat(),
                )
        result = self._fetch_detail(links[0][1])
        if result is None:
            return self._failed(f"detail fetch failed for {query_desc}")
        return result

    def _extract_detail_links(self, html: str) -> List[tuple]:
        """Return [(strap, absolute_href), ...] for parcel-detail anchors."""
        out: List[tuple] = []
        seen = set()
        soup = BeautifulSoup(html or "", "lxml")
        for a in soup.find_all("a", href=True):
            m = self._detail_href_re.search(a["href"])
            if m:
                strap = m.group(1)
                href = urljoin(self._base_url, a["href"])
                if (strap, href) not in seen:
                    seen.add((strap, href))
                    out.append((strap, href))
        return out

    def _fetch_detail(self, href: str) -> Optional[PropertyAppraiserResult]:
        try:
            resp = self.session.get(href, timeout=30)
            if resp.status_code != 200:
                return None
            return self._parse_detail(resp.text, href)
        except Exception:
            return None

    # ----------------------------------------------------------- parse

    @staticmethod
    def _looks_like_detail(html: str) -> bool:
        h = (html or "").lower()
        return ("ownership" in h or "owner:" in h) and (
            "situs" in h
            or "legal description" in h
            or "parcel description" in h
            or "land description" in h
        )

    def _parse_detail(self, html: str, source_url: str) -> PropertyAppraiserResult:
        """Detail-page parse — LIVE-VALIDATED 2026-06-10 against parcel
        0150010019 (BRUNO/SHOLA, 1016 Scherer Way). Live page shape:

          Property Record Information for <strap>
          Ownership: <one line per owner>
          <mailing line>                  (e.g. "PO BOX 915, OSPREY, FL, …")
          Situs Address: \n <situs line>
          Parcel Description: <legal>
          Values table (Year|Land|Building|Extra Feature|Just|Assessed|…)
          Homestead Property: Yes/No
          Sales & Transfers table
        """
        soup = BeautifulSoup(html or "", "lxml")
        # The live page uses &nbsp; inside labels ("Parcel\xa0Description:") —
        # normalize to plain spaces before label matching.
        text = soup.get_text("\n", strip=True).replace("\xa0", " ")
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        def labeled(*labels: str) -> str:
            for label in labels:
                m = re.search(
                    rf"{re.escape(label)}\s*:?\s*\n?\s*([^\n]+)", text, re.IGNORECASE
                )
                if m:
                    val = m.group(1).strip()
                    if val and val.rstrip(":") != "":
                        return val
            return ""

        # APN: page title "Property Record Information for 0150010019",
        # falling back to the /parcel/details/<strap> URL, then labels.
        strap = ""
        m = re.search(r"Property Record Information for\s+(\d{7,12})", text, re.I)
        if m:
            strap = m.group(1)
        if not strap and source_url:
            mu = re.search(r"parcel/details/(\d{7,12})", source_url)
            if mu:
                strap = mu.group(1)
        if not strap:
            strap = self._normalize_apn(
                labeled("Parcel ID", "Account Number", "Account #", "Strap")
            )

        # Ownership block: one owner per line until the mailing-address line
        # (first subsequent line containing a digit, e.g. "PO BOX 915, …").
        owners: List[str] = []
        mailing = ""
        for i, ln in enumerate(lines):
            if re.match(r"^Ownership\s*:", ln, re.I) or ln.lower() == "ownership:":
                tail = ln.split(":", 1)[1].strip() if ":" in ln else ""
                if tail:
                    owners.append(tail)
                for nxt in lines[i + 1 :]:
                    low = nxt.lower()
                    if low.startswith(("change mailing", "situs")):
                        break
                    if re.search(r"\d", nxt):
                        mailing = nxt
                        break
                    owners.append(nxt)
                break
        if not owners:
            owner_raw = labeled("Ownership", "Owner of Record", "Owner")
            owners = [o.strip() for o in re.split(r";|\n", owner_raw) if o.strip()]

        situs = labeled("Situs Address", "Situs", "Property Address")
        legal = labeled(
            "Parcel Description", "Legal Description", "Land Description",
            "Short Description",
        )

        just_value, assessed_value = self._parse_values_table(soup)
        homestead = bool(
            re.search(r"Homestead\s+Property\s*:?\s*\n?\s*Yes", text, re.I)
        )

        result = PropertyAppraiserResult(
            apn=strap,
            folio=strap,
            owner_of_record=owners[0] if owners else "",
            co_owners=owners[1:],
            situs_address=situs,
            mailing_address=mailing or labeled("Mailing Address"),
            legal_description=legal,
            just_value=just_value,
            assessed_value=assessed_value,
            homestead_active=homestead,
            source_url=source_url
            or f"https://www.sc-pa.com/propertysearch/parcel/details/{strap}",
            status="PA_SUCCESS" if (strap or owners) else "PA_FAILED",
            notes="" if (strap or owners) else "detail page had no Parcel ID/Ownership labels",
            fetched_at=datetime.now().isoformat(),
        )
        result.sale_history = self._parse_sales(soup)
        return result

    @staticmethod
    def _parse_values_table(soup: BeautifulSoup) -> tuple:
        """Values table (live): Year|Land|Building|Extra Feature|Just|
        Assessed|Exemptions|Taxable|Cap — first data row = latest year.
        Returns (just_value, assessed_value)."""
        for t in soup.find_all("table"):
            headers = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
            if "just" in headers and "assessed" in headers:
                i_just = headers.index("just")
                i_assessed = headers.index("assessed")
                for tr in t.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) > max(i_just, i_assessed):
                        texts = [td.get_text(" ", strip=True) for td in tds]
                        jv = _safe_money(texts[i_just])
                        av = _safe_money(texts[i_assessed])
                        if jv or av:
                            return jv, av
        return 0, 0

    def _parse_sales(self, soup: BeautifulSoup) -> List[SaleHistoryEntry]:
        """Find the sales/transfers table and map rows newest-first."""
        sales: List[SaleHistoryEntry] = []
        table = None
        for t in soup.find_all("table"):
            caption = " ".join(
                filter(None, [t.get("id", ""), " ".join(t.get("class") or [])])
            ).lower()
            header_txt = " ".join(
                th.get_text(" ", strip=True).lower() for th in t.find_all("th")
            )
            if any(k in caption or k in header_txt for k in ("sale", "transfer")):
                table = t
                break
        if table is None:
            return sales

        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]

        def col(*keys: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if any(k in h for k in keys):
                    return i
            return None

        # Live headers (2026-06-10): Transfer Date | Recorded Consideration |
        # Instrument Number | Qualification Code | Grantor/Seller | Instrument Type
        c_date = col("date")
        c_price = col("consideration", "price", "amount")
        c_type = col("instrument type", "deed type")
        c_grantor = col("grantor", "seller")
        c_grantee = col("grantee", "buyer")
        c_qual = col("qual")

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            texts = [td.get_text(" ", strip=True) for td in tds]
            row_blob = " ".join(texts)
            date = texts[c_date] if c_date is not None and c_date < len(texts) else ""
            if not date:
                m = _DATE_RE.search(row_blob)
                date = m.group(1) if m else ""
            if not date:
                continue

            instrument, book_page = "", ""
            # Prefer an instrument-number anchor (SC-PA links sales to OR docs).
            a = tr.find("a", href=True)
            blob_for_cites = (a.get_text(" ", strip=True) + " " + row_blob) if a else row_blob
            mi = _INSTRUMENT_RE.search(blob_for_cites)
            if mi:
                instrument = mi.group(1)
            else:
                mb = _BOOK_PAGE_RE.search(blob_for_cites)
                if mb:
                    book_page = f"{mb.group(1)}/{mb.group(2)}"

            sales.append(
                SaleHistoryEntry(
                    sale_date=date,
                    sale_price=_safe_money(
                        texts[c_price] if c_price is not None and c_price < len(texts) else ""
                    ),
                    deed_doc_number=instrument,
                    deed_book_page=book_page,
                    deed_type=texts[c_type] if c_type is not None and c_type < len(texts) else "",
                    grantor=texts[c_grantor] if c_grantor is not None and c_grantor < len(texts) else "",
                    grantee=texts[c_grantee] if c_grantee is not None and c_grantee < len(texts) else "",
                    # Sarasota qualification codes: 01/02 = qualified
                    # arm's-length; 11 = related/trust; X* = multi-parcel etc.
                    qualified=(
                        texts[c_qual].strip().lstrip("0") in ("1", "2")
                        or texts[c_qual].strip() in ("01", "02", "Q")
                        if c_qual is not None and c_qual < len(texts) and texts[c_qual]
                        else False
                    ),
                    notes=(
                        f"qual_code={texts[c_qual].strip()}"
                        if c_qual is not None and c_qual < len(texts) and texts[c_qual]
                        else ""
                    ),
                )
            )

        # Newest-first per result contract.
        def _key(s: SaleHistoryEntry):
            try:
                mm, dd, yy = s.sale_date.split("/")
                yy = int(yy)
                if yy < 100:
                    yy += 1900 if yy > 30 else 2000
                return (yy, int(mm), int(dd))
            except Exception:
                return (0, 0, 0)

        sales.sort(key=_key, reverse=True)
        return sales

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _failed(notes: str) -> PropertyAppraiserResult:
        return PropertyAppraiserResult(
            status="PA_FAILED", notes=notes, fetched_at=datetime.now().isoformat()
        )


def _safe_money(s: Any) -> int:
    if s is None:
        return 0
    m = _MONEY_RE.search(str(s))
    if not m:
        return 0
    try:
        return int(float(m.group(0).replace("$", "").replace(",", "")))
    except Exception:
        return 0
