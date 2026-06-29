# Report Structure Reference — Required Sections + Validation Rules

CURE produces two markdown reports per case: a RAW exam (the AI's analysis output) and a Title Examination Notes (the polished abstractor product). Both have strict structural contracts enforced by the pipeline; this skill should verify the structure as well as the content.

---

## RAW Report — `RAW_TWO_OWNER_SEARCH_EXAM.md`

### Required H2 sections (in order)

The pipeline's `RAW_REQUIRED_SECTIONS` validator REJECTS any report missing these exact headers:

1. `## PHASE 1: RECORDER NAME SEARCHES`
2. `## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION`
3. `## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION`
4. `## PHASE 4: TAX & PROPERTY LOOKUP`
5. `## PHASE 5: RAW EXAM REPORT`

### Validation rules

| Rule | How to check |
|---|---|
| All 5 H2 headers present and spelled exactly | `grep -c "^## PHASE [1-5]:" RAW_TWO_OWNER_SEARCH_EXAM.md` should return 5 |
| No extra top-level `## ...` headers outside the 5 phases | Grep for `^## ` — every match should be one of the 5 phases or a permitted sub-header within Phase 5 |
| `## PHASE 4: TAX & PROPERTY LOOKUP` contains either `TAX STATUS NOT VERIFIED` OR a valid tax lookup result | Grep for the literal phrase or for `"status": "success"` near `tax_lookup_status.json` |
| `## PHASE 5: RAW EXAM REPORT` includes Phase-1 verification surfacing | Look for `subject-property`, `Subject-Property Match`, `Wrong-Property`, `RELEASED`, or similar verifier-output references |
| If `prohibited_documents.json` exists → report contains `## INACCESSIBLE / PROHIBITED DOCUMENTS` section | Grep for the section header AND for the literal statutory message |
| Each row of `documents_found.json` (less those moved to `not_needed/`) appears in the report | Cross-reference doc numbers — see Check D5 in `directives-checklist.md` |

### Sub-section expectations within Phase 5

The RAW prompt mandates a structure inside Phase 5:

- `### A. Property Information` — subject address, APN/folio, legal description
- `### B. Legal Description (verbatim)` — verbatim text from the vesting deed
- `### C. Current Vesting` — current record owner + Source: WD (preferred) or QCD (only with WD precedent)
- `### D. Chain of Title` — newest-to-oldest deed sequence
- `### E. Open Mortgages` — properly classified `open` mortgages only
- `### F. Released / Satisfied Mortgages` — released mortgages linked to their satisfactions
- `### G. Judgments / Liens / Lis Pendens / UCC` — any encumbrances
- `### H. Documents Examined and Excluded` — the audit trail for not_needed/ docs
- `### I. Critical Issues` — any RED-LIGHT items including Wrong-Property Matches
- `### J. Tax Status` — verified or `TAX STATUS NOT VERIFIED`

---

## Title Examination Notes — `Title_Examination_Notes.md`

### Required H1 + H2 sections (in order)

The pipeline's `TITLE_REQUIRED_SECTIONS` validator REJECTS any report missing these:

- `# Abstractor Notes/Chain` (H1 — **case-sensitive**; the running PDF header depends on it)
- `## TITLE EXAMINATION SUMMARY`
- `## CHAIN OF TITLE`
- `## LEGAL DESCRIPTION (EXHIBIT A)`
- `## DEEDS OF TRUST / MORTGAGES`
- `## DOCUMENTS EXAMINED`

### Validation rules

| Rule | How to check |
|---|---|
| `# Abstractor Notes/Chain` on line 1 (drives the PDF running header) | `head -1 Title_Examination_Notes.md` should match `# Abstractor Notes/Chain` |
| All 5 required H2 headers present | `grep -c "^## (TITLE EXAMINATION SUMMARY\|CHAIN OF TITLE\|LEGAL DESCRIPTION (EXHIBIT A)\|DEEDS OF TRUST / MORTGAGES\|DOCUMENTS EXAMINED)"` should return 5 |
| `## LEGAL DESCRIPTION (EXHIBIT A)` content is the VERBATIM Exhibit A from the most-recent vesting deed | Compare to `_verbatim_legal_descriptions.json` (if exists) or to the extracted text of the cited vesting deed |
| `## CHAIN OF TITLE` lists deeds newest-to-oldest with grantor/grantee/instrument/recording date/consideration | Table or list format; each row identifiable |
| `## DEEDS OF TRUST / MORTGAGES` is partitioned into OPEN vs RELEASED | Grep for both subsections |
| `## DOCUMENTS EXAMINED` is a complete inventory matching `documents_found.json` | Cross-reference doc numbers |
| `## ANALYSIS RULES`, `## IMPORTANT NOTES`, `## DISCLAIMER` sections present (per the system prompt template) | `grep -c "^## (ANALYSIS RULES\|IMPORTANT NOTES\|DISCLAIMER)"` should return ≥ 1 each |

### Critical content patterns inside Title

- **Joint vesting:** if both spouses appear on the vesting deed, the trust grants and trustee names should be cited (matches Tony's SIMMONS expectation about Simmons Family Revocable Living Trust)
- **HELOC chain:** parent HELOC + all modifications + subordinations grouped together, with maximum-principal increases noted
- **Released-mortgage evidence:** each released mortgage must cite the doc number of its satisfaction/release — NOT just "released" without evidence
- **Wrong-property docs:** any NO_MATCH deed from `phase1_verifications.json` must appear under Critical Issues / Wrong-Property, not in the chain of title

---

## Cross-doc consistency

The Title report should be CONSISTENT with the RAW report. The verifier should flag any of these as 🟡 WARN:

- RAW cites WD X as vesting; Title cites a different doc
- RAW classifies MTG Y as released; Title shows it under open
- RAW notes a wrong-property NOC; Title omits it
- RAW lists 23 docs examined; Title lists fewer

Severe inconsistencies (different vesting deed, different open-vs-released classification) → 🔴 FAIL.

---

## Versioned copies

Both reports get a versioned timestamped copy (e.g., `RAW_TWO_OWNER_SEARCH_EXAM_Broward_ANAND_v2_20260523_104453.md`). When verifying, prefer the un-versioned canonical file — but if multiple versioned copies exist, surface them as "previous iterations" so the user can compare.

The versioned copies are also the place to look for evidence that the prohibited-doc notice was correctly injected — the `inject_prohibited_notice()` step appends to BOTH the canonical and the latest versioned file.

---

## Tax-status integrity

If `workflow_config.fetch_tax == true`:
- `tax_lookup_status.json` must exist
- If `tax_lookup_status.status != "success"`, the RAW report MUST contain `TAX STATUS NOT VERIFIED` literally
- The Title report's `## TAX STATUS` section must echo the same disposition

If `fetch_tax == false`:
- RAW report's Phase 4 should say "tax lookup disabled by workflow configuration" or similar
- No false claim of tax-paid status anywhere in either report

---

## Companion File: `Tony_verified_commentary.md`

Every verification run produces a third file alongside the RAW and Title:
`<case_dir>/Tony_verified_commentary.md`. This is the **engineering-facing**
companion — the place where all the internal/diagnostic content that the
customer-facing Title MUST suppress (per F11) gets captured instead.

### File path

Same case folder as the Title (e.g.,
`src/titlepro/api/downloaded_doc/0522/Broward_ANAND_v2/Tony_verified_commentary.md`).

### Generator

`src/titlepro/verification/tony_commentary_generator.py`

CLI:

```bash
python3 -m titlepro.verification.tony_commentary_generator <case_dir>
```

### Citation format (CRITICAL)

The commentary's directive citations use **only** this format:

- ✅ `As per directive #5 (examine every indexed document; no silent dropping)`
- ✅ `As per directive #6 (released-mortgage exclusion via satisfaction linkage)`
- ❌ `Per Tony directive #5`
- ❌ `Tony directive #5`
- ❌ `Tony Roveda directive #6`
- ❌ Bare `directive #6` with no inline parenthetical description

The reviewer's name ("Tony" / "Tony Roveda") is suppressed even in the
engineering-facing companion file. Every citation MUST inline the one-line
description.

### Required sections (in order)

| # | Section | Content |
|---|---|---|
| 1 | `## Verifier Verdict` | `SHIPPABLE` / `SHIPPABLE WITH FIXES` / `BLOCKED — re-run required` / `BLOCKED — needs human review` |
| 2 | `## Step 0 — Source of Truth` | `SoT_PASS` / `SoT_DRIFT` / `SoT_MISSING_COUNTY` + county + master-sheet cross-check notes |
| 3 | `## Six Directives — Scorecard` | Per-directive PASS/FAIL/WARN row using "As per directive #N (description)" format |
| 4 | `## Known Failure Modes — Scans` | F1-F11 scan outcomes (PASS / DETECTED / N/A) with evidence |
| 5 | `## Subject-Property Address Verification (per doc)` | Table of doc# / extracted address / status / similarity / evidence — full per-doc MATCH/NO_MATCH disclosure |
| 6 | `## Document Type Classification (per doc)` | Table of doc# / inferred type / confidence / source / evidence snippet |
| 7 | `## Mortgage Status Classification (per mortgage)` | Per-mortgage status (open / released / modified) + release-chain doc# + book/page evidence + related modifications |
| 8 | `## Linker-vs-LLM Discrepancies` | Cases where the LLM caught something the regex linker missed (e.g., Book/Page-only cross-refs); ship-blocker if any |
| 9 | `## Engineering Follow-ups` | Items for the next CURE release — NOT for the customer (e.g., "tune linker to match Original-Mortgagor + Original-Mortgagee + Book/Page tuple") |
| 10 | `## Prohibited Documents` | FL Ch. 2002-302 (or equivalent) blocked docs with full statutory citation |
| 11 | `## Tony-Style Verdict` | Verbatim from the verifier's Step-6 Tony-voice paragraph |

### Allowed engineering vocabulary

The commentary MAY include (and the Title MUST NOT):

- `released_mortgage_linker`, `subject_address_verifier`, `document_type_classifier` (module names)
- `MATCH (1.00)` / `NO_MATCH (0.079)` (similarity scores)
- `[16, 16, 16, 23, 23, 23]` (per-search count patterns)
- `Phase-1 sidecar`, `sidecar`, `automated sidecar`
- `Engineering follow-up:`, `Engineering action:`, `tune the linker`
- `state contamination`, `linker gap`, `linker missed`, `linker misclassified`

### Sanity checks the verifier should run on the companion file

- File exists at `<case_dir>/Tony_verified_commentary.md`
- All 11 required sections present (`grep -c "^## "` ≥ 11)
- Directive citations match `r"As per directive #\d+\s*\([^)]+\)"` — not the
  bare `directive #N` or any reviewer-name variant
- Per-doc verifier rows match `phase1_verifications.json`
  `subject_address_verification` cardinality
- Per-mortgage rows match `phase1_verifications.json`
  `mortgage_classifications` cardinality
- `## Prohibited Documents` references every entry from
  `prohibited_documents.json` (if file exists)
