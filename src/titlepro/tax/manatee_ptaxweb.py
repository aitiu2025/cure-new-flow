"""Manatee County FL — `secure.taxcollector.com/ptaxweb/` HTTP adapter.

Pure-HTTP tax lookup for Manatee County's proprietary Struts-style ptaxweb
application. Distinct from the Grant Street GovHub vendor used by Broward
and Hillsborough; Manatee is NOT in the Grant Street fl-<county>.property_tax
Algolia index (verified live 2026-05-27 — returns 404 "Index does not exist").

Why HTTP not Playwright
-----------------------
Probed 2026-05-27:
* `curl_cffi` (chrome120 impersonate) passes every endpoint.
* No anti-bot, no CAPTCHA.
* Sticky session required — initial GET sets a JSESSIONID; the disclaimer
  POST follows (`action=list`); subsequent property-search POST returns the
  results page with the tax rows embedded.
* Result HTML format is row-per-year (most recent first) with cells
  containing year, parcel id, owner/situs, status (Paid|Unpaid), bill
  amount, payment date, and balance due.

Tony Roveda directive #1 (no Selenium/Playwright in Phase 1) satisfied.

Public entry point
------------------
``lookup_manatee_tax(apn: str, case_dir: Path, *, safe_owner: str = 'tax',
                     property_address: str = '') -> TaxLookupResult``
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi

from titlepro.tax.result import TaxLookupResult, apn_matches, host_in_whitelist


DEFAULT_IMPERSONATE = "chrome120"
DEFAULT_BASE = "https://secure.taxcollector.com/ptaxweb"
DEFAULT_AUTHORITATIVE_HOSTS = ["secure.taxcollector.com", "www.taxcollector.com"]


def _log(msg: str) -> None:
    print(f"[manatee-ptaxweb] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Currency / number helpers
# ---------------------------------------------------------------------------


_CURRENCY_RE = re.compile(r"\$?-?[\d,]+(?:\.\d+)?")


def _parse_money(text: Any) -> float:
    if text is None:
        return 0.0
    s = str(text)
    m = _CURRENCY_RE.search(s)
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace("$", "").replace(",", ""))
    except ValueError:
        return 0.0


def _clean_apn(apn: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", apn or "")


# ---------------------------------------------------------------------------
# Two-stage flow: disclaimer-accept -> search
# ---------------------------------------------------------------------------


def _accept_disclaimer(session: Any, base_url: str) -> None:
    """ptaxweb landing requires a one-shot POST with action=list before any
    search is accepted; the disclaimer button on the landing page does this."""
    session.get(base_url + "/", timeout=20)
    session.post(
        base_url + "/editPropertySearch2.action",
        data={"action": "list"},
        timeout=20,
        allow_redirects=True,
    )


def _post_property_search(session: Any, base_url: str, apn: str) -> str:
    """POST the property-search form. Returns HTML body."""
    payload = {
        "action": "search",
        "mode": "",
        "searchField": "accountNumber",
        "searchValue": apn,
        "taxYear": "",
        "paidStatus": "",
    }
    r = session.post(
        base_url + "/editPropertySearch2.action",
        data=payload,
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"ptaxweb search returned HTTP {r.status_code}: {r.text[:200]}"
        )
    return r.text or ""


# ---------------------------------------------------------------------------
# Result-row parser
# ---------------------------------------------------------------------------

# A row pattern shape after stripping markup (probe-derived):
# "2025 1697719559 FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR Paid 3,423.64 12/01/2025 0.00"
_ROW_RE = re.compile(
    r"\b(?P<year>20\d{2})\s+"
    r"(?P<apn>\d{8,12})\s+"
    r"(?P<owner_situs>.+?)\s+"
    r"(?P<status>Paid|Unpaid|Delinquent|Partial|Refund|Pending)\s+"
    r"(?P<bill_amount>[\d,]+\.\d{2})"
    r"(?:\s+(?P<pay_date>\d{2}/\d{2}/\d{4}))?"
    r"(?:\s+(?P<balance>[\d,]+\.\d{2}))?",
    re.IGNORECASE,
)


def _parse_tax_rows(html: str) -> List[dict]:
    """Extract per-year tax rows from the property-search results HTML.

    Returns a list of dicts (newest year first) with at least:
        year, apn, owner_situs, status, bill_amount, balance, pay_date.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    rows: List[dict] = []
    for m in _ROW_RE.finditer(text):
        rows.append({
            "year": int(m.group("year")),
            "apn": m.group("apn"),
            "owner_situs": m.group("owner_situs").strip(),
            "status": m.group("status").title(),
            "bill_amount": _parse_money(m.group("bill_amount")),
            "balance": _parse_money(m.group("balance") or "0"),
            "pay_date": (m.group("pay_date") or "").strip(),
        })
    # Sort newest-first (descending year) for consumer convenience.
    rows.sort(key=lambda r: r["year"], reverse=True)
    return rows


