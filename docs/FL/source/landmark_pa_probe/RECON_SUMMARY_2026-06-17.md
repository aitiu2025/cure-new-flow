# Landmark-county FL Property Appraiser recon — 13 portals (2026-06-17)

**Goal:** classify the 13 remaining Landmark-county PA portals by software platform so we
build SHARED parameterized adapters where they cluster, instead of 13 bespoke ones.

**Status:** RECON ONLY. No adapter code written, no config touched, nothing committed.
Egress was verified **US** (ipinfo → Seattle, US) before any live call; all calls used
`curl_cffi safari17_2_ios` where Cloudflare was present, ≤30 s timeouts, spaced ~3 s.

Per-county detail in `fl_<county>/probe_observed.md`. Reference DONE adapter = Escambia
(`src/titlepro/property_appraiser/counties/escambia_pa.py`, ASP.NET WebForms / VIEWSTATE).

---

## The headline finding

**8 of the 13 counties delegate their property search to ONE multi-tenant vendor app:
qPublic by Schneider Geospatial** (`qpublic.schneidercorp.com` / `beacon.schneidercorp.com`).
The county "websites" (mostly WordPress) carry no data — they link out to the same
Schneider app, keyed only by a per-county `AppID`. The Schneider app loads **identically**
by `AppID` alone with the **same ASP.NET control IDs** (`txtName` / `txtAddress` /
`txtParcelID`) for every county. → **One shared `qpublic_schneider_pa_http` adapter
unlocks 8 counties.** The remaining 5 are one-offs (1 Tyler EagleWeb + 3 custom JS/SPA + the
qPublic mechanics overlap noted below).

---

## 13-row classification table

| County | Portal host (landing) | Vendor / platform | Search mechanism | Anti-bot | Cluster id |
|---|---|---|---|---|---|
| bay | baypa.net (WordPress) | **qPublic / Schneider** AppID=834 | HTML grid — ASP.NET WebForms (VIEWSTATE) on `qpublic.schneidercorp.com` | Cloudflare (landing+app); curl_cffi safari17 passes; disclaimer gate; no CAPTCHA | **QPUBLIC** |
| clay | ccpao.com (WordPress) | **qPublic / Schneider** AppID=830 | HTML grid — ASP.NET WebForms (VIEWSTATE) | Cloudflare; curl_cffi safari17 passes; disclaimer gate | **QPUBLIC** |
| flagler | flaglerpa.com (WordPress) | **qPublic / Schneider** AppID=598 | HTML grid — ASP.NET WebForms (VIEWSTATE) | Cloudflare; curl_cffi safari17 passes; disclaimer gate | **QPUBLIC** |
| monroe | mcpafl.org (WordPress) | **qPublic / Schneider** AppID=605 | HTML grid — ASP.NET WebForms (VIEWSTATE) | Cloudflare; curl_cffi safari17 passes; disclaimer gate | **QPUBLIC** |
| wakulla | mywakullapa.com (WordPress) | **qPublic / Schneider** AppID=836 | HTML grid — ASP.NET WebForms (VIEWSTATE) | Cloudflare; curl_cffi safari17 passes; disclaimer gate | **QPUBLIC** |
| walton | waltonpa.com (WordPress) | **Beacon / Schneider** AppID=835 | HTML grid — ASP.NET WebForms (VIEWSTATE) | Cloudflare; curl_cffi safari17 passes; disclaimer gate | **QPUBLIC** |
| indian_river | ircpa.org | **qPublic / Schneider** AppID=1109 (App=IndianRiverCountyFL) | HTML grid — ASP.NET WebForms (VIEWSTATE) | No CF on landing; CF on qPublic app (curl_cffi passes); disclaimer gate | **QPUBLIC** |
| st_johns | sjcpa.gov (WordPress/WP Engine) | **qPublic / Schneider** AppID=960 (App=StJohnsCountyFL) | HTML grid — ASP.NET WebForms (VIEWSTATE) | CF (WP Engine) on landing; CF on qPublic app (curl_cffi passes); disclaimer gate | **QPUBLIC** |
| levy | qpublic.net/fl/levy (legacy) | **qPublic / Schneider** AppID=930 | HTML grid — ASP.NET WebForms (VIEWSTATE) | CF on qPublic app (curl_cffi passes); disclaimer gate | **QPUBLIC** |
| citrus | citruspa.org → `/_dnn/` (DotNetNuke) | **Tyler / TrueAutomation "ProVal Web" EagleWeb** (`_web/search/commonsearch.aspx`) | HTML grid — ASP.NET WebForms (VIEWSTATE) | No Cloudflare; **Disclaimer.aspx** gate; no CAPTCHA | TYLER-EAGLEWEB (one-off) |
| hernando | hernandopa-fl.us → **hernandocountypa-florida.us** | **Custom Blazor (.NET 8) SPA** (`propsearch.` subdomain; `_framework/blazor.web.js` + ArcGIS + EagleView) | **JS/SPA** → backend API (endpoint TBD) | No Cloudflare; no CAPTCHA; contentless shell (JS-rendered) | CUSTOM-SPA (one-off) |
| martin | pa.martin.fl.us → **pamartinfl.gov** (Apache/PHP/Joomla) | **Custom PHP app, GovernMax-derived** (`/app/search/` webpack bundles) | **JS app** → PHP/JSON backend (endpoint TBD) | No Cloudflare; no CAPTCHA; JS-rendered results | CUSTOM-SPA (one-off) |
| okeechobee | okeechobeepa.com (IIS/classic-ASP) | **Grizzly Logic** GIS (`/GIS/`) | **JS/GIS SPA** → handler/REST (endpoint TBD) | No Cloudflare; no CAPTCHA; contentless `/GIS/` shell | GRIZZLY (one-off) |

