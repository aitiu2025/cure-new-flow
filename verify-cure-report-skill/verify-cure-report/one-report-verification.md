# OnE Report Verification — Peter Bodonyi + Tony Roveda Check Pack

> **Added 2026-05-26** per Peter Bodonyi's directive that the client-facing **Ownership and Encumbrance Report** (OnE Report) must be verified against his template + supplement before issuance.
> **Updated 2026-05-28 to v1.5** per Tony Roveda's review: §3 OPEN-only, §7 CONDITIONAL, §5 Bankruptcy unchanged.
>
> **Applies to:** files named `OnE_Report_<Subject>.{md,pdf,docx}` in any case folder.
>
> **Source authority (canonical compiler spec — read FIRST):**
> 1. `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md` — **current version is v1.5** (file name kept as v1.2 for stable referencing; content is amended in place per the Revision History block at the bottom of the file)
> 2. `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/O&E Template CURE.docx` — original blank template (the (a)–(l) codes are retired; kept only for historical context)
> 3. `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/Anand_report Template for O&E supplement.docx` — Anand-filled instance with Peter's review comments
>
> **Render path (canonical — DOCX):** `python3 /Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/render_one_report_docx.py OnE_Report_<Subject>.md OnE_Report_<Subject>.docx` (pandoc with `--reference-doc=/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/docs/Cure_Response/reference.docx` for Table Grid borders).
>
> **Render path (supplementary — PDF):** `render_markdown_pdf(... doc_type=RAW_DOC_TYPE)` from `src/titlepro/automation/renderers.py` (white background, NOT yellow). The PDF is a visual review aid; the DOCX is the canonical client deliverable.

## When to invoke this check pack

Trigger any of these checks when:
- A file named `OnE_Report_*.md` or `OnE_Report_*.pdf` appears in the case folder
- The user asks to "verify the OnE report", "audit the O&E", "check the ownership report"
- A user mentions Peter Bodonyi by name in the verification request

If the case folder has BOTH a Title Examination Notes report AND an OnE Report, run the regular `directives-checklist.md` (Title) + this check pack (OnE) and surface BOTH scorecards.

## OnE-specific check inventory (10 checks)

### Check OnE-1 — Section structure (v1.5 — 8 clean numbered sections, §7 conditional)

The OnE report must contain these sections **in this order** (per `OnE_Report_SystemPrompt_v1.2.md` v1.5):

1. **§1 Report Header** — single 2-row table; no sub-headers
2. **§2 Vesting (Deed) Information** — `### Current Vesting` + `### Prior Vesting`
3. **§3 Open Mortgages / Deeds of Trust** — OPEN only (no Released/Reconveyed sub-table)
4. **§4 Judgments** — "None of record..." OR judgment block(s); no municipal-search caveat
5. **§5 Bankruptcy** — PACER / state-court operator-verify placeholders (unchanged in v1.5)
6. **§6 Property Tax Information** — no TRA / Millage / Taxing Authority Code rows
7. **§7 Miscellaneous Documents Examined** — **CONDITIONAL** (render only if open/unsatisfied subject-attaching misc items OR prohibited document exist; OMIT entirely otherwise — see Q9)
8. **§8 Exhibit A** — own page; boilerplate prefix + verbatim legal description + Parcel ID + Source Instrument

### How to score OnE-1

```bash
# Required numbered H2 headers — §1, §2, §3, §4, §5, §6, §8 must always be present
grep -cE "^##\s+(1\.\s+Report Header|2\.\s+Vesting|3\.\s+Open Mortgages|4\.\s+Judgments|5\.\s+Bankruptcy|6\.\s+Property Tax|8\.\s+Exhibit A)" OnE_Report_*.md
# Must equal 7

# §7 is conditional — check separately
grep -cE "^##\s+7\.\s+Miscellaneous" OnE_Report_*.md
# 0 = omitted (acceptable if no qualifying open items); 1 = rendered (acceptable if qualifying open items exist)
```

| Status | When |
|---|---|
| 🟢 PASS | All 7 mandatory numbered sections (§1, §2, §3, §4, §5, §6, §8) present and in order. §7 is either present (with qualifying open content) or omitted (no qualifying open content). |
| 🟡 WARN | All 7 mandatory sections present but out of order. |
| 🔴 FAIL | Any of §1, §2, §3, §4, §5, §6, §8 missing. |
| 🔴 FAIL | §7 rendered but contains only non-qualifying content (expired NOCs, released satisfactions, examined-and-excluded items, personal civil actions). |
| 🔴 FAIL | §7 omitted but Title shows at least one active NOC / open subject-attaching misc item. |

