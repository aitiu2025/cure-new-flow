# Miami-Dade Clerk Official Records — Live Portal Probe Report

**Date:** 2026-05-21
**Portal:** https://onlineservices.miamidadeclerk.gov/officialrecords/
**Probe subject:** HAUGABOOK, RACHEL ANNE (one of Tony's two test subjects)
**Artifacts:** `docs/FL/source/miami_dade_probe/` (6 HTML snapshots + 6 PNG screenshots + `findings.json`)

---

## TL;DR — HARD BLOCK on public scraping

**The Miami-Dade Official Records portal has NO public, anonymous name-search.** Every visible entry point on the landing page funnels the user into one of two paid/registered channels:

1. **Register/Login** → `https://www2.miamidadeclerk.gov/usermanagementservices` (account creation + identity verification + payment)
2. **Web API Services** (Developer API) → `https://www2.miamidadeclerk.gov/Developers/Home/MyAccount` (also paid, also requires registration)

The landing HTML is a 32 KB Vue/React SPA scaffold with **zero `<input>` fields, zero `<form>` tags, zero `<select>` elements, and zero references to "search"**. The probe enumerated all visible inputs and clickables — no name-search form is exposed to anonymous traffic.

This matches Tony's stub-config note exactly: *"If we register and pay for exams: Tiered pricing: Min $1 each / up to 5000 exams for $500 (0.10) allows for bypass of any CAPTCHA etc."*

The custom-scraper adapter path that worked for Broward (AcclaimWeb) and the Tyler counties **is not available for Miami-Dade**. A scraper would have nothing to scrape against — the search form simply does not exist outside of an authenticated session.

---

## What the probe actually saw

### A. Landing page (`01_landing.html`, 32,190 bytes)
- URL: `https://onlineservices.miamidadeclerk.gov/officialrecords/`
- Title: `Official Records`
- **`<input>` count: 0**
- **`<form>` count: 0**
- **`<select>` count: 0**
- Mentions of "search": 0 (in raw HTML)
- All visible interactivity is via top-bar links: `Register/Login`, `Contact Us`, `Clerk Home`, `Web API Services`, `Basket` (cart for previously-purchased docs).
- The only visible buttons are `Registering` and `Logging In` — these are **help/FAQ explanations**, not action buttons.

### B. Click trace
The probe attempted to click the most likely "accept/continue" candidate (`Registering`) — the click redirected to `https://www2.miamidadeclerk.gov/UserManagementServices/?hs=or`, confirming this is the account-creation gateway, not a search shortcut.

### C. Post-redirect page (`05_search_results.html`, 19,252 bytes)
- URL: `www2.miamidadeclerk.gov/UserManagementServices/?hs=or`
- This is the account-management portal landing — still no search form, still gated.

---

## Why the SPA shell hides the form (educated guess)

The Vue/React bundle (`/officialrecords/assets/index-Bm5edTMA.css` + a JS bundle of similar name) almost certainly contains the post-auth search form rendered client-side after a successful login. Pre-auth, the only thing the SPA renders is the marketing landing + nav rail. Without an auth cookie or session token, the SPA never mounts the search route.

This is **architecturally distinct** from the FL platforms we've already built / scoped (Tyler, AcclaimWeb, Landmark, etc.) — all of which expose a search form to anonymous traffic and gate downstream image access (not search itself) behind disclaimers, captchas, or paywalls.

---

## Paths forward — three options

### Option 1: Commercial Portal Access ($)
- Register for an account at `https://www2.miamidadeclerk.gov/usermanagementservices`.
- Per Tony: **$1/exam OR $500 prepaid for 5,000 exams ($0.10/exam)**.
- Pros: Official channel. Bypasses any CAPTCHA per Tony. Stable. Likely covered by an SLA. Real subject coverage (the full Miami-Dade record set, including post-2026 records).
- Cons: Money. Identity verification (likely business-entity registration). Per-exam metering — operational cost scales linearly with usage. Need to model the unit economics against the per-report price we charge a client.

### Option 2: Miami-Dade Developer API ($, but probably more efficient)
- Register at `https://www2.miamidadeclerk.gov/Developers/Home/MyAccount`.
- Programmatic access via official API — likely the cleanest integration path if the API supports the operations CURE needs (name search, document metadata, image download).
- Pros: No browser automation, no DOM fragility, no CAPTCHA, far simpler maintenance burden than a scraper. Likely cheaper at scale than the per-exam UI pricing.
- Cons: Same registration + identity-verification hurdles. Unknown pricing — Developer Portal pricing page would need to be checked. Unknown which operations the API exposes.

### Option 3: TitlePro247 / third-party data provider fallback (cost unknown for FL)
- The existing CURE pipeline has a TitlePro247 fallback path for image retrieval (see `docs/TitlePro247 Document Retrieval Selenium Automation Guide.md`).
- **Open question:** does our TitlePro247 subscription cover Miami-Dade FL? The master URL doc (`docs/County_URL_Mapping_CA_OH.md`) only enumerates TitlePro247 URLs for CA/OH — FL coverage is unknown.
- Could investigate alternative third-party providers (DataTree, PropertyShark, ATTOM, etc.) but these are all paid commercial services with their own integration costs.

---

## Recommendation

**Stop adapter-build work on Miami-Dade until Option 1 vs Option 2 is decided.** A custom scraper is not technically feasible against an anonymous SPA with no search form. Both viable paths require a financial decision that's above this engineering scope:

1. **Short-term:** Check the Developer API pricing page (manual visit) — if the API is reasonable, Option 2 dominates: lower operational cost, far less maintenance, no DOM dependency.
2. **Short-term:** Confirm whether TitlePro247 subscription covers Miami-Dade (probably the cheapest fallback if yes).
3. **Decision needed from product/business owner:** Pay $500 for 5,000 exams as a starter and run the math (cost per CURE report vs price per CURE report)?

---

## What was preserved for resumption

When this decision is made and Option 1/2 selected:

- **`miami_dade.json`** has been updated with `access_model: "registration_required"` and `blocked_until: "commercial_access_decision"` so the registry surface still loads, but downstream code can branch on the gate.
- **`miami_dade_adapter.py`** skeleton remains in place. If Option 2 (API) is chosen, the adapter is the wrong abstraction — switch to a new `MiamiDadeAPIClient` class (not a Selenium adapter). Note this in the eventual implementation issue.
- **Probe artifacts** (`docs/FL/source/miami_dade_probe/`) are preserved for future reference — re-run the probe after auth is in place to capture the post-auth search form's selectors.

---

## Updates to follow-up list for Tony

The original Indexing Review's "Adapter implications" (3-field name input, two-click image flow, 3-day image lag, etc.) **all describe what's behind the auth wall**. None of those observations conflict with what we found — they just don't apply until we have an account. Add to the open questions:

- Confirm pricing tier currently in effect: $1/exam? $500 / 5000? Other?
- Confirm whether the Developer API has separate / lower pricing than the UI route.
- Is there a TitlePro247 (or other third-party) channel that aggregates Miami-Dade records without per-search payment to the Clerk?

---

## Probe replay command

```bash
cd /Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X\ Door/CA\ properties/titlePro
source venv/bin/activate
python3 /tmp/miami_dade_probe.py
# Outputs to docs/FL/source/miami_dade_probe/
```
