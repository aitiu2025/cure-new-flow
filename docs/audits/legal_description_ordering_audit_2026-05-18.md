# Audit — Legal Description Verbatim Capture + Canonical Ordering
**Date:** 2026-05-18
**Auditor:** code-audit agent (read-only)
**Scope:** Title + RAW report generation across the 0513 case dirs (MONTOYA, WALTERS, AMAYA)
**Branch:** `0422_titlePro_checkpoint`

---

## Defects observed

### Defect 1 — Legal Description is paraphrased, not verbatim
**Confirmed.** Across every Title (and RAW) report examined, the "Legal Description (Exhibit A)" block is a re-typeset paraphrase of the source PDF's Exhibit A. The pipeline:
1. Adds Markdown emphasis (`**Lot 10**`, `**Justice Subdivision...**`) that is not in the source.
2. Silently "corrects" OCR artifacts (source: `"Unit No, 2"` → output: `"Unit No. 2"`).
3. Substitutes synonyms (source: `"Volume 51 of Maps"` → output: `"Book 51 of Maps"`).
4. Collapses prepositional phrases (source: `"Office of the Recorder of the County of Contra Costa, State of California"` → output: `"Office of the Recorder of Contra Costa County, California"`).
5. **Drops entire substantive clauses** — e.g. the WALTERS Exhibit A omits the 15-line mineral / hydrocarbon / geothermal reservation paragraph and the AMAYA / MONTOYA Exhibits omit the "THIS BEING THE SAME PROPERTY CONVEYED TO …" conveyance recital.

### Defect 2 — No enforced canonical ordering (Deed → Addendum A → Legal Description → APN/PIN/Parcel)
**Confirmed.** The canonical ordering is enforced nowhere — not in `RAW_REQUIRED_SECTIONS` / `TITLE_REQUIRED_SECTIONS`, not in either external system prompt, not in any post-generation validator, and not in any renderer. Concretely:
- `TITLE_REQUIRED_SECTIONS` (`pipeline.py:48-54`) only mandates: `# Abstractor Notes/Chain`, `## TITLE EXAMINATION SUMMARY`, `## CHAIN OF TITLE`, `## DEEDS OF TRUST / MORTGAGES`, `## DOCUMENTS EXAMINED`. Legal Description is NOT a required section.
- In all three observed cases, the Legal Description section is placed near the END of the Title md (line ~200+), AFTER `DOCUMENTS EXAMINED`, mirroring item #10 of the Step2 prompt's list. There is no proximity to the vesting Deed.
- The token "Addendum A" appears in zero generated reports. Nothing in the pipeline ever surfaces an Addendum A even when the source DOT references one (e.g. WALTERS `B49178641_extracted.md:260` references "Rules-of-Agency Disclosure Addendum").
- Heading capitalization drifts between runs: MONTOYA uses `## Legal Description (Exhibit A)`; WALTERS / AMAYA / QUINTANA use `## LEGAL DESCRIPTION (EXHIBIT A)`.

---

## Evidence

### MONTOYA — `B49178046.pdf` (DOT, instrument 2026-0022802) vs `Title_Examination_Notes.md`

**Source DOT — PyMuPDF text layer is empty (image-only PDF, 11 pages).** OCR text layer extraction is in `B49178046_extracted.md` at lines 667-694 (verbatim from OCR):

```
EXHIBIT A

THE LAND REFERRED TO IS SITUATED IN THE COUNTY OF
CONTRA COSTA, CITY OF EL CERRITO, STATE OF CALIFORNIA,
AND IS DESCRIBED AS FOLLOWS:

LOT 10, AS SHOWN ON THE MAP OF JUSTICE SUBDIVISION, UNIT
NO. 2, CITY OF EL CERRITO, COUNTY OF CONTRA COSTA,
CALIFORNIA, WHICH MAP WAS FILED IN THE OFFICE OF THE
RECORDER OF THE COUNTY OF CONTRA COSTA, STATE OF
CALIFORNIA, ON JULY 24, 1953, IN VOLUME 51 OF MAPS, PAGE 30.

EXCEPTING THEREFROM THE MINERALS AND MINERAL RIGHTS
RESERVED IN THE DEED FROM RECONSTRUCTION FINANCE
CORPORATION TO NOBLE F. JUSTICE, ET UX., DATED OCTOBER
13, 1952, RECORDED NOVEMBER 26, 1952, IN BOOK 2032 OF
OFFICIAL RECORDS OF CONTRA COSTA COUNTY, PAGE 145.

THIS BEING THE SAME PROPERTY CONVEYED TO MARCELINO
MONTOYA AND SARA MONTOYA, HUSBAND AND WIFE AS JOINT
TENANTS, DATED 06/12/2018 AND RECORDED ON 06/19/2018 IN
INSTRUMENT NO. 2018-0097205-00, IN THE CONTRA COSTA
COUNTY RECORDERS OFFICE.

PARCEL NO. 502-153-010-9
```