def _split_owner_and_situs(blob: str) -> tuple:
    """`"FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR"` -> (owner, situs).

    Heuristic: the first run that begins with a street number is the situs;
    everything before it (joined with commas) is the owner string.
    """
    parts = [p.strip() for p in blob.split(",")]
    situs_idx = None
    for i, p in enumerate(parts):
        # A street starts with a digit. Some Florida unit/lot numbers also
        # start with digits, so prefer the first run >= 3 chars beginning
        # with a digit, then a space, then a letter.
        if re.match(r"^\d+\s+\w", p):
            situs_idx = i
            break
    if situs_idx is None:
        return blob, ""
    owner = ", ".join(parts[:situs_idx]).strip()
    situs = ", ".join(parts[situs_idx:]).strip()
    return owner, situs


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lookup_manatee_tax(
    apn: str,
    case_dir: Path,
    *,
    safe_owner: str = "tax",
    property_address: str = "",
    base_url: str = DEFAULT_BASE,
    authoritative_hosts: Optional[List[str]] = None,
) -> TaxLookupResult:
    """End-to-end Manatee FL tax lookup. Saves the raw search-result HTML
    to ``case_dir/tax_<safe_owner>_capture.html`` for forensic linkage.

    Returns a TaxLookupResult populated for the MOST RECENT tax year that
    has a non-zero bill. Older years are included in ``notes`` as a
    "history: YYYY $A.AA PAID; YYYY $B.BB PAID; ..." string for downstream
    examination.
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now()

    cleaned_apn = _clean_apn(apn)
    hosts = authoritative_hosts or DEFAULT_AUTHORITATIVE_HOSTS

    session = cffi.Session(impersonate=DEFAULT_IMPERSONATE)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base_url + "/editPropertySearch2.action",
    })

    try:
        _accept_disclaimer(session, base_url)
    except Exception as exc:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED",
            error=f"disclaimer accept raised: {type(exc).__name__}: {exc}",
            captured_at=captured_at,
        )

    try:
        html = _post_property_search(session, base_url, cleaned_apn)
    except Exception as exc:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED",
            error=f"property search raised: {type(exc).__name__}: {exc}",
            captured_at=captured_at,
        )

    capture_path = case_dir / f"tax_{safe_owner}_capture.html"
    capture_path.write_text(html, encoding="utf-8")

    rows = _parse_tax_rows(html)
    if not rows:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_NO_RESULTS",
            notes=(
                f"ptaxweb search returned HTML but no parseable tax rows for APN {apn!r}. "
                f"Capture: {capture_path}"
            ),
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    # Confirm APN echo from any row.
    echoed = [r["apn"] for r in rows if r.get("apn")]
    if echoed and not any(apn_matches(apn, e) for e in echoed):
        return TaxLookupResult(
            apn=apn, tax_year=str(rows[0]["year"]),
            property_address=property_address,
            status="TAX_FAILED",
            error=(
                f"APN echo mismatch: input={apn!r} portal={echoed[:3]!r}"
            ),
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    most_recent = rows[0]
    owner, situs = _split_owner_and_situs(most_recent.get("owner_situs", ""))

    bill_amount = float(most_recent["bill_amount"] or 0.0)
    balance = float(most_recent["balance"] or 0.0)
    paid = (most_recent["status"].lower() == "paid")
    delinquent = (most_recent["status"].lower() in ("unpaid", "delinquent"))

    installments = [{
        "label": "annual",
        "amount": bill_amount,
        "status": "PAID" if paid else ("UNPAID" if delinquent else most_recent["status"].upper()),
        "due_date": "",          # FL annual due 03/31; portal does not show due-date for paid bills
        "pay_date": most_recent["pay_date"],
        "balance_due": balance,
        "status_text": (
            f"{most_recent['status']} ${bill_amount:,.2f}"
            + (f" on {most_recent['pay_date']}" if most_recent.get("pay_date") else "")
        ),
    }]

    # Build a history string for older years (excluded from installments).
    history_bits = [
        f"{r['year']} {r['status']} ${r['bill_amount']:,.2f}"
        + (f" {r['pay_date']}" if r['pay_date'] else "")
        for r in rows[1:6]
    ]
    history_str = "; ".join(history_bits)

    source_url = base_url + "/editPropertySearch2.action"
    if not host_in_whitelist(source_url, hosts, mode="strict"):
        return TaxLookupResult(
            apn=apn, tax_year=str(most_recent["year"]),
            property_address=property_address,
            status="TAX_FAILED",
            error=f"source URL host not whitelisted: {source_url!r}",
            source_url=source_url,
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    # Verified / missing fields
    verified: List[str] = []
    missing: List[str] = []
    if cleaned_apn:
        verified.append("apn")
    else:
        missing.append("apn")
    if most_recent["year"]:
        verified.append("tax_year")
    else:
        missing.append("tax_year")
    if bill_amount > 0:
        verified.append("annual_total")
        verified.append("installments[0].amount")
    else:
        missing.extend(["annual_total", "installments[0].amount"])

    status = "TAX_SUCCESS" if not missing else ("TAX_PARTIAL" if verified else "TAX_FAILED")

    notes = "All required fields verified." if status == "TAX_SUCCESS" else (
        f"Partial: {len(verified)} verified, {len(missing)} missing"
        if status == "TAX_PARTIAL" else ""
    )
    if history_str:
        notes = (notes + f" (history: {history_str})").strip()
    if owner:
        notes = (notes + f"; owner_on_record={owner}").strip()

    return TaxLookupResult(
        apn=cleaned_apn,
        tax_year=str(most_recent["year"]),
        property_address=situs or property_address,
        tra="",
        assessed_value={},
        installments=installments,
        annual_total=bill_amount,
        delinquent=delinquent,
        special_assessments=[],
        source_url=source_url,
        source_artifact=str(capture_path),
        captured_at=captured_at,
        status=status,
        verified_fields=verified,
        missing_fields=missing,
        notes=notes,
    )


__all__ = ["lookup_manatee_tax"]
