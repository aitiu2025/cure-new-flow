# Tax-Lookup Plumbing — Architecture Proposal (v2, Codex-revised)

**Status:** Approved-with-revisions by Codex adversarial review (verdict: needs-attention; three findings — two addressed inline below, one orthogonal security issue surfaced separately).
**Predecessor:** `tax_plumbing_v1.md` (this folder)
**Date:** 2026-05-15

---

## What changed from v1 (Codex feedback)

### Finding 1 (CRITICAL, ORTHOGONAL — not in scope for this build)
`secrets.json.bak.2026-02-24` is untracked but visible — contains real TitlePro credentials. `.gitignore` only ignores exact `secrets.json`. **Resolution path (handled out-of-band by orchestrator):** rotate the exposed TitlePro creds, delete the backup file, expand `.gitignore` with `secrets.json*`, `*.bak`. This must happen before any commit lands but is not part of the recipe-runner implementation.

### Finding 2 (HIGH — incorporated)
Today's `_validate_tax_artifact` accepts the input APN as "verified" even when the artifact's APN field is empty or mismatched, accepts `annual_tax_estimated` as the required dollar field, and accepts `data_source: "claude_web_search"` as a valid `source_url`. A WebSearch/Zillow-hallucinated payload can pass as `TAX_SUCCESS`.

**Hardening shipped in this build:**
- `TaxLookupResult.status = TAX_SUCCESS` requires ALL of:
  1. `result.apn` equals the input APN exactly (case-insensitive, after stripping format hyphens). Mismatch → `TAX_FAILED`.
  2. `result.source_url` matches the **county portal whitelist** declared in the recipe (e.g. Fresno only counts if source is `fcacttcptr.fresnocountyca.gov`). Reject `zillow.com`, `redfin.com`, `claude_web_search`, etc.
  3. Every field in `verification_required` is populated with a non-empty, non-`_estimated` value.
- Estimated fields (any key ending in `_estimated`) **never count toward verification.** Their presence in `verified_fields` is disallowed.
- New helper `validate_source_authoritative(source_url, recipe)` runs before status assignment.
- `_validate_tax_artifact` for back-compat (older `mbc`/`oc_treasurer` artifacts) gains the same per-field strict checks.
- Unit test: a mock artifact with `data_source: "claude_web_search"` + estimated fields + a different APN must produce `TAX_FAILED` (not `TAX_SUCCESS`).

### Finding 3 (HIGH — incorporated)
With `fetch_tax: True` default + `tax_lookup` phase wired in + only `mbc`/`oc_treasurer` having runners, every CA county we configured today (Fresno, Contra Costa, SBD, Riverside, San Diego, Sacramento) hard-fails on the tax phase before reports can generate.

**Hardening shipped in this build:**
- `TAX_NO_RUNNER` is **non-blocking by default.** The phase passes with a warning; `tax_lookup_status.json.status = "TAX_NO_RUNNER"`; downstream RAW report receives the explicit "not verified" signal and must include the literal phrase `TAX STATUS NOT VERIFIED`.
- `WorkflowConfig.strict_tax_no_runner: bool = False` — a future global switch to flip lenient → strict once all CA counties have recipes. Set to `True` only when coverage is complete.
- Hard-fail (`WorkflowError`) reserved for:
  - `TAX_FAILED` (runner crashed mid-flow, navigation timeout)
  - `TAX_NO_RESULTS` (county portal explicitly says "parcel not on file") — this is a real signal that downstream report would be wrong
- Soft-pass-with-warning:
  - `TAX_NO_RUNNER`
  - `TAX_PARTIAL` (some fields verified, others missing)