---

## Cluster groupings → shared-vs-bespoke adapter plan

### Cluster A — qPublic / Schneider (8 counties) → ONE shared adapter
**Counties:** bay (834), clay (830), flagler (598), monroe (605), wakulla (836),
walton (835, on `beacon.` host), indian_river (1109), st_johns (960), levy (930).
*(that's 9 listed — see note; levy/indian_river/st_johns confirmed qPublic too, so the
qPublic cluster is actually **9 of 13**, not 8. The 4 "one-offs" are citrus, hernando,
martin, okeechobee.)*

- **Build:** one shared `qpublic_schneider_pa_http` adapter, parameterized by `app_id`
  (and optional `app_friendly` name + `host` = `qpublic.` vs `beacon.`). Register all 9
  in `config/county_property_appraiser_urls.json` with
  `platform: "qpublic_schneider_pa_http"` + `app_id`.
- **Mirror template:** **Escambia `escambia_pa.py`** — same engine family (ASP.NET
  WebForms, VIEWSTATE/EVENTVALIDATION harvest → POST). Reuse its session/VIEWSTATE
  helpers verbatim; swap in qPublic's control IDs (`ctlBodyPane_ctl01_ctl01_txtName`,
  `..._ctl02_ctl01_txtAddress`, `..._ctl03_ctl01_txtParcelID`, per-panel `btnSearch`)
  and add the one-time **Disclaimer/agree postback** step.
- **Anti-bot:** Cloudflare on the Schneider app — use `curl_cffi safari17_2_ios`
  (proven; matches CLAUDE.md directive). No CAPTCHA.
- **Effort:** ~1 day for the shared adapter + parser + ≥10 unit tests against ONE county's
  captured fixtures; then each additional county is a **config-only** add (just the
  `app_id`) + a smoke live-run. This is the big win: **9 counties for ~1 adapter.**

