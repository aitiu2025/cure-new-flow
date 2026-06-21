# Collier County (FL) Property Appraiser — Live Probe 2026-06-19

## Portal
- URL: https://www.collierappraiser.com/
- Platform: **County-custom frameset ASPX** (ASPSESSION cookie, custom JS, jQuery 3.6.1 + jQuery UI)
- Anti-bot: **Referrer-based block** at the ASP.NET application layer
  - All `/Main_Search/*.aspx` paths return HTTP 302 → `/system/error.html?aspxerrorpath=...`
  - This is a server-side 500 error (unhandled exception), NOT a CF/bot block
  - The frameset wraps the content but ASP.NET is throwing an application error on all RecordDetail.aspx calls
- Datacenter reachable: YES (200 on homepage), but search endpoints are broken server-side

## Portal Architecture
- Main page: `/index.html` or `/` — loads a frameset (frameset cols="*,1440,*")
  - left: `/sidepanel.html`
  - logo: `/nav.html` (navigation frame)
  - rbottom: `/Main_Search/search_rp.html` (property search UI)
- Search JS: `/Main_Search/search_rp.html` uses jQuery AJAX to call `/Main_Search/RecordDetail.aspx`
- `framed.js` enforces frameset context: direct loads redirect to `/index.html?page=<path>`
- `RecordDetail.aspx` requires being inside the frameset AND requires proper session/cookies
- Cookie: `ASPSESSIONID*` + `__Host-cookies-enabled=1`

## Why It's Blocked
- `/Main_Search/RecordDetail.aspx` (search endpoint) throws unhandled server exception regardless of headers/referrer
- The server returns `302 → /system/error.html?aspxerrorpath=/Main_Search/RecordDetail.aspx`
- This is an IIS 500 error, not a referrer block — the ASPX module has a configuration issue or database connectivity problem when called outside the expected session context
- Confirmed: tried with proper cookies, correct Referer, Sec-Fetch-Dest: frame — all return the same 302 to error.html
- The `/Main_Search/Security/blocked.html` redirect is for the search_rp.html page (referrer check) — but RecordDetail goes to error.html, which is a different issue

## Status: DEFERRED — Server-side broken endpoint
- The Collier PA ASPX search endpoint is functionally broken from HTTP (500-class error on all calls)
- This is consistent with the frameset's JS-enforced model: the actual search may rely on `$.ajax` with specific session state that's only populated when navigating through the JS UI
- **Unblock path**: Use Playwright/browser automation inside the frameset → let JS build the proper session state → then the AJAX calls to RecordDetail.aspx would succeed
- OR: network-capture from a real browser session to find the actual XHR payload that RecordDetail.aspx accepts
- Note: This pattern is the same as the "SPA-no-REST" deferred category (like hernando/martin/okeechobee)

## Config snippet (scaffold to add)
```json
"fl_collier": {
  "county_name": "Collier",
  "base_url": "https://www.collierappraiser.com",
  "platform": "landmark_pa_scaffold",
  "status": "deferred_spa",
  "notes": "Custom jQuery frameset app. /Main_Search/RecordDetail.aspx returns 500→error.html regardless of session/headers — appears to require JS-populated session state from the frameset UI. Unblock: Playwright browser session inside frameset → capture RecordDetail.aspx XHR payload → mirror in HTTP adapter."
}
```
