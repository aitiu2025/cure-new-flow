# Okeechobee County PA — live probe (observed 2026-06-17)

Probed live from a confirmed **US egress** (ipinfo → US). Observed, not assumed.

## Portal
- Landing: `https://www.okeechobeepa.com/` — **Microsoft-IIS/10.0**, classic ASP
  (`ASPSESSIONID...` cookie), a hand-built CMS. Page source references **Grizzly Logic**
  (the vendor that builds the PA's GIS + search).
- **Search/data app:** `https://www.okeechobeepa.com/GIS/` (Grizzly Logic GIS), with
  query-string entry points seen on the homepage:
  - `https://www.okeechobeepa.com/GIS/` (map)
  - `https://www.okeechobeepa.com/GIS/?GIS`
  - `https://www.okeechobeepa.com/GIS/?SalesReport`

## Platform — **Grizzly Logic** GIS/property-search (one-off)
- The `/GIS/` endpoint returns a tiny (~3.5 KB) shell titled "Okeechobee County
  Property Appraiser" with **no inline script/API references in the initial HTML** — the
  app is injected/framed and renders client-side. Grizzly Logic is a small FL PA vendor
  (also seen on a handful of other rural FL counties), not qPublic/Tyler/Schneider.

## Anti-bot
- No Cloudflare, no CAPTCHA. Plain IIS/classic-ASP. The obstacle is that `/GIS/` is a
  contentless shell — the parcel data + search endpoint must be discovered via browser
  network capture (the shell loads its real app/JS dynamically).

## Search mechanism — JS/GIS SPA, endpoint TBD
- On the build probe: open `/GIS/` (and `/GIS/?SalesReport`) with the network tab open,
  run an address/parcel search, and capture the XHR/handler the Grizzly app calls
  (Grizzly apps typically hit a `.ashx`/`.asmx` handler or a GIS REST service for parcel
  + sales JSON). Capture the search request + parcel-detail + sales-report responses.

## Adapter implication
**One-off, deferred** — `okeechobee_pa_http` after endpoint discovery. Smallest county of
the 13 (Okeechobee is rural/low-volume), so lowest priority. No in-repo mirror for the
Grizzly platform. If the GIS REST/handler returns clean JSON it's an easy `curl_cffi`
adapter once found; if it's a stateful classic-ASP postback it's closer to the Escambia
pattern. Effort: medium (discovery-bound). Defer to last.
