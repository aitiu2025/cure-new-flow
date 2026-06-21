# FL Platform Examination Guide

> **Sources (in date order):**
> - `docs/FL/source/2026-05-20_Florida_Platform_Examination_Instructions.docx` — v1 from Tony Roveda (2026-05-20)
> - `docs/FL/source/2026-05-21_Florida_Platform_Examination_Instructions_v2.docx` — v2 from Tony Roveda (2026-05-21); adds Clericus body + Parcel-ID notes on all four prior platforms
>
> Structured guidance for human + automated examination of Florida county recorder portals, grouped by platform family. Use this as the reference whenever building or operating a FL recorder adapter.
>
> **Status note (updated 2026-05-21 from v2):**
> - **Landmark, Tyler, OnceCare, DueProcess** — covered; v2 adds explicit Parcel-ID search availability for each
> - **Clericus** — NOW COVERED (v2 filled in the section: effective date present, Cloudflare passive challenge, sortable columns, View-Image button, no PPN)
> - **VisualGov + PublicSoft** — STILL NOT COVERED in either v1 or v2. Tony's email called these "the big proprietary ones." Adapter build for VisualGov / PublicSoft must source guidance from live portals + sample subjects when Tony delivers them. **Recommended follow-up to Tony:** request VisualGov + PublicSoft sections in v3, plus the per-county Clericus list to scope inspection targets.
> - **Miami-Dade indexing review captured separately at `docs/FL/Miami_Dade_Indexing_Review.md` (2026-05-21).** First input for the Miami-Dade proprietary-platform adapter; complements (does not duplicate) the 5-platform sections below.

---

## Common terminology (applies across all platforms)

| Document type | "Grantor" role | "Grantee" role |
|---|---|---|
| Vesting Deed | Seller | Buyer |
| Judgment | Defendant / judgment debtor | Plaintiff / judgment creditor |
| Mortgage / Deed of Trust | **Mortgagor** (= borrower) | **Mortgagee** (= lender) |
| Lien | Lienor | Lienee |

Most FL portals display these as **Grantor/Grantee** regardless of doc type. Examiners should mentally map mortgages back to Mortgagor/Mortgagee when reading results.

**Name format across all 5 documented platforms:** `Last Name First Name` (no comma). Same convention used by our existing CA Tyler/RecorderWorks adapters.

---

## Platform 1 — Landmark

