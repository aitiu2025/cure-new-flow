---
name: verify-cure-report
description: Verify CURE TitlePro RAW (RAW_TWO_OWNER_SEARCH_EXAM.*), Title Examination Notes (Title_Examination_Notes.*), or OnE Ownership-and-Encumbrance (OnE_Report_*.{md,pdf}) reports against Tony Roveda's six directives + Peter Bodonyi's OnE template + known failure modes. Use when asked to verify, validate, audit, review, check, or grade a CURE report; or when comparing two case-folder report outputs.
---

# verify-cure-report — CURE TitlePro Report Verifier

## Mission

Audit a CURE-generated TitlePro report (`RAW_TWO_OWNER_SEARCH_EXAM.*`, `Title_Examination_Notes.*`, and/or `OnE_Report_*.{md,pdf}`) and produce a **structured PASS/FAIL/WARN report** scored against Tony Roveda's six abstractor directives, Peter Bodonyi's OnE template directives, the known regression signatures, and the production-quality reporting rules. This skill encapsulates everything we learned during the 2026-05-22/23 Broward Test Review remediation cycle PLUS the 2026-05-26 OnE-template alignment audit.

## When to invoke

### Abstractor-side reports (Title Notes + RAW)
- "Verify the SIMMONS report"
- "Check the ANAND 0522 output"
- "Audit / validate / grade this RAW report"
- "Did this report meet Tony's directives?"
- "Compare 0521 vs 0522 ANAND reports"
- "Find regressions in the latest Title Examination Notes"

### Client-side OnE reports (added 2026-05-26 per Peter Bodonyi's directive)
- "Verify the OnE report"
- "Audit / check the O&E for Anand"
- "Did the Ownership and Encumbrance Report follow Peter's template?"
- "Run Peter's verification on `OnE_Report_<Subject>.pdf`"
- "Are the (a)–(l) codes all present?"

## Background reading (must be loaded into context before scoring)

These files contain the verification ground truth:

1. **Tony's six directives:** `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/tony_review_directives.md`
2. **State-contamination signature:** `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/state_contamination_assertion.md`
3. **Project CLAUDE.md** (anti-patterns): `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/CLAUDE.md`
4. **Tony's review findings** (verbatim with response): `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/01_tony_review_findings_response.md`
5. **Co-developer alias trick:** `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/codev_title_abstractor_findings.md`

Skill reference files (next to this SKILL.md):

- `source-of-truth-verification.md` — **Step-0 pre-flight check. Always run FIRST.** Confirms the county URLs and config the report was generated against match the canonical master sheet.
- `directives-checklist.md` — Tony's six abstractor directives + the 4 Quality Gates Q1-Q4 (Broward Standard) as actionable checks (apply to RAW + Title Notes)
- `known-failure-modes.md` — Regression patterns to detect (F1-F15)
- `report-structure-reference.md` — Required RAW + Title sections and their validation rules
- `one-report-verification.md` — **Peter Bodonyi's OnE-report 10-check pack** (added 2026-05-26 per Peter's directive). Apply when the target file is named `OnE_Report_<Subject>.{md,pdf}`. References Peter's two source documents: `O&E Template CURE.docx` (blank template) + `Anand_report Template for O&E supplement.docx` (annotated example with Peter's review comments).

## Two verification tracks (route based on file type)

