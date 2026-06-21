# Walton County PA — live probe (observed 2026-06-17)

Probed live from a confirmed **US egress** (ipinfo → US). Findings are **observed**,
not assumed. This county is part of the **qPublic / Schneider Geospatial** shared
cluster — see `RECON_SUMMARY_2026-06-17.md` for the cluster build plan.

## Portal
- County landing: `https://waltonpa.com/` — a **WordPress** marketing site (no property data of
  its own). All record/parcel search links delegate OUT to Schneider qPublic.
- **Real search engine:** `https://beacon.schneidercorp.com/Application.aspx?AppID=835&PageType=Search`
- Platform: **qPublic by Schneider Geospatial** (a.k.a. "Beacon" / `qpublic.schneidercorp.com`).
  Multi-tenant **ASP.NET WebForms** app keyed by `AppID=835` (also accepts the
  numeric `AppID=835` directly — confirmed loads identically).
- County landing site is **Cloudflare-fronted** (plain `requests`/curl UA got HTTP 403; `curl_cffi` `safari17_2_ios` returned 200). The qPublic search app itself is **also** Cloudflare-fronted (`server: cloudflare`) and passes the same way.

## Anti-bot
- Cloudflare on the qPublic app. `curl_cffi.Session(impersonate="safari17_2_ios")`
  passes (matches the Broward/CLAUDE.md directive). No visible CAPTCHA on the search
  form. A one-time **Disclaimer / "agree" gate** is present (ASP.NET postback) before
  the search panel is usable — handle exactly like Escambia's VIEWSTATE flow.

## Search mechanism — SERVER-RENDERED ASP.NET WebForms (VIEWSTATE)
- Single page `Application.aspx?AppID=835&PageType=Search` exposes multiple search
  panels with stable control IDs (identical across every qPublic county — this is one
  app, many tenants):
  - **Owner Name:** `ctlBodyPane_ctl01_ctl01_txtName` (+ `chkNameExact`)
  - **Address:** `ctlBodyPane_ctl02_ctl01_txtAddress` (+ `chkExact`)
  - **Parcel ID:** `ctlBodyPane_ctl03_ctl01_txtParcelID`
  - Each panel has its own `...btnSearch` postback submit.
- Flow mirrors **Escambia (ESCPA)**: GET to harvest `__VIEWSTATE` /
  `__VIEWSTATEGENERATOR` / `__EVENTVALIDATION` → POST the disclaimer-accept (if gated)
  → POST the chosen search panel → parse the results grid → follow the parcel link to a
  `PageType=Details` (or `Datalet`) detail view carrying owner / situs / legal / values /
  sale history.
- Detail page key: qPublic detail is reached via `&PageTypeID=...&PageID=...&KeyValue=<parcelID>`
  style links emitted in the results grid (capture the exact KeyValue param when building
  the parser fixture).

## Fields available (qPublic standard detail layout)
Owner of record, mailing address, **situs/site address**, parcel/PIN, legal description,
land/building/just/assessed values (multi-year), homestead/exemptions, **sales history
grid** (date · price · deed book/page or instrument # · deed type — the back-chain),
year built.

## Adapter implication
Do NOT build a bespoke Walton adapter. This county is covered by the shared
**`qpublic_schneider_pa_http`** adapter, parameterized by `app_id=835`
(`AppID=835`). Mirror template = **Escambia `escambia_pa.py`** (same ASP.NET
VIEWSTATE postback pattern) + the qPublic-specific control IDs above. Register in
`config/county_property_appraiser_urls.json` with `platform: "qpublic_schneider_pa_http"`
and an `app_id` field.

## qPublic params for this county
- `app_id`: `835`
- friendly `App=`: `(numeric AppID only on county homepage)`
- search URL: `https://beacon.schneidercorp.com/Application.aspx?AppID=835&PageType=Search`
