# CA Implementation Update — Pause Point (2026-05-20)

> **🔒 SOURCE OF TRUTH for CA pickup.** This file is the comprehensive snapshot of California recorder-search + tax-lookup implementation status as of **2026-05-20**, at the moment work pivoted to Florida. Read this BEFORE resuming any CA work.
>
> Cross-references:
> - `docs/County_URL_Mapping_CA_OH.md` — canonical URL list
> - `docs/CA_Examples.md` — test subjects per county
> - `MEMORY.md` (auto-memory) — short-form session log
> - This file is referenced from MEMORY.md under "🔒 CA Pickup Point"

---

## Executive Summary

**End-to-end pipeline (search → download → extract → tax → AI → PDF → JSON/XML) verified working on 4 of 23 CA recorder counties + 1 OH county.** Major breakthrough this session: 2Captcha API integration for Tyler reCAPTCHA counties — SBD now runs fully unattended. Pivoted to FL work before completing the remaining CA batch; SD AcclaimWeb adapter exists but is untested live; Riverside Tyler adapter works but hits Tyler result-cap on common names; Sacramento/Alameda still lack adapters.

**Cost so far in 2Captcha API spend:** trivial — under $0.10 across all SBD test runs.

---

## What's WORKING end-to-end (verified 2026-05-20)

### Counties with full pipeline runs (RAW + Title reports generated)

| County | Subject | Adapter | Tax | RAW report | Title report | Notes |
|---|---|---|---|---|---|---|
| **Contra Costa** | MONTOYA Marcelino | recorderworks | ✓ playwright recipe | ✓ | ✓ | Full Exhibit A canonical-picker fix landed today |
| **Contra Costa** | WALTERS Jesse | recorderworks | ✓ playwright recipe | ✓ | ✓ | Pre-existing |
| **Fresno** | AMAYA Janine | tyler | ✓ playwright recipe | ✓ | ✓ | Pre-existing — confirms Tyler adapter works for narrow-name subjects |
| **Orange** | NAVA Gonzalo | recorderworks | ⚠ manual capture | ✓ | ✓ | Tax via user-supplied screenshot; legacy OC scraper broken pending Task #8 rewrite |
| **Orange** | Quintana | recorderworks | ✓ | ✓ | ✓ | Pre-existing |
| **Alameda** | AGIULERA | — | — | — | — | Search/download only — no adapter, used TitlePro247-direct path |
| **SBD** | MILES Cheyne | tyler + 2Captcha | not run | not run | not run | Search + download + extract complete via 2Captcha integration. 7 PDFs, 7 extracted .md. |
| **SBD** | ENGLISH Jason+Jessica | tyler + 2Captcha | not run | not run | not run | Same — 30 PDFs, 17 extracted .md. Multi-name search session-reused single CAPTCHA solve. |

### Tax recipes (`config/tax_recipes/*.json`) — 8 CA recipes shipped + verified

`alameda`, `contra_costa`, `fresno`, `riverside`, `sacramento`, `san_bernardino`, `san_diego`, `santa_clara` — all use the `playwright_form` runner with strict TAX_SUCCESS validation (APN echo + source-host whitelist).

### Pipeline phases (10 phases)

```
search → download → validate_downloads → extract_text →
extract_legal_descriptions → tax_lookup →
generate_raw_report → generate_title_notes →
render_pdfs → serialize_reports
```

All 10 phases verified working in isolation. `serialize_reports` added today wraps `build_json_xml_reports.build_case` and writes JSON+XML alongside the MD+PDF outputs (5-format set).

### 2Captcha integration (NEW today)

> **Foundational reference:** `docs/implementation_references/2Captcha_reCAPTCHA_Integration.md` — the original design doc (from a sibling Windows fork, dated 2026-02-16) that the implementation here is based on. Keep this around when extending 2Captcha to additional counties (FL Tyler, future RecorderWorks-with-CAPTCHA, etc.).

