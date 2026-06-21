# Abstractor Notes/Chain

> **CURE TitlePro — Confidential Abstractor's Report**
> *Subject: 4837 Sabal Harbour Dr, Bradenton, FL 34203 (Manatee County) · Examiner: Claude (Local-DB Phase 1-3 + OCR Phase 4 Pipeline) · Examination Date: 2026-05-23*

## TITLE EXAMINATION SUMMARY

| Item | Value |
|---|---|
| **Common Address** | 4837 Sabal Harbour Dr, Bradenton, FL 34203 |
| **County** | Manatee County, Florida |
| **Parcel ID (APN)** | 1697719559 |
| **Subdivision / Legal** | LOT 141, SABAL HARBOUR, PHASE V |
| **Plat Reference** | Plat Book 35, Pages 56-62 (Public Records of Manatee County, Florida) |
| **Current Vested Owners** | Pablo Fernandez and Daniela Rozanes, husband and wife (joint with right of survivorship per F.S. §689.15) |
| **Vesting Source** | Warranty Deed, Instrument `201841020434`, recorded 2018-03-01, Book 2716 / Page 2565 |
| **Land Size** | 0.1752 Acres (7,632 sq ft) |
| **Improvements** | 2,381 sq ft under roof / 1,873 sq ft living area — 1-story masonry/stucco SFR, built 2000, 3/2/0 rooms |
| **2025 Just/Market Value** | $413,185 (MCPAO) |
| **2025 County Taxable** | $212,377 (Homestead Exemption: YES since 2019) |
| **Title Status** | MARKETABLE WITH CONDITIONS (see Critical Issues) |
| **Examination Scope** | Local-cache (manatee_cache.db) records 2007-01-02 through 2025-12-31; 23 union-set candidates discovered; 14 Group-A docs downloaded + OCR'd; 8 Group-B excluded as non-subject; 1 Group-C judgment image unavailable |

### Headline Findings
- ✅ Vesting deed (A2) is a **Warranty Deed** from immediate predecessors-in-interest (Reijo + Pirjo Toivanen) directly to current owners. NLP subject-address verification: **MATCH 1.00**.
- ✅ The 2018 purchase-money mortgage (Fairway/MERS, $258,400) is **RELEASED** of record by the 2020 satisfaction.
- ⚠️ Two open mortgages totaling **$332,332.66** in recorded principal: Suncoast HELOC (capped $217,332.66, senior in time) and SouthState Bank ($115,000, junior in time).
- ⚠️ One unresolved **floating-lien cloud**: 2021 Domestic Relations judgment indexed against "FERNANDEZ PABLO C" (middle initial unconfirmed; image sealed under FL Ch. 119 + AOSC restriction).
- ⚠️ Cache coverage starts 2007 — **pre-2007 chain** (2000 + 2002 conveyances) not examined; pull from live recorder before commitment.

## CHAIN OF TITLE

Listed newest → oldest. Rows with `(pre-cache)` annotation derive from MCPAO sales-history JSON and were NOT examined as part of this exam.

| # | Date | Instrument Type | Inst # / Book-Page | Grantor → Grantee | Consideration | Notes |
|---|---|---|---|---|---:|---|
| 1 | 2018-03-01 | Warranty Deed *(current vesting)* | `201841020434` / 2716-2565 | Reijo Toivanen & Pirjo Toivanen → Pablo Fernandez & Daniela Rozanes | $272,000 (impl. via $1,904 doc stamps) | NLP MATCH 1.00 — no subsequent deed-out; vesting clean since 2018-03-01 |
| 2 | 2002-10-31 | Warranty Deed *(pre-cache)* | — / 1781-4691 | (Cirrito or successor) → Reijo Toivanen | $187,000 | NOT IN CACHE — requires live-recorder pull |
| 3 | 2000-11-15 | Special Warranty Deed *(pre-cache)* | — / 1657-4044 | (Developer — likely Pulte Home Corp.) → Angela L. Cirrito | $149,000 | NOT IN CACHE — requires live-recorder pull |

**Status:** vesting chain integrity within cache window is complete and verified. Pre-cache portion is asserted-but-not-verified.

## LEGAL DESCRIPTION (EXHIBIT A)

Verbatim from the vesting deed (Instrument `201841020434`, recorded 2018-03-01 in Official Records Book 2716, Page 2565, Public Records of Manatee County, Florida):

> Lot 141, SABAL HARBOUR, PHASE V, according to the plat thereof, recorded in Plat Book 35, Page(s) 56 through 62, inclusive, of the Public Records of Manatee County, Florida.
>
> Parcel Identification Number: 1697719559

