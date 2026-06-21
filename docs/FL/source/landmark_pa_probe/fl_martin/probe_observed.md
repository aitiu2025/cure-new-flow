# Martin County PA — live probe (observed 2026-06-17)

Probed live from a confirmed **US egress** (ipinfo → US). Observed, not assumed.

## Portal
- Old landing `https://www.pa.martin.fl.us/` → 302 → **`https://www.pamartinfl.gov/`**
  (new `.gov` domain). Server: **Apache**, `x-powered-by: PHP/8.2.29` — a
  **PHP / Joomla**-style stack (Joomla session cookie `1a656b3d...`, a
  `component/search/?format=opensearch` route).
- **Property search app:** `https://www.pamartinfl.gov/app/search/` (a distinct
  JS-driven app under `/app/`):
  - `/app/search/real-property`
  - `/app/search/sales`
  - `/app/search/subdivision`
  - `/app/search/advanced`
  - `/app/search/trim-notice`
  - `/app/search/personal-property`

## Platform — custom PHP app, **GovernMax / GovMax-derived** data search
- Homepage source references **GovernMax** (legacy Martin PA used a Manatron/Thomson
  GovernMax "MaxSearch" product). The current `/app/search/` is a modern **JS front end**:
  `searchResults.js`, `salesSearchResults~searchResults.js`,
  `vendors~salesSearchResults~searchResults.js` (webpack bundles) → results are rendered
  client-side from a backend query.
- jQuery 3.1.1 + an accessibility widget (`acsbap.com`). Not qPublic, not Tyler, not
  Grizzly, not Schneider.

## Anti-bot
- No Cloudflare, no CAPTCHA observed. Apache/PHP. A disclaimer string is present on the
  search shell. Main challenge is **the JS results pipeline** — the `/app/search/`
  page is a shell; results come from an XHR the `searchResults.js` bundle issues.

## Search mechanism — JS app hitting a PHP/JSON backend (endpoint TBD)
- On the build probe: load `/app/search/real-property`, run an address/parcel search
  with the browser network tab open, capture the XHR (likely a `/app/...` or
  `/index.php?option=com_...` JSON/AJAX route). Grep `searchResults.js` for the URL it
  fetches. Sales history is a separate route (`salesSearchResults`).

## Adapter implication
**One-off** — build `martin_pa_http` after capturing the JSON/AJAX endpoint. No in-repo
mirror matches a PHP-JSON flow (closest conceptually is BCPA's JSON path, not the
Escambia VIEWSTATE path). Once the endpoint is known, it's a clean `curl_cffi` GET/POST
→ JSON parse. Effort: medium (endpoint discovery + JSON map). Defer behind the qPublic
cluster, alongside Citrus.
