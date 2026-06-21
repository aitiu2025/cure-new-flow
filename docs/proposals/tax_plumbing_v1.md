# Tax-Lookup Plumbing — Architecture Proposal

## Problem Statement

The TitlePro Step-Wise pipeline has a `tax_lookup` phase that routes every county through `multi_county_tax.lookup_tax()`. That function only handles two platforms (`mbc`, `oc_treasurer`) and falls back to Claude WebSearch for `platform: "direct"` counties. WebSearch can fetch static URLs but cannot:
- Click through disclaimers ("I Acknowledge")
- Fill multi-field forms (Fresno splits APN into 3 inputs)
- Drive interactive lookups (Contra Costa, San Bernardino, San Diego, Riverside)

Result: every California county marked `direct` produces skeleton-only tax JSON. The pipeline silently completes with empty financial fields, and downstream reports either hallucinate or admit "tax not verified."

The master sheet has the recipe in prose ("Acknowledge disclaimer; PPN only — split into 3 fields"). The codebase has Playwright installed and proven. The APN is already in `documents_found.json`. We had everything we needed and never connected the dots.

## Goals

1. **Make `direct`-platform counties work end-to-end** without writing per-county Python scrapers.
2. **Generalize**: adding a new CA county should be a config edit, not a code change.
3. **Strict status semantics**: the pipeline must distinguish "no runner exists" vs "runner ran with empty results" vs "verified data captured."
4. **Survive portal drift**: regression tests catch when a county changes its DOM.
5. **Integrate with the just-shipped CAPTCHA checkpoint system**: any mid-flow CAPTCHA raises `NEEDS_HUMAN_CAPTCHA` and uses the new `needs_human` UI flow.

## Non-Goals

- Solving CAPTCHAs automatically (forbidden per the CAPTCHA proposal).
- Multi-state coverage (CA only for now).
- Tax authentication flows (none of our target portals require login).

## Architecture — 8 Layers

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
    source_url: str = ""
    source_artifact: str = ""
    captured_at: datetime = field(default_factory=datetime.now)
    status: TaxStatus = "TAX_FAILED"
    verified_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    notes: str = ""
    error: str = ""
