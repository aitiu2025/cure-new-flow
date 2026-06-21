"""
Multi-County Tax Lookup Dispatcher

Routes tax lookups to the appropriate county-specific scraper.
Supports MBC platform counties, Orange County, and provides graceful fallback.

County configuration is loaded from config/county_tax_urls.json.

Usage:
    from titlepro.tax.multi_county_tax import lookup_tax, get_supported_tax_counties
    result = lookup_tax("015520016000", "amador")
"""

import json
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime

from titlepro.tax.mbc_tax_scraper import lookup_mbc_tax, MBC_COUNTY_URLS

# Try to import Orange County scraper
try:
    from titlepro.tax.tax_lookup import get_tax_info_for_report as oc_tax_lookup
    OC_AVAILABLE = True
except ImportError:
    OC_AVAILABLE = False


def log(msg: str) -> None:
    print(f"[tax-dispatch] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Build TAX_COUNTY_REGISTRY from centralized config
# ---------------------------------------------------------------------------

def _build_registry_from_config() -> Dict[str, Dict]:
    """
    Build TAX_COUNTY_REGISTRY from config/county_tax_urls.json.

    Reads every county entry and creates registry entries with platform
    and url keys. Falls back to the legacy approach (MBC_COUNTY_URLS +
    hardcoded OC) if the config file is not available.
    """
    config_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "county_tax_urls.json"
    registry = {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        counties = data.get("counties", {})

        for key, cfg in counties.items():
            platform = cfg.get("platform", "direct")
            # Only register counties that have an implemented scraper
            # (mbc and oc_treasurer have scrapers; others are informational for now)
            if platform == "mbc":
                registry[key] = {
                    "platform": "mbc",
                    "url": cfg["base_url"],
                }
            elif platform == "oc_treasurer" and OC_AVAILABLE:
                registry[key] = {
                    "platform": "oc_treasurer",
                    "url": cfg["base_url"],
                }
            # 'direct' and other platform types are listed in config but
            # do not yet have scraper implementations. They are intentionally
            # NOT added to the active registry to avoid runtime errors.

        if registry:
            log(f"Tax registry built from config: {len(registry)} counties")
            return registry

    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        log(f"Warning: Could not load tax config from {config_path}: {exc}")

    # Fallback: build from MBC_COUNTY_URLS dict + OC
    log("Falling back to legacy registry build (MBC_COUNTY_URLS + OC)")
    for county_name in MBC_COUNTY_URLS:
        registry[county_name] = {
            "platform": "mbc",
            "url": MBC_COUNTY_URLS[county_name],
        }
    if OC_AVAILABLE:
        registry["orange"] = {
            "platform": "oc_treasurer",
            "url": "https://taxbill.octreasurer.gov/",
        }

    return registry


# Registry of all supported counties and their tax lookup method
TAX_COUNTY_REGISTRY = _build_registry_from_config()


def normalize_county(county: str) -> str:
    """Normalize county name for registry lookup."""
    county_key = county.lower().strip()
    for suffix in [" county", " county, ca", ", ca", " ca"]:
        if county_key.endswith(suffix):
            county_key = county_key[:-len(suffix)]
    # Normalize spaces to underscores to match config keys (e.g. "san benito" -> "san_benito")
    county_key = county_key.strip().replace(" ", "_")
    return county_key


_NO_RUNNER_NOTE = (
    "Tax lookup runner not configured for this county. Manual portal "
    "verification required."
)


def lookup_tax(apn: str, county: str, headless: bool = True) -> Dict:
    """
    Look up property tax for any supported county.

    This legacy entry point now delegates to the v2 dispatcher
    `titlepro.tax.fetch_tax`, which handles recipe-driven counties,
    MBC, OC, and returns `TAX_NO_RUNNER` cleanly for counties without
    a runner. We keep this function for callers that haven't migrated
    yet (e.g. `server.perform_tax_lookup`'s Selenium fallback path).

    Importantly: the error field NEVER contains a hardcoded "Supported:
    [...]" list — those lists go stale and embarrass the report.

    Args:
        apn: Assessor's Parcel Number
        county: County name (e.g., "amador", "orange", "Amador County")
        headless: Run browser invisibly (kept for backwards-compat;
            ignored by the v2 dispatcher which always runs headless).

    Returns:
        Dict with tax data (legacy flat shape preserved for downstream
        readers). On TAX_NO_RUNNER, returns a neutral 'error' / 'notes'
        message — no "Supported: [...]" list.
    """
    county_key = normalize_county(county)
    log(f"Tax lookup request: APN={apn}, county={county_key}")
    timestamp = datetime.now().isoformat()

    # ---- Delegate to v2 dispatcher first --------------------------------
    try:
        # Local import avoids a hard cycle: tax/__init__.py imports
        # mbc_tax_scraper but not this module.
        from titlepro.tax import fetch_tax as _fetch_tax
        from pathlib import Path as _Path
        import tempfile as _tempfile

        # The v2 dispatcher needs a case_dir for source-artifact captures
        # (used by the playwright runner). Legacy callers don't provide
        # one, so use a tmp dir as a safe sink.
        _case_dir = _Path(_tempfile.mkdtemp(prefix="legacy_tax_"))
        result = _fetch_tax(
            county_id=county_key,
            apn=apn,
            owner_name="legacy_lookup",
            property_address="",
            case_dir=_case_dir,
        )
    except Exception as exc:
        log(f"Dispatcher delegation failed: {exc}; falling back to legacy registry path.")
        result = None

    if result is not None:
        # Map v2 TaxLookupResult -> legacy flat dict (preserves the
        # downstream consumer expectations in save_tax_file).
        status = result.status
        success = status in ("TAX_SUCCESS", "TAX_PARTIAL")

        # TAX_NO_RUNNER => neutral message, no hardcoded list
        if status == "TAX_NO_RUNNER":
            return {
                "success": False,
                "apn": apn,
                "county": county_key,
                "status": "TAX_NO_RUNNER",
                "notes": _NO_RUNNER_NOTE,
                "error": "",  # explicit empty — do not leak legacy text
                "lookup_timestamp": timestamp,
            }

        # Build the legacy flat dict for callers that still expect it
        out: Dict = {
            "success": success,
            "apn": result.apn or apn,
            "county": county_key,
            "status": status,
            "tax_year": result.tax_year,
            "property_address": result.property_address,
            "annual_tax": result.annual_total,
            "assessed_value_land": result.assessed_value.get("land", ""),
            "assessed_value_improvements": result.assessed_value.get("improvements", ""),
            "assessed_value_total": result.assessed_value.get("net_taxable", ""),
            "delinquent": result.delinquent,
            "verification_url": result.source_url,
            "source_url": result.source_url,
            "data_source": result.source_url,
            "lookup_timestamp": (
                result.captured_at.isoformat()
                if hasattr(result.captured_at, "isoformat")
                else timestamp
            ),
            "verified_fields": list(result.verified_fields),
            "missing_fields": list(result.missing_fields),
            "notes": result.notes or "",
            "error": "" if success else (result.error or result.notes or ""),
        }
        # Flatten first/second installments for legacy save_tax_file format
        installments = result.installments or []
        if installments:
            first = installments[0] if len(installments) > 0 else {}
            second = installments[1] if len(installments) > 1 else {}
            out["first_installment_amount"] = first.get("amount", "")
            out["first_installment_status"] = first.get("status", "")
            out["first_installment_due"] = first.get("due_date", "December 10")
            out["second_installment_amount"] = second.get("amount", "")
            out["second_installment_status"] = second.get("status", "")
            out["second_installment_due"] = second.get("due_date", "April 10")
        return out

    # ---- Last-resort legacy fallback ------------------------------------
    # Only reached if the v2 dispatcher itself blew up. Even here, do NOT
    # emit a hardcoded "Supported: [...]" list — return a neutral message.
    if county_key not in TAX_COUNTY_REGISTRY:
        return {
            "success": False,
            "apn": apn,
            "county": county_key,
            "status": "TAX_NO_RUNNER",
            "notes": _NO_RUNNER_NOTE,
            "error": "",
            "lookup_timestamp": timestamp,
        }

    entry = TAX_COUNTY_REGISTRY[county_key]
    platform = entry["platform"]

    if platform == "mbc":
        log(f"Routing to MBC scraper for {county_key}")
        return lookup_mbc_tax(apn, county_key, headless=headless)

    elif platform == "oc_treasurer":
        log(f"Routing to OC Treasurer scraper for {county_key}")
        try:
            result_dict = oc_tax_lookup(apn)
            result_dict["county"] = "orange"
            result_dict["verification_url"] = entry["url"]
            result_dict["data_source"] = "OC Treasurer-Tax Collector website"
            return result_dict
        except Exception as e:
            return {
                "success": False,
                "apn": apn,
                "county": county_key,
                "status": "TAX_FAILED",
                "error": f"Orange County tax lookup failed: {e}",
                "verification_url": entry["url"],
                "lookup_timestamp": timestamp,
            }

    return {
        "success": False,
        "apn": apn,
        "county": county_key,
        "status": "TAX_NO_RUNNER",
        "notes": _NO_RUNNER_NOTE,
        "error": "",
        "lookup_timestamp": timestamp,
    }


def save_tax_file(tax_data: Dict, folder_path: Path, owner_name: str) -> Path:
    """
    Save tax lookup results to a JSON file in the owner's folder.

    Args:
        tax_data: Tax lookup result dict
        folder_path: Path to the owner's download folder
        owner_name: Owner name for filename

    Returns:
        Path to the saved file
    """
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    filename = f"tax_{safe_owner}.json"
    file_path = folder_path / filename

    output = {
        "lookup_metadata": {
            "county": tax_data.get("county", ""),
            "platform": TAX_COUNTY_REGISTRY.get(tax_data.get("county", ""), {}).get("platform", "unknown"),
            "lookup_timestamp": tax_data.get("lookup_timestamp", datetime.now().isoformat()),
            "apn_searched": tax_data.get("apn", ""),
            "clean_apn": tax_data.get("clean_apn", ""),
            "verification_url": tax_data.get("verification_url", ""),
            "data_source": tax_data.get("data_source", ""),
            "success": tax_data.get("success", False),
            "error": tax_data.get("error"),
        },
        "tax_information": {
            "tax_year": tax_data.get("tax_year", ""),
            "apn": tax_data.get("apn", ""),
            "annual_tax_estimated": tax_data.get("annual_tax", ""),
            "first_installment_amount": tax_data.get("first_installment_amount", ""),
            "first_installment_status": tax_data.get("first_installment_status", ""),
            "first_installment_due": tax_data.get("first_installment_due", "December 10"),
            "second_installment_amount": tax_data.get("second_installment_amount", ""),
            "second_installment_status": tax_data.get("second_installment_status", ""),
            "second_installment_due": tax_data.get("second_installment_due", "April 10"),
            "assessed_value_land": tax_data.get("assessed_value_land", ""),
            "assessed_value_improvements": tax_data.get("assessed_value_improvements", ""),
            "assessed_value_total": tax_data.get("assessed_value_total", ""),
            "property_address": tax_data.get("property_address", ""),
            "delinquent": tax_data.get("delinquent", False),
            "verification_url": tax_data.get("verification_url", ""),
            "data_source": tax_data.get("data_source", ""),
        }
    }

    folder_path.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(output, indent=2))
    log(f"Tax data saved to {file_path}")
    return file_path


def get_supported_tax_counties() -> List[str]:
    """Return list of county names that support tax lookup."""
    return sorted(TAX_COUNTY_REGISTRY.keys())


def get_tax_verification_url(county: str) -> Optional[str]:
    """Get the tax verification URL for a county."""
    county_key = normalize_county(county)
    entry = TAX_COUNTY_REGISTRY.get(county_key)
    return entry["url"] if entry else None