- Mid-flow CAPTCHA → `NEEDS_HUMAN_CAPTCHA` checkpoint (uses morning's registry)

---

## Architecture — 8 Layers (unchanged from v1 except where noted)

### Layer 1 — Canonical Result Schema (`src/titlepro/tax/result.py`)

```python
from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime

TaxStatus = Literal[
    "TAX_SUCCESS",
    "TAX_PARTIAL",
    "TAX_NO_RESULTS",
    "TAX_NO_RUNNER",
    "TAX_FAILED",
    "NEEDS_HUMAN",
]

@dataclass
class TaxLookupResult:
    apn: str
    tax_year: str
    property_address: str
    tra: str = ""
    assessed_value: dict = field(default_factory=dict)
    installments: list[dict] = field(default_factory=list)
    annual_total: float = 0.0
    delinquent: bool = False
    special_assessments: list = field(default_factory=list)
    source_url: str = ""           # MUST match recipe's authoritative_source_hosts on TAX_SUCCESS
    source_artifact: str = ""      # local path to saved HTML/PDF
    captured_at: datetime = field(default_factory=datetime.now)
    status: TaxStatus = "TAX_FAILED"
    verified_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    notes: str = ""
    error: str = ""
```

### Layer 2 — Declarative Recipes (`config/tax_recipes/<county>.json`)

```jsonc
{
  "county": "fresno",
  "platform": "playwright_form",
  "base_url": "https://fcacttcptr.fresnocountyca.gov/",
  "authoritative_source_hosts": ["fcacttcptr.fresnocountyca.gov"],   // ← NEW (Codex finding 2)
  "headless": false,
  "min_delay_seconds": 2,
  "navigation_steps": [
    { "action": "goto", "url": "{base_url}" },
    { "action": "click", "selector": "button:has-text('I Acknowledge'), input[value*='Accept']", "optional": true },
    { "action": "split_apn", "format": "XXX-XXX-XX", "fields": ["#book", "#page", "#parcel"] },
    { "action": "click", "selector": "input[type='submit'], button:has-text('Search')" },
    { "action": "wait_for", "selector": "table.tax-bill, #secured-bill" }
  ],
  "output_mode": "html",
  "extract": {
    "tax_year": { "regex": "(\\d{4}-\\d{2})\\s*FRESNO COUNTY", "scope": "body" },
    "tra":      { "regex": "TAX RATE AREA\\s*([0-9-]+)", "scope": "body" },
    "assessed_value.land":         { "selector": "td.land-value", "type": "currency" },
    "assessed_value.improvements": { "selector": "td.improvement-value", "type": "currency" },
    "assessed_value.net_taxable":  { "selector": "td.net-taxable", "type": "currency" },
    "installments[0].amount":      { "selector": "td.inst1-amount", "type": "currency" },
    "installments[0].status":      { "selector": "td.inst1-status", "type": "string" },
    "installments[0].due_date":    { "regex": "Due Date\\s*(\\d{2}/\\d{2}/\\d{4})", "scope": "tr.inst1" },
    "installments[1].amount":      { "selector": "td.inst2-amount", "type": "currency" },
    "installments[1].status":      { "selector": "td.inst2-status", "type": "string" }
  },
  "verification_required": [
    "assessed_value.net_taxable",
    "installments[0].amount",
    "installments[1].amount"
  ]
}
```

Actions: `goto`, `click`, `fill`, `select`, `split_apn`, `wait_for`, `wait_for_url`, `extract_field`, `extract_table`. Add new actions only when a real portal forces it.

### Layer 3 — Generic Runner (`src/titlepro/tax/playwright_runner.py`)

~250 LOC. Pure Playwright. Responsibilities (unchanged) plus:
- **Source validation:** after extraction, set `result.source_url = page.url` and verify host is in `authoritative_source_hosts` from recipe. Mismatch → `TAX_FAILED` with error explaining the host mismatch.
- **APN echo check:** if recipe's extracted APN doesn't match input APN → `TAX_FAILED`.
- **Estimated-field rejection:** keys ending in `_estimated` excluded from `verified_fields`.
- Mid-flow CAPTCHA → raise `CaptchaCheckpointRequired` (integrates with morning's checkpoint registry).
- Save artifacts to case_dir.

### Layer 4 — Dispatcher (`src/titlepro/tax/__init__.py`)

```python
def fetch_tax(county_id, apn, owner_name, property_address, case_dir) -> TaxLookupResult:
    cfg = load_county_tax_config(county_id)
    platform = (cfg or {}).get("platform")
    if platform == "mbc":
        return _wrap_legacy(mbc_scraper.lookup(...))
    if platform == "oc_treasurer":
        return _wrap_legacy(oc_treasurer.lookup(...))
    if platform == "playwright_form":
        recipe = load_recipe(county_id)
        return playwright_runner.run(recipe, apn, case_dir)
    # NO RUNNER for this county yet
    return TaxLookupResult(
        apn=apn,
        tax_year="",
        property_address=property_address,
        status="TAX_NO_RUNNER",
        notes=f"No tax-lookup runner configured for county {county_id!r}; platform={platform!r}.",
    )
```

### Layer 5 — Pipeline Integration (Codex finding 3 hardened)

```python
def tax_lookup(self) -> dict:
    if not self.config.fetch_tax:
        return self._write_tax_status({"status": "disabled"})

    apn = self.config.apn or self._extract_apn_from_artifacts()
    if not apn:
        if self.config.allow_tax_skip_on_missing_apn:
            return self._write_tax_status({"status": "TAX_SKIPPED", "reason": "apn_missing"})
        raise WorkflowError("tax_lookup: APN missing and allow_tax_skip_on_missing_apn=False")

    result = fetch_tax(self.config.county, apn, self.config.safe_owner,
                      self.config.property_address, self.case_dir)

    # Write both artifacts
    (self.case_dir / f"tax_{self.config.safe_owner}.json").write_text(
        json.dumps(asdict(result), default=str, indent=2))
    (self.case_dir / "tax_lookup_status.json").write_text(json.dumps({
        "status": result.status,
        "verified_fields": result.verified_fields,
        "missing_fields": result.missing_fields,
        "reason": result.notes or result.error,
        "source_url": result.source_url,
        "captured_at": result.captured_at.isoformat(),
    }, indent=2))

    # Phase gate (CODEX FINDING 3: TAX_NO_RUNNER is non-blocking)
    if result.status == "TAX_FAILED":
        raise WorkflowError(f"tax_lookup failed: {result.error or result.notes}")
    if result.status == "TAX_NO_RESULTS":
        raise WorkflowError(f"tax_lookup found no parcel: {result.notes}")
    if result.status == "NEEDS_HUMAN":
        raise CaptchaCheckpointRequired(...)  # registry already populated
    # TAX_SUCCESS / TAX_PARTIAL / TAX_NO_RUNNER all pass through
    return {"success": True, "status": result.status,
            "verified_fields": result.verified_fields}
```

The strict guard in `generate_raw_report` (shipped this morning) already enforces "TAX STATUS NOT VERIFIED" in the RAW md whenever `status != "TAX_SUCCESS"`. No change there.

### Layer 6 — Testing (Codex finding 2 hardening built into tests)

- **Replay-mode unit tests** (`tests/unit/test_tax_runner.py`):
  - Happy path: Fresno fixture HTML → TAX_SUCCESS with all required fields
  - Parcel not found: returns TAX_NO_RESULTS
  - Partial extraction: TAX_PARTIAL
  - **Adversarial test (Codex finding 2):** a payload with `source_url: "zillow.com"`, `annual_tax_estimated: 5000`, APN mismatch → must produce `TAX_FAILED` (not `TAX_SUCCESS`)
  - Mid-flow CAPTCHA: raises `CaptchaCheckpointRequired`
- **Recipe schema validation** for every `config/tax_recipes/*.json` at server startup
- **TAX_NO_RUNNER lenient pass-through test** (Codex finding 3): a county with no recipe entry produces `TAX_NO_RUNNER`, pipeline phase succeeds, status sidecar emits the explicit "not verified" signal
- **Live integration test** (manual trigger, not CI): Fresno against APN 455-113-24 → full TAX_SUCCESS

### Layer 7 — Recipe-Authoring Tool (deferred to follow-up)

`python -m titlepro.tax.recipe_builder --county <name> --url <portal>`. Out of scope for this build.

### Layer 8 — UI Surface (CURE.html)

Tax phase card displays:
- Status badge: `TAX_SUCCESS` (green), `TAX_PARTIAL` (yellow), `TAX_NO_RUNNER` (gray "No recipe yet"), `TAX_FAILED` (red), `NEEDS_HUMAN` (blue)
- "View captured page" link → opens saved HTML/PDF artifact
- Per-field verified-vs-missing checklist

---

## Implementation Phases

### Phase A — Foundation (coding agent, 2-3 hr)
1. `TaxLookupResult` dataclass + JSON schema
2. Wrap existing `mbc` + `oc_treasurer` scrapers to return `TaxLookupResult` with strict source/APN validation
3. Generic `playwright_runner.py` with all hardening from findings 2 & 3
4. Dispatcher in `tax/__init__.py`
5. Pipeline `tax_lookup` rewrite with non-blocking `TAX_NO_RUNNER`
6. Recipe JSON schema + validator
7. Fresno recipe (`config/tax_recipes/fresno.json`)
8. Live run against AMAYA → produces real `tax_Fresno_AMAYA_Janine.json` with TAX_SUCCESS
9. Save captured HTML + golden expected.json
10. Replay-mode unit tests (including adversarial tests from Codex finding 2)
11. TAX_NO_RUNNER lenient test (Codex finding 3)
12. Restart server + verify Fresno run end-to-end

### Phase B — Validation/Evals (separate eval agent, ~45 min)
1. All unit tests pass (target: 50+ tests, zero failures)
2. **Specifically verify the Codex findings are closed:**
   - Inject mock artifact with Zillow source + estimated fields + APN mismatch → must NOT produce TAX_SUCCESS
   - Inject mock county-config with no recipe → pipeline phase must pass-through as TAX_NO_RUNNER
3. Live Fresno re-run for AMAYA → idempotent, same result
4. Verify pipeline produces correct `tax_lookup_status.json`
5. Verify `generate_raw_report` strict guard fires for TAX_PARTIAL / TAX_NO_RUNNER
6. Re-run existing tax-phase tests from morning's CAPTCHA refactor (back-compat)
7. Confirm `TAX_NO_RUNNER` renders correctly in UI for un-recipe'd county
8. Confirm CAPTCHA-mid-flow path uses the morning's checkpoint registry

### Phase C — County rollout (future session)
Recipes for Contra Costa, San Bernardino, Riverside, San Diego.

### Phase D — Recipe-builder CLI (future session)

---

## Success Criteria

1. Fresno tax for APN 455-113-24 produces `TaxLookupResult(status="TAX_SUCCESS")` with all `verification_required` fields populated, source verified as fcacttcptr.fresnocountyca.gov.
2. Adding any new CA county is config-only (recipe + fixture). No Python edits.
3. Strict guard in `generate_raw_report` enforces "TAX STATUS NOT VERIFIED" for non-success.
4. Replay tests cover 4 scenarios per county: success, partial, no-results, adversarial (zillow/estimated/mismatched APN).
5. Existing MONTOYA/WALTERS cases pass without regression.
6. Codex findings 2 and 3 are closed (adversarial tests prove it).

## Backward Compatibility

- `mbc` and `oc_treasurer` scrapers wrapped, not rewritten.
- Existing case dirs without `tax_lookup_status.json` continue to load via back-compat branch.
- `WorkflowConfig.fetch_tax`, `apn`, `strict_tax_no_runner`, `allow_tax_skip_on_missing_apn` all default safely.
- No case-dir migration.

## Out-of-Scope (Surfaced Separately)

- **Critical credential rotation** for `secrets.json.bak.2026-02-24` (Codex finding 1). Orchestrator handles outside this build.