**Generated Title md (`Title_Examination_Notes.md` lines 210-222):**

```
## Legal Description (Exhibit A)

The land is situated in the **City of El Cerrito, County of Contra Costa, State of California**, and is described as:

> **Lot 10**, as shown on the map of "**Justice Subdivision, Unit No. 2**, City of El Cerrito, County of Contra Costa, California", which Map was filed in the Office of the Recorder of Contra Costa County, California, on **July 24, 1953**, in **Book 51 of Maps, Page 30**.
>
> **EXCEPTING THEREFROM** the minerals and mineral rights reserved in the deed from Reconstruction Finance Corporation to Noble F. Justice, et ux., dated October 13, 1952, recorded November 26, 1952, in Book 2032 of Official Records of Contra Costa County, Page 145.

**APN:** 502-153-010

**Commonly known as:** 1724 Wesley Avenue, El Cerrito, CA 94530

*(Sources: Instrument 2018-0097205 Exhibit A; Instrument 2017-0034109 Exhibit A)*
```

**Delta:**
- Source `VOLUME 51 OF MAPS` → output `Book 51 of Maps` (synonym substitution).
- Source `Office of the Recorder of the County of Contra Costa, State of California` → output `Office of the Recorder of Contra Costa County, California` (clause compression).
- Source `UNIT NO. 2` → output `Unit No. 2` (case change + bold added).
- Source has a `THIS BEING THE SAME PROPERTY CONVEYED TO …` conveyance recital → **omitted entirely** from output.
- Source has `PARCEL NO. 502-153-010-9` → output drops the trailing `-9` check digit (`502-153-010`).
- Output adds `**bold**` markdown that does not exist in the source.
- Output adds an editorial prose lead-in ("The land is situated in...") that is not in Exhibit A — Exhibit A itself reads "THE LAND REFERRED TO IS SITUATED…".

**Why the LLM had access to the verbatim text but still paraphrased:** The saved `_workflow_prompts/raw_user_prompt.md` (line 1938-1956) **does** contain the full verbatim Exhibit A from the related 2018 Grant Deed (instrument 2018-0097205). The Step1 LLM saw it and chose to paraphrase. Step2 (title) gets no access to source PDFs (only the already-paraphrased RAW markdown — see `pipeline.py:_build_title_user_prompt` lines 1507-1546), so it cannot recover.

**Note on Document Excerpt Clipping (`pipeline.py:247` → `max_document_chars: int = 6000`):** For the MONTOYA DOT specifically (`B49178046_extracted.md`, 38,203 chars), `EXHIBIT A` is at char-offset **37,067** — well past the 6,000-char clip. The DOT's own Exhibit A is therefore **never sent to the LLM**. The 2018 Grant Deed companion document happened to be short enough that its Exhibit A appeared in-prompt, and that is the only reason the legal description appears at all in this case. **If only the DOT had been downloaded, the report would have had no legal description source whatsoever.**

### WALTERS — `B49178647_extracted.md` (Substitution DOT containing Exhibit A) vs `Title_Examination_Notes.md`

**Source (`B49178647_extracted.md:115-137`):**

```
EXHIBIT A

The land referred to is situated in the unincorporated area of the County of Contra Costa, State
of California, and is described as follows:

Lot 28 as shown on the Map of Subdivision 7679, filed September 14, 1994 in Map Book 375,
Page 35, Contra Costa County Records.

Excepting therefrom all oil, oil rights, minerals, mineral rights, natural gas rights, and other
hydrocarbons by whatsoever name known, geothermal steam and other geothermal resources
defined in California Public Resources code Section 6903, et seq., that may be within or under
the Parcels of Land hereinabove described, together with the perpetual right of drilling, mining,
exploring and operating therefore, and storing in and removing same from said land or any
other land, including the right to Whipstock or Directionally drill and mine from lands other
than those hereinabove described, oil, or gas wells, tunnels and shafts into, through across or
across the subsurface of the land hereinabove described, and to bottom such whipstocked or
directionally drilled wells, tunnels and shafts under the beneath or beyond the exterior limits
thereof, and to re-drill, re-tunnel, equip, maintain, repair, deepen and operate nay such wells or
mines without, however, the right to drill, mine, store, explore and operate through the surface
or the upper 500 feet of the subsurface of said land, as reserved in deed recorded December 8,
1993, Book 19243, Page 701, under Recorder's Serial Number 93 349591, Official Records.

APN: 011-291-028-6
```

**Generated Title md (`Title_Examination_Notes.md` lines 227-229):**

