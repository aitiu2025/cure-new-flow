# OnE Spec v1.7 Amendment — Prior Vesting Chain Display (FINAL)

> **Status:** FINAL + APPLIED — Amit's review answers received 2026-06-12 and
> incorporated (see §1.1 Review Refinements + §5 Resolved Questions). Applied to the
> canonical spec (`OnE_Report_SystemPrompt_v1.2.md`, current content version v1.7)
> and supporting generator rules; implementation checklist retained in §4 for audit.
>
> **Source:** Peter Bodonyi, `~/Downloads/Vesting Exam - Report Standards example.xlsx`
> (received 2026-06-12). Four worked scenarios — straight sale; add-spouse QCD; trust QCD;
> trust + divorce + name-change with two same-day QCDs — each with a recorded chain and a
> "Report should show" expected output.
>
> **Net effect:** §2 Prior Vesting changes from a single immediate-prior-owner block to a
> **chain table (newest → oldest)** ending at the prior owner's **tenure-commencing
> instrument**, governed by a **materiality rule** for which rows render client-side
> (current-tenure interims always; prior-tenure administrative interims may be
> Title-only with a connector note; when in doubt, INCLUDE). The v1.6 same-day
> refi-cycle guard is **repositioned** (annotate, don't hide), not removed. Follow-on
> rules: same-day ordering, current-legal-name display with alias retained for
> searching, and the no-search-window-floor rule with a single sourced index-horizon
> carve-out.

---

## 1. The rules Peter's scenarios encode

| # | Rule | Evidence in xlsx |
|---|---|---|
| P-V1 | **Current Vesting = the single most-recent vesting instrument, even when it's a QCD** (add-spouse, into-trust, out-of-trust, divorce). Never walk back to the last WD for the Current Vesting block. | Scenarios 2, 3, 4: expected Current Vesting is the QCD in every case |
| P-V2 | **Prior Vesting = the ENTIRE prior chain, newest → oldest, every interim conveyance visible**, terminating at (and including) the **prior owner's arm's-length acquisition deed**. Nothing walked past, nothing demoted out of the client report. **Refined by R-1 (§1.1)** — materiality rule for prior-tenure interims; all of Peter's scenario interims are current-tenure, so the xlsx is consistent with the refinement. | Scenario 2: 2 prior rows; Scenario 3: 3 rows; Scenario 4: all 5 prior instruments incl. both same-day QCDs |
| P-V3 | **Two-owner boundary counted by arm's-length acquisitions, not deed count.** All intra-family / trust / divorce QCDs within one tenure are the SAME owner. Prior owner in Scenario 4 is Bill Brown (not the trust, not "Joe alone"). | Scenario 4 chain bottoms at Mark Williams → Bill Brown (2010), two arm's-length WDs total |
| P-V4 | **Same-day instruments both render**, ordered by chain logic (grantee of one = grantor of the next), not collapsed and not reordered by date alone. | Scenario 4: 06/01/2026 trust→couple precedes 06/01/2026 couple→Jane |
| P-V5 | **Display the current legal name; keep the alias for searching.** Indexed grantee "Jane Johnson formerly Jane Smith" renders as "Jane Johnson"; the former name stays in the Title notes and the name-search list. | Scenario 4 expected Current Vesting grantee = "Jane Johnson" |
| P-V6 | **The exam reaches back as far as the two-owner chain requires — there is NO fixed search-window floor** (not 2010, not any other date). The chain is complete only when both tenure-commencing acquisitions are found and cited. "Date outside of search window" (and variants) is BANNED language everywhere in both reports. **Refined by R-2 + R-3 (§1.1)** — tenure-commencing definition + index-horizon carve-out. | Every scenario's expected output includes the 2010 prior-owner acquisition; user directive 2026-06-12 |

**Already aligned (no change):** Current Vesting selection (P-V1), two-owner boundary
(P-V3), and `vesting_chain_walker.py` internals — the walk logic is exactly what
identifies the arm's-length boundary; only its *presentation contract* changes.

## 1.1 Review Refinements (Amit, 2026-06-12 — these refine the raw P-V readings above)

| # | Refinement | Source |
|---|---|---|
| R-1 | **Chain-display materiality rule.** Both tenure-commencing acquisitions: ALWAYS in the OnE. Current-tenure interim conveyances (add-spouse / trust / divorce / corrective / name-change QCDs): ALWAYS in the OnE — they are title-material to what the current owner holds (GREER Orange class: 2004 QCD completing the fee from the 2002 ½-interest WD). PRIOR-tenure administrative interims (e.g., prior owners deeded into their own trust and we acquired from the trust): MAY be omitted from the OnE — Title TV3 carries them ALWAYS, and the OnE gets a one-line connector note so the chain shows no unexplained grantor/grantee discontinuity. **When in doubt, INCLUDE — more is good; the examiner can strip rows before sending; removing material information is the failure mode, extra rows are not.** | Amit answer #1, 2026-06-12 |
| R-2 | **Tenure-commencing instrument definition** (replaces bare "arm's-length acquisition" as the chain terminator): arm's-length sale (WD or equivalent) OR inheritance vesting (Personal Representative's / probate deed) OR court/involuntary transfer (Certificate of Title from foreclosure, tax deed). The chain stops at the prior owner's tenure-commencing instrument — no need to chain beyond it. Walker stops at PR deeds, Certificates of Title, and tax deeds. | Amit answer #2, 2026-06-12 |
| R-3 | **Index-horizon carve-out** (sole exception to the banned-language rule): when a needed instrument predates the county's digitized index, the report states it concretely and sourced — "Official Records online index begins MM/YYYY per [county source]; instrument predates the digitized index; manual/mail search ordered — engineering ticket #". Bare "outside search window" stays banned. | Amit answer #3, 2026-06-12 |
| R-4 | **Same-day display order clarified:** within a same-day pair in the newest→oldest table, the chain-LATER instrument (the one whose grantor is the other's grantee) renders HIGHER; instrument-number fallback (higher number higher). | Review fix (the draft's "comes first" was ambiguous about display vs chain order) |
| R-5 | **Verifier checks stay SEPARATE** (OnE-15 same-day ordering, OnE-16 name display) — NOT folded into OnE-14. Distinct failure modes with distinct severities; folding muddies triage. Reverses the draft §3.3 folding recommendation. | Review decision |

