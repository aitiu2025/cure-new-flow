# CURE Exam Methodology Guide

**Source:** Tony Roveda — `docs/FL/source/2026-05-21_CURE_General_Search_Notes_and_Examination_Suggestions.docx` (2026-05-21)

**Imported to this repo:** 2026-05-21

**Status:** Implementation reference — captures the abstractor's mental model + working-smarter shortcuts that CURE should replicate. Apply when designing adapters, prompt logic, and report generation.

> **Scope note:** This guide is **cross-cutting and state-agnostic** — it documents the underlying human-abstractor workflow that drives every CURE exam regardless of jurisdiction (CA, FL, OH, future states). It complements platform-specific guides like `docs/FL/FL_Platform_Examination_Guide.md` (per-platform UI behavior) and `docs/CA_Implementation_Update_2005.md` (CA adapter rollout status).

---

## CURE Goal

To act as the human completing a 2 Owner Title Exam, known as an Ownership and Encumbrance Report (O&E).

Historically, title exams take approximately 24-48 hours to complete because the human abstractor must "pull" multiple documents — sometimes a very large volume of documents (due to common names) — to confirm/identify which documents pertain to their specific transaction.

While there are tricks of the trade, there is **one hard-and-fast rule** that must be followed:

> The exam must be completed by reviewing the County's official public records for our transaction, including the **land records**, **judgment liens**, and **tax roll**. The only exception to this rule is if a "pay-for" title plant is used or an approved public record legal aggregator — **none are currently approved for CURE's purposes**.

There are methods used by human abstractors that allow them to work smart and not hard. **These same methodologies should be implemented in some fashion by the L & SLMs** (large + small language models). The following suggestions should be implemented to reduce the need to pull ancillary documents that are not pertinent to our transaction.

---

## What is provided by the Client to complete the Search

### Borrower Names
- Party One
- Party Two
- Potentially more

### Property Address
- Street Address
- City
- State
- County
- Occasionally and rare: Parcel Number (UPI / APN / etc.)

---

## Recommended Steps to complete the Exam

> The following is written through the lens of a human title examiner searching a County's Grantor/Grantee Index platform.

---

### Step 1: Identify the start date of when our subject party took ownership of the property

**Search Criteria:**
- **Document Type:** DEED
- **Name Search**
- All party names should be run and compared.
- First name search run should be run **as provided by the client order form**. Most abstractors will run the name search multiple times, taking into consideration name variances:
  - With middle initial/name
  - Without middle initial/name

The abstractor will then **cross-reference the output**, eliminating duplicates and/or results where names clearly do not match our transaction criteria.

The abstractor will compile their list of document images that need to be "pulled" and reviewed, keeping in mind that our transaction may have **multiple Deed entries** (to be explained later).

The abstractor will eyeball each document, confirming it/they match the following:
1. **First:** Address and Parcel Number (if provided in exam request)
2. **Second:** Party Names

> ⚠️ The initial Deed may not include all the current names on our title exam order request from client. This is due to a myriad of different reasons, which include but are not limited to:
> - Party 1 bought as a single person. Was later married and spouse was added later (via Quitclaim Deed).
> - Divorce, Death, add or remove family/friends/investors, etc.

**Once the Initial Transfer Deed (Warranty Deed) is identified, the abstractor has a true "Starter Date."** Any document, name, etc., can be ignored prior to this date, with one exception: **the search should be run for "Both" the Grantor and Grantee.**

#### Two Owner Exams require us to pull the prior deed

The abstractor will look at the Transfer Deed and identify:
- Grantor Names
- Parcel Number

The abstractor will then run the **Grantor Names** with an open start date, and end date being the date where they sell/transfer the property to our party.

Once the abstractor identifies the Prior Deed, the image is pulled and the abstractor notes its Grantor/Grantee Names, recording information, document type, etc.

This process yields:
- Copy and information of **Prior Ownership Deed** completing the Two-Owner piece of the exam
- **Start Date** for examining our Party for encumbrances
- The **Parcel Number**

#### Multiple post-Warranty deeds (Quitclaims, etc.)

The abstractor may identify multiple Deeds of record that were filed **AFTER** the initial Warranty Deed. Most often these are **Quitclaim Deeds**.

> A Quitclaim Deed provides notice of a low- to mid-level change in the property's ownership status due to marriage, divorce, death, or agreed addition or subtraction of the parties.

These documents need to be **shown on the report in chronological order (Newest to Oldest)** including the prior ownership deed.