```
## LEGAL DESCRIPTION (EXHIBIT A)

> Lot 28 as shown on the Map of Subdivision 7679, filed September 14, 1994 in Map Book 375, Page 35, Contra Costa County Records.
```

**Delta:** The output prints ONLY the first granting clause. The entire ~15-line oil/gas/mineral/geothermal reservation paragraph is silently dropped, as is the `APN: 011-291-028-6` line at the foot of Exhibit A (APN is shown elsewhere in the report but not as part of the Exhibit A reproduction). The mineral reservation IS title-relevant — it carves out subsurface ownership — and a title underwriter relying on the report would not see it without going back to the source PDF.

### AMAYA — `B49205561.pdf` (DOT, instrument 2026-0042902) vs `Title_Examination_Notes.md`

**Source (`B49205561_extracted.md:90-96`):**

```
THE FOLLOWING DESCRIBED REAL PROPERTY IN CITY OF FRESNO, FRESNO COUNTY, STATE OF CALIFORNIA,
DESCRIBED AS: LOT 56 OF TRACT NO. 1440, OLIVE TERRACE, IN THE CITY OF FRESNO, COUNTY OF
FRESNO, STATE OF CALIFORNIA, ACCORDING TO THE MAP RECORDED IN BOOK 17, PAGE 57 OF PLATS
IN THE OFFICE OF THE COUNTY RECORDER OF SAID COUNTY. THIS BEING THE SAME PROPERTY
CONVEYED TO JANINE AMAYA AND CRISTIAN AMAYA, WIFE AND HUSBAND, AS JOINT TENANTS,
DATED 10/17/2019 AND RECORDED ON 11/20/2019 IN INSTRUMENT NO. 2019-0140496,
IN THE FRESNO COUNTY RECORDERS OFFICE. PARCEL NO. 455-113-24
```

**Generated Title md (`Title_Examination_Notes.md` lines 203-207):**

```
## LEGAL DESCRIPTION (EXHIBIT A)

> Lot 56 of Tract No. 1440, **Olive Terrace**, in the City of Fresno, County of Fresno, State of California, according to the Map recorded in **Book 17, Page 57 of Plats** in the Office of the County Recorder of said County.
>
> **APN: 455-113-24**
```

**Delta:** ALL-CAPS lowered, bold added, the entire `THIS BEING THE SAME PROPERTY CONVEYED TO …` conveyance recital deleted. The recital is legally meaningful — it identifies the prior conveyance that gives the borrower notice of color of title.

### Cross-defect scope summary

| Case | DOT examined | Defect 1 (paraphrase) | Defect 2 (ordering / Addendum A absent) | RAW also affected |
|---|---|---|---|---|
| MONTOYA | B49178046.pdf | YES (severe — entire conveyance recital dropped, OCR "corrected", synonym substitution) | YES | YES (RAW `### D. Legal Description` is the same paraphrase — see `RAW_TWO_OWNER_SEARCH_EXAM.md:80-90` and the structured `legal_description` string at line 302) |
| WALTERS | B49178647.pdf | YES (severe — ~15-line mineral/geothermal reservation dropped) | YES | YES |
| AMAYA | B49205561.pdf | YES (conveyance recital dropped, ALL-CAPS lost) | YES | YES |

**The defect is 100% universal in the sampled set, affects BOTH Title and RAW reports, and is independent of county/state.** Orange_Quintana also has `## LEGAL DESCRIPTION (EXHIBIT A)` at line 199 of its Title md, presumed same pattern.

---

## Root cause findings (ranked by likelihood)

### Cause 1 (PRIMARY, accounts for ~70% of severity) — Prompt does not enforce "verbatim" + no verbatim source is structurally surfaced
The Step1 system prompt (`/Users/ag/Downloads/0414_CA_Exams/TitleExam_SystemPrompt_Step1.md`) mentions "Legal descriptions (Exhibit A)" at line 45 and "Full legal description" at line 68 — but **never says "verbatim," "literal," "copy character-for-character," or anything equivalent.** The Step1 RAW user prompt builder (`pipeline.py:_build_raw_user_prompt`, lines 1383-1505) likewise never instructs verbatim copying. The MANDATORY OUTPUT CONTRACT block (lines 1455-1486) only constrains H2 headers; it says nothing about the textual content of the legal description.

The Step2 prompt (`AbstractorNotes_Step2.md` line 40) DOES say "The full verbatim legal description" — but (a) the word "verbatim" is buried in a 12-item section-order list, (b) Step2 has zero access to the source PDFs or `*_extracted.md` files (see `_build_title_user_prompt` at `pipeline.py:1507-1546` — it concatenates ONLY the RAW markdown), so even if it tried to be verbatim it couldn't be more verbatim than the already-paraphrased RAW it consumes.

