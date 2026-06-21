# README — BEFORE Implementing

**Read this before changing any report-generation code.**
**Last verified:** 2026-05-13 against branch `0422_titlePro_checkpoint`.

> **2026-05-13 update — CAPTCHA Checkpoint Model.** Phases that talk to
> CAPTCHA-gated portals (Fresno, San Bernardino, and similar Tyler counties)
> now treat CAPTCHA as a first-class, resumable workflow state. Phases can
> emit a new `needs_human` display_status instead of failing. See
> §"CAPTCHA Checkpoint Model" near the bottom of this document and the new
> endpoints `POST /api/workflow/resume`, `/api/workflow/renew`,
> `/api/workflow/cancel`.

---

## 0. TL;DR — Two workflows exist. Only one is canonical.

| Workflow | UI location | Status |
|---|---|---|
| **One-shot "Generate Report"** (CURE.html `Generate` tab) | Default tab at `http://localhost:5555/` | ❌ **DEPRECATED — do not extend.** |
| **Step Wise Report Generation** (CURE.html `Step Wise Report Generation Tab`) | Workflow tab in CURE.html | ✅ **CANONICAL — extend this.** |

All new features (RAW report, Title Examination Notes, Abstractor Notes/Chain, PDF rendering, new counties, new AI providers, retry/resume logic) must be wired into the **step-wise pipeline**.

---

## 1. Canonical pipeline — the 8 gated phases

Defined in `src/titlepro/automation/pipeline.py` at `RecorderAutomationPipeline.phase_order`:

```python
phase_order = [
    "search",
    "download",
    "validate_downloads",
    "extract_text",
    "tax_lookup",
    "generate_raw_report",
    "generate_title_notes",
    "render_pdfs",
]
```

Each phase is a method on `RecorderAutomationPipeline` with the same name. The pipeline runs phases in order; each phase is **hard-gated** — it refuses to run unless the previous phase's artifact validates via `_can_skip_phase()`.

### Phase responsibilities (one line each)

| # | Phase | What it does | Primary artifact |
|---|---|---|---|
| 1 | `search` | Run recorder name searches via `get_recorder(county)` for each `SearchRequest` × `party_types` | `documents_found.json`, `search_results.json` |
| 2 | `download` | Pull every inventoried doc via `download_document()` into the case dir; retries respect `download_retries` / `download_retry_delay_seconds` | PDFs + `download_manifest.json` |
| 3 | `validate_downloads` | Hard-stop if any inventoried doc is missing from metadata or filesystem | `download_validation.json` |
| 4 | `extract_text` | PyMuPDF + optional Tesseract OCR fallback per page; writes `<docnum>_extracted.md` per doc | `extracted_documents.json` |
| 5 | `tax_lookup` | Fetch tax/assessor data for the subject property via the county tax portal (`config/county_tax_urls.json`). Calls `perform_tax_lookup()` (server helper) → Claude WebSearch primary + Selenium scraper fallback. Skips cleanly when the county has no registered scraper and no APN is available. | `tax_<safe_owner>.json` |
| 6 | `generate_raw_report` | Run AI agent with RAW prompt over extracted markdown; validate required sections | `RAW_TWO_OWNER_SEARCH_EXAM.md` (+ versioned copy) |
| 7 | `generate_title_notes` | Run AI agent with Title/Abstractor prompt over the RAW md; validate required sections | `Title_Examination_Notes.md` (+ versioned copy) |
| 8 | `render_pdfs` | WeasyPrint render of RAW and/or Title md → PDF | `RAW_TWO_OWNER_SEARCH_EXAM.pdf`, `Title_Examination_Notes.pdf` |

Phase enable rules (see `phase_enabled()`):
- `tax_lookup` runs only if `config.fetch_tax` is true (defaults to `True`; legacy `workflow_config.json` without the key is treated as `True`).
- `generate_title_notes` runs only if `config.generate_title_notes` is true.
- `render_pdfs` runs only if `config.generate_raw_pdf` or `config.generate_title_pdf` is true.

### Required-section validators (the gate's teeth)

Set in `pipeline.py`:

```python
RAW_REQUIRED_SECTIONS = [
    "## PHASE 1: RECORDER NAME SEARCHES",
    "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION",
    "## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION",
    "## PHASE 4: TAX & PROPERTY LOOKUP",
    "## PHASE 5: RAW EXAM REPORT",
]

TITLE_REQUIRED_SECTIONS = [
    "# Abstractor Notes/Chain",
    "## TITLE EXAMINATION SUMMARY",
    "## CHAIN OF TITLE",
    "## DEEDS OF TRUST / MORTGAGES",
    "## DOCUMENTS EXAMINED",
]
```
If a generated markdown is missing any of these headers, the phase **fails** and the gate blocks downstream phases. **Do not soften this** without explicit approval.

