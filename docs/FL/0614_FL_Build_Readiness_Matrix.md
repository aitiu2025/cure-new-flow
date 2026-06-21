# FL Next-Batch Build Readiness — Code-Verified Matrix (0614)

**Date:** 2026-06-14
**Companion to:** `docs/FL/0614_FL_Next_Batch_County_Prioritization_Plan.md`
**Method:** verified directly against the codebase, not the plan — recorder
registry (`src/titlepro/search/recorder/counties/registry.py` + per-county
configs under `.../config/fl/`), PA registry/adapters
(`config/county_property_appraiser_urls.json` + `property_appraiser/counties/`),
and tax registry (`config/county_tax_urls.json`).

This answers: for the next batch, do we have the **recorder adapter**, the
**per-county config/logic**, the **tax recipe**, and the **Property Appraiser
adapter** coded and ready to test (while we wait on Tony's test subjects)?

Legend: ✅ coded/registered · 🟡 scaffold (wired, live probe pending) · ⚠️ skeleton (incomplete) · ❌ absent.

---

## Readiness by county and layer

| Tier / County | Recorder adapter | Recorder per-county config | Property Appraiser | Tax recipe |
|---|---|---|---|---|
| **Miami-Dade** | ⚠️ skeleton — adapter exists but all 7 search/download methods `raise NotImplementedError` pending a live probe | ✅ `miami_dade.json` (registered, stub) | ❌ not built | ❌ not registered (Grant St — trivial) |
| **Broward** *(reference)* | ✅ live | ✅ | ✅ | ✅ |
| **Landmark — Escambia** | ✅ `landmark_adapter` (proven Palm Beach + Lee) | ✅ `escambia.json` | 🟡 scaffold (this session) | ✅ |
| **Landmark — St. Johns** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Clay** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Hernando** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Bay** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Martin** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Indian River** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Citrus** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Flagler** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Monroe** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Walton** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Wakulla** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Levy** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **Landmark — Okeechobee** | ✅ | ✅ | 🟡 scaffold | ✅ |
| **OneCare — Pinellas** | ❌ no OneCare adapter; absent from registry | ❌ | ❌ | ❌ not registered (Grant St) |
| **OneCare — Lake** | ❌ absent from registry | ❌ | ❌ | ❌ not registered (Grant St) |
| **Tyler — Okaloosa** | ✅ reuses `tyler_http_adapter` (same tylerhost product as Orange) | ❌ absent from registry (config-only gap) | ❌ | ❌ not registered (Grant St) |
| **Tyler — Gadsden** | ❌ different product (`PublicInquiry.aspx`) — new adapter needed | ❌ | ❌ | ❌ not registered (Aumentum) |
| **Tyler — Taylor** | ❌ `PublicInquiry.aspx` — new adapter needed | ❌ | ❌ | ❌ not registered (PublicSoft) |

---

## What this means

**Landmark (14) is by far the most ready.** The recorder adapter is proven, all
14 per-county recorder configs are fully populated, and all 14 tax recipes are
registered. As of this session the missing PA layer is now **scaffolded** for all
14 (registered + wired + importable), so the only remaining work per county is a
live PA portal probe + parse implementation. This is the high-leverage block.

**Miami-Dade** needs real work on three layers: finish the recorder adapter
(implement the 7 stubbed methods after a live probe), build the MDCPA Property
Appraiser adapter, and register its tax (Grant Street).

**Tyler — Okaloosa** is cheap: it reuses the existing `tyler_http` adapter, so
it only needs a registry entry + config, plus a PA adapter and tax registration.

**Tyler — Gadsden / Taylor** and **OneCare — Pinellas / Lake** are the least
built: no recorder adapter/config exists yet (Gadsden/Taylor use a different
older Tyler `PublicInquiry.aspx` product; OneCare has no adapter at all), plus
PA and tax across the board.

**Bottom line:** end-to-end, no new county is 100% ready, because the
Property-Appraiser anchor (mandatory per the Broward Standard) is not yet
*implemented* for any target. But the gap is now concentrated and visible — for
Landmark it is purely the PA probe+parse step on top of an otherwise-complete stack.

---

## Subject-independent build backlog (do now, while waiting on Tony)

Priority order = readiness payoff per unit of effort.

1. **Implement the 14 Landmark PA adapters** (scaffolds already in place this
   session): per county, probe the portal → fill `lookup_by_address` /
   `lookup_by_apn` in `property_appraiser/counties/<county>_pa.py` → flip config
   `platform` from `landmark_pa_scaffold` to `<county>_pa_http` → add a factory
   branch + ≥10 fixture tests. This alone makes the 14 most-ready counties fully
   testable the moment subjects land.
2. **Miami-Dade**: live-probe the recorder portal → implement the 7 stubbed
   methods; build the MDCPA PA adapter; register Miami-Dade tax (Grant Street).
3. **Tyler — Okaloosa**: add registry entry + `okaloosa.json` (reuse `tyler_http`),
   build PA, register tax.
4. **Tyler `PublicInquiry.aspx` adapter** for Gadsden + Taylor; configs; PAs;
   tax (Aumentum for Gadsden, PublicSoft for Taylor).
5. **OneCare adapter** + Pinellas/Lake configs; PAs; tax registration.

All five are code-only and need no test subjects — exactly the wait-time work.

---

## Scaffolds delivered this session

- `src/titlepro/property_appraiser/counties/_scaffold.py` — shared `LandmarkPAScaffold` base (raises `NotImplementedError` until a county is implemented, so no empty anchor can ship).
- `property_appraiser/counties/{escambia,st_johns,clay,hernando,bay,martin,indian_river,citrus,flagler,monroe,walton,wakulla,levy,okeechobee}_pa.py` — 14 county modules with per-county probe checklists.
- 14 entries in `config/county_property_appraiser_urls.json` (`platform: landmark_pa_scaffold`, `status: scaffold`, best-known portal URL flagged **verify-on-probe**).
- Factory branch in `property_appraiser/__init__.py`.
- `tests/unit/test_landmark_pa_scaffolds.py` — structural tests (registration, import, factory routing, NotImplemented contract). Green.

> ⚠️ The scaffold portal URLs are best-known and **must be verified during the live probe** — they were not validated against the live portals in this pass.