### Cause 2 (SECONDARY, but a hard-block in some cases) — `max_document_chars = 6000` clips Exhibit A out of the prompt for many DOTs
`pipeline.py:247` defaults to clipping each `*_extracted.md` to its **first 6,000 characters**. Empirical char-offsets of `EXHIBIT A` in observed extracts:

| File | total_chars | first `EXHIBIT A` / `LOT ` offset | In-prompt? |
|---|---|---|---|
| `B49178046_extracted.md` (MONTOYA DOT) | 38,203 | 37,067 | **NO — clipped out** |
| `B49205561_extracted.md` (AMAYA DOT) | 36,671 | 3,453 (`LOT 56...`) | YES |
| `B49205589_extracted.md` (AMAYA Grant Deed) | 2,661 | 1,175 (`Lot 56...`) | YES |
| `B49178647_extracted.md` (WALTERS Substitution) | 4,787 | 3,181 | YES |
| `B49178641_extracted.md` (WALTERS Loan Mod) | 80,478 | 78,906 (`LOT 28...`) | **NO — clipped out** |
| `B49178638_extracted.md` (WALTERS Modification) | 87,159 | 85,586 (`LOT 28...`) | **NO — clipped out** |

For long DOTs (typical recorded loan documents are 30-90 pages with many boilerplate riders before Exhibit A), 6,000 chars is wholly insufficient — Exhibit A typically appears in the last 10-20% of the file. The pipeline survives today only because at least ONE document per case happens to be short enough to surface a legal description. MONTOYA is the borderline case: only the companion Grant Deed surfaced an Exhibit A; the actual DOT's was lost.

### Cause 3 — No post-generation validator compares output to source
`pipeline.py:_validate_markdown_content` (lines 1589-1598) only checks for the presence of required H2 headers. There is no semantic / content validator. A working helper exists at `verification/pdf_analyzer.py:39-50` (`extract_legal_description`) and a comparison helper at `verification/property_verifier.py:913-1029` (`compare_legal_descriptions`) — **but neither is wired into the automation pipeline.** They are dead code w.r.t. report generation.

### Cause 4 — No structured `legal_description_verbatim` field anywhere in the schemas
`documents_found.json` per-doc keys (`document_number`, `grantors`, `grantees`, `grantor_grantees`, `document_type`, `recording_date`, `pages`, `found_via_names`, `found_via_party_types`, `search_hits`) carry NO legal description field. `document_metadata.json` per-doc keys (`filename`, `year`, `downloaded_at`, `all_files`, `note`, `document_type`, `found_via_names`, `is_party_specific`) likewise carry none. `extracted_documents.json/documents[]` only carries (`document_number`, `filename`, `extracted_markdown`, `total_chars`, `ocr_used`). The legal description is implicit in the (clipped) extracted markdown only.

### Cause 5 — Section-ordering enforcement is at H2-level only; no sub-section / paragraph order enforced
`TITLE_REQUIRED_SECTIONS` (`pipeline.py:48-54`) mandates 5 H2 headers and nothing else. `RAW_REQUIRED_SECTIONS` (lines 40-46) mandates 5 phase headers and nothing else. Neither enforces the canonical Deed → Addendum A → Legal Description → APN/PIN ordering. The actual placement of the Legal Description block at the END of the Title md (after `## DOCUMENTS EXAMINED`) is driven by `AbstractorNotes_Step2.md` line 40 listing it as item #10 of an 11-item section order, with no code-side check.

---

## Gaps (each tied to a specific file/line)

