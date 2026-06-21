# Codex Adversarial Review — Tax Plumbing Proposal (v1)

**Date:** 2026-05-15
**Reviewer:** Codex (via `/codex:adversarial-review` plugin)
**Target:** `tax_plumbing_v1.md`
**Verdict:** needs-attention (3 findings: 1 critical orthogonal, 2 high incorporated into v2)

## Verbatim Codex Output

```
Target: working tree diff
Verdict: needs-attention

No-ship: this diff can leak live credentials and the tax phase can either
falsely mark unverified tax data as verified or block the new target counties
before reports can be generated.

Findings:
- [critical] Live TitlePro credentials are in an unignored backup file
  (secrets.json.bak.2026-02-24:2-4)
  The working tree adds an untracked secrets backup containing a real TitlePro
  username/password and service URL. .gitignore only ignores the exact
  secrets.json name, so this backup is visible to git and can be accidentally
  committed or shared with a PR bundle. That exposes document-retrieval
  credentials and requires rotation once distributed.
  Recommendation: Delete the backup from the repo, rotate the exposed
  credential, and expand ignores to cover secrets.json*, *.bak, or an explicit
  secrets-backup pattern.

- [high] Tax validation can bless LLM estimates as verified tax data
  (src/titlepro/automation/pipeline.py:1012-1044)
  The validator treats the input APN as verified even if the artifact omits or
  mismatches it, accepts data_source as a source URL, and accepts
  annual_tax_estimated as the required amount. Combined with
  perform_tax_lookup asking Claude/WebSearch to use Zillow/Redfin or leave
  fields estimated, a non-authoritative or hallucinated JSON payload can
  produce tax_lookup_status.json with status: success, allowing downstream RAW
  reports to present tax as verified.
  Recommendation: Only mark success when data comes from a deterministic
  county tax runner or captured county artifact, require an exact APN match
  from the returned payload, require a real verification URL, and classify
  estimated/WebSearch-only fields as partial or unverified.

- [high] Direct-platform counties still have no runner but are now on the
  blocking path (src/titlepro/automation/pipeline.py:849-917)
  The proposal targets Fresno, Contra Costa, San Bernardino, Riverside, etc.,
  but the implemented pipeline still routes tax lookup through
  perform_tax_lookup, which only does Claude WebSearch and the existing
  multi_county_tax fallback. Direct counties are not registered in
  TAX_COUNTY_REGISTRY; this code only logs that fact, then raises
  WorkflowError when the helper returns no verified data. Because tax_lookup
  was inserted before RAW generation and fetch_tax defaults true, the target
  counties can be blocked from report generation instead of passing through as
  TAX_NO_RUNNER/unverified.
  Recommendation: Implement the proposed fetch_tax dispatcher/Playwright
  recipe runner before enabling this phase by default, or return a
  non-blocking TAX_NO_RUNNER sidecar for unsupported counties and force RAW
  output to say tax is not verified.

Next steps:
- Remove and rotate the leaked credential before any commit.
- Add a fixture proving WebSearch-only/estimated tax JSON cannot produce
  status: success.
- Gate direct-platform counties behind a real recipe runner or downgrade them
  to explicit unverified status.
```

## Disposition

| # | Severity | Finding | Where addressed |
|---|---|---|---|
| 1 | critical | Leaked TitlePro creds in `secrets.json.bak.2026-02-24` | Orthogonal to this build; surfaced to orchestrator. Must rotate creds + add `secrets.json*` / `*.bak` to `.gitignore` before any commit. |
| 2 | high | TAX_SUCCESS validation accepts WebSearch/estimated fields | Hardened in `tax_plumbing_v2_codex_revised.md`: per-field source-host whitelist, exact-APN-match requirement, `_estimated` fields rejected from verification |
| 3 | high | Direct-platform counties block report generation when fetch_tax is True default | Hardened in v2: `TAX_NO_RUNNER` is non-blocking, soft-pass with explicit "not verified" sidecar; hard-fail reserved for TAX_FAILED and TAX_NO_RESULTS only |

v2 proposal: `tax_plumbing_v2_codex_revised.md` (this folder).
