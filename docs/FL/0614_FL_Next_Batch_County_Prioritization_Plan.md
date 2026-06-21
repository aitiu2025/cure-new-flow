# FL Next-Batch County Prioritization Plan — 0614

**Date:** 2026-06-14
**Author:** TIU / CURE engineering
**Trigger:** Peter Bodonyi email "next batch of counties" (2026-06-12), seconded by Tony Roveda.
**Source of truth:** `docs/FL/FL_CURE_County_Search_URLs.xlsx` (FL sheet) — Peter's worksheet, sorted by recorder platform; Column B = Peter-reviewed files.

---

## 1. Peter's directive (verbatim hit list)

After counsel with Tony, the agreed attack order for the next batch is:

1. **Miami-Dade** (Proprietary)
2. **Broward** (Proprietary)
3. **All Landmark counties** (green) — 2 / 16 completed
4. **OneCare** (grey) — 2 / 4 completed
5. **Tyler Technologies** (peach) — 1 / 5 completed *(sheet shows 4 Tyler counties — see §7 discrepancy)*

> "Then once these are solid, go back and finish off the remaining proprietary platform counties and Clericus platform (the rural counties)."

This plan keeps Peter's ordering intact and sequences the work **within** it by engineering readiness, so we run exams in the order that clears blockers fastest.

---

## 2. Scope snapshot (from the source-of-truth sheet)

