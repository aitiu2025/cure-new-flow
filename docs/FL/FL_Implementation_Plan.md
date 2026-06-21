# FL Implementation Plan

> **Status:** Active. Pivot from CA → FL completed 2026-05-20. First test subjects delivered 2026-05-21.
>
> **Source of truth:** `docs/FL/FL_Examples.md` (county data) + `docs/FL/FL_Platform_Examination_Guide.md` (per-platform examination procedures).

## Build Wave (priority order)

### Wave 1: Tyler Technologies (4 counties) — **MINIMAL CODE** — reuses CA Tyler adapter

Reuse `tyler_adapter.py`. The 2Captcha integration already shipped covers reCAPTCHA-protected Tyler counties.

Counties (population rank):
- #5 **Orange** — https://selfservice.or.occompt.com/ssweb/user/disclaimer [HAS SUBJECTS]
- #26 **Okaloosa** — https://okaloosacountyfl-web.tylerhost.net/web/user/disclaimer
- #44 **Gadsden** — https://www.gadsdenclerk.com/PublicInquiry/Search.aspx?Type=Name
- #52 **Taylor** — https://pubrecords.taylorclerk.com/PublicInquiry/Search.aspx?Type=Name

**First target: Orange (#5)** — only Tyler FL county with test subjects ready (GREER + MIRANDA).

### Wave 2: Landmark (16 counties) — **NEW ADAPTER**

Build `landmark_adapter.py`. Pattern documented in `FL_Platform_Examination_Guide.md`. Est ~1-2 days.

Counties:
- #3 Palm Beach [HAS SUBJECTS]
- #8 Lee [HAS SUBJECTS]
- #19 Escambia
- #22 St. Johns
- #25 Clay
- #27 Hernando
- #28 Bay
- #30 Martin
- #31 Indian River
- #33 Citrus
- #34 Flagler
- #38 Monroe
- #42 Walton
- #46 Wakulla
- #47 Levy
- #48 Okeechobee

### Wave 3: OneCare (4 counties) — **NEW ADAPTER**

Build `onecare_adapter.py`. Unique 'name variance dialogue' step (check 'Show All' to capture middle-initial variants). Est ~1 day.

Counties:
- #6 Duval [HAS SUBJECTS]
- #7 Pinellas [HAS SUBJECTS]
- #11 Brevard [HAS SUBJECTS]
- #21 Lake

### Wave 4: DuProcess (3 counties) — **NEW ADAPTER** (simplest)

Build `duprocess_adapter.py`. Simple form, no CAPTCHA gate. Parcel-ID search may be available (untested by Tony).

Counties:
- #13 Seminole [HAS SUBJECTS]
- #50 Baker
- #59 Union

### Wave 5: Clericus (23 counties) — **NEW ADAPTER**, biggest single-platform

Build `clericus_adapter.py`. **Blocked on Tony's docx Clericus section being empty.** Need either updated docx or live-portal investigation.

Counties:
- #35 Nassau
- #36 Sumter
- #39 Columbia
- #40 Putnam
- #41 Jackson
- #43 Hendry
- #45 DeSoto
- #49 Suwannee
- #51 Hardee
- #53 Bradford
- #54 Washington
- #55 Holmes
- #56 Gulf
- #57 Gilchrist
- #58 Madison
- #60 Dixie
- #61 Hamilton
- #62 Calhoun
- #63 Jefferson
- #64 Franklin
- #65 Glades
- #66 Lafayette
- #67 Liberty

### Wave 6: z-Proprietary (17 counties) — **PER-VENDOR ADAPTERS**

Each proprietary vendor likely needs its own adapter. Tony flagged **VisualGov + PublicSoft** as the two biggest. Investigation needed to confirm which vendor powers each county.

Notable: 10 of the top-20 most-populous FL counties fall in this bucket — Miami-Dade, Broward, Hillsborough, Pasco, Polk, Volusia, Sarasota, Manatee. These have HIGH revenue impact but require dedicated per-vendor builds.

**Active sub-build (2026-05-21):** Miami-Dade adapter scaffolded — config promoted from `status: stub` to `status: in_progress`, adapter skeleton (`miami_dade_adapter.py`) + registry wiring + test-subject case folders (NAVAS, HAUGABOOK) in place; method bodies pending live-portal probe. Commercial-access alternative ($1/exam or $500 for 5000) flagged for cost/effort comparison before completing the scraper build. See `docs/FL/Miami_Dade_Indexing_Review.md` for design inputs.

**Probe completed 2026-05-21 (BLOCK):** Live portal probe (see `docs/FL/miami_dade_probe.md`) confirmed the portal is an SPA shell with NO anonymous search form — 0 `<input>`, 0 `<form>`, 0 search references in the landing HTML. All entry points funnel to `Register/Login` or the paid Developer API. **Custom-scraper path is not viable.** Status: `blocked_on_access_decision`. Two paths forward: commercial portal access ($1/exam UI route) or Developer API (also paid). Both require a business decision on monthly cost vs per-CURE-report margin. **No further adapter work until access decision is made.**

Counties:
- #1 Miami-Dade [HAS SUBJECTS] — **BLOCKED on access decision** (probe complete, no public search form exists)
- #2 Broward [HAS SUBJECTS]
- #4 Hillsborough [HAS SUBJECTS]
- #9 Polk [HAS SUBJECTS]
- #10 Pasco [HAS SUBJECTS]
- #12 Volusia [HAS SUBJECTS]
- #14 Sarasota [HAS SUBJECTS]
- #15 Manatee [HAS SUBJECTS]
- #16 St. Lucie
- #17 Collier
- #18 Marion
- #20 Osceola
- #23 Leon
- #24 Alachua
- #29 Charlotte
- #32 Santa Rosa
- #37 Highlands

## Tax recipes (separate concern)

Tax platforms across the 67 counties (from `Tax Platform` column):
- **Grant Street**: 31 counties
- **PublicSoft**: 11 counties
- **VIsualGov**: 10 counties
- **VisualGov**: 8 counties
- **Aumentum Technologies**: 3 counties
- **Pacific Blue**: 2 counties
- **Unnamed 1**: 2 counties

**Big win:** Grant Street's `county-taxes.net` pattern is already handled by our `playwright_form` tax-recipe runner (used for CA Sacramento, San Bernardino). Adding FL recipes for Grant Street counties = config-only, no new runner code.

## Decision log (2026-05-21)

- **Adapter config location:** existing `src/titlepro/search/ca_recorder/counties/config/` (module rename to `recorder_counties` deferred until non-CA content reaches critical mass)
- **File naming convention:** state suffix for non-CA counties — e.g. `orange_fl.json` (vs existing `orange.json` for Orange CA)
- **Adapter stub creation:** only for counties with test subjects ready (15 today)
- **First build target:** Tyler / Orange FL — drop-in test of existing Tyler adapter + 2Captcha integration
