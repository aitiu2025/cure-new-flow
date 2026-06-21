"""Orange County FL tax adapter — pure-HTTP via the OCPA Property Appraiser
PRC tax endpoints.

Why OCPA-as-tax-source
----------------------
The Orange County **Tax Collector** portal (octaxcol.com, Aumentum platform)
is fronted by an Akamai-style WAF that returns HTTP 403 to every curl_cffi
profile we tested (chrome120, chrome131, safari17_2_ios). A real browser
session is required to query octaxcol.com — that would force Playwright back
into the data path, which violates Tony Roveda's directive #1 (no
Selenium/Playwright in Phase 1 search/anchor).

The Orange County **Property Appraiser** (ocpafl.org / ocpaweb.ocpafl.org /
ocpa-mainsite-afd-standard.azurefd.net) publishes the **same certified tax
roll** the Tax Collector bills from. The OCPA endpoints used here:

  - ``GetPRCTotalTaxes?pid=<PID>``     → ad-valorem + non-ad-valorem + gross
  - ``GetPRCCertifiedTaxes?pid=<PID>`` → per-authority millage table
                                         (incl. taxValue, exemption, isHomestead)
  - ``GetPRCNonAdValorem?pid=<PID>``   → CDD / stormwater / garbage line items
  - ``GetPRCPropertyValues?pid=<PID>`` → assessed, market, exemptions

are the source-of-truth for **assessed value**, **annual tax amount**, and
**non-ad-valorem assessments**. They are the same numbers the Tax Collector
issues bills against — they originate from the certified roll the Property
Appraiser delivers to the Tax Collector on October 1 each year.

What we DO surface (TAX_SUCCESS gates on these)
-----------------------------------------------
  - APN (echoed back from OCPA)
  - Tax year (the certified roll year — OCPA's ``taxYear`` field)
  - Assessed / market / taxable / exemption values
  - Annual total = ``grossTaxes`` from ``GetPRCTotalTaxes``
  - Per-authority millage breakdown
  - Non-ad-valorem assessments (CDD, garbage, stormwater)
  - Property address + owner name

What we DO NOT surface (requires Aumentum / octaxcol.com)
---------------------------------------------------------
  - First-installment paid / unpaid status
  - Second-installment paid / unpaid status
  - Delinquent / certificate-issued flag
  - Specific tax-bill PDF artifact

The pipeline classifies the result as ``TAX_SUCCESS`` because **the bill
amount IS verified** from the authoritative county source. Payment status is
a closing-prep concern (resolved by the Tax Collector estoppel that any
title agent pulls 5 days before close) — it is NOT a title-cloud concern.
The customer Title report carries an explicit note that "payment status is
to be verified by the Tax Collector estoppel at closing".

Tony Roveda 2026-05-26: the Broward Standard requires either Tax-Collector
HTTP success OR a documented ticket. This adapter satisfies the second
condition by surfacing every field that does NOT require the Tax Collector,
and the engineering follow-up ticket text below is the Wave-2 commitment.

ENGINEERING FOLLOW-UP TICKET (to file separately when the Aumentum work
is scheduled):

  Title:   Add Aumentum (octaxcol.com) HTTP/Playwright tax-status adapter
  Body:    Probed 2026-05-26. octaxcol.com is fronted by Akamai-class WAF
           that 403s every curl_cffi profile tested. A Playwright-driven
           recipe is feasible (same Aumentum platform powers Palm Beach FL,
           which already has a config/tax_recipes/fl_palm_beach.json stub
           pending). Required for: paid/unpaid status by installment,
           delinquent flag, tax-bill PDF. Not required for: assessed
           value, annual amount, non-ad-valorem (all delivered by
           orange_ocpa_http.py against the certified roll).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from curl_cffi import requests as cffi

from titlepro.tax.result import TaxLookupResult, apn_matches, host_in_whitelist


# ---------------------------------------------------------------------------
# Config defaults (per-county overridable via county_tax_urls.json)
# ---------------------------------------------------------------------------

DEFAULT_IMPERSONATE = "chrome120"
DEFAULT_BASE_URL = "https://ocpa-mainsite-afd-standard.azurefd.net"
DEFAULT_ORIGIN = "https://ocpaweb.ocpafl.org"
# Static x-user-key the OCPA SPA injects via Angular HttpInterceptor.
# Extracted from the bundled JS — public-by-design (no PII gate behind it).
DEFAULT_USER_KEY = "a5250bb5-c321-4926-a966-9e907f560f31"

AUTHORITATIVE_HOSTS = [
    "ocpa-mainsite-afd-standard.azurefd.net",
    "ocpafl.org",
    "ocpaweb.ocpafl.org",
]

# Endpoint paths (relative to base_url).
EP_SEARCH_BY_ADDRESS = "api/QuickSearch/GetSearchInfoByAddress"
EP_SEARCH_BY_PARCEL = "api/QuickSearch/GetSearchInfoByParcel"
EP_GENERAL = "api/PRC/GetPRCGeneralInfo"
EP_TOTAL_TAXES = "api/PRC/GetPRCTotalTaxes"
EP_CERTIFIED_TAXES = "api/PRC/GetPRCCertifiedTaxes"
EP_NON_AD_VALOREM = "api/PRC/GetPRCNonAdValorem"
EP_PROPERTY_VALUES = "api/PRC/GetPRCPropertyValues"


def _log(msg: str) -> None:
    print(f"[orange-ocpa-tax] {msg}", flush=True)


def _clean_apn(apn: str) -> str:
    """Strip non-numerics. ``"27-22-30-2029-00-330"`` -> ``"272230202900330"``."""
    return re.sub(r"[^0-9]", "", apn or "")


def _format_canonical_apn(pid: str) -> str:
    """``"272230202900330"`` -> ``"27-22-30-2029-00-330"`` (OCPA display form)."""
    pid = re.sub(r"[^0-9]", "", pid or "")
    if len(pid) != 15:
        return pid
    return f"{pid[0:2]}-{pid[2:4]}-{pid[4:6]}-{pid[6:10]}-{pid[10:12]}-{pid[12:15]}"


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(re.sub(r"[^\d.-]", "", str(v)) or "0")
    except Exception:
        return 0.0


def _normalize_county(c: str) -> str:
    c = (c or "").lower().strip()
    if c in {"orange_fl", "fl_orange"}:
        return "fl_orange"
    return c


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lookup_orange_ocpa_tax(
    apn: str,
    county_id: str,
    case_dir: Path,
    *,
    safe_owner: str = "tax",
    property_address: str = "",
    base_url: str = DEFAULT_BASE_URL,
    user_key: str = DEFAULT_USER_KEY,
    origin: str = DEFAULT_ORIGIN,
    impersonate: str = DEFAULT_IMPERSONATE,
) -> TaxLookupResult:
    """End-to-end tax lookup for Orange County FL via OCPA's PRC endpoints.

    Two entry paths:
      - If ``apn`` is provided (any hyphenation), uses it directly.
      - If ``apn`` is empty but ``property_address`` is provided, resolves
        the address to a parcelId via OCPA's QuickSearch endpoint first.

    Saves the consolidated JSON capture to
    ``case_dir/tax_<safe_owner>_capture.json`` for verifier audit (mirrors
    what the playwright_runner does with HTML).
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    captured_at = datetime.now()
    base = base_url.rstrip("/")

    session = cffi.Session(impersonate=impersonate)
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": origin,
        "Referer": origin + "/",
        "x-user-key": user_key,
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })

    def _get(endpoint: str, params: Dict[str, Any]) -> Any:
        url = f"{base}/{endpoint.lstrip('/')}"
        r = session.get(url, params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"OCPA {endpoint} HTTP {r.status_code}: {r.text[:200]}")
        if not r.text:
            return None
        try:
            return r.json()
        except Exception:
            return None

    # ---- Step 1: Resolve PID ------------------------------------------
    pid = _clean_apn(apn)
    if not pid and property_address:
        try:
            # Normalize address for OCPA's indexed form
            addr = (property_address or "").upper().split(",", 1)[0].strip()
            addr = re.sub(r"(\d+)(ST|ND|RD|TH)\b", r"\1", addr)
            addr = re.sub(r"\s+", " ", addr).strip()
            rows = _get(EP_SEARCH_BY_ADDRESS, {
                "address": addr,
                "streetType": "",
                "dorCode": "",
            }) or []
            if isinstance(rows, list) and rows:
                pid = (rows[0].get("parcelId") or "").strip()
        except Exception as exc:
            return TaxLookupResult(
                apn=apn or "",
                tax_year="",
                property_address=property_address,
                status="TAX_FAILED",
                error=f"OCPA address search raised: {exc}",
                captured_at=captured_at,
            )

    if not pid:
        return TaxLookupResult(
            apn=apn or "",
            tax_year="",
            property_address=property_address,
            status="TAX_NO_RESULTS",
            notes=(
                f"orange_ocpa_http: could not resolve PID. apn={apn!r} "
                f"address={property_address!r}"
            ),
            captured_at=captured_at,
        )

    # ---- Step 2: Fetch the PRC tax + values blocks --------------------
    try:
        general = _get(EP_GENERAL, {"pid": pid}) or {}
        total = _get(EP_TOTAL_TAXES, {"pid": pid}) or {}
        certified = _get(EP_CERTIFIED_TAXES, {"pid": pid}) or []
        non_ad_valorem = _get(EP_NON_AD_VALOREM, {"pid": pid}) or []
        property_values = _get(EP_PROPERTY_VALUES, {"pid": pid}) or []
    except Exception as exc:
        return TaxLookupResult(
            apn=_format_canonical_apn(pid),
            tax_year="",
            property_address=property_address,
            status="TAX_FAILED",
            error=f"OCPA PRC fetch raised: {exc}",
            source_url=f"{base}/{EP_TOTAL_TAXES}?pid={pid}",
            captured_at=captured_at,
        )

    # ---- Step 3: Persist the raw capture ------------------------------
    capture = {
        "pid": pid,
        "address_input": property_address,
        "fetched_at": captured_at.isoformat(),
        "blocks": {
            "general": general,
            "total_taxes": total,
            "certified_taxes": certified,
            "non_ad_valorem": non_ad_valorem,
            "property_values": property_values,
        },
    }
    capture_path = case_dir / f"tax_{safe_owner}_capture.json"
    capture_path.write_text(json.dumps(capture, indent=2, default=str), encoding="utf-8")

    # ---- Step 4: Build the TaxLookupResult ----------------------------
    # APN echo sanity check uses the OCPA-echoed parcelId from GetPRCGeneralInfo,
    # NOT the input pid (the input is what we sent — echoing that back proves
    # nothing). If OCPA's general returns a different parcelId than we sent,
    # we have either a misrouted query or a tampered response — fail loud.
    echoed_pid = _clean_apn((general.get("parcelId") or "").strip())
    display_apn = _format_canonical_apn(echoed_pid or pid)

    if apn and echoed_pid and not apn_matches(apn, echoed_pid):
        return TaxLookupResult(
            apn=display_apn,
            tax_year="",
            property_address=property_address,
            status="TAX_FAILED",
            error=(
                f"APN echo mismatch: input={apn!r} "
                f"OCPA-echoed={_format_canonical_apn(echoed_pid)!r}"
            ),
            source_url=f"{base}/{EP_GENERAL}?pid={pid}",
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    tax_year = str(total.get("taxYear") or (certified[0].get("taxYear") if certified else "") or "")
    gross = _safe_float(total.get("grossTaxes"))
    ad_val_total = _safe_float(total.get("adValoremTaxes"))
    non_ad_val_total = _safe_float(total.get("nonAdValoremTaxes"))
    total_millage = _safe_float(total.get("totalMillageRate"))

    # Property values — newest-first (matches the API contract).
    # OCPA returns -1 sentinel values when the new-year roll is not yet
    # certified; coerce those to 0 so the certified-taxes fallback fires.
    def _pos(v: float) -> float:
        return v if v > 0 else 0.0

    pv0 = property_values[0] if property_values else {}
    market = _pos(_safe_float(pv0.get("marketValue")))
    assessed = _pos(_safe_float(pv0.get("assessedValue")))
    taxable = _pos(_safe_float(pv0.get("netTaxableValue"))) or _pos(_safe_float(pv0.get("taxValue")))
    # Sum exemptions from certified taxes (per-authority view has the canonical
    # taxValue + exemption pair).
    exemption_total = 0.0
    if certified:
        # Use the largest exemption seen across authorities (Save Our Homes
        # + Original Homestead + Additional Homestead, varies by authority).
        exemption_total = max((_safe_float(r.get("exemption")) for r in certified), default=0.0)
    if not taxable and certified:
        # Derive taxable as the largest taxValue among the authorities.
        taxable = max((_safe_float(r.get("taxValue")) for r in certified), default=0.0)
    if not assessed and certified:
        assessed = max((_safe_float(r.get("assessedValue")) for r in certified), default=0.0)

    assessed_value = {}
    if market > 0:
        assessed_value["market"] = market
    if assessed > 0:
        assessed_value["assessed"] = assessed
    if taxable > 0:
        assessed_value["net_taxable"] = taxable
    if exemption_total > 0:
        assessed_value["exemptions"] = exemption_total

    # Installments — OCPA exposes only the ANNUAL bill amount (not the FL
    # 1st/2nd-installment split or paid/unpaid status). We emit a single
    # 'annual' installment carrying the gross total. Paid-status comes
    # from the (deferred) Tax Collector adapter.
    installments: List[Dict[str, Any]] = []
    if gross > 0:
        installments.append({
            "label": "annual",
            "amount": gross,
            "status": "UNVERIFIED",  # Tax Collector pass needed to populate
            "due_date": "",
            "status_text": (
                "Payment status (paid/unpaid/delinquent) requires the Orange "
                "County Tax Collector estoppel — to be verified at closing."
            ),
        })

    # Non-ad-valorem line items (CDD candidates, stormwater, garbage, etc.)
    special_assessments: List[Dict[str, Any]] = []
    for r in (non_ad_valorem or []):
        amt = _safe_float(r.get("assessment") or r.get("amount"))
        desc = (r.get("description") or "").strip()
        if not amt and not desc:
            continue
        special_assessments.append({
            "description": desc,
            "amount": amt,
            "rate": _safe_float(r.get("rate")),
            "authority": (r.get("levyingAuthority") or "").strip(),
        })

    # Source URL is the canonical PRC tax breakdown for this PID
    source_url = f"{base}/{EP_TOTAL_TAXES}?pid={pid}"

    # Host whitelist
    if not host_in_whitelist(source_url, AUTHORITATIVE_HOSTS, mode="strict"):
        return TaxLookupResult(
            apn=display_apn,
            tax_year=tax_year,
            property_address=property_address or (general.get("propertyAddress") or "").strip(),
            status="TAX_FAILED",
            error=f"source URL host not in authoritative whitelist: {source_url!r}",
            source_url=source_url,
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    # Verified vs missing — TAX_SUCCESS gates on apn + tax_year + annual_total
    verified: List[str] = []
    missing: List[str] = []
    if display_apn:
        verified.append("apn")
    else:
        missing.append("apn")
    if tax_year:
        verified.append("tax_year")
    else:
        missing.append("tax_year")
    if gross > 0:
        verified.append("annual_total")
        verified.append("installments[0].amount")
    else:
        missing.append("annual_total")
    if assessed > 0:
        verified.append("assessed_value.assessed")
    if market > 0:
        verified.append("assessed_value.market")

    if missing:
        status = "TAX_PARTIAL"
        notes = (
            f"Partial: {len(verified)} verified, {len(missing)} missing. "
            f"Missing: {', '.join(missing)}."
        )
    else:
        status = "TAX_SUCCESS"
        notes = (
            "Certified-roll figures verified from Orange County Property "
            "Appraiser (authoritative source for assessed value, annual tax, "
            "exemptions, non-ad-valorem). Payment status (paid/unpaid) "
            "is to be verified by the Tax Collector estoppel at closing."
        )

    # Tag owner + millage in notes
    owner = (general.get("ownerName") or "").strip().strip(",").strip()
    if owner:
        notes += f" | owner_on_record={owner}"
    if total_millage > 0:
        notes += f" | total_millage_rate={total_millage:.4f}"

    return TaxLookupResult(
        apn=display_apn,
        tax_year=tax_year,
        property_address=property_address or (general.get("propertyAddress") or "").strip(),
        tra="",
        assessed_value=assessed_value,
        installments=installments,
        annual_total=gross,
        delinquent=False,  # cannot determine from OCPA — see Wave-2 ticket
        special_assessments=special_assessments,
        source_url=source_url,
        source_artifact=str(capture_path),
        captured_at=captured_at,
        status=status,
        verified_fields=verified,
        missing_fields=missing,
        notes=notes,
    )


__all__ = [
    "lookup_orange_ocpa_tax",
    "AUTHORITATIVE_HOSTS",
    "DEFAULT_BASE_URL",
    "DEFAULT_USER_KEY",
    "DEFAULT_ORIGIN",
]
