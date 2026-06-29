# Directives Checklist — Tony Roveda's Six Asks as Actionable Checks

Each directive maps to one verifier check. The check has a clear PASS/FAIL/WARN rubric anchored to artifacts on disk so verdicts are reproducible.

---

## Check D1 — No Selenium/Playwright in Phase 1 search

**Tony's words:** "We should not run any selenium or playwright runs we should run python http GET or POST request to run the Grantor, Grantee search and Both name search wherever applicable."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | The workflow status / logs show the HTTP adapter (`acclaimweb_http`, `tyler_http`, etc.) was used for the search phase. No Selenium imports active during search. |
| 🟡 WARN | Selenium adapter used for the search but the HTTP adapter is scaffolded and tested in the repo. (This is the current state of `fl_broward` as of 2026-05-23.) |
| 🔴 FAIL | Selenium used AND no HTTP adapter exists for the platform AND no documented blocker (e.g., the Telerik DocTypes payload reverse-engineering still in progress per `memory/broward_http_adapter.md`). |

### What to inspect

- Read `workflow_status.json` → `phases.search.details.platform` or check the adapter class name in error logs.
- If the case folder has a `phase1_search_plan.json` — that's an HTTP-adapter signature → PASS.
- Otherwise: check `src/titlepro/search/recorder/counties/registry.py` for the platform routing of the case's county; if it routes to a Selenium-based adapter → WARN with the documented-blocker citation.

---

## Check D2 — Deed-first search methodology applied

**Tony's words:** "Please adopt the DocType Deed as the initial exam. This will allow you to quickly locate the vesting deed for our party using NLP and pull the APN."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | The case folder has a `deed_candidates.json` AND a `vesting_resolution.json`. The RAW report's vesting section cites a Deed-type document chosen via the verifier. |
| 🟡 WARN | All-doctype search was used BUT the subject-address verifier ran post-extraction (the current 0522 v2 state). The methodology is approved-but-not-yet-shipped. |
| 🔴 FAIL | All-doctype search used AND no NLP-verifier output exists AND a non-Deed document was used as the vesting candidate. |

### What to inspect

- Look for `deed_candidates.json` and `vesting_resolution.json` in the case folder — these are the deed-first artifacts.
- If absent, check `phase1_verifications.json` for the `subject_address_verification` block — proves the verifier ran.
- Read the RAW report's `## PHASE 5: RAW EXAM REPORT > ### A. Property Information` or the Title's `## CHAIN OF TITLE` for the cited vesting doc and confirm it's a Deed-type (WD or QCD).

---

## Check D3 — Every provided name was searched + cross-spouse correlation

**Tony's words:** "I have stated countless times that all names provided must be run."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | `search_results.json` has one run per (name, party_type) tuple from `workflow_config.search_requests`. None of them returned 0 (or, if some did, the 0-result name has independent corroboration in the RAW report). Per-search counts do NOT match the `[N, 0, 0, 0, 0, 0]` regression signature. |
| 🟡 WARN | One name returned 0 but the report explicitly notes the absence as a finding (e.g., "DESTON SIMMONS not indexed under that exact name — consider alias 'BARKER, DESTON'"). |
| 🔴 FAIL | Per-search counts match `[N, 0, 0, 0, 0, 0]` pattern (only run 1 returned results, all subsequent runs returned 0) — the state-contamination signature. |
| 🔴 FAIL | `workflow_config.search_requests` has 2+ names but `search_results.json` only shows runs for 1. |

### What to inspect

```python
import json
sr = json.load(open(f"{case_dir}/search_results.json"))
counts = [r["result_count"] for r in sr["runs"]]
# [N, 0, 0, 0, 0, 0] → 🔴 FAIL StateContaminationDetected
# All nonzero → 🟢 PASS
# Mix → check report content for absence-as-finding
```

Then cross-check `documents_found.json` — every doc's `found_via_names` list should be non-empty. Docs reaching the RAW report via only ONE spouse trigger the spouse-delta narrative (see `~/.claude/projects/-Users-ag-Desktop-AIProjectsJuly2025-TIUConsulting-10X-Door-CA-properties-titlePro/memory/codev_title_abstractor_findings.md` — Tony's review of SIMMONS found MTG `112573690` exists under both BARKER + DESTON, which is the gold-standard joint-vesting signal).

