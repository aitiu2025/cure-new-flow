---
name: codev-title-abstractor-findings
description: What the co-developer's Hillsborough Title_Abstractor_Tools repo did/didn't solve — transferable insights vs the Cloudflare wall they never hit
type: reference
originSessionId: 3c98fcd9-98fe-4b81-b8f0-026a72f93e20
---
The co-developer (https://github.com/iamme2/AIProjects/tree/main/Title_Abstractor_Tools) claims "reversed REST API bypassing standard headless browser limits" for Hillsborough County FL. Investigation summary at `~/Downloads/Cure_Response/06_codev_title_abstractor_analysis.md`.

**Why this memory exists:** when CURE expansion hits a new FL county, check whether that county is bare-IIS (like Hillsborough) vs Cloudflare-fronted (like Broward) BEFORE designing the adapter. The bypass strategy differs fundamentally.

**How to apply:**

## The big disappointment
**Hillsborough has zero anti-bot.** `publicaccess.hillsclerk.com` and `gis.hcpafl.org` are bare Microsoft-IIS — no Cloudflare, no `cf-ray` header, no JS challenge. The co-developer's "no browser" stack is just `urllib.request` + a Chrome User-Agent. **None of this transfers to Broward** (which has real Cloudflare with both TLS-fingerprint and post-challenge cookie requirements).

For Broward (and any other Cloudflare-fronted FL county — see `docs/County_URL_Mapping_CA_OH.md`): use `curl_cffi.Session(impersonate="safari17_2_ios")` as the transport. Do NOT pivot to `urllib.request` or `cloudscraper` (both are blocked).

## Three transferable insights (despite the WAF difference)

### 1. Two-hop search pattern (use for ANY FL adapter)
```
property_appraiser.search_by_address(addr) → returns folio/PIN
property_appraiser.fetch_sales_history(pin) → returns recent deed instrument numbers
clerk_of_court.search_by_name(owner_from_pin) → returns full document list
```
This is FASTER and more accurate than name-only search because the PIN narrows the search to documents on the actual subject parcel. Use it as the "deed-first" implementation per Tony's #2 directive.

### 2. `viewModels.js` recon trick (use for any unknown county portal)
Tony's co-dev discovered Hillsborough's hidden JSON endpoints by GETting `/Scripts/viewModels.js` (or any front-end JS bundle) and grepping for URL templates. AcclaimWeb sites do similar — the inline JS contains data-source URLs that aren't documented anywhere else. Apply this as the FIRST step of any new-county adapter investigation: fetch the page, grep the inline JS for `/api/`, `/ajax/`, `Url:`, `url:`, `dataSource:`.

### 3. Spouse-delta alias discovery (use to honor Tony's #3 directive)
```python
docs_for_spouse_A = adapter.search_name("SIMMONS, SHANTELL")
docs_for_spouse_B = adapter.search_name("BARKER, SHANTELL")  # AKA
alias_only_docs = {d['document_number'] for d in docs_for_spouse_A} ^ {d['document_number'] for d in docs_for_spouse_B}
```
The symmetric-difference finds docs recorded under ONE name variant but not the other — exactly the kind of construction lien Tony found in his manual SIMMONS exam. The co-dev's `find_distinct_alana_docs.py` is the reference implementation.

## Their `released_mortgage_linker` is worse than ours
Their `analyze_history.py` treats modifications as still-open mortgages. Ours (`src/titlepro/verification/released_mortgage_linker.py`) explicitly classifies them as `modified` separately from `open`/`released`. Do NOT adopt their linker logic.

## Two small patches to apply to OUR linker
1. Add `DISCHARGE` to the satisfaction-doctype list (Hillsborough uses DISCHARGE where Broward uses SATISFACTION).
2. Add compact FL-anchor regexes for cross-reference text patterns (e.g., `"satisfies OR Inst.\s*\d+"`, `"of record at Book \d+, Page \d+"`).

## PDF generation: don't switch
Their `build_pdf.js` uses Puppeteer-core + headless Chrome CLI. We use WeasyPrint + xhtml2pdf. Headless Chrome gives them slightly better CSS support but the Chrome dependency is a heavyweight Node toolchain we don't need. Keep WeasyPrint.

## Open questions to ask the co-developer
- Did Hillsborough's HCPA require any auth setup or session cookies, or was the IIS truly stateless?
- Have they attempted any Cloudflare-fronted FL counties (Broward, Miami-Dade, Palm Beach)? If so, what was their fallback?
- Their `find_distinct_alana_docs.py` — does it handle 3+ co-owners or only pairs?