---

## 2. Case-folder anatomy

Everything for one case lives under `src/titlepro/api/downloaded_doc/<safe_owner>/`:

```
<safe_owner>/
├── workflow_config.json              # last-used WorkflowConfig (auto-saved)
├── workflow_status.json              # phase state machine + timestamps + errors
├── search_results.json               # raw search runs (per name × party_type)
├── documents_found.json              # deduped, sorted inventory
├── download_manifest.json            # per-doc download attempts/results
├── download_validation.json          # success/missing report
├── extracted_documents.json          # per-doc extraction summary (chars, ocr_used)
├── <docnum>.pdf                      # downloaded recorder docs
├── <docnum>_extracted.md             # per-doc markdown extraction
├── _workflow_prompts/                # saved prompt bundles (raw + title) per run
│   ├── raw_system.md / raw_user.md
│   └── title_system.md / title_user.md
├── RAW_TWO_OWNER_SEARCH_EXAM.md      # canonical RAW output (stable name)
├── RAW_TWO_OWNER_SEARCH_EXAM_<safe>_<ts>.md   # versioned copy
├── Title_Examination_Notes.md
├── Title_Examination_Notes_<safe>_<ts>.md
├── RAW_TWO_OWNER_SEARCH_EXAM.pdf
└── Title_Examination_Notes.pdf
```

Use `<safe_owner>` = `re.sub(r"[^A-Za-z0-9_]+", "_", (output_folder_name or owner_name).replace(",", "")).strip("_")` (see `WorkflowConfig.safe_owner`).

---

## 3. Backend wiring (Flask)

**Server:** `src/titlepro/api/server.py`, port **5555**, debug mode w/ auto-reload.

Step-wise endpoints (only these matter going forward):

| Method + Path | Handler | Purpose |
|---|---|---|
| `POST /api/workflow/status` | `workflow_status` (server.py:2003) | Load saved/posted config → return full status payload (phase statuses, artifacts, active jobs, `checkpoints[]`) |
| `POST /api/workflow/run-phase` | `workflow_run_phase` (server.py:2028) | Queue a single phase as background job, returns `job_id` |
| `GET /api/workflow/job/<job_id>` | `workflow_job_status` (server.py:2124) | Poll background phase job |
| `POST /api/workflow/resume` (alias `/resume-checkpoint`) | `workflow_resume_checkpoint` | Resume after a human CAPTCHA checkpoint; re-enters the paused phase with the live driver. |
| `POST /api/workflow/renew` | `workflow_renew_checkpoint` | Extend the expiry of an active human checkpoint. |
| `POST /api/workflow/cancel` | `workflow_cancel_checkpoint` | Cancel a checkpoint and close the live browser session. |

Phase status vocabulary now includes:

| display_status | Meaning |
|---|---|
| `pending`     | Not run yet |
| `running`     | A job is currently executing |
| `completed`   | Artifacts present and validated |
| `failed`      | Phase raised a terminal error |
| `needs_human` | Phase paused on a CAPTCHA/login/retry checkpoint; resume token in `checkpoint.resume_token` |
| `disabled`    | Phase is gated off by config (e.g. `fetch_tax=false`) |

Supporting helpers in `server.py`:
- `load_workflow_config_from_request(data)` — accepts inline `config` or rehydrates from `downloaded_doc/<safe_owner>/workflow_config.json`
- `save_workflow_config(pipeline)` — persists config back to disk
- `build_workflow_status_payload(config)` — assembles UI payload (phase_statuses, next_phase, artifacts, active_jobs)
- `collect_workflow_artifacts(case_dir, safe_owner, limit=80)` — lists files in case dir for the UI

**Deprecated endpoints — DO NOT BUILD ON:**
- `POST /generate-report` (one-shot RAW) → uses `titlepro.reports.report_generator` (deterministic, non-AI legacy path)
- `POST /generate-title-exam-notes` + `GET /title-exam-status/<id>` → legacy one-shot title notes
- `GET /list-reports`, `GET /read-report/<owner>` → legacy report list (used by the Generate tab only)

These remain only for backward compatibility with the deprecated tab. **New work uses the workflow endpoints.**

---

## 4. Frontend wiring (CURE.html)