---

## 2. Spec changes (`docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md`)

### 2.1 Version banner — ADD above the v1.6 line

```markdown
> **Version: 1.7** (2026-06-12) — Peter Bodonyi "Vesting Exam — Report Standards" xlsx
> adoptions + Amit review refinements. Four changes vs v1.6: (a) **§2 Prior Vesting is
> now a chain table** (newest → oldest, terminating at the prior owner's
> tenure-commencing instrument) replacing the single immediate-prior-owner block,
> governed by a **materiality rule** — current-tenure interims always render;
> prior-tenure administrative interims may be Title-only with a connector note; when in
> doubt, include. The v1.6 same-day refi-cycle guard is REPOSITIONED — the walker now
> ANNOTATES which chain row is the genuine prior-owner acquisition instead of demoting
> interim deeds out of the OnE. (b) **Tenure-commencing instrument definition** —
> arm's-length sale OR PR/probate deed OR Certificate of Title OR tax deed; the chain
> stops there. (c) **Current-legal-name display rule** — vesting fields render the
> current legal name; "formerly known as" aliases stay in the Title notes and the
> name-search list. (d) **NO search-window floor** — the exam back-chains as many years
> as the two-owner chain requires; "date outside of search window" and variants are
> BANNED in both reports, with a single sourced index-horizon carve-out. Quality Gates
> Q24 amended; Q26-Q28 added.
```