| Platform | Total | Reviewed / done | Remaining in this batch |
|---|---|---|---|
| Proprietary — flagships | 2 | Broward (refined) | Miami-Dade, Broward (regression-lock) |
| Landmark | 16 | Palm Beach, Lee | 14 |
| OneCare | 4 | Duval, Brevard | Pinellas, Lake |
| Tyler Technologies | 4 | Orange | Okaloosa, Gadsden, Taylor |
| **Batch total** | **26** | **6** | **20** |
| *Deferred (Peter's "then")* | | | z-Proprietary ×9, Clericus ×23 |

Already green (Peter-confirmed perfect/correct): Palm Beach, Lee, Duval, Orange, Polk, Manatee, Volusia, Seminole, Sarasota, Pasco, Hillsborough (yellow→green pending vesting-command tweak).

---

## 3. The real bottleneck is **not** the recorder adapter

The recorder adapters for every platform in this batch already exist and are proven live. What gates each exam is the **Property Appraiser (PA) anchor** — mandatory per the Broward Standard — and **Tony delivering test subjects**. Current registry coverage:

| Capability | Built / registered | Gap for this batch |
|---|---|---|
| **Recorder adapter** | Miami-Dade, AcclaimWeb (Broward), Landmark, Tyler self-service, DuProcess, Hillsborough, Manatee, Pasco, PublicSoft, Sarasota, Volusia | OneCare needs generalizing (Duval was one-off); Tyler "PublicInquiry.aspx" product (Gadsden, Taylor) is a **different** adapter from Orange's tylerhost self-service |
| **Tax adapter** | All 14 Landmark targets ✅ already registered; Grant Street, Manatee, Orange covered | Pinellas, Lake, Okaloosa (Grant St — register only); Gadsden (Aumentum — new); Taylor (PublicSoft) |
| **Property Appraiser** | 13 FL: Brevard, Broward, Duval, Hillsborough, Lee, Manatee, Orange, Palm Beach, Pasco, Polk, Sarasota, Seminole, Volusia | **Miami-Dade, Pinellas, Lake, all 14 Landmark targets, Okaloosa, Gadsden, Taylor — 20 PA adapters to build** |

**Takeaway:** PA-adapter builds are the critical path for ~every county in the batch, and the Landmark counties additionally need Tony to deliver test subjects (only Palm Beach & Lee have them today). Tax is largely a non-issue for Landmark.

---

## 4. Per-county readiness matrix

Legend: ✅ ready · 🔧 build/generalize needed · ⬜ missing · ⏳ awaiting Tony

### 4a. Flagship proprietary

| # | County | Recorder | Tax | PA | Test subj | Net effort |
|---|---|---|---|---|---|---|
| 1 | Miami-Dade | ✅ | ✅ (Grant St) | ⬜ build MDCPA | ✅ Navas / Haugabook | **High** (PA build) |
| 2 | Broward | ✅ | ✅ | ✅ | ✅ Simmons / Anand | **Low** (regression only) |

### 4b. Landmark (14 remaining, population-ranked)

| # | County | Recorder | Tax | PA | Test subj |
|---|---|---|---|---|---|
| 19 | Escambia | ✅ | ✅ | ⬜ | ⏳ |
| 22 | St. Johns | ✅ | ✅ | ⬜ | ⏳ |
| 25 | Clay | ✅ | ✅ | ⬜ | ⏳ |
| 27 | Hernando | ✅ | ✅ | ⬜ | ⏳ |
| 28 | Bay | ✅ | ✅ | ⬜ | ⏳ |
| 30 | Martin | ✅ | ✅ | ⬜ | ⏳ |
| 31 | Indian River | ✅ | ✅ | ⬜ | ⏳ |
| 33 | Citrus | ✅ | ✅ | ⬜ | ⏳ |
| 34 | Flagler | ✅ | ✅ | ⬜ | ⏳ |
| 38 | Monroe | ✅ | ✅ | ⬜ | ⏳ |
| 42 | Walton | ✅ | ✅ | ⬜ | ⏳ |
| 46 | Wakulla | ✅ | ✅ | ⬜ | ⏳ |
| 47 | Levy | ✅ | ✅ | ⬜ | ⏳ |
| 48 | Okeechobee | ✅ | ✅ | ⬜ | ⏳ |

Recorder adapter proven on Palm Beach + Lee → each new Landmark county is **config + PA build + live-run**. Tax already registered for all 14.

### 4c. OneCare (2 remaining)

| # | County | Recorder | Tax | PA | Test subj |
|---|---|---|---|---|---|
| 7 | Pinellas | 🔧 generalize OneCare | ⬜ register (Grant St) | ⬜ | ✅ Grenesko / Harris-Weismann |
| 21 | Lake | 🔧 generalize OneCare | ⬜ register (Grant St) | ⬜ | ⏳ |

Pinellas already has subjects and an earlier probe (Abhishek, 6/5) — resolve that flagged issue first.

### 4d. Tyler (3 remaining)

| # | County | Recorder | Tax | PA | Test subj |
|---|---|---|---|---|---|
| 26 | Okaloosa | ✅ reuse Orange tylerhost | ⬜ register (Grant St) | ⬜ | ⏳ |
| 44 | Gadsden | 🔧 new "PublicInquiry.aspx" adapter | 🔧 Aumentum tax | ⬜ | ⏳ |
| 52 | Taylor | 🔧 new "PublicInquiry.aspx" adapter | 🔧 PublicSoft tax | ⬜ | ⏳ |

Okaloosa rides the existing Tyler self-service adapter; Gadsden and Taylor are a different, older Tyler product and need their own adapter.

---

## 5. Recommended wave plan

**Wave 0 — Lock the flagships (this week).**
Run Broward as a regression against the current model (both Simmons and Anand) to re-confirm the reference floor — near-zero cost. In parallel, build the **Miami-Dade Property Appraiser (MDCPA) adapter** (the one true gap for #1), then run Navas + Haugabook. Miami-Dade is the highest-effort single county in the batch and should start first because its PA build is on the critical path and the recorder + indexing work is already done.

**Wave 1 — Landmark scale-out (highest leverage).**
The adapter is proven, tax is fully covered, so throughput is bounded only by PA builds and Tony's subjects. Build PA adapters in population order and live-run in batches of 3–4 as subjects arrive:
- 1a: Escambia, St. Johns, Clay, Hernando
- 1b: Bay, Martin, Indian River, Citrus
- 1c: Flagler, Monroe, Walton, Wakulla
- 1d: Levy, Okeechobee

This is where most of the 20-county volume clears, fastest per unit of effort.

**Wave 2 — Finish OneCare (small).**
Generalize the Duval/OneCare recorder path into a reusable adapter, then run Pinellas (subjects ready — clear the 6/5 probe issue first) and Lake (needs subject + PA). Only two counties.

**Wave 3 — Finish Tyler.**
Okaloosa first (reuses the Orange adapter — fastest). Then build the "PublicInquiry.aspx" adapter once and apply to Gadsden + Taylor; add Aumentum (Gadsden) and PublicSoft (Taylor) tax.

**Wave 4 — Deferred per Peter ("then").**
Remaining z-Proprietary ×9 (St. Lucie, Collier, Marion, Osceola, Leon, Alachua, Charlotte, Santa Rosa, Highlands) and Clericus ×23 rural counties. Clericus has **no adapter yet** and Tony's Clericus worksheet section is empty — both are prerequisites before this wave can start.

---

## 6. Critical-path asks

**To Tony (test subjects) — this unblocks Waves 1–3.** Please deliver A/B test subjects for: the 14 Landmark counties, Lake, and the 3 Tyler counties (Okaloosa, Gadsden, Taylor) — 18 counties total. Miami-Dade, Broward, and Pinellas already have subjects.

**To engineering (build order):**
1. Miami-Dade PA adapter (MDCPA) — gates Wave 0.
2. 14 Landmark PA adapters — gate Wave 1 (mirror the Palm Beach/Lee PA pattern; ~the rate-limiter for the batch).
3. Generalize OneCare recorder adapter (from the Duval one-off) — gates Wave 2.
4. Tyler "PublicInquiry.aspx" recorder adapter (Gadsden, Taylor) + Okaloosa tax registration — gates Wave 3.
5. Tax registration: Pinellas, Lake, Okaloosa (Grant Street — config only); Gadsden (Aumentum), Taylor (PublicSoft).

---

## 7. Open items / to confirm with Peter

- **Tyler count.** Peter wrote "1 / 5 completed," but the source-of-truth sheet lists **4** Tyler counties (Orange, Okaloosa, Gadsden, Taylor). Confirm whether a 5th county is being counted (possible mis-tag of a county sorted under another platform).
- **Broward intent.** Confirming we read #2 as "lock/regression the reference county," not a fresh build — Broward is already the Standard's floor.
- **Hillsborough.** Currently yellow pending the vesting-command adjustment; once that lands it should flip green and need no new exam.

---

## 8. Suggested two-week shape (subject to Tony's subject delivery)

| Days | Focus |
|---|---|
| 1–2 | Broward regression; start MDCPA PA build |
| 3–4 | Miami-Dade live-run; begin Landmark PA builds (1a) |
| 5–8 | Landmark waves 1a → 1c live-runs as subjects arrive |
| 9–10 | Landmark 1d; OneCare generalize + Pinellas |
| 11–12 | Lake; Tyler Okaloosa |
| 13–14 | Tyler PublicInquiry adapter → Gadsden + Taylor; batch verifier sign-off |

Every county ships only after the `verify-cure-report` 6-directive scorecard + Quality Gates Q1–Q4 pass (or WARN with a concrete engineering ticket — never bare FAIL), per the Broward Standard.