---

### Check OnE-2 — (a)–(l) coding system MUST BE ABSENT (RETIRED in v1.2 / locked in v1.5)

The OnE prompt retired the `(a)`–`(l)` field-mapping codes in v1.2 (2026-05-27). v1.5 locks this — ANY `(a)`–`(l)` code rendered in the OnE markdown is a regression to the original draft template that the closing agent never wanted.

### How to score OnE-2

```bash
# Must be 0 — every (a)..(l) marker counts as a hit
grep -cE "\*?\([a-l]\)\*?" OnE_Report_*.md
```

| Status | When |
|---|---|
| 🟢 PASS | Zero `(a)`–`(l)` markers anywhere in the rendered OnE |
| 🔴 FAIL | Any `(a)`–`(l)` marker present |

---

### Check OnE-3 — Verbatim field-label preservation

Peter wrote each field label exactly once in the template. The OnE compiler must preserve these labels verbatim — minor cosmetic drift (added/removed colons, missing parentheticals) is the most common error mode and is a directive violation.

**Verbatim labels that must match exactly:**

| Source label | Common drift | Pass condition |
|---|---|---|
| `"All Party Names (as ordered)"` | drops "(as ordered)" | "(as ordered)" must appear verbatim |
| `"Street Address (as ordered)"` | drops "(as ordered)" | "(as ordered)" must appear verbatim |
| `"City, State, County, Zip (as ordered)"` | drops "(as ordered)" | "(as ordered)" must appear verbatim |
| `"Court/Case No."` (NO trailing colon) | adds colon → `"Court/Case No.:"` | must end with `.` not `.:` |
| `"Exhibit A"` + `"Legal Description (l)"` (two stacked headers) | combined into single header | two separate `##`/`###` headers, not joined with em-dash |

### How to score OnE-3

```bash
grep -cE "All Party Names \(as ordered\)" OnE_Report_*.md  # must be >= 1
grep -cE "Street Address \(as ordered\)" OnE_Report_*.md   # must be >= 1
grep -cE "City, State, County, Zip \(as ordered\)" OnE_Report_*.md  # must be >= 1
grep -cE "Court/Case No\.\s*$|Court/Case No\.[^:]" OnE_Report_*.md   # must be >= 1, must NOT match "Court/Case No.:"
grep -cE "^##\s+Exhibit A\s*$" OnE_Report_*.md    # must be >= 1 (Exhibit A as standalone header)
grep -cE "^###?\s+Legal Description" OnE_Report_*.md   # must be >= 1 (Legal Description as separate header)
```

| Status | When |
|---|---|
| 🟢 PASS | All 5 verbatim-label checks pass |
| 🟡 WARN | 1–2 cosmetic drifts |
| 🔴 FAIL | 3+ drifts OR critical drift (e.g., "Court/Case No." with trailing colon, or "Exhibit A — Legal Description" combined) |

---

### Check OnE-4 — POTENTIALLY OPEN mortgage warnings rendered

Every mortgage classified `POTENTIALLY OPEN — NO RECONVEYANCE FOUND` in the source Title Notes MUST have the red-bold direct-payoff warning rendered in §3.

### How to score OnE-4

1. Read source Title Notes file → find rows in `DEEDS OF TRUST / MORTGAGES > Potentially Open` table
2. For each, grep the OnE report for the instrument number
3. Confirm surrounding text contains `"DIRECT PAYOFF VERIFICATION REQUIRED"` and is styled bold + ⚠️ or red

| Status | When |
|---|---|
| 🟢 PASS | Every POTENTIALLY OPEN mortgage has the warning |
| 🟡 WARN | Warning text present but not styled red-bold |
| 🔴 FAIL | A POTENTIALLY OPEN mortgage is rendered without the warning text |

This is the ANAND-class regression — high-severity miss.

---

### Check OnE-5 — Verbatim Exhibit A (Peter's P-1 flag)

The legal description in §8 must match the source Title Notes' `LEGAL DESCRIPTION (EXHIBIT A)` section **verbatim** (whitespace + punctuation preserved within a blockquote).