| File name pattern | Track | Reference file(s) |
|---|---|---|
| `RAW_TWO_OWNER_SEARCH_EXAM.*` | Abstractor (Tony's 6 directives) | `directives-checklist.md`, `report-structure-reference.md`, `known-failure-modes.md` |
| `Title_Examination_Notes.*` | Abstractor (Tony's 6 directives) | Same as above |
| `OnE_Report_*.{md,pdf}` | Client-side (Peter's OnE template) | `one-report-verification.md` |
| All three present in same case folder | **Combined audit** | Run both tracks + cross-consistency checks per `one-report-verification.md` §"Cross-check with the regular verify-cure-report flow" |

## Inputs the skill expects

The user will typically point at a case folder, e.g.:

```
src/titlepro/api/downloaded_doc/0522/Broward_ANAND_v2/
```

The skill MUST locate and read these artifacts from that folder:

| File | Used for |
|---|---|
| `RAW_TWO_OWNER_SEARCH_EXAM.md` | Primary report under review |
| `Title_Examination_Notes.md` | Secondary report (if exists) |
| `search_results.json` | Verifies per-search-count pattern (Directive #3) |
| `documents_found.json` | Verifies `found_via_names` coverage + doc-count vs golden |
| `document_metadata.json` | Confirms downloads succeeded |
| `broward_download_manifest.json` | Surfaces prohibited / failed downloads |
| `phase1_verifications.json` (if exists) | Subject-address + mortgage classifications |
| `prohibited_documents.json` (if exists) | FL Ch. 2002-302 statutory blocks |
| `_REPORT_NOTICES.md` (if exists) | Notice content that must appear in the report |
| `workflow_config.json` | Subject property + search-name expectations |
| `not_needed/documents_found.json.original` (if exists) | Confirms NO silent dropping (Directive #5) |

## Verification procedure

### Step 0 — Source-of-truth pre-flight (MANDATORY, runs FIRST)

**Do not score any of the nine checks until this step passes.** A report verified against a stale or out-of-sync adapter config can produce false-positive PASS results.

Load `source-of-truth-verification.md` and run the pre-flight:

1. Identify the county from `workflow_config.json` (`county` field, e.g. `fl_broward`).
2. Locate that county's row in the canonical master sheet:
   `docs/County_URL_Mapping_CA_OH.md` (parent index) +
   `docs/County_URL_Mapping_CUREMasterSheet.xlsx` (authoritative spreadsheet).
3. Compare the master-sheet URLs (Recorder URL, TitlePro247 Image-Download URL, Tax URL, CAPTCHA / Post-CAPTCHA URL) against the adapter config used:
   - `src/titlepro/search/recorder/counties/registry.py` entry
   - `src/titlepro/search/recorder/counties/config/<state>/<county>.json`
   - `config/county_tax_urls.json`
   - `selenium_downloader.py` + `secrets.json` TITLEPRO_URL
4. If ANY of the four are out of sync with the master sheet → **STOP and report SoT_DRIFT before proceeding.** The verifier cannot trust downstream results.
5. Apply county-specific knowledge from `source-of-truth-verification.md` (e.g., Broward = Cloudflare-fronted Telerik; Miami-Dade = registration-required SPA; Hillsborough = bare IIS).

Record the Step-0 outcome as `SoT_PASS` / `SoT_DRIFT` / `SoT_MISSING_COUNTY` (county not in master sheet — caller must add it before any further verification). Surface the result at the TOP of the verification report.

### Step 1 — Identify the case folder and load all artifacts

If the user names only a subject (e.g. "ANAND"), search under `src/titlepro/api/downloaded_doc/0522/` (or the most recent date folder) for matching case dirs. Confirm with the user if ambiguous.

Read the workflow_config first to learn:
- `owner_name`
- `search_requests[].name` (the expected name list)
- `property_address` (the subject the verifier should anchor on)
- `start_date` / `end_date`

### Step 2 — Run the verification checks (route by report type)

**For abstractor-side reports (RAW / Title Examination Notes):** apply each check from `directives-checklist.md` (6 Tony directive checks **plus the 4 Quality Gates Q1-Q4 added 2026-05-26** for the Broward Standard, **plus Q13 prior-owner-name-sweep added 2026-06-11** — ship-blocker for Two-Owner reports that never searched the vesting deed's grantor) and `known-failure-modes.md` (15 regression patterns F1-F15) in order. **A FAIL on any Q1-Q4 quality gate is a 🔴 ship-blocker regardless of the 6-directive scorecard** — these gates catch the placeholder-language / missing-tax / missing-PA-anchor / placeholder-grantor failure modes that defeat the product's purpose.

**For client-side reports (OnE_Report_\*.{md,pdf,docx}):** apply each check from `one-report-verification.md` (**14 OnE-specific checks** as of v1.6 / 2026-06-03 — Peter Bodonyi's template + supplement plus 4 new Peter-review-adoption checks OnE-11..OnE-14) **PLUS the 10 OnE Quality Gates Q5-Q12 + Q14-Q15 from `directives-checklist.md`** (Q5-Q9 added 2026-05-28 per Tony Roveda's review — clean 8-section template, Exhibit A boilerplate + own page, OPEN-only §3, no TRA in §6, conditional §7; Q10-Q12 added 2026-06-03 per the cross-report Peter Bodonyi synthesis — internal-memo pairing, inline FL-statute citation coverage, same-day refi-cycle Prior-Vesting guard; **Q14-Q15 added 2026-06-18 per operator review — Q14 no Title-only field leaked into the OnE (clean-MATCH verification line, Doc Stamps, Examiner Classification, Subject To, Prepared By, TRA, Released sub-table); Q15 OnE §6 carries a real annual tax figure when the data is retrievable**) **PLUS the F18-F23 regression scans from `known-failure-modes.md`** (no (a)-(l) codes, no engineering rows, page-break-before present in either DOCX OOXML or PDF HTML form, boilerplate prefix, no municipal-search caveat, no Released/Reconveyed subsection) **PLUS the F26 messy-print scan** (run `pdftotext` on the rendered OnE PDF and grep the VISIBLE text for leaked markup — `w:br`, `w:type=`, `<w:p`, `<w:r`, `{=openxml}`, `page-break-before`, stray `<div`/`<!--`). A FAIL on any Q5-Q9, Q11-Q12, **Q14, Q15 (retrievable-tax case),** or F18/F19/F21/F22/F23 is a 🔴 ship-blocker. **F26 (messy print) is a 🔴 ship-blocker that forces the overall verdict to RED — "Manual review needed — messy print detected" — regardless of every other check's score** (a client must never receive a report with raw markup printed in it). Q10 (internal memo) is informational only — never blocks ship. **OnE-11 (internal memo present) is a WARN reminder to strip before forwarding; OnE-14 (same-day refi-cycle vesting) is a ship-blocker FAIL when the OnE cites the candidate interim deed instead of the walker's recommended walk-target.**

**If both abstractor + OnE reports exist in the same case folder:** run BOTH check packs, then run the cross-consistency checks listed at the bottom of `one-report-verification.md` (vesting parity, mortgage parity, critical-issue subset, tax-data field-for-field).

For each check, record:

- **Status:** PASS / FAIL / WARN / N/A
- **Evidence:** specific line numbers, doc numbers, or JSON paths
- **Severity:** 🟢 advisory / 🟡 fix-recommended / 🔴 ship-blocker

### Step 3 — Cross-check report content against `documents_found.json`

Every doc in `documents_found.json` (minus those in `not_needed/`) should appear in the RAW's "DOCUMENTS EXAMINED" section. Silent drops are a Directive #5 violation. Build a delta set:

```
expected = {d["document_number"] for d in documents_found.json}
mentioned = {extract all instrument-number-shaped strings from RAW md}
silently_dropped = expected - mentioned
```

If `silently_dropped` is non-empty AND those docs aren't itemized under "EXAMINED AND EXCLUDED" → FAIL Directive #5.

### Step 4 — Apply Tony's golden-doc list when present

If the case has a golden-doc list (e.g., ANAND's 13 expected docs from Tony's review at `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/01_tony_review_findings.md`), score coverage as `hits/total`. Anything below 80% is a 🔴 ship-blocker.

### Step 5 — Compare RAW report's classifications against `phase1_verifications.json`

For each doc the verifier marked NO_MATCH, check that the RAW report:
- Surfaces it as `[CRITICAL] Wrong-Property Match` in Critical Issues
- Does NOT use it as the vesting deed
- Does NOT count it among open encumbrances if it's actually for a different property

For each mortgage the linker marked `released`:
- Must appear under "Released / Satisfied" NOT "Open Mortgages"
- Must cite the satisfaction/release doc# as evidence

### Step 6 — Format the verdict

Output a markdown report with:

1. **Headline verdict:** one line — `SHIPPABLE`, `SHIPPABLE WITH FIXES`, `BLOCKED — re-run required`, or `BLOCKED — needs human review`.
2. **9-check scorecard** as a table (one row per check, with Status / Severity / Evidence).
3. **Concrete fix list** — every FAIL gets a bullet with the exact remediation (file path + change description).
4. **Comparison to baseline** (if user asked for delta vs an earlier run) — table of per-check status changes.
5. **Tony-style verdict paragraph** — a 3-5 sentence summary written in Tony's no-nonsense voice ("Vesting checks out", "Released mortgages still showing as open — fix before sending"), so the user can forward it as a one-paragraph summary.

### Step 7 — Generate `Tony_verified_commentary.md` (UNCONDITIONAL)

After Steps 0-6 complete, **always** emit a companion file at
`<case_dir>/Tony_verified_commentary.md`. This is the **engineering-facing**
companion to the customer-facing Title Examination Notes. It captures every
internal observation that the Title MUST suppress (per F11):

- Per-doc verifier MATCH/NO_MATCH similarity scores from
  `phase1_verifications.subject_address_verification`
- Per-doc inferred type + confidence + source from
  `phase1_verifications.document_type_classifications`
- Per-mortgage classification (`open` / `released` / `modified`) + the
  satisfaction/release doc number cited as evidence
- Linker-vs-LLM discrepancies (cases where the LLM caught a Book/Page
  cross-reference the regex linker missed)
- Directive-citation rationale, using the canonical inline format:
  `As per directive #N (one-line description of the rule)` — never
  `Per Tony directive #N` or `Tony directive #N` (the reviewer name is
  suppressed even in the engineering file).
- Engineering follow-ups for the next CURE release (NOT for the customer)
- Subject-address-verification anomalies (e.g., the lender-HQ address
  extraction signature from F7)
- Prohibited-document handling (FL Ch. 2002-302) with statutory citations
- The verbatim `## Tony-Style Verdict` from Step 6 (Tony's voice goes
  here; the file itself uses neutral directive-citation language elsewhere)

**Required sections** (see `report-structure-reference.md` "Companion
File" section for full schema):

1. `## Verifier Verdict` — SHIPPABLE / SHIPPABLE WITH FIXES / BLOCKED
2. `## Step 0 — Source of Truth`
3. `## Six Directives — Scorecard` (each row uses the "As per directive
   #N (description)" citation format)
4. `## Known Failure Modes — Scans`
5. `## Subject-Property Address Verification (per doc)`
6. `## Document Type Classification (per doc)`
7. `## Mortgage Status Classification (per mortgage)`
8. `## Linker-vs-LLM Discrepancies`
9. `## Engineering Follow-ups`
10. `## Prohibited Documents`
11. `## Tony-Style Verdict` (verbatim from Step 6)

**Implementation:** Use the generator at
`src/titlepro/verification/tony_commentary_generator.py`. CLI form:

```bash
python3 -m titlepro.verification.tony_commentary_generator <case_dir>
```

This is an **unconditional** output — every verification run produces this
file, even when the verdict is SHIPPABLE with no fixes. Downstream tooling
relies on the file existing.

### Step 8 — Stamp the 3-light verifier-status banner (post-review, UNCONDITIONAL)

After Steps 0-7, stamp the **reviewed report file** at the very top with an
internal QA traffic-light banner reflecting this run's headline verdict. This
gives the operator an at-a-glance ship/hold signal on the report itself — the
rendered DOCX/PDF shows the lights, while the HTML-comment sentinels are dropped
by pandoc/weasyprint so they never print.

**Verdict → light mapping:**

| Headline verdict | Light |
|---|---|
| SHIPPABLE (clean or cosmetic-only) | 🟢 GREEN |
| SHIPPABLE WITH FIXES (non-blocking WARN / fix-needed) | 🟡 YELLOW |
| BLOCKED — re-run required / needs human review | 🔴 RED (NEEDS REVIEW) |
| **F26 messy print detected** (raw markup in the rendered PDF/DOCX) | 🔴 **RED — overrides everything** |

**Override:** if the F26 messy-print scan hits (raw `w:br`/`{=openxml}`/`<div`/`<!--` etc. in the rendered PDF visible text), the verdict is RED no matter what the other checks say, and the badge uses the messy-print label below.

**Banner format** — prepend to the report `.md`, ABOVE the title. Keep it MINIMAL: just the colored dot + label, nothing else — no date, no three-light row, no open-items prose (per operator directive 2026-06-17, the extra commentary was rejected as noise):

```
<!-- VERIFIER-STATUS-START -->
<active light — see below>
<!-- VERIFIER-STATUS-END -->
```

The banner shows ONLY the active status, one bold line:
- GREEN:  `🟢 **Shippable**`
- YELLOW: `🟡 **Shippable with fixes**`
- RED:    `🔴 **Needs review**`
- RED (F26 messy print):  `🔴 **Manual review needed — messy print detected**`

**Rules:**
- **Idempotent:** if a `VERIFIER-STATUS-START … VERIFIER-STATUS-END` block already exists, REPLACE it (strip the old block first) — never stack banners.
- **Internal-only:** the banner is QA status, NOT client content. The `<!-- VERIFIER-STATUS-START … VERIFIER-STATUS-END -->` wrapper makes it programmatically strippable (regex `VERIFIER-STATUS-START.*?VERIFIER-STATUS-END -->\n\n`, DOTALL); strip the block before any client send. Same discipline as the internal-memo pattern — a 🔴/🟡 status must never reach a client.
- **Re-render after stamping:** regenerate the canonical DOCX (`docs/Cure_Response/render_one_report_docx.py <md> <docx>`) + supplementary PDF (`docs/Cure_Response/render_one_report.py <md> <pdf>`) so the badge appears in the rendered deliverables. Pandoc drops the HTML-comment sentinels automatically; the dot+label line renders visibly.
- **No commentary in the stamp:** the banner is the dot + label only. Per-finding detail, open items, and fix lists belong in the verification output and `Tony_verified_commentary.md` — NOT in the badge.
- Applies to the OnE report under review; for a combined audit, stamp each reviewed report (RAW / Title / OnE) with its own track + verdict.

## Output format example

```markdown
# CURE Report Verification — Broward_ANAND_v2 (0522)

**Verdict:** SHIPPABLE WITH FIXES (1 ship-blocker, 2 advisories)

## 9-check scorecard

| # | Check | Status | Severity | Evidence |
|---|---|---|---|---|
| 1 | No Selenium/Playwright in Phase 1 search | 🟡 WARN | 🟡 | Selenium adapter used; HTTP adapter built but not yet wired (memory/broward_http_adapter.md) |
| 2 | Deed-first methodology applied | 🔴 FAIL | 🟡 | DocType=All used; verifier still post-extraction sidecar |
| 3 | All provided names searched (no [N,0,0,0,0,0] signature) | 🟢 PASS | — | search_results.json pattern: [16,16,16,23,23,23] |
| 4 | NLP subject-address verification ran on deeds | 🟢 PASS | — | 9/9 MATCH per phase1_verifications.json |
| 5 | Every doc examined (no silent drops) | 🟢 PASS | — | 8 moved to not_needed/ all itemized; documents_found.json.original preserved |
| 6 | Released mortgages excluded from "Open" | 🟢 PASS | — | 112424642 correctly classified RELEASED |
| 7 | Vesting is a WD (or chain of WD → QCD oldest-to-newest) | 🟢 PASS | — | WD 110509369 cited as current vesting |
| 8 | Prohibited-doc statutory notice present (if applicable) | 🟢 PASS | — | 113945927 notice in both RAW + Title |
| 9 | Tony-golden coverage ≥ 80% | 🟢 PASS | — | 11/13 (85%) |

## Concrete fixes
...

## Tony-style verdict
Vesting + chain of title looks right. Released mortgages connected to their satisfactions correctly. NOC `119437728` got flagged as wrong-property — good catch. Still using browser automation for search and skipping the deed-first approach — fix before the next batch. Otherwise shippable.
```

## Anti-patterns to actively look for

The verifier is allowed (encouraged) to fail a report on any of these — even if the LLM-generated text "looks right":

- "Standing on" a QCD as the vesting deed without an earlier WD in the chain
- Reporting a released mortgage as "open"
- A NO_MATCH subject-address verifier result that doesn't surface in Critical Issues
- A document in `documents_found.json` that doesn't appear anywhere in the RAW report
- A `[N, 0, 0, 0, 0, 0]` per-search-count pattern in `search_results.json`
- Reports that fail to list both spouse names when `workflow_config.search_requests` has two entries
- Reports that "summarize" rather than "examine" — e.g., "23 docs reviewed" without itemizing all 23

See `known-failure-modes.md` for the full list with regex/JSON-path heuristics.

## What this skill MUST NOT do

- Modify the report files. Verification is read-only.
- Run additional searches or downloads — the skill scores what's already on disk.
- Override Tony's directives. If the report passes the LLM's own self-checks but fails a Tony directive, the FAIL stands.
- Hide ship-blockers. Surface every 🔴 finding clearly.
