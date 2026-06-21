# Citrus County PA — live probe (observed 2026-06-17)

Probed live from a confirmed **US egress** (ipinfo → US). Observed, not assumed.

## Portal
- Landing: `https://www.citruspa.org/` → 302 → `https://www.citruspa.org/_dnn/`
  (**DotNetNuke / DNN** CMS shell on **Microsoft-IIS/10.0**, `x-powered-by: ASP.NET`,
  `.ASPXANONYMOUS` + `dnn_IsMobile` cookies).
- **Real search engine:** `https://www.citruspa.org/_web/search/` — a separate
  **Tyler Technologies "ProVal Web" / TrueAutomation EagleWeb-style** property-search
  app (the `_web/search/commonsearch.aspx` + `Disclaimer.aspx` + `advancedsearch.aspx`
  family). Page source carries `Tyler` branding + ASP.NET `__VIEWSTATE`.
- Search modes exposed:
  - `_web/search/commonsearch.aspx?mode=address` (Location Address)
  - `...?mode=owner` (Owner)
  - `...?mode=realprop` (Real Property / parcel)
  - `...?mode=persprop` (Tangible)
  - `_web/search/advancedsearch.aspx?mode=advanced`

## Anti-bot
- **No Cloudflare.** Plain IIS. A **Disclaimer gate** intercepts the first hit:
  `commonsearch.aspx?mode=address` → 302/redirect → `Disclaimer.aspx?FromUrl=...`
  (ASP.NET postback "I agree" before the search form renders). Handle like Escambia's
  VIEWSTATE accept flow.

## Search mechanism — SERVER-RENDERED ASP.NET WebForms (VIEWSTATE), Tyler ProVal
- GET `commonsearch.aspx?mode=<address|owner|realprop>` → land on `Disclaimer.aspx`
  → POST accept → GET/POST the search form → parse the results grid → follow the parcel
  link to a Tyler **`datalet.aspx`**-style detail page (owner / situs / legal / values /
  sales). (Confirm the exact detail URL + grid columns on the build probe — the disclaimer
  blocked a clean grid capture this pass.)
- This is the **Tyler/TrueAutomation EagleWeb** platform family — NOT qPublic, NOT BCPA.
  It is a DISTINCT cluster from Escambia (Escambia is plain ASP.NET `/CAMA/`, Citrus is
  Tyler `_web/search/`). Worth checking whether other FL counties (outside this 13) run
  the same `_web/search/commonsearch.aspx` engine before building — if so this becomes a
  reusable `tyler_eagleweb_pa_http` adapter.

## Adapter implication
**One-off** within this batch (only Citrus runs Tyler EagleWeb among the 13). Build
`citrus_pa_http`. Mirror = **Escambia `escambia_pa.py`** for the VIEWSTATE/disclaimer
mechanics, but the URL scheme + grid selectors are Tyler-EagleWeb-specific. Effort:
~1 adapter (medium — disclaimer + datalet parsing).