### 2.2 §2 Prior Vesting — REPLACE the whole "### Prior Vesting" block
(currently "Same structure. Render the immediate prior owner of record…" + the
same-day-guard paragraph + the sidecar-integration paragraph)

```markdown
### Prior Vesting

**v1.7 (2026-06-12, per Peter's Vesting Exam — Report Standards xlsx + Amit's review
answers): Prior Vesting is a CHAIN TABLE, not a single block.** Render the vesting
chain newest → oldest, terminating at (and including) the **prior owner's
tenure-commencing instrument** (the two-owner boundary — definition below).

**Tenure-commencing instrument (v1.7 definition):** the instrument that starts an
ownership tenure — an arm's-length sale (WD or equivalent), OR inheritance vesting
(Personal Representative's / probate deed), OR a court/involuntary transfer
(Certificate of Title from foreclosure, tax deed). The chain stops at the prior
owner's tenure-commencing instrument; never chain beyond it.

**Which rows render in the OnE chain (materiality rule):**
- Both tenure-commencing acquisitions (current owner's AND prior owner's) — ALWAYS.
- ALL current-tenure interim conveyances (add-spouse QCD, into-/out-of-trust QCD,
  divorce QCD, corrective deed, name-change QCD) — ALWAYS. These are title-material to
  what the current owner holds (GREER Orange class: the 2004 QCD completing the fee
  from the 2002 ½-interest WD).
- PRIOR-tenure interim conveyances — only when material to the examiner's conclusions.
  A pure administrative shuffle inside the prior owner's tenure (e.g., prior owners
  deeded into their own trust and the current owner acquired from the trust) MAY be
  omitted from the OnE chain; it MUST still appear in the Title TV3 chain. When
  omitted, add a one-line connector note on the current owner's acquisition row
  ("grantor is the prior owners' estate-planning trust — interim conveyance detailed
  in Title notes") so the OnE chain shows no unexplained grantor/grantee
  discontinuity.
- **When in doubt, INCLUDE.** More is good; the examiner can strip rows before
  sending. Removing material information is the failure mode; extra rows are not.

| Recording Date | Document Type | Instrument # | OR Book / Page | Grantor | Grantee |
|---|---|---|---|---|---|
| MM/DD/YYYY | QCD | instr# | Book/Page | … | … |
| MM/DD/YYYY | WD ◀ *tenure-commencing — current owner tenure begins* | instr# | Book/Page | … | … |
| MM/DD/YYYY | WD ◀ *tenure-commencing — prior owner tenure begins* | instr# | Book/Page | … | … |

Annotation rules:
- Mark each **tenure-commencing** row (the tenure boundaries) with the inline italic
  note shown above. There will normally be exactly two in a Two-Owner search.
- **Same-day instruments:** render both, NEVER collapse into one row. Display order
  within the newest→oldest table: the chain-LATER instrument (the one whose grantor is
  the other's grantee) renders HIGHER; fall back to instrument-number order (higher
  instrument number renders higher).
- If a chain row was first located via the PA roll index, its Instrument # / Book /
  Page must still be resolved by pulling the document from the recorder's
  direct-retrieval endpoint (the recorder indexes virtually all FL counties back well
  past any chain we will need). Cite the recorder instrument concretely; the PA roll is
  a locator, not a citation of record.
- **Two-owner boundary is counted by tenure-commencing instruments, not deed count.**
  All intra-family / trust / divorce conveyances within one tenure belong to the SAME
  owner.

**Same-day refi-cycle guard — REPOSITIONED in v1.7 (supersedes the v1.6 walk-past
rule):** the guard no longer hides interim deeds from the OnE — Peter's standard shows
the chain. The guard's job is now identification, not suppression:
(a) the chain table must CONTINUE PAST any interim conveyance (≤30 days from Current
Vesting with party overlap, or any intra-tenure QCD) down to the genuine
tenure-commencing instrument — a chain that STOPS at an interim conveyance is the
failure mode;
(b) the **prior OWNER** (for the prior-owner name sweep, Q13) is the grantor of the
current owner's tenure-commencing acquisition — never an interim-deed grantor, never
the owners' own trust. When that grantor is a trust the prior owners created
mid-tenure, the prior OWNER for sweep purposes is the individuals, and their sweep
window covers their full tenure (individual + trust-held years).

**Sidecar integration (v1.7):** `src/titlepro/verification/vesting_chain_walker.py`
writes findings to `phase1_verifications.json` under key `vesting_chain_walker`. When
`status == "SAME_DAY_REFI_INTERIM_DETECTED"`, the LLM MUST (i) render the full chain
including the detected interim deed as a visible row, (ii) annotate
`recommended_walk_target_doc_number` as the tenure-commencing acquisition row, and
(iii) use the walk-target's grantor as the prior owner for sweep purposes. When
`status == "AMBIGUOUS"`, render the chain and add an inline operator-review note on the
ambiguous row. (v1.6 behavior — citing only the walk-target and demoting the interim
deed to the Title — is RETIRED.)

**Name display (v1.7):** vesting fields render the **current legal name**. When the
recorder index carries an alias ("Jane Johnson formerly Jane Smith", "f/k/a", "n/k/a"),
strip the alias phrase from the OnE display name. The former name MUST be retained in
the Title companion (Documents Examined + name-search list) and swept for liens like
any other provided name (Tony directive #3 / spouse-delta).
```

