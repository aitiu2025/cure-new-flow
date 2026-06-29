# Source-of-Truth Verification (Step 0 — runs FIRST)

This is the **pre-flight check** for every CURE report verification. A report can only be trusted if the adapter and config it was generated against are in sync with the canonical county-data master sheet. Skipping this step means you might score a report PASS that was actually built against an out-of-date URL or selector configuration.

## The canonical master sheet

**Authoritative source:**
- `docs/County_URL_Mapping_CA_OH.md` (parent index, human-readable)
- `docs/County_URL_Mapping_CUREMasterSheet.xlsx` (authoritative spreadsheet)

The master sheet declares for each supported county:

| Column | What it asserts |
|---|---|
| Rank | County population rank |
| County | Display name |
| CountyURL (Recorder) | Live recorder portal URL — must match `config/<state>/<county>.json` `base_url` + `search_url` |
| Platform (Tax) | Tax-portal vendor (Grant Street / VisualGov / PublicSoft / etc.) |
| CAPTCHA | Whether the recorder portal serves a CAPTCHA |
| POST-CAPTCHA URL | Post-clearance URL pattern (if applicable) |
| TaxURL | Tax-portal entry URL — must match `config/county_tax_urls.json` |

When the master sheet changes, the following files MUST be kept in sync (this is the "Monday-update sync checklist" memorialized in `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/county_url_source_of_truth.md`):

1. `src/titlepro/search/recorder/counties/registry.py` — entry + platform
2. `src/titlepro/search/recorder/counties/config/<state>/<county>.json` — base_url, search_url, selectors
3. `config/county_tax_urls.json` — tax URL + vendor
4. `selenium_downloader.py` + `secrets.json TITLEPRO_URL` — image-download portal
5. `CURE.html` county dropdown (legacy UI; check if still in use)
6. `docs/FL/FL_Implementation_Plan.md` Wave-allocation table (if a county moves between waves)

If ANY of these are out of sync with the master sheet, the report under review was generated against an obsolete config — STOP verification and surface `SoT_DRIFT` to the caller.

## Step-0 procedure

### 1. Read `workflow_config.json` from the case folder

Identify:
- `county` field (e.g. `fl_broward`)
- `download_portal_county` (e.g. `fl_broward`, may differ from the recorder county for CA cases that use TitlePro247 fallback)
- `download_base_url` (the URL the bulk downloader actually hit)

### 2. Look up the county in the master sheet

```bash
grep -A 1 -E "^\| [0-9]+ \| <DisplayName>" \
  "docs/County_URL_Mapping_CA_OH.md"
```

Record the master-sheet values for: Recorder URL, Tax URL, CAPTCHA flag, Post-CAPTCHA URL.

If the county is not present → `SoT_MISSING_COUNTY`. The caller must add it to the master sheet before any verification is possible.

### 3. Compare master-sheet values against the adapter config

For each of these, confirm match:

| Master-sheet field | Adapter file | Field to compare |
|---|---|---|
| Recorder URL | `src/titlepro/search/recorder/counties/config/<state>/<county>.json` | `base_url`, `search_url`, `disclaimer_url` |
| CAPTCHA flag | same JSON | `captcha_required` |
| Tax URL | `config/county_tax_urls.json` | the county's tax URL |
| Tax Platform | same JSON | the county's platform name |
| Image-Download URL | `secrets.json` | `TITLEPRO_URL` |

Mismatches → `SoT_DRIFT`. Itemize each drift with the master-sheet value vs the config value.

### 4. Apply county-specific knowledge

Each supported county has known platform-level behaviour that affects how the verifier interprets the report:

#### Broward FL (`fl_broward`)
- **Platform:** AcclaimWeb (Telerik MVC skin), Cloudflare-fronted
- **Search column gotcha:** `document_type` in `search_results.json` contains the GRANTEE NAME (e.g. "TRUIST BANK"), NOT the actual doc type. Verifier must use `phase1_verifications.json` → `document_type_classifications` for real types, not the search column.
- **CSS class for result rows:** `tr.t-alt` (Telerik), NOT `tr.k-master-row` (Kendo). If `extract_results()` JS uses Kendo selectors only → expect `[N, 0, 0, 0, 0, 0]` state-contamination signature in `search_results.json`.
- **Cloudflare:** plain `requests` returns 403 `cf-mitigated: challenge`. Only `curl_cffi.Session(impersonate="safari17_2_ios")` passes both GET and POST.
- **CPX docs (Court Papers Hidden from Web):** statutorily blocked under FL Ch. 2002-302. Reports referencing such a doc number MUST carry the verbatim statutory notice (see `prohibited_documents.json` and `_REPORT_NOTICES.md`).

#### Miami-Dade FL (`fl_miami_dade`)
- **Status:** `blocked_on_access_decision` per `src/titlepro/search/recorder/counties/config/fl/miami_dade.json`
- **Platform:** Proprietary (custom miamidadeclerk.gov SPA) — no public anonymous search
- **Access:** $1/exam UI route OR Developer API (both require account + payment)
- **Do not attempt verification of any Miami-Dade report** unless the case folder includes evidence of a successful authenticated session (look for cookies named `MDClerkAuth`, `api_key`, etc. in download manifest, or an admin note that the commercial-access decision has been made).
- See `docs/FL/miami_dade_probe.md` for the full 2026-05-21 probe report.