**To complete this, CURE will need to implement NLP.** CURE will need to make multiple calls/searches to the County index to complete this, building the raw data (yellow) abstract.

---

### Step 2: Name Search to identify Encumbrances on Property and subject names

The name search of **ALL parties listed on the MOST RECENT recorded Deed/Quitclaim Deed**. These are the true owners of our subject property. >95% of the time, these names will match our search exam order. But occasionally they may not. The search should be run for **"Both" Grantor and Grantee**.

#### Scenario Example

- Our client Search Request lists only Peter Bodonyi.
- After pulling the current ownership deed, we have determined that the property is owned by Peter **AND** Rae Bodonyi.
- **Both names must be run.** Why?
  - The entire purpose of running these exams is to provide assurance that the lender will be in their agreed-upon lien position and that there are no intervening liens that could be in front of them in the event of foreclosure.
  - We are responsible for providing any potential liens or judgments that may be attached to the property.

In this example:
- If we only ran Peter Bodonyi and he is clean, the client would assume they were in (e.g.) 2nd position for this new Home Equity loan.
- But what if **Rae Bodonyi had taken out her own Home Equity loan** on the property?
- If the Bodonyis went into foreclosure, the lender for Peter would expect to collect the balance on his loan during the foreclosure, only to find out that Rae's loan is in front of them — raising the realistic possibility that there will be no money left to pay Peter's loan balance, resulting in a **claim/lawsuit against CURE**, which we would then be liable for.

> **This is why we need to look at BOTH the search request for names AND the names listed on the most recently filed Vesting Deed.**

#### Reviewing the result set

Now that we have run all the names, the indexing platform — using the identified Start Date — will return a host of documents for examination. Depending on the last name's ethnicity, the returns vary, but due to the start date, the list will be markedly shorter.

Depending on the platform's functionality, the abstractor will review the results and determine which records are specific to our property or party. This includes but is not limited to review of:

**Pulling the image to examine:**
- Names
- Parcel Numbers
- Address
- Legal

This must be completed for **all** names identified.

**CURE will need to use NLP to complete this.** Once again, this requires multiple entries into the County platform, extracting the data, and depositing it into the raw exam (yellow) abstract.

---

### Step 3: Parcel Number Search (Option)

Depending on the functionality of the County indexing platform, an abstractor will run a **quick Parcel Number search as a backup** and compare it against the name search.

One could argue that a search by parcel number could be conducted **prior** to the name search. But:

> ⚠️ **Name searches must ALWAYS be run** — not all documents are indexed to the Parcel Number. For example, a simple unpaid plumber may file a **mechanics lien** on the person and property address but is not required to include the parcel number on the lien. As a result, the document would only be indexed by the name, not the property.

---

## Final compilation

Assuming the abstractor has pulled their document images for all documents they know or suspect are specific to our property or party, they are done with the platform and will begin their **deep review of the pulled images**, crossing out on their notepad any documents that do not pertain to our transaction.

When complete, they will have the following data and supporting images:

- **Deed Ownership transition** from Newest to Oldest, including Prior Ownership deed
- **Open Mortgages** (only)
- Any **Judgments** against property or names
- **Exhibit A** Full Legal description pulled from the Vesting Deed (Short Legals are unacceptable by client)

> **Tax explained on a separate document.** (See `docs/COUNTY_TAX_RECIPE_HOWTO.md` for the CURE tax-recipe implementation.)

---

## Implementation crosswalk

Each abstractor tip below is mapped to the CURE component that owns it. Use this table when designing new adapters, prompt revisions, or pipeline phases.