**File:** `src/titlepro/search/ca_recorder/CURE.html` (~7k lines, single file).

**Tab:** `<div id="tab-workflow">` (line ~3370). Header: "⚙️ Step Wise Report Generation Tab".

Key JS constants (line ~3654):
- `WORKFLOW_PHASES` — mirror of `phase_order`. **Must stay in sync** with `pipeline.phase_order`.
- `WORKFLOW_PHASE_META` — UI labels/descriptions per phase.
- `WORKFLOW_DRAFT_KEY = 'cure-workflow-draft-v1'` — localStorage key for form draft.

Key JS functions:
- `buildWorkflowConfigPayload()` (~line 6091) — builds the `WorkflowConfig` JSON sent to the server.
- `refreshWorkflowStatus()` — `POST /api/workflow/status`, re-renders cards.
- `startWorkflowPhase(phase)` — `POST /api/workflow/run-phase`, then `pollWorkflowJob()`.
- `pollWorkflowJob(jobId)` — polls `/api/workflow/job/<id>` every 1.5s up to 720 attempts (18 min).
- `renderWorkflowPhaseCards(payload)` — renders one card per phase with `Run Step` / `Run Again` buttons.

UI form fields → config (see `captureWorkflowDraft()` and `buildWorkflowConfigPayload()`):
- Owner Names (one per line) → `search_requests[].name` (each with party_types Grantor/Grantee/Grantor-Grantee)
- Output Folder Override → `output_folder_name` (overrides `safe_owner`)
- Subject ID, Property Address, County, State, Start/End Date — direct passthrough
- AI Provider (`claude` | `codex`) → `ai.provider`
- Download Base URL → `download_base_url` (default `https://www.titlepro247.com/`)
- Download Portal County → `download_portal_county`
- RAW Prompt Path → `ai.raw_prompt_path`
- Title Notes Prompt Path → `ai.title_prompt_path`
- Design System Path → `ai.design_system_path`
- Show Browser → `download_headless = !show_browser`
- Strict Downloads → `strict_downloads`
- Generate Title Notes / RAW PDF / Title PDF → corresponding booleans

---

## 5. Config schema

`WorkflowConfig` (dataclass in `pipeline.py:100`):

```jsonc
{
  "owner_name": "HERRON DAVID R",                    // required
  "county": "orange",                                 // required
  "search_requests": [                                // required (at least 1)
    { "name": "HERRON DAVID R",
      "party_types": ["Grantor","Grantee","Grantor/Grantee"] }
  ],
  "property_address": "",
  "subject_id": "",
  "state": "CA",
  "start_date": "01/01/2000",                         // MM/DD/YYYY
  "end_date": "05/13/2026",
  "output_folder_name": null,                         // optional; overrides safe_owner derivation
  "resume": true,                                     // skip phases whose artifacts validate
  "strict_downloads": true,                           // raise on any missing download
  "download_headless": false,
  "download_retries": 2,
  "download_retry_delay_seconds": 2,
  "download_base_url": null,                          // overrides secrets.json TITLEPRO_URL
  "download_portal_county": null,
  "use_ocr_fallback": true,
  "min_page_text_chars": 50,
  "max_document_chars": 6000,
  "generate_title_notes": true,
  "generate_raw_pdf": true,
  "generate_title_pdf": true,
  "raw_required_sections": [ /* RAW_REQUIRED_SECTIONS */ ],
  "title_required_sections": [ /* TITLE_REQUIRED_SECTIONS */ ],
  "ai": {
    "provider": "claude",                             // "claude" | "codex"
    "model": null,
    "timeout_seconds": 900,
    "raw_prompt_path": "/Users/ag/Downloads/0414_CA_Exams/TitleExam_SystemPrompt_Step1.md",
    "title_prompt_path": "/Users/ag/Downloads/0414_CA_Exams/AbstractorNotes_Step2.md",
    "design_system_path": "/Users/ag/Downloads/0414_CA_Exams/DESIGN_SYSTEM.md"
  }
}
```

Resolution order for prompt paths (see `_resolve_prompt_path`):
1. Explicit `ai.raw_prompt_path` / `ai.title_prompt_path` from config
2. `~/Downloads/0414_CA_Exams/TitleExam_SystemPrompt_Step1.md` (RAW) or `AbstractorNotes_Step2.md` (Title)
3. Repo fallback: `docs/RAW_Report_Generation_System_Prompt.md` (RAW) or `Title_Examination_Notes_System_Prompt.md` (Title)

---

## 6. AI runners

