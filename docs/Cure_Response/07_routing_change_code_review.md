# Code Review — FL Download Routing + Recipe-Style Config (2026-05-26)

## Executive verdict

**SHIP WITH FIXES.** The state-default routing is sound conceptually and the Tyler `download_pdf` flow looks reasonable for the Orange FL portal verified in testing. However, there are at least two **ship-blockers**: (1) `Dict[str, Any]` return annotation references `Any` which is **not imported** — the module will `NameError` at import time the first time `download_pdf` is referenced via reflection, and worse the test scaffold for `download_pdf` is **entirely absent**; (2) the much-touted `doc_image_url_pattern` "recipe-style config" is **dead code** — `download_pdf` scrapes the URL straight from the `pdfJsUrl` JS assignment and never consults `self._doc_image_url_pattern`. Several backwards-compat hazards lurk in the silent `except: pass` rehydration and the missing sidecar cleanup. Fix the blockers, address the 🟡 items, then ship.

---

## Findings (in severity order)

### 🔴 #1 — `Any` used in type hint but never imported
**File / line:** `tyler_http_adapter.py:57`, used at line 665
**Category:** Bug
**What's wrong:** `download_pdf` is annotated `-> Dict[str, Any]:` but the file's `from typing import` line only pulls `Dict, List, Optional`. There is no `Any`.
**Why it matters:** Under `from __future__ import annotations` this becomes a deferred-evaluated string and survives import — but any tool that resolves annotations (Pydantic, FastAPI, `get_type_hints`, IDE inspectors, mypy --strict) will raise `NameError: name 'Any' is not defined`. The test suite does not currently exercise this path, so it slipped through.
**Recommended fix:** Add `Any` to the `from typing import` line. Verify the file head still says `from __future__ import annotations` (if it does, runtime is safe; static analysis still breaks).

---

### 🔴 #2 — `doc_image_url_pattern` config field is dead code
**File / line:** `tyler_http_adapter.py:138-141` (init) vs `tyler_http_adapter.py:697-715` (download_pdf)
**Category:** Documentation / Architecture
**What's wrong:** The init stores `self._doc_image_url_pattern` with default `"document-image-pdfjs/{doc_id}/{uuid}/{doc_number}.pdf?…"`, but `download_pdf` **never references this attribute**. It scrapes the literal URL out of the `pdfJsUrl = '…'` JS assignment via regex on line 699-702. The whole "recipe-style tokens" mechanism is unused.
**Why it matters:** This is the centerpiece of the change description — and it doesn't do anything. The promised abstraction (per-county pattern overrides for Broward `{token}`, Hillsborough `{ID}`) cannot work because the code doesn't consult the config field. New counties that override `doc_image_url_pattern` in JSON will see no behavior change.
**Recommended fix:** Pick one approach. EITHER (a) delete the field and the docstring about it — be honest that this adapter relies on scraping `pdfJsUrl`; OR (b) actually use the pattern: when `pdfJsUrl` regex misses, fall back to formatting `self._doc_image_url_pattern.format(doc_id=…, uuid=…, doc_number=doc_num, index=1)`. The latter is more robust because tenants that hide the JS variable still work. Note: extracting `uuid` separately would also be needed.

---

### 🔴 #3 — No test coverage for `download_pdf`
**File / line:** `tests/unit/test_tyler_http_adapter_scaffold.py` — entire file
**Category:** Testability
**What's wrong:** The scaffold tests cover `warm_session`, `perform_search`, `extract_results`, sitekey scraping, captcha-solver injection, and registry routing. There is **zero coverage** of `download_pdf`: no test mocks the detail-page GET, no test exercises the `pdfJsUrl` regex, no test verifies the `%PDF` magic-bytes guard, no test covers the missing-`doc_id` failure path, no test exercises the relative-vs-absolute URL branch.
**Why it matters:** This is brand-new code that runs against real money (2Captcha costs ~$3/1000 solves) and writes binary files to disk. Shipping untested. A single regex tweak will break in production unnoticed.
**Recommended fix:** Add minimum 5 unit tests:
1. `test_download_pdf_happy_path_writes_file_with_pdf_magic` (mock session, `%PDF` content)
2. `test_download_pdf_returns_error_when_doc_id_missing_from_cache`
3. `test_download_pdf_returns_error_when_pdfjsurl_not_in_detail_html` (e.g., FL Ch. 2002-302 hidden filings)
4. `test_download_pdf_returns_error_when_response_is_html_not_pdf` (subscription-wall scenario)
5. `test_download_pdf_handles_relative_pdf_path` (path starts with `/`, with `http`, and bare)

