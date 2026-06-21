"""
County Tax Lookup Module

Loads county tax URL configuration from config/county_tax_urls.json and provides
functions to query county assessor/tax-collector sites by APN or address.

The JSON config is loaded once and cached. If the config file is missing or
malformed, the module falls back to an empty registry and logs a warning.
"""

import json
import requests
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

# Resolve path: this file is at src/titlepro/tax/county_tax_lookup.py
# Config is at <project_root>/config/county_tax_urls.json
_THIS_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _THIS_DIR.parent.parent.parent / "config" / "county_tax_urls.json"

# Module-level cache
_config_cache: Optional[Dict[str, Any]] = None


def _load_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load and cache the county tax URL config from JSON.

    Returns the full parsed JSON dict with a 'counties' key mapping
    county IDs to their configuration. Returns an empty 'counties' dict
    on any load failure so callers always get a safe structure.
    """
    global _config_cache

    if _config_cache is not None and not force_reload:
        return _config_cache

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "counties" not in data or not isinstance(data["counties"], dict):
            logger.warning(
                "county_tax_urls.json is missing 'counties' key or it is not a dict. "
                "Falling back to empty registry."
            )
            data = {"counties": {}}
        _config_cache = data
        logger.info(
            "Loaded %d county tax configs from %s",
            len(data["counties"]),
            _CONFIG_PATH,
        )
    except FileNotFoundError:
        logger.warning(
            "County tax config not found at %s. No counties will be available.",
            _CONFIG_PATH,
        )
        _config_cache = {"counties": {}}
    except json.JSONDecodeError as exc:
        logger.error(
            "Failed to parse county_tax_urls.json: %s. Falling back to empty registry.",
            exc,
        )
        _config_cache = {"counties": {}}

    return _config_cache


def get_county_config(county: str) -> Optional[Dict[str, Any]]:
    """
    Return the config dict for a single county, or None if not found.

    Normalizes the county key (lowercase, strip whitespace, remove
    ' county' / ', ca' suffixes, spaces to underscores).
    """
    config = _load_config()
    county_key = normalize_county_key(county)
    return config["counties"].get(county_key)


def get_all_county_configs() -> Dict[str, Dict[str, Any]]:
    """Return the full counties dict from config."""
    return _load_config()["counties"]


def get_supported_counties() -> List[str]:
    """Return a sorted list of all county keys in the config."""
    return sorted(get_all_county_configs().keys())


def normalize_county_key(county: str) -> str:
    """
    Normalize a county name into the canonical config key.

    Examples:
        'Los Angeles'        -> 'los_angeles'
        'los_angeles'        -> 'los_angeles'
        'Orange County'      -> 'orange'
        'San Benito, CA'     -> 'san_benito'
        'AMADOR COUNTY, CA'  -> 'amador'
    """
    key = county.lower().strip()
    for suffix in [" county, ca", " county,ca", " county", ", ca", ",ca", " ca"]:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
            break
    # Replace spaces with underscores for multi-word counties
    key = key.replace(" ", "_")
    return key


def reload_config() -> Dict[str, Any]:
    """Force-reload the config from disk. Useful after editing the JSON file."""
    return _load_config(force_reload=True)


# ---------------------------------------------------------------------------
# Backward-compatible COUNTY_TAX_URLS dict
# ---------------------------------------------------------------------------
# Some existing code may reference COUNTY_TAX_URLS directly. We expose a
# dynamically-populated version so those imports keep working.

def _build_legacy_urls() -> Dict[str, Dict[str, str]]:
    """
    Build the legacy COUNTY_TAX_URLS dict from the JSON config.

    The old format was:
        {
            'los_angeles': {
                'apn_lookup': 'https://.../{apn}',
                'address_lookup': 'https://.../{address}',
            },
        }

    We construct an approximation from the new config so that any code still
    using the old dict structure will not break.
    """
    counties = get_all_county_configs()
    legacy = {}
    for key, cfg in counties.items():
        base = cfg.get("base_url", "")
        entry = {"base_url": base}
        # LA County has separate assessor portal
        if key == "los_angeles":
            assessor_url = cfg.get("assessor_url", base)
            entry["apn_lookup"] = f"{assessor_url}parceldetail/{{apn}}"
            entry["address_lookup"] = f"{assessor_url}address/{{address}}"
        legacy[key] = entry
    return legacy


# Lazy-loaded legacy dict -- populated on first access
class _LegacyURLsProxy(dict):
    """Dict that populates itself from config on first access."""

    _loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.update(_build_legacy_urls())
            self._loaded = True

    def __getitem__(self, key):
        self._ensure_loaded()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure_loaded()
        return super().__contains__(key)

    def keys(self):
        self._ensure_loaded()
        return super().keys()

    def values(self):
        self._ensure_loaded()
        return super().values()

    def items(self):
        self._ensure_loaded()
        return super().items()

    def get(self, key, default=None):
        self._ensure_loaded()
        return super().get(key, default)

    def __len__(self):
        self._ensure_loaded()
        return super().__len__()

    def __repr__(self):
        self._ensure_loaded()
        return super().__repr__()


COUNTY_TAX_URLS = _LegacyURLsProxy()


# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------

class CountyTaxLookupError(Exception):
    pass


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_apn(apn: str) -> str:
    """Format APN as needed for query URL (e.g. zero padding, dashes)."""
    return apn.replace('-', '').replace(' ', '')


def format_address(address: str) -> str:
    """Format address for query URL (e.g. URL encoding)."""
    from urllib.parse import quote_plus
    return quote_plus(address.strip())


# ---------------------------------------------------------------------------
# Assessor response parser (placeholder)
# ---------------------------------------------------------------------------

def parse_assessor_response(response_text: str) -> Dict[str, Any]:
    """
    Dummy parser for demonstration; in production, parse HTML or JSON per county.
    """
    assessed_value = None
    tax_amount = None
    tax_status = None

    import re
    if 'Assessed Value:' in response_text:
        m = re.search(r'Assessed Value:\s*\$([\d,]+)', response_text)
        if m:
            assessed_value = m.group(1).replace(',', '')
    if 'Annual Tax:' in response_text:
        m = re.search(r'Annual Tax:\s*\$([\d,]+)', response_text)
        if m:
            tax_amount = m.group(1).replace(',', '')
    if 'Tax Status:' in response_text:
        m = re.search(r'Tax Status:\s*([\w ]+)', response_text)
        if m:
            tax_status = m.group(1).strip()

    return {
        'assessed_value': assessed_value,
        'tax_amount': tax_amount,
        'tax_status': tax_status,
    }


# ---------------------------------------------------------------------------
# County-specific query helpers
# ---------------------------------------------------------------------------

def query_la_by_apn(apn: str) -> Optional[Dict[str, Any]]:
    """Query LA County assessor portal by APN."""
    cfg = get_county_config("los_angeles")
    if not cfg:
        logger.warning("LA County not found in config")
        return None

    assessor_url = cfg.get("assessor_url", cfg["base_url"])
    url = f"{assessor_url}parceldetail/{format_apn(apn)}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = parse_assessor_response(resp.text)
            if any(data.values()):
                return data
    except Exception as e:
        logger.warning('APN lookup failed: %s', e)
    return None


def query_la_by_address(address: str) -> Optional[Dict[str, Any]]:
    """Query LA County assessor portal by address."""
    cfg = get_county_config("los_angeles")
    if not cfg:
        logger.warning("LA County not found in config")
        return None

    assessor_url = cfg.get("assessor_url", cfg["base_url"])
    url = f"{assessor_url}address/{format_address(address)}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = parse_assessor_response(resp.text)
            if any(data.values()):
                return data
    except Exception as e:
        logger.warning('Address lookup failed: %s', e)
    return None


# ---------------------------------------------------------------------------
# Main lookup function
# ---------------------------------------------------------------------------

def county_tax_lookup(
        apn: Optional[str] = None,
        address: Optional[str] = None,
        county: str = 'los_angeles'
) -> Dict[str, Any]:
    """
    Query county site for tax data using APN (primary) or address (fallback).

    Returns dict with keys: assessed_value, tax_amount, tax_status.
    On failure, values are None and an 'error' key is included.

    Args:
        apn: Assessor's Parcel Number (optional).
        address: Property street address (optional).
        county: County name or key (default: 'los_angeles').

    Returns:
        Dict with tax data or error information.
    """
    results = {'assessed_value': None, 'tax_amount': None, 'tax_status': None}

    county_key = normalize_county_key(county)
    cfg = get_county_config(county_key)

    if cfg is None:
        supported = get_supported_counties()
        results['error'] = (
            f'County "{county}" (key: "{county_key}") not found in config. '
            f'Supported counties: {supported}'
        )
        return results

    # Currently only LA County has a direct HTTP query implementation.
    # Other counties require Selenium-based scrapers dispatched via
    # multi_county_tax.py. If the county is in config but does not have
    # a direct query path here, return a helpful pointer.
    if county_key == 'los_angeles':
        if apn:
            data = query_la_by_apn(apn)
            if data:
                results.update(data)
                return results
            else:
                logger.info(
                    "APN lookup failed for %s, attempting address fallback if available.",
                    apn,
                )
        if address:
            data = query_la_by_address(address)
            if data:
                results.update(data)
                return results
            else:
                results['error'] = f'No data found for address {address}.'
        else:
            results['error'] = 'Neither valid APN nor address provided.'
        return results

    # For all other counties, point to the appropriate scraper
    platform = cfg.get("platform", "unknown")
    results['error'] = (
        f'County "{county_key}" is configured (platform: {platform}) but direct '
        f'HTTP query is not implemented in county_tax_lookup. Use '
        f'multi_county_tax.lookup_tax() for Selenium-based lookups. '
        f'Verification URL: {cfg.get("base_url", "N/A")}'
    )
    results['verification_url'] = cfg.get("base_url")
    return results


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    print(f"Config loaded from: {_CONFIG_PATH}")
    print(f"Supported counties ({len(get_supported_counties())}): {get_supported_counties()}")
    print()

    # Example test calls
    test1 = county_tax_lookup(apn='1234-567-890', county='los_angeles')
    print('Test APN (LA):', test1)

    test2 = county_tax_lookup(address='500 W Temple St, Los Angeles, CA', county='los_angeles')
    print('Test Address (LA):', test2)

    test3 = county_tax_lookup(apn=None, address=None, county='los_angeles')
    print('Test Missing:', test3)

    test4 = county_tax_lookup(apn='1234-567-890', county='orange')
    print('Test Orange County:', test4)

    test5 = county_tax_lookup(apn='1234-567-890', county='nonexistent')
    print('Test Unsupported County:', test5)

    test6 = county_tax_lookup(apn='015520016000', county='amador')
    print('Test Amador (MBC):', test6)