#### Hillsborough FL (`fl_hillsborough`)
- **Status:** PRODUCTION — recorder + tax + PA all live as of 2026-05-26.
- **Recorder platform:** `hillsborough_http` (pure-HTTP `HillsboroughHTTPAdapter`). Bare Microsoft-IIS with no anti-bot per the co-developer's `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/codev_title_abstractor_findings.md`. Reference case: FROMER 4004 W North B St (49 docs, both spouse searches non-zero).
- **Recorder portal URL:** `https://pubrec3.hillsclerk.com/Pubrec2/PubrecHome.aspx`
- **Tax platform:** `grant_street_http` — shared with Broward; `hillsborough.county-taxes.com` GovHub iframe → Algolia + GovHub 3-hop. Reference: FROMER tax `$791.67 PAID` 2025 (`tax_Hillsborough_FROMER_v1.json`).
- **Property Appraiser platform:** `hcpa_http` (`HillsboroughHCPA`) — REST/JSON service at `https://gis.hcpafl.org/CommonServices/property/search/`. Endpoints: `BasicSearch?address|folio|name=X`, `ParcelData?pin=X`, `Autocomplete?value=X&table=address`. Zero anti-bot. Reference: FROMER folio `1151460000` returned vesting QCD `2025214758` + back-chain 1971 WD `OR BK 2411 PG 752`.
- **Tax-column gotcha:** Hillsborough returns proper doc-type codes (`(D) DEED`, `(MTG) MORTGAGE`, `(SAT) SATISFACTION`) — no grantee-name-in-doctype corruption like Broward's AcclaimWeb. Trust `document_type` from `documents_found.json` directly.
- **Pre-2000 OCR caveat:** Image-only scanned mortgages 1986–1997 produce NO_ADDRESS verifier results (subject-address verifier correctly refuses to assert MATCH on insufficient evidence). Cross-confirm via grantor name + grantor index parity rather than failing the case.

#### Orange FL (`fl_orange`)
- **Platform:** Tyler Technologies (reuses CA Tyler adapter)
- **CAPTCHA:** reCAPTCHA v2 (handled by 2Captcha integration)
- **Test subjects:** GREER + MIRANDA (per Tony Roveda's first FL test batch)
- Verifier should expect Tyler-grid result row format (`tr.k-master-row`), not Telerik.

#### San Diego CA (`san_diego`) — reference CA case
- **Platform:** AcclaimWeb (CA tenant — uses Kendo grid, NOT Telerik like Broward)
- **No CAPTCHA**
- **Download path:** TitlePro247 fallback (per master sheet)
- If verifying a San Diego report, expect different CSS selectors than Broward in the adapter's `extract_results` JS.

#### CA RecorderWorks counties (Amador, Contra Costa, Imperial, Merced, Orange, Stanislaus)
- **Platform:** RecorderWorks (classic ASP.NET WebForms with `__VIEWSTATE`)
- No CAPTCHA
- Standard `tr.gvr-row` result-grid selectors

#### CA Tyler counties (18 total) — 5 no-CAPTCHA + 13 with reCAPTCHA
- **Platform:** Tyler Technologies
- CAPTCHA-protected counties wired through 2Captcha solver via `tyler_adapter.py` + `registry.py`
- Verifier should check that captcha_required counties have a captcha-resolution event in `workflow_status.json` if CAPTCHA actually fired

### 5. Tax recipe verification (when `fetch_tax` is enabled in workflow_config)

If the workflow ran tax lookup:
- Confirm the tax recipe used matches the county's `Platform (Tax)` per the master sheet
- Recipe files live in `config/tax_recipes/<county>.json`
- The 8 production CA recipes as of 2026-05-18: fresno, contra_costa, riverside, san_bernardino, san_diego, alameda, sacramento, santa_clara
- If the report claims TAX_SUCCESS but `tax_lookup_status.json` shows anything other than `status: "success"` → FAIL

## Step-0 outputs

The verifier MUST surface one of these as the FIRST line of the verification report:

- `SoT_PASS` — Master sheet, adapter config, tax URL, and image-download URL all agree. Proceed with Step 1.
- `SoT_DRIFT — <list of mismatches>` — At least one source is out of sync. Verification BLOCKED until reconciled. Itemize each mismatch with master-sheet value vs config value.
- `SoT_MISSING_COUNTY — <county_id>` — County not present in master sheet. Caller must add it before any verification can proceed.

## Common drift patterns

These have actually happened during the 2026-04 → 2026-05 development cycle — watch for them:

1. **Adapter JSON references an old portal URL** — happens when a county clerk migrates platforms (e.g. Riverside CA moved from RecorderWorks to Tyler). The `base_url` in the config may still point at the old portal.
2. **Tax URL has rotted** — county-taxes.net subdomain changes, especially when a county switches between Grant Street and VisualGov mid-year.
3. **CAPTCHA flag mismatch** — a county added or removed CAPTCHA protection mid-year. The master sheet was updated but the registry entry wasn't.
4. **TitlePro247 URL mismatch** — `secrets.json TITLEPRO_URL` doesn't match master-sheet image-download URL, usually because someone updated the master sheet but didn't sync the secrets file.

Each of these will produce reports that LOOK correct (the LLM is happy with what it sees) but were generated against stale endpoints — the verifier's Step 0 is the only mechanism that catches them.
