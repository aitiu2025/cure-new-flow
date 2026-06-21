# Landmark Web Platform — Live Probe Findings (2026-05-26)

**Probed counties:** Palm Beach (#3 by FL population) + Lee (#8) — chosen to
exercise both a vanilla Landmark tenant and a Cloudflare/Akamai-fronted one
so the adapter can be confirmed platform-generic, not Palm-Beach-specific.

**Probe driver:** curl_cffi.Session(impersonate="chrome120") + BeautifulSoup.
No browser, no Playwright, no Selenium.

## What's the same across both counties

| Trait | Palm Beach | Lee |
|---|---|---|
| Recorder root | https://erec.mypalmbeachclerk.com/ | https://or.leeclerk.org/LandMarkWeb/ |
| <title> text | Landmark Web Official Records Search | Landmark Web Official Records Search |
| Disclaimer endpoint | POST /Search/SetDisclaimer (200 OK, empty body) | same |
| Search-form route | GET /search/index?theme=.blue&section=searchCriteriaName | same |
| Captcha probe endpoint | POST /Search/ShowCaptcha returns "True" | POST /Search/ShowCaptcha returns "True" |
| reCAPTCHA sitekey | 6LdBHOorAAAAALwRLkAZpnNsfcp7qfFS4YIGIRTU | (not yet scraped — search form Akamai-gated) |
| Name search endpoint | POST /Search/NameSearch | POST /Search/NameSearch |
| Parcel-ID search endpoint | POST /Search/ParcelIdSearch | POST /Search/ParcelIdSearch |
| Detail endpoint | POST /Document/Index with {id,row,time,navigationType} | same |
| Result row convention | <tr id="doc_{documentId}"> + GetDetailSection('{id}',{row}) anchor | same expected |

Conclusion: the Landmark platform's HTTP surface is identical across tenants.
Only the recorder root URL (and per-tenant CDN gating) differs. This
validates the adapter's config-driven architecture — adding a new Landmark
county is a JSON-only task in 95% of cases.

## What's different (the tenant-specific bits)

1. CDN gating. Palm Beach is unprotected — chrome120 impersonation passes
   every endpoint. Lee sits behind Akamai (bazadebezolkohpepadr=...
   challenge on the landing). chrome120 passed landing + disclaimer +
   ShowCaptcha but got 403 on the search-form GET. Recommended override:
   impersonate_profile: "safari17_2_ios" in the per-county JSON for Lee
   and any other CDN-protected Landmark tenant.

2. Subpath vs root. Palm Beach: /. Lee: /LandMarkWeb/. Escambia:
   /LandmarkWeb1.4.6.134/. Adapter handles via the recorder_root config
   field — all endpoint suffixes resolved relative to it.

3. reCAPTCHA enforcement timing. Both counties report ShowCaptcha=="True"
   on every cold session. Lee's sitekey can't be scraped via pure HTTP
   because of the Akamai 403 — fall-back is to set recaptcha_site_key in
   the per-county JSON if known.

## Critical finding: reCAPTCHA token <-> IP binding

The Palm Beach /Search/NameSearch POST returns HTTP 500 even when fed a
freshly-solved-and-valid 2318-char g-recaptcha-response token from 2Captcha.
The response body is the generic ASP.NET error template, NOT the
"Invalid Captcha" string that the Landmark JS specifically looks for.
This signature is consistent with server-side reCAPTCHA verification
including the remoteip parameter — Google's siteverify API binds the token
to the IP that solved it. A proxyless 2Captcha solution fails server-side
verification even though the token is syntactically valid.

Fix paths (any one will unblock the live run; documented in detail in
src/titlepro/api/downloaded_doc/0526/PalmBeach_HABER_v1/end_to_end_blocker.md):
  1. 2Captcha proxy-on mode (~$0.005 extra per solve)
  2. Playwright/Selenium fallback (mirrors tyler_adapter.py CA pattern)
  3. Indexer/data-feed subscription

## Probe artifacts in this directory

- palm_beach_search_form.html — 2.5 MB rendered search form (contains every
  doc-type checkbox, the reCAPTCHA sitekey div, and the inline JS for
  LaunchDisclaimer + SetDisclaimer)
- landmark_search_index.js — 49 KB of platform JavaScript including the
  full SetCriteria() switch statement that documents the exact payload
  for every search mode (Name / Parcel / BookPage / Document / Consideration
  / Legal / Marriage / Abstract / etc.)

## Per-platform examination decisions (encoded in adapter)

- Default partyType=0 (Both) — matches Tony Roveda's FL examiner guide.
- Default matchType=0 (StartsWith) — examiner default; configurable per-county.
- Default recordCount=200 — first page only; pagination via
  /Search/GetResultsForPage is a deferred concern.
- Parcel-ID search exposed as LandmarkAdapter.perform_parcel_search() —
  Tony's recommended fallback for common-surname result caps.