---

## Check D4 — NLP subject-address verification on every deed candidate

**Tony's words:** "The document images must be pulled and reviewed with NLP. I don't know how else to say it."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | `phase1_verifications.json` has a `subject_address_verification` block covering every deed-type doc in the case. Any NO_MATCH result is surfaced in the RAW report as `[CRITICAL] Wrong-Property Match`. |
| 🟡 WARN | Verifier ran but missed some deed candidates (e.g., docs without an extractable address line). Acceptable IF the report's "DOCUMENTS EXAMINED" section explicitly notes which docs were exempt and why. |
| 🔴 FAIL | A doc was used as vesting AND its subject_address_verifier result is NO_MATCH AND the RAW report does NOT flag it as wrong-property. |
| 🔴 FAIL | No `phase1_verifications.json` exists at all for a 2026-05-23+ run. |

### What to inspect

- Open `phase1_verifications.json` → `subject_address_verification`. For each entry, check `status`. NO_MATCH should propagate to the RAW report's Critical Issues section.
- Tony's SIMMONS smoking gun: a QCD for `6830 Falconsgate Avenue, Davie` was shipped as the vesting for `2151 NW 93rd Ave, Pembroke Pines`. Re-read the report and confirm that:
  - The vesting deed cited has subject_address_verifier status MATCH
  - No NO_MATCH deed is silently treated as vesting

---

## Check D5 — Every indexed document examined; no silent drops

