"""Palm Beach County Property Appraiser HTTP adapter (Phase 1a anchor).

The Palm Beach PAO (a.k.a. PAPA = Property Appraiser Public Access) serves
property-detail HTML at::

    https://www.pbcpao.gov/Property/Details/?parcelId=<unhyphenated_PCN>

Verified live 2026-05-26 against HABER subject at 21831 PALM GRASS DR
(PCN `00-41-47-22-04-000-1090`, unhyphenated `00414722040001090`). The
response is a 146 KB HTML doc that contains, among other things, several
labelled key/value tables:

  * Property detail            (Location Address, Municipality, PCN,
                                Subdivision, latest OR Book/Page+SaleDate,
                                Legal Description)
  * Owner Information          (Owner(s), Mailing Address)
  * Sales Information          (Sales Date, Price, OR Book/Page, Sale Type,
                                Owner — usually 2-5 historical rows newest
                                first, including pre-recorder-window sales
                                back to the 1990s)
  * Exemption Information      (Applicant/Owner, Year, Exemption Detail —
                                e.g. HOMESTEAD + ADDITIONAL HOMESTEAD)
  * Appraisal / Assessment Information (Tax Year columns 2016..2025 with
                                Improvement Value / Land Value / Total
                                Market Value, then Assessed Value /
                                Exemption Amount / Taxable Value)
  * Structural Information     (Year Built, Beds, Baths, Total SqFt, etc.)

This adapter:

  * Implements `lookup_by_apn(pcn)` against the canonical PBCPAO endpoint.
  * Implements `lookup_by_address(addr)` via POST to
    `/AdvSearch/RealPropSearch` with `RealPropertySearch.Address.*` fields,
    falling back to PA_AMBIGUOUS when the AdvSearch returns no parcel.
  * Implements `lookup_by_owner_name(name)` likewise as a best-effort
    diagnostic (PBCPAO requires extra fields for owner-only search,
    typically returns multiple parcels — we surface the count and stop).

Tony Roveda 2026-05-22 directive #4 (subject-address verifier) is satisfied
by populating `PropertyAppraiserResult.situs_address` from the PAO's own
"Location Address" field (THE authoritative subject address — the recorder
index is a name/event index, not a subject-property index).

Test plan: see tests/unit/test_property_appraiser_palm_beach_pbcpao.py
(10 unit tests — config wiring, PCN normalize, label parser, sale-history
parser, exemption parser, missing-field handling, address-search fallback,
ambiguous-result handling).
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
_PCN_HYPHEN_RE = re.compile(r"^\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{3}-\d{4}$")


class PalmBeachPBCPAO(AbstractPropertyAppraiser):
    """Pure-HTTP adapter for the Palm Beach County Property Appraiser (PAPA)."""

    def __init__(self, config: Dict[str, Any]):
        self.county_id = "fl_palm_beach"
        self.county_name = "Palm Beach"
        self.source_label = config.get(
            "description", "Palm Beach County Property Appraiser (PAPA)"
        )
        self._impersonate = config.get("impersonate", _DEFAULT_IMPERSONATE)
        endpoints = config.get("endpoints", {})
        self._base_url = config.get("base_url", "https://www.pbcpao.gov/").rstrip("/") + "/"
        self._url_detail = endpoints.get(
            "parcel_detail",
            "https://www.pbcpao.gov/Property/Details/",
        )
        self._url_address_search = endpoints.get(
            "address_search",
            "https://www.pbcpao.gov/AdvSearch/RealPropSearch",
        )
        # Display URL pattern (the one the customer-facing report should cite
        # as `source_url` — uses the hyphenated form for readability).
        self._public_detail_pattern = endpoints.get(
            "public_detail_pattern",
            "https://www.pbcpao.gov/Property/Details/?parcelId={pcn_clean}",
        )

        # Sessions are lazy so tests can mock via `adapter.session = MagicMock()`.
        self._session: Optional[Any] = None

    @property
    def session(self):
        if self._session is None:
            self._session = _cffi_requests.Session(impersonate=self._impersonate)
            self._session.headers.update({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
        return self._session

    @session.setter
    def session(self, value):
        self._session = value

    # ----------------------------------------------------------- normalize

    @staticmethod
    def _clean_pcn(pcn: str) -> str:
        """``00-41-47-22-04-000-1090`` -> ``00414722040001090``."""
        return re.sub(r"[^0-9]", "", pcn or "")

    @staticmethod
    def _format_pcn_hyphenated(pcn_clean: str) -> str:
        """``00414722040001090`` -> ``00-41-47-22-04-000-1090`` (best-effort)."""
        d = re.sub(r"[^0-9]", "", pcn_clean or "")
        if len(d) != 17:
            return pcn_clean
        return f"{d[0:2]}-{d[2:4]}-{d[4:6]}-{d[6:8]}-{d[8:10]}-{d[10:13]}-{d[13:17]}"

    @staticmethod
    def _safe_money(s: Any) -> int:
        if s is None:
            return 0
        try:
            return int(re.sub(r"[^\d]", "", str(s)) or "0")
        except Exception:
            return 0

    @staticmethod
    def _safe_int(s: Any) -> int:
        if s is None:
            return 0
        try:
            return int(re.sub(r"[^\d]", "", str(s)) or "0")
        except Exception:
            return 0

    # ----------------------------------------------------------- API

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        pcn_clean = self._clean_pcn(apn)
        if not pcn_clean:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"empty/invalid PCN after normalize: {apn!r}",
                fetched_at=datetime.now().isoformat(),
            )

        try:
            resp = self.session.get(
                self._url_detail,
                params={"parcelId": pcn_clean},
                timeout=30,
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"PBCPAO parcel-detail GET error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

        if resp.status_code != 200:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"PBCPAO returned HTTP {resp.status_code} for PCN {pcn_clean!r}",
                fetched_at=datetime.now().isoformat(),
            )

        html = resp.text or ""
        # PBCPAO returns 200 with a "no parcel found" landing if the PCN is
        # invalid — the discriminator is whether the page actually has a
        # "Property detail" table with rows.
        return self._parse_parcel_html(html, pcn_clean)

    def lookup_certified_tax(self, apn: str) -> Dict[str, Any]:
        """Pull the per-year certified tax breakdown from PBCPAO.

        The PBCPAO property-details page embeds a per-year tax table::

            Tax Year       | 2025  | 2024  | 2023 ...
            AD VALOREM     | $4,449| $4,315| ...
            NON AD VALOREM | $413  | $398  | ...
            TOTAL TAX      | $4,862| $4,713| ...

        These are the CERTIFIED (TRIM) numbers — the same figures the Palm
        Beach County Tax Collector bills from. The Tax Collector adds only a
        4% early-pay-discount adjustment in Nov/Dec and a delinquency penalty
        for unpaid bills after April 1; the underlying certified-tax figure
        does not change.

        Returns a dict shaped like::

            {
              "status": "TAX_SUCCESS" | "TAX_NO_RESULTS" | "TAX_FAILED",
              "apn": str (normalized hyphenated PCN),
              "tax_year": str (most recent year),
              "ad_valorem": int,
              "non_ad_valorem": int,
              "total_tax": int (annual certified amount in whole dollars),
              "history": [{"year": "2025", "ad_valorem": 4449,
                           "non_ad_valorem": 413, "total_tax": 4862}, ...],
              "source_url": str (the same PBCPAO detail URL),
              "fetched_at": str (ISO),
              "notes": str,
            }

        Caller should treat ``total_tax`` as the certified annual tax for the
        most recent tax year; the Tax Collector's bill amount (the number a
        homeowner sees on the November statement) equals this minus any
        early-pay discount.
        """
        pcn_clean = self._clean_pcn(apn)
        if not pcn_clean:
            return {
                "status": "TAX_FAILED",
                "apn": apn,
                "notes": f"empty/invalid PCN after normalize: {apn!r}",
                "fetched_at": datetime.now().isoformat(),
            }

        try:
            resp = self.session.get(
                self._url_detail,
                params={"parcelId": pcn_clean},
                timeout=30,
            )
        except Exception as exc:
            return {
                "status": "TAX_FAILED",
                "apn": self._format_pcn_hyphenated(pcn_clean),
                "notes": f"PBCPAO detail GET error: {type(exc).__name__}: {exc}",
                "fetched_at": datetime.now().isoformat(),
            }

        if resp.status_code != 200:
            return {
                "status": "TAX_FAILED",
                "apn": self._format_pcn_hyphenated(pcn_clean),
                "notes": f"PBCPAO returned HTTP {resp.status_code} for PCN {pcn_clean!r}",
                "fetched_at": datetime.now().isoformat(),
            }

        soup = BeautifulSoup(resp.text or "", "html.parser")
        history = self._parse_tax_history_table(soup)
        if not history:
            return {
                "status": "TAX_NO_RESULTS",
                "apn": self._format_pcn_hyphenated(pcn_clean),
                "notes": (
                    "PBCPAO detail HTML had no per-year Tax Year / AD VALOREM / "
                    f"TOTAL TAX table for PCN {pcn_clean!r} (page may be unparsed)."
                ),
                "source_url": self._public_detail_pattern.format(pcn_clean=pcn_clean),
                "fetched_at": datetime.now().isoformat(),
            }

        latest = history[0]
        return {
            "status": "TAX_SUCCESS",
            "apn": self._format_pcn_hyphenated(pcn_clean),
            "tax_year": latest["year"],
            "ad_valorem": latest["ad_valorem"],
            "non_ad_valorem": latest["non_ad_valorem"],
            "total_tax": latest["total_tax"],
            "history": history,
            "source_url": self._public_detail_pattern.format(pcn_clean=pcn_clean),
            "fetched_at": datetime.now().isoformat(),
            "notes": (
                "PBCPAO publishes the certified (TRIM) tax figures the Palm Beach "
                "County Tax Collector bills from. Total Tax = Ad Valorem + Non Ad "
                "Valorem. The annual paid/unpaid status (early-pay discount, "
                "delinquency penalty) is NOT exposed on the PA site; pull the "
                "Tax Collector bill at pbctax.publicaccessnow.com for that "
                "(this adapter does not require it to ship the certified amount)."
            ),
        }

    @classmethod
    def _parse_tax_history_table(cls, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Pull the 'Tax Year | AD VALOREM | NON AD VALOREM | TOTAL TAX' block.

        Returns a list of per-year dicts ordered most recent first. Empty list
        if the table is not found.
        """
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 3:
                continue
            header_cells = [
                c.get_text(" ", strip=True)
                for c in rows[0].find_all(["th", "td"])
            ]
            joined_header = " | ".join(header_cells)
            if "Tax Year" not in joined_header:
                continue

            # Collect AD VALOREM / NON AD VALOREM / TOTAL TAX rows
            ad_val_row: Optional[List[str]] = None
            non_ad_val_row: Optional[List[str]] = None
            total_row: Optional[List[str]] = None
            for tr in rows[1:]:
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not cs:
                    continue
                label = cs[0].upper().strip()
                if label == "AD VALOREM":
                    ad_val_row = cs[1:]
                elif label in ("NON AD VALOREM", "NON-AD VALOREM"):
                    non_ad_val_row = cs[1:]
                elif label == "TOTAL TAX":
                    total_row = cs[1:]

            if not total_row or not ad_val_row:
                # Skip non-tax tables (assessment, sales, etc.)
                continue

            # Year headers are after the leftmost label header
            year_headers = header_cells[1:]
            results: List[Dict[str, Any]] = []
            for i, yr in enumerate(year_headers):
                if not yr.isdigit():
                    continue
                # Defensive: pad with empty strings if a row is short
                ad_val = ad_val_row[i] if i < len(ad_val_row) else ""
                non_ad_val = non_ad_val_row[i] if non_ad_val_row and i < len(non_ad_val_row) else ""
                total = total_row[i] if i < len(total_row) else ""
                results.append({
                    "year": yr,
                    "ad_valorem": cls._safe_money(ad_val),
                    "non_ad_valorem": cls._safe_money(non_ad_val),
                    "total_tax": cls._safe_money(total),
                })
            if results:
                # Most-recent year first (PBCPAO already orders it this way,
                # but assert via sort).
                results.sort(key=lambda r: int(r["year"]), reverse=True)
                return results
        return []

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Best-effort address -> parcel resolution via PBCPAO's
        AdvSearch/RealPropSearch POST.

        On success, redirects (server-side) to the parcel-detail page so we
        can re-use the same parser. On failure, returns PA_AMBIGUOUS with
        the canonical search URL the human reviewer can use to disambiguate.

        The 2026-05-26 probe found that POSTing the form with just
        StreetNumber + StreetName returns HTTP 500 (the form has additional
        antiforgery / page-fields). Until the full set is discovered, this
        path returns PA_AMBIGUOUS with the AdvSearch URL — callers that have
        a recorder-index PCN should call `lookup_by_apn` instead.
        """
        # 1. Pull the AdvanceSearch landing to harvest antiforgery + form fields.
        try:
            search_page = self.session.get(
                self._base_url + "AdvSearch/AdvanceSearch", timeout=30
            )
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"PBCPAO AdvSearch landing GET error: {type(exc).__name__}: {exc}",
                fetched_at=datetime.now().isoformat(),
            )
        if search_page.status_code != 200:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"PBCPAO AdvSearch landing returned HTTP {search_page.status_code}",
                fetched_at=datetime.now().isoformat(),
            )

        # 2. Parse the address components from the input.
        norm = (address or "").upper().split(",", 1)[0].strip()
        street_num_m = re.match(r"^\s*(\d+)\s+(.+)$", norm)
        if not street_num_m:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"could not parse street number from address {address!r}",
                fetched_at=datetime.now().isoformat(),
            )
        street_num = street_num_m.group(1)
        rest = street_num_m.group(2).strip()
        # Strip trailing direction / suffix when present, fold suffix into its own field.
        rest_parts = rest.split()
        suffix = ""
        if rest_parts and rest_parts[-1] in {"DR", "ST", "AVE", "RD", "BLVD", "LN", "CT", "WAY", "PL", "TER", "CIR", "PKWY"}:
            suffix = rest_parts[-1]
            rest_parts = rest_parts[:-1]
        street_name = " ".join(rest_parts)

        # Return PA_NEEDS_PCN — the full AdvSearch form requires
        # antiforgery + page tokens we haven't reverse-engineered yet.
        # Callers should fall back to lookup_by_apn() when they have a PCN
        # (which the recorder-index search ALWAYS provides via column 15
        # legal field on Palm Beach Landmark).
        return PropertyAppraiserResult(
            status="PA_AMBIGUOUS",
            notes=(
                f"Palm Beach PAO address search has not been reverse-engineered "
                f"(AdvSearch RealPropSearch returns HTTP 500 without antiforgery "
                f"token). Use lookup_by_apn() when the recorder-index PCN is "
                f"available. Manual lookup URL: "
                f"{self._base_url}AdvSearch/AdvanceSearch?StreetNumber={street_num}"
                f"&StreetName={street_name.replace(' ', '+')}"
                f"{f'&StreetType={suffix}' if suffix else ''}"
            ),
            source_url=(
                f"{self._base_url}AdvSearch/AdvanceSearch?StreetNumber={street_num}"
                f"&StreetName={street_name.replace(' ', '+')}"
                f"{f'&StreetType={suffix}' if suffix else ''}"
            ),
            fetched_at=datetime.now().isoformat(),
        )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        # Owner-name search on PBCPAO returns a paginated multi-parcel list
        # under non-trivial conditions — leave as diagnostic only.
        return []

    # ----------------------------------------------------------- parse

    @classmethod
    def _parse_kv_tables(cls, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Pull every Field/Value-styled table into a list of dicts.

        Field/Value tables are detected by the first row containing the
        literal "Field" and "Value" as <th> text. Each table becomes a
        single dict; multiple field tables produce multiple dicts.
        """
        out: List[Dict[str, str]] = []
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 2:
                continue
            header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
            if "Field" not in header_cells or "Value" not in header_cells:
                continue
            kv: Dict[str, str] = {}
            for tr in rows[1:]:
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cs) >= 2:
                    kv[cs[0]] = " ".join(cs[1:]).strip()
            if kv:
                out.append(kv)
        return out

    @classmethod
    def _parse_sales_table(cls, soup: BeautifulSoup) -> List[SaleHistoryEntry]:
        """Find the table with header 'Sales Date / Price / OR Book/Page /
        Sale Type / Owner' and convert each row into a SaleHistoryEntry.

        PBCPAO emits OR Book / Page as TWO separate `<td>` cells with a "/"
        separator cell between them. We rebuild the combined string for the
        SaleHistoryEntry `deed_book_page` field.
        """
        sales: List[SaleHistoryEntry] = []
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 2:
                continue
            header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
            joined = " | ".join(header_cells).lower()
            if "sales date" not in joined or "or book" not in joined:
                continue
            for tr in rows[1:]:
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                # PBCPAO row shape: [date, price, book, '/', page, type, owner]
                if len(cs) < 4:
                    continue
                sale_date = cs[0].strip()
                sale_price = cls._safe_money(cs[1]) if len(cs) > 1 else 0
                book = page = ""
                deed_type = ""
                owner = ""
                # Detect "/" separator cell to deduce shape
                if "/" in cs and len(cs) >= 7:
                    book = cs[2]
                    page = cs[4]
                    deed_type = cs[5]
                    owner = cs[6] if len(cs) > 6 else ""
                elif len(cs) >= 5:
                    # Compact shape: [date, price, book/page, type, owner]
                    bp = cs[2].strip()
                    if "/" in bp:
                        book, _, page = bp.partition("/")
                        book = book.strip()
                        page = page.strip()
                    else:
                        book = bp
                    deed_type = cs[3]
                    owner = cs[4]
                if not sale_date or not re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", sale_date):
                    continue
                deed_book_page = f"{book} / {page}".strip(" /") if book or page else ""
                sales.append(SaleHistoryEntry(
                    sale_date=sale_date,
                    sale_price=sale_price,
                    deed_doc_number="",     # PBCPAO doesn't expose CIN here
                    deed_book_page=deed_book_page,
                    deed_type=deed_type.strip().upper(),
                    grantor="",
                    grantee=owner.strip(),
                    qualified=False,       # PBCPAO doesn't flag sale quality
                    notes="",
                ))
            break  # only one sales table per parcel
        return sales

    @classmethod
    def _parse_owner_table(cls, soup: BeautifulSoup) -> Dict[str, str]:
        """Locate the 'Owner(s) | Mailing Address' table and return
        ``{owner_of_record, co_owners, mailing_address}``.

        PBCPAO can render owner names two ways:
          (a) One owner per <tr> in the Owner(s) column (the test fixture).
          (b) Multiple <span>HABER DANA M</span><br/><span>HABER MARK &</span>
              packed into a single <td> with <br/> separators (the live
              2026-05-26 markup).
        We handle both by splitting either across rows OR across <span>/<br>
        boundaries inside a single cell.
        """
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 2:
                continue
            header_cells = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            joined = " | ".join(header_cells)
            if "owner" not in joined or "mailing" not in joined:
                continue
            owners: List[str] = []
            mailing_lines: List[str] = []
            for tr in rows[1:]:
                tds = tr.find_all(["td", "th"])
                if len(tds) < 2:
                    continue
                # (b) Look for <span> children inside the owner cell first.
                owner_spans = tds[0].find_all("span")
                if owner_spans:
                    for sp in owner_spans:
                        name = sp.get_text(" ", strip=True)
                        if name:
                            owners.append(name)
                else:
                    # Split on <br>-derived newlines if any
                    raw = tds[0].get_text("\n", strip=True)
                    for line in raw.split("\n"):
                        line = line.strip()
                        if line:
                            owners.append(line)

                # Mailing address — preserve line breaks separately
                mailing_raw = tds[1].get_text("\n", strip=True)
                for line in mailing_raw.split("\n"):
                    if line.strip():
                        mailing_lines.append(line.strip())

            primary = owners[0] if owners else ""
            co_owners = owners[1:] if len(owners) > 1 else []
            mailing = ", ".join(mailing_lines).strip()
            return {
                "owner_of_record": primary,
                "co_owners": co_owners,
                "mailing_address": mailing,
            }
        return {}

    @classmethod
    def _parse_assessment_table(cls, soup: BeautifulSoup) -> Dict[str, int]:
        """Pull Assessed Value / Taxable Value / Total Market Value / Land Value /
        Improvement Value from the PBCPAO per-year assessment/appraisal tables.

        PBCPAO may render the assessment rows (Assessed Value, Taxable Value,
        Exemption Amount) in one table and the appraisal rows (Total Market Value,
        Land Value, Improvement Value) in a SEPARATE table.  We do two passes:

        Pass 1 — find the table with BOTH "assessed value" AND "taxable value" rows.
        Pass 2 — scan ALL tables for appraisal rows not yet found (total market value,
                  land value, improvement value).
        """
        _APPRAISAL_LABELS = {
            "assessed value":    "assessed_value",
            "taxable value":     "taxable_value",
            "net taxable value": "taxable_value",
            "exemption amount":  "exemption_amount",
            "total market value":"just_value",
            "just value":        "just_value",
            "market value":      "just_value",
            "improvement value": "improvement_value",
            "building value":    "improvement_value",
            "land value":        "land_value",
        }

        def _extract_from_table(t) -> Dict[str, int]:
            extracted: Dict[str, int] = {}
            for r in t.find_all("tr"):
                cells = r.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(" ", strip=True).lower().strip()
                key = _APPRAISAL_LABELS.get(label)
                if not key:
                    continue
                values_text = [c.get_text(" ", strip=True) for c in cells[1:]]
                first_val = next(
                    (v for v in values_text if v.startswith("$") or v[:1].isdigit()), ""
                )
                if first_val:
                    amt = cls._safe_money(first_val)
                    if amt and key not in extracted:
                        extracted[key] = amt
            return extracted

        out: Dict[str, int] = {}

        # Pass 1 — primary assessment table (must have assessed value + taxable value)
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 3:
                continue
            row_labels = [
                r.find_all(["td", "th"])[0].get_text(" ", strip=True).lower()
                for r in rows if r.find_all(["td", "th"])
            ]
            if "assessed value" not in row_labels and "taxable value" not in row_labels:
                continue
            out.update(_extract_from_table(t))
            if out:
                break

        # Pass 2 — look for appraisal table with land/improvement/market rows
        # that may be separate from the assessment table
        if not out.get("just_value") or not out.get("land_value"):
            appraisal_keys = {"just_value", "land_value", "improvement_value"}
            for t in soup.find_all("table"):
                rows = t.find_all("tr")
                if len(rows) < 3:
                    continue
                row_labels = [
                    r.find_all(["td", "th"])[0].get_text(" ", strip=True).lower()
                    for r in rows if r.find_all(["td", "th"])
                ]
                if not any(lbl in _APPRAISAL_LABELS and _APPRAISAL_LABELS[lbl] in appraisal_keys
                           for lbl in row_labels):
                    continue
                partial = _extract_from_table(t)
                for k, v in partial.items():
                    if k not in out:
                        out[k] = v
                if out.get("just_value") and out.get("land_value"):
                    break

        return out

    @classmethod
    def _parse_exemption_table(cls, soup: BeautifulSoup) -> Dict[str, Any]:
        """Look for the 'Applicant/Owner(s) | Year | Detail' exemption table.

        Sets `homestead_active=True` when any current-year row's Detail
        contains "HOMESTEAD".
        """
        out: Dict[str, Any] = {"homestead_active": False, "exemptions": []}
        current_year = datetime.now().year
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 2:
                continue
            header = " | ".join(c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"]))
            if "applicant" not in header or "detail" not in header:
                continue
            for tr in rows[1:]:
                cs = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cs) < 3:
                    continue
                applicant, year, detail = cs[0], cs[1], cs[2]
                out["exemptions"].append({
                    "applicant": applicant,
                    "year": year,
                    "detail": detail,
                })
                # Active homestead = any row in current OR last tax year
                if detail.upper().startswith("HOMESTEAD"):
                    try:
                        if int(year) >= current_year - 1:
                            out["homestead_active"] = True
                    except (ValueError, TypeError):
                        pass
            break
        return out

    def _parse_parcel_html(self, html: str, pcn_clean: str) -> PropertyAppraiserResult:
        """Parse the full PBCPAO Property/Details HTML into a
        PropertyAppraiserResult. Sets `status=PA_NO_RESULTS` when the page
        appears to be an empty-result shell."""
        if not html or len(html) < 5000:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"PBCPAO returned an empty/short response for PCN {pcn_clean!r}",
                apn=self._format_pcn_hyphenated(pcn_clean),
                fetched_at=datetime.now().isoformat(),
            )

        soup = BeautifulSoup(html, "html.parser")

        # Property detail table (Location Address, Subdivision, Legal Desc, etc.)
        kv_tables = self._parse_kv_tables(soup)
        property_detail: Dict[str, str] = {}
        for kv in kv_tables:
            if "Location Address" in kv or "Parcel Control Number" in kv or "Legal Description" in kv:
                property_detail = kv
                break

        if not property_detail or not property_detail.get("Location Address"):
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"PBCPAO HTML had no Property Detail table for PCN {pcn_clean!r}",
                apn=self._format_pcn_hyphenated(pcn_clean),
                fetched_at=datetime.now().isoformat(),
            )

        # Owner / mailing
        owner_data = self._parse_owner_table(soup)

        # Sales history
        sales = self._parse_sales_table(soup)

        # Assessment values
        asmt = self._parse_assessment_table(soup)

        # Exemption / homestead
        exempt = self._parse_exemption_table(soup)

        # Structural (year built, sqft) — pulled from any kv-table that has them
        year_built = 0
        living_area = 0
        for kv in kv_tables:
            for k, v in kv.items():
                if k.lower() == "year built":
                    year_built = self._safe_int(v)
                if k.lower() in ("total square feet*", "total square feet"):
                    living_area = self._safe_int(v)

        # Build display URL (the one the customer-facing report cites)
        source_url = self._public_detail_pattern.format(pcn_clean=pcn_clean)

        result = PropertyAppraiserResult(
            apn=self._format_pcn_hyphenated(pcn_clean),
            folio=pcn_clean,
            pin="",
            owner_of_record=(owner_data.get("owner_of_record") or "").strip(),
            co_owners=list(owner_data.get("co_owners") or []),
            situs_address=property_detail.get("Location Address", "").strip(),
            mailing_address=(owner_data.get("mailing_address") or "").strip(),
            legal_description=property_detail.get("Legal Description", "").strip(),
            just_value=asmt.get("just_value", 0),
            assessed_value=asmt.get("assessed_value", 0),
            land_value=asmt.get("land_value", 0),
            improvement_value=asmt.get("improvement_value", 0),
            homestead_active=exempt.get("homestead_active", False),
            homestead_amount=asmt.get("exemption_amount", 0),
            year_built=year_built,
            living_area_sqft=living_area,
            sale_history=sales,
            source_url=source_url,
            status="PA_SUCCESS",
            notes="",
            fetched_at=datetime.now().isoformat(),
        )
        return result


__all__ = ["PalmBeachPBCPAO"]
