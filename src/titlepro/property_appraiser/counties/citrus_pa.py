"""Citrus County (FL) Property Appraiser — Tyler / TrueAutomation "EagleWeb" adapter.

Derived from the 2026-06-18 live probe (see
docs/FL/source/landmark_pa_probe/fl_citrus/probe_observed.md). Citrus runs the
**Tyler Technologies / TrueAutomation "ProVal Web" (EagleWeb)** property-search
engine at ``https://www.citruspa.org/_web/`` — a server-rendered ASP.NET WebForms
app (``__VIEWSTATE`` / ``__EVENTVALIDATION``) behind a one-time **Disclaimer gate**.
No Cloudflare / Akamai / CAPTCHA — plain IIS, reachable from any US egress.

Cross-county note (2026-06-18): among the FL Landmark batch, Citrus is the ONLY
EagleWeb county — the others delegate to qPublic/Schneider. A spot-check of likely
peers (Sumter, Hardee, Suwannee, Pinellas) found them on qPublic or with the
``_web/search/commonsearch.aspx`` path retired, so this stays a Citrus-specific
adapter (``citrus_pa_http``) rather than a shared ``tyler_eagleweb_pa_http``. The
class is written engine-generically (base host + ``_web`` root are config-driven),
so if another live EagleWeb county turns up it can reuse this with a base_url swap.

Flow (all under ``/_web``):
  1. GET ``search/commonsearch.aspx?mode=<address|realprop|owner>`` → 200 on
     ``Search/Disclaimer.aspx`` (form: ``btAgree`` / ``btDisagree`` + ``hdURL``).
  2. POST ``btAgree`` → the live search form (address fields ``inpNumber`` /
     ``inpStreet`` / ``inpSuffix1`` …; parcel field ``inpParid``; owner ``inpName``).
  3. POST ``btSearch`` → results grid ``table#searchResults`` (columns: Altkey,
     Parcel ID, Owner Name, Site Address, Site City, Short Legal). Each row's
     ``selectSearchRow('../Datalets/Datalet.aspx?sIndex=<s>&idx=<n>')`` is the
     detail key. "Your search did not find any records." = no results.
  4. GET ``Datalets/Datalet.aspx?mode=profileall&sIndex=<s>&idx=<n>`` — the
     **single** all-sections detail page: header (Parcel ID + situs), All Owners
     table (co-owners + tenancy), Value History (Year/Land/Impr/**Just Value**/
     Non-Sch. Assessed — newest first), Homestead, and a **Sales** table
     (Sale Date / Sale Price / Book/Page / Instr Type / V-or-I — newest first).

All parsing is on side-effect-free public methods (``parse_profileall_html`` /
``parse_results_grid``) so unit tests feed captured fixtures with no network.
HTTP-only via ``curl_cffi`` (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_BASE = "https://www.citruspa.org"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+)\)?")
_NO_RESULTS_RE = re.compile(r"did not find any records|no records? found", re.I)


def _money(s: str) -> int:
    m = _MONEY_RE.search(s or "")
    return int(m.group(1).replace(",", "")) if m else 0


class CitrusPA(AbstractPropertyAppraiser):
    """Tyler / TrueAutomation EagleWeb adapter (Citrus County FL)."""

    SOURCE_LABEL = "Citrus County Property Appraiser"
    LIVE_PLATFORM = "citrus_pa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "fl_citrus")
        self.county_name = self.config.get("county_name", "Citrus")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.base_url = (self.config.get("base_url") or _DEFAULT_BASE).rstrip("/")
        # EagleWeb apps live under a /_web root.
        self.web_root = f"{self.base_url}/_web"
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        self.search_url = f"{self.web_root}/search/commonsearch.aspx"
        self.datalet_url = f"{self.web_root}/Datalets/Datalet.aspx"

    # ------------------------------------------------------------------ net
    def _session(self):
        from curl_cffi import requests as cffi  # local import; optional dep
        return cffi.Session(impersonate=self.impersonate, timeout=30)

    @staticmethod
    def _hidden(html: str, name: str) -> str:
        m = (
            re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
            or re.search(r'value="([^"]*)"[^>]*name="%s"' % re.escape(name), html)
        )
        return m.group(1) if m else ""

    def _accept_disclaimer_and_get_form(self, session, mode: str) -> str:
        """GET the search URL (lands on Disclaimer), POST btAgree, return the
        live search-form HTML. If no disclaimer is shown (cookie already set),
        the first GET already is the form."""
        url = f"{self.search_url}?mode={mode}"
        r = session.get(url, allow_redirects=True)
        html = r.text
        if "btAgree" in html and "isclaimer" in (str(r.url) + html):
            form = {
                "__VIEWSTATE": self._hidden(html, "__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": self._hidden(html, "__VIEWSTATEGENERATOR"),
                "__EVENTVALIDATION": self._hidden(html, "__EVENTVALIDATION"),
                "hdURL": self._hidden(html, "hdURL"),
                "btAgree": "Agree",
            }
            session.post(str(r.url), data=form, allow_redirects=True)
            html = session.get(url, allow_redirects=True).text
        return html

    @staticmethod
    def _all_hidden(html: str) -> Dict[str, str]:
        """All ``<input type="hidden">`` name->value pairs in the form.

        EagleWeb's commonsearch form carries a large bundle of state hidden
        fields (__VIEWSTATE, SortBy=PADDR1, SortDir, hdListType=PA, mode=ADDRESS,
        ...). Round-tripping them verbatim — rather than hand-reconstructing a
        subset — is what makes the submit register; a hand-built subset returns
        EagleWeb's "Requested page not registered" guard page. First occurrence
        of a duplicated name wins.
        """
        out: Dict[str, str] = {}
        for tag in re.findall(r"<input[^>]*type=[\"']hidden[\"'][^>]*>", html, re.I):
            n = re.search(r'name="([^"]+)"', tag)
            if not n or n.group(1) in out:
                continue
            v = re.search(r'value="([^"]*)"', tag)
            out[n.group(1)] = v.group(1) if v else ""
        return out

    def _run_search(self, session, mode: str, fields: Dict[str, str]) -> str:
        """Submit a commonsearch POST for the given mode + input fields.

        Mirrors a real browser submit: harvest the live form's hidden state
        verbatim, override only the visible search inputs, add the btSearch
        trigger, and POST to the **mode-qualified** action URL (the live form
        action is ``commonsearch.aspx?mode=<mode>`` — mode in the query string,
        not just the body — without which EagleWeb returns "page not
        registered").
        """
        H = self._accept_disclaimer_and_get_form(session, mode)
        form = self._all_hidden(H)
        form.setdefault("__EVENTTARGET", "")
        form.setdefault("__EVENTARGUMENT", "")
        form["hdSelectAllChecked"] = "false"
        form.update(fields)          # inpNumber / inpStreet / inpParid / inpName
        form["btSearch"] = "Search"
        post_url = f"{self.search_url}?mode={mode}"
        return session.post(post_url, data=form, allow_redirects=True).text

    # -------------------------------------------------------------- parsing
    @staticmethod
    def _soup(html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def _section_table(soup, *, id_startswith: str = "",
                       header_contains: List[str] | None = None):
        """Locate an EagleWeb Datalet section table.

        The Tyler/TrueAutomation Datalet page names each section table by its
        ``id`` (e.g. ``id="Value History and Tax Amount"`` / ``id="Sales"`` /
        ``id="All Owners"``) and renders the column-header row as ``<td>`` cells,
        NOT ``<th>``. So a ``<th>``-keyed scan finds nothing. Match by ``id``
        prefix first; fall back to a table whose first row's text contains every
        token in ``header_contains``. Returns the ``<table>`` tag or ``None``.
        """
        if id_startswith:
            for tbl in soup.find_all("table"):
                tid = (tbl.get("id") or "")
                if tid.lower().startswith(id_startswith.lower()):
                    return tbl
        if header_contains:
            for tbl in soup.find_all("table"):
                first = tbl.find("tr")
                if first is None:
                    continue
                cells = " ".join(c.get_text(" ", strip=True)
                                 for c in first.find_all(["td", "th"])).lower()
                if all(tok.lower() in cells for tok in header_contains):
                    return tbl
        return None

    @staticmethod
    def _rows_with_header(tbl) -> Tuple[List[str], List[List[str]]]:
        """Split a section table into (header_cells, [data_row_cells, ...]).

        The first row carrying any text is taken as the header (``<td>`` or
        ``<th>``); subsequent non-empty rows are data. EagleWeb pads sections
        with blank spacer rows, which are dropped.
        """
        header: List[str] = []
        data: List[List[str]] = []
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            if not header:
                header = cells
            else:
                data.append(cells)
        return header, data

    def parse_results_grid(self, html: str) -> List[Dict[str, str]]:
        """Parse the ``table#searchResults`` grid into row dicts.

        Each dict carries ``parcel_id`` / ``owner`` / ``address`` / ``city`` /
        ``legal`` plus ``sIndex`` + ``idx`` (the Datalet detail key). [] for a
        no-results page.
        """
        if _NO_RESULTS_RE.search(html):
            return []
        soup = self._soup(html)
        tbl = soup.find("table", id="searchResults")
        if tbl is None:
            return []
        trs = tbl.find_all("tr")
        if not trs:
            return []
        headers = [re.sub(r"[^\w/ ]", "", c.get_text(" ", strip=True)).strip()
                   for c in trs[0].find_all(["td", "th"])]
        hidx = {h.lower(): i for i, h in enumerate(headers)}
        rows: List[Dict[str, str]] = []
        for tr in trs[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells or not any(cells):
                continue
            sidx = idx = ""
            # The detail link rides the row's onclick=selectSearchRow('...Datalet
            # .aspx?sIndex=0&idx=1'). BeautifulSoup re-serializes the '&' as
            # '&amp;' in str(tr), so the separator must be optional-amp aware.
            m = re.search(r"sIndex=(\d+)&(?:amp;)?idx=(\d+)", str(tr))
            if m:
                sidx, idx = m.group(1), m.group(2)

            def col(name: str) -> str:
                i = hidx.get(name.lower())
                return cells[i] if i is not None and i < len(cells) else ""

            row = {
                "parcel_id": col("Parcel ID"),
                "altkey": col("Altkey"),
                "owner": col("Owner Name"),
                "address": col("Site Address"),
                "city": col("Site City"),
                "legal": col("Short Legal"),
                "sIndex": sidx,
                "idx": idx,
            }
            if row["sIndex"] and row["idx"]:
                rows.append(row)
        return rows

    def parse_profileall_html(self, html: str) -> PropertyAppraiserResult:
        """Parse the ``mode=profileall`` Datalet page -> PropertyAppraiserResult.

        Public + side-effect-free so unit tests feed captured fixtures.
        """
        res = PropertyAppraiserResult()
        soup = self._soup(html)
        lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]

        res.apn = self._after_label(lines, "Parcel ID:")
        res.folio = self._after_label(lines, "Altkey:")

        res.situs_address = self._extract_situs(lines)
        res.legal_description = self._after_label(lines, "Short Legal")

        owner, co_owners = self._parse_all_owners(soup, lines)
        res.owner_of_record = owner
        res.co_owners = co_owners
        res.mailing_address = self._parse_mailing(lines)

        res.homestead_active = self._has_homestead(lines)

        yb = self._after_label(lines, "Year Built")
        res.year_built = int(yb) if yb.isdigit() else 0

        just, assessed = self._parse_value_history(soup)
        res.just_value = just
        res.assessed_value = assessed

        res.sale_history = self._parse_sales(soup)

        res.status = "PA_SUCCESS" if res.apn else "PA_NO_RESULTS"
        res.fetched_at = datetime.now().isoformat()
        return res

    # ---- profileall sub-parsers -------------------------------------------
    @staticmethod
    def _after_label(lines: List[str], label: str) -> str:
        """Value following an inline 'Label: value' or a 'Label' \\n 'value' pair."""
        for i, ln in enumerate(lines):
            if ln.startswith(label):
                rest = ln[len(label):].strip(" :").strip()
                if rest:
                    # take only up to the next "Word:" label if inline-joined
                    rest = re.split(r"\s{2,}|\bAltkey:|\bParcel ID:", rest)[0].strip()
                    return rest
                for j in range(i + 1, len(lines)):
                    if lines[j]:
                        return lines[j]
        return ""

    @staticmethod
    def _extract_situs(lines: List[str]) -> str:
        # The situs line looks like "1015 S HIGHLANDS AVE , INVERNESS, 34452".
        situs_re = re.compile(r"^\d+\s+.+,\s*[A-Z][A-Za-z ]+,\s*\d{5}$")
        for ln in lines:
            if situs_re.match(ln):
                return re.sub(r"\s+,", ",", re.sub(r"\s{2,}", " ", ln)).strip()
        return ""

    def _parse_all_owners(self, soup, lines: List[str]) -> Tuple[str, List[str]]:
        """Owner(s) from the 'All Owners' table (Name / Owner Type columns).

        Falls back to the 'Name' label under Mailing Address if absent.
        """
        owners: List[str] = []
        tbl = self._section_table(soup, id_startswith="All Owners",
                                  header_contains=["name", "owner type"])
        if tbl is not None:
            header, data = self._rows_with_header(tbl)
            ni = next((i for i, h in enumerate(header)
                       if h.strip().lower() == "name"), 0)
            for cells in data:
                if ni < len(cells):
                    nm = cells[ni].strip()
                    if nm and nm.lower() != "name":
                        owners.append(nm)
        if not owners:
            nm = self._after_label(lines, "Name")
            if nm:
                owners = [nm]
        return (owners[0] if owners else ""), owners[1:]

    @staticmethod
    def _parse_mailing(lines: List[str]) -> str:
        for i, ln in enumerate(lines):
            if ln == "Mailing Address" and i + 1 < len(lines):
                parts = []
                for j in range(i + 1, min(i + 4, len(lines))):
                    nxt = lines[j]
                    if nxt in ("Name", "All Owners", "Bldg Number") or nxt.endswith(":"):
                        break
                    parts.append(nxt)
                if parts:
                    return " ".join(parts).strip()
        return ""

    @staticmethod
    def _has_homestead(lines: List[str]) -> bool:
        # The profileall page renders "R39 - Homestead 2023" when homestead is on.
        return any(re.search(r"-\s*Homestead\b", ln) for ln in lines)

    def _parse_value_history(self, soup) -> Tuple[int, int]:
        """Just Value + Non-Sch. Assessed from the Value History table (newest
        row first). Returns (just_value, assessed_value)."""
        tbl = self._section_table(soup, id_startswith="Value History",
                                  header_contains=["just value", "assessed"])
        if tbl is None:
            return 0, 0
        header, data = self._rows_with_header(tbl)
        ji = next((i for i, h in enumerate(header)
                   if h.strip().lower() == "just value"), None)
        ai = next((i for i, h in enumerate(header) if "assessed" in h.lower()), None)
        for cells in data:
            if cells and re.match(r"^\d{4}$", cells[0].strip()):
                just = _money(cells[ji]) if ji is not None and ji < len(cells) else 0
                assessed = _money(cells[ai]) if ai is not None and ai < len(cells) else 0
                return just, assessed
        return 0, 0

    def _parse_sales(self, soup) -> List[SaleHistoryEntry]:
        """Sales table (newest-first): Sale Date / Sale Price / Book/Page /
        Instr Type / V/I."""
        tbl = self._section_table(soup, id_startswith="Sales",
                                  header_contains=["sale date", "sale price"])
        if tbl is None:
            return []
        header, data = self._rows_with_header(tbl)
        hidx = {h.strip().lower(): i for i, h in enumerate(header)}
        sales: List[SaleHistoryEntry] = []
        for cells in data:
            def col(name: str) -> str:
                i = hidx.get(name.lower())
                return cells[i] if i is not None and i < len(cells) else ""

            date = col("Sale Date")
            if not re.match(r"\d{1,2}/\d{1,2}/\d{4}", date):
                continue
            sales.append(SaleHistoryEntry(
                sale_date=date,
                sale_price=_money(col("Sale Price")),
                deed_book_page=col("Book/Page"),
                deed_type=self._deed_type_code(col("Instr Type")),
            ))
        return sales

    @staticmethod
    def _deed_type_code(instr: str) -> str:
        """Normalize EagleWeb's '00-WARRANTY DEED'-style code to a short code."""
        u = (instr or "").upper()
        table = [
            ("WARRANTY DEED", "WD"),
            ("QUIT CLAIM", "QCD"),
            ("QUITCLAIM", "QCD"),
            ("SPECIAL WARRANTY", "SWD"),
            ("TAX DEED", "TXD"),
            ("CERTIFICATE OF TITLE", "CT"),
            ("PERSONAL REP", "PRD"),
            ("TRUSTEE", "TRD"),
        ]
        for needle, code in table:
            if needle in u:
                return code
        # keep the raw "NN-DESCRIPTION" otherwise (e.g. "14-SALE / MORE THAN 1 PARCEL")
        return instr or ""

    # --------------------------------------------------------- entry points
    def _fetch_detail(self, session, sidx: str, idx: str) -> PropertyAppraiserResult:
        url = f"{self.datalet_url}?mode=profileall&sIndex={sidx}&idx={idx}"
        r = session.get(url, allow_redirects=True)
        if r.status_code != 200:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"Citrus datalet returned {r.status_code} (sIndex={sidx} idx={idx})",
                fetched_at=datetime.now().isoformat(),
            )
        res = self.parse_profileall_html(r.text)
        res.source_url = url
        return res

    @staticmethod
    def _norm_parcel(s: str) -> str:
        return re.sub(r"[^0-9A-Za-z]", "", s or "").upper()

    @staticmethod
    def _norm_addr(s: str) -> str:
        """Street portion of an address, sans trailing suffix, for grid matching."""
        s = re.sub(r"\s+", " ", (s or "").upper()).strip().split(",")[0].strip()
        s = re.sub(r"\b(ST|AVE|RD|DR|LN|BLVD|CT|PL|WAY|TER|CIR|HWY|PKWY)\b\.?$",
                   "", s).strip()
        return s

    def _resolve(self, session, html: str, query: str,
                 expect_unique: bool) -> PropertyAppraiserResult:
        rows = self.parse_results_grid(html)
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"Citrus search returned no rows for {query!r}",
                fetched_at=datetime.now().isoformat(),
            )

        # Address mode: prefer rows whose site address exactly matches the query
        # street (EagleWeb returns neighbors on a number+street search).
        if not expect_unique:
            wanted = self._norm_addr(query)
            if wanted:
                exact_addr = [r for r in rows if self._norm_addr(r["address"]) == wanted]
                if exact_addr:
                    rows = exact_addr

        # Collapse rows that point at the SAME parcel — EagleWeb emits one row
        # per owner, so a single property surfaces N rows (one per co-owner).
        # Only DISTINCT parcels constitute genuine ambiguity.
        by_parcel: Dict[str, Dict[str, str]] = {}
        for r in rows:
            by_parcel.setdefault(self._norm_parcel(r["parcel_id"]), r)
        distinct = list(by_parcel.values())

        # APN mode: honor an exact parcel match if present.
        if expect_unique:
            q = self._norm_parcel(query)
            exact = [r for r in distinct if self._norm_parcel(r["parcel_id"]) == q]
            if len(exact) == 1:
                return self._fetch_detail(session, exact[0]["sIndex"], exact[0]["idx"])

        if len(distinct) == 1:
            r = distinct[0]
            return self._fetch_detail(session, r["sIndex"], r["idx"])

        res = self._fetch_detail(session, distinct[0]["sIndex"], distinct[0]["idx"])
        if res.status == "PA_SUCCESS":
            res.status = "PA_AMBIGUOUS"
            res.notes = (f"Citrus returned {len(distinct)} distinct parcels for "
                         f"{query!r}; first detailed. Parcels: "
                         f"{', '.join(r['parcel_id'] for r in distinct[:8])}")
        return res

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        try:
            session = self._session()
            # Strip city/state/zip after the first comma so EagleWeb gets a
            # bare street address (e.g. "2451 N Stampede Dr, Beverly Hills, FL"
            # → "2451 N Stampede Dr").  The full address is preserved for
            # _resolve's _norm_addr comparison.
            street_only = (address or "").split(",")[0].strip()
            fields = self._address_fields(street_only)
            html = self._run_search(session, "address", fields)
            return self._resolve(session, html, address, expect_unique=False)
        except Exception as exc:  # fail soft per base contract
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"Citrus address lookup error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        """Realprop lookup.

        Live-validated 2026-06-18: Citrus's ``realprop`` ``inpParid`` field keys
        on the numeric **altkey/folio** (e.g. ``1772311``), NOT the geo strap
        ``Parcel ID`` shown in the grid (``20E19S210020 02280 0400``) — the strap
        returns zero rows in realprop mode. The PA anchor is normally reached via
        ``lookup_by_address`` (the SIMMONS gate), whose result carries the folio
        in ``.folio`` for any follow-up realprop re-search.
        """
        try:
            session = self._session()
            parcel = (apn or "").strip()
            html = self._run_search(session, "realprop", {"inpParid": parcel})
            res = self._resolve(session, html, parcel, expect_unique=True)
            if res.status == "PA_NO_RESULTS" and re.search(r"[A-Za-z]", parcel):
                res.notes = (f"Citrus realprop found no rows for strap {parcel!r}; "
                             f"realprop keys on the numeric altkey/folio, not the "
                             f"geo strap. Re-search by .folio (via address lookup).")
            return res
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"Citrus APN lookup error: {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        try:
            session = self._session()
            html = self._run_search(session, "owner", {"inpName": (owner_name or "").strip()})
            rows = self.parse_results_grid(html)
            out: List[PropertyAppraiserResult] = []
            for row in rows[:25]:
                out.append(self._fetch_detail(session, row["sIndex"], row["idx"]))
            return out
        except Exception:
            return []

    @staticmethod
    def _address_fields(address: str) -> Dict[str, str]:
        """Split a free-form address into EagleWeb's separate address inputs.

        Live-validated 2026-06-18: ``inpStreet`` matches the BARE street name —
        a leading directional (N/S/E/W/...) belongs in ``inpAdrdir`` and the
        trailing suffix (AVE/ST/...) in ``inpSuffix1``, NOT in ``inpStreet``.
        Folding the direction into ``inpStreet`` (e.g. "S HIGHLANDS") returns
        zero rows. ``"1015 S HIGHLANDS AVE"`` -> number=1015, dir=S,
        street=HIGHLANDS, suffix=AVE.
        """
        addr = (address or "").strip()
        m = re.match(r"^\s*(\d+)\s+(.*)$", addr)
        number, rest = (m.group(1), m.group(2)) if m else ("", addr)
        # Leading directional -> inpAdrdir.
        adrdir = ""
        dm = re.match(r"^(N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST)\s+(.*)$",
                      rest, flags=re.I)
        if dm:
            adrdir, rest = dm.group(1).upper()[:2], dm.group(2)
        # Trailing street suffix -> inpSuffix1.
        suffix = ""
        sm = re.search(r"\s+(ST|AVE|RD|DR|LN|BLVD|CT|PL|WAY|TER|CIR|HWY|PKWY|"
                       r"CIRCLE|COURT|LANE|ROAD|DRIVE|STREET|AVENUE)\.?\s*$",
                       rest, flags=re.I)
        if sm:
            suffix = sm.group(1).upper()
            rest = rest[:sm.start()].strip()
        return {"inpNumber": number, "inpStreet": rest.strip(),
                "inpAdrdir": adrdir, "inpSuffix1": suffix,
                "inpSuffix2": "", "inpUnit": ""}