**Tony's words:** "It appears to have selectively picked some and not all."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | Every doc in `documents_found.json` either appears in the RAW report OR is itemized under "DOCUMENTS EXAMINED AND EXCLUDED" with a reason. Docs moved to `not_needed/` preserved in `not_needed/documents_found.json.original`. |
| 🟡 WARN | A few docs are missing from the report but are itemized in `not_needed/documents_found.json.original` (i.e., the audit trail exists but the report doesn't surface them). |
| 🔴 FAIL | One or more docs in `documents_found.json` don't appear in the RAW report AND don't appear under "EXAMINED AND EXCLUDED" AND no `not_needed/documents_found.json.original` exists. |

### What to inspect

```python
import json, re
docs = {d["document_number"] for d in json.load(open(f"{case_dir}/documents_found.json"))}
raw_md = open(f"{case_dir}/RAW_TWO_OWNER_SEARCH_EXAM.md").read()
mentioned = set(re.findall(r"\b1\d{8}\b", raw_md))  # adjust pattern for county doc# format
silently_dropped = docs - mentioned
# silently_dropped non-empty AND not_needed/documents_found.json.original missing → 🔴 FAIL
```

If `silently_dropped` is non-empty, check the `not_needed/` folder and the "EXAMINED AND EXCLUDED" section of the RAW report. Each dropped doc must be accounted for.

---

## Check D6 — Released mortgages excluded from "Open"

**Tony's words:** "It appears to have identified satisfactions but didn't connect the dots to remove them."

### How to score

| Status | When |
|---|---|
| 🟢 PASS | Every mortgage classified `released` by `released_mortgage_linker` (in `phase1_verifications.json`) appears in the RAW report's "RELEASED / SATISFIED" section, NOT "OPEN MORTGAGES". Each released mortgage cites its satisfaction/release doc# as evidence. |
| 🟡 WARN | Linker classified a mortgage `released` but the RAW report has it under both "Open" and "Released" (likely the LLM was hedging). Acceptable but worth a clean-up note. |
| 🔴 FAIL | A mortgage classified `released` in `phase1_verifications.json` appears ONLY in the "Open Mortgages" section of the RAW report. |
| 🔴 FAIL | The report says a mortgage is "open" but the case folder has a satisfaction/release doc whose extracted text cites that mortgage's instrument number or Book/Page. |

### What to inspect

- `phase1_verifications.json` → `mortgage_classifications` (per-doc `status: open|released|modified|subordinate`)
- For each `released` entry: grep the RAW md for the doc number. Confirm the surrounding text classifies it as released (look for words: "released", "satisfied", "discharged", "extinguished").
- For each `open` mortgage in the RAW report: grep all `*_extracted.md` files for mentions of that doc's instrument number AND for the keywords "satisfies", "satisfaction of", "release of", "discharge of". If found, that mortgage may have been wrongly classified as open.

The hardest catch (LLM caught it manually in 0522 v2): release docs that reference the parent mortgage by **Book/Page** not by instrument number (e.g., "OR BK 50955 PG 1364" referring to MTG `112424642`). The linker's regex misses these; the verifier should warn the user to manually confirm.

---

## Summary scorecard format

```markdown
| Directive | Status | Severity | Evidence |
|---|---|---|---|
| D1 — No Selenium/Playwright | 🟡 WARN | 🟡 | Selenium adapter still used; HTTP adapter built and tested but Telerik form-submit not yet wired |
| D2 — Deed-first methodology | 🟡 WARN | 🟡 | Verifier ran post-extraction (sidecar); deed-first planning step not yet wired into the pipeline driver |
| D3 — All names searched | 🟢 PASS | — | Pattern `[16,16,16,23,23,23]`; both ANAND names returned results |
| D4 — NLP address verification | 🟢 PASS | — | 9/9 MATCH on ANAND deeds; wrong-property NOC `119437728` correctly flagged |
| D5 — No silent drops | 🟢 PASS | — | 8 docs moved to `not_needed/`; `documents_found.json.original` preserved |
| D6 — Released mortgages excluded | 🟢 PASS | — | MTG `112424642` correctly in "Released" section, evidence cited |
```

Followed by:

- Concrete fix list (each FAIL → one line with file path + change)
- Comparison-to-baseline if asked (table of per-check status changes)
- Tony-style verdict paragraph

---

## Quality Gates Q1-Q4 — The Broward Standard (added 2026-05-26)

These four checks were added after the 0526 batch shipped reports that passed the 6-directive scorecard but were still below customer-deliverable quality. They are **mandatory** scorecard items now — a FAIL on any one is a 🔴 ship-blocker regardless of the directives' status.

### Q1 — No placeholder / non-resolution language in customer Title (F12)

| Status | Criteria |
|---|---|
| 🟢 PASS | `grep -niE "manual fetch\|pulled manually\|to be pulled\|to be confirmed\|\(prior owner [—-]\|confirm by pulling\|outside (the )?automated\|outside (the )?search\|outside.*range\|outside.*period\|out of search\|out of.*window\|not available\|not (yet )?verified\|pending direct pull\|verification is pending\|not in.*search range\|not in.*search window\|deed image not\|pre-(dates|2010|2007).*search.*window" Title_Examination_Notes.md` returns **zero hits**. The ONLY acceptable exception is a doc that's provably (a) statutorily-blocked (e.g., FL Ch. 2002-302) with the citation in-line, OR (b) image-sealed for legal reasons with the citation in-line. "Out of search window" / "pre-dates search window" is NEVER acceptable when the recorder has Book/Page direct retrieval available for pre-window deeds (which AcclaimWeb, Landmark, Tyler, Hillsborough Clerk, Manatee Clerk all do). |
| 🔴 FAIL | Any hit lacking a justifying citation, OR any "out of search window" / "pre-dates search window" claim when Book/Page direct retrieval is available. Customer report quality is the product — placeholder language is a regression to the legacy "manual abstractor" tool we're supposed to replace. |

See F12 in `known-failure-modes.md` for remediation. Every FL recorder we support has a direct-retrieval endpoint (`JumpToInstrumentNumber` / `JumpToBookPage` / equivalent) — use it.

### Q2 — Tax lookup data present in the report (F13)

**RULE (hardened 2026-05-27 after PalmBeach false-pass):** Tax DATA must be in the report — a ticket text alone is NEVER sufficient to ship. A report missing the bill amount is an incomplete report, full stop.

| Status | Criteria |
|---|---|
| 🟢 PASS | The customer report contains, at minimum, the **certified-roll annual tax amount** for the most recent tax year (sourced from PA tax-roll endpoints like OCPA's PRC / PBCPAO equivalent / county tax-roll CSV) AND `tax_*.json` is present with concrete amounts. Bonus if paid/delinquent installment status is also present. |
| 🔴 FAIL | The report contains "TAX STATUS NOT VERIFIED", "pending direct pull", "verification is pending", "tax bill amount not retrieved", or equivalent language — regardless of whether an engineering ticket accompanies it. A ticket goes in `engineering_ticket_*.md` next to the report; the customer report itself MUST carry the certified amount. |
| 🔴 FAIL | `fetch_tax: false` in workflow_config (even with justification). The justification should drive building the adapter, not skipping the lookup. |

**Recovery path when the Tax Collector portal is WAF-blocked or down:** Pull the certified-roll annual amount from the county Property Appraiser's tax endpoints (OCPA has `GetPRCTotalTaxes` / `GetPRCCertifiedTaxes`; PBCPAO likely has equivalents — probe before declaring the lookup impossible). The PA-sourced certified amount is the SAME number the Tax Collector bills from. Only paid/unpaid installment status genuinely requires the Tax Collector portal, and that gap is acceptable IF the certified amount is in the report.

See F13. The Grant Street HTTP pattern (`src/titlepro/tax/grant_street_http.py`, ~390 LOC) and the OCPA tax pattern (`src/titlepro/tax/orange_ocpa_http.py`, ~360 LOC) are the canonical templates.

### Q3 — Property Appraiser anchor present and APN-matched (F14)

| Status | Criteria |
|---|---|
| 🟢 PASS | `phase1_property_appraiser.json` + `phase1_reconciliation.json` exist in the case folder. PA `status: PA_SUCCESS`. Reconciliation `apn_agreement: MATCH` against workflow_config APN (digit-stripped). PA sale-history `back_chain_recovered_from_sale_history` is computed (may be empty if all priors are already in recorder results — that's fine). |
| 🟡 WARN | Sidecars exist with `status: PA_NO_RESULTS` after retry — flag for manual address-disambiguation, not a blocker. |
| 🔴 FAIL | Sidecars missing entirely, OR `status: PA_NO_RUNNER` (county adapter not built), OR `apn_agreement: MISMATCH` (the SIMMONS-class wrong-property gate — vesting deed MUST be rejected). |

See F14. The BCPA adapter (`src/titlepro/property_appraiser/counties/broward_bcpa.py`, ~310 LOC) is the canonical template. Building a new county PA = probe → mirror → tests → register in `config/county_property_appraiser_urls.json`.

### Q4 — Every prior-deed in chain has concrete grantor/grantee (F15)

| Status | Criteria |
|---|---|
| 🟢 PASS | The "CHAIN OF TITLE" table in both Title + RAW shows concrete party names for every row. No "(prior owner)" / "(Unknown)" / "likely foreclosed mortgagor" placeholders on rows where the recorder is HTTP-accessible. |
| 🔴 FAIL | Any chain row has placeholder party names AND its instrument# / book/page is retrievable via the recorder's direct-retrieval endpoint. The recorder will return Grantor/Grantee/Doc Type/Consideration/Case Number/Legal in plain HTML — the chain table MUST cite those. |

See F15. Pattern: `GET /details/JumpToInstrumentNumber/{record_type}/{doc_num}` (AcclaimWeb) or `GET /details/JumpToBookPage/{record_type}/{book}/{page}` — Tyler / Landmark / Hillsborough / Manatee all have equivalent endpoints.

---

## OnE Quality Gates Q5-Q9 — The Clean OnE Standard (added 2026-05-28)

These five OnE-specific quality gates were added after Tony's 2026-05-28 redline mandated the v2 clean OnE template (no `(a)`–`(l)` codes, no Title-only engineering rows, Exhibit A on its own page with boilerplate prefix, OPEN-mortgages only, no municipal-search caveat). A FAIL on any Q5-Q9 is a 🔴 ship-blocker for the OnE deliverable.

### Q5 — OnE strictly follows the 8-section clean template (F18 + structure)

| Status | Criteria |
|---|---|
| 🟢 PASS | OnE renders: Critical Issues callout + §1 Report Header + §2 Vesting + §3 Open Mortgages + §4 Judgments + §5 Bankruptcy + §6 Property Tax + (optional §7 Misc — see Q9) + §8 Exhibit A — IN THIS ORDER. ZERO `(a)`–`(l)` codes anywhere (`grep -E "\*?\([a-l]\)\*?"` → 0 hits). No "Client & Order Information" or "Search & Subject Details" sub-headers in §1. |
| 🔴 FAIL | Any `(a)`–`(l)` code rendered, OR sections out of order, OR any of §1-§6/§8 missing, OR §1 carries sub-header labels. |

See F18 + `OnE_Report_System_Prompt.md` "Required structure (8 sections in this exact order)".

### Q6 — OnE Exhibit A on its own page with boilerplate prefix (F20 + F21)

| Status | Criteria |
|---|---|
| 🟢 PASS | EITHER (a) the raw OOXML pandoc block `` ```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n``` `` (canonical DOCX path) OR (b) `<div class="page-break-before"></div>` (supplementary PDF path) appears IMMEDIATELY before the `## 8. Exhibit A` header. The line(s) below the `### Legal Description` sub-header contain the verbatim boilerplate `The following described land, situate, lying and being in [County] County, [State], to-wit:` (county + state substituted). |
| 🟡 WARN | Boilerplate present but page-break directive missing in BOTH forms (cosmetic — F20). |
| 🔴 FAIL | Boilerplate missing (F21) regardless of page-break state. |

See F20 + F21 + `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md` (v1.5) §8.

### Q7 — OnE §3 lists OPEN mortgages only (F23)

| Status | Criteria |
|---|---|
| 🟢 PASS | `grep -nE "^### Released\|^### Reconveyed\|^## Released\|^## Reconveyed" OnE_Report_*.md` returns 0 hits. All §3 mortgages are OPEN or POTENTIALLY OPEN. The released-mortgage detail is carried by the Title only. |
| 🔴 FAIL | Any released/reconveyed mortgage subsection inside §3. |

See F23 + the 2026-05-28 user lock-in (Released Mortgages = Title only).

### Q8 — OnE §6 Tax has no TRA / Millage rows (F19 subset)

| Status | Criteria |
|---|---|
| 🟢 PASS | `grep -niE "TRA\|Millage\|Taxing Authority Code" OnE_Report_*.md` returns 0 hits inside §6. (Hits OUTSIDE §6 are fine — e.g., if "Taxing Authority Code" appears as part of a different rendered value, but typically there is no such use case.) |
| 🔴 FAIL | TRA / Millage / Taxing Authority Code rendered as table rows in §6. |

See F19 + `OnE_Report_System_Prompt.md` §6 (Pg 8 redline retired these).

### Q9 — OnE §7 Misc — conditional inclusion (locked rule)

The 2026-05-28 user lock-in: §7 Miscellaneous Documents Examined renders ONLY if at least one open/unsatisfied subject-attaching misc item exists (active NOC inside statutory construction-lien window, lapsed-but-recent NOC inside extended statutory window, Declaration of Domicile material to ongoing homestead, unresolved subject-parcel administrative recording). If none, the section is omitted entirely.

| Status | Criteria |
|---|---|
| 🟢 PASS | §7 is rendered AND every row is an open/unsatisfied subject-attaching misc item. OR §7 is omitted AND the Title shows no qualifying open misc items either. |
| 🟡 WARN | §7 is rendered but contains expired NOCs / "examined-and-excluded" items / personal civil actions that don't attach to title. Section should be slimmed or omitted. |
| 🔴 FAIL | §7 carries released-mortgage satisfactions, examined-and-excluded different-property items, or pure-audit-trail content that belongs in the Title only. OR §7 is omitted AND the Title shows an active NOC / open misc item on the subject parcel (the OnE missed an open closing condition). |

See `OnE_Report_System_Prompt.md` §7 (CONDITIONAL — locked rule).

---

### Q10 — Internal-memo scratch pad properly paired (v1.6 — 2026-06-03)

Operators may append an `[INTERNAL MEMO ...]` block to the OnE markdown as a scratch pad. Per the 2026-06-03 user directive (Amit), the memo is preserved as a workflow tool — the verifier WARNs (not FAILs) so reviewers are reminded to strip before forwarding. Maps to OnE check `OnE-11` in `one-report-verification.md`.

| Status | Criteria |
|---|---|
| 🟢 PASS | No memo block present (both verbatim sentinels absent). |
| 🟡 WARN | Properly paired memo present (BOTH the start sentinel `[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]` AND the end sentinel `[END INTERNAL MEMO — REMOVE EVERYTHING BETWEEN THE [INTERNAL MEMO] AND [END INTERNAL MEMO] MARKERS BEFORE FORWARDING THIS REPORT]` appear exactly once each). Surface in verdict as: "Internal memo present — strip before forwarding to client." |
| 🔴 FAIL | Unpaired sentinels (broken markers leave half a memo in the report). Not a ship-blocker — but the malformed markup must be repaired. |

**Severity:** Never ship-blocker. Informational only.

---

### Q11 — Inline FL-statute citation coverage (v1.6 — 2026-06-03)

OnE v1.6 requires inline FL-statute citations whenever the source data contains a triggering condition (HELOC, NOC, Lis Pendens, etc.). Maps to OnE check `OnE-13`. Build expected-citation set from `documents_found.json` + `phase1_verifications.json`; grep OnE markdown for required citations.

| Trigger detected | Required citation (any spelling counts) |
|---|---|
| HELOC / open-end mortgage | `FS §697.04` / `§697.04` / `Open-End Mortgage per §697.04` |
| Active NOC | `FL §713.13` / `§713.13` |
| Notice of Termination of NOC | `FL §713.132` / `§713.132` |
| Lis Pendens | `FL §48.23` / `§48.23` |
| Construction Lien claim | `FL Ch. 713 Part I` / `Florida Construction Lien Law` |
| Statutorily prohibited document | `FL Ch. 2002-302` / `FS §119.0714(2)` |

| Status | Criteria |
|---|---|
| 🟢 PASS | No triggers in source OR 100% citation coverage |
| 🟡 WARN | 80-99% coverage (1-2 missing) |
| 🔴 FAIL | <80% coverage — ship-blocker |

---

### Q12 — Same-day refi-cycle Prior-Vesting guard (v1.6 — 2026-06-03)

OnE v1.6 §2 Prior Vesting must walk past any candidate that is recorded within ≤30 days of Current Vesting AND has party overlap with Current. New verification module `src/titlepro/verification/vesting_chain_walker.py` writes findings to `phase1_verifications.json` under key `vesting_chain_walker`. Maps to OnE check `OnE-14`. RILEY Pasco Jun 2 → Jun 3 regression class.

| Status | Criteria |
|---|---|
| 🟢 PASS | `walker.status == "PASS"` (no same-day refi detected) OR `walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"` AND OnE §2 Prior Vesting cites the `recommended_walk_target_doc_number` |
| 🟡 WARN | `walker.status == "AMBIGUOUS"` — operator review recommended |
| 🔴 FAIL | `walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"` AND OnE §2 Prior Vesting cites the candidate interim deed (the same-day refi cycle) instead of the recommended arm's-length acquisition |

**Severity:** 🔴 ship-blocker when FAIL.

---

### Q13 — Prior-owner name sweep executed (added 2026-06-11 — Duval SKINNER lesson)

Tony directive #3 covers every PROVIDED name, but a Two-Owner search also requires the PRIOR owner's name — which is *discovered* mid-run from the vesting deed grantor, not provided at intake. Duval/SKINNER (0610) shipped without sweeping the prior owner (DRUGG) and missed an unsatisfied 2005 AMNET/MERS mortgage (2005290168) that Peter Bodonyi's report carried — the only PETER BETTER verdict of the 0610 batch. Volusia/GUILD (same batch) DID sweep the prior owner and caught a 2003 prior-owner mortgage + its release that Peter missed.

**Check:** identify the vesting deed's grantor(s) (the prior owner). Verify the run's `search_results.json` / RAW search log contains at least one recorder name search for each prior-owner surname covering the prior-ownership window (prior acquisition date → current vesting date + buffer). Then verify every prior-owner mortgage found was either (a) linked to a recorded satisfaction, or (b) reported as PRIOR-OWNER POTENTIALLY OPEN with the operator-confirm flag.

| Status | Criteria |
|---|---|
| 🟢 PASS | Prior-owner name(s) searched over their ownership window; all prior-owner mortgages dispositioned (released-of-record or flagged POTENTIALLY OPEN) |
| 🟡 WARN | Prior owner searched but window coverage is partial (e.g., starts at the vesting date, missing the acquisition-era instruments) |
| 🔴 FAIL | No prior-owner name search in the run — ship-blocker for any report labeled Two-Owner |

**Severity:** 🔴 ship-blocker when FAIL (the report is a one-owner search wearing a two-owner label).

### Q14 — No Title-only field leaked into the OnE (added 2026-06-18 — operator review)

The OnE is the client-facing trimmed view; the OnE content matrix marks several fields **Title-only** (stripped from the OnE). A clean-MATCH subject-address verification result leaked into two 0618 OnEs (`subject-address verified ✓ MATCH 1.00` in a chain row) and the verifier did not catch it — there was no gate for Title-only field leakage. This gate closes that gap.

**Check:** grep the OnE **client body** (after stripping the `<!-- VERIFIER-STATUS … -->` banner AND any `[INTERNAL MEMO]…` operator block) for Title-only fields that must never appear in the OnE:
- Subject-address **verification result on a clean match** — `✓ ?MATCH`, `verified ✓`, `MATCH 1\.0`, a bare confidence score like `1\.00`/`0\.9[0-9]` attached to an address/verification phrase. *(EXCEPTION: a genuine NON-match / discrepancy flag — `NO MATCH`, `MISMATCH`, a documented false-positive note — is ALLOWED and intended; only the clean-match annotation is forbidden.)*
- **Doc Stamps** line in Current Vesting; **Subject-Address Verification** as a labeled field; **Subject To (per deed recital)**; **Prepared By**.
- **Examiner Classification** column; **exam-depth / back-chain** note; the **Property-Appraiser back-chain ledger** (E3) as a section.
- TRA / Taxing-Authority / Millage rows in §6 (also Q8); a **Reconveyed/Released** mortgage sub-table in §3 (also Q7/F23).

| Status | Criteria |
|---|---|
| 🟢 PASS | OnE client body contains none of the Title-only fields above |
| 🔴 FAIL | Any Title-only field present in the OnE client body (clean-match verification line, Doc Stamps, Examiner Classification, Subject To, Prepared By, TRA, Released sub-table) |

**Severity:** 🔴 ship-blocker when FAIL. The OnE must not leak Title-only/engineering content to the client.

### Q15 — OnE §6 carries a real annual tax figure (added 2026-06-18 — operator review)

The RAW/Title missing-tax ship-blocker is Q2, applied abstractor-side. The OnE-side §6 had no equivalent, so a §6 showing only the Property-Appraiser assessed value plus a "tax adapter in development" note passed as 🟡 (e.g. 0618 PalmBeach/VOLLMAN — the figure was in fact retrievable via the PBCPAO certified-TRIM table). This gate makes a missing **annual tax dollar amount** in the OnE §6 a ship-blocker **when the data is retrievable**.

**Check:** confirm OnE §6 contains a real annual-tax **dollar figure** (e.g. an "Annual Tax" row with `$N`), not merely assessed value + a pending/eng-ticket note. Then check retrievability: does a tax runner exist for the county (`config/county_tax_urls.json` platform ≠ `direct`/unset) OR did `tax_lookup_status.json` capture a figure?

| Status | Criteria |
|---|---|
| 🟢 PASS | §6 shows a real annual-tax dollar figure (live or sourced-from-capture) |
| 🟡 WARN | §6 has no annual-tax figure AND a genuine engineering ticket is documented (no tax runner exists for the county + the build target is named) — acceptable interim |
| 🔴 FAIL | §6 has no annual-tax figure BUT the data was retrievable — a tax runner exists for the county, or `tax_lookup_status.json` = TAX_SUCCESS, or the County PA exposes a certified-tax table |

**Severity:** 🔴 ship-blocker when FAIL (retrievable tax left out); 🟡 fix-recommended when WARN (genuine no-adapter ticket).