```

Every scraper — old (`mbc`, `oc_treasurer`) and new — returns this dataclass. Pipeline never touches raw dicts.

### Layer 2 — Declarative Recipes (`config/tax_recipes/<county>.json`)

One file per county. Schema-validated at server startup.

```jsonc
{
  "county": "fresno",
  "platform": "playwright_form",
  "base_url": "https://fcacttcptr.fresnocountyca.gov/",
  "headless": false,
  "min_delay_seconds": 2,
  "navigation_steps": [
    { "action": "goto", "url": "{base_url}" },
    { "action": "click", "selector": "button:has-text('I Acknowledge'), input[value*='Accept']", "optional": true },
    { "action": "split_apn", "format": "XXX-XXX-XX",
      "fields": ["#book", "#page", "#parcel"] },
    { "action": "click", "selector": "input[type='submit'], button:has-text('Search')" },
    { "action": "wait_for", "selector": "table.tax-bill, #secured-bill" }
  ],
  "output_mode": "html",
  "extract": {
    "tax_year":                      { "regex": "(\\d{4}-\\d{2})\\s*FRESNO COUNTY", "scope": "body" },
    "tra":                           { "regex": "TAX RATE AREA\\s*([0-9-]+)", "scope": "body" },
    "assessed_value.land":           { "selector": "td.land-value", "type": "currency" },
    "assessed_value.improvements":   { "selector": "td.improvement-value", "type": "currency" },
    "assessed_value.net_taxable":    { "selector": "td.net-taxable", "type": "currency" },
    "installments[0].amount":        { "selector": "td.inst1-amount", "type": "currency" },
    "installments[0].status":        { "selector": "td.inst1-status", "type": "string" },
    "installments[0].due_date":      { "regex": "Due Date\\s*(\\d{2}/\\d{2}/\\d{4})", "scope": "tr.inst1" },
    "installments[1].amount":        { "selector": "td.inst2-amount", "type": "currency" },
    "installments[1].status":        { "selector": "td.inst2-status", "type": "string" }
  },
  "verification_required": [
    "assessed_value.net_taxable",
    "installments[0].amount",
    "installments[1].amount"
  ]
}
```

Recipe actions supported (small initial set; expand only when a real portal demands):
- `goto` — navigate
- `click` — click selector; `optional: true` skips on missing
- `fill` — text input
- `select` — `<select>` dropdown
- `split_apn` — given APN format + N target fields, splits and fills each
- `wait_for` — wait for selector
- `wait_for_url` — wait for URL pattern
- `extract_field` — single field
- `extract_table` — tabular data

`output_mode` can be `html`, `pdf` (portal returns a PDF), or `mixed`.

### Layer 3 — Generic Runner (`src/titlepro/tax/playwright_runner.py`)

~250 LOC. Pure Playwright. Responsibilities:
- Load recipe, validate against JSON schema
- Open browser (visible/headless per config)
- Execute steps with per-step timeout + retry on transient failures (network, stale element)
- Detect CAPTCHA between steps → raise `CaptchaCheckpointRequired` (integrates with checkpoint registry shipped in CAPTCHA refactor)
- Run extraction
- Save artifacts to case_dir: `tax_<county>_capture.html`, `tax_<county>_screenshot.png`, optional PDF
- Build and return `TaxLookupResult`
- Set status: `TAX_SUCCESS` (all `verification_required` populated), `TAX_PARTIAL` (some missing), `TAX_NO_RESULTS` (page text indicates parcel not found), `TAX_FAILED` (extraction or navigation crashed)

### Layer 4 — Dispatcher (`src/titlepro/tax/__init__.py`)

Single public entry: `fetch_tax(county_id: str, apn: str, owner_name: str, property_address: str, case_dir: Path) -> TaxLookupResult`. Routes:
- `mbc` → wraps existing `mbc_scraper.py` (back-compat — convert old dict to `TaxLookupResult`)
- `oc_treasurer` → wraps existing OC scraper
- `playwright_form` → loads recipe, runs `playwright_runner.run(recipe, apn, case_dir)`
- nothing → `TaxLookupResult(status="TAX_NO_RUNNER", ...)`

### Layer 5 — Pipeline Integration

`pipeline.py:tax_lookup` becomes:

```python
def tax_lookup(self) -> dict:
    if not self.config.fetch_tax:
        return self._write_tax_status_skipped("fetch_tax disabled")
    apn = self.config.apn or self._extract_apn_from_artifacts()
    if not apn:
        return self._write_tax_status_skipped("apn_missing")
    result = fetch_tax(
        county_id=self.config.county,
        apn=apn,
        owner_name=self.config.safe_owner,
        property_address=self.config.property_address,
        case_dir=self.case_dir,
    )
    # write artifacts
    (self.case_dir / f"tax_{self.config.safe_owner}.json").write_text(json.dumps(asdict(result), default=str, indent=2))
    (self.case_dir / "tax_lookup_status.json").write_text(json.dumps({
        "status": result.status,
        "verified_fields": result.verified_fields,
        "missing_fields": result.missing_fields,
        "reason": result.notes or result.error,
        "captured_at": result.captured_at.isoformat(),
    }, indent=2))
    # phase gate
    if result.status in {"TAX_FAILED", "TAX_NO_RESULTS"}:
        raise WorkflowError(f"tax_lookup failed: {result.status} — {result.error or result.notes}")
    if result.status == "NEEDS_HUMAN":
        # registry already populated; signal the workflow
        raise CaptchaCheckpointRequired(...)
    return {"success": True, "status": result.status, "verified_fields": result.verified_fields}