### Cluster B — Tyler / TrueAutomation EagleWeb (1 county: citrus) → bespoke
- **Build:** `citrus_pa_http`. Mirror = Escambia for the VIEWSTATE+disclaimer mechanics,
  but Tyler's URL scheme (`_web/search/commonsearch.aspx?mode=...` + `Disclaimer.aspx` +
  `datalet.aspx` detail) and grid selectors are platform-specific.
- **Effort:** medium (~0.5–1 day). **Worth checking first** whether any *other* FL county
  (beyond these 13) runs the same `_web/search/commonsearch.aspx` engine — if 2+ do, make
  it a shared `tyler_eagleweb_pa_http` instead of a Citrus one-off.

### Cluster C — Custom JS/SPA, endpoint-discovery-bound (3 counties) → bespoke, DEFER
- **hernando** — custom **Blazor (.NET 8)** SPA on `propsearch.hernandocountypa-florida.us`
  (ArcGIS + EagleView). Data via a backend API the Blazor/JS calls — **not** in the HTML.
- **martin** — custom **PHP** app (`pamartinfl.gov/app/search/`, GovernMax-derived) with
  webpack `searchResults.js` bundles → PHP/JSON backend.
- **okeechobee** — **Grizzly Logic** `/GIS/` shell → handler/REST JSON.
- All three render results client-side, so the HTML alone is contentless. Each needs a
  **browser network capture** to discover the JSON/AJAX endpoint before an adapter can be
  written. Once the endpoint is known, each is a clean `curl_cffi` GET/POST → JSON parse
  (potentially *easier* than VIEWSTATE). No shared mirror (three different stacks).
- **Effort:** medium each, dominated by endpoint discovery. Defer behind A and B.

---

## Recommended build order (most counties unlocked first)

1. **`qpublic_schneider_pa_http` (Cluster A) — unlocks 9 counties.** Build + test against
   one county's fixtures (suggest **Clay 830** or **Bay 834** — clean WordPress→qPublic
   delegation, AppID-only load confirmed). Then add the other 8 as config-only `app_id`
   entries with a per-county smoke live-run. *Single biggest ROI by far.*
2. **`citrus_pa_http` (Cluster B, Tyler EagleWeb) — 1 county.** First spend ~15 min
   checking if other FL counties share the `_web/search/commonsearch.aspx` engine; if so,
   generalize to `tyler_eagleweb_pa_http`.
3. **Cluster C one-offs, in ascending discovery-cost / descending county-importance:**
   **martin** (PHP/JSON — likely the cleanest endpoint) → **hernando** (Blazor; capture the
   `_blazor`/`/api` route) → **okeechobee** (Grizzly; smallest/rural, lowest priority).
   Each requires a browser network capture first.

---

## Deferrals / flags

- **Cluster C (hernando, martin, okeechobee)** cannot be finished from an HTTP-only probe
  alone — they need a one-time **browser network capture** to reveal the JSON endpoint.
  Flagged as deferred; do them after the qPublic cluster + Citrus are shipping.
- **Cloudflare** is present on every qPublic/Schneider request (and on the bay/clay/
  flagler/monroe/wakulla/walton/st_johns landing pages). `curl_cffi safari17_2_ios` passed
  all of them this probe — do **not** pivot off curl_cffi (per CLAUDE.md).
- **Disclaimer/agree gates** exist on qPublic (all 9) and Citrus — the adapter must POST
  the accept before searching (same shape as Escambia's VIEWSTATE accept).
- **No CAPTCHA** observed on any of the 13.
- **Domain drift:** martin (`pa.martin.fl.us` → `pamartinfl.gov`), hernando
  (`hernandopa-fl.us` → `hernandocountypa-florida.us`), st_johns (`sjcpa.us` → `sjcpa.gov`),
  bay/flagler/wakulla/walton strip the `www.` → apex. Update the registered base_url to the
  final resolved host when wiring config.
- **Egress:** all FL county-hosted portals silently TCP-drop non-US egress. This probe ran
  from US; any future live build/test must re-verify US egress first.