**Together with** all the tenements, hereditaments and appurtenances thereto belonging or in anywise appertaining. (Vesting deed grants in fee simple, with general warranty covenants, subject to covenants, restrictions, easements of record and taxes for the current and subsequent years.)

## DEEDS OF TRUST / MORTGAGES

Florida is a lien-theory state; the instruments here are **Mortgages** (not Deeds of Trust). All status assignments confirmed by `released_mortgage_linker` (`phase1_verifications.json`).

### OPEN Mortgages

#### M-1. Suncoast Credit Union HELOC — SENIOR (chronologically)
| Field | Value |
|---|---|
| Mortgage Instrument | `202041027843` (A7) |
| Recorded | 2020-03-13 |
| Mortgagee | Suncoast Credit Union (PO Box 11829, Tampa, FL 33680) |
| Mortgagor | Pablo Fernandez and Daniela Rozanes |
| Type | Home Equity Line of Credit (HELOC) |
| Original Principal (per OCR'd Note) | **$254,500.00** |
| Capped Principal (per LRFA, as of 2026-03-24) | **$217,332.66** |
| Modifications | Instrument `202641040261` (M-3 below) — Limitation of Right of Future Advances (NOT a subordination) |
| Status | **OPEN — NO SATISFACTION OF RECORD** |
| Priority | **1st (chronologically senior under F.S. §695.11)** |
| Subject-address NLP | MATCH 1.00 ✅ |

#### M-2. SouthState Bank Mortgage — JUNIOR (chronologically)
| Field | Value |
|---|---|
| Mortgage Instrument | `202641040260` (A12) |
| Recorded | 2026-04-09 |
| Mortgagee | SouthState Bank, N.A. (2811 Manatee Ave West, Bradenton, FL 34205) |
| Mortgagor | Pablo Fernandez and Daniela Rozanes |
| Original Principal | **$115,000.00** |
| Status | **OPEN — NO SATISFACTION OF RECORD** |
| Priority | **2nd (chronologically junior to M-1)** |
| Subject-address NLP | MATCH 1.00 ✅ |

#### M-3. Related — Limitation of Right of Future Advances on M-1 (NOT a subordination)
| Field | Value |
|---|---|
| Instrument | `202641040261` (A13) |
| Recorded | 2026-04-09 (same instrument-day as M-2) |
| Caption | "LIMITATION OF RIGHT OF FUTURE ADVANCES PURSUANT TO SECTION 697.04, FLORIDA STATUTES" |
| Executed By | Pablo Fernandez and Daniela Rozanes (mortgagors of M-1) |
| Effect | Caps the principal secured by M-1 at $217,332.66 outstanding as of 2026-03-24; future advances under the HELOC will NOT be secured by the existing mortgage |
| Beneficiary | Suncoast Credit Union (M-1 lender) and SouthState Bank (M-2 junior lender) |
| Important | An LRFA under F.S. 697.04 is **NOT** a subordination agreement. M-1 Suncoast HELOC remains chronologically senior to M-2 SouthState for the $217,332.66 capped principal. See Critical Issues §C-1. |

### RELEASED / SATISFIED Mortgages

#### M-R1. Fairway/MERS 2018 Purchase-Money Mortgage — RELEASED
| Field | Value |
|---|---|
| Mortgage Instrument | `201841020435` (A3) |
| Recorded | 2018-03-01, Book 2716 / Page 2566 (same instrument-day as vesting deed A2) |
| Mortgagee | MORTGAGE ELECTRONIC REGISTRATION SYSTEMS, INC. ("MERS"), as nominee for FAIRWAY INDEPENDENT MORTGAGE CORPORATION |
| Mortgagor | Pablo Fernandez and Daniela Rozanes |
| Original Principal (per OCR'd Note) | $258,400.00 |
| **Released By** | Instrument `202041043360` (A8) — "MORTGAGE RELEASE, SATISFACTION, AND DISCHARGE" recorded 2020-04-28 |
| Release Evidence | A8 explicitly cites "OR2716 PG2566" in its legal-description field; A8 OCR confirms MERS as nominee for Fairway Independent Mortgage Corporation |
| `released_mortgage_linker` Verdict | `status: "released"`, `release_chain: [202041043360]` ✅ |

## DOCUMENTS EXAMINED

Complete inventory of all 23 union-set candidates discovered during Phase 1-3 search, per Tony Directive #5 (no silent drops).

### Group A — Subject Parcel (14 documents — all downloaded + OCR'd)
| Inst # | Date | Doc Type | Pages | Role | NLP Address |
|---|---|---|---:|---|---|
| `201541003454395` | 2015-12-01 | NOC | 1 | Toivanen / Lee Overholt Construction (pre-vesting, statutory-expired) | NO_ADDRESS (handwritten; zip + city match) |
| `201841020434` | 2018-03-01 | WD | 1 | **Vesting deed** Toivanen → Fernandez/Rozanes | MATCH 1.00 ✅ |
| `201841020435` | 2018-03-01 | MORTGAGE | 20 | $258,400 Fairway/MERS — RELEASED (M-R1) | MATCH 1.00 ✅ |
| `202041027841` | 2020-03-13 | AFFIDAVIT | 1 | Refi-related affidavit (with M-1 origination) | MATCH 1.00 ✅ |
| `202041027842` | 2020-03-13 | TERMINATION | 2 | Terminates 2019 Dynasty NOC | MATCH 1.00 ✅ |
| `201941092835` | 2019-09-17 | NOC | 1 | Dynasty Building (misspelled "FERNADEZ" + wrong legal) — terminated 2020 | NO_ADDRESS (cross-ref) |
| `202041027843` | 2020-03-13 | MORTGAGE | 17 | $254,500 Suncoast HELOC — OPEN (M-1) | MATCH 1.00 ✅ |
| `202041043360` | 2020-04-28 | SATISFACTION | 1 | Releases A3 Fairway mortgage | NO_ADDRESS (cross-ref OR2716 PG2566) |
| `202541032476` | 2025-03-13 | NOC | 1 | Freedom Forever Solar (Pablo only) | NO_ADDRESS (APN 1697719559 in OCR) |
| `202541046441` | 2025-04-11 | UCC | 3 | Solar Mosaic fixture filing — terminated 2026 | NO_ADDRESS (direct "4837 Sabal Harbour Dr" + Lot 141 PHASE V in OCR) |
| `202641010612` | 2026-01-30 | AFFIDAVIT | 1 | Solar contractor affidavit | MATCH 1.00 ✅ |
| `202641040260` | 2026-04-09 | MORTGAGE | 10 | $115,000 SouthState — OPEN (M-2) | MATCH 1.00 ✅ |
| `202641040261` | 2026-04-09 | NOTICE (LRFA) | 3 | F.S. 697.04 limit on M-1 (M-3) | MATCH 1.00 ✅ |
| `202641050708` | 2026-05-04 | TERMINATION | 2 | Terminates A10 UCC | MATCH 1.00 ✅ |

### Group B — Different Parcels (8 documents — examined and excluded)
Cache `legal` field unambiguously identifies these as belonging to different subdivisions. NOT downloaded per user authorization 2026-05-23.

| Inst # | Date | Doc Type | Legal | Excluded Because |
|---|---|---|---|---|
| `201641013923` | 2016-06-30 | DEED | LOT 361 DEL TIERRA | Different subdivision — prior residence purchase |
| `201641013924` | 2016-06-30 | MORTGAGE | LOT 361 DEL TIERRA | Released by `201841023993` — not subject |
| `201841020245` | 2018-03-01 | DEED | LOT 361 DEL TIERRA | Sale of Del Tierra (same day as subject purchase) |
| `201841023993` | 2018-03-12 | SATISFACTION | OR2627 PG2203 | Releases the Del Tierra mortgage — not subject |
| `202141105577` | 2021-08-10 | DEED | LOT 5 BLK E TYLERS | Different subdivision — Tylers Acres investment |
| `202141105578` | 2021-08-10 | MORTGAGE | LOT 5 BLK E TYLERS | Released by `202341078556` — not subject |
| `202341078556` | 2023-07-21 | RELEASE | INST 202141105578 | Releases the Tylers mortgage — not subject |
| `202341080572` | 2023-07-27 | DEED | LOT 5 BLK E TYLERS | Sale of Tylers — not subject |

### Group C — Critical Cloud, Image Unavailable (1 document)
| Inst # | Date | Doc Type | Image | Notes |
|---|---|---|---|---|
| `202141142133` | 2021-10-26 | JUDGMENT (DR) | **NOT AVAILABLE** (`doc_id="N/A"`) | "FERNANDEZ PABLO C" → LOPEZ REINA, Case 2021 DR 001719 — see Critical Issues §C-2 |

## CRITICAL ISSUES

### C-1. Lien Position Discrepancy (HIGH)
The 2026 SouthState mortgage (M-2, $115,000) does NOT enjoy first-lien position on the recording-order timeline. M-1 Suncoast HELOC (recorded 2020-03-13) remains chronologically senior for $217,332.66 capped principal under FL §695.11. The same-day-as-M-2 instrument `202641040261` (M-3) is a Limitation of Right of Future Advances under F.S. 697.04 — **NOT** a subordination agreement.

**Action required:** verify with closing file whether (a) a separate subordination was executed but unrecorded, (b) SouthState insured as a 2nd, or (c) Suncoast was paid off but the satisfaction is delayed. **Title commitment should NOT recite SouthState as a first lien without a recorded subordination or a satisfied/released Suncoast HELOC.**

### C-2. Domestic Relations Judgment — Identity Unconfirmed (HIGH)
Instrument `202141142133` recorded 2021-10-26 in favor of Reina Lopez against "FERNANDEZ PABLO C" (Case 2021 DR 001719, 12th Judicial Circuit). The middle initial "C" is not confirmed for the subject Pablo Fernandez. Image is restricted under FL Ch. 119.0714 + Florida Supreme Court AOSC e-access rules; not retrievable via standard Clerk image endpoint.

Active family-court support judgments under F.S. 61.181 attach as floating liens against all real property owned by the judgment debtor in the county until satisfied. **No satisfaction or release of record.**

**Required at closing:** (a) retrieve certified copy of judgment in person at the Manatee County Clerk's office; (b) compare debtor identity (DOB / SSN / last known address) against subject Pablo Fernandez's identity documents; (c) if same individual → satisfaction of record required before close; (d) if different individual → same-name affidavit + title-insurance indemnity per ALTA standard.

### C-3. Pre-2007 Chain Gap (HIGH)
Local cache coverage begins 2007-01-02. Two prior conveyances (Cirrito 2000-11-15 and Toivanen 2002-10-31) are NOT examined by this exam, and any associated mortgages or satisfactions in that 2000-2007 era are likewise unexamined.

**Action required before closing:** pull the two pre-2007 deeds and any associated mortgage/satisfaction documents directly from the live Manatee County Clerk recorder portal (`https://records.manateeclerk.com/OfficialRecords/Search`). Confirm clean chain back to original developer and confirm all pre-2007 mortgages are satisfied of record.

### C-4. Indexing Errors on Cleared 2019 NOC (MEDIUM)
Instrument `201941092835` was indexed under misspelled grantor "FERNADEZ PABLO" (missing N) with wrong legal "LOT 09 BLK 35 SABAL HARBOUR" — appears to be a contractor (Dynasty Building Solutions) template error; 5 unrelated homeowners filed same legal same week via same contractor. NOC was terminated 2020-03-13 by instrument `202041027842` → no current lien impact.

**Recommend:** record a Scrivener's Affidavit at closing memorializing the dual indexing error so future exact-match name OR exact-match legal searches don't surface this as a phantom encumbrance.

### C-5. Wrong-Property Match Check — PASS
NO wrong-property deeds were identified in the chain. All 14 Group-A documents passed subject-property verification (9 via NLP MATCH 1.00; 5 via OCR cross-reference using APN, legal description, or referenced book/page). The SIMMONS gate (Tony Directive #4) is satisfied.

## SPOUSE-DELTA ANALYSIS (Tony Directive #3)

Per Tony's Broward review, alias discovery via spouse-delta is the key catch for one-spouse-only liens. Independent searches per spouse, then set-difference:

- **Daniela exclusive: 0 docs.** All of Daniela's 16 records are joint-filed with Pablo. Indicates clean joint titling — no separate-property docs under Daniela alone.
- **Pablo exclusive: 5 docs.**
  1. `202541032476` — 2025 Solar NOC (Freedom Forever) — Pablo only; subject confirmed via APN
  2. `202541046441` — 2025 Solar Mosaic UCC — Pablo only; terminated 2026
  3. `202641010612` — 2026 Solar Affidavit — joint contractor affidavit
  4. `202641050708` — 2026 Solar Mosaic UCC Termination — terminates #2
  5. **`202141142133` — 2021 DR Judgment under "FERNANDEZ PABLO C"** — identity verification required (see Critical Issues §C-2)

## TAX STATUS

**TAX STATUS NOT VERIFIED** — live Manatee tax-portal lookup was not executed in this run.

### Reference data (from local MCPAO parcel profile)
| Tax Year | Just/Market | County Taxable | Ad Valorem | Non-AV |
|---:|---:|---:|---:|---:|
| 2025 | $413,185 | $212,377 | $3,245.05 | $321.24 |
| 2024 | $418,684 | $205,684 | $3,155.75 | $298.83 |
| 2023 | $420,375 | $198,237 | $3,117.03 | $278.02 |
| 2022 | $364,917 | $191,007 | $3,035.17 | $260.54 |
| 2021 | $245,607 | $183,987 | $3,036.25 | $244.11 |
| 2020 | $230,756 | $180,756 | $3,009.98 | $231.10 |
| 2019 | $234,360 | $180,956 | $3,049.08 | $219.09 (HX starts) |
| 2018 | $223,612 | $223,612 | $3,594.68 | $207.19 (purchase year — no HX) |

Homestead Exemption: YES (since 2019 tax year).

**Pre-closing action:** verify current-year tax-paid status, confirm no delinquent tax certificates or tax-deed proceedings of record, via Manatee County Tax Collector portal `https://secure.taxcollector.com/ptaxweb/editPropertySearch2.action`.

## ANALYSIS RULES

This examination applied the following CURE TitlePro analysis rules:

1. **Vesting must trace from a Warranty Deed (WD) or chain of WD → QCD, oldest to newest.** A QCD alone is insufficient as vesting. ✅ Applied — current vesting cites the 2018 WD (`201841020434`).
2. **Subject address must be NLP-verified from deed image content (Tony Directive #4).** ✅ Applied — verifier yielded MATCH 1.00 on the vesting deed; no NO_MATCH doc was promoted to vesting.
3. **Every indexed document must be examined and accounted for (Tony Directive #5).** ✅ Applied — all 23 union-set candidates appear in the Documents Examined section with include/exclude rationale.
4. **Mortgages must be classified open/released/modified/subordinate via cross-reference, NOT via the search-index column alone (Tony Directive #6).** ✅ Applied — `released_mortgage_linker` confirmed A3 Fairway as RELEASED by A8.
5. **Spouse-delta must be reported to catch one-spouse-only liens (Tony Directive #3).** ✅ Applied — 5 Pablo-only docs surfaced, including the C-2 judgment cloud.
6. **A Limitation of Right of Future Advances (F.S. 697.04) is NOT a subordination.** ✅ Applied — M-3 correctly characterized; M-1 / M-2 priority assigned by recording date.

## IMPORTANT NOTES

- **Local-cache scope:** all Phase 1-3 instrument discovery used the local `manatee_cache.db` SQLite file (snapshot through 2025-12-31). Phase 4 image retrieval used the cache's `doc_id` values via the Clerk's `/DisplayInstrument/InstrumentResultFile/{doc_id}/1/1` endpoint. No live recorder name-searches were executed.
- **Manatee adapter status:** as of this examination, Manatee FL is registered as `fl_manatee` in `src/titlepro/search/recorder/counties/registry.py` (status: `stub_with_local_cache`). No production adapter has been built yet for live search; future runs that require post-2025-12-31 records must build out the two-stage HTTP flow against `records.manateeclerk.com` per `src/titlepro/search/recorder/counties/config/fl/manatee.json`.
- **OCR confidence:** tesseract OCR on handwritten fields (A1 + A6 address fields) produced unreliable text. Verification of those two NOCs relied on cross-reference (terminated by A5 in the case of A6; pre-vesting & expired in the case of A1) rather than direct address parsing.
- **Joint vesting:** both spouses appear on the vesting deed as joint owners. No separate trust grants or trustee designations were recorded for this property (no trust deed found in cache for the subject parcel).
- **Solar UCC chain:** the 2025-2026 solar PV financing arc (NOC → UCC → satisfaction/termination) was completed before the 2026 SouthState refinance closed; no open UCC fixture filing remains.

## DISCLAIMER

This examination was performed against a local SQLite cache snapshot (`manatee_cache.db`, last crawled 2025-12-31) per explicit client directive (2026-05-23). Coverage limitations are documented above:

1. Cache coverage 2007-01-02 → 2025-12-31; **pre-2007 chain (2000 + 2002 conveyances) NOT examined**.
2. C1 Domestic Relations judgment image is **UNAVAILABLE** electronically — courthouse retrieval required for identity verification.
3. Subject-address verifier did not parse handwritten address fields on A1 and A6 (verification by cross-reference instead — see Documents Examined).
4. Lien-position analysis assumes recording-order priority under FL §695.11; does NOT account for any unrecorded subordination agreements that may exist in closing files.
5. Manatee tax-portal lookup not yet wired into the pipeline — **TAX STATUS NOT VERIFIED**.

**Verification against the live Manatee County Clerk records prior to closing is recommended for any item this exam flags as HIGH priority** (lien-position discrepancy §C-1, DR judgment §C-2, pre-2007 chain gap §C-3). This examination is informational and does NOT constitute a title insurance commitment or guarantee.

— *Issued under CURE TitlePro Local-DB Phase 1-4 Pipeline · 2026-05-23 · Examiner: Claude*
