"""titlepro.tax — county tax lookup dispatcher (per tax_plumbing v2).

Public entry point: `fetch_tax(county_id, apn, owner_name, property_address, case_dir)`.

Routes by platform declared in `config/county_tax_urls.json`:
  - `mbc`           -> wraps `mbc_tax_scraper.lookup_mbc_tax`
  - `oc_treasurer`  -> wraps `tax_lookup.get_tax_info_for_report`
  - `playwright_form` -> loads `config/tax_recipes/<county>.json` and runs `playwright_runner.run`

Anything else (and any county without a recipe) returns
`TaxLookupResult(status="TAX_NO_RUNNER", ...)`. This is **non-blocking** at
the pipeline level by default (Codex finding 3).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .recipe_schema import load_recipe
from .result import TaxLookupResult, apn_matches, host_in_whitelist, normalize_apn

# Default recipe directory (project_root/config/tax_recipes)
_DEFAULT_RECIPES_DIR = Path(__file__).resolve().parents[3] / "config" / "tax_recipes"

# Whitelists used when wrapping legacy scrapers. These mirror the
# authoritative source domains the scrapers actually visit.
_MBC_HOSTS = ["mptsweb.com"]  # covers common1./common2./common3.mptsweb.com
_OC_HOSTS = ["octreasurer.gov", "taxbill.octreasurer.gov"]


def _normalize_county(county: str) -> str:
    """Mirror of `multi_county_tax.normalize_county` (kept local to avoid
    importing the heavy scraper module just for one helper)."""
    c = (county or "").lower().strip()
    for suffix in (" county, ca", ", ca", " county", " ca"):
        if c.endswith(suffix):
            c = c[: -len(suffix)]
    return c.strip().replace(" ", "_")


def _load_county_tax_config(county_id: str) -> dict[str, Any] | None:
    """Load the per-county dict from `config/county_tax_urls.json`."""
    cfg_path = Path(__file__).resolve().parents[3] / "config" / "county_tax_urls.json"
    if not cfg_path.exists():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (data.get("counties") or {}).get(county_id)


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in {".", "-"})
    try:
        return float(cleaned or "0")
    except ValueError:
        return 0.0


def _wrap_legacy_dict(
    raw: dict,
    *,
    apn: str,
    property_address: str,
    authoritative_hosts: list[str],
    platform_label: str,
    host_whitelist_mode: str = "strict",
) -> TaxLookupResult:
    """Convert a legacy scraper dict (mbc/oc) -> TaxLookupResult with hardening.

    Applies the same source-whitelist + APN-echo checks the playwright
    runner does. Estimated-only payloads cannot reach TAX_SUCCESS.
    """
    if not isinstance(raw, dict):
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED", error=f"{platform_label} returned non-dict result",
        )

    raw_success = bool(raw.get("success"))
    scraped_apn = raw.get("apn") or raw.get("clean_apn") or ""
    tax_year = raw.get("tax_year") or ""
    source_url = (
        raw.get("source_url")
        or raw.get("verification_url")
        or raw.get("url")
        or ""
    )

    # Assessed value: normalize to dict shape used by the new schema.
    assessed = {
        "land": _to_float(raw.get("assessed_value_land")) or "",
        "improvements": _to_float(raw.get("assessed_value_improvements")) or "",
        "net_taxable": _to_float(raw.get("assessed_value_total"))
            or _to_float(raw.get("net_taxable")),
    }
    # Drop zero-valued empties for cleaner JSON.
    assessed = {k: v for k, v in assessed.items() if v not in (0.0, "")}

    # Installments
    installments: list[dict] = []
    first_amt = raw.get("first_installment_amount")
    if first_amt:
        installments.append({
            "label": "first",
            "amount": _to_float(first_amt),
            "status": raw.get("first_installment_status", ""),
            "due_date": raw.get("first_installment_due", ""),
        })
    second_amt = raw.get("second_installment_amount")
    if second_amt:
        installments.append({
            "label": "second",
            "amount": _to_float(second_amt),
            "status": raw.get("second_installment_status", ""),
            "due_date": raw.get("second_installment_due", ""),
        })

    annual = _to_float(raw.get("annual_tax"))
    if not annual:
        annual = sum(i.get("amount", 0) for i in installments) or 0.0

    result = TaxLookupResult(
        apn=str(scraped_apn or apn),
        tax_year=str(tax_year),
        property_address=str(raw.get("property_address") or property_address or ""),
        assessed_value=assessed,
        installments=installments,
        annual_total=annual,
        delinquent=bool(raw.get("delinquent")),
        source_url=str(source_url),
        source_artifact="",
        captured_at=datetime.now(),
        status="TAX_FAILED",
    )

    # Source whitelist check
    if not host_in_whitelist(source_url, authoritative_hosts, mode=host_whitelist_mode):
        result.status = "TAX_FAILED"
        result.error = (
            f"{platform_label}: source host not in authoritative whitelist "
            f"({source_url!r} vs {authoritative_hosts}, mode={host_whitelist_mode})"
        )
        return result

    # APN echo check
    if scraped_apn and not apn_matches(apn, str(scraped_apn)):
        result.status = "TAX_FAILED"
        result.error = (
            f"{platform_label}: APN echo mismatch (input={apn!r}, scraped={scraped_apn!r})"
        )
        return result

    # Field verification: APN + tax_year + at least one of (net_taxable, annual_total, installments[0].amount)
    verified: list[str] = []
    missing: list[str] = []

    if scraped_apn:
        verified.append("apn")
    else:
        missing.append("apn")
    if tax_year:
        verified.append("tax_year")
    else:
        missing.append("tax_year")
    if assessed.get("net_taxable"):
        verified.append("assessed_value.net_taxable")
    else:
        missing.append("assessed_value.net_taxable")
    if annual:
        verified.append("annual_total")
    else:
        missing.append("annual_total")

    result.verified_fields = verified
    result.missing_fields = missing

    if not raw_success or not verified:
        result.status = "TAX_FAILED"
        result.error = result.error or (raw.get("error") or "legacy scraper reported failure")
        return result

    if missing:
        result.status = "TAX_PARTIAL"
        result.notes = f"Partial: {len(verified)} verified, {len(missing)} missing"
    else:
        result.status = "TAX_SUCCESS"
        result.notes = "All required fields verified from authoritative county source."

    return result


def fetch_tax(
    county_id: str,
    apn: str,
    owner_name: str,
    property_address: str,
    case_dir: Path,
    *,
    recipes_dir: Path | None = None,
) -> TaxLookupResult:
    """Dispatch to the appropriate tax runner for `county_id`.

    Returns a `TaxLookupResult`. NEVER raises for "no runner configured" —
    that case returns `status="TAX_NO_RUNNER"` so the pipeline can decide
    whether to soft-pass or hard-fail per `WorkflowConfig.strict_tax_no_runner`.

    Raises `CaptchaCheckpointRequired` (from the runner) only when a
    CAPTCHA blocks mid-flow. All other failures are encoded in the
    returned result.
    """
    county_key = _normalize_county(county_id)
    case_dir = Path(case_dir)
    cfg = _load_county_tax_config(county_key) or {}
    platform = cfg.get("platform", "")

    # Convert owner_name -> safe filename stem (we don't have the pipeline
    # in scope here, so just sanitize locally).
    import re as _re
    safe_owner = _re.sub(r"[^A-Za-z0-9_]+", "_", (owner_name or "tax")).strip("_") or "tax"

    # ---- MBC platform ------------------------------------------------
    if platform == "mbc":
        try:
            from titlepro.tax.mbc_tax_scraper import lookup_mbc_tax
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"mbc scraper import failed: {exc}",
            )
        try:
            raw = lookup_mbc_tax(apn, county_key, headless=True)
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"mbc scraper raised: {exc}",
            )
        return _wrap_legacy_dict(
            raw,
            apn=apn,
            property_address=property_address,
            authoritative_hosts=_MBC_HOSTS,
            platform_label="mbc",
            host_whitelist_mode="suffix",  # mptsweb.com fronts common1/common2/common3 subdomains
        )

    # ---- Orange County treasurer ------------------------------------
    if platform == "oc_treasurer":
        try:
            from titlepro.tax.tax_lookup import get_tax_info_for_report as oc_lookup
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"oc scraper import failed: {exc}",
            )
        try:
            raw = oc_lookup(apn)
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"oc scraper raised: {exc}",
            )
        return _wrap_legacy_dict(
            raw,
            apn=apn,
            property_address=property_address,
            authoritative_hosts=_OC_HOSTS,
            platform_label="oc_treasurer",
        )

    # ---- Grant Street Group county-taxes.net (pure HTTP) -------------
    if platform == "grant_street_http":
        try:
            from titlepro.tax.grant_street_http import lookup_grant_street_tax
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"grant_street_http import failed: {exc}",
            )
        try:
            return lookup_grant_street_tax(
                apn=apn,
                county_id=county_key,
                case_dir=case_dir,
                safe_owner=safe_owner,
                property_address=property_address,
                county_overrides=cfg.get("grant_street_overrides") or None,
            )
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"grant_street_http raised: {exc}",
            )

    # ---- Orange County FL via OCPA PRC endpoints (pure HTTP) ---------
    # Property Appraiser is authoritative for assessed value + annual tax;
    # payment-status verification at the Tax Collector (octaxcol.com Aumentum
    # WAF) is deferred to a Wave-2 Playwright recipe — see
    # src/titlepro/tax/orange_ocpa_http.py module docstring for the ticket.
    if platform == "ocpa_http":
        try:
            from titlepro.tax.orange_ocpa_http import lookup_orange_ocpa_tax
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"orange_ocpa_http import failed: {exc}",
            )
        try:
            return lookup_orange_ocpa_tax(
                apn=apn,
                county_id=county_key,
                case_dir=case_dir,
                safe_owner=safe_owner,
                property_address=property_address,
            )
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"orange_ocpa_http raised: {exc}",
            )

    # ---- Manatee FL proprietary ptaxweb (pure HTTP) ------------------
    if platform == "manatee_ptaxweb":
        try:
            from titlepro.tax.manatee_ptaxweb import lookup_manatee_tax
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"manatee_ptaxweb import failed: {exc}",
            )
        try:
            return lookup_manatee_tax(
                apn=apn,
                case_dir=case_dir,
                safe_owner=safe_owner,
                property_address=property_address,
            )
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED",
                error=f"manatee_ptaxweb raised: {exc}",
            )

    # ---- Palm Beach FL via PBCPAO certified-tax (TRIM) table ---------
    # Tax Collector runs on Aumentum/PublicAccessNow (JS SPA, no HTTP search);
    # the Property Appraiser's Property-Details page carries the per-year
    # certified tax (ad valorem + non-ad valorem + total) the Collector bills
    # from. Source the annual total there. See palm_beach_pbcpao_tax.py.
    if platform == "pbcpao_tax":
        try:
            from titlepro.tax.palm_beach_pbcpao_tax import lookup_palm_beach_pbcpao_tax
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"pbcpao_tax import failed: {exc}",
            )
        try:
            return lookup_palm_beach_pbcpao_tax(
                apn=apn, county_id=county_key, case_dir=case_dir,
                safe_owner=safe_owner, property_address=property_address,
            )
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"pbcpao_tax raised: {exc}",
            )

    # ---- Generic Playwright recipe ----------------------------------
    if platform == "playwright_form":
        try:
            recipe = load_recipe(county_key, recipes_dir=recipes_dir or _DEFAULT_RECIPES_DIR)
        except ValueError as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"recipe load/validation failed: {exc}",
            )
        if recipe is None:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_NO_RUNNER",
                notes=(
                    f"County {county_key!r} declares platform='playwright_form' but no "
                    f"recipe file exists at {recipes_dir or _DEFAULT_RECIPES_DIR}/{county_key}.json."
                ),
            )
        # Pre-populate property_address since runner may not extract it
        try:
            from .playwright_runner import run as _runner_run
        except Exception as exc:
            return TaxLookupResult(
                apn=apn, tax_year="", property_address=property_address,
                status="TAX_FAILED", error=f"playwright_runner import failed: {exc}",
            )
        result = _runner_run(recipe, apn, case_dir, safe_owner=safe_owner, property_address=property_address or "")
        if not result.property_address and property_address:
            result.property_address = property_address
        return result

    # ---- No platform / unknown --------------------------------------
    return TaxLookupResult(
        apn=apn,
        tax_year="",
        property_address=property_address,
        status="TAX_NO_RUNNER",
        notes=(
            f"No tax-lookup runner configured for county {county_id!r} "
            f"(normalized={county_key!r}, platform={platform!r})."
        ),
    )


__all__ = ["fetch_tax", "TaxLookupResult"]
