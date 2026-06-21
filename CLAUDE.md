# TitlePro CURE — Project Instructions

This file is loaded automatically by Claude Code sessions working in this repo. Read it FIRST before touching recorder-search code, adapter implementations, or pipeline phases.

## 🔒 Phase 1 Restructure — Tony Roveda's Six Directives (2026-05-22)

These six rules supersede prior assumptions about how recorder search should work. They came from Tony's Broward Test Review (`/Users/ag/Downloads/Broward County Test Review.docx`, summarized at `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/01_tony_review_findings.md`). The full plan + adversarial review are at `~/.claude/plans/async-wondering-tiger.md` and `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/05_synthesized_plan.md`.

1. **NO Selenium/Playwright in Phase 1 search.** Use HTTP GET/POST via `curl_cffi` + `safari17_2_ios` impersonation (proven to pass Broward's Cloudflare layer for both GET and POST). Legacy Selenium adapter (`acclaimweb_adapter.py`) is a fallback during the transition; the HTTP adapter is at `acclaimweb_http_adapter.py` — see `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/broward_http_adapter.md` for status.

2. **Deed-first search.** First search MUST be `DocType=DEED` (not "all"). Locate vesting deed → NLP-extract APN → re-search by parcel number for completeness (catches corporate-grantor priors and unrelated-name liens on the same parcel).

3. **Run EVERY provided name.** Husband + wife always. Cross-check vesting Deed# between both spouses' search results (joint conveyance vs separate property). Apply spouse-delta (`set(insts_A) - set(insts_B)`) to catch alias-only liens (this came from the co-developer's `find_distinct_alana_docs.py` — see `codev_title_abstractor_findings.md`).

4. **NLP-verify subject address.** Pull deed images, OCR them, run `titlepro.verification.subject_address_verifier.verify_subject_address(extracted, subject)`. Status != `MATCH` → reject the deed candidate with evidence in the report. This is the SIMMONS gate (CURE shipped a wrong-property QCD in 0521 because this check didn't exist).

5. **Examine EVERY indexed document.** If dedup or filter removes anything, the report MUST itemize it as "examined and excluded because X". Selectively dropping documents silently is what made the ANAND report 80% accurate instead of 100%.

6. **Released-mortgage exclusion.** Run `titlepro.verification.released_mortgage_linker.classify_mortgages(documents, extracted_texts)` post-extraction. Any mortgage with a linked satisfaction/release is `released`, not `open`. Don't ship released mortgages as open.

## 🔒 The `[N, 0, 0, 0, 0, 0]` Diagnostic Signature

If a recorder run's `search_results.json` shows only run 1 returning results and runs 2-6 returning zero, the adapter has a state-contamination bug. This was the root cause for both SIMMONS (`[12, 0, 0, 0, 0, 0]`) and ANAND (`[16, 0, 0, 0, 0, 0]`) in 0521. **Add a pipeline-level assertion** that raises `StateContaminationDetected` on this pattern rather than silently shipping partial data — see `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/state_contamination_assertion.md` for the exact assertion code.

**Root cause (fixed 2026-05-22):** `extract_results()` JS in `acclaimweb_adapter.py` hardcoded Kendo selectors (`tr.k-master-row, tr.k-alt`) but Broward emits Telerik (`tr.t-alt`). Strategy 2 fallback only succeeded on run 1 because `return_to_search` didn't actually navigate back. Fixed by broadening CSS selectors + forcing URL navigation in `return_to_search` + unioning Strategy 1 and Strategy 2.

## 🔒 The Cloudflare Reality (Broward, Miami-Dade, etc.)

Plain `requests` returns `403 cf-mitigated: challenge` on Broward. `cloudscraper`'s old JS-challenge solver is dead against current Cloudflare. **Only `curl_cffi.Session(impersonate="safari17_2_ios")` passes both GET and POST.** Chrome profile impersonations (chrome120/124/131) pass GET but get challenged on POST. Do NOT pivot off curl_cffi without revalidating against live Broward — every other library tested has been blocked.

The co-developer's Hillsborough Title_Abstractor_Tools repo uses bare `urllib.request` — that works for Hillsborough because Hillsborough has zero anti-bot (bare Microsoft-IIS). It does NOT transfer to Broward. See `codev_title_abstractor_findings.md`.

## 🔒 Live testing rules

Before testing against live Broward (or any FL Cloudflare county):

1. **Reuse cookies where possible.** The shared chrome user-data-dir at `~/.titlepro/chrome_profile_acclaim/` caches `cf_clearance` for ~30 days. If you blow it away you'll have to re-mint via a live disclaimer flow.
2. **Don't hammer.** Cloudflare rate-limits after ~5 rapid POSTs. Space test runs 30+ seconds apart.
3. **Capture state at each step.** The bug-reproducer at `tools/diagnostics/broward_state_repro.py` snapshots form HTML + cookies + screenshots between each search — emulate that pattern when debugging.

## 🔒 Reference paths

- **Plan:** `~/.claude/plans/async-wondering-tiger.md`
- **Discussion docs:** `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/` (6 markdown files: Tony review, Codex plan, adversarial review, state-contamination diagnosis, synthesized plan, co-dev investigation)
- **Per-topic memory:** `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/` — read `MEMORY.md` first, then the specific topic file you need
- **Bug-reproducer captures:** `docs/FL/source/broward_state_bug_repro/` (27 artifacts from 3 sequential searches)
- **Verification modules:** `src/titlepro/verification/{subject_address_verifier,released_mortgage_linker}.py` (350 + 314 LOC, 16/16 tests pass)
- **Test fixtures:** `tests/unit/test_acclaimweb_http_adapter_scaffold.py`, `test_subject_address_verifier.py`, `test_released_mortgage_linker.py` — all green as of 2026-05-22

## 🔒 What NOT to do

- ❌ Don't switch off `curl_cffi` for Cloudflare counties. Other libs are blocked.
- ❌ Don't ship a partial result set when one search returns 0 and another returns N. Raise instead.
- ❌ Don't treat modifications/subordinations as still-open mortgages. They have separate classifications.
- ❌ Don't "stand on" a QCD as the vesting deed. Show the WD chain first, then subsequent QCDs (per Tony).
- ❌ Don't pull a deed and ship it as the vesting without verifying its property address matches the subject (the SIMMONS gate).
- ❌ Don't run only the first provided name. ALL provided names must be searched, every time.
- ❌ Don't skip the **prior-owner name sweep**. A Two-Owner search isn't done when the provided names are searched: once the vesting deed identifies the grantor (the prior owner), run a recorder name search for that party over their ownership window (their acquisition date → vesting date + buffer) and disposition every mortgage found (released-of-record or PRIOR-OWNER POTENTIALLY OPEN with operator-confirm). Duval/SKINNER (0610) missed an unsatisfied 2005 MERS mortgage this way — the only PETER BETTER verdict of the batch; Volusia/GUILD's sweep caught what Peter missed. Verifier gate Q13 now FAILs reports that skip it.
- ❌ Don't ship customer reports with placeholder language like "manual fetch required", "to be confirmed", "not available", "outside search window" when the data IS retrievable via the recorder's direct-retrieval endpoint or the county Property Appraiser. Pull it. Cite it concretely. Placeholders defeat the entire purpose of the product. (See Quality Gates Q1-Q4 below.)
- ❌ Don't set `fetch_tax: false` to skip tax-lookup unless an engineering ticket text accompanies the report citing the missing adapter and the next-step path to build it.
- ❌ Don't ship a county report without a Property Appraiser anchor (`phase1_property_appraiser.json` + `phase1_reconciliation.json`). The PA anchor is the SIMMONS-gate enforcer and the ANAND back-chain recoverer — it's a quality baseline, not an optional add-on.

## 🔒 The Broward Standard (mandatory baseline for every new county)

Broward (BCPA + Grant Street tax + AcclaimWeb direct retrieval + verification stack) is the **floor**, not a stretch goal. Every new county MUST satisfy all seven items below before its case folder ships. Anything missing must be documented inline in the report as an engineering ticket — not as a customer-visible placeholder.

| # | Component | Broward reference | New-county work |
|---|---|---|---|
| 1 | **Property Appraiser adapter** (subject address → APN + owner of record + sale history) | `src/titlepro/property_appraiser/counties/broward_bcpa.py` (~310 LOC) | Probe live portal → mirror BCPA pattern → ≥10 unit tests → register in `config/county_property_appraiser_urls.json` → live-run for the case |
| 2 | **Tax lookup adapter** (actual paid/delinquent amounts via HTTP) | `src/titlepro/tax/grant_street_http.py` (~390 LOC) | Same pattern: probe → mirror → tests → register in `config/county_tax_urls.json` |
| 3 | **Recorder search adapter** (deed-first, all names, APN-anchored) | `acclaimweb_http_adapter.py` | One per portal platform (Tyler, Landmark, AcclaimWeb, bare-IIS, etc.) |
| 4 | **Direct-deed retrieval** by instrument # or book/page (`JumpToInstrumentNumber` / `JumpToBookPage` / equivalent) | `acclaimweb_http_adapter` `pull_detail` + the live `details/JumpToInstrumentNumber/27/<num>` pattern | Confirm the endpoint exists on the new portal during the recorder probe |
| 5 | **Subject-address verification** on every deed | `src/titlepro/verification/subject_address_verifier.py` | Already cross-county — just wire it for the new county's address format |
| 6 | **Released-mortgage linker** | `src/titlepro/verification/released_mortgage_linker.py` | Already cross-county |
| 7 | **Customer Title with ZERO placeholder language** + engineering RAW + `Tony_verified_commentary.md` companion | Set up by `tony_commentary_generator.py` + customer-language rules in `Title_Examination_Notes_System_Prompt.md` | Run the verifier (`verify-cure-report` skill) — its Quality Gates Q1-Q4 catch any placeholder leaks |

**New-county build order** (proven on Broward over ~2 days; should be ≤1 day each by following this template):

1. **Probe live** (≤30 min) — capture canonical request/response shape for each of: recorder search, recorder deed-detail, Property Appraiser by address, tax lookup by APN. Save to `/tmp/{county}_*_probe.md`.
2. **Mirror existing adapter** (≤2 hrs per adapter) — copy the Broward equivalent, swap URLs/field names, run tests against canned fixtures from the probe.
3. **Wire into pipeline** (≤1 hr) — register in the three config JSONs (`county_property_appraiser_urls`, `county_tax_urls`, county recorder config).
4. **Live-run the case** (≤30 min wall-clock + 2Captcha cost) — pipeline phases: search → download → extract → tax → PA anchor → reconciliation → RAW → Title → render → verify-cure-report.
5. **Verifier sign-off** — the `verify-cure-report` skill's 6-directive scorecard + Quality Gates Q1-Q4 must all be PASS (or WARN with a concrete engineering ticket; never bare FAIL).

**Anti-pattern: never start a new county case run without first confirming items 1+2 of this checklist exist.** Doing so produces the same "shipped with placeholders" outcome the 0526 batch had, which the user explicitly rejected on 2026-05-26 evening.

## 🔒 OnE vs Title content matrix (locked 2026-05-28 per Tony's review)

Two reports per case. Different audiences, different content scopes. **The Title is the engineering-side complete view; the OnE is the client-facing trimmed view.**

**Canonical OnE prompt:** `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md` (filename stays at v1.2 for stable referencing; current content version is **v1.7** per the Revision History block in the file).
**Canonical report DOCX renderer:** `python3 /Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/render_one_report_docx.py <input.md> <output.docx>` — pandoc default DOCX table model. The historical `reference.docx` is intentionally not auto-applied until rebuilt and render-verified because it caused v1.7 chain-table text to render outside empty grids. Canonical OnE output is **DOCX**; PDF is supplementary for visual review.
**Title prompt:** `Title_Examination_Notes_System_Prompt.md` at the project root. Section taxonomy (O1, TV1, TV2, TV3, M1, M2, J1, J2, T1, E1, E2, E3, E4, E5, D1) is documented in the prompt — the codes are internal-only and never printed in the customer report.

### Field-by-field matrix

| Field / Section | Title | OnE | Notes |
|---|---|---|---|
| Subject Owner & Property Examined (O1) | ✓ | ✓ (as §1 Report Header) | OnE strips internal review-scope metadata and "(as ordered)" sub-labels |
| Exam depth / back-chain note | ✓ | ✗ | Title records the two-owner chain depth; OnE shows County Effective Date only |
| (a)–(l) field-mapping codes | ✗ | ✗ | Retired in OnE v1.2; never in Title |
| Title Examination Summary (TV1) | ✓ | ✗ | Title-only summary block |
| Current Vesting — base fields (Vested Owners, Manner of Holding, Vesting Instrument, Instr#, Recorded, OR Book/Page, Grantor, Grantee) (TV2) | ✓ | ✓ (as §2 Current Vesting) | Both reports |
| Current Vesting — **Doc Stamps** | ✓ | ✗ | Title-only; OnE strips |
| Current Vesting — **Subject-Address Verification** result | ✓ | ✗ | Title-only; OnE strips |
| Current Vesting — **Subject To (per deed recital)** | ✓ | ✗ | Title-only; OnE strips |
| Current Vesting — **Prepared By** | ✓ | ✗ | Title-only; OnE strips |
| Prior Vesting chain | ✓ | ✓ (as §2 Prior Vesting) | OnE v1.7 shows a newest-to-oldest chain table through tenure-commencing instruments |
| Chain of Title (TV3) — full newest-to-oldest two-owner chain | ✓ | ✓ (trimmed v1.7 §2 chain) | Title is the complete superset; OnE may omit immaterial prior-tenure administrative interims only with connector note |
| Property-Appraiser Back-Chain / Sale History (E3) | ✓ | ✗ as a separate ledger | Title-only as a ledger; individual rows required by the v1.7 §2 chain may appear in OnE |
| Subject-Property APN Anchor / county tax-roll cross-check (E2) | ✓ | ✗ | Title-only; APN appears in OnE §1 + §8 only |
| Legal Description (Exhibit A) verbatim from vesting deed | ✓ | ✓ (as §8 Exhibit A) | OnE §8 must be on its own page with the boilerplate prefix "The following described land, situate, lying and being in [County] County, Florida, to-wit:" |
| Parcel Identification Number | ✓ | ✓ | Both, immediately below legal description |
| Source Instrument citation under Exhibit A | ✓ | ✓ | Both |
| Open / Active Mortgages (M1) | ✓ | ✓ (as §3) | Both |
| POTENTIALLY OPEN Mortgages | ✓ | ✓ (as §3 sub-block with ⚠️ DIRECT PAYOFF VERIFICATION REQUIRED warning) | Both |
| Reconveyed / Released Mortgages sub-table | ✓ | ✗ | **Title-only as of OnE v1.5** (locked 2026-05-28); OnE §3 is OPEN-only |
| HELOC modification chain (M2) | ✓ | ✓ (sub-table under parent §3 mortgage) | Both |
| Notes column on mortgage tables | ✓ | ✗ | Title-only; OnE retired Notes column |
| Judgments / Liens / Lis Pendens / UCC (J1) | ✓ | ✓ (as §4) | Both |
| Municipal-search / code-enforcement disclaimer | ✗ | ✗ | Forbidden in both (CURE is not paid/insured for municipal search) |
| Notices of Commencement / Construction-Lien Window (J2) — ACTIVE | ✓ | ✓ (as §7 if rendered) | OnE §7 is CONDITIONAL (see below) |
| Notices of Commencement — EXPIRED | ✓ | ✗ | Title-only; OnE §7 omits expired NOCs |
| Bankruptcy (PACER / state-court operator-verify) | ✓ (sidecar — usually omitted) | ✓ (as §5) | OnE §5 is operator-verify placeholder; acceptable phrasing |
| Tax Status / Property Tax Information (T1) — Tax Year, APN, Address, Just Value, Net Taxable, Exemptions, Annual Tax, Installment Status, Source, Captured At | ✓ | ✓ (as §6) | Both |
| **TRA / Taxing Authority Code / Millage District** rows | ✓ | ✗ | Title-only; OnE strips |
| Documents Examined (E1) — full inventory + Examiner Classification column | ✓ | ✗ | Title-only |
| Examiner Classification column | ✓ | ✗ | Title-only |
| Inaccessible / Prohibited Documents (E4 — FL Ch. 2002-302 statutory notice) | ✓ | ✓ (under §7 sub-block whenever a prohibited doc exists) | Both — required by statute when present |
| Miscellaneous Instruments — Non-Encumbering, Examined-and-Excluded (E5) | ✓ | ✗ | Title-only |
| Critical Issues callout (top of report) | ✓ | (retired in OnE v1.2; Critical Issues now appear inline within the affected sections, e.g., POTENTIALLY OPEN warning above §3 mortgage) | OnE v1.2+ removed the top-of-document callout block per Peter's directive |
| Recommendations block | ✓ | ✗ | Title-only |
| Disclaimer (D1) | ✓ | ✗ | Title-only |
| Page-1 layout | O1 + TV1 (Subject block + Examination Summary) | §1 Report Header (2-row table) | Different layouts per audience |
| PDF rendering doc_type | `TITLE_DOC_TYPE` (yellow/cream `#FFFDF0` + "LOGO" header-right) | `RAW_DOC_TYPE` (white background + "CURE TitlePro" header-right) | NEVER swap |
| Canonical output format | PDF + DOCX when client-editable Title is needed | DOCX (PDF supplementary) | DOCX path uses the canonical pandoc helper; visual QA is required after render |

### OnE §7 conditional-inclusion rule (locked 2026-05-28)

Render §7 ONLY when at least ONE of the following holds:
1. Active NOC on the subject parcel inside the statutory construction-lien window.
2. Subject-attaching open / unsatisfied administrative item (Declaration of Domicile material to ongoing homestead, lapsed-but-recent NOC inside extended statutory window, recorded administrative encumbrance not yet released).
3. Prohibited / statutorily-blocked document exists (FL Ch. 2002-302 or equivalent) — the statutory notice is required regardless.

OMIT §7 entirely otherwise. Released-mortgage satisfactions, expired NOCs, "examined-and-excluded" different-property recordings, personal civil actions where the subject is plaintiff, and pure-audit-trail content all stay in the Title only.
