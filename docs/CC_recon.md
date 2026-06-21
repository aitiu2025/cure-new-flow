# Contra Costa Recorder Recon — 2026-05-13

## Verdict
- **Reuse existing adapter:** YES — `RecorderWorksAdapter`
- **Confidence:** HIGH
- **Estimated work to wire up:** ~10–15 minutes (config JSON + registry entry only; no adapter code changes required)

The site is a vanilla RecorderWorks deployment hosted by the vendor at `crsecurepayment.com/RW/`
(instead of a county-branded subdomain like `cr.occlerkrecorder.gov/RecorderWorksInternet/`).
Page title is literally `"RecorderWorks"`. All form-field IDs use the
`MainContent_MainMenu1_SearchByName1_*` prefix exactly like Orange/Amador/Imperial/Merced/Stanislaus.
The result table uses `tr.searchResultRow` rows with the same
`EntityTitleDocNum_docNumber` / `docTypeGrtGrteeContainer` structure already handled by
`RecorderWorksAdapter.extract_results()` Strategy 1.

## URLs
- **Entry / Name Search:** `https://crsecurepayment.com/RW/?ln=en`
- **Post-acceptance landing:** *(no disclaimer; entry IS the post-acceptance landing)*
- **Name Search:** same URL, accessed by clicking the `Name` tab. The tab navigation is in-page
  (anchor `href="#tabs-nohdr-2"`), so no URL change. Form posts back to the same URL.

## Navigation steps (the "2 clicks")
The master sheet noted "2 clicks". Actual observed behavior is **1 click** (no disclaimer page):
1. Navigate to `https://crsecurepayment.com/RW/?ln=en` (entry already shows the tabbed nav).
2. Click `<a>Name</a>` — XPath: `//a[contains(text(), 'Name')]` — to switch to the Name Search panel.
3. *(No third click needed.)*

If counter-evidence later shows a disclaimer page, it likely appears only on first visit per session
or via cookie state we didn't trigger. The probe found **no** "I Agree" / "Accept" / "Continue" button
on first load (see `entry_clickables` in `findings.json`).

## Selectors

| Purpose                     | Strategy | Locator                                                        |
|----------------------------|----------|----------------------------------------------------------------|
| Disclaimer accept           | n/a      | *(none observed)*                                              |
| Name search nav             | XPath    | `//a[contains(text(), 'Name')]`                                |
| Party type dropdown         | ID       | `MainContent_MainMenu1_SearchByName1_partytype`                |
| Name input (combined)       | ID       | `MainContent_MainMenu1_SearchByName1_nameForSearch`            |
| Start date                  | ID       | `MainContent_MainMenu1_SearchByName1_FromDate`                 |
| End date                    | ID       | `MainContent_MainMenu1_SearchByName1_ToDate`                   |
| Partial match checkbox      | ID       | `MainContent_MainMenu1_SearchByName1_allowPartial`             |
| Search button               | ID       | `MainContent_MainMenu1_SearchByName1_btnSearch`                |
| Results table (rows)        | CSS      | `tr.searchResultRow`                                           |
| Doc number cell (per row)   | CSS      | `span#EntityTitleDocNum_docNumber.enableHighlight`             |
| Grantor/Grantee/DocType     | CSS      | `td#docTypeGrtGrtee` (combined) within `.docTypeGrtGrteeContainer` |
| No-results indicator        | text     | `0 Result` substring on page body                              |
| Back to Search              | XPath    | `//a[contains(text(), 'Back to Search')]`                      |

### Key delta vs Orange config
- Orange date fields: `_startdate` / `_enddate`. **Contra Costa: `_FromDate` / `_ToDate`.**
- Orange party types include `Grantor/Grantee`. **Contra Costa offers only: `All`, `Grantor`, `Grantee`.**
  Adapter's existing fallback logic (`_set_party_type`) already handles this by falling back to `All`.