### How to score OnE-5

```python
# Pull source legal block
source_legal = extract_section(title_notes_md, "LEGAL DESCRIPTION (EXHIBIT A)")
# Pull OnE §8 blockquote
one_legal = extract_blockquote_under_section(one_md, "Exhibit A")
# Strip whitespace and compare
assert normalize(one_legal) == normalize(source_legal)
```

**Peter's P-1 flag:** From the Anand supplement comment on (l): *"not sure this is the full legal will confirm"*.

| Status | When |
|---|---|
| 🟢 PASS | Verbatim match + P-1 flag note present (if legal is single-paragraph) |
| 🟡 WARN | Verbatim match but P-1 flag missing |
| 🔴 FAIL | Verbatim drift (whitespace/punctuation differs, or sentence rephrased) |

---

### Check OnE-6 — Tax status echo (no fabrication)

If the source Title Notes' `TAX STATUS` section says **`TAX STATUS NOT VERIFIED`**, the OnE §6 must echo the same status with the prescribed note. If source has full tax data, OnE must render it verbatim — NO invented values.

### How to score OnE-6

```python
source_tax_status = extract_table_row(title_notes_md, "TAX STATUS", "Installment Status")
one_tax_status = extract_table_row(one_md, "Property Tax Information", "Installment Status")
# Must match
```

| Status | When |
|---|---|
| 🟢 PASS | Tax status echoes source exactly |
| 🟡 WARN | Numbers match but formatting differs |
| 🔴 FAIL | Tax status fabricated (source says NOT VERIFIED, OnE shows a tax amount) |

---

### Check OnE-7 — Wrong-property vesting guard

The current vesting deed in §2 must NOT be a NO_MATCH deed from the source's `phase1_verifications.json`. (Mirrors the `directives-checklist.md` Check D4 / known-failure-mode F2 — SIMMONS gate.)

### How to score OnE-7

1. Read source case-folder `phase1_verifications.json` if present
2. Find any deed with `subject_address_verification.status == "NO_MATCH"`
3. For each, confirm it's NOT in §2 Current Vesting

| Status | When |
|---|---|
| 🟢 PASS | Vesting deed has MATCH verification (or no NO_MATCH deeds in source) |
| 🔴 FAIL | A NO_MATCH deed used as current vesting (SIMMONS regression — ship-blocker) |

---

### Check OnE-8 — Critical Issues callout preserved

The CURE-extension Critical Issues callout must contain the top 5 (by severity) `[CRITICAL]` / `[WARNING]` items from the source Title Notes' Critical Issues section.

### How to score OnE-8

```python
source_critical = extract_critical_issues(title_notes_md)  # [CRITICAL] / [WARNING] / [INFO] items
one_callout = extract_callout(one_md, "Critical Issues")
# At least every [CRITICAL] item must appear (verbatim or paraphrased preserving instrument numbers)
```

| Status | When |
|---|---|
| 🟢 PASS | All `[CRITICAL]` items present in callout + at least 2 `[WARNING]` (if any exist) |
| 🟡 WARN | All `[CRITICAL]` present but some `[WARNING]` dropped without "see Title Notes for full list" footer |
| 🔴 FAIL | Any `[CRITICAL]` item dropped from callout |

---

### Check OnE-9 — Peter P-1 / P-2 flags MUST be ABSENT (updated 2026-05-27)

Both Peter standing flags have been retired by directive:
- **P-1** (Legal-description completeness flag below §Exhibit A) — removed 2026-05-27
- **P-2** (Mortgage section completeness flag at end of §Open Mortgages) — removed in v1.2

The verifier now checks the OPPOSITE of the v1.1 behavior: any rendered OnE that still contains either flag is a regression.

### How to score OnE-9

```bash
# Both must be 0 (the flags are RETIRED)
grep -cE "Peter P-1|Legal-description completeness flag" OnE_Report_*.md   # MUST be 0
grep -cE "Peter P-2|Mortgage section completeness flag" OnE_Report_*.md   # MUST be 0
```

| Status | When |
|---|---|
| 🟢 PASS | Zero P-1 or P-2 callouts in the rendered OnE |
| 🔴 FAIL | Any P-1 or P-2 callout present — regression to retired v1.1 behavior |

---

### Check OnE-10 — No abstractor jargon (client-facing tone)

