# Miami-Dade Indexing Review (and Hillsborough test-subject table)

**Source:** Tony Roveda — `docs/FL/source/2026-05-21_Single_Jurisdictional_Indexing_Platform_Review.docx` (2026-05-21)

**Imported to this repo:** 2026-05-21

**Status:** Miami-Dade is one of the FL proprietary platforms (`z-Proprietary` in the master sheet `docs/County_URL_Mapping_CUREMasterSheet.xlsx`). This review is the **FIRST input** for designing a Miami-Dade adapter (currently a stub at `src/titlepro/search/recorder/counties/config/fl/miami_dade.json`). The same source docx also contains a small Hillsborough section header + test-subject table — captured here for completeness, but Hillsborough's platform behaviour is already documented in `FL_Platform_Examination_Guide.md` (Landmark family).

> **Note on title typo in source:** The source docx labels the section **"Miami-Date"**. This is a typo for **Miami-Dade** (Florida) — the correct county name. We use Miami-Dade throughout this MD.

---

## Miami-Dade — Single Jurisdictional Indexing Review

### Effective Date

- **No Effective Date listed** on the platform.
- Implication: no server-side as-of date is exposed; downstream consumers (CURE pipeline / report builder) must rely on the **download timestamp** as the effective-date proxy, same approach we use for Tyler + DueProcess.

### Search form

- **Simple entry** (single-form search, no multi-step wizard).
- **Separate fields for Last, First, and Middle names.** This is distinct from the FL platform family standard (`Last First` in one combined field) — Miami-Dade requires the adapter to split the name string into three discrete fields.

### Result-set behaviour

- **Sort by Date available.** Sortable column at least for date; other sort options not called out.
- **Doc Type listed** in the result row.

### Detail / image access

- **Mouse over and click** the row to **open detailed index data**.
- A **separate hyperlink** labelled **"Document Image"** opens the image — i.e. the detail panel and the image are two distinct UI affordances, not a combined click.

### Indexing vs imaging lag

- During Tony's test: **indexing is up to date**, but **document images are behind by about 3 days.**
- Implication: an adapter run on a freshly recorded document may successfully read the index entry but **fail to retrieve the image** for up to ~3 days. The pipeline needs a "image-not-yet-available" retry / queue posture, not a hard failure, for very-recent records.

---

## Hillsborough (partial — section started in same docx)

The same docx also begins a Hillsborough section. It is brief, and the platform-level behaviour for Hillsborough is already fully documented in `FL_Platform_Examination_Guide.md` (Hillsborough runs on the Landmark family). The unique content here is:

### Hillsborough test-subject table

| Subject 1 — First party | Subject 1 — Second party | Subject 1 — Address | Subject 1 — City | (separator) | Subject 2 — First party | Subject 2 — Second party | Subject 2 — Address | Subject 2 — City |
|---|---|---|---|---|---|---|---|---|
| ALANA FROMER | MICHAEL FROMER | 4004 W NORTH B ST | TAMPA | | ANGEL DEL MONTE | CHRISTINE DEL MONTE | 13519 ESTSHIRE DR | TAMPA |

> Source table is a single-row, 9-column Word table (8 data cells + 1 empty separator cell). Rendered above with one column per cell to preserve fidelity. Two test subjects supplied: **FROMER** (Alana + Michael, 4004 W North B St, Tampa) and **DEL MONTE** (Angel + Christine, 13519 Estshire Dr, Tampa).

### Hillsborough search-form notes (from the same section)

- **Effective Date** presented right-justified in an "Important Messages" box.
- **Leave Person Type blank** (ignore the filter).
- Enter **Last name first name**. Click **Search**.

(For full Hillsborough platform behaviour see Landmark section in `FL_Platform_Examination_Guide.md`.)

---

## Adapter implications

Concrete adapter requirements derived from the Miami-Dade review — these are the building blocks for promoting `miami_dade.json` from `status: stub` to a working adapter:

- **Three-field name input:** The adapter form-fill step must split client-provided full names into **Last / First / Middle** (three discrete selectors) — NOT the single combined `Last First` string used by Tyler/Landmark/Clericus/OnceCare/DueProcess. Add a `name_input_mode: "split_lfm"` field to the JSON config and have the runner branch on it.
- **No Effective Date scraping:** Skip the effective-date extraction step. Stamp the download timestamp as the effective date in the report metadata layer, matching the Tyler/DueProcess pattern.
- **Two-click image flow:** Implement two distinct interaction selectors per result row — `detail_open_selector` (mouse-over + click on the row) and `image_open_selector` (the separate "Document Image" hyperlink). Don't assume one click reveals the image.
- **Doc Type column extraction:** Doc-type is exposed in the row — wire it into the standard `extract_results()` column map. This is the cheap-and-reliable signal for filtering deeds vs mortgages vs liens before pulling images.
- **Date-sort enforcement:** Use the platform's date sort to put newest-first (matches the chain-of-title rendering rule from `CURE_Exam_Methodology_Guide.md` — "Newest to Oldest").
- **3-day image-lag tolerance:** Add a per-county config field `image_availability_lag_days: 3` and have the download phase fall through to a "pending — retry after N days" status rather than hard-erroring when a recent document has no image yet. Surface this in the report so the examiner knows to circle back.
- **No CAPTCHA called out:** Tony's review does not mention a CAPTCHA / human-check step for Miami-Dade — consistent with the current `captcha_required: false` in the stub config. Verify on first live run; if a passive challenge appears, fall through to a real-browser Playwright session like Clericus.
- **No Parcel-ID search mentioned:** Tony's review describes only the name-search flow. Parcel-ID availability is unspecified — flag as an open question for the next round with Tony (see Follow-ups below).
- **Commercial-access alternative:** The existing stub note flags tiered Miami-Dade exam pricing ($1 ea / 5000 for $500) that may bypass CAPTCHA — worth a parallel cost-vs-build analysis before sinking deep into a custom scraper. Track separately from the adapter build itself.

---

## Follow-ups to Tony

- **Parcel-ID search:** Does Miami-Dade expose a parcel-number search? The review covers name-search flow only.
- **Party Type / Grantor-Grantee filter:** No mention of a party-type filter for Miami-Dade — is "Both" the default, or is there a dropdown to set?
- **Other proprietary platforms:** This docx covers only Miami-Dade + a Hillsborough stub. The remaining FL proprietary platforms (VisualGov, PublicSoft, others) still have no examination guidance — same outstanding ask as in `FL_Platform_Examination_Guide.md`.
- **Hillsborough completeness:** The Hillsborough section in this docx is truncated (ends mid-flow at "Last name first name. Click Search."). If there's a v2 with the remaining Hillsborough behaviour, please share.
- **Typo confirmation:** Confirm the "Miami-Date" header in the source docx was a typo for Miami-Dade.

---

## Related FL docs

- `docs/FL/FL_Platform_Examination_Guide.md` — platform-by-platform examination guide; Miami-Dade is **not** covered there (proprietary platform), but the Landmark / Tyler / Clericus / OnceCare / DueProcess sections give the analogous patterns this adapter will diverge from.
- `docs/FL/FL_Implementation_Plan.md` — 5-platform build wave plan. Miami-Dade sits in the Proprietary bucket; this review unblocks scoping for it.
- `docs/FL/FL_Examples.md` — 67-county URL table.
- `docs/implementation_references/CURE_Exam_Methodology_Guide.md` — cross-cutting abstractor methodology (Steps 1-3) that the Miami-Dade adapter must operationalize, just like every other adapter.
- `src/titlepro/search/recorder/counties/config/fl/miami_dade.json` — adapter stub. Promote `status: stub` → `status: in_progress` when adapter build begins; add the `name_input_mode`, `detail_open_selector`, `image_open_selector`, `image_availability_lag_days` fields described above.