| # | Abstractor tip | CURE component(s) | Notes |
|---|---|---|---|
| 1 | Run name search **as provided** + with middle initial variant + without | Adapter `name_search` phase (per-county config) + pipeline orchestrator | Multi-pass name search; cross-reference + dedupe in post-processing |
| 2 | Dedupe results across name variants, eliminate non-matches | Pipeline post-search step (between `search` and `download`) | NLP-driven match scoring; key on address + parcel + names |
| 3 | Match each pulled doc against (a) address/parcel FIRST, (b) party names SECOND | LLM analysis phase (`Title_Examination_Notes_System_Prompt.md`) | Priority order matters — address/parcel is the high-precision signal |
| 4 | Locate **Initial Transfer Deed (Warranty Deed)** to establish "Starter Date" | LLM analysis phase + report builder | Drives the search-window start date used in Step 2 |
| 5 | Run search for **"Both" Grantor and Grantee** | Adapter config (`party_type=Both/All/Either` per platform) | Defaults differ by platform — see `FL_Platform_Examination_Guide.md` cross-platform tips |
| 6 | Pull **Prior Deed** using Grantor names + end-date = transfer-to-our-party date | New pipeline sub-step: "prior_deed_lookup" | Currently implicit in one-shot prompt; consider explicit gated phase |
| 7 | Capture **post-Warranty Quitclaims** chronologically (newest → oldest) | Report builder (chain-of-title section) | Already mostly handled in `Title_Examination_Notes_System_Prompt.md`; verify ordering rule |
| 8 | Step 2: name search **of ALL parties on MOST RECENT recorded deed** (not just client-provided names) | LLM analysis → re-trigger adapter name_search | Critical: party set must be **derived from the deed**, not trusted from the order form |
| 9 | Run encumbrance search **for both spouses / co-owners** (Peter + Rae Bodonyi scenario) | Adapter loop in `name_search` phase | One search per derived party; liability-driving rule |
| 10 | Use the **Starter Date** to narrow Step-2 result set | Pipeline orchestrator passes `start_date` to adapter | Markedly shorter result list, lower CAPTCHA + 2Captcha cost |
| 11 | Pull image to verify Names / Parcel / Address / Legal on every candidate doc | Adapter `download` phase + LLM extraction | Already shipped; ensure extraction returns all four fields for the chain-of-title builder |
| 12 | Parcel-number search as **backup** (never primary) — because mechanics liens often have no parcel | Adapter `parcel_search` phase, gated behind name_search | Some FL platforms expose Parcel-ID search (Landmark, OnceCare, DueProcess, Tyler Advanced); Clericus does NOT — see FL guide |
| 13 | Pull **ancillary docs only when needed** (work-smart shortcut) | Adapter `download` phase + dedup logic | Avoid blanket-downloading the full result set; filter on address/parcel/name match scoring before pulling images |
| 14 | Final exam outputs: chain-of-title, open mortgages only, judgments, full Exhibit A | Report builder + serialize_reports phase (MD/HTML/PDF/JSON/XML) | Already covered by `serialize_reports` and the title-exam-notes prompt |
| 15 | **Tax is a separate document** | `tax_lookup` pipeline phase + `docs/COUNTY_TAX_RECIPE_HOWTO.md` | Already shipped (8/8 CA recipes); FL Grant Street pattern reusable for Miami-Dade et al. |

---

## Key principles for L/SLM design

Tony's overarching framing — distilled for adapter + prompt authors:

1. **The exam is reviewed against official public records, not third-party plants.** No legal aggregators are CURE-approved. Every search must hit the county's indexing platform directly.
2. **Two-owner exams are inherently multi-pass.** A single adapter call is rarely sufficient — plan on at least: (a) deed search for our parties, (b) prior-deed search using grantor names, (c) encumbrance search for derived owners.
3. **NLP / LLM analysis is the bridge between raw index hits and the final report.** Tony explicitly calls out NLP for chain-of-title reconstruction (Step 1) and for encumbrance filtering (Step 2). The LLM is the abstractor's "eyeball" + "notepad."
4. **Name searches are non-negotiable.** Even when parcel-search is available, name search must always run — mechanics liens and other person-indexed encumbrances will be missed otherwise.
5. **Liability is a real cost of skipping co-owner searches.** The Bodonyi scenario is not hypothetical — it's the worked example Tony chose specifically because it's how CURE could get sued.

---

## Related docs

- `docs/FL/FL_Platform_Examination_Guide.md` — platform-by-platform UI behaviour (Landmark, Tyler, OnceCare, DueProcess, Clericus) — apply Steps 1-3 above through each platform's specific UI conventions.
- `docs/CA_Implementation_Update_2005.md` — CA adapter rollout status and immediate next steps; the methodology in this guide is what those adapters are operationalizing.
- `docs/implementation_references/2Captcha_reCAPTCHA_Integration.md` — sibling implementation reference for autonomous CAPTCHA solving (Tyler counties).
- `docs/COUNTY_TAX_RECIPE_HOWTO.md` — companion tax-recipe documentation (Step 3's "tax explained on separate document").
- `Title_Examination_Notes_System_Prompt.md` (repo root) — the LLM prompt that operationalizes Steps 1-2 against the raw download set.
- `README_BEFOREImplementing.md` (repo root) — Step-Wise pipeline contract; the methodology phases in this guide map onto pipeline phases.