The OnE is for the closing agent / title insurer. The following examiner-internal terms MUST NOT appear in the rendered OnE:

| Forbidden term | Why |
|---|---|
| `spouse-delta` | Tony's alias-discovery technique — internal jargon |
| `released_mortgage_linker` | Internal Python module name |
| `phase1_verifications.json` | Internal pipeline artifact |
| `subject_address_verifier` | Internal Python module |
| `MATCH 1.00` / `NO_MATCH` (verifier scores) | Verifier output — abstractor-internal |
| `[N, 0, 0, 0, 0, 0]` | State-contamination signature — pipeline-internal |
| `SIMMONS gate` | Internal regression-pattern name |
| `Tony Directive #N` | Internal methodology reference |
| `acclaimweb_adapter` / `tyler_adapter` / `manatee_http` | Adapter class names |

### How to score OnE-10

```bash
egrep -ci "(spouse-delta|released_mortgage_linker|phase1_verifications|subject_address_verifier|MATCH 1\.00|NO_MATCH|N, 0, 0, 0, 0, 0|SIMMONS gate|Tony Directive|acclaimweb_adapter|tyler_adapter|manatee_http)" OnE_Report_*.md
# Must be 0
```

| Status | When |
|---|---|
| 🟢 PASS | Zero jargon terms found |
| 🟡 WARN | 1–2 jargon terms found |
| 🔴 FAIL | 3+ jargon terms OR any verifier score (`MATCH 1.00`) appears verbatim |

---

### Check OnE-11 — Internal-memo scratch pad (v1.6 — 2026-06-03)

Operators may append an `[INTERNAL MEMO ...]` block to the OnE markdown as a scratch pad for audit-trail corrections, F-class regression notes, reviewer action items, and engineering follow-ups. Per the 2026-06-03 user directive, the memo is preserved as a workflow tool. This check REMINDS reviewers to strip it before forwarding the .docx to the client — it never blocks.

**Verbatim sentinel markers** (must match exactly — including punctuation, spaces, and the em-dash):
- **Start:** `[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]`
- **End:** `[END INTERNAL MEMO — REMOVE EVERYTHING BETWEEN THE [INTERNAL MEMO] AND [END INTERNAL MEMO] MARKERS BEFORE FORWARDING THIS REPORT]`

### How to score OnE-11

```bash
START=$(grep -cF "[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]" OnE_Report_*.md)
END=$(grep -cF "[END INTERNAL MEMO — REMOVE EVERYTHING BETWEEN THE [INTERNAL MEMO] AND [END INTERNAL MEMO] MARKERS BEFORE FORWARDING THIS REPORT]" OnE_Report_*.md)
```

| Status | When |
|---|---|
| 🟢 PASS | No memo block present (START=0 AND END=0) |
| 🟡 WARN | Properly paired memo present (START=1 AND END=1) — REMIND reviewer to strip before forwarding the DOCX. Surface in verdict as: "Internal memo present — strip before forwarding to client." |
| 🔴 FAIL | Unpaired sentinel (START≠END) — broken markers leave half a memo in the report |

**Severity:** Never a ship-blocker. WARN is informational only.

---

### Check OnE-12 — Placeholder density (v1.6 — 2026-06-03)

Expands the existing Q1 quality gate with a per-token density check. Tony's policy (CLAUDE.md): "Don't ship customer reports with placeholder language when the data IS retrievable."

### How to score OnE-12