---

### 🟡 #4 — Sidecar JSON rehydration silently swallows all errors
**File / line:** `pipeline.py:918-923`
**What's wrong:**
```python
try:
    ids = json.loads(sidecar.read_text(encoding="utf-8"))
    if isinstance(ids, dict):
        adapter._doc_id_by_number = ids
except Exception:
    pass
```
A corrupted, truncated, or empty `recorder_internal_ids.json` will silently fall through to `download_pdf` calling `self._doc_id_by_number.get(doc_num)` on an empty/missing dict, returning an opaque "no Tyler doc_id cached for instrument X" error.
**Why it matters:** The operator gets a misleading error: "run perform_search first" — but they just did. The real cause (JSON parse failure) is hidden.
**Recommended fix:** Log the parse failure to `print(f"[download] WARNING: recorder_internal_ids.json corrupt: {exc}")`. Better: re-raise as a `WorkflowError` since the download phase cannot succeed without it.

---

### 🟡 #5 — Sidecar write happens too late — exception between search end and write loses cache
**File / line:** `pipeline.py:822-842`
**What's wrong:** The sidecar is written **after** `documents_found.json` is sorted and persisted, after the search loop completes. If `_sortable_recording_date` or `ordered_documents` construction throws (KeyError on missing `recording_date`, type error, etc.), the search appears to have failed even though Tyler returned data — and the in-memory `_doc_id_by_number` cache is lost. Resume from checkpoint would re-run the search, costing another 2Captcha solve.
**Why it matters:** Captcha costs real money. Cache loss = forced re-solve.
**Recommended fix:** Move the sidecar write to **immediately after the search loop** (before the sort/persist), or wrap the persist in `try/finally` with the sidecar write in `finally`. Even simpler: write the sidecar progressively after each search run, not once at the end.

---

### 🟡 #6 — Stale sidecar from prior run will poison fresh searches
**File / line:** `pipeline.py:822-842`
**What's wrong:** Nothing cleans up `recorder_internal_ids.json` at search-phase start. If a user runs the workflow with `resume=False` or manually clears `documents_found.json` but leaves the sidecar, the rehydration will load **stale `doc_id` values from the prior run**, then `download_pdf` will GET the wrong detail page on the wrong portal session.
**Why it matters:** Wrong PDFs land in the case folder with correct filenames. Silent data corruption.
**Recommended fix:** At the top of `_run_search_with_recorder` (or wherever the search phase starts), unlink `recorder_internal_ids.json` if it exists. Also add it to `.gitignore` (currently NOT in `.gitignore` — verified via repo grep).

---