`src/titlepro/automation/agent_runners.py`:
- `ClaudeCliRunner` — shells out to `claude` CLI (found via `shutil.which("claude")`); combines system + user prompts via `_combine_prompt()` with an output contract that forbids code-fence wrapping.
- `CodexCliRunner` — same shape for the Codex CLI.
- `build_agent_runner(provider, model, timeout_seconds)` — factory.

Per-run prompt bundles are saved to `<case>/_workflow_prompts/{raw,title}_{system,user}.md` for full reproducibility.

---

## 7. CLI entry point (parity with UI)

```bash
python -m titlepro.automation.cli \
    --config /path/to/workflow_config.json \
    [--stop-after <phase>]
```
(`src/titlepro/automation/cli.py`)

Use this to drive the canonical pipeline from scripts, tests, or CI without touching the Flask layer.

---

## 8. Rules for adding new functionality

1. **Tyler counties require LAST FIRST name order.** The `search_requests` list in `WorkflowConfig` must use `"AMAYA JANINE"` not `"JANINE AMAYA"`. Tyler's autocomplete-driven index requires this order; passing First-Last yields zero or wrong hits.
2. **Add behavior to a pipeline phase, not to a route handler.** Route handlers must remain thin.
3. **If a new artifact is produced, add a `_can_skip_phase` validator for it.** Without that, the resume gate cannot detect completion.
4. **Update `RAW_REQUIRED_SECTIONS` / `TITLE_REQUIRED_SECTIONS`** if the prompt produces a new mandatory section. Update the prompt **and** the validator together.
5. **If you add a new phase, edit all four spots:**
   - `RecorderAutomationPipeline.phase_order` (pipeline.py)
   - `phase_enabled()` (pipeline.py) if the phase is conditional
   - `_can_skip_phase` validators (pipeline.py)
   - `WORKFLOW_PHASES` + `WORKFLOW_PHASE_META` in CURE.html
6. **Counties:** register in `src/titlepro/search/ca_recorder/counties/registry.py`. Verify against `docs/County_URL_Mapping_CA_OH.md` (source of truth).
7. **Downloads:** route through `selenium_downloader.download_document()`; respect `download_base_url` override (canonical URL lives in `docs/County_URL_Mapping_CA_OH.md`, `secrets.json TITLEPRO_URL` is the runtime default).
8. **Prompts:** never inline prompt text in Python. Load from a file path resolvable in the config so we can A/B prompts without code changes.
9. **No new endpoints under `/generate-*`.** Workflow phases only.

---

## 9. Common-mistake checklist

- ❌ Don't add a new "shortcut" route that bypasses gates — it will silently produce unverifiable reports.
- ❌ Don't mutate `RAW_TWO_OWNER_SEARCH_EXAM.md` from outside the pipeline (e.g., the deprecated `report_generator.py`). The step-wise flow assumes that file equals the AI's last validated output.
- ❌ Don't change `safe_owner` derivation without migrating existing case folders.
- ❌ Don't remove the versioned copy (`*_<safe>_<timestamp>.md/pdf`) — it's our audit trail.
- ❌ Don't change `phase_order` list without updating CURE.html `WORKFLOW_PHASES`.
- ✅ Do save Playwright/UI screenshots into the case folder for regression visibility.
- ✅ Do test with the canonical fixtures: `ph3_gated_workflow/{Herron,Mastrangelo,Vondran}_Exam/`.

---

## 10. Quick smoke test (manual)

```bash
# 1. Start server
cd "src/titlepro" && python api/server.py    # http://localhost:5555

# 2. Open CURE.html → click "Step Wise Report Generation Tab"

# 3. Fill in (or click "Copy from Generate tab"):
#    - Owner Names: HERRON DAVID R
#    - County: orange
#    - Subject ID: CURE-2026-HERRON-001

# 4. Click "Run Step" on each phase in order. Verify each card flips to
#    Complete and that artifacts appear in the artifact list before
#    advancing.

# 5. Outputs land in src/titlepro/api/downloaded_doc/HERRON_DAVID_R/
```

---

## 10b. CAPTCHA Checkpoint Model (2026-05-13)

Counties such as Fresno and San Bernardino require a human to solve a
CAPTCHA before, during, or after recorder/tax searches. The workflow now
treats CAPTCHA as a first-class, resumable state rather than a failure.

### Resume flow (recorder example)

1. Pipeline phase calls `recorder.search_name(...)` inside a `with recorder:` block.
2. `TylerAdapter._handle_captcha()` detects the reCAPTCHA iframe and raises
   `CaptchaCheckpointRequired` carrying a `resume_token`. The adapter's
   `__exit__` recognises this exception and keeps the live Chrome window open.
