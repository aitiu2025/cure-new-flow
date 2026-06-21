"""Structural tests for the remaining Landmark Property-Appraiser scaffolds.

These lock the scaffold contract: each county is registered + wired + importable,
and its lookups return a PA_NO_RUNNER soft-failure ``PropertyAppraiserResult``
through the public ``fetch_property_appraiser`` factory (which must NEVER raise,
P2b) — so a scaffold can never silently ship an empty anchor AND never crashes a
caller that treats a registered county as callable. A DEV-ONLY ``preflight()``
still raises ``NotImplementedError`` for manual dev signalling. When a county
graduates to a live adapter, drop it from SCAFFOLD_COUNTIES here and add real
fixture-backed tests.

GRADUATIONS:
  * fl_escambia → escambia_pa_http (2026-06-14) — test_property_appraiser_escambia_pa.py
  * fl_bay / fl_clay / fl_flagler / fl_monroe / fl_wakulla / fl_walton /
    fl_indian_river / fl_st_johns / fl_levy → qpublic_schneider_pa_http (2026-06-17,
    ONE shared adapter) — test_property_appraiser_qpublic_schneider.py.
    Their per-county scaffold modules (clay_pa.py etc.) still exist + still
    subclass LandmarkPAScaffold, but the PA config + factory now route them to the
    shared qPublic adapter, so they are no longer in SCAFFOLD_COUNTIES below.
  * fl_citrus → citrus_pa_http (2026-06-18) — Tyler/TrueAutomation EagleWeb;
    test_property_appraiser_citrus_pa.py. citrus_pa.py is now the REAL adapter
    (subclasses AbstractPropertyAppraiser, NOT LandmarkPAScaffold), so it is
    dropped from BOTH sets below — its scaffold stub was replaced outright.

Remaining scaffolds = the 3 one-off custom-SPA platforms that still need bespoke
adapters: hernando, martin, okeechobee.
"""

import importlib

import pytest

from titlepro.property_appraiser import fetch_property_appraiser
from titlepro.property_appraiser.counties._scaffold import LandmarkPAScaffold

# county_id -> (module, ClassName) — only counties STILL on the scaffold.
SCAFFOLD_COUNTIES = {
    "fl_hernando": ("hernando_pa", "HernandoPA"),
    "fl_martin": ("martin_pa", "MartinPA"),
    "fl_okeechobee": ("okeechobee_pa", "OkeechobeePA"),
}

# Counties graduated off the scaffold to the shared qPublic adapter. Their
# per-county modules still subclass LandmarkPAScaffold (module test below), but
# config + factory route them to qpublic_schneider_pa_http.
QPUBLIC_GRADUATED = {
    "fl_st_johns": ("st_johns_pa", "StJohnsPA"),
    "fl_clay": ("clay_pa", "ClayPA"),
    "fl_bay": ("bay_pa", "BayPA"),
    "fl_indian_river": ("indian_river_pa", "IndianRiverPA"),
    "fl_flagler": ("flagler_pa", "FlaglerPA"),
    "fl_monroe": ("monroe_pa", "MonroePA"),
    "fl_walton": ("walton_pa", "WaltonPA"),
    "fl_wakulla": ("wakulla_pa", "WakullaPA"),
    "fl_levy": ("levy_pa", "LevyPA"),
}

# Both sets still own a scaffold *module* (class subclasses the base).
ALL_SCAFFOLD_MODULES = {**SCAFFOLD_COUNTIES, **QPUBLIC_GRADUATED}


@pytest.mark.parametrize("county_id,modcls", ALL_SCAFFOLD_MODULES.items())
def test_scaffold_module_imports_and_subclasses_base(county_id, modcls):
    mod_name, cls_name = modcls
    mod = importlib.import_module(
        f"titlepro.property_appraiser.counties.{mod_name}"
    )
    cls = getattr(mod, cls_name)
    assert issubclass(cls, LandmarkPAScaffold)
    assert cls.LIVE_PLATFORM.endswith("_pa_http")
    assert "Property Appraiser" in cls.SOURCE_LABEL


def test_remaining_scaffolds_registered_in_config():
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    cfg = json.loads((repo / "config" / "county_property_appraiser_urls.json").read_text())
    counties = cfg["counties"]
    for county_id in SCAFFOLD_COUNTIES:
        assert county_id in counties, f"{county_id} missing from PA config"
        entry = counties[county_id]
        assert entry["platform"] == "landmark_pa_scaffold"
        assert entry["status"] == "scaffold"
        assert entry["base_url"].startswith("http")


def test_qpublic_graduated_counties_routed_to_shared_adapter():
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    cfg = json.loads((repo / "config" / "county_property_appraiser_urls.json").read_text())
    counties = cfg["counties"]
    for county_id in QPUBLIC_GRADUATED:
        assert county_id in counties, f"{county_id} missing from PA config"
        entry = counties[county_id]
        assert entry["platform"] == "qpublic_schneider_pa_http"
        assert entry.get("app_id"), f"{county_id} missing app_id"
        assert "schneidercorp.com" in entry.get("qpublic_host", "")
        assert entry["base_url"].startswith("http")


@pytest.mark.parametrize("county_id", list(SCAFFOLD_COUNTIES))
def test_factory_routes_to_scaffold_soft_fails_never_raises(county_id):
    # P2b: the public factory contract is that adapters NEVER raise — they return
    # a PropertyAppraiserResult. A scaffold must surface PA_NO_RUNNER with a clear
    # not-implemented message naming the county, not crash the caller.
    for kwargs in ({"address": "123 Main St"}, {"apn": "00-00-00-0000-000-0000"}):
        result = fetch_property_appraiser(county_id, **kwargs)
        assert result.status == "PA_NO_RUNNER"
        assert "SCAFFOLD" in result.notes
        assert county_id in result.notes
        assert "not yet implemented" in result.notes
        # Anchor is loudly absent, never silently empty-but-success.
        assert result.apn == ""
        assert result.fetched_at  # factory backfills the timestamp


@pytest.mark.parametrize("county_id,modcls", ALL_SCAFFOLD_MODULES.items())
def test_scaffold_preflight_still_raises_for_dev_signal(county_id, modcls):
    # The dev-only preflight() hard signal is preserved (NOT on the factory path):
    # a developer wiring a new county still gets a loud NotImplementedError.
    mod_name, cls_name = modcls
    mod = importlib.import_module(
        f"titlepro.property_appraiser.counties.{mod_name}"
    )
    cls = getattr(mod, cls_name)
    adapter = cls({"county_id": county_id, "base_url": "https://example.test"})
    with pytest.raises(NotImplementedError):
        adapter.preflight("address")
    # And the lookups themselves soft-fail rather than raise.
    assert adapter.lookup_by_address("x").status == "PA_NO_RUNNER"
    assert adapter.lookup_by_apn("y").status == "PA_NO_RUNNER"
    owner_results = adapter.lookup_by_owner_name("z")
    assert owner_results and owner_results[0].status == "PA_NO_RUNNER"