## Date constraints
- **Format:** `MM/DD/YYYY` (placeholder reads `MM/DD/YYYY`)
- **Indexes available:** 1/1/1986 through 5/12/2026 (per on-page help text)
- **Max window:** None observed — accepted `01/01/2000` to `05/13/2026` (26-year window) without complaint
- **Min start:** 1/1/1986

## Test search outcome
- **Query:** `Montoya Marcelino` / party type `All` / partial match `True` / `01/01/2000` to `05/13/2026`
- **Result count:** **25 results** (paged 20 + 5)
- **Doc number format:** `YYYY-NNNNNNN` (e.g., `2026-0022802`, `2005-0444041`).
  Already supported by existing flexible regex `^\d{4}-\d+$` in adapter.
- **Sample row (text extraction via `searchResultRow` cells):**
  ```
  ['', '', '2026-0022802', '2026-0022802',
   'MONTOYA MARCELINO\n\n\t\t\n\nDEED OF TRUST',
   '3/9/2026', '11']
  ```
- **Sample row outerHTML (truncated, full copy in `/tmp/cure_titlepro_probe/cc/row_sample.json`):**
  ```html
  <tr id="row1" class="searchResultRow" role="presentation">
    <td id="CheckBoxTD"> ...checkbox table... </td>
    <td id="tdDocNum">
      <span id="EntityTitleDocNum_docNumber" class="enableHighlight">2026-0022802</span>
      <input id="EntityTitleDocNum_docId" type="hidden" value="21293401">
    </td>
    <td id="docTypeGrtGrtee" colspan="4">
      <!-- .docTypeGrtGrteeContainer with .GrtContainer / .GrteeContainer / .GrGrteeContainer / .DocTypeContainer -->
    </td>
    <td>3/9/2026</td>
    <td>11</td>
  </tr>
  ```
  This is **byte-for-byte the same structure** as Orange's new RecorderWorks rendering,
  which means `RecorderWorksAdapter.extract_results()` Strategy 1 (the `searchResultRow` branch)
  will work out of the box.

## Comparison to RecorderWorks-style sites
Per platform fingerprint check:
- Page `<title>RecorderWorks</title>` — explicit
- All ASP.NET WebForms control IDs (`ctl00$MainContent$MainMenu1$SearchByName1$...`) match Orange exactly
- Same tabbed UI (`Home / Name / Document Number / Document Type / Map / Recording Date / Book and Page / Old Book / Options`)
- Same "Predefined Search Types" widget, same `allowPartial` checkbox, same `btnSearch`
- Same results envelope: `25 Result(s)`, `Back to Search`, `Add To Shopping Cart`, paging table
- **NOT** Telerik RadGrid (`rgMasterTable`/`rgRow`) — uses newer `tblResultMain` / `searchResultRow`
  layout (the modern RecorderWorks design that adapter Strategy 1 already targets)

This is therefore a RecorderWorks site, hosted at the vendor's shared payment domain rather
than a county subdomain. The `/RW/` in the path is the same product family as `/RecorderWorksInternet/`.

## Recommended config
Drop into `src/titlepro/search/ca_recorder/counties/config/contra_costa.json`:

```json
{
  "county_id": "contra_costa",
  "county_name": "Contra Costa",
  "state": "CA",
  "platform": "recorderworks",
  "base_url": "https://crsecurepayment.com/RW/?ln=en",
  "search_url": "https://crsecurepayment.com/RW/?ln=en",
  "captcha_required": false,
  "name_format": "Last First",
  "name_separator": " ",
  "date_format": "MM/DD/YYYY",
  "doc_number_pattern": "^\\d{4}-\\d{5,}$",
  "doc_number_patterns": [
    "^\\d{4}-\\d{5,}$",
    "^20\\d{10,11}$"
  ],
  "party_types": ["All", "Grantor", "Grantee"],
  "default_party_type": "All",
  "selectors": {
    "name_tab": "//a[contains(text(), 'Name')]",
    "party_type_dropdown": "MainContent_MainMenu1_SearchByName1_partytype",
    "name_field": "MainContent_MainMenu1_SearchByName1_nameForSearch",
    "start_date_field": "MainContent_MainMenu1_SearchByName1_FromDate",
    "end_date_field": "MainContent_MainMenu1_SearchByName1_ToDate",
    "partial_match_checkbox": "MainContent_MainMenu1_SearchByName1_allowPartial",
    "search_button": "MainContent_MainMenu1_SearchByName1_btnSearch",
    "results_table": "//table[contains(@class, 'tblResultMain')]",
    "result_rows": "tr.searchResultRow",
    "no_results": "//*[contains(text(), '0 Result')]",
    "back_to_search": "//a[contains(text(), 'Back to Search')]",
    "result_count": "//*[contains(text(), 'Result(s)')]"
  },
  "notes": "Hosted on vendor domain crsecurepayment.com (not a county subdomain). No disclaimer/CAPTCHA. Doc# format YYYY-NNNNNNN (Amador style). Date field IDs differ from Orange: FromDate/ToDate (not startdate/enddate). Party types limited to All/Grantor/Grantee — no combined option. Indexes available 1/1/1986 through current."
}
```

## Notes / gotchas
1. **Date field ID delta** — adapter's default selectors (`startdate`/`enddate`) WILL NOT WORK here.
   The config override above is required, OR rely on the adapter's `_set_dates()` heuristic which
   scans for any input with "date" in id/name (which would match `FromDate`/`ToDate`). Belt-and-suspenders:
   keep the explicit selectors in config in case the heuristic regresses.
2. **No "Grantor/Grantee" combo party-type** — adapter already falls back to `All` (see
   `_set_party_type` lines 232–239 in `recorderworks_adapter.py`). Setting
   `"default_party_type": "All"` makes this explicit.
3. **No disclaimer page** observed on first load. If it appears later (e.g., new session/cookie),
   we can add a `disclaimer_selector` field and a one-time click in `navigate_to_search()`.
4. **Same hostname as multiple counties?** `crsecurepayment.com/RW/` is the vendor's shared
   payment URL. The site detects which county based on session state (perhaps a referrer header
   or a `?ln=en` query param that's missing). The visible "CountyGreetingContainer" shows
   "Welcome to the Contra Costa County Clerk-Recorder's Official Records Index", so the site
   IS scoped to Contra Costa when entered via this URL. **Recommend monitoring** in case the
   vendor changes routing — if other RW counties switch to this domain they'd collide.
5. **Doc detail / image download** — the doc number cell wires an `onclick` calling
   `detailsContainer.showDetails(event, ...)` with a `docid` integer (e.g., `docid=21293401`).
   This means image downloads from the recorder itself require either clicking the row or
   reconstructing the `showDetails` URL. **Per the task scope, image downloads are TitlePro247's
   job** — but Step 2 should verify whether `selenium_downloader.py` / TitlePro247 has a
   working entry for Contra Costa (master sheet says "shared TitlePro247 image-download URL").
6. **Pagination** — 25 results split as 20 + 5 across 2 pages. Existing adapter does NOT yet paginate.
   Step 1 should decide whether to (a) bump default page size to 100 via the Options panel
   (`Options` tab → `100 items per page`) or (b) add a paging loop in `extract_results()`.
   For most title searches, 25–50 results is the norm — page size 100 should cover most cases.

## Artifacts
All saved under `/tmp/cure_titlepro_probe/cc/`:
- `01_entry.png` / `01_entry.html` — landing page (already shows tabbed nav, no disclaimer)
- `02_after_accept.png` / `02_after_accept.html` — same page (no accept needed)
- `03_name_search.png` / `03_name_search.html` — after clicking `Name` tab
- `04_form_filled.png` — form with "Montoya Marcelino", dates, and party type set
- `05_results.png` / `05_results.html` — results page showing 25 results
- `findings.json` — complete probe data dump (clickables, form inventory, selectors observed, result-table inspection)
- `row_sample.json` — outerHTML of first 3 result rows + first part of `tblResultMain`
- `probe.py` — the probe script itself (for reproducibility)