3. `RecorderAutomationPipeline.run_phase` catches the exception, writes
   `workflow_status.json["phases"]["search"] = {"status": "needs_human", "checkpoint": {...}}`,
   and the job record in `workflow_jobs` becomes `{"status": "needs_human", "resume_token": "..."}`.
4. The UI polls `/api/workflow/job/<id>`, renders the **Resume / Renew / Cancel** buttons
   plus a live countdown to the expiry.
5. User solves CAPTCHA in the visible browser → clicks Resume.
6. `POST /api/workflow/resume` calls `RecorderAutomationPipeline.resume_checkpoint(resume_token)`,
   which fetches the live driver from the in-process registry and re-enters
   the same search loop. CAPTCHA can re-trigger; in that case a new
   resumable token is issued.

### Registry guarantees

- **Case/job/search-unit scoped** keys (`make_session_key`) so two cases
  never collide on one driver.
- **Thread-safe** (RLock); concurrent `create`/`cancel` paths are tested in
  `tests/unit/test_checkpoints.py`.
- **Automatic browser cleanup** on cancel / expire / process shutdown. The
  store always calls `.quit()` (Selenium) or `.close()` (Playwright) and
  swallows teardown exceptions.
- **Renewable** when the county config allows it
  (`allow_captcha_timeout_renewal: true`). Default is 900s (15 min).

### Tax phase strict semantics

- `fetch_tax=false`             → writes `tax_lookup_status.json` with
  `status="disabled"` and succeeds without a lookup.
- APN missing                    → writes `status="skipped"` with
  `reason="apn_missing"` and FAILS the phase by default.
  Override with `allow_tax_skip_on_missing_apn=true`.
- Lookup returns empty fields    → writes `status="failed"` with
  `reason="empty_required_fields"`, listing the `missing_fields[]`.
- Real success                   → writes `tax_<safe>.json` AND
  `tax_lookup_status.json` with `status="success"` and a
  `verified_fields[]` array.

The RAW report generator reads `tax_lookup_status.json` and either passes
the tax JSON to the LLM (when verified) or instructs the LLM to emit the
literal phrase `TAX STATUS NOT VERIFIED`. A post-generation guard in
`generate_raw_report` enforces that phrase whenever the status is not
`success`, so the LLM cannot silently launder empty tax data into a
"current/paid" claim.

### County config additions

```jsonc
{
  "requires_manual_captcha": true,
  "manual_captcha_timeout_seconds": 900,
  "allow_captcha_timeout_renewal": true,
  "allow_automated_captcha_solver": false,
  "checkpoint_key_scope": "case_job_search_unit",
  "resume_detection": {
    "success_url_contains": "/web/search",
    "success_selector": "input[name='SearchCriteria'], input[id*='BothNames']",
    "failure_selector": "//iframe[contains(@src, 'recaptcha')]"
  }
}
```

Counties that do not require CAPTCHA (Orange, Contra Costa, Calaveras,
Monterey, etc.) need NONE of these fields — defaults in
`WorkflowConfig` and `TylerAdapter` are safe.

---

## 11. Pointers

- Pipeline: `src/titlepro/automation/pipeline.py`
- AI runners: `src/titlepro/automation/agent_runners.py`
- PDF renderers: `src/titlepro/automation/renderers.py`
- CLI: `src/titlepro/automation/cli.py`
- Server (workflow routes only): `src/titlepro/api/server.py` lines ~85–310, ~2003–2130
- UI (workflow tab + JS): `src/titlepro/search/ca_recorder/CURE.html` lines ~3370–3550 (markup), ~3654–3700 (constants), ~5898–6700 (logic)
- **County URL + Test Subjects truth (NEW, 2026-05-13):** `docs/County_URL_Mapping_CUREMasterSheet.xlsx` (mirrored from `~/Downloads/CURE Source of Truth/County_URL_Mapping_CUREMasterSheet.xlsx`). Supersedes the older `docs/County_URL_Mapping_CA_OH.{md,xlsx}` for county/recorder/tax URL + CAPTCHA flags + Subject A/B test data.
- Prompts: `~/Downloads/0414_CA_Exams/{TitleExam_SystemPrompt_Step1,AbstractorNotes_Step2}.md` (primary); `docs/RAW_Report_Generation_System_Prompt.md`, `Title_Examination_Notes_System_Prompt.md` (fallbacks)