```

`TAX_PARTIAL` and `TAX_NO_RUNNER` pass through with status sidecar — downstream phases see them and the strict guard in `generate_raw_report` enforces "TAX STATUS NOT VERIFIED" phrasing.

### Layer 6 — Testing

- **Replay-mode unit tests** (`tests/unit/test_tax_runner.py`): runner loads recipe, runs against saved HTML fixture (no live network), asserts extracted `TaxLookupResult` matches expected JSON.
- **Recipe schema validation** test for every recipe in `config/tax_recipes/`.
- **Fixture pair per county**:
  - `tests/fixtures/tax/fresno/captured.html` — actual portal response at recipe-creation time
  - `tests/fixtures/tax/fresno/expected.json` — golden `TaxLookupResult`
  - `tests/fixtures/tax/fresno/parcel_not_found.html` — negative case
- **Weekly cron integration test** (long-term): hit live portal with a known-good APN; alert on extraction drift.

### Layer 7 — Recipe-Authoring Tool (follow-up, separate session)

`python -m titlepro.tax.recipe_builder --county <name> --url <portal>` — opens Playwright in interactive mode, records each human action as a recipe step, captures the final HTML, writes `config/tax_recipes/<county>.json` + `tests/fixtures/tax/<county>/captured.html`. Cuts per-county effort from coding to clicking.

### Layer 8 — UI Surface (CURE.html)

Tax phase card additions:
- Status badge: `TAX_SUCCESS` (green) / `TAX_PARTIAL` (yellow) / `TAX_NO_RUNNER` (gray) / `NEEDS_HUMAN` (blue) / `TAX_FAILED` (red)
- "View captured page" link → opens saved artifact
- Per-field checklist (verified vs missing)
- For `TAX_NO_RUNNER`: explicit "No recipe yet for this county" + link to recipe builder

## Implementation Sequencing

### Phase A — Foundation (2-3 hr, single coding agent)
1. `TaxLookupResult` dataclass + JSON schema
2. Wrap existing `mbc` + `oc_treasurer` scrapers to return `TaxLookupResult` (back-compat)
3. Generic `playwright_runner.py`
4. Dispatcher in `tax/__init__.py`
5. Pipeline `tax_lookup` integration (replace current routing)
6. Recipe JSON schema (jsonschema validation)
7. Fresno recipe (`config/tax_recipes/fresno.json`)
8. Live run against AMAYA → produces real `tax_Fresno_AMAYA_Janine.json`
9. Save captured HTML + golden expected.json
10. Replay-mode unit tests

### Phase B — Validation (separate validation/evals agent, ~30 min)
1. Replay tests pass against captured fixtures
2. Schema-validate every recipe JSON at startup
3. Live re-run against AMAYA → confirms idempotency
4. Verify pipeline produces correct status sidecar
5. Verify `generate_raw_report` strict guard fires correctly for `TAX_PARTIAL`
6. Run existing tax-phase tests from this morning's CAPTCHA refactor (should still pass — back-compat)
7. Confirm `TAX_NO_RUNNER` shows up cleanly in UI for an un-recipe'd county

### Phase C — County rollout (separate session, ~30 min/county)
Recipes for Contra Costa, San Bernardino, Riverside, San Diego.

### Phase D — Recipe builder tool (follow-up)
The interactive CLI from Layer 7.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Recipe schema too rigid for some portal | Start with 8 action types; add only when a real portal requires it |
| Portal DOM drift breaks recipes silently | Weekly live integration test; fail loudly when extraction returns zero verified fields |
| Recipe authoring is tedious | Layer 7 builder tool (follow-up) |
| Rate limiting / ToS | `min_delay_seconds` per recipe; document target portal volume; only hit on demand |
| CAPTCHA appears mid-flow | Already handled by the checkpoint registry shipped this morning |
| Existing MBC/OC scrapers break during refactor | Wrap rather than rewrite; preserve their current code paths |

## Backwards Compatibility

- Existing `mbc` and `oc_treasurer` scrapers continue to work; they're wrapped to return `TaxLookupResult`.
- Existing case dirs without `tax_lookup_status.json` continue to load (back-compat branch already in `_tax_lookup_skip_ok`).
- `WorkflowConfig.fetch_tax` and `WorkflowConfig.apn` default to safe values.
- No case-dir migration needed.

## Open Questions

1. Per-county recipe files vs inline in `county_tax_urls.json`? (Recommendation: per-file under `config/tax_recipes/`.)
2. `TAX_NO_RUNNER` strict-fail vs lenient-warn at the phase gate? (Recommendation: lenient initially; tighten when CA counties have full recipe coverage.)
3. Should `output_mode: "pdf"` use our existing PyMuPDF/OCR stack, or treat the PDF as the artifact and rely on regex extraction on body innerText? (Recommendation: PyMuPDF for structure + OCR fallback for image-only PDFs.)
4. Should the runner reuse the checkpoint registry's `make_session_key` semantics so a mid-flow CAPTCHA can land in the same `needs_human` UI as recorder CAPTCHAs? (Recommendation: yes — uniform UX.)

## Success Criteria

1. Fresno tax for APN 455-113-24 produces a valid `TaxLookupResult` with all verified fields populated, end-to-end via the pipeline.
2. Adding Contra Costa, SBD, Riverside, San Diego is recipe-only — no Python edits.
3. The strict guard in `generate_raw_report` correctly emits "TAX STATUS NOT VERIFIED" when status is anything other than `TAX_SUCCESS`.
4. Replay tests cover at least 3 scenarios per county (success, partial, parcel-not-found).
5. Existing MONTOYA/WALTERS cases still load without regression.
