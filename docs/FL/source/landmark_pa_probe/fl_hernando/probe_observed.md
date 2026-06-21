# Hernando County PA — live probe (observed 2026-06-17)

Probed live from a confirmed **US egress** (ipinfo → US). Observed, not assumed.

## Portal
- Old landing `https://www.hernandopa-fl.us/` (IIS/ASP.NET) now emits a
  `<meta http-equiv="refresh">` → **new domain `https://hernandocountypa-florida.us/`**
  (Microsoft-IIS/10.0, `x-powered-by: ASP.NET`, `SRVNAME=hernandopa` cookie).
- **Real property search:** `https://propsearch.hernandocountypa-florida.us/`
  (dedicated subdomain). GIS map at `https://centralgis.hernandocountypa-florida.us/`.

## Platform — CUSTOM **Blazor (.NET 8) Web App** (one-off, modern SPA)
- `propsearch` subdomain serves a thin HTML shell (~6.5 KB) bootstrapping
  **`_framework/blazor.web.js`** (ASP.NET Core Blazor) plus county JS:
  `propertySearch.js`, `resultsExport.js`, `salesExport.js`, `ui.js`, an
  **ArcGIS JS 4.29** map, and an **EagleView** embedded-explorer widget.
- This is NOT a vendor PA product (not qPublic, not Tyler, not Grizzly) — it's a
  bespoke in-house Hernando app. Data is loaded **client-side via Blazor/JS**, so the
  parcel data comes from a backend API the JS calls (likely Blazor SignalR/HTTP or a
  REST endpoint behind `propsearch`), NOT from the initial HTML.

## Anti-bot
- No Cloudflare, no CAPTCHA on the shell. Plain IIS. The challenge is **discovering the
  JSON/API endpoint** the Blazor app calls (the HTML is contentless until JS runs).

## Search mechanism — JS/Blazor SPA hitting a backend (API shape TBD)
- The shell exposes no server-rendered grid. On the build probe, open
  `propsearch.hernandocountypa-florida.us` in a network-capturing browser, run an
  address/parcel search, and capture the XHR/fetch (Blazor often POSTs to a `_blazor`
  hub or a `/api/...` JSON route in `propertySearch.js`). Fetch `propertySearch.js` and
  grep for the endpoint paths it calls.

## Adapter implication
**One-off, deferred** — hardest of the 13 because there is no server-rendered HTML to
parse and the API contract is unknown until a browser network capture is done. Build
`hernando_pa_http` only after capturing the JSON endpoint. No good in-repo mirror (it's
not an ASP.NET-WebForms VIEWSTATE flow); once the JSON API is found it becomes a simple
`curl_cffi` GET/POST → JSON parse (easier than VIEWSTATE if the endpoint is clean).
Effort: medium-high (endpoint discovery is the cost). Defer behind the qPublic cluster.