### 2.3 Quality Gates — AMEND Q24, ADD Q26-Q28

Q24 (replace):

```markdown
24. **§2 PRIOR-VESTING CHAIN COMPLETE (v1.7 — supersedes the v1.6 walk-past form of this
    gate)** — the Prior Vesting chain table must (a) include EVERY current-tenure
    conveyance between Current Vesting and the current owner's tenure-commencing
    acquisition (no skipped interim deeds), (b) NOT stop at an interim conveyance —
    when
    `phase1_verifications.json.vesting_chain_walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"`,
    the chain must continue to `recommended_walk_target_doc_number` and that row must
    carry the tenure-commencing annotation — and (c) for any PRIOR-tenure interim
    conveyance omitted from the OnE under the materiality rule: the instrument MUST
    appear in the Title TV3 chain AND the connector note MUST be present on the
    affected OnE row. (`verify-cure-report` check OnE-14 — ship-blocker when violated.)
```

Append:

```markdown
26. **§2 SAME-DAY ORDERING (v1.7)** — when two or more vesting instruments share a
    recording date, both render as separate rows; within the newest→oldest table the
    chain-LATER instrument (the one whose grantor is the other's grantee) renders
    HIGHER, with instrument-number order as fallback (higher number higher). Collapsed
    or misordered same-day pairs are FAIL.
27. **§2 CURRENT-LEGAL-NAME DISPLAY (v1.7)** — no "formerly known as" / "f/k/a" /
    "n/k/a" alias phrases inside OnE vesting name fields; the alias must appear in the
    Title companion's name-search list. Alias leaked into the OnE vesting display OR
    alias absent from the Title name-search list is FAIL.
28. **NO SEARCH-WINDOW LANGUAGE, NO SEARCH-WINDOW FLOOR (v1.7)** — zero occurrences,
    anywhere in the OnE OR the Title, of: "outside (of) (the) search window",
    "outside (the) search range", "pre-search-range", "beyond the search period",
    "prior to the search start date", or any equivalent phrase implying a date-based
    exam boundary. **SOLE permitted exception (index-horizon carve-out, approved
    2026-06-12):** a sourced, concrete statement of the county's digitized-index start
    — "Official Records online index begins MM/YYYY per [county source]; instrument
    predates the digitized index; manual/mail search ordered — engineering ticket #" —
    is allowed; bare window language is not. Additionally FAIL when the Prior Vesting
    chain's oldest row is NOT a tenure-commencing instrument (arm's-length sale,
    PR/probate deed, Certificate of Title, or tax deed) AND no index-horizon statement
    explains the stop — a chain whose oldest row is an unexplained QCD/interim
    conveyance means the back-chain stopped short, almost always a window-floor
    artifact. Ship-blocker.
