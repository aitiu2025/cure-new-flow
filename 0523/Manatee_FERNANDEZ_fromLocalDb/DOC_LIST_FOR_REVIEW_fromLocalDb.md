# Manatee County FL — FERNANDEZ/ROZANES Subject Document Inventory (from local cache)

**Generated:** 2026-05-23
**Source:** `/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/US_Counties_Data/FL/AIProjects/Manatee_Title_Abstractor_Tools/manatee_cache.db` (table `clerk_records`, 2,682,351 rows, coverage `2007-01-02 → 2025-12-31`)
**NO web calls were made.** All instrument numbers were derived from `clerk_records` queries only.

## Subject
| Field | Value |
|---|---|
| **Property** | 4837 SABAL HARBOUR DR, BRADENTON, FL |
| **APN (Parcel ID)** | `1697719559` (from local `parcel_profile_1697719559.json`) |
| **Subdivision / Legal** | LOT 141 SABAL HARBOUR PHASE V |
| **Current Owners (joint)** | FERNANDEZ PABLO and ROZANES DANIELA |
| **Vesting Deed** | Instrument `201841020434`, recorded 2018-03-01, Book 2716 Page 2565 |

## Cache Coverage Caveat (per Tony Directive #5 — "examine every doc")
- Cache holds Manatee records from **2007-01-02 onward** only.
- Pre-2007 chain links are **NOT** in this DB and must be sourced elsewhere if needed:
  - 2002-10-31 Warranty Deed (CIRRITO/GOULAH → TOIVANEN) at Book 1781 Page 4691
  - 2000-11-15 Special Warranty Deed (PULTE → CIRRITO ANGELA L) at Book 1657 Page 4044
  - Any associated 2000/2002-era mortgages and their satisfactions
- The 1781/4691 and 1657/4044 historical conveyances are visible in the **MCPAO `parcel_profile_1697719559.json` Sales History**, but the corresponding clerk records are absent from the cache.

---

## Search Methodology (Tony Roveda Directives)

| # | Directive | How applied here |
|---|---|---|
| 1 | No Selenium/Playwright | ✅ Pure SQLite queries against local cache |
| 2 | Deed-first search | ✅ Ran `doc_type='DEED'` filter first; identified vesting `201841020434` via `legal LIKE '%LOT 141 SABAL HARBOUR%'` |
| 3 | Every provided name | ✅ Both spouses searched independently + name-misspelling sweep (`FERNADEZ`/`ROSANES`/`ROZANEZ`/`ROZANNES`) + prior-owner sweep (`TOIVANEN REIJO/PIRJO`) |
| 4 | NLP-verify subject address | ⏳ Deferred to Phase 4 (post-download); the `legal` column is the only address proxy in cache — full image OCR needed to confirm |
| 5 | Examine every doc (no silent drops) | ✅ All 23 candidates itemized below with include/exclude status + reason |
| 6 | Released-mortgage exclusion | ✅ Satisfaction/release linkage shown in dependency map below |

## Per-name Hit Counts
| Search key | Hits |
|---|---:|
| `grantors/grantees LIKE '%FERNANDEZ PABLO%'` | 21 |
| `grantors/grantees LIKE '%ROZANES DANIELA%'` | 16 |
| `grantors/grantees LIKE '%FERNADEZ PABLO%'` (misspelling) | 1 |
| `grantors/grantees LIKE '%TOIVANEN REIJO%'` or `TOIVANEN PIRJO%` | 2 |
| Daniela name variants (`ROSANES`/`ROZANEZ`/`ROZANNES`) | 0 |
| `legal LIKE '%LOT 141 SABAL HARBOUR%'` | 7 |
| **Unique union (final candidate set)** | **23** |

**Spouse-delta (Pablo − Daniela) = 5 docs:** the solar UCC chain (`202541032476`, `202541046441`, `202641010612`, `202641050708`) plus the family-court judgment `202141142133` (`FERNANDEZ PABLO C`).

---

## Group A — SUBJECT PARCEL (4837 SABAL HARBOUR DR / Lot 141 Sabal Harbour Phase V)
13 documents

