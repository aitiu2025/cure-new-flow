# Known Failure Modes — Regression Patterns To Detect

Each pattern below is a real defect we observed in 0521 / early-0522 runs. The verifier should actively scan for these in addition to the directive-based checks. Many of them are FAIL-level findings even if the directive checks pass — they indicate a deeper problem with the data pipeline or LLM behavior.

---

## F1 — `[N, 0, 0, 0, 0, 0]` state-contamination signature

**Origin:** The Selenium AcclaimWeb adapter hardcoded Kendo CSS selectors (`tr.k-master-row, tr.k-alt`) but Broward emits Telerik (`tr.t-alt`). After run 1 picked up rows via the Strategy-2 fallback, runs 2-6 failed silently and returned 0 every time.

**Where to detect:**

```python
import json
sr = json.load(open(f"{case_dir}/search_results.json"))
counts = [r["result_count"] for r in sr["runs"]]
if len(counts) >= 3 and counts[0] > 0 and all(c == 0 for c in counts[1:]):
    raise StateContaminationDetected(counts)
```

**Severity:** 🔴 ship-blocker.

**Remediation:** This is fixed in `acclaimweb_adapter.py` as of 2026-05-22 (broadened CSS selectors + URL-navigation in `return_to_search` + unioned Strategy 1+2). If a recent report shows this signature, the adapter regressed or the wrong adapter is being used.

---

## F2 — Wrong-property QCD shipped as vesting (the SIMMONS gate)

**Origin:** 0521 SIMMONS report cited QCD `119410878` (for property `6830 Falconsgate Ave, Davie, FL`) as the vesting deed for the subject property `2151 NW 93rd Ave, Pembroke Pines, FL`. The doc was indexed under the borrower's name (because she lived in/owned both properties) but is for a completely different parcel.

**Where to detect:**

1. Read `phase1_verifications.json` → `subject_address_verification`
2. For each doc with `status == "NO_MATCH"`, grep the RAW report for that doc number
3. If the doc appears in any role implying it conveys subject title (e.g., in `## CHAIN OF TITLE`, as the cited "current vesting", as the source of legal description) → FAIL

**Severity:** 🔴 ship-blocker. Per Tony's #4 directive, NO_MATCH deeds MUST appear only in Critical Issues / Wrong-Property sections.

**Remediation:** Verifier should escalate to `[CRITICAL] Wrong-Property Match` AND trigger RED LIGHT for human review. The 0522 v2 reports demonstrate this correctly (e.g., ANAND NOC `119437728` flagged as for "2929 N. University Dr. Unit 204").

---

## F3 — Released mortgage shown as "Open"

**Origin:** 0521 ANAND showed MTGs `111249687`, `112424642`, `110509371` as open mortgages despite the case folder containing their satisfactions. Tony's words: "It appears to have identified satisfactions but didn't connect the dots to remove them."

**Where to detect:**

1. Read `phase1_verifications.json` → `mortgage_classifications`
2. For each entry with `status: "released"`, grep the RAW report for the mortgage's doc number
3. If the surrounding context places it under "OPEN MORTGAGES" without an explicit release note → FAIL
4. Bonus detection: scan all `*_extracted.md` files for "satisfaction of mortgage", "release of mortgage", "discharge of mortgage" — for each found release, extract any cited instrument numbers OR Book/Page references and confirm those target mortgages aren't marked open in the report

