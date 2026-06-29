---
name: state-contamination-assertion
description: Pipeline-level diagnostic assertion to detect the [N, 0, 0, 0, 0, 0] adapter state-contamination signature
type: project
originSessionId: 3c98fcd9-98fe-4b81-b8f0-026a72f93e20
---
The Broward Test Review (Tony Roveda, 2026-05-22) surfaced two production reports (SIMMONS, ANAND) where the recorder-search adapter silently shipped partial data. Inspecting `search_results.json` revealed both cases had identical pattern:

```
SIMMONS: [12, 0, 0, 0, 0, 0]   # only SIMMONS,SHANTELL Grantor returned results
ANAND:   [16, 0, 0, 0, 0, 0]   # only ANAND,RISHI G Grantor returned results
```

**Why:** Per Agent B (codex:codex-rescue diagnostic agent, 2026-05-22), `extract_results()` in `acclaimweb_adapter.py` hardcoded Kendo CSS selectors (`tr.k-master-row, tr.k-alt`) but Broward emits Telerik (`tr.t-alt`). Strategy 2 fallback only succeeded on run 1 because `return_to_search` didn't actually navigate back — stale prior rows satisfied the next run's wait predicate, and `extract_results` read them before the new dataBound fired. The result was a 1/6 search that the pipeline shipped without raising.

**Fix shipped 2026-05-22:** Broadened CSS selectors to cover both Telerik and Kendo families. `return_to_search` now force-navigates via URL. Pipeline NEEDS the diagnostic assertion below to ensure this regression cannot re-occur silently.

**Why:** the pipeline at `src/titlepro/automation/pipeline.py:_run_search_with_recorder` (lines 760-843) currently has no per-search-count sanity check. A `[N, 0, 0, 0, 0, 0]` pattern is mathematically near-impossible for legitimate independent searches (the chance that both Grantee-roles and the entire second name return zero by chance is vanishingly small).

**How to apply:** after `_run_search_with_recorder` populates `search_runs`, add:

```python
counts = [r["result_count"] for r in search_runs]
if (
    len(counts) >= 3
    and counts[0] > 0
    and all(c == 0 for c in counts[1:])
):
    raise WorkflowError(
        f"StateContaminationDetected: search counts {counts} match the "
        f"[N, 0, 0, 0, 0, 0] signature. The first search succeeded but every "
        f"subsequent search returned zero — almost certainly an adapter form-"
        f"reset bug. Refer to docs/FL/source/broward_state_bug_repro/ for the "
        f"reproducer and Tony's review findings before re-running."
    )
```

This is a HARD ASSERTION — silent partial data is worse than a loud failure.