- **`src/titlepro/automation/pipeline.py:247`** — `max_document_chars: int = 6000`. Truncates every `*_extracted.md` to its first 6,000 characters before sending to the LLM. Exhibit A in long DOTs is consistently past this offset. Either remove the cap, raise it dramatically (≥80k), or — preferred — emit a deterministically-extracted `legal_description_verbatim` block per document independent of the clip.
- **`src/titlepro/automation/pipeline.py:1548-1570`** — `_build_document_excerpt_block` performs a blind prefix clip (`text[: self.config.max_document_chars]`). No tail-preserving, no anchor-aware extraction (i.e. it does not seek `EXHIBIT A`, `LEGAL DESCRIPTION`, `described as:` markers and ensure they survive).
- **`src/titlepro/automation/pipeline.py:1383-1505`** — `_build_raw_user_prompt` and the `output_contract` literal (lines 1455-1486) never say "verbatim," never say "copy character-for-character," never name the canonical ordering rule.
- **`src/titlepro/automation/pipeline.py:1507-1546`** — `_build_title_user_prompt` feeds Step2 ONLY the RAW markdown. Step2 cannot recover from upstream paraphrasing — it has no source PDFs, no extracted MDs, no per-doc `legal_description_verbatim` field.
- **`src/titlepro/automation/pipeline.py:1513-1535`** — `title_contract` mentions `## LEGAL DESCRIPTION` only as an "extra" optional section (not required, not verbatim-mandated, not anchored to a position).
- **`src/titlepro/automation/pipeline.py:48-54`** — `TITLE_REQUIRED_SECTIONS` does not include `## LEGAL DESCRIPTION (EXHIBIT A)`. (Hence it is technically optional today.)
- **`src/titlepro/automation/pipeline.py:40-46`** — `RAW_REQUIRED_SECTIONS` does not require a verbatim legal-description sub-block.
- **`src/titlepro/automation/pipeline.py:1589-1598`** — `_validate_markdown_content` is a header-presence check only; no content / similarity validation.
- **`src/titlepro/verification/pdf_analyzer.py:39-50`** — `extract_legal_description()` exists but is dead code in the automation context. The regex is also too narrow (only `LEGAL DESCRIPTION` anchor + `described as:` fallback; does not anchor on `EXHIBIT A`, `Lot \d+`, `As per Map`, `THE LAND REFERRED TO`, or `THE FOLLOWING DESCRIBED REAL PROPERTY`).
- **`/Users/ag/Downloads/0414_CA_Exams/TitleExam_SystemPrompt_Step1.md:45,68`** — Step1 prompt mentions "Legal descriptions" without "verbatim". Step1 produces the RAW, which Step2 consumes; if Step1 paraphrases, the chain is corrupt.
- **`/Users/ag/Downloads/0414_CA_Exams/AbstractorNotes_Step2.md:40`** — Step2 says "full verbatim legal description" but buries it as item #10 in an 11-item ordering list; no anti-paraphrase / no anti-formatting-injection rule.
- **`documents_found.json` per-doc schema** — no `legal_description_verbatim`, no `addendum_a_present`, no `parcel_number_from_exhibit_a` fields.
- **`document_metadata.json` per-doc schema** — same gaps.
- **`extracted_documents.json/documents[]`** — same gaps.

---

## Recommended fixes (phased)

### Phase 1 — Immediate (lowest risk, blocks new occurrences)

**1.1 Strengthen Step1 user-prompt language (`pipeline.py:_build_raw_user_prompt`, append to `output_contract`).** Inject a hard verbatim directive:

```
ADDITIONAL HARD RULES — LEGAL DESCRIPTIONS

a. The legal description for the subject property MUST be reproduced
   verbatim, character-for-character, from the source instrument. This
   includes ALL-CAPS where the source uses ALL-CAPS, comma-vs-period
   exactly as in the source, "VOLUME" vs "BOOK" exactly as in the source,
   "THIS BEING THE SAME PROPERTY CONVEYED TO …" conveyance recitals if
   present, and the full "EXCEPTING THEREFROM …" reservation paragraph.
b. You MUST NOT add Markdown emphasis (**bold**, *italic*) to legal
   description text. You MUST NOT silently correct OCR artifacts in legal
   description text. You MUST NOT compress, paraphrase, or re-typeset
   legal description text.
c. If the source document presents the legal description as an attached
   Exhibit A or Addendum A, reproduce the Exhibit/Addendum label and its
   header text verbatim.
d. After the verbatim block, append (on its own line) the APN/PIN/Parcel
   Number exactly as it appears in the source. If the source shows
   "PARCEL NO. 502-153-010-9" (with check digit), reproduce that form.
e. Source-anchoring: every legal description MUST cite the specific
   source instrument (e.g. "Source: Instrument 2018-0097205, Exhibit A,
   page N"). If multiple source instruments contain Exhibit A's, prefer
   the most recent vesting Deed.
f. Canonical ordering within the property-identification block, applied
   in BOTH the RAW (Phase 3 §D) and Title (Property & Ownership /
   Subject Owner) sections, in this exact order:
     (i)   Most recent vesting Deed reference (instrument no., rec.
           date, grantor → grantee)
     (ii)  Addendum A (if present in the source — reproduce verbatim;
           if absent, write "Addendum A: Not present in source.")
     (iii) Legal Description (Exhibit A) — verbatim block per (a)
     (iv)  APN / PIN / Parcel Number — verbatim per (d)
```

**1.2 Mirror the same hard rules into Step2 `title_contract` (`pipeline.py:_build_title_user_prompt`).** Add: "If the RAW legal description appears paraphrased (mixed case where the source is ALL-CAPS, missing 'EXCEPTING THEREFROM' paragraph, missing 'THIS BEING THE SAME PROPERTY CONVEYED TO …' recital), flag with `[LEGAL DESCRIPTION PARAPHRASE DETECTED — re-extraction required]` and do NOT propagate the paraphrase forward."