Covers ~16 FL counties (per Tony's earlier email): Lee (rank 8), Escambia (rank 21), plus smaller counties.

| Aspect | Behaviour |
|---|---|
| County Effective Date | **Displayed** on results page |
| Party Type filter | Set to `Both` |
| Name format | `Last First` |
| CAPTCHA | A few jurisdictions have **"I am not a robot"** checkbox; most have none |
| Output | Sortable columns; **Document type column is included** |
| Open image | Mouse-over + click any row → image opens |
| Download/print | Free; image is print-to-PDF capable |
| Short legal | Included in result row — **NOT usable as the canonical Exhibit A**; treat as preview only. Pull the full Exhibit A from the actual deed image. |
| Parcel ID search | **Enabled** (v2 confirmation) — usable as fallback when name search hits result cap |

**Adapter notes (when built):** RecorderWorks-style table parser. Single-step search form. Result table sortable, so column-index mapping is straightforward. Treat per-row legal as advisory only — Exhibit A extraction must come from the downloaded image. Adapter config should expose a Parcel-ID search mode alongside the name search.

---

## Platform 2 — Tyler Technologies

Covers 4 FL counties (per Tony): unknown specifically, but Tony confirmed Tyler exists in FL. We already have a working Tyler adapter for CA (Fresno, Riverside, SBD, etc.) — should be drop-in reusable.

| Aspect | Behaviour |
|---|---|
| Acknowledge step | **"I am not a robot" checkbox OR Agree-to-Disclaimer** (one or the other; varies by county) |
| Search modes | Two: **Basic Official Records Search** and **Advanced Official Records Search** |
| Recommended mode | **Basic** (Tony's recommendation) — Advanced adds Parcel-Number search but is not generally needed |
| County Effective Date | **Not displayed** |
| Party Type filter | `Search Either Party` |
| Name format | `Last First` |
| Open image | "View" link, right-justified with arrow icon |
| Parcel Number search | **Available in the Advanced search tab** (v2 confirmation) |

**Adapter notes:** Our existing CA `tyler_adapter.py` already handles the disclaimer + reCAPTCHA + name search. The 2Captcha integration shipped today (see `docs/CA_Implementation_Update_2005.md` for the in-repo applied form and `docs/implementation_references/2Captcha_reCAPTCHA_Integration.md` for the foundational design doc) makes reCAPTCHA-protected Tyler counties fully autonomous. **For FL Tyler counties, the existing adapter + `combined_name_search` config should work with minimal tuning** — primarily the `base_url` and `search_url` paths.

**Advanced search trade-off:** v2 confirms the Parcel-Number search lives in the Advanced tab. This would solve the common-name result-cap problem we hit in CA (FINKELSTEIN, ENCISO). If we know the parcel number for FL subjects we should add an "advanced" mode toggle in the adapter that routes to the Advanced tab when a parcel ID is supplied.

---

## Platform 3 — OnceCare

Coverage TBD — not in Tony's earlier email breakdown. Likely one of the 17 "Proprietary" counties.

| Aspect | Behaviour |
|---|---|
| County Effective Date | **Displayed** |
| Party Type filter | Use `All` |
| Name format | `Last First` |
| Variant dialogue | Dialogue box appears showing **name variances** (e.g. middle initial variants). **Tony recommends checking "Show All"** to capture every variant. |
| Output | Sortable columns; doc type included; short legal included |
| Open image | Click anywhere on the result row |
| Parcel ID search | **Enabled** (v2 confirmation) |

**Adapter notes (when built):** The variance dialogue is the unique step here. The adapter needs to:
1. Submit initial search
2. Detect the variance dialogue
3. Click "Show All" / select all variants
4. Then read the consolidated result set

This pattern is distinct from RecorderWorks/Tyler. Plan for a custom adapter or a Tyler subclass with an extra interaction step.

---

## Platform 4 — DueProcess

Covers 3 FL counties (per Tony): Seminole (rank 13) is confirmed via URL — `recording.seminoleclerk.org/DuProcessWebInquiry/`. Other 2 TBD.

| Aspect | Behaviour |
|---|---|
| County Effective Date | **Not displayed** — but results show each record marked **"verified"** |
| Search behaviour | Simple platform |
| Party Type filter | Use `All` |
| Parcel ID search | **Enabled** (v2 explicitly confirms — earlier "appears to be available / not tested" caveat now resolved) |
| Name format | `Last First` |
| Output | Sortable columns |
| Open image | Mouse-over + click; result includes all indexing data |

**Adapter notes (when built):** Simplest of the 5 platforms. Likely a single-form search with no disclaimer/CAPTCHA gate. The "verified" status field is useful — confirms the record has gone through quality review. Parcel ID search is now confirmed (v2) — wire it in as a first-class search mode rather than a fallback.

---

## Platform 5 — Clericus

Covers 23 FL counties (per Tony) — by far the largest single-platform group (smaller rural counties). **Section body added in v2 (2026-05-21).**

| Aspect | Behaviour |
|---|---|
| County Effective Date | **Provided** on results page |
| CAPTCHA | **No interactive challenge**, but runs an automated **Cloudflare "verifying if human" check** in the background |
| Name format | `Last First` (assumed — Tony did not call out a deviation; standing FL convention) |
| Output | **Sortable columns** |
| Open image | **"View Image" button** on each row |
| PPN / Parcel ID search | **No PPN functionality** — name search only |

**Adapter notes:** Cloudflare passive challenge means a vanilla `requests` session will likely be blocked — use a real browser (Playwright/Selenium) so the JS challenge token can be set. No CAPTCHA solver fee should be incurred because there is no interactive challenge; we just need to let the page settle until Cloudflare clears. Lack of Parcel-ID search means common-name jurisdictions (largest single platform group) will be the hardest to disambiguate — invest in a robust name-variant sweep + result-cap detection. The View-Image button is a stable selector to anchor on.

**Per-county URLs:** see `docs/FL/FL_Examples.md` for the 23 Clericus counties.

---

## Platforms NOT in this guide

Per Tony Roveda's email (2026-05-19): **17 of 67 FL counties use "Proprietary" platforms**, including:
- **VisualGov** — big one, top-tier counties
- **PublicSoft** — big one, top-tier counties

These have no examination guidance from Tony yet. **10 of the top-20 most-populous FL counties fall into the Proprietary bucket** — meaning the Clericus/Tyler/Landmark adapters won't cover them. Plan separate adapter builds for at least VisualGov + PublicSoft.

---

## Per-county deep-dives

Some proprietary / unusual counties have their own dedicated review docs that go beyond the platform-family generalisation above. Link them here as they are produced:

- **Miami-Dade** (proprietary; `onlineservices.miamidadeclerk.gov`) — `docs/FL/Miami_Dade_Indexing_Review.md` (Tony Roveda 2026-05-21). Covers: separate Last/First/Middle name fields, no effective date, two-click image flow, ~3-day image-availability lag. Adapter stub at `src/titlepro/search/recorder/counties/config/fl/miami_dade.json`.

---

## Cross-platform examination tips (Tony's standing advice)

These apply regardless of platform:

1. **Short legal in result row ≠ canonical Exhibit A.** Always pull the full Exhibit A from the downloaded image. (Same rule we follow for CA today.)
2. **`Last First` name format** is universal across documented platforms — same as our CA Tyler/RecorderWorks adapters.
3. **Party-Type filter defaults:**
   - Landmark → `Both`
   - Tyler → `Search Either Party`
   - OnceCare → `All`
   - DueProcess → `All`
   - Clericus → not called out by Tony (assume `All` / default; verify on first live run)
4. **County Effective Date** is shown on Landmark + OnceCare + **Clericus (v2)**. For Tyler/DueProcess we don't have a server-side date; use the download timestamp as a proxy.
5. **CAPTCHA / human-check matrix:**
   - Landmark → a few counties have "I am not a robot" checkbox
   - Tyler → "I am not a robot" checkbox OR Agree-to-Disclaimer (varies)
   - OnceCare → none documented
   - DueProcess → none documented
   - **Clericus → passive Cloudflare "verifying if human" challenge (no user-interactive CAPTCHA)** — needs a real browser session
   - `docs/CA_Implementation_Update_2005.md` describes our 2Captcha auto-solve flow for interactive reCAPTCHA; Cloudflare passive challenges are handled by letting Playwright settle, not by 2Captcha.
6. **Doc-type column** is present on Landmark + OnceCare. Tyler usually has it too. DueProcess shows "verified" instead. Clericus presents sortable columns (doc-type likely included — confirm on first live run).
7. **Parcel ID search availability (v2):**
   - Landmark → Enabled
   - Tyler → Available in Advanced tab
   - OnceCare → Enabled
   - DueProcess → Enabled
   - **Clericus → NOT available** (name search only) — biggest disambiguation risk

---

## When to update this doc

- ~~Tony delivers the **Clericus section** content → fill in Platform 5~~ **DONE 2026-05-21 via v2 docx**
- Tony delivers guidance for **VisualGov / PublicSoft / other proprietary** → add Platforms 6+ (still outstanding; recommended follow-up)
- After first **live test of any FL platform**, append a "Live observations" subsection capturing any deviations from this written guidance
- After building each platform adapter, link the adapter file in the relevant platform section

---

## Related FL docs

- `docs/FL/FL_Examples.md` — 67-county URL table + per-county CAPTCHA flags
- `docs/FL/FL_Implementation_Plan.md` — 5-platform build wave plan + open questions
- `docs/FL/Miami_Dade_Indexing_Review.md` — Tony Roveda 2026-05-21; per-county deep-dive for Miami-Dade proprietary platform
- `docs/FL/source/2026-05-20_Florida_Platform_Examination_Instructions.docx` — original v1 guidance from Tony
- `docs/FL/source/2026-05-21_Florida_Platform_Examination_Instructions_v2.docx` — v2 guidance from Tony (adds Clericus body + Parcel-ID notes)
- `docs/FL/source/2026-05-21_Single_Jurisdictional_Indexing_Platform_Review.docx` — Tony Roveda 2026-05-21; Miami-Dade indexing review source docx
- `docs/implementation_references/CURE_Exam_Methodology_Guide.md` — cross-cutting abstractor methodology (Tony Roveda 2026-05-21); Steps 1-3 + work-smart shortcuts that EVERY adapter (FL + CA + future) must operationalize
- `docs/County_URL_Mapping_CA_OH.md` — master URL list (CA/OH/FL)
- `docs/County_URL_Mapping_CUREMasterSheet.xlsx` — authoritative machine-readable form
