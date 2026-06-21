"""Property Appraiser adapters — Phase 1a anchor source.

Public API:
    fetch_property_appraiser(county_id, address=..., apn=...)
        → PropertyAppraiserResult

Routing is config-driven via `config/county_property_appraiser_urls.json`.
Mirrors the `tax/__init__.py` factory pattern.

This module exists to deliver Tony Roveda's directive #4 (subject-address
verification, SIMMONS gate) + close the ANAND-class corporate-grantor prior
deed gap via PA-sourced sale history. See ~/.claude/plans/async-wondering-tiger.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .result import PropertyAppraiserResult, SaleHistoryEntry  # re-exported


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "county_property_appraiser_urls.json"


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {"counties": {}}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _county_config(county_id: str) -> Optional[dict]:
    cfg = _load_config()
    return cfg.get("counties", {}).get(county_id)


def fetch_property_appraiser(
    county_id: str,
    address: Optional[str] = None,
    apn: Optional[str] = None,
    case_dir: Optional[Path] = None,
) -> PropertyAppraiserResult:
    """Dispatch to the county-specific PA adapter.

    At least one of `address` or `apn` must be supplied. If both are passed,
    APN is used as the authoritative key (more precise).

    Returns a `PropertyAppraiserResult` with a populated `status` field.
    Adapters do NOT raise on portal failure — they return `status=PA_FAILED`
    or `PA_NO_RUNNER` with explanatory notes.
    """
    if not address and not apn:
        return PropertyAppraiserResult(
            status="PA_FAILED",
            notes="fetch_property_appraiser: at least one of `address` or `apn` is required",
            fetched_at=datetime.now().isoformat(),
        )

    cfg = _county_config(county_id)
    if not cfg:
        return PropertyAppraiserResult(
            status="PA_NO_RUNNER",
            notes=f"no property-appraiser runner registered for county_id={county_id!r}",
            fetched_at=datetime.now().isoformat(),
        )

    platform = cfg.get("platform", "")
    if platform == "bcpa_http":
        from .counties.broward_bcpa import BrowardBCPA
        adapter = BrowardBCPA(cfg)
    elif platform == "hcpa_http":
        from .counties.hillsborough_hcpa import HillsboroughHCPA
        adapter = HillsboroughHCPA(cfg)
    elif platform == "ocpa_http":
        from .counties.orange_ocpa import OrangeOCPA
        adapter = OrangeOCPA(cfg)
    elif platform == "manatee_pao":
        from .counties.manatee_pao import ManateePAO
        adapter = ManateePAO(cfg)
    elif platform == "pbcpao_http":
        from .counties.palm_beach_pbcpao import PalmBeachPBCPAO
        adapter = PalmBeachPBCPAO(cfg)
    elif platform == "vcpa_http":
        from .counties.volusia_vcpa import VolusiaVCPA
        adapter = VolusiaVCPA(cfg)
    elif platform == "duval_pao":
        from .counties.duval_pao import DuvalPAO
        adapter = DuvalPAO(cfg)
    elif platform == "pascopa_http":
        from .counties.pasco_pa import PascoPA
        adapter = PascoPA(cfg)
    elif platform == "leepa_http":
        from .counties.lee_leepa import LeeLeePA
        adapter = LeeLeePA(cfg)
    elif platform == "bcpao_http":
        from .counties.brevard_bcpao import BrevardBCPAO
        adapter = BrevardBCPAO(cfg)
    elif platform == "scpa_http":
        from .counties.sarasota_scpa import SarasotaSCPA
        adapter = SarasotaSCPA(cfg)
    elif platform == "scpa_arcgis":
        from .counties.seminole_scpa import SeminoleSCPA
        adapter = SeminoleSCPA(cfg)
    elif platform == "polk_pa":
        from .counties.polk_pa import PolkPA
        adapter = PolkPA(cfg)
    elif platform == "escambia_pa_http":
        from .counties.escambia_pa import EscambiaPA
        adapter = EscambiaPA(cfg)
    elif platform == "mdcpa_http":
        from .counties.miami_dade_mdcpa import MiamiDadeMDCPA
        adapter = MiamiDadeMDCPA(cfg)
    elif platform == "citrus_pa_http":
        # Citrus County — Tyler/TrueAutomation "EagleWeb" (ProVal Web). The only
        # EagleWeb county in the FL Landmark batch (peers run qPublic/Schneider).
        # Plain IIS, no Cloudflare. Seed county_id from the routing key.
        from .counties.citrus_pa import CitrusPA
        citrus_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = CitrusPA(citrus_cfg)
    elif platform == "lake_copa_http":
        # Lake County FL — county-custom ASP.NET WebForms PA at lakecopropappr.com.
        # TOU gate + owner/street search + property-details.aspx?AltKey=<key>.
        # No Cloudflare — plain IIS, US egress only. Live-validated 2026-06-18.
        from .counties.lake_copa import LakeCOPA
        lake_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = LakeCOPA(lake_cfg)
    elif platform == "leon_pa_http":
        from .counties.leon_pa import LeonPA
        adapter = LeonPA(cfg)
    elif platform == "santa_rosa_pa_http":
        from .counties.santa_rosa_pa import SantaRosaPA
        sr_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = SantaRosaPA(sr_cfg)
    elif platform == "qpublic_schneider_pa_http":
        # Shared multi-tenant qPublic / Schneider Geospatial adapter — serves
        # every FL county whose PA delegates search to qpublic.schneidercorp.com /
        # beacon.schneidercorp.com (Landmark wave: bay/clay/flagler/monroe/
        # wakulla/walton/indian_river/st_johns/levy). Parameterized by the
        # per-county `app_id` (+ `qpublic_host`) in the config entry. The config
        # entry's routing key is county_id; seed it so adapter notes name the county.
        from .counties.qpublic_schneider_pa_http import QPublicSchneiderPA
        qp_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = QPublicSchneiderPA(qp_cfg)
    elif platform == "charlotte_ccpa_http":
        # Charlotte County FL — county-custom Classic ASP portal at ccappraiser.com.
        # IIS 8.5 / ASP.NET 4.0 — no Cloudflare, no CAPTCHA, datacenter OK.
        # Two-step flow: GET RPSearchEnter.asp → POST RPSearchQuery.asp →
        # GET RPSearchSelect.asp (results) → GET Show_Parcel.asp?acct=<APN>.
        # APN lookup shortcut: GET homepage (seed session) → GET Show_Parcel.asp directly.
        # Live-validated 2026-06-19 (OLAR IVAN, 100 Long Meadow Ln, APN 412024203012).
        from .counties.charlotte_ccpa import CharlotteCCPA
        charlotte_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = CharlotteCCPA(charlotte_cfg)
    elif platform == "landmark_pa_scaffold":
        # FL Landmark next-batch wave: county recognized + wired, but the PA
        # anchor is not yet implemented (live probe pending). The scaffold's
        # lookups return a PA_NO_RUNNER soft failure (NOT a raise) so the public
        # factory's no-raise contract holds and a caller that treats a registered
        # county as callable never crashes — while the anchor is still loudly
        # absent (never silently empty). See counties/_scaffold.py.
        from .counties._scaffold import LandmarkPAScaffold
        # The PA config entry doesn't carry county_id (it's the routing key
        # here), so seed it from the factory arg so the soft-failure notes name
        # the county. Shallow-copy to avoid mutating the cached config dict.
        scaffold_cfg = {**cfg, "county_id": cfg.get("county_id") or county_id}
        adapter = LandmarkPAScaffold(scaffold_cfg)
    else:
        return PropertyAppraiserResult(
            status="PA_NO_RUNNER",
            notes=f"county_id={county_id!r} has platform={platform!r} which has no adapter yet",
            fetched_at=datetime.now().isoformat(),
        )

    if apn:
        result = adapter.lookup_by_apn(apn)
    else:
        result = adapter.lookup_by_address(address)

    if not result.fetched_at:
        result.fetched_at = datetime.now().isoformat()

    return result


__all__ = [
    "PropertyAppraiserResult",
    "SaleHistoryEntry",
    "fetch_property_appraiser",
]