| # | Instrument | Date | Doc Type | Pages | Grantor | Grantee | Legal | Status / Notes |
|---|---|---|---|---:|---|---|---|---|
| A1 | `201541003454395` | 2015-12-01 | NOC | 1 | TOIVANEN REIJO | LEE OVERHOLT CONSTRUCTION INC | (blank in cache; B2596 P7252) | PRIOR-OWNER NOC — OCR-verify subject |
| A2 | `201841020434` | 2018-03-01 | DEED | 1 | TOIVANEN REIJO, TOIVANEN PIRJO | FERNANDEZ PABLO, ROZANES DANIELA | LOT 141 SABAL HARBOUR | **VESTING DEED** (Book 2716/2565) |
| A3 | `201841020435` | 2018-03-01 | MORTGAGE | 20 | FERNANDEZ PABLO, ROZANES DANIELA | MERS / FAIRWAY INDEPENDENT MTG CORP | LOT 141 SABAL HARBOUR | Purchase-money mortgage (Book 2716/2566) — **SATISFIED** by A7 |
| A4 | `202041027841` | 2020-03-13 | AFFIDAVIT | 1 | FERNANDEZ PABLO, ROZANES DANIELA | — | LOT 141 SABAL HARBOUR | Refi-related (likely homestead/identity) |
| A5 | `202041027842` | 2020-03-13 | TERMINATION | 2 | FERNANDEZ PABLO, ROZANES DANIELA | — | OR2802 PG4840 (= NOC A6 below) | Terminates 2019 NOC `201941092835` |
| A6 | `201941092835` | 2019-09-17 | NOC | 1 | FERNADEZ PABLO *(sic, misspelled)* | DYNASTY BUILDING SOLUTIONS | LOT 09 BLK 35 SABAL HARBOUR *(wrong legal?)* | **LIKELY SUBJECT** — indexed with 2 errors (name + legal); contractor batch-NOC pattern (5 other unrelated owners also showed "Lot 09 Blk 35" same week) — OCR-verify |
| A7 | `202041027843` | 2020-03-13 | MORTGAGE | 17 | FERNANDEZ PABLO, ROZANES DANIELA | SUNCOAST CREDIT UNION | LOT 141 SABAL HARBOUR | 2020 HELOC — **SUBORDINATED** to A10 by A11 (still open junior lien) |
| A8 | `202041043360` | 2020-04-28 | SATISFACTION | 1 | MERS / FAIRWAY INDEPENDENT MTG CORP | FERNANDEZ PABLO, ROZANES DANIELA | OR2716 PG2566 (= A3) | Releases A3 (the 2018 Fairway mortgage) |
| A9 | `202541032476` | 2025-03-13 | NOC | 1 | FERNANDEZ PABLO | FREEDOM FOREVER FL LLC | LOT 141 SABAL HARBOUR | Solar install NOC (Pablo only) |
| A10 | `202541046441` | 2025-04-11 | UCC FINANCING STMT | 3 | FERNANDEZ PABLO | SOLAR MOSAIC LLC | (blank) | Solar fixture lien — **TERMINATED** by A13 |
| A11 | `202641010612` | 2026-01-30 | AFFIDAVIT | 1 | ALBRIGHT GREGORY, FREEDOM FOREVER FL LLC, FERNANDEZ PABLO | — | LOT 141 SABAL HARBOUR | Solar contractor affidavit |
| A12 | `202641040260` | 2026-04-09 | MORTGAGE | 10 | FERNANDEZ PABLO, ROZANES DANIELA | SOUTHSTATE BANK | LOT 141 SABAL HARBOUR | **CURRENT OPEN FIRST LIEN** (per workflow guide $115,000 refi) |
| A13 | `202641040261` | 2026-04-09 | NOTICE | 3 | FERNANDEZ PABLO, ROZANES DANIELA | "SUNCROAST" *(sic)* CREDIT UNION | INST 202041027843 (= A7) | **Subordination Agreement** keeping A7 junior to A12 |
| A14 | `202641050708` | 2026-05-04 | TERMINATION | 2 | SOLAR MOSAIC LLC | FERNANDEZ PABLO | INST 202541046441 (= A10) | Terminates A10 UCC — solar paid off pre-refi |

## Group B — NOT SUBJECT (different parcels, examined and excluded per Directive #5)
8 documents