**1.3 Add `## LEGAL DESCRIPTION (EXHIBIT A)` to `TITLE_REQUIRED_SECTIONS`** (`pipeline.py:48-54`) so the header-presence validator at least requires the section to exist. Lock the spelling to ALL-CAPS to fix the MONTOYA vs WALTERS capitalization drift.

**1.4 Update external prompts.** In `TitleExam_SystemPrompt_Step1.md` lines 38-46 and 63-73, replace "Legal descriptions (Exhibit A)" / "Full legal description" with "**Verbatim legal description (Exhibit A)** — reproduce character-for-character; do not paraphrase, re-typeset, or add Markdown emphasis." Hoist the "full verbatim" phrase from `AbstractorNotes_Step2.md:40` to the very top of the Section Order list, and add the canonical 4-item ordering rule as a stand-alone Rule.

Risk: **LOW.** All changes are additive text in prompts and one new required header. No behavior change to extraction, downloads, or rendering.

### Phase 2 — Structural (introduces the verbatim field + deterministic extractor)

**2.1 Add `extract_legal_descriptions` sub-phase to the pipeline** (between the existing `extract_text` phase and `generate_raw`). Implementation outline (read-only context — proposing the algorithm, not writing code):

- Per-document, given `*_extracted.md`:
  1. **Anchor search** (in priority order, case-insensitive):
     - `EXHIBIT A` (then take the paragraph block until the next `## Page` header, page-break, or all-blank line).
     - `LEGAL DESCRIPTION` (same trailing rule).
     - `THE LAND REFERRED TO IS`/`THE LAND REFERRED TO HEREIN IS` … through the next double-newline.
     - `THE FOLLOWING DESCRIBED REAL PROPERTY` … through the next double-newline.
     - `described as[: follows:]?` (fallback; capture the next 30-1500 chars).
  2. Capture **everything** from the anchor through the next strong terminator: `Page \d+ of \d+`, a notary boilerplate marker (`A notary public or other officer completing this certificate`), or a blank-line-followed-by-ALLCAPS-section.
  3. Within the captured block, separately tag: `[granting_clause]`, `[excepting_therefrom]` (if present), `[same_property_recital]` (if present), `[parcel_number]` (regex: `(?:PARCEL|APN|PIN)\s*(?:NO\.?)?\s*[:\-]?\s*([\d\-]+)`).
- **Use PyMuPDF's native text layer first**; only fall back to OCR when `page.get_text("text").strip()` is empty AND `pytesseract` is available (already the case — `pipeline.py:1606-1622`). Note that for image-only DOTs like MONTOYA's `B49178046.pdf`, the text layer is empty across all 11 pages so OCR is the only path; the OCR has captured Exhibit A correctly today (lines 667-694 of the extracted MD) — the problem is the 6,000-char downstream clip, not OCR.
- **Last-page-bias heuristic:** if no anchor is found in pages 1..N-2, additionally scan the last 3 pages with a relaxed `(?:LOT\s+\d+|PARCEL\s+\d+|TRACT\s+\d+)` regex.

**2.2 Write the extracted block to a new sidecar `legal_descriptions.json`** with shape:

```json
{
  "<document_number>": {
    "filename": "B49178046.pdf",
    "found": true,
    "anchor_used": "EXHIBIT A",
    "page_number": 11,
    "verbatim_text": "EXHIBIT A\n\nTHE LAND REFERRED TO IS …",
    "parcel_number": "502-153-010-9",
    "same_property_recital_present": true,
    "excepting_therefrom_present": true,
    "addendum_a_present": false,
    "extraction_method": "ocr"
  }
}
```

**2.3 Inject the per-document `verbatim_text` into the RAW user prompt** as its own clearly-labeled block (`pipeline.py:_build_document_excerpt_block`):

```
### Document N (Instrument X)
- legal_description_verbatim (from EXHIBIT A, page 11, OCR):
  ```
  EXHIBIT A
  THE LAND REFERRED TO IS SITUATED IN …
  PARCEL NO. 502-153-010-9
  ```
- excerpt (first 6,000 chars of extracted text):
  [existing clip continues here]
```

This guarantees the verbatim text is in-prompt regardless of where in the PDF it lives, decoupling correctness from `max_document_chars`.

**2.4 ALSO inject `legal_descriptions.json` into the Step2 (Title) user prompt** so the Title generator can sanity-check the RAW against the deterministic extraction even though it doesn't have the raw extracted MDs.