```bash
NOT_SUPPLIED=$(grep -cE "\*\(not supplied at order intake\)\*" OnE_Report_*.md)
NOT_PROVIDED=$(grep -cE "\[NOT PROVIDED\]" OnE_Report_*.md)
TO_BE_CONFIRMED=$(grep -ciE "to be confirmed|\bTBD\b|\bTBC\b|manual fetch required|outside search window" OnE_Report_*.md)
TOTAL=$((NOT_SUPPLIED + NOT_PROVIDED + TO_BE_CONFIRMED))

# Also detect placeholders outside §1 (anywhere after `## 2.`) — these are the worst kind
OUTSIDE_SECTION_1=$(awk '/^## 2\. Vesting/{found=1} found && /\*\(not supplied at order intake\)\*|\[NOT PROVIDED\]/{c++} END{print c+0}' OnE_Report_*.md)
```

| Status | When |
|---|---|
| 🟢 PASS | TOTAL ≤ 5 AND all `*(not supplied at order intake)*` instances are in §1 intake-metadata rows (CURE File Number, Client Name/File/Contact). OUTSIDE_SECTION_1 = 0. |
| 🟡 WARN | TOTAL 6–10, OR OUTSIDE_SECTION_1 between 1 and 3 (placeholder leaked into §2/§3/§6 etc.) |
| 🔴 FAIL | TOTAL > 10, OR OUTSIDE_SECTION_1 > 3, OR any `[NOT PROVIDED]` token appears in a field where data IS retrievable (tax year on a fetched Tax Collector page, Book/Page on a pre-2017 jurisdiction, etc.) |

**Severity:** 🔴 ship-blocker when FAIL. Placeholder leaks where data IS retrievable defeat the product's purpose.

**Note:** The v1.6 OnE spec defines concrete fallback phrases that REPLACE generic `*(not supplied at order intake)*` for specific known cases (instrument-only recording, OCR-degraded cover page, proprietary lender form, etc.). When you see the SPECIFIC fallback phrase (e.g., `*(instrument-only recording — Book/Page no longer assigned by this jurisdiction)*`), that's a PASS — the compiler resolved the unknown to a concrete jurisdiction-specific reason.

---

### Check OnE-13 — Inline FL-statute citation coverage (v1.6 — 2026-06-03)

OnE v1.6 requires inline FL-statute citations whenever a triggering condition appears in the source data. The verifier reads `documents_found.json` + `phase1_verifications.json` to enumerate triggers, then greps the OnE markdown for the required citation.

| Trigger detected in source | Required OnE citation (any of these spellings counts) |
|---|---|
| HELOC / open-end mortgage in §3 | `FS §697.04` / `Florida Statutes §697.04` / `Open-End Mortgage per § 697.04` |
| Active NOC in §7 | `FL §713.13` / `FS §713.13` / `§713.13` |
| Notice of Termination of NOC in §7 | `FL §713.132` / `FS §713.132` / `§713.132` |
| Lis Pendens in §4 | `FL §48.23` / `FS §48.23` / `§48.23` |
| Construction Lien claim in §4 | `FL Ch. 713 Part I` / `Ch. 713 Part I` / `Florida Construction Lien Law` |
| Statutorily prohibited document in §7 Inaccessible/Prohibited | `FL Ch. 2002-302` / `FS §119.0714(2)` / `§ 119.0714(2)` |
| Declaration of Domicile in §7 | `FL §222.17` / `FS §222.17` |
| Federal Tax Lien in §4 | `IRC §6321` / `26 U.S.C. § 6321` |
| State Tax Lien (FDOR) in §4 | `FL §213.756` / `FS §213.756` |

### How to score OnE-13

```bash
# Pseudo: build expected-citations set from triggers, then grep
EXPECTED=0; PRESENT=0

# Example: detect HELOC trigger from documents_found.json
HELOC_HITS=$(jq -r '.[] | select((.mortgage_type // "") | test("HELOC|Open-End|Revolving";"i")) | .document_number' "$CASE/documents_found.json" 2>/dev/null | wc -l)
if [ "$HELOC_HITS" -gt 0 ]; then
    EXPECTED=$((EXPECTED+1))
    grep -qE "(FS|FL|§)\s*§?\s*697\.04" "$CASE/OnE_Report_"*.md && PRESENT=$((PRESENT+1))
fi

# Repeat for each trigger row above...