```

### 2.4 Revision History — ADD entry

```markdown
- **2026-06-12 — v1.7** — Peter Bodonyi "Vesting Exam — Report Standards example.xlsx"
  adoptions (4 worked scenarios) + Amit review refinements (same day). §2 Prior Vesting
  changed from single immediate-prior-owner block to chain table (newest → oldest,
  terminating at the prior owner's tenure-commencing instrument) governed by the
  materiality rule: current-tenure interims always render in the OnE; prior-tenure
  administrative interims may be Title-only with a connector note; when in doubt,
  include. New **tenure-commencing instrument** definition (arm's-length sale OR
  PR/probate deed OR Certificate of Title OR tax deed) replaces bare "arm's-length
  acquisition" as the chain terminator. Same-day refi-cycle guard repositioned from
  walk-past/demote to annotate-in-place (`vesting_chain_walker` recommendation now
  marks the tenure-commencing row + prior-owner sweep target instead of replacing the
  Prior Vesting citation); same-day ordering rule (chain-later renders higher in the
  newest→oldest table, instrument-number fallback); current-legal-name display rule
  with alias retained in Title name-search list; **search-window floor REMOVED** — the
  exam back-chains as many years as the two-owner chain requires, all
  "outside-search-window" phrasing banned in both reports (2026-06-12 user directive),
  with the sole sourced index-horizon carve-out. Q24 amended; Q26-Q28 added. Current
  Vesting selection (latest instrument even when QCD) and two-owner boundary semantics
  unchanged — confirmed already aligned with Peter's scenarios 1-4.
```

### 2.5 NO search-window floor — ADD as a new top-level rule section
(place after the §2 VESTING section, before §3 OPEN MORTGAGES; applies to BOTH the OnE
and the Title companion)

```markdown
## EXAM DEPTH — NO SEARCH-WINDOW FLOOR (v1.7 — 2026-06-12)

The Two-Owner exam is bounded by OWNERSHIP TENURES, not by dates. There is NO fixed
search-window start (not 2010, not 16 years, not any other floor). The recorder search
goes back as many years as needed to find and cite BOTH tenure-commencing
acquisitions: the current owner's and the prior owner's. A chain that stops at a date
boundary instead of a tenure-commencing instrument is an INCOMPLETE EXAM, not a
finished report.

Banned language — never render in EITHER report (OnE or Title), in any section:
- "date outside of search window" / "outside the search window"
- "outside the search range" / "pre-search-range"
- "beyond the search period" / "prior to the search start date"
- any equivalent phrase implying the exam was restricted by a date boundary

**Sole exception — index-horizon carve-out (approved 2026-06-12):** when an instrument
required by the chain predates the county's digitized Official Records index, the
report states the limit concretely and sourced:
"Official Records online index begins MM/YYYY per [county source]; instrument predates
the digitized index; manual/mail search ordered — engineering ticket #." This is a
statement of the county's documented index horizon, not of our search window — bare
window language remains banned.

When an instrument needed for the chain predates whatever range the initial recorder
query used: WIDEN THE QUERY and pull the document via the recorder's direct-retrieval
endpoint (JumpToInstrumentNumber / JumpToBookPage / doc-id search — proven back to
1996 instruments on Tyler, GREER 2026-06-11). The encumbrance sweep for each owner
runs over that owner's full tenure (acquisition → disposition + buffer), regardless of
how far back the tenure starts — this is the same window logic the prior-owner name
sweep (Q13) already mandates.

The order intake's nominal search range (when one is supplied) is a MINIMUM, never a
ceiling: it may widen the exam, it must never truncate the two-owner chain.
```

---

## 3. Verifier skill changes (`~/.claude/skills/verify-cure-report/`)

### 3.1 `one-report-verification.md` — Check OnE-14 rescore

Replace the OnE-14 scoring table (the v1.6 version FAILs when the OnE "cites the
candidate interim deed" — under v1.7 that's *correct* behavior, so the old gate would
fail compliant reports):

```markdown
| Verdict | Condition (v1.7) |
|---|---|
| 🟢 PASS | `walker.status == "PASS"` AND chain table includes every current-tenure conveyance back to the prior owner's tenure-commencing instrument (prior-tenure interims either rendered or Title-TV3-present with connector note); OR `walker.status == "SAME_DAY_REFI_INTERIM_DETECTED"` AND the interim deed renders as a chain row AND the chain continues to `recommended_walk_target_doc_number` AND that row carries the tenure-commencing annotation |
| 🟠 WARN | `walker.status == "AMBIGUOUS"` AND the chain renders with the inline operator-review note |
| 🔴 FAIL | Chain STOPS at an interim conveyance (walk-target absent from the table); OR any current-tenure conveyance between Current Vesting and the tenure-commencing acquisition is missing from the chain; OR a prior-tenure interim is omitted from the OnE without BOTH Title TV3 presence AND the connector note; OR Prior Vesting still renders as a single block when ≥2 chain-material prior instruments exist in the source chain |
```

Severity stays 🔴 ship-blocker — still the RILEY Pasco regression class, now expressed
as "chain stops at the trust QCD" instead of "trust QCD cited as Prior Vesting".

### 3.2 `directives-checklist.md` — Q12 mirror

Apply the same rescore to the Q12 PASS/FAIL table (it duplicates the v1.6 OnE-14
conditions verbatim).

### 3.3 `SKILL.md` — one-line description update

The OnE-14 summary sentence ("ship-blocker FAIL when the OnE cites the candidate
interim deed instead of the walker's recommended walk-target") becomes: "ship-blocker
FAIL when the §2 Prior Vesting chain omits current-tenure conveyances or stops short
of the walker's tenure-commencing walk-target." Add **OnE-15 (same-day ordering, Q26
mirror — FAIL)** and **OnE-16 (current-legal-name display, Q27 mirror — FAIL)** as
SEPARATE checks. (R-5 decision, 2026-06-12: the draft's folding recommendation is
REVERSED — chain-stop, same-day misorder, and alias leak are distinct failure modes
with distinct severities; folding them into OnE-14 muddies triage, and appending new
check numbers carries no renumbering risk.) SKILL.md check count 14 → 16.

---

## 4. Application checklist + code impact (land as ONE change-set)

- **`vesting_chain_walker.py` — two REQUIRED changes at application time** (the
  draft's "no algorithm change" claim was revised in review):
  1. **Tenure-stop extension (R-2):** PR/probate deeds are already valid never-walk-past
     stops; add Certificate of Title (foreclosure) and tax deed to the same valid-stop
     class so the walker doesn't walk past an involuntary tenure start hunting for a WD
     that doesn't exist.
  2. **Emit the full ordered chain in `to_dict()`** (list of doc numbers, Current →
     prior tenure-commencing, with per-row `tenure: current|prior` and
     `kind: tenure_commencing|interim` tags) — REQUIRED, not optional: Q26's
     deterministic same-day ordering and the R-1 materiality split cannot depend on
     the LLM reconstructing grantor→grantee linkage from raw search rows; that
     reconstruction class is exactly what the sidecars exist to eliminate. Today it
     emits only the recommendation.
- **`pipeline.py:_build_phase1_verifications_block()`** — the SAME_DAY_REFI branched
  reporting-rule prose tells the LLM to *use the walk-target as Prior Vesting*; that
  sentence needs the v1.7 annotate-in-place wording. MUST land in the same change-set
  as the spec edit, or the prompt instructs the retired v1.6 behavior while the spec
  mandates v1.7.
- **Title side — two renames, content otherwise unchanged.** TV3 Chain of Title
  already carries the full chain (it remains the always-complete superset; the OnE
  chain is the materiality-filtered view). At application time: (1) update the
  `CLAUDE.md` content-matrix row "Prior Vesting (immediate prior owner of record)" →
  "Prior Vesting (chain to prior owner's tenure-commencing acquisition, materiality
  rule)" AND the TV3 row's note ("OnE Prior Vesting is the one-row equivalent" is no
  longer true); (2) **rename E3 "Pre-Search-Range Sale History"** → "PA Sale-History
  Back-Chain" in `Title_Examination_Notes_System_Prompt.md`, the OnE spec's Title-only
  item list (line ~472), and the CLAUDE.md matrix — the current section NAME itself
  contains Q28-banned phrasing and would trip the verifier grep on every report.
- **Search-range plumbing (the real source of the 2010 floor).** The banned phrases are
  a symptom; the cause is the fixed date range fed to the recorder search phase. When
  this amendment is applied, audit: per-case pipeline configs / `run_e2e.py`-style
  drivers that hardcode a search start date, and any adapter defaulting to a fixed
  `from_date`. The search phase needs an iterative-deepening contract: initial range →
  if the two-owner chain is incomplete (oldest chain row not arm's-length), widen and
  re-query (or direct-retrieve by instrument #) until both acquisitions are found. The
  Title's "Search Range" metadata line then reports the range actually examined, not a
  nominal default. (CLAUDE.md's "What NOT to do" already bans shipping
  "outside search window" placeholders — this makes the underlying restriction itself
  illegal, not just the phrase.) **File the iterative-deepening contract as a NAMED
  engineering ticket the day this amendment is applied** — Q28 is a ship-blocker from
  day one, and until the contract ships, deep chains are satisfied by manual
  direct-retrieval back-fill (proven on Tyler back to 1996 — GREER 2026-06-11 — and on
  AcclaimWeb Jump endpoints; UNPROVEN on the 15 Landmark Wave-2 counties, so expect
  operator manual work there in the interim).
- **Verifier grep:** OnE-12 (placeholder density) already greps for placeholder
  phrases; add the Q28 banned-phrase list to that grep set, applied to BOTH report
  files, plus the structural check (oldest Prior Vesting chain row must be a
  tenure-commencing instrument). The grep MUST whitelist the approved index-horizon
  carve-out sentence (R-3) so a compliant horizon statement doesn't trip the
  banned-phrase scan.

---

## 5. Resolved questions (Amit review, 2026-06-12)

1. **Scope — RESOLVED (→ R-1 materiality rule).** Chain content in the OnE §2 is
   governed by materiality, not all-or-nothing: QCDs that matter to the examiner
   (GREER Orange class — current-tenure, fee-completing) ALWAYS render in the OnE;
   prior-tenure administrative interims (prior owners' own trust shuffle when we
   acquired from the trust) may be Title-only with a connector note. Doctrine: more is
   good — removing material information is the failure; extra rows the examiner can
   strip before sending.
2. **Tenure boundary without an arm's-length sale — RESOLVED (→ R-2).** The chain
   stops at the prior owner's acquisition whatever its form — arm's-length sale,
   PR/probate deed, Certificate of Title, or tax deed. No need to chain beyond it.
3. **Index-horizon language — RESOLVED (→ R-3).** The proposed sourced
   concrete-statement phrasing is approved as the sole exception to the Q28 ban.

### Non-blocking FYIs for Peter (do not hold application)

4. **Scenario 1 date typo:** expected Current Vesting says recorded **06/01/2026** but
   the underlying deed row says **01/01/2026**. Proceeding on the assumption 01/01 is
   intended; flag to Peter at next touchpoint.
5. **Chain columns:** the xlsx shows Recording Date / Doc Type / Grantor / Grantee;
   the amendment adds Instrument # and OR Book/Page (closers need the cites). Adopted
   under the more-is-good doctrine; FYI to Peter.
