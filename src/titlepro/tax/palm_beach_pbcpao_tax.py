"""Palm Beach County FL tax lookup via the PBCPAO certified-tax (TRIM) table.

The Palm Beach County Tax Collector runs on the Aumentum / PublicAccessNow
platform (JS-rendered SPA, no clean HTTP search), so the live bill is not
HTTP-scrapable without a browser. BUT the **Property Appraiser** (pbcpao.gov)
Property-Details page embeds the per-year **certified (TRIM)** tax table —
``AD VALOREM`` + ``NON AD VALOREM`` + ``TOTAL TAX`` — which are the exact
figures the Tax Collector bills from (the Collector only adds statutory
interest on unpaid bills after April 1). We source the annual tax there via
the existing ``PalmBeachPBCPAO.lookup_certified_tax()``.

Limitation (documented honestly, not a placeholder): paid/delinquent
installment status lives only at the Tax Collector, so this runner reports the
certified annual total + ad/non-ad-valorem split but leaves installment status
unset. That is the authoritative bill amount; the §6 note states the source.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .result import TaxLookupResult


def lookup_palm_beach_pbcpao_tax(
    *,
    apn: str,
    county_id: str = "fl_palm_beach",
    case_dir: Optional[Path] = None,
    safe_owner: str = "",
    property_address: str = "",
    pa_config: Optional[dict] = None,
) -> TaxLookupResult:
    try:
        from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO
    except Exception as exc:  # pragma: no cover - import guard
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED", error=f"PBCPAO import failed: {exc}",
        )

    cfg = dict(pa_config or {})
    cfg.setdefault("county_id", county_id)
    cfg.setdefault("base_url", "https://www.pbcpao.gov/")

    try:
        raw = PalmBeachPBCPAO(cfg).lookup_certified_tax(apn)
    except Exception as exc:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED", error=f"PBCPAO certified-tax raised: {exc}",
        )

    status = raw.get("status", "TAX_FAILED")
    pcn_clean = str(raw.get("apn") or apn).replace("-", "").strip()
    source_url = f"https://www.pbcpao.gov/Property/Details?parcelId={pcn_clean}"

    if status != "TAX_SUCCESS":
        return TaxLookupResult(
            apn=str(raw.get("apn") or apn), tax_year=str(raw.get("tax_year", "")),
            property_address=property_address, status=status,
            source_url=source_url, notes=raw.get("notes", ""),
        )

    total = float(raw.get("total_tax") or 0)
    ad_val = raw.get("ad_valorem")
    non_ad = raw.get("non_ad_valorem")
    return TaxLookupResult(
        apn=str(raw.get("apn") or apn),
        tax_year=str(raw.get("tax_year", "")),
        property_address=property_address,
        annual_total=total,
        assessed_value={"ad_valorem": ad_val, "non_ad_valorem": non_ad},
        special_assessments=([{"description": "Non-Ad Valorem (certified)", "amount": non_ad}]
                             if non_ad else []),
        status="TAX_SUCCESS",
        source_url=source_url,
        captured_at=datetime.now(),
        verified_fields=["annual_total", "tax_year",
                         "assessed_value.ad_valorem", "assessed_value.non_ad_valorem"],
        notes=("Certified (TRIM) tax from the Palm Beach County Property Appraiser "
               "(pbcpao.gov) — the figure the Tax Collector bills from. Paid/delinquent "
               "installment status is held only at the Tax Collector (Aumentum/"
               "PublicAccessNow); the certified annual total is authoritative."),
    )