### 🟡 #7 — `_should_use_titlepro()` defaults to CA when `state` is missing
**File / line:** `pipeline.py:885-891`, `pipeline.py:335`
**What's wrong:** `from_dict` defaults `state="CA"` if absent. `_should_use_titlepro` does `(self.config.state or "CA").upper() == "CA"`. So a workflow config without explicit `state` AND without explicit `use_titlepro` lands on TitlePro247 routing.
**Why it matters:** Mostly desirable (preserves CA behavior), but if an FL user forgets to set `state="FL"` in their workflow config they get baffling TitlePro247 attempts against FL doc numbers (which will fail in an unhelpful way: TitlePro247 doesn't recognize FL counties). The CA default is sticky and silent.
**Recommended fix:** Either (a) make `state` required in `from_dict` (raise on missing) — best practice; or (b) log the resolution clearly: `print(f"[download] state={state} use_titlepro={result} (explicit={config.use_titlepro is not None})")`. There IS a log on line 957 but it doesn't say which signal won.

---

### 🟡 #8 — `warm_session` can silently re-solve captcha and double-spend on 2Captcha
**File / line:** `pipeline.py:925-929`, `tyler_http_adapter.py:678` (in download_pdf)
**What's wrong:** The pipeline's `_download_via_adapter` instantiates a **fresh** adapter — `self._session_warmed` is False — then calls `adapter.warm_session()`. That re-solves the disclaimer captcha against 2Captcha. Cost: ~$0.003/solve. For a 50-document case running search + download, this is 2× the captcha cost vs. running search-and-download in one process. Furthermore, in `download_pdf` itself, line 678 ALSO calls `warm_session()` if not warmed — which is OK now because `_download_via_adapter` warms it first, but it's defense-in-depth that could mask the cost.
**Why it matters:** Cost. The legacy TitlePro247 path doesn't have this problem because it's a different portal entirely.
**Recommended fix:** Persist the disclaimer-accepted session cookies between phases. Add `pickle.dump(adapter.session.cookies, sidecar_cookies_path)` after warm_session in the search phase; `pickle.load` in `_download_via_adapter` before deciding whether to re-warm. If cookies are still valid, set `adapter._session_warmed = True` and skip the warm step. **Caveat:** verify cookies haven't expired before trusting — fall back to re-solve on 401/redirect-to-disclaimer.

---

### 🟡 #9 — `_doc_id_by_number` cache schema is not future-proof
**File / line:** `tyler_http_adapter.py:759-760, 779-780`, `pipeline.py:835-842`
**What's wrong:** The cache is `Dict[str, str]` — instrument → opaque ID. Tyler has TWO IDs: `doc_id` (used to fetch detail) and `uuid` (embedded in pdfJsUrl). Currently we cache `doc_id` only and re-scrape `uuid` from the detail HTML. Other portals (AcclaimWeb) have token + cache-hash. Hillsborough has `{ID}`.
**Why it matters:** First time we hit a county that needs more than one ID per doc, we'll have to either (a) add a SECOND sidecar (`recorder_internal_ids_v2.json`) or (b) breaking-change the schema. The for-loop on `pipeline.py:835-837` even hints at multiple cache_attrs but only declares one.
**Recommended fix:** Change schema to `Dict[str, Dict[str, str]]` — instrument → `{"doc_id": "...", "uuid": "...", "token": "..."}`. Bonus: also store `recording_date` and `doc_type` for offline validation. Cost: 5 LOC change in `extract_results`, 1 line in `download_pdf`.

---

### 🟡 #10 — `download_pdf` error messages leak internal portal vocabulary
**File / line:** `tyler_http_adapter.py:704`, surfaced via `pipeline.py:942`
**What's wrong:** Error message says `"pdfJsUrl not found in detail page"`. That's a Tyler-internal JavaScript variable name. Operators (not engineers) will read this in the UI and have no idea what it means.
**Why it matters:** Minor leakage of internal portal details. Not a security issue per se (Tyler's portal is public), but a UX issue — a CURE operator's job is title research, not Tyler reverse-engineering.
**Recommended fix:** Translate to operator-language: `"PDF download URL missing from county portal detail page (doc may be hidden/restricted, e.g. FL Ch. 2002-302). Verify the document is publicly downloadable on the live portal."` Pair with a debug-mode `pdfJsUrl` log for engineers.

---

### 🟡 #11 — `_download_via_adapter` creates a fresh adapter per document, not per case
**File / line:** `pipeline.py:893-942` (called inside the `for document in documents` loop in `download()`)
**What's wrong:** Inside `download()` the `_download_via_adapter` call is made per-document. Each call calls `get_recorder(...)`, builds a fresh `TylerHTTPAdapter`, rehydrates sidecar, calls `warm_session()`. For N documents that's N captcha solves.
**Why it matters:** Catastrophic cost amplification. For a 50-doc case at $0.003/solve = $0.15/case vs. $0.003/case. Multiplied across all FL cases.
**Recommended fix:** Hoist the adapter instantiation out of the loop. Build the adapter ONCE per `download()` call, warm it once, then call `adapter.download_pdf(doc_num, dest)` in a loop. Pass adapter into `_download_via_adapter` rather than creating it inside.

---

### 🟢 #12 — Flag naming `use_titlepro` reads as positive instead of legacy
**File / line:** `pipeline.py:288`
**What's wrong:** `use_titlepro` makes TitlePro247 sound like an option being opted into, when in fact it's the **legacy** path being kept for CA backwards-compat. New FL counties opt OUT by being non-CA.
**Why it matters:** Future maintainers will think "TitlePro is the canonical path; adapter download is experimental" when the architectural intent is the opposite.
**Recommended fix:** Rename to `legacy_titlepro_routing: Optional[bool]` or `download_via_titlepro247: Optional[bool]`. The latter is unambiguous. Existing CA workflow configs with `use_titlepro=true` would need a deprecation shim — accept both for one release, log a warning on the old name.

---

### 🟢 #13 — Tax URLs duplicated under both `orange_fl` and `fl_orange` keys
**File / line:** `config/county_tax_urls.json:461-492`
**What's wrong:** The same Aumentum URL block is duplicated under `orange_fl` (line 461) and `fl_orange` (line 477). This mirrors the Hillsborough pattern but doubles the surface area for drift.
**Why it matters:** If someone updates the URL or status under one key and forgets the other, the resolver returns whichever it tries first. Both are `status: stub_pending_recipe` for now so no live impact — but the moment a real recipe lands under one key only, behavior depends on which alias the dispatcher tries first.
**Recommended fix:** Have one canonical key (`fl_orange`) and make `orange_fl` a `{"alias_of": "fl_orange"}` redirect resolved at load time. Or just document the duplication policy with a top-of-file comment.

---

### 🟢 #14 — Pipeline log line mis-classifies "FL" as the only non-TitlePro state
**File / line:** `pipeline.py:957`
**What's wrong:** Log says `'recorder adapter direct (FL)'` — but that branch applies to any non-CA state.
**Why it matters:** Misleading once we add TX, AZ, etc.
**Recommended fix:** `f"recorder adapter direct ({self.config.state})"`.

---

## Summary of required actions before ship

| # | Severity | Action |
|---|----------|--------|
| 1 | 🔴 | Add `Any` to typing import in tyler_http_adapter.py |
| 2 | 🔴 | Either wire up `doc_image_url_pattern` or delete it |
| 3 | 🔴 | Add 5+ unit tests for `download_pdf` |
| 4 | 🟡 | Log/raise on sidecar parse failure instead of bare `pass` |
| 5 | 🟡 | Move sidecar write earlier (before sort/persist) |
| 6 | 🟡 | Clean sidecar on fresh search; add to `.gitignore` |
| 7 | 🟡 | Make `state` required OR log resolved routing decision |
| 8 | 🟡 | Persist disclaimer-accepted session cookies between phases |
| 9 | 🟡 | Future-proof cache schema to `Dict[str, Dict[str, str]]` |
| 10 | 🟡 | Translate `pdfJsUrl` error to operator language |
| 11 | 🟡 | Hoist adapter instantiation out of per-doc loop |
| 12 | 🟢 | Rename `use_titlepro` → `download_via_titlepro247` |
| 13 | 🟢 | De-dupe `orange_fl` / `fl_orange` tax URLs |
| 14 | 🟢 | Fix log line to use actual state |