- `.env` at project root with `CAPTCHA_API_KEY` + `CAPTCHA_SERVICE=2captcha` (gitignored)
- `python-dotenv` + `undetected-chromedriver` installed (setuptools shim for py3.12 distutils)
- `server.py` loads dotenv on startup
- `registry.get_recorder()` auto-attaches `RecaptchaSolver` when county config sets `allow_automated_captcha_solver: true` (currently SBD + Fresno)
- `tyler_adapter._inject_recaptcha_token()` (4-strategy: data-callback / enterprise / safe `___grecaptcha_cfg` walk / button-enable)
- `_handle_captcha()` auto-solves via 2Captcha API before raising human checkpoint
- `_accept_disclaimer()` invokes CAPTCHA flow EARLY (before trying to click the disabled accept button)
- `_post_solve_advance()` clicks "I Accept" + navigates past disclaimer, OR re-submits search on results page
- **CRITICAL fix**: `grecaptcha.getResponse()` override so AJAX form-submit reads our 2Captcha token instead of empty
- `_read_recaptcha_textarea()` fallback for verifying token landed when `grecaptcha` API doesn't reflect external sets

Cost: ~$0.003 per CAPTCHA × ~1 CAPTCHA per subject = trivial.

---

## What's PARTIALLY working

### San Diego AcclaimWeb adapter (NEW today — UNTESTED LIVE)

`acclaimweb_adapter.py` shipped today with full Kendo-staleness handling: 5 helpers (`_retry_on_stale`, `_find_clickable`, `_find_present`, `_safe_click`, `_safe_send_keys`) + 8 functions refactored. Confidence 4/5 on staleness; 2/5 on PDF download (paywall — needs TitlePro247 fallback).

**First live test result:** `StaleElementReferenceException` — fix was applied AFTER this test. Has not been re-tested. **PRIORITY: re-test San Diego subjects before any further AcclaimWeb work.**

Also unlocks future FL counties: Broward, Brevard, Lee, Volusia, St. Lucie, Brevard all use AcclaimWeb variants (confirmed by URL).

### Tyler post-submit CAPTCHA loop (FIXED today, partial validation)

`_handle_captcha` now checks for visible results-table rows BEFORE raising `CaptchaCheckpointRequired`. SBD MILES + ENGLISH ran without this loop after the fix. Other Tyler+CAPTCHA counties (Fresno, Kings, Madera, etc.) untested with the fix but should benefit.

### Tyler 3-part name handling (FIXED today)

`_enter_name()` now truncates 3+ token names to LAST FIRST for the combined-name field. SBD MILES ("MILES CHEYNE A" → "MILES CHEYNE") confirmed working.

### Tyler modal-overlay click interception (FIXED today)

`return_to_search()` dismisses session-keepalive modals + falls back to JS click on `ElementClickInterceptedException`. Riverside STINSON crashed pre-fix; not yet re-tested.

---

## What's BROKEN / BLOCKED

### Orange County tax (Task #8 — DEFERRED)

Legacy `tax_lookup.py` scraper at `taxbill.octreasurer.gov` is broken — the post-CAPTCHA detail page is now an Angular SPA rendered inside an iframe; `body.text` reads only navigation chrome. **NAVA tax was captured manually via user screenshot.** Rewrite estimated 4-8 hrs; should migrate to `playwright_form` recipe pattern (same as Sacramento/SBD/Santa Clara recipes).

### Riverside common-name searches (NEW finding today)

FINKELSTEIN returned zero docs (likely Tyler result-cap — "ENCISO DANIEL" on Fresno returned 154/181 with similar issue). Name-only Tyler searches hit a server-side display cap for common surnames. **Architecture decision needed**: name-only search is the wrong tool for common names — see "Long-term" section.

### Sacramento + Alameda recorder adapters (NO ADAPTER)

Per research today: **Sacramento** uses a GRM AngularJS SPA (`recordersdocumentindex.saccounty.net`); **Alameda** uses Harris Recording Solutions / RecChart / Aumentum (`rechart1.acgov.org`). Both are NEW platforms not covered by RecorderWorks/Tyler/AcclaimWeb adapters. Estimated build: 4-8 hrs each.

### 8 pre-existing unit-test failures (NOT touched today)

Pre-existing test failures unrelated to today's adapter work:
- `test_cross_reference_checker.py` (3) — `extract_lien_type` undefined import
- `test_legal_description_validator_montoya_regression.py::test_existing_montoya_title_md_fails_verbatim_validator` — needs fresh MONTOYA fixture
- `test_parse_test_subjects.py::test_load_and_parse_subjects` — fixture issue
- `test_property_verification.py::test_address_apn_match` — needs `downloaded_doc/` fixtures
- `test_vesting_deed_analysis.py::test_gibberish_fallback` — assertion drift

None affect adapter behavior.

---

## Per-County Status Table (as of 2026-05-20)

