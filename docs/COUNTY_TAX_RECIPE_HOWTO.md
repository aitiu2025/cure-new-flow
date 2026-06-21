# How to add a new county tax-recipe

The county tax pipeline is recipe-driven: `config/tax_recipes/<county>.json`
declares how the generic Playwright runner walks the county portal,
which fields to extract, and what counts as "verified". Adding a new
county is a config + fixture job — no Python changes required (unless
the portal needs a brand-new step type, which is rare).

This pager is the 5-minute path. The full spec lives at
`docs/proposals/tax_plumbing_v2_codex_revised.md`.

---

## The 5 steps

### 1. Probe the portal manually with Playwright

Drive the portal end-to-end against one known APN in a non-headless
browser, captureing every selector/URL you needed. The probe outputs
live under `/tmp/tax_probes/<county>/` (gitignored). Note:

- The exact URL that lands the bill page (the **authoritative source URL**).
- Selectors for the search input, suggestion list, submit button.
- Whether the portal nests data inside iframes (see step 4).
- The exact strings the portal uses for "parcel not found" — those go
  into `no_results_patterns`.

### 2. Save the captured HTML + expected JSON to the fixtures dir

```
tests/fixtures/tax/<county>/
    captured_apn_<apn>.html        # full DOM at the moment of extraction
    captured_apn_<apn>.body.txt    # innerText (easier for grep / regex prototyping)
    expected_apn_<apn>.json        # canonical TaxLookupResult.to_json_dict()
```

The expected JSON freezes the values the recipe MUST produce for the
chosen APN. CI replay tests assert against this fixture.

### 3. Write `config/tax_recipes/<county>.json`

Required keys:

```jsonc
{
  "county": "<canonical county_id, snake_case>",
  "platform": "playwright_form",
  "base_url": "https://...",
  "authoritative_source_hosts": ["host.where.bill.actually.lives"],
  "host_whitelist_mode": "strict",   // or "suffix" — see below
  "navigation_steps": [ /* see schema */ ],
  "extract": { /* dotted/indexed field-paths -> regex/selector */ },
  "verification_required": [ /* field-paths that MUST be populated for TAX_SUCCESS */ ]
}
```

The full schema (allowed actions, types, extras) is in
`src/titlepro/tax/recipe_schema.py`.

### 4. Run replay tests, then a live test

```bash
./venv/bin/pytest tests/unit/test_tax_recipes_new_counties.py -v
```

Then live-test:

```python
from titlepro.tax import fetch_tax
result = fetch_tax(
    county_id="<county>", apn="<known APN>",
    owner_name="LIVE_TEST", property_address="",
    case_dir=Path("/tmp/<county>_live"),
)
assert result.status == "TAX_SUCCESS"
```

### 5. Add the county to `config/county_tax_urls.json`

The dispatcher routes by the `platform` field in
`config/county_tax_urls.json`. If your new county isn't listed,
`fetch_tax` returns `TAX_NO_RUNNER` (non-blocking, sidecar emits the
warning). To enable: add an entry with `"platform": "playwright_form"`.

---

## When to use iframe actions (`enter_frame` / `exit_frame`)

Use them when the bill data lives inside one or more `<iframe>`s in the
portal page. Symptom: `page.locator("…")` returns 0 matches even though
you can see the data in your browser; viewing the page source shows
`<iframe src="…">`s rather than the data.

Syntax:

```json
{ "action": "enter_frame",
  "selector": "iframe[src*='child-host']",
  "url_contains": "child-host.example.com",
  "timeout_ms": 25000,
  "settle_ms": 2000 }
```

- `selector` picks the `<iframe>` ELEMENT in the parent DOM.
- `url_contains` disambiguates when multiple iframes match `selector`.
- After this step, all subsequent `click`/`fill`/`wait_for`/extraction
  runs **inside that iframe's DOM**.
- Stack multiple `enter_frame` actions to descend further (e.g.
  parent -> iframe-A -> iframe-B).
- `exit_frame` pops one level. `exit_frame` with `"to": "top"` pops all
  the way back to the page.
- The runner picks `source_url` from the **innermost active frame**, so
  set `authoritative_source_hosts` to that innermost host, NOT the
  outer page's host.

San Bernardino is the canonical example — see `config/tax_recipes/san_bernardino.json`
and the `_iframe_topology` comment in it.

## When to use `host_whitelist_mode: "suffix"`

Default is `"strict"` (exact host match, case-insensitive). Use
`"suffix"` only when the authoritative portal legitimately rotates
sub-domains and you can't enumerate them up front. Real example: MBC
serves `common1.mptsweb.com`, `common2.mptsweb.com`, `common3.mptsweb.com`
— so the MBC legacy wrapper uses `["mptsweb.com"]` with
`host_whitelist_mode: "suffix"`.

**Don't reach for suffix mode** just because your URL has a `www.` and
the whitelist doesn't. The fix there is to add both `www.foo.com` and
`foo.com` to the whitelist. Suffix mode widens the attack surface
(sub-domain takeovers); use only when needed.

---

## The deferred-county pattern (resolved 2026-05-13 — SBD example)

When a county's portal works but the runner doesn't yet support what
it needs, drop a non-functional recipe that fails fast and document the
limitation inline:

```jsonc
{
  ...,
  "_known_limitation": "Bill data is in a cross-origin iframe; runner needs `enter_frame` support before this recipe can pass."
}
```

The dispatcher returns `TAX_FAILED` (not silently TAX_NO_RUNNER) so
the pipeline surfaces the issue rather than printing a misleading
"no runner configured" warning. When the runner gains the missing
feature, rewrite the recipe and remove the `_known_limitation` field.

San Bernardino's recipe was the first deferred-county example. It was
resolved on 2026-05-13 when `enter_frame`/`exit_frame` shipped: the
recipe now drives two levels of iframe descent (gsg-public-site ->
gsgprod.sbcountyatc.gov -> bill iframe), clicks into Bill Details, and
extracts the canonical values. See `config/tax_recipes/san_bernardino.json`
for the working pattern.

---

## Common pitfalls

- **Dynamic IDs**: typeahead inputs often have IDs like
  `typeahead-input-79095` that change per page-load. Use prefix
  selectors: `input[id^='typeahead-input-']`.
- **`fill` template collision**: don't pass `{apn}` in a `fill.value`
  via `apn=apn`; the runner already puts `apn` into the format context.
  Just use `"value": "{apn}"`.
- **Alternation regex returns wrong group**: if your regex uses `|`,
  the runner now returns the first NON-None capture group (fix shipped
  with the iframe work). Test against the captured `.body.txt` fixture
  to confirm you're capturing what you expect.
- **`Total Taxable Value:` appearing twice**: portals often print the
  label in multiple sections (one populated, one empty). Anchor your
  regex tightly with a `\$` next to the value to avoid empty matches.
- **`www.` mismatch**: strict mode requires exact host. Add both
  `www.foo.com` and `foo.com` to the whitelist (San Diego does this).

---

## Verifying everything is wired up

```bash
./venv/bin/pytest tests/unit/test_tax_*.py tests/unit/test_pipeline_validation.py -v
```

Should report 94+ tests passing, zero failures. Then do a live run
against your county to confirm `TAX_SUCCESS`.
