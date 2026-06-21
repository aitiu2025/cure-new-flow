"""Shared qPublic / Schneider Geospatial Property Appraiser HTTP adapter.

ONE adapter for every Florida county whose Property Appraiser delegates its
public record search to Schneider's multi-tenant qPublic / Beacon app
(``qpublic.schneidercorp.com`` / ``beacon.schneidercorp.com``). Derived from the
2026-06-17 live probe (see docs/FL/source/landmark_pa_probe/RECON_SUMMARY_2026-06-17.md
+ the per-county fl_<county>/probe_observed.md files). The county marketing sites
(mostly WordPress) carry no data — they all link out to the SAME Schneider app,
keyed only by a per-county ``app_id``.

Covers (Landmark wave): bay(834), clay(830), flagler(598), monroe(605),
wakulla(836), walton(835 — beacon host), indian_river(1109), st_johns(960),
levy(930). New qPublic counties are a config-only add (just the ``app_id``).

Engine = **ASP.NET WebForms** (``__VIEWSTATE`` / ``__EVENTVALIDATION`` postbacks),
Cloudflare-fronted. HTTP-only via ``curl_cffi`` ``safari17_2_ios`` (Tony directive
#1 — no Selenium/Playwright; safari17_2_ios is the only impersonation proven to pass
Schneider's Cloudflare for both GET and POST — do NOT pivot off it).

**Cloudflare Bot-Manager note + cf_clearance jar.** Under sustained automated
volume (or from a flagged datacenter egress) the schneidercorp.com zone escalates
to a *managed* challenge ("Just a moment..." 403) that TLS impersonation alone
can't solve. To unblock without a browser at request time, mint a ``cf_clearance``
cookie ONCE (residential egress / one-time headed browser through the challenge)
and drop it at ``~/.titlepro/schneider_cookies.json`` (same shape as Lee's
``~/.titlepro/lee_cookies.json``: a dict with a ``cookies`` list of
``{name,value,domain,path,...}``). On session init the adapter loads that jar
before the first request; if it's absent the adapter behaves exactly as before.
Path is overridable per-county via the ``cookie_jar`` config key. See
``_DEFAULT_COOKIE_JAR`` + ``_load_cookie_jar``.

Two flows, both off ``Application.aspx?AppID=<id>&PageType=Search``:
  * **Search** — GET the search page (harvest VIEWSTATE), POST a ``__doPostBack``
    on the chosen search panel's ``btnSearch``. An EXACT parcel hit 302s straight
    to the parcel detail (``PageTypeID=4 … KeyValue=<parcel>``); a looser
    address/owner search lands on a results grid (``PageTypeID=3``) whose rows each
    link to a detail by ``KeyValue``.
  * **Detail** — server-rendered tables: Parcel Summary (Parcel ID / Location
    Address / Brief Tax Description = legal), Owner Information, Valuation
    (Just/Assessed, multi-year newest-first), and a **Sales** table (newest-first:
    Sale Date / Sale Price / Instrument=deed-type / Deed Book / Deed Page /
    Qualification / Transfer Code / Multi-Parcel / V-or-I / Grantor / Grantee).

**Per-tenant drift handled (the multi-tenancy gotchas the live probe caught):**
  1. The search-panel ``ctlBodyPane$ctlNN$ctl01`` index SHIFTS per county (Clay:
     Name=ctl00/Addr=ctl01/Parcel=ctl02; Walton: Name=ctl02/Addr=ctl03/Parcel=ctl04
     because Walton has extra panels). We therefore NEVER hardcode the index — we
     discover each panel's event-target + field prefix by its stable
     ``SearchIntent="OwnerName|Address|ParcelID|LegalDesc"`` attribute.
  2. Valuation labels differ ("Just Market Value" vs "Just (Market) Value";
     "Total Assessed Value" vs "Assessed Value") — matched by flexible token rules.
  3. Host is ``qpublic.`` for most, ``beacon.`` for some (Walton) — config-driven.

All parsing is on side-effect-free, public methods (``parse_detail_html`` /
``parse_grid_html``) so unit tests feed captured fixtures with no network.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult, SaleHistoryEntry

_DEFAULT_IMPERSONATE = "safari17_2_ios"
_DEFAULT_HOST = "qpublic.schneidercorp.com"
_MONEY_RE = re.compile(r"-?\$?\(?([\d,]+)\)?")

# Optional Cloudflare-clearance cookie jar for the schneidercorp.com zone.
# When present, its cookies (notably ``cf_clearance``) are loaded into the
# curl_cffi session BEFORE any request, so a jar minted once from a residential
# egress / headed browser lets this datacenter egress through Schneider's
# Cloudflare Bot-Manager managed challenge. Absent → behave exactly as before
# (no regression). Format mirrors ~/.titlepro/lee_cookies.json:
#   {
#     "minted_at": "2026-06-18T...", "landing": "https://qpublic.schneidercorp.com/",
#     "cookies": [{"name": "cf_clearance", "value": "...", "domain": ".schneidercorp.com",
#                  "path": "/", "expires": <unix or -1>, "httpOnly": true,
#                  "secure": true, "sameSite": "None"}, ...]
#   }
# Override the path per-county via config key ``cookie_jar``.
_DEFAULT_COOKIE_JAR = "~/.titlepro/schneider_cookies.json"

# qPublic search panels carry a stable SearchIntent attribute even though the
# ctlBodyPane$ctlNN$ index shifts per tenant. Map our logical search -> intent.
_INTENT_OWNER = "OwnerName"
_INTENT_ADDRESS = "Address"
_INTENT_PARCEL = "ParcelID"
_INTENT_LEGAL = "LegalDesc"

_NO_RESULTS_RE = re.compile(
    r"No results match your search criteria|No Global Search Results", re.I
)


def _money(s: str) -> int:
    m = _MONEY_RE.search(s or "")
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


class QPublicSchneiderPA(AbstractPropertyAppraiser):
    """Multi-tenant qPublic / Schneider Geospatial PA adapter (config-keyed by app_id)."""

    SOURCE_LABEL = "County Property Appraiser (qPublic)"
    LIVE_PLATFORM = "qpublic_schneider_pa_http"

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "")
        self.county_name = self.config.get("county_name", "")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.app_id = str(self.config.get("app_id", "")).strip()
        self.host = (self.config.get("qpublic_host") or _DEFAULT_HOST).strip()
        self.impersonate = self.config.get("impersonate", _DEFAULT_IMPERSONATE)
        self.cookie_jar_path = self.config.get("cookie_jar", _DEFAULT_COOKIE_JAR)
        self.base_url = f"https://{self.host}/Application.aspx"
        self.search_url = f"{self.base_url}?AppID={self.app_id}&PageType=Search"

    # ------------------------------------------------------------------ net
    def _session(self):
        from curl_cffi import requests as cffi  # local import; optional dep
        session = cffi.Session(impersonate=self.impersonate, timeout=30)
        self._load_cookie_jar(session)
        return session

    def _load_cookie_jar(self, session) -> int:
        """Load a Cloudflare-clearance cookie jar into ``session`` if present.

        Returns the count of cookies applied (0 = jar absent/empty/unreadable).
        Fail-soft: a missing or malformed jar never raises and never alters
        behaviour vs. having no jar — so this is a pure no-op until a jar is
        minted. See ``_DEFAULT_COOKIE_JAR`` for the expected path + format.
        """
        import json
        import os

        path = os.path.expanduser(self.cookie_jar_path or "")
        if not path or not os.path.isfile(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return 0
        cookies = data.get("cookies") if isinstance(data, dict) else data
        if not isinstance(cookies, list):
            return 0
        applied = 0
        for c in cookies:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            try:
                session.cookies.set(
                    name, value,
                    domain=c.get("domain") or f".{self.host}",
                    path=c.get("path", "/"),
                )
                applied += 1
            except Exception:
                continue
        return applied

    @staticmethod
    def _hidden(html: str, name: str) -> str:
        m = (
            re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
            or re.search(r'value="([^"]*)"[^>]*name="%s"' % re.escape(name), html)
        )
        return m.group(1) if m else ""

    @staticmethod
    def discover_panels(html: str) -> Dict[str, Tuple[str, str]]:
        """Map SearchIntent -> (event_target, field_prefix).

        Walks the search-panel ``<a … SearchIntent="…" … __doPostBack('…')>``
        buttons. The ctlBodyPane index shifts per tenant, so this discovery is
        what makes ONE adapter work across every county. ``field_prefix`` is the
        button target minus ``$btnSearch`` (e.g. ``ctlBodyPane$ctl01$ctl01``),
        to which the text field name (``$txtName`` / ``$txtAddress`` /
        ``$txtParcelID``) is appended.
        """
        out: Dict[str, Tuple[str, str]] = {}
        for m in re.finditer(
            r'<a[^>]*SearchIntent="([^"]+)"[^>]*__doPostBack\((?:&#39;|\')'
            r"([^&']+)(?:&#39;|')",
            html,
        ):
            intent, target = m.group(1), m.group(2)
            prefix = target.rsplit("$btnSearch", 1)[0]
            out.setdefault(intent, (target, prefix))
        return out

    def _post_search(self, session, html: str, intent: str, field_suffix: str,
                     value: str):
        """POST a __doPostBack search for the given SearchIntent panel."""
        panels = self.discover_panels(html)
        if intent not in panels:
            return None
        target, prefix = panels[intent]
        form = {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": self._hidden(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": self._hidden(html, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": self._hidden(html, "__EVENTVALIDATION"),
            f"{prefix}${field_suffix}": value,
        }
        return session.post(self.search_url, data=form, allow_redirects=True)

    # ---------------------------------------------------------- result links
    @staticmethod
    def _first_detail_href(html: str) -> Optional[str]:
        m = re.search(r'href="([^"]*PageTypeID=4[^"]*KeyValue=[^"]+)"', html) \
            or re.search(r'href="([^"]*KeyValue=[^"]+)"', html)
        return m.group(1).replace("&amp;", "&") if m else None

    def _abs_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"https://{self.host}{href}"
        return f"https://{self.host}/{href}"

    @staticmethod
    def _is_detail_page(url: str, html: str) -> bool:
        return ("PageTypeID=4" in (url or "") and "KeyValue=" in (url or "")) \
            or "Parcel Summary" in html

    # -------------------------------------------------------------- parsing
    @staticmethod
    def _soup(html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    @classmethod
    def _text_lines(cls, html: str) -> List[str]:
        return [ln.strip() for ln in cls._soup(html).get_text("\n").splitlines()
                if ln.strip()]

    @staticmethod
    def _value_after(lines: List[str], label: str,
                     stop: Tuple[str, ...] = ()) -> str:
        """Return the first non-empty line after an exact-or-startswith label."""
        for i, ln in enumerate(lines):
            if ln == label or ln.startswith(label):
                for j in range(i + 1, len(lines)):
                    if not lines[j]:
                        continue
                    if stop and lines[j] in stop:
                        return ""
                    return lines[j]
        return ""

    def parse_grid_html(self, html: str) -> List[Dict[str, str]]:
        """Parse a search results grid into a list of row dicts.

        Each dict carries at least ``parcel_id`` + ``key_value`` (the KeyValue
        used to build the detail URL) plus owner / address / city / legal when
        present. Also carries ``detail_href`` — the full session-bound href
        (``PageTypeID=4&PageID=...&Q=...&KeyValue=...``) from the grid link,
        which is required for Beacon/some qPublic tenants whose detail page
        returns 500 when the simplified ``PageType=Details`` form is used.
        Returns [] for a no-results page.
        """
        # Guard: "No Global Search Results" appears in the qPublic nav header on
        # EVERY page including genuine result pages. Only treat it as no-results
        # when the page also has no KeyValue links (true empty results page).
        _has_results_data = "KeyValue=" in html
        if _NO_RESULTS_RE.search(html) and not _has_results_data:
            return []
        soup = self._soup(html)
        rows: List[Dict[str, str]] = []
        for tbl in soup.find_all("table"):
            if "KeyValue=" not in str(tbl):
                continue
            trs = tbl.find_all("tr")
            if not trs:
                continue
            headers = [th.get_text(" ", strip=True) for th in trs[0].find_all(["th", "td"])]
            hidx = {h.lower(): i for i, h in enumerate(headers)}
            for tr in trs[1:]:
                # qPublic rows mix <th> (row-header cell) + <td>; collect both so
                # the column index lines up with the all-<th> header row.
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if not cells:
                    continue
                kv = ""
                detail_href = ""
                a = tr.find("a", href=re.compile("KeyValue="))
                if a:
                    raw_href = a.get("href", "")
                    m = re.search(r"KeyValue=([^&\"']+)", raw_href)
                    if m:
                        kv = m.group(1)
                    # Prefer the full PageTypeID=4 href (session-bound) over the
                    # simplified PageType=Details form, which returns 500 on
                    # Beacon/some qPublic tenants.
                    if "PageTypeID=4" in raw_href:
                        detail_href = raw_href.replace("&amp;", "&")

                def col(name: str) -> str:
                    i = hidx.get(name.lower())
                    return cells[i] if i is not None and i < len(cells) else ""

                row = {
                    "parcel_id": col("Parcel ID") or col("Parcel Number") or kv,
                    "key_value": kv,
                    "detail_href": detail_href,
                    "owner": col("Owner"),
                    "address": col("Property Address") or col("Location Address"),
                    "city": col("City"),
                    "legal": col("Legal Description"),
                    "last_sale": col("Last Sale"),
                }
                if row["parcel_id"] or row["key_value"]:
                    rows.append(row)
            if rows:
                break
        return rows

    def parse_detail_html(self, html: str) -> PropertyAppraiserResult:
        """Parse a qPublic parcel detail page -> PropertyAppraiserResult.

        Public + side-effect-free so unit tests feed captured fixtures.
        """
        res = PropertyAppraiserResult()
        # Guard: "No Global Search Results" is emitted by the qPublic nav header on
        # EVERY page (including valid parcel pages). Only treat it as a true no-results
        # if the page also has no parcel data signal ("Parcel Summary", "Parcel Number",
        # or "KeyValue=" in the URL/body).
        _has_parcel_data = (
            "Parcel Summary" in html
            or "Parcel Number" in html
            or "KeyValue=" in html
        )
        if _NO_RESULTS_RE.search(html) and not _has_parcel_data:
            res.status = "PA_NO_RESULTS"
            res.fetched_at = datetime.now().isoformat()
            return res

        lines = self._text_lines(html)

        res.apn = (
            self._value_after(lines, "Parcel ID")
            or self._value_after(lines, "ParcelID")
            or self._value_after(lines, "Parcel Number")
        )
        res.folio = res.apn

        # Location Address spans the street line + a city/zip line.
        # Some tenants use "Location Address(es)" (Levy) or "Site Location" (Report pages).
        situs_parts: List[str] = []
        for i, ln in enumerate(lines):
            if ln in ("Location Address", "Location Address(es)", "Site Location"):
                for j in range(i + 1, min(i + 3, len(lines))):
                    nxt = lines[j]
                    if nxt in ("Brief Tax Description*", "Brief Tax Description",
                               "Owner Information", "Property Use Code",
                               "City", "Zip", "Tax District", "Legal Description"):
                        break
                    situs_parts.append(nxt)
                break
        res.situs_address = " ".join(situs_parts).strip()

        # Legal description: standard pages use "Brief Tax Description*"; Report pages
        # use "Legal Description".
        res.legal_description = (
            self._value_after(lines, "Brief Tax Description",
                              stop=("Owner Information", "Property Use Code"))
            or self._value_after(lines, "Legal Description",
                                 stop=("Acres", "Owner Information", "Owner", "Property Use Code"))
        )

        # Owner Information — first line is the primary owner; subsequent lines
        # are the mailing address until the next section header.
        # Report pages use "Owner" (no "Information" suffix).
        owner, co_owners, mailing = self._parse_owner_block(lines)
        if not owner:
            # Report page fallback: "Owner" label followed by the owner name
            owner, co_owners, mailing = self._parse_owner_block_report(lines)
        res.owner_of_record = owner
        res.co_owners = co_owners
        res.mailing_address = mailing

        # Homestead: "YES, Granted 2020" / "NO".
        hs = self._value_after(lines, "Homestead")
        res.homestead_active = hs.upper().startswith("YES")

        yb = (self._value_after(lines, "Year Built")
              or self._value_after(lines, "Actual Year Built"))
        res.year_built = int(yb) if yb.isdigit() else 0

        res.just_value = self._first_value_for(lines, self._is_just_label)
        res.assessed_value = self._first_value_for(lines, self._is_assessed_label)

        res.sale_history = self._parse_sales(html)

        # Build canonical source URL when we can recover the KeyValue.
        m = re.search(r'KeyValue=([0-9A-Za-z\-\./]+)', html)
        if m:
            res.source_url = (f"{self.base_url}?AppID={self.app_id}"
                              f"&PageType=Details&KeyValue={m.group(1)}")

        res.status = "PA_SUCCESS" if res.apn else "PA_NO_RESULTS"
        res.fetched_at = datetime.now().isoformat()
        return res

    # ---- detail sub-parsers ------------------------------------------------
    _SECTION_HEADERS = (
        "Land Information", "Owner Information", "Valuation", "Values", "Sales",
        "Building Information", "Photos", "Sketches", "Map", "Land Use",
        "Area Sales Report", "Property Use Code",
    )
    # Sub-labels some tenants emit inside the Owner block before the real name.
    # "Owner Name" appears as a visible label in Levy/some Beacon tenants.
    _OWNER_SUBLABELS = ("Primary Owner", "Secondary Owner", "Owner Name",
                        "Owner(s)", "Owners", "Mailing Address")

    @classmethod
    def _parse_owner_block(cls, lines: List[str]) -> Tuple[str, List[str], str]:
        owner = ""
        co_owners: List[str] = []
        mailing_parts: List[str] = []
        for i, ln in enumerate(lines):
            if ln != "Owner Information":
                continue
            block: List[str] = []
            for j in range(i + 1, len(lines)):
                if lines[j] in cls._SECTION_HEADERS:
                    break
                if lines[j] in cls._OWNER_SUBLABELS:
                    continue  # skip "Primary Owner" / "Secondary Owner" labels
                block.append(lines[j])
            # Heuristic: name lines have no digits; mailing-address lines do
            # (street number / zip). Names come first.
            names: List[str] = []
            for b in block:
                if re.search(r"\d", b):
                    mailing_parts.append(b)
                elif not mailing_parts:
                    names.append(b)
                else:
                    mailing_parts.append(b)
            if names:
                owner = names[0]
                co_owners = names[1:]
            break
        return owner, co_owners, " ".join(mailing_parts).strip()

    @classmethod
    def _parse_owner_block_report(cls, lines: List[str]) -> Tuple[str, List[str], str]:
        """Fallback owner parser for qPublic Report pages.

        Report pages use the label "Owner" (not "Owner Information") followed
        immediately by the owner name, then the mailing address lines.
        """
        owner = ""
        co_owners: List[str] = []
        mailing_parts: List[str] = []
        # Report-page section terminators (anything that follows the owner block)
        _REPORT_STOPS = ("Map", "Land", "Building Data", "Valuation", "Sales",
                         "Exempt", "Homestead", "Tax District", "Property Usage",
                         "Line #", "Actual Year Built")
        for i, ln in enumerate(lines):
            if ln != "Owner":
                continue
            block: List[str] = []
            for j in range(i + 1, len(lines)):
                if lines[j] in _REPORT_STOPS:
                    break
                if lines[j] in cls._OWNER_SUBLABELS:
                    continue  # skip "Owner Name", "Mailing Address", etc.
                block.append(lines[j])
            names: List[str] = []
            for b in block:
                if re.search(r"\d", b):
                    mailing_parts.append(b)
                elif not mailing_parts:
                    names.append(b)
                else:
                    mailing_parts.append(b)
            if names:
                owner = names[0]
                co_owners = names[1:]
            break
        return owner, co_owners, " ".join(mailing_parts).strip()

    @staticmethod
    def _is_just_label(label: str) -> bool:
        u = label.upper()
        return "JUST" in u and "VALUE" in u and "AGRICULTUR" not in u

    @staticmethod
    def _is_assessed_label(label: str) -> bool:
        u = label.upper()
        return "ASSESSED VALUE" in u

    @classmethod
    def _first_value_for(cls, lines: List[str], pred) -> int:
        """First $-money line after the first label matching predicate ``pred``.

        Valuation tables render multi-year, newest-first; index 0 (the line
        right after the label) is the current year.
        """
        for i, ln in enumerate(lines):
            if pred(ln):
                for j in range(i + 1, len(lines)):
                    if re.match(r"^-?\$?\(?[\d,]+\)?$", lines[j]):
                        return _money(lines[j])
                    # stop if we hit another label before any money
                    if lines[j] and not lines[j].startswith(("=", "-", "+")):
                        break
        return 0

    def _parse_sales(self, html: str) -> List[SaleHistoryEntry]:
        """Parse the Sales <table> (newest-first) into SaleHistoryEntry list."""
        soup = self._soup(html)
        for tbl in soup.find_all("table"):
            txt = tbl.get_text(" ", strip=True)
            if "Sale Date" not in txt or "Sale Price" not in txt:
                continue
            trs = tbl.find_all("tr")
            if not trs:
                continue
            headers = [th.get_text(" ", strip=True) for th in trs[0].find_all(["th", "td"])]
            hidx = {h.lower(): i for i, h in enumerate(headers)}
            sales: List[SaleHistoryEntry] = []
            for tr in trs[1:]:
                # Data rows put Sale Date in a <th> + the rest in <td>; collect
                # both so columns line up with the all-<th> header.
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if not cells or not any(cells):
                    continue

                def col(name: str) -> str:
                    i = hidx.get(name.lower())
                    return cells[i] if i is not None and i < len(cells) else ""

                date = col("Sale Date")
                if not date:
                    continue
                book = col("Deed Book")
                page = col("Deed Page")
                bp = f"{book}/{page}" if (book or page) else ""
                sales.append(SaleHistoryEntry(
                    sale_date=date,
                    sale_price=_money(col("Sale Price")),
                    deed_book_page=bp,
                    deed_type=self._deed_type_code(col("Instrument")),
                    grantor=col("Grantor"),
                    grantee=col("Grantee"),
                    qualified=col("Sale Qualification").upper().startswith("QUALIF"),
                ))
            return sales
        return []

    @staticmethod
    def _deed_type_code(instrument: str) -> str:
        """Normalize qPublic's spelled-out instrument to a short deed code."""
        u = (instrument or "").upper()
        mapping = [
            ("WARRANTY", "WD"),
            ("QUIT", "QCD"),
            ("QUITCLAIM", "QCD"),
            ("SPECIAL WARRANTY", "SWD"),
            ("TAX DEED", "TXD"),
            ("CERTIFICATE OF TITLE", "CT"),
            ("PERSONAL REPRESENTATIVE", "PRD"),
            ("TRUSTEE", "TRD"),
        ]
        for needle, code in mapping:
            if needle in u:
                return code
        return instrument or ""

    # --------------------------------------------------------- entry points
    def _fetch_detail_by_keyvalue(self, session, key_value: str,
                                   detail_href: str = "") -> PropertyAppraiserResult:
        """Fetch a parcel detail page.

        ``detail_href`` is the full session-bound href from the grid
        (``/Application.aspx?AppID=...&LayerID=...&PageTypeID=4&PageID=...&Q=...&KeyValue=...``).
        When provided, it is used as-is (absolute URL) because some Beacon /
        qPublic tenants return HTTP 500 on the simplified
        ``?AppID=<id>&PageType=Details&KeyValue=<kv>`` form. Falls back to
        the simplified form when no href is supplied (works for most tenants).
        """
        if detail_href:
            url = self._abs_url(detail_href)
        else:
            url = (f"{self.base_url}?AppID={self.app_id}&PageType=Details"
                   f"&KeyValue={key_value}")
        r = session.get(url, allow_redirects=True)
        if r.status_code != 200:
            if detail_href:
                # Fallback: try the simplified form as a last resort
                url2 = (f"{self.base_url}?AppID={self.app_id}&PageType=Details"
                        f"&KeyValue={key_value}")
                r2 = session.get(url2, allow_redirects=True)
                if r2.status_code == 200:
                    return self.parse_detail_html(r2.text)
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"qPublic detail returned {r.status_code} for {key_value} "
                      f"({self.county_id})",
                fetched_at=datetime.now().isoformat(),
            )
        return self.parse_detail_html(r.text)

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        if not self.app_id:
            return self._config_error("APN")
        try:
            session = self._session()
            g = session.get(self.search_url, allow_redirects=True)
            r = self._post_search(session, g.text, _INTENT_PARCEL, "txtParcelID",
                                  (apn or "").strip())
            if r is None:
                return PropertyAppraiserResult(
                    status="PA_FAILED",
                    notes=f"qPublic ParcelID search panel not found ({self.county_id})",
                    fetched_at=datetime.now().isoformat(),
                )
            # Exact parcel usually lands straight on the detail page.
            if self._is_detail_page(str(r.url), r.text):
                return self.parse_detail_html(r.text)
            return self._resolve_from_grid(session, r.text, expect_unique=True,
                                           query=apn)
        except Exception as exc:  # fail soft per base contract
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"qPublic APN lookup error ({self.county_id}): {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        if not self.app_id:
            return self._config_error("address")
        try:
            session = self._session()
            g = session.get(self.search_url, allow_redirects=True)
            r = self._post_search(session, g.text, _INTENT_ADDRESS, "txtAddress",
                                  (address or "").strip())
            if r is None:
                return PropertyAppraiserResult(
                    status="PA_FAILED",
                    notes=f"qPublic Address search panel not found ({self.county_id})",
                    fetched_at=datetime.now().isoformat(),
                )
            if self._is_detail_page(str(r.url), r.text):
                return self.parse_detail_html(r.text)
            return self._resolve_from_grid(session, r.text, expect_unique=False,
                                           query=address)
        except Exception as exc:
            return PropertyAppraiserResult(
                status="PA_FAILED",
                notes=f"qPublic address lookup error ({self.county_id}): {exc}",
                fetched_at=datetime.now().isoformat(),
            )

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        if not self.app_id:
            return [self._config_error("owner-name")]
        try:
            session = self._session()
            g = session.get(self.search_url, allow_redirects=True)
            r = self._post_search(session, g.text, _INTENT_OWNER, "txtName",
                                  (owner_name or "").strip())
            if r is None:
                return []
            if self._is_detail_page(str(r.url), r.text):
                return [self.parse_detail_html(r.text)]
            rows = self.parse_grid_html(r.text)
            out: List[PropertyAppraiserResult] = []
            for row in rows[:25]:  # cap diagnostic fan-out
                kv = row.get("key_value")
                if kv:
                    out.append(self._fetch_detail_by_keyvalue(
                        session, kv, detail_href=row.get("detail_href", "")))
            return out
        except Exception:
            return []

    # ------------------------------------------------------------- helpers
    def _resolve_from_grid(self, session, html: str, expect_unique: bool,
                           query: str) -> PropertyAppraiserResult:
        rows = self.parse_grid_html(html)
        if not rows:
            return PropertyAppraiserResult(
                status="PA_NO_RESULTS",
                notes=f"qPublic search returned no rows for {query!r} ({self.county_id})",
                fetched_at=datetime.now().isoformat(),
            )

        def _fetch(row: Dict[str, str]) -> PropertyAppraiserResult:
            return self._fetch_detail_by_keyvalue(
                session, row["key_value"],
                detail_href=row.get("detail_href", ""))

        if expect_unique and len(rows) > 1:
            # Try to find an exact parcel match; else AMBIGUOUS.
            q = re.sub(r"[^0-9A-Za-z]", "", (query or "")).upper()
            exact = [r for r in rows
                     if re.sub(r"[^0-9A-Za-z]", "", r["parcel_id"]).upper() == q]
            if len(exact) == 1:
                rows = exact
            else:
                res = _fetch(rows[0])
                res.status = "PA_AMBIGUOUS"
                res.notes = (f"qPublic returned {len(rows)} candidates for {query!r} "
                             f"({self.county_id}); first candidate detailed. "
                             f"Parcels: {', '.join(r['parcel_id'] for r in rows[:8])}")
                return res
        if not expect_unique and len(rows) > 1:
            res = _fetch(rows[0])
            if res.status == "PA_SUCCESS":
                res.status = "PA_AMBIGUOUS"
                res.notes = (f"qPublic returned {len(rows)} address candidates for "
                             f"{query!r} ({self.county_id}); first candidate detailed. "
                             f"Parcels: {', '.join(r['parcel_id'] for r in rows[:8])}")
            return res
        return _fetch(rows[0])

    def _config_error(self, kind: str) -> PropertyAppraiserResult:
        return PropertyAppraiserResult(
            status="PA_FAILED",
            notes=(f"qpublic_schneider_pa_http {kind} lookup: missing app_id in "
                   f"config for county_id={self.county_id!r}"),
            source_url=self.base_url,
            fetched_at=datetime.now().isoformat(),
        )