**Severity:** 🔴 ship-blocker for direct-instrument-number references. 🟡 WARN for Book/Page-only references (the linker's regex misses these; LLM may have caught them).

**Remediation:** `released_mortgage_linker.py` now handles instrument numbers. Book/Page cross-references are an open issue — until fixed in code, the verifier should flag them as warnings and the LLM should be reading the doc content.

---

## F4 — Missing second-name search results

**Origin:** 0521 ANAND ran searches for both `ANAND, RISHI G` and `ANAND, PAYAL` but only RISHI's results survived (`[16, 0, 0, 0, 0, 0]`). PAYAL's 11 docs were lost. Same in SIMMONS — DESTON's 6 docs (including the missing MTG `112573690`) were lost.

**Where to detect:**

1. Read `workflow_config.json` → `search_requests` (the names that SHOULD have run)
2. Read `search_results.json` → `runs[*].name_searched` (the names that actually ran)
3. Read `documents_found.json` → for each doc, the `found_via_names` set
4. For each expected name from `workflow_config.search_requests`, confirm `sum(1 for d in documents_found if name in d.get("found_via_names", [])) > 0`
5. If an expected name has zero docs → FAIL (unless the report explicitly notes "no records found under name X — consider alias Y")

**Severity:** 🔴 ship-blocker. This is Tony's #3 directive.

**Remediation:** Already fixed via the Telerik-selector + URL-navigation fixes in `acclaimweb_adapter.py`. If a recent report shows this regression, the adapter swap may have broken.

---

## F5 — QCD as vesting without a preceding WD

**Origin:** 0521 SIMMONS report stood on a Quit-Claim Deed as the vesting. Tony's words: "We cannot stand on a QCD; we need to show the Warranty Deed and any subsequent QCDs, oldest to newest."

**Where to detect:**

1. Find the "current vesting" reference in the RAW report (typically in `## PHASE 5 > A. Property Information` or `## CHAIN OF TITLE`)
2. Extract the cited doc number(s)
3. For each: check `phase1_verifications.json` → `document_type_classifications` → `inferred_type`
4. If the FIRST doc in the chain is `DEED_QUITCLAIM` AND no `DEED_WARRANTY` precedes it → FAIL

**Severity:** 🔴 ship-blocker IF no WD exists. 🟡 WARN if WD exists but isn't cited first (LLM ordering issue).

**Remediation:** Title prompt now mandates "WD oldest to newest, then QCDs" — see `Title_Examination_Notes_System_Prompt.md` analysis rules. The 0522 v2 SIMMONS report correctly cites WD `112573689` (Sai Chhaya Properties LLC → Barker) as the vesting.

---

## F6 — Doc count vs search result count mismatch

**Origin:** 0521 ANAND `search_results.json` summary claimed 16 unique documents but `documents_found.json` had only 11 after the search phase completed (no filter step had run yet). Indicates extraction loss in the search → documents_found.json conversion.

**Where to detect:**

```python
sr = json.load(open(f"{case_dir}/search_results.json"))
expected = sr["summary"]["total_unique_documents"]
actual = len(json.load(open(f"{case_dir}/documents_found.json")))
if actual < expected:
    # Confirm whether the diff was filtered to not_needed/ or genuinely lost
    notneeded = case_dir / "not_needed/documents_found.json.original"
    if not notneeded.exists() or len(json.load(notneeded.open())) - actual != expected - actual:
        FAIL: f"Lost {expected - actual} docs between search and documents_found"
```

**Severity:** 🔴 ship-blocker if no `not_needed/` audit trail exists.

---

## F7 — Address-extraction picks the LENDER's office address

**Origin:** 0522 ANAND (pre-2026-05-23 upgrade) had 4 mortgage docs whose subject_address_verifier extracted `7455 Chancellor Drive, Orlando, FL` — that's SunTrust Bank's HQ address, NOT the borrower's subject property. Resulted in 5 false NO_MATCH verdicts.

**Where to detect:**

1. Read `phase1_verifications.json` → `subject_address_verification`
2. For each NO_MATCH entry, inspect the extracted address. If it matches known bank/lender HQ patterns (BANK, FINANCIAL, MORTGAGE in the city/state context, or addresses outside the subject's metro area) → FLAG.
3. Cross-check by re-running `extract_subject_address_from_text(text, subject_hint=subject)` with the current verifier code. If the new run returns MATCH but the saved sidecar shows NO_MATCH → the pipeline was run with the pre-upgrade verifier; recommend regenerating reports.

**Severity:** 🟡 WARN — outdated verifier code, not a real address mismatch.

**Remediation:** The 2026-05-23 verifier upgrade added keyword-proximity scoring with positive boosts for "currently has the address of" / "Property Address:" and penalties for "Lender's address" / "After recording return to". If the verifier output looks suspicious, regenerate with the upgraded code.

---

## F8 — Prohibited doc shipped without statutory notice

**Origin:** ANAND doc `113945927` is a `CPX - Court Papers Hidden from Web` filing in divorce case `FMCE-16-009289`. Per FL Ch. 2002-302, the image cannot be displayed on the Internet. CURE downloads return 404 with the statutory notice text in the body.

**Where to detect:**

1. Read `prohibited_documents.json` (if exists)
2. For each entry, grep the RAW report and the Title report for the doc number
3. The reports MUST contain:
   - The doc number listed in `## INACCESSIBLE / PROHIBITED DOCUMENTS`
   - The verbatim statutory message: "In accordance with CHAPTER 2002-302 of the Laws of Florida, this page of the requested document is prohibited from being displayed on this Internet website."
4. If either is missing → FAIL

**Severity:** 🔴 ship-blocker. Legal-compliance issue — the abstractor must explicitly disclose blocked documents.

**Remediation:** `inject_prohibited_notice()` in the pipeline runner handles this. Confirm it ran by checking the report for the statutory string.

---

## F9 — Search results' `document_type` interpreted literally

**Origin:** Broward's `document_type` column in the search results actually contains the GRANTEE name (e.g., "TRUIST BANK", "SUNTRUST BANK", "HERNANDEZ CONSTRUCTION LLC") rather than the actual doc type. A pre-2026-05-23 `released_mortgage_linker` couldn't identify any docs as mortgages because none had `document_type` containing "MORTGAGE".

**Where to detect:**

1. Read `documents_found.json` — sample 3-5 `document_type` values
2. If they look like grantee names (BANK / LLC / INC suffixes, person names) rather than doc-type labels → FLAG
3. Confirm `phase1_verifications.json` has a `document_type_classifications` block — this is what should be used instead

**Severity:** 🟡 WARN if `phase1_verifications.json` has the classifications. 🔴 FAIL if a verifier-equivalent doesn't exist and downstream consumers (the LLM, the linker) are relying on the unreliable column.

**Remediation:** Use `document_type_classifications` from `phase1_verifications.json`. The 2026-05-23 `document_type_classifier.py` infers actual types from OCR content.

---

## F11 — Internal-tool plumbing leaked into customer-facing Title report

**Origin:** 0522 ANAND v2 Title Examination Notes contained references to `released_mortgage_linker sidecar`, `subject-property address verifier`, per-doc `MATCH (1.00)` similarity scores, the `[16, 16, 16, 23, 23, 23]` per-search count pattern, "Engineering follow-up: tune linker to...", and a `Critical Issue #8: Linker Gap` item that described a tooling-misclassification rather than a title-state problem. The Title is the **customer-facing deliverable** — these would confuse closing attorneys, escrow officers, and lenders who don't need to know about CURE's internal modules.

**Where to detect:**

```python
import re
title_text = open(f"{case_dir}/Title_Examination_Notes.md").read()
forbidden_patterns = [
    r"released_mortgage_linker",
    r"subject[- ]?address[- ]?verifier",
    r"subject[- ]property[- ]address[- ]?verifier",
    r"document_type_classifier",
    r"Phase[- ]1 sidecar",
    r"\bsidecar\b",
    r"\[\s*\d+(?:\s*,\s*\d+){5,}\s*\]",      # per-search count tuple
    r"state[- ]contamination",
    r"Engineering action:",
    r"Engineering follow-up:",
    r"tune (?:the )?(?:linker|verifier|classifier)",
    r"MATCH\s*\(\d\.\d{2}\)",                 # MATCH (1.00) similarity score
    r"NO_MATCH\s*\(\d\.\d{2}\)",
    r"automated sidecar",
    r"computed sidecar",
    r"linker (?:gap|missed|misclassified)",
    # Reviewer-name / directive-citation patterns (Title is customer-facing;
    # the reviewer's identity and bare directive citations don't belong here).
    # The engineering-facing Tony_verified_commentary.md MAY cite directives,
    # but only in the format "As per directive #N (one-line description)".
    r"(?i)\bper Tony( Roveda)?\b",
    r"(?i)\bTony( Roveda)? directive[s]?\s*#?\d*",
    r"(?i)\bTony Roveda\b",
    r"(?i)\bper [A-Z][a-z]+( [A-Z][a-z]+)?('s)? (review|directive)",
    r"(?i)\bAs per Tony",
    r"(?i)\bPer Tony directive[s]?\s*#?\d*",
    r"(?i)\bTony directive[s]?\s*#\d+",
    r"(?i)\bper Tony('s)? review",
    r"(?i)\bper Tony('s)? directive",
    r"(?i)\bdirective #\d+\b(?!\s*\()",       # bare "directive #N" without inline parenthetical
]
hits = []
for p in forbidden_patterns:
    for m in re.finditer(p, title_text, re.IGNORECASE):
        line_no = title_text[:m.start()].count("\n") + 1
        hits.append((line_no, p, m.group(0)))
```

**Severity:** 🔴 ship-blocker for the Title report. The RAW report MAY contain these (it's engineering-facing).

**Remediation:**
1. The Title system prompt (`/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/Title_Examination_Notes_System_Prompt.md`) has a CUSTOMER-FACING LANGUAGE RULES section (added 2026-05-23) that explicitly forbids each of these patterns. If a Title report still contains them, regenerate the Title only (no need to re-run search/extract/RAW) — the updated prompt will produce a clean version.
2. The customer-facing equivalents are documented in the same prompt section (e.g., `MATCH (1.00)` → ✓; `Engineering follow-up:` → omit entirely; `linker sidecar misclassified` → state the correct fact directly).
3. The check applies ONLY to `Title_Examination_Notes.md` and its versioned copies — NOT to `RAW_TWO_OWNER_SEARCH_EXAM.md` which is engineering-facing.

**Why this matters:** the customer is reading a title-examiner product, not a software diagnostic. Leaking tool names erodes trust ("does CURE even know what it's reporting?") and creates support burden ("what's a 'linker'?"). The fix is one prompt update + one regeneration — cheaper than answering customer questions later.

**Companion-file rule (engineering-facing `Tony_verified_commentary.md`):**
The companion file MAY discuss internal tooling and directives, but MUST use the canonical
citation format:

- ✅ `As per directive #5 (examine every indexed document; no silent dropping)`
- ✅ `As per directive #6 (released-mortgage exclusion via satisfaction linkage)`
- ❌ `Per Tony directive #5`
- ❌ `Tony directive #5`
- ❌ `As per Tony's directive`
- ❌ `Tony Roveda directive #6`
- ❌ Bare `directive #6` with no inline parenthetical description

The reviewer's identity ("Tony" / "Tony Roveda") is suppressed even in the engineering file.
Every directive citation must inline the one-line description so the reader understands the
rule without lookup. The six directives + their canonical one-line descriptions:

- D1 (no Selenium/Playwright in Phase 1 search — use HTTP GET/POST)
- D2 (deed-first search: DocType=DEED → extract APN → APN search)
- D3 (run ALL provided names + cross-check Deed# between spouses)
- D4 (NLP-verify subject address from deed image content)
- D5 (examine every indexed document; no silent dropping)
- D6 (released-mortgage exclusion via satisfaction/release linkage)

---

## F10 — Pagination loss (8 visible, 16+ actual)

**Origin:** Telerik grids on Broward show ~8 rows per page. A naive scrape of visible rows gets 8 docs when the real total is 16+. Caught when 0522 ANAND initially returned 8 docs per RISHI search vs 16 in 0521.

**Where to detect:**

1. Read `documents_found.json` count
2. Compare to known-good counts for the case (if any). For ANAND, expect 23 unique docs. For SIMMONS-BARKER, expect ~20 unique docs.
3. Check the extractor log (`extracted N document(s) via union strategy (s1=X, s2_added=Y)`). If `s1` ≈ 8-11 and `s2_added` is 0 → pagination loss; the union fallback isn't picking up the missing rows.

**Severity:** 🟡 WARN if counts are low but the union extraction is in place. 🔴 FAIL if counts are dramatically below expectations and no fallback ran.

**Remediation:** The 2026-05-22 union-extraction fix runs both Strategy 1 (Kendo/Telerik visible rows) and Strategy 2 (all-table scan) and dedupes — this recovers the hidden-pagination rows on Broward.

---

## F12 — Placeholder / non-resolution language in customer-facing Title

**Origin:** 0526 batch shipped multiple Title reports that punted on resolvable gaps with placeholder text like "needs to be pulled manually", "manual pre-2010 abstractor pass required", "(prior owner — confirm by pulling recorded image)", "outside the automated search range" — even though the data was retrievable from the recorder's HTTP API or the county Property Appraiser's sale history. The user surfaced this 2026-05-26 evening: such language "defeats the whole purpose of building this product."

**Forbidden phrases in customer Title** (case-insensitive grep; any hit = 🔴 FAIL):
- `manual fetch`, `pulled manually`, `manual pre-\d+`, `manual abstractor pass`
- `to be pulled`, `to be confirmed`, `to be verified` (when the data IS resolvable)
- `(prior owner —`, `(prior owner -`, `confirm by pulling`
- `outside the automated search` / `outside search window` — UNLESS accompanied by a citation that (a) the date IS provably before the recorder's earliest indexed entry AND (b) the Property Appraiser sale-history also doesn't surface it
- `not available` / `Not Available` — UNLESS the immediately following sentence cites a concrete non-availability reason (statutory block, image-sealed, indexed window predates digitization, etc.)

**Detection:**
```bash
grep -niE "manual fetch|pulled manually|to be pulled|to be confirmed|\(prior owner [—-]|confirm by pulling|outside (the )?automated|outside search window|not available" Title_Examination_Notes.md
```

If any hit lacks a justifying citation in the same paragraph → 🔴 ship-blocker.

**Severity:** 🔴 ship-blocker. Customer report quality is the product. A placeholder shipped to a customer is a regression to the legacy "manual abstractor" tool the product is supposed to replace.

**Remediation:** Pull the actual data. Every FL recorder we support (AcclaimWeb, Tyler self-service, Landmark, bare-IIS Hillsborough, Manatee Clerk) exposes a `JumpToInstrumentNumber` or equivalent direct-retrieval endpoint — see `acclaimweb_http_adapter._handshake_disclaimer` + `details/JumpToInstrumentNumber/{record_type}/{doc_num}` for the canonical pattern. If the prior-deed grantor is unknown, GET the detail page; the grantor/grantee/book-page/consideration all render in the listDocDetails block. If a deed is genuinely pre-window AND the PA has no record of it, cite that explicitly: "Pre-2007 deed at OR Book X/Page Y — outside Hillsborough's electronic indexing window which begins 2007-01-02; certified copy available from Clerk's office, $X fee, ~7-day turnaround."

---

## F13 — Tax lookup skipped without concrete justification

**Origin:** 0526 Orange GREER + PalmBeach HABER + Manatee FERNANDEZ all shipped with either `fetch_tax: false` in workflow_config OR "TAX STATUS NOT VERIFIED" boilerplate in the report — none of which had concrete ticket-class text explaining (a) what adapter is missing, (b) what was probed, (c) what the next-step fix is.

**Detection:**
1. Read `workflow_config.json`. If `fetch_tax: false` → check the case's `_REPORT_NOTICES.md` or `tax_lookup_status.json` for an explicit justification. No justification → 🔴 FAIL.
2. Read both RAW + Title. If "TAX STATUS NOT VERIFIED" appears, scan the surrounding paragraph for a concrete next-step ticket text. If absent → 🔴 FAIL.
3. The acceptable boilerplate is: "TAX STATUS NOT VERIFIED — Tax adapter for {platform} (e.g. Aumentum, GovHub, AS400) is not yet built for {county}. Probed endpoints {URLs} returned {responses}. Engineering ticket: build `src/titlepro/tax/{platform}_http.py` mirroring `grant_street_http.py`. Manual lookup available at {URL}."

**Severity:** 🔴 ship-blocker if no justification. 🟡 WARN if the adapter is documented missing + ticket exists.

**Remediation:** Either BUILD the missing tax adapter (the Grant Street HTTP pattern is ~390 LOC, fully usable as a template — see `src/titlepro/tax/grant_street_http.py`), OR file the engineering ticket inline in the report with the concrete next steps above. Never just say "TAX STATUS NOT VERIFIED."

---

## F14 — Property Appraiser anchor missing for a non-Broward FL county

**Origin:** 0526 batch — only Broward had a working PA anchor (BCPA built 2026-05-26). Orange, Manatee, Palm Beach, Hillsborough shipped without `phase1_property_appraiser.json` + `phase1_reconciliation.json` sidecars, meaning the SIMMONS wrong-property gate is unenforceable, the ANAND-class corporate-grantor priors are unrecoverable, and the report has no canonical APN/owner-of-record cross-reference.

**Detection:**
1. Check for `phase1_property_appraiser.json` + `phase1_reconciliation.json` in the case folder. Missing → 🔴 FAIL (unless the county is genuinely non-FL or has no PA portal — which is rare).
2. Even if the sidecars are present, verify `status: PA_SUCCESS`. `PA_NO_RUNNER` means the adapter is missing — 🔴 FAIL.
3. The PA anchor's APN MUST match the workflow_config `apn` (digit-stripped comparison).

**Severity:** 🔴 ship-blocker. The PA anchor is the only mechanism that catches wrong-property false positives and recovers pre-window back-chain priors.

**Remediation:** Build the county's PA adapter. The canonical pattern is `src/titlepro/property_appraiser/counties/broward_bcpa.py` (~310 LOC). Steps: (1) probe the live portal, save canonical request/response to `/tmp/{county}_pa_probe.md`; (2) mirror the file structure (`counties/{county}_xxx.py`); (3) add ≥10 unit tests in `tests/unit/test_property_appraiser_{county}_xxx.py`; (4) register in `config/county_property_appraiser_urls.json`; (5) live-run for the case.

Known FL PAs awaiting adapter (2026-05-26):
- Orange: https://www.ocpafl.org/
- Palm Beach: https://www.pbcpao.gov/
- Manatee: https://www.manateepao.gov/
- Hillsborough: https://gis.hcpafl.org/CommonServices/property/search/
- Miami-Dade: https://www.miamidade.gov/Apps/PA/PAOnlineTools/

---

## F15 — Prior-owner deed cited with placeholder grantor/grantee

**Origin:** Same root cause as F12 — chain-of-title tables in 0526 reports had rows like `| 2 | 03/16/2011 | (Book 47826 / Pg 836) | Certificate of Title | (Prior owner — likely foreclosed mortgagor) | Regent Bank | ... |` even though `GET /details/JumpToBookPage/27/47826/836` returns the actual grantor list (`BROWARD COUNTY CIRCUIT COURT, BAUM,GREGORY, BAUM,ROBERT`) and case number (`CACE-10-037436`) in plain HTML.

**Detection:**
```bash
grep -niE "\(Prior owner|\(prior owner|\(Unknown\)|\(unknown\)|\(.+confirm by pulling|likely foreclosed mortgagor" Title_Examination_Notes.md RAW_TWO_OWNER_SEARCH_EXAM.md
```

Any hit on a chain-of-title row when the corresponding instrument# or book/page IS retrievable from the recorder → 🔴 FAIL.

**Severity:** 🔴 ship-blocker.

**Remediation:** Use the recorder's direct-retrieval endpoint (`JumpToInstrumentNumber` / `JumpToBookPage` / equivalent) to GET the detail page for every prior-deed entry in the PA sale history. Parse the `listDocDetailsLabel` + `listDocDetails` blocks (or county-specific equivalent) to extract Grantor/Grantee/Doc Type/Consideration/Case Number/Legal. Patch the chain table with the concrete data. Tony's two-owner-chain directive is satisfied only when EVERY row in the chain has concrete party names; "(prior owner)" placeholders mean the chain is incomplete by construction.

---

## F18 — OnE contains `(a)`–`(l)` mapping codes (RETIRED — 2026-05-28 redline)

**Origin:** The 0526 OnE prompts emitted internal (a)/(b)/(c)/.../(l) field-mapping codes from Peter Bodonyi's draft template. The 2026-05-28 redline retired those codes — they were internal-only and confused the closing agent.

**Detection:**
```bash
grep -niE "\*?\([a-l]\)\*?" OnE_Report_*.md
```

Any hit → 🔴 FAIL. The current OnE prompt (`OnE_Report_System_Prompt.md`) explicitly forbids `(a)`–`(l)` codes anywhere in the rendered output.

**Severity:** 🔴 ship-blocker.

**Remediation:** Strip every `*(letter)*` and `(letter)` instance from the OnE output. The OnE prompt's "Required structure" section enforces this.

---

## F19 — OnE contains forbidden engineering / Title-only rows

**Origin:** The 0522 v2 OnE for ANAND carried over engineering / Title-only fields that the 2026-05-28 redline retired: Doc Stamps, Subject-Address Verification, Search Range, TRA / Millage / Taxing Authority Code, Subject-Property APN Anchor sub-table, Pre-Search-Range PA sale-history rows, Peter P-1 / P-2 mortgage-completeness flags, Examiner Classification column, Prepared By, Notes column on mortgages, Released/Reconveyed mortgage subsection.

**Detection:**
```bash
grep -niE "Doc Stamps|Subject-Address Verification|\*\*Search Range:?\*\*|^.+\| TRA \||\*\*TRA[^A-Z]|Millage|Taxing Authority Code|Subject-Property APN Anchor|Pre-Search-Range Sale History|Peter P-[12]|Examiner Classification|\*\*Prepared By|\| Notes \||### Released|### Reconveyed" OnE_Report_*.md
```

The patterns are tightened to match **labeled field rows / column headers** (`**Search Range:**`, `**TRA**`, `**Prepared By**`, `| Notes |` as a column header), not incidental prose like "in the search range" (which is a customer-acceptable phrase in §4 Judgments "None of record … in the search range"). Any hit → 🔴 FAIL.

**Severity:** 🔴 ship-blocker. These fields live in the Title only; rendering them in the OnE breaks the OnE-vs-Title content matrix locked by the project CLAUDE.md.

**Remediation:** Regenerate the OnE under the current `OnE_Report_System_Prompt.md`. Each forbidden field is explicitly listed as STRIPPED in the prompt's §1-§8 rules.

---

## F20 — OnE Exhibit A not on own page

**Origin:** The 0522 v2 OnE rendered §8 Exhibit A immediately after §7 with no forced page break, so the legal description shared a page with the NOC table and looked cluttered.

**Detection (accepts BOTH render paths — DOCX via pandoc OOXML AND PDF via CSS HTML):**

```bash
# Path A — DOCX (canonical via pandoc): raw OOXML page-break block on its own line
grep -nE '^```\{=openxml\}$' OnE_Report_*.md          # opening fence
grep -nE 'w:br w:type="page"' OnE_Report_*.md         # the page-break element

# Path B — PDF supplementary (via renderers.py CSS): HTML div with page-break-before class
grep -nE 'page-break-before|page-break' OnE_Report_*.md
```

EITHER path is acceptable. The directive (whichever form is used) must appear within ~1-2 lines BEFORE the `## 8. Exhibit A` / `## Exhibit A` header.

| Status | When |
|---|---|
| 🟢 PASS | One of the two page-break forms appears immediately before the Exhibit A header. |
| 🟡 WARN | Neither form appears (Exhibit A will share a page with §7 / §6). |

**Severity:** 🟡 fix-recommended (cosmetic but tracked).

**Remediation (DOCX path — canonical):** Insert this raw OOXML pandoc block immediately before `## 8. Exhibit A`:

````
```{=openxml}
<w:p><w:r><w:br w:type="page"/></w:r></w:p>
```
````

Pandoc's markdown→DOCX pipeline emits this verbatim into the Word document, producing a hard page break that Word, Pages, and Google Docs all honor.

**Remediation (PDF path — supplementary):** Emit `<div class="page-break-before"></div>` on its own line immediately before the `## 8. Exhibit A` header. The CSS rule in `src/titlepro/automation/renderers.py::CSS_SHARED` (`.page-break-before { page-break-before: always; }`) handles the rest. The HTML pass-through in the markdown-to-html converter is in place as of 2026-05-28.

In practice the same markdown file can carry BOTH directives — pandoc DOCX honors the OOXML fence and ignores the `<div>`; weasyprint PDF honors the `<div>` and ignores the OOXML fence (which it skips as an unknown fenced block). The OnE renderer is fine with both present.

---

## F21 — OnE Exhibit A missing boilerplate prefix

**Origin:** Tony's 2026-05-28 redline mandates the legal description be preceded by the verbatim boilerplate `The following described land, situate, lying and being in [County] County, Florida, to-wit:` (with `[County]` substituted by the actual county name).

**Detection:**
```bash
# The line(s) following the Exhibit A header must contain this exact phrase.
awk '/^##.*Exhibit A/,/^##[^#]/' OnE_Report_*.md | grep -E "following described land, situate, lying and being in .+ County, .*, to-wit"
```

If no match → 🔴 FAIL.

**Severity:** 🔴 ship-blocker. The boilerplate is the canonical Florida deed-description prefix and is required for downstream legal-language consistency.

**Remediation:** Edit the OnE markdown to add the boilerplate line between `### Legal Description` and the verbatim legal description blockquote. See `OnE_Report_System_Prompt.md` §8 for the exact template.

---

## F22 — OnE Judgments section contains municipal-search caveat

**Origin:** Some early OnE drafts added "code-enforcement not searched" / "municipal-lien search not included" disclaimers to §4 Judgments. The 2026-05-28 redline retired this — CURE is not paid or insured for municipal searches, and volunteering the disclaimer creates downstream support burden ("why didn't you check?").

**Detection:**
```bash
grep -niE "code.?enforcement.*not searched|municipal lien search|code enforcement search|not paid.*municipal|not insured.*municipal|municipal.*not (covered|included|searched|performed)" OnE_Report_*.md
```

Any hit → 🔴 FAIL.

**Severity:** 🔴 ship-blocker.

**Remediation:** Remove the caveat. §4 Judgments must render only the recorder-search findings (or "None of record …") with the small bulleted sub-list of categories — no municipal-search disclaimer.

---

## F23 — OnE contains Released / Reconveyed Mortgages subsection

**Origin:** The 2026-05-28 user lock-in: "Released Mortgages — Title only. OnE shows OPEN mortgages only." Some 0526 OnEs still carried a `### Released / Reconveyed Mortgages (informational)` table inside §3.

**Detection:**
```bash
grep -nE "^### Released|^### Reconveyed|^## Released|^## Reconveyed" OnE_Report_*.md
```

Any hit → 🔴 FAIL.

**Severity:** 🔴 ship-blocker.

**Remediation:** Drop the Released/Reconveyed table from §3 entirely. The released-mortgage detail (with satisfaction/release instrument # + Book/Page evidence) lives in the Title's `## DEEDS OF TRUST / MORTGAGES → ### Reconveyed / Released Deeds of Trust` block only.

---

## F24 — Released satisfactions silently dropped to `not_needed/` (Broward AcclaimWeb F9 family)

**Origin:** Broward AcclaimWeb returns the GRANTEE NAME in the search-index `document_type` column (e.g., `"MORTGAGE ELECTRONIC REGISTRATION SYSTEMS INC"`) instead of the actual doc type. Search-side filter trusts the column → dumps satisfactions into `not_needed/`. Downstream `document_type_classifier` (2026-05-23) re-classifies via OCR content but only runs against `documents_found.json`, never against `not_needed/`. Result on ANAND v2: `111293535` (02/01/2013 SunTrust satisfaction of `110509370`) + `116593405` (07/07/2020 TD Bank satisfaction of `111249687`) shipped for ~5 days as POTENTIALLY OPEN.

**Fix landed (2026-05-29):** `src/titlepro/verification/not_needed_audit.py` scans `case_dir/not_needed/*_extracted.md`, re-classifies via OCR, runs (date + Book/Page + MIN + principal) cross-reference, returns `RecoveredDocument` list spliced into the linker corpus + `LedgerEntry` list (Tony directive #5 every-doc accounting). Linker accepts `recovered_docs=` kwarg. Driver at `tools/audit_existing_case.py <case_dir>` retro-fits existing case folders.

**Detection (run on any case folder):**
```bash
PYTHONPATH=src python3 tools/audit_existing_case.py <case_dir>
# Compare phase1_verifications.json before/after — any mortgage that flipped from open → released is evidence the regression was present
```

**Severity:** 🔴 ship-blocker on Broward / AcclaimWeb-fronted FL counties.

**Remediation:** Always run `tools/audit_existing_case.py` against any AcclaimWeb case folder before declaring Title Notes ship-ready. For new case generation, ensure the audit phase runs INSIDE the producer pipeline (currently runs as a post-hoc driver — to-do: wire into `run_e2e.py` / `run_phase4_verifications.py`).

---

## F25 — Linker can't pair satisfaction to mortgage when mortgage's OCR Book/Page is degraded (F17)

**Origin:** Pre-2000 mortgages (typically 1986-1997 vintage) have title-page OCR so degraded that `released_mortgage_linker.find_referenced_instruments` cannot extract the mortgage's Book/Page from its own document. Example from FROMER (Hillsborough): mortgage `86249257`'s title page OCRs as `EKO06O O029` (should be Book 4960 Pg 291). The satisfaction `88093094` cleanly cites `Book 4960 page 291` in its body, but the linker can't match because there's no clean Book/Page on the mortgage side. Result on FROMER: 8 legacy mortgages (1986-1997) shipped as POTENTIALLY OPEN when they were all RELEASED of record.

**Detection:**
1. Read any case folder's `Title_Examination_Notes.md` and count `POTENTIALLY OPEN — NO RECONVEYANCE FOUND` occurrences
2. If >0 AND the mortgages span pre-2000 vintage → likely F25 candidate
3. Manually run: for each POTENTIALLY OPEN mortgage, grep all `*_extracted.md` in main corpus for the mortgage's lender name + date + principal — if a SATISFACTION cover page references the right (date + principal + lender + parties), it's F25
4. If FROMER-style (8 of 10 mortgages flipped under audit) → confirmed F25

**Fix status (as of 2026-05-29):** NOT IMPLEMENTED. FROMER was manually patched (apply_8_reclassifications.py one-off). The `not_needed_audit` module addresses F24 (drops in `not_needed/`) but not F25 (drops via Book/Page extraction failure on docs in main corpus).

**Severity:** 🔴 ship-blocker if pre-2000 mortgages present and shipped as POTENTIALLY OPEN.

**Remediation (when built):** Add fallback to `released_mortgage_linker.find_referenced_instruments` — when mortgage Book/Page extraction fails, triangulate via (date + principal + lender + parties) from the mortgage's OCR'd content vs the satisfaction's body cite. Multi-anchor scoring with min-2-of-4 match threshold. For now, manual audit + patch (`tools/audit_existing_case.py` extension or one-off script) is the workaround.

**Workaround pattern for client-facing OnE that needs F25 audit corrections:** Apply the **Internal Memo pattern** — keep the F25 audit correction visible in the Title Notes (banner at top — abstractor-internal is appropriate). For OnE: do NOT add a banner. Instead, append `[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]` block AFTER `## 8. Exhibit A` containing the full reclassification evidence + reviewer action items + engineering follow-ups. Operator deletes the section before forwarding to client. Canonical example: `src/titlepro/api/downloaded_doc/0526/Hillsborough_FROMER_v1/OnE_Report_Fromer.md`.

## F26 — Messy print: raw render artifact leaked into the customer PDF/DOCX

**Origin:** A DOCX-only / source-only construct rendered as **literal visible text** in the deliverable. Canonical case (0617 batch, 2026-06-17): the OnE source carries a `` ```{=openxml} `` page-break block (`<w:p><w:r><w:br w:type="page"/></w:r></w:p>`) that pandoc consumes correctly for the DOCX, but the PDF renderer (`render_one_report.py`, python-`markdown` + `fenced_code`) rendered it as a literal code block — so the raw OOXML printed on the page just above `## 8. Exhibit A`. Affected ALL 12 OnE PDFs. Same failure class covers any leaked markup: `<div class="page-break-before">` printing as text, an HTML-comment sentinel (`<!-- VERIFIER-STATUS-START -->`) printing, stray pandoc raw-attribute fences, escaped table HTML, etc.

**Detection (scan the RENDERED deliverable, not the `.md`):**
1. `pdftotext <OnE_Report_*>.pdf -` (and/or the DOCX's visible run text) → grep the VISIBLE text for any of: `w:br`, `w:type=`, `<w:p`, `<w:r`, `{=openxml}`, `page-break-before`, a literal `<div`, or a stray `<!--`/`-->`.
2. ANY hit in the rendered visible text = messy print.
3. Do NOT flag the `.md` source for `` ```{=openxml} `` or the `<!-- VERIFIER-STATUS -->` wrapper — those are intentional source constructs. Do NOT flag `w:br` inside the DOCX `document.xml` when it is an actual page-break ELEMENT (legitimate); only flag it when it surfaces as visible run text. The reliable signal is the **PDF text**.

**Severity:** 🔴 **ship-blocker — forces verdict RED.** Stamp the report `🔴 **Manual review needed — messy print detected**` (Step 8) regardless of every other check's score. A client must never receive a report with raw markup printed in it.

**Remediation:** Fix the renderer, do not hand-edit the PDF. For the canonical case: `render_one_report.py` now strips `` ```{=openxml}``  `` blocks before conversion (`_strip_raw_openxml`) and a `.page-break-before { page-break-before: always; }` CSS rule drives the PDF page break via the existing `<div>`. Re-render, then re-scan per Detection above to confirm 0 hits before shipping.