COVERAGE=$(echo "scale=2; $PRESENT / $EXPECTED" | bc 2>/dev/null || echo "1.0")
```

| Status | When |
|---|---|
| 🟢 PASS | EXPECTED=0 (no triggers in source) OR COVERAGE = 1.00 (100% of expected citations present) |
| 🟡 WARN | 0.80 ≤ COVERAGE < 1.00 (1-2 missing) |
| 🔴 FAIL | COVERAGE < 0.80 |

**Severity:** 🟡 fix-recommended at WARN; 🔴 ship-blocker at FAIL.

---

### Check OnE-14 — Same-day refi-cycle Prior-Vesting guard (v1.6 — 2026-06-03)

The new verification module `src/titlepro/verification/vesting_chain_walker.py` writes its findings to `phase1_verifications.json` under key `vesting_chain_walker`. The verifier reads this sidecar to confirm the OnE §2 Prior Vesting cites the walker's recommended walk-target when a same-day refi cycle was detected.

**Sidecar shape:**

```json
{
  "vesting_chain_walker": {
    "status": "PASS" | "SAME_DAY_REFI_INTERIM_DETECTED" | "AMBIGUOUS",
    "current_vesting_doc_number": "2021099994",
    "candidate_prior_vesting_doc_number": "2021099992",
    "candidate_age_days_from_current": 0,
    "candidate_party_overlap_reason": "Same trustees on both sides — same-day Trust conveyance",
    "recommended_walk_target_doc_number": "2012188921",
    "recommended_walk_target_reason": "Arm's-length acquisition from Stiefel Properties LLC, 2012-11-05",
    "walked_past_doc_numbers": ["2021099992"]
  }
}
```

### How to score OnE-14

```bash
STATUS=$(jq -r '.vesting_chain_walker.status // "MISSING"' "$CASE/phase1_verifications.json" 2>/dev/null)
CANDIDATE=$(jq -r '.vesting_chain_walker.candidate_prior_vesting_doc_number // ""' "$CASE/phase1_verifications.json")
WALK_TARGET=$(jq -r '.vesting_chain_walker.recommended_walk_target_doc_number // ""' "$CASE/phase1_verifications.json")

if [ "$STATUS" = "SAME_DAY_REFI_INTERIM_DETECTED" ]; then
    # OnE §2 Prior Vesting MUST cite WALK_TARGET, NOT CANDIDATE
    awk '/^### Prior Vesting/{flag=1} flag && /^## /{flag=0} flag' "$CASE/OnE_Report_"*.md > /tmp/prior_vesting_block.md
    grep -qF "$WALK_TARGET" /tmp/prior_vesting_block.md && WALK_TARGET_CITED=1 || WALK_TARGET_CITED=0
    grep -qF "$CANDIDATE" /tmp/prior_vesting_block.md && CANDIDATE_CITED=1 || CANDIDATE_CITED=0