| # | Instrument | Date | Doc Type | Grantor | Grantee | Legal | Exclude Reason |
|---|---|---|---|---|---|---|---|
| B1 | `201641013923` | 2016-06-30 | DEED | D R HORTON INC | ROZANES DANIELA, FERNANDEZ PABLO | LOT 361 DEL TIERRA | Different parcel (Del Tierra builder home) |
| B2 | `201641013924` | 2016-06-30 | MORTGAGE | ROZANES/FERNANDEZ | MERS / DHI MTG | LOT 361 DEL TIERRA | Del Tierra purchase-money — **SATISFIED** by B4 |
| B3 | `201841020245` | 2018-03-01 | DEED | FERNANDEZ/ROZANES | HANSEN JON MICHAEL, HANSEN ELIZABETH ANNE | LOT 361 DEL TIERRA | Different parcel (sale of Del Tierra) |
| B4 | `201841023993` | 2018-03-12 | SATISFACTION | MERS / DHI MTG | FERNANDEZ/ROZANES | OR2627 PG2203 (= B1 mortgage chain) | Releases B2 |
| B5 | `202141105577` | 2021-08-10 | DEED | SCOTT PAMELA | FERNANDEZ/ROZANES | LOT 5 BLK E TYLERS | Different parcel (Tylers purchase) |
| B6 | `202141105578` | 2021-08-10 | MORTGAGE | FERNANDEZ/ROZANES | MERS / CROSSCOUNTRY MTG | LOT 5 BLK E TYLERS | Tylers purchase-money — **RELEASED** by B7 |
| B7 | `202341078556` | 2023-07-21 | RELEASE | MERS / CROSSCOUNTRY MTG | FERNANDEZ/ROZANES | INST 202141105578 (= B6) | Releases B6 |
| B8 | `202341080572` | 2023-07-27 | DEED | FERNANDEZ/ROZANES | MATALA MATTHEW/HARRY JOSEPH | LOT 5 BLK E TYLERS | Different parcel (sale of Tylers) |

## Group C — CRITICAL CLOUD / IDENTITY UNCONFIRMED
1 document

| # | Instrument | Date | Doc Type | Grantor | Grantee | Legal | Notes |
|---|---|---|---|---|---|---|---|
| C1 | `202141142133` | 2021-10-26 | JUDGMENT | **FERNANDEZ PABLO C** | LOPEZ REINA | Case `2021 DR 001719` (Domestic Relations) | Middle initial **"C"** differs from subject's known name. Active family-court support judgments attach as floating liens against all real property in the county owned by the named obligor. Cannot resolve identity from cache alone — requires (a) OCR'd judgment for DOB/SSN/address match, and (b) same-name affidavit at closing |

---

## Mortgage Status Map (Directive #6)
| Mortgage | Status | Linked Satisfaction/Termination | Position |
|---|---|---|---|
| A3 (2018 Fairway, Book 2716/2566) | **RELEASED** | A8 (2020-04-28) | n/a |
| A7 (2020 Suncoast HELOC) | **OPEN — SUBORDINATED** | A13 (2026 subordination notice) | Junior 2nd |
| A12 (2026 SouthState) | **OPEN — FIRST LIEN** | — | Senior 1st |
| A10 (2025 Solar Mosaic UCC) | **TERMINATED** | A14 (2026-05-04) | n/a |
| A6 (2019 NOC) | **TERMINATED** | A5 (2020-03-13) | n/a |
| B2 (2016 Del Tierra DHI) | **SATISFIED** | B4 (2018-03-12) | not on subject |
| B6 (2021 Tylers CrossCountry) | **RELEASED** | B7 (2023-07-21) | not on subject |

---

## Pre-Download Questions for User
Before we proceed to Phase 4 (download + OCR + report generation), please confirm:

1. **A6 + A1 inclusion** — proceed to download `201941092835` (FERNADEZ misspelling) and `201541003454395` (Toivanen NOC) for OCR verification of subject relevance? Both could be subject-related but indexed weirdly.
2. **C1 identity** — do we have any independent source (closing prelim, MLS, prior title commitment) that confirms whether subject Pablo Fernandez has middle initial "C"? If yes/no, the judgment treatment changes.
3. **Pre-2007 chain** — confirmed acceptable to flag pre-2007 conveyances as "outside cache coverage; refer to MCPAO sales history" in the report, OR do you want me to pull them from another source later?
4. **Doc download set** — proceed with all 23, or limit to Group A + C only (skip the 8 unrelated-parcel docs)?