**2.5 Validation hook** — new function `_validate_legal_description_verbatim(report_md, legal_descriptions_json)`:
- Locate the `## LEGAL DESCRIPTION (EXHIBIT A)` section in the report.
- Compute similarity between the report's quoted block and `legal_descriptions[<most_recent_vesting_deed_instrument>].verbatim_text` after:
  - Lowercasing.
  - Stripping all Markdown emphasis (`**`, `*`, `_`).
  - Collapsing whitespace.
  - Normalizing common OCR noise (`Vondran`↔`vondran`; treat `,` interchangeably with `.` adjacent to `No`).
- Algorithm: **token-set Jaccard ≥ 0.95** OR `difflib.SequenceMatcher.ratio() ≥ 0.92` on normalized text. Anything below → fail validation.
- Additionally, require token-substring presence of: `EXCEPTING THEREFROM` (if `excepting_therefrom_present`), `SAME PROPERTY CONVEYED` or `BEING THE SAME` (if `same_property_recital_present`), and the parcel number string.

Risk: **MEDIUM.** Adds a new pipeline phase, a new sidecar artifact, a new validator. No effect on already-generated reports.

### Phase 3 — Order enforcement

**3.1 Add an ordering directive to the Step1 RAW `output_contract`** (`pipeline.py:_build_raw_user_prompt` around line 1455-1486):

```
ORDERING RULE — PROPERTY IDENTIFICATION (PHASE 3 §A–D)

Within PHASE 3, the property-identification sub-sections MUST appear
in this exact order:
  A. Property Information (address, county, TRA)
  B. Most recent vesting Deed (instrument, recording date, grantor →
     grantee, vesting type)
  C. Addendum A (if present — verbatim; if absent, write the literal
     line "Addendum A: Not present in source.")
  D. Legal Description (Exhibit A) — verbatim block per the rules above
  E. APN / PIN / Parcel Number — verbatim per the rules above

The Title (Step 2) report MUST then mirror this exact ordering inside
its "Subject Owner and Property Examined" header table and its
"LEGAL DESCRIPTION (EXHIBIT A)" section.
```

**3.2 Add a deterministic post-generation re-orderer** (new helper in `automation/renderers.py` or a new `automation/ordering.py`). After the LLM writes its Title md, parse the property-identification sub-block (between the H1 and the first H2 thereafter), extract its labeled bullets, and re-emit them in canonical order. This is a string-level rewrite — safe, deterministic, no semantic risk.

**3.3 Promote `## LEGAL DESCRIPTION (EXHIBIT A)` to `TITLE_REQUIRED_SECTIONS`** (already proposed in Phase 1.3). Additionally, validate that it appears IMMEDIATELY before `## DISCLAIMER` (or wherever the canonical position is defined) — fail-fast otherwise.

**3.4 Make the Addendum A line a required token** in the validator. If `legal_descriptions.json` reports `addendum_a_present: false` for the controlling Deed, the report must literally contain "Addendum A: Not present in source." (or equivalent). If true, the verbatim Addendum A text must appear.

Risk: **MEDIUM.** Phase 3.2 is the only behavioral change; everything else is additive validation.

---

## Test plan

### T1 — Re-run MONTOYA after Phase 1 prompt fixes only
- Expectation: Step1 RAW Phase 3 §D contains verbatim Exhibit A from instrument 2018-0097205 (the Grant Deed currently surfaced in-prompt at raw_user_prompt.md:1938-1956). Should match source `LOT 10, AS SHOWN ON THE MAP OF...VOLUME 51 OF MAPS, PAGE 30...EXCEPTING THEREFROM...PARCEL NO. 502-153-010-9` modulo whitespace.
- Step2 Title md `## LEGAL DESCRIPTION (EXHIBIT A)` section should mirror it character-for-character (with ALL-CAPS, no bold).
- **Pass criterion:** token-set Jaccard between Title md legal description and source extracted-MD Exhibit A ≥ 0.95.

### T2 — Re-run MONTOYA after Phase 2 (verbatim sidecar + targeted injection)
- Expectation: even if Step1 still tried to paraphrase, the validator at `_validate_legal_description_verbatim` should fail-and-retry the LLM call with a stronger directive.
- Pass criterion: `legal_descriptions.json` written; verbatim text matches the actual DOT `B49178046_extracted.md` lines 667-694 (not just the companion Grant Deed); validator passes ≥ 0.95.

### T3 — Re-run WALTERS after Phase 2
- Pass criterion: the ~15-line oil/gas/mineral/geothermal reservation paragraph from `B49178647_extracted.md` lines 123-135 is present verbatim in the Title md.

### T4 — Re-run AMAYA after Phase 2
- Pass criterion: the "THIS BEING THE SAME PROPERTY CONVEYED TO JANINE AMAYA AND CRISTIAN AMAYA …" recital from `B49205561_extracted.md:93-96` is present verbatim. `PARCEL NO. 455-113-24` appears in ALL-CAPS exactly once at the foot of the Exhibit A block (not separately bolded).