fi
```

| Status | When |
|---|---|
| 🟢 PASS | `walker.status == "PASS"` (no same-day refi detected) OR `walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"` AND OnE §2 Prior Vesting cites `recommended_walk_target_doc_number` |
| 🟡 WARN | `walker.status == "AMBIGUOUS"` (walker couldn't decide cleanly) — recommend operator review |
| 🔴 FAIL | `walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"` AND OnE §2 Prior Vesting cites the candidate interim deed (the same-day refi cycle, not the arm's-length acquisition) |

**Severity:** 🔴 ship-blocker when FAIL — this is the RILEY Pasco regression class (Jun 2 version showed a same-day Trust QCD as Prior Vesting; Jun 3 corrected to the 9-year-older Stiefel Properties LLC arm's-length deed).

---

## OnE-specific Scorecard format

```markdown
## OnE Report Verification Scorecard

| # | Check | Status | Severity | Evidence |
|---|---|---|---|---|
| OnE-1 | Section structure (8 required, ordered) | 🟢/🟡/🔴 | — | grep counts |
| OnE-2 | (a)–(l) code labels present | 🟢/🟡/🔴 | — | code coverage |
| OnE-3 | Verbatim field-label preservation | 🟢/🟡/🔴 | — | 5-label drift check |
| OnE-4 | POTENTIALLY OPEN warnings rendered | 🟢/🟡/🔴 | 🔴 ship-blocker if FAIL | matched instrument numbers |
| OnE-5 | Verbatim Exhibit A (P-1) | 🟢/🟡/🔴 | — | diff(source, OnE) |
| OnE-6 | Tax status echo (no fabrication) | 🟢/🟡/🔴 | 🔴 ship-blocker if FAIL | tax-status match |
| OnE-7 | Wrong-property vesting guard | 🟢/🔴 | 🔴 ship-blocker if FAIL | verifier-status check |
| OnE-8 | Critical Issues callout preserved | 🟢/🟡/🔴 | — | critical-item coverage |
| OnE-9 | Peter's P-1 + P-2 flags applied | 🟢/🟡/🔴 | — | flag-note presence |
| OnE-10 | No abstractor jargon | 🟢/🟡/🔴 | — | jargon-term count |
| Q14 | No Title-only field leaked into OnE (clean-MATCH line, Doc Stamps, Examiner Classification, Subject To, Prepared By, TRA, Released sub-table) | 🟢/🔴 | 🔴 ship-blocker if FAIL | grep client body (banner+memo stripped) |
| Q15 | §6 carries a real annual tax figure (when retrievable) | 🟢/🟡/🔴 | 🔴 ship-blocker if retrievable-but-missing; 🟡 if genuine no-adapter ticket | §6 $-figure + county tax-runner check |
```

## Post-review traffic-light stamp (UNCONDITIONAL)

After scoring an OnE report, stamp it with the 3-light verifier-status banner per **`SKILL.md` Step 8** — 🟢 SHIPPABLE / 🟡 SHIPPABLE WITH FIXES / 🔴 NEEDS REVIEW, mapped from the headline verdict. Prepend the sentinel-wrapped (`VERIFIER-STATUS … END`) banner to the top of the OnE `.md`, then re-render DOCX + PDF. It is an internal QA stamp — strip before client delivery.

**F26 messy-print override:** before stamping, run the F26 scan (`pdftotext` the rendered OnE PDF, grep visible text for `w:br` / `{=openxml}` / `<div` / `<!--` / `w:type=`). ANY hit → force the badge to `🔴 **Manual review needed — messy print detected**`, overriding every other check. See `known-failure-modes.md` F26.

## Peter-style verdict paragraph (template)

The OnE-report verdict should be written in client/operator voice (not Tony's abstractor voice — they're different audiences):

> "Section coverage looks complete — all eight sections present with the (a)–(l) coding preserved. Critical Issues callout captures both unsatisfied senior mortgages and the HELOC close-out condition. Vesting deed cross-checks clean against the source Title Notes (MATCH 1.00 in the sidecar). Exhibit A is single-paragraph — P-1 verification flag has been appended for closer review. Mortgage section is complete except [Field: missing Executed Date for Instr # XYZ] — P-2 flag also raised. **Recommend forwarding to closing agent with the two P-flag items called out as operator-action items.**"

## Cross-check with the regular `verify-cure-report` flow

When both a Title Notes report AND an OnE Report exist in the same case folder, the skill should:

1. Run the **9-check directives scorecard** (from `directives-checklist.md`) on the Title Notes — that's the abstractor-side verification.
2. Run the **10-check OnE scorecard** (this file) on the OnE Report — that's the client-side verification.
3. Run **cross-consistency checks** between the two:
   - Vesting deed in OnE §2 must equal vesting deed in Title's CURRENT OWNERSHIP block
   - Open mortgages in OnE §3 must equal mortgages classified `OPEN` or `POTENTIALLY OPEN` in Title
   - Critical issues in OnE callout must be a subset (top-N) of Title's Critical Issues section
   - Tax data in OnE §6 must match Title's TAX STATUS block field-for-field

Cross-consistency mismatches → 🟡 WARN at minimum, 🔴 FAIL if classifications diverge.

## Worked example outcome — `OnE_Report_Anand.pdf` (2026-05-26 13-page version)

| Check | Status |
|---|---|
| OnE-1 Section structure | 🟢 PASS — all 9 sections present + ordered |
| OnE-2 (a)–(l) codes | 🟢 PASS — all 12 codes labeled |
| OnE-3 Verbatim labels | 🟢 PASS — "(as ordered)", "Court/Case No." (no colon), Exhibit A split |
| OnE-4 POTENTIALLY OPEN warnings | 🟢 PASS — M-3 + M-4 both have red-bold direct-payoff warnings |
| OnE-5 Verbatim Exhibit A | 🟢 PASS + P-1 flag appended |
| OnE-6 Tax status echo | 🟢 PASS — 2025 figures from source preserved |
| OnE-7 Wrong-property vesting guard | 🟢 PASS — vesting deed MATCH 1.00 |
| OnE-8 Critical Issues callout | 🟢 PASS — 5 issues rendered, all `[CRITICAL]` items preserved |
| OnE-9 P-1 + P-2 flags | 🟢 PASS — P-1 applied (single-paragraph legal); P-2 N/A (mortgages complete) |
| OnE-10 No jargon | 🟢 PASS — zero forbidden terms |

**Verdict:** SHIPPABLE — all 10 OnE checks green; pair this with the underlying Title Notes verifier verdict before forwarding to closing agent.
