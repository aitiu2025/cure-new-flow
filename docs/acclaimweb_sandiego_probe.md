# AcclaimWeb (San Diego County) Probe Notes

## Direct probing results
- `curl https://arcc-acclaim.sdcounty.ca.gov/` -> **HTTP 403** (Akamai/CDN WAF blocks non-browser UA).
- `curl https://arcc-acclaim.sdcounty.ca.gov/AcclaimWeb/` -> 403.
- `curl https://arcc-acclaim.sdcounty.ca.gov/AcclaimWeb/Search/SearchTypeName` -> 403.
- WebFetch (tool) -> permission denied in sandbox.
- Conclusion: Live probing must be done via Selenium with full browser UA + stealth flags. Real Chrome (webdriver_manager) routinely passes this WAF on sister sites.

## Inferred AcclaimWeb structure
(Derived from `docs/FL_Examples.md` — Broward, Brevard, Volusia, St. Lucie, Pinellas, Lee all run AcclaimWeb. Patterns are consistent.)

**Vendor:** Acclaim Systems Inc., ASP.NET MVC/Razor. NOT classic WebForms — there is no big `__VIEWSTATE` blob for the search form (it uses AJAX POST against MVC actions). A small `__RequestVerificationToken` antiforgery hidden field is present and is sent automatically by the form.

**URL routes (canonical AcclaimWeb pattern):**
| Step | URL |
|---|---|
| Landing / disclaimer | `/AcclaimWeb/` or `/AcclaimWeb/Disclaimer` |
| Home dashboard (post-disclaimer) | `/AcclaimWeb/Home/Index` |
| Name search | `/AcclaimWeb/search/SearchTypeName` |
| Doc-number search | `/AcclaimWeb/search/SearchTypeDocType` |
| Detail page | `/AcclaimWeb/Details/Index?docId=<GUID>` |
| Image viewer | `/AcclaimWeb/Image/ViewImage?docId=...` |

**Disclaimer acknowledgment:** single button or link click. Sister-site selectors:
- `//a[contains(text(),'I have read') or contains(text(),'agree')]`
- `//button[contains(text(),'Accept') or contains(text(),'I Agree') or contains(text(),'Continue')]`
- Some deployments add a precondition checkbox `input[type=checkbox]` that must be checked first.

**Name-search form (Razor MVC field naming convention):**
- Last name: `input#LastName` / `input[name="LastName"]`
- First name: `input#FirstName` / `input[name="FirstName"]`
- Party type: `select#PartyType` (values: `Grantor`, `Grantee`, `Both`)
- Date range: `input#DateFiledFrom`, `input#DateFiledTo` (MM/DD/YYYY)
- Doc-type multi-select: `#DocTypesDisplay` (leave empty for ALL)
- Submit: `button#btnSearch` (or `input[type=submit][value=Search]`)

**Results grid:** Kendo UI grid. Container `div#SearchResultsGrid`, content `.k-grid-content table`, rows `tr.k-master-row` (alt `tr.k-alt`). The doc-number cell is typically the first link cell pointing to `/AcclaimWeb/Details/Index?docId=<GUID>`.

**Doc-number format (San Diego ARCC):** `YYYY-NNNNNNNNNN` (e.g., `2024-1234567890`). Pre-2003: shorter `YYYY-NNNNNN`. Older still: `BOOK-PAGE`.

**No CAPTCHA** (confirmed by spec and CA URL master sheet).

**Image download:** San Diego ARCC historically gates unredacted image PDFs behind paid per-page fees. Free public preview is image-only via the viewer; downloadable PDFs may be paywalled. **Most likely outcome:** recorder-search returns metadata (`documents_found.json`), and the actual image-download phase falls back to TitlePro247 (the shared image-download URL already documented in `County_URL_Mapping_CA_OH.md`). This adapter therefore focuses on search + metadata extraction; image fetch is left as a `download_documents` TODO.

## Blockers / unknowns
1. **Akamai WAF** — verified on curl probes. Selenium with `--disable-blink-features=AutomationControlled` (already in RecorderWorksAdapter setup_driver) should pass, but worth flagging if first run gets challenged.
2. **Field IDs unconfirmed** — selectors above are inferred from sister Acclaim deployments. The first live run needs a 1-2 min interactive Selenium pass to confirm exact IDs and adjust the config JSON.
3. **Kendo grid pagination** — results may span pages (default 20/page). Skeleton handles page 1; pagination is a TODO.
4. **Image paywall** — confirmed risk; design assumes image fetch via TitlePro247 fallback.

## Confidence (per area)
- Disclaimer acknowledgment: 4/5
- Search-form submit + result-row extraction (metadata): 3.5/5
- Image download from AcclaimWeb directly: 2/5 (paywall risk; rely on TitlePro247 fallback)
- Overall search-only end-to-end: 3.5/5