### T5 — Ordering check across all three cases
- Pass criterion: in each Title md, the sub-bullets within the property-identification table appear in this exact order: (1) Vesting Deed instrument, (2) Addendum A status line, (3) Legal Description (or pointer with `(see § LEGAL DESCRIPTION (EXHIBIT A))`), (4) APN. The H2 `## LEGAL DESCRIPTION (EXHIBIT A)` appears at the canonical position (e.g. immediately before `## DISCLAIMER`).

### T6 — Regression: empty / missing Exhibit A
- Synthetic test: a DOT whose extracted MD has no anchor. Pipeline should write `legal_descriptions[<instrument>].found = false` and the report should print "Legal Description: NOT EXTRACTABLE FROM SOURCE — manual verification required" instead of fabricating one.

### T7 — Regression: existing 3 reports re-rendered with Phase 1+2+3
- Compare new outputs against the current `Title_Examination_Notes_*_20260517_*.md` baseline. Differences should be confined to (a) the Legal Description block (now verbatim), (b) the property-identification sub-bullet ordering, and (c) the `Addendum A: Not present in source.` line. No other section should drift.

---

## Risks / non-goals

- **OCR noise propagation:** Verbatim reproduction will faithfully reproduce OCR artifacts (e.g. `"Unit No, 2"` for `"Unit No. 2"`, `"Noble F, Justice"` for `"Noble F. Justice"`). This is intended — a title underwriter relying on the report must see what the OCR saw so they know whether to pull the source. A future enhancement could flag a `[sic — OCR; verify against source]` annotation but that is **out of scope** for this audit.
- **Multiple Exhibit A's per case:** When the case dir contains several DOTs / Grant Deeds, each with its own Exhibit A, the Title md should cite the controlling vesting Deed only. Phase 2's `most_recent_vesting_deed_instrument` selection logic is a small modeling choice (probably: latest recording date among documents classified as `document_type == "DEED"` and `grantee` matches subject owner). Out of scope for this audit beyond noting the requirement.
- **Addendum A semantics:** "Addendum A" is not a universally-defined recording-jurisdiction term — some counties use it (e.g. Riverside HOA addenda); most use only "Exhibit A". The audit recommends keeping the slot in the canonical ordering and rendering "Addendum A: Not present in source." when absent, rather than dropping the slot.
- **No change to county-recorder / tax-portal flows.** This audit is scoped to legal-description fidelity and ordering. No recommendation touches the search, download, OCR engine choice, tax lookup, or rendering pipelines.
- **No code modifications were made.** All findings are based on read-only inspection of `pipeline.py`, the external prompts, the generated case-dir files, the source PDFs (via PyMuPDF) and the existing extracted markdowns.

---

## Unexpected findings

1. **Dead verification code:** `src/titlepro/verification/pdf_analyzer.py:39-50` and `src/titlepro/verification/property_verifier.py:847-1029` already contain `extract_legal_description()`, `extract_apn_from_legal_description()`, and `compare_legal_descriptions()` (the last includes a fairly thorough similarity / key-element analysis). The automation pipeline never imports or calls any of them. Phase 2's new sub-phase could either resurrect these helpers (after broadening the anchor regex) or supersede them.
2. **MONTOYA's Exhibit A was technically OCR'd correctly** — the bytes are in `B49178046_extracted.md:667-694`. The defect is **purely downstream** for this case (paraphrase by Step1 LLM + 6,000-char clip blocking the DOT's own Exhibit A). This is a strong signal that the OCR pipeline is healthy and the fix is in prompt + structured-injection, not in extraction.
3. **The MONTOYA Title md silently dropped the parcel-number check digit:** source `PARCEL NO. 502-153-010-9` → report `APN 502-153-010`. The trailing `-9` is the Contra Costa check digit and is part of the canonical APN. Other tooling that parses the report (e.g. a downstream tax lookup) may key on a 9-digit vs 10-digit string and miss matches.
4. **Heading casing drift** (`## Legal Description (Exhibit A)` vs `## LEGAL DESCRIPTION (EXHIBIT A)`) crosses runs of the same case — see MONTOYA `Title_Examination_Notes.md:210` vs `Title_Examination_Notes_ContraCosta_MONTOYA_Marcelino_20260514_150230.md:205`. Whichever run produces the all-caps form aligns with the WALTERS/AMAYA/QUINTANA convention; the mixed-case form is the outlier. Locking this in `TITLE_REQUIRED_SECTIONS` will eliminate the drift.
5. **The `_workflow_prompts/` sidecar files** (the actual prompts sent for each run) are gold for forensic comparison — they captured exactly what the LLM saw. This made root-cause diagnosis here much faster. Recommend keeping that artifact even after the fixes ship.