| # | County | Recorder adapter | Tax recipe | Test subject(s) | End-to-end status |
|---|---|---|---|---|---|
| 1 | Alameda | ❌ (Harris/Aumentum, NEW platform) | ✓ playwright | AGIULERA (P1, search only) | TitlePro247-direct path only |
| 2 | Contra Costa | ✓ recorderworks | ✓ playwright | MONTOYA ✓, WALTERS ✓ | **FULL PIPELINE WORKS** |
| 3 | Fresno | ✓ tyler + 2Captcha | ✓ playwright | AMAYA ✓; ENCISO ⚠ (result cap) | **FULL PIPELINE WORKS for narrow names** |
| 4 | Los Angeles | — (No Data Online) | — | — | Blocked — Tapestry Plant access TBD |
| 5 | Orange | ✓ recorderworks | ⚠ broken (Task #8) | NAVA ✓ (manual tax), Quintana ✓ | **WORKS except tax** |
| 6 | Riverside | ✓ tyler | ✓ playwright | FINKELSTEIN ⚠ (result cap), STINSON ⚠ (untested with modal fix) | Search works, but result-cap blocks common names |
| 7 | Sacramento | ❌ (GRM SPA, NEW platform) | ✓ playwright | BURGER, CORNMAN (untested) | NO RECORDER ADAPTER |
| 8 | San Bernardino | ✓ tyler + 2Captcha | ✓ playwright | MILES ✓ (search/download/extract), ENGLISH ✓ | **SBD WORKING via 2Captcha** |
| 9 | San Diego | ✓ acclaimweb (NEW today) | ✓ playwright | THURSTON (untested), HEPLER (untested) | Adapter exists, Kendo fixes landed but UNTESTED LIVE |
| 10 | Santa Clara | — (No Data Online) | ✓ playwright | — | Tax recipe works (verified earlier); no recorder adapter |

Plus 13 small CA counties (Amador, Calaveras, Del Norte, Humboldt, Imperial, Inyo, Kings, Lake, Madera, Merced, Monterey, San Benito, San Joaquin, San Luis Obispo, Santa Cruz, Sierra, Stanislaus, Trinity, Tulare, Tuolumne, Yolo) with adapters configured but no test subjects.

---

## Immediate Next Steps (when CA work resumes)

Listed in dependency order:

### A. Validate the unfinished SBD batch (5 min)
The SBD MILES + ENGLISH subjects ran search/download/extract today but didn't continue to tax/AI/PDF/serialize. Just flip the workflow_config flags and run the remaining 6 phases — should produce 5-format reports. No new code needed.

### B. Re-test San Diego AcclaimWeb adapter (30 min)
The Kendo-staleness fixes landed but haven't been validated live. Run `SanDiego_THURSTON_Jason` + `SanDiego_HEPLER_David` end-to-end. Expect possible selector tuning on first live run.

### C. Validate Riverside fixes (15 min)
Re-run STINSON (multi-name) to verify the modal-overlay dismissal fix. FINKELSTEIN's "zero docs" issue is the result-cap problem (see Path C below) — separate from the adapter.

### D. Run Fresno ENCISO with a narrow date range (5 min)
ENCISO returned 181+ results over 2020-2025. The user paused before narrowing. Tighten the date range to a 1-2 year window once the actual subject's recording years are known. OR skip to Path C below.

### E. Re-run pending CA subjects per `CA_Examples.md`
After A-D, the remaining queue (excluding Alameda/Sacramento which need new adapters): ~5 subjects.

---

## Long-term improvements (when CA work resumes)

### 1. Use TitlePro247 as PRIMARY search source instead of recorder name-search

**The right architectural fix.** Name-only Tyler searches hit a result cap for common surnames (FINKELSTEIN, ENCISO both blocked). TitlePro247 is property-anchored — search by owner+address returns specific doc numbers for the specific property. Today we use TitlePro247 only for image downloads; bring it forward to be the search source for properties whose owner has a common name.

Eliminates the name-disambiguation problem entirely. Estimate: 1-2 days.

### 2. Sacramento adapter (GRM SPA) — 8-12 hrs

`recordersdocumentindex.saccounty.net` uses Angular + AJAX waits + possibly sign-on. Build a new `grm_adapter.py`. Unlocks Sacramento BURGER + CORNMAN.

### 3. Alameda adapter (Harris/Aumentum) — 4-6 hrs

`rechart1.acgov.org` uses Infragistics WebDataMenu. Static form, simpler than Sacramento. Build `aumentum_adapter.py`. Unlocks Alameda TAM.

### 4. OC Treasurer tax scraper rewrite (Task #8) — 4-8 hrs

Migrate the broken `tax_lookup.py` to the `playwright_form` recipe pattern (same as Sacramento/SBD/Santa Clara). Need to find the new SPA-friendly element selectors. Browse with iframe-aware extraction. Unlocks Orange tax across all subjects.

### 5. Tyler result-cap detection

Add a generic "more documents than maximum allowed" detector in `tyler_adapter.py`. When triggered, raise a `RetryableSubmitError` with `kind="result_cap"` so the workflow surfaces "search too broad" instead of misreporting "zero documents."

### 6. CSV export of generated reports

Optional — nice-to-have for batch dashboards.

### 7. Tony Roveda FL test subjects integration (when CA resumes after FL)

When FL adapters are ready, the test-subject coordination pattern proven for CA (CA_Examples.md) should be applied to FL too.

---

## Key files modified today (2026-05-20)

### Adapters
- `src/titlepro/search/ca_recorder/counties/adapters/tyler_adapter.py` — 7 patches: result-visibility CAPTCHA bypass, modal-overlay dismiss, 3-part name truncation, 2Captcha integration (`_inject_recaptcha_token`, `_post_solve_advance`, `_read_recaptcha_textarea`), grecaptcha.getResponse override, disclaimer CAPTCHA-gate handling
- `src/titlepro/search/ca_recorder/counties/adapters/acclaimweb_adapter.py` (NEW) — 5 Kendo helpers + 8 refactored functions

### Configs
- `src/titlepro/search/ca_recorder/counties/config/san_diego.json` (NEW) — AcclaimWeb
- `src/titlepro/search/ca_recorder/counties/config/san_bernardino.json` — `allow_automated_captcha_solver: true` + `combined_name_search: true`
- `src/titlepro/search/ca_recorder/counties/config/fresno.json` — `allow_automated_captcha_solver: true`
- `src/titlepro/search/ca_recorder/counties/config/riverside.json` — base_url fix + `combined_name_search: true`

### Registry
- `src/titlepro/search/ca_recorder/counties/registry.py` — san_diego entry, acclaimweb dispatch, auto-wire 2Captcha solver for CAPTCHA Tyler counties

### Server / env
- `.env` (NEW, gitignored) — CAPTCHA_API_KEY + CAPTCHA_SERVICE=2captcha
- `.gitignore` — added `.env`
- `src/titlepro/api/server.py` — dotenv loading at top

### Pipeline
- `src/titlepro/automation/pipeline.py` — `serialize_reports` phase + canonical legal-description picker (`_pick_canonical_legal_doc`)
- `src/titlepro/reports/build_json_xml_reports.py` (referenced) — already existed, now invoked via the new phase

### Test files
- `tests/unit/test_pipeline_serialize_reports.py` (NEW) — 5 tests
- `tests/unit/test_tax_dispatcher.py` — stub kwargs fix

### Docs
- `docs/County_URL_Mapping_CA_OH.md` — added FL section + sync date
- `docs/FL_Examples.md` (NEW), `docs/CA_Examples.md` (NEW), `docs/FL_Implementation_Plan.md` (NEW)
- `docs/County_URL_Mapping_CUREMasterSheet.xlsx` — merged v2 + v3 (Tony's platform classification) + 27 FL tax URL updates
- **THIS FILE** (`docs/CA_Implementation_Update_2005.md`)

---

## How to resume CA work

1. **Read this file end-to-end** (you're doing that now).
2. **Re-read `MEMORY.md`** for any newer session-level context.
3. **Pick a path** from "Immediate Next Steps" (A→E).
4. **Confirm 2Captcha balance** at https://2captcha.com (look at the .env account).
5. **Start the dev server** (`./venv/bin/python3 src/titlepro/api/server.py`) — confirms `[startup] tax recipes: 8 valid` + `CAPTCHA solver configured for {county}` lines fire for SBD/Fresno when those adapters are instantiated.
6. **Don't re-run subjects that are already done** — Contra Costa MONTOYA/WALTERS, Fresno AMAYA, Orange Quintana/NAVA are complete with 5-format reports under `src/titlepro/api/downloaded_doc/0513/`.

---

## Pause-point pinned (2026-05-20)

Last completed action: SBD MILES + ENGLISH search+download+extract via 2Captcha. Fresno ENCISO returned zero docs (result cap). Pivot to FL work begins immediately after this file is committed.
