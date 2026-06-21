# TitlePro Directory Structure

**Last updated**: 2026-04-22
**Restructure branch**: `0422_titlePro_checkpoint`
**Checkpoint commit**: `dd5ebc7` (pre-restructure snapshot)

## Phase Overview

| Phase | Purpose | Status |
|-------|---------|--------|
| **Ph1** | One-shot title exam report generation (legacy) | Archived |
| **Ph2** | CURE 2.0 UI mockup only | Standalone mock |
| **Ph3** | Step-by-step gated automation workflow | Current active work |

## Layout

```
titlePro/
├── ph1_oneshot/              ← Legacy one-shot era
│   ├── scripts/              (6 files: run_mastrangelo*, download_vondran_docs, run_mis_pilot_*.sh)
│   ├── results/              (11 files: *_results.json, herron/hench/vondran/mastrangelo JSONs)
│   ├── logs/                 (3 files: cure_test_execution.log, search_execution.log, test_suite_results.log)
│   ├── docs/                 (7 files: RAW_Report prompt, Orange County research, Impl_0110, search_*)
│   └── cure_titlepro_mastrangelo/
│
├── ph2_cure_ui/              ← CURE 2.0 UI mock (imported from sibling titlePro_Ph2/)
│   ├── mock/  mock_ui_0320/  api/  docs/
│   ├── PROJECT_SUMMARY.md
│   └── USABILITY_SUGGESTIONS.md
│
├── ph3_gated_workflow/       ← Current phase
│   ├── docs/                 (GATED_AUTOMATION_WORKFLOW.md, AbstractorNotes_Step2.md, TitleExam_SystemPrompt_Step1.md)
│   ├── config/               (workflow_case.example.json)
│   ├── CURE Product Set Overview/
│   ├── Herron_Exam/          (was HERRON_DAVID_R)
│   ├── Mastrangelo_Exam/     (was MASTRANGELO_ANTHONY)
│   ├── Vondran_Exam/         (was VONDRAN_DAVID)
│   └── Ohio_Exam/            (was Ohio)
│
├── src/titlepro/             ← Python package UNTOUCHED (imports still work)
│   ├── api/                  (Flask server.py, claude_client.py)
│   ├── automation/           (cli.py, pipeline.py, agent_runners.py, renderers.py) — Ph3 gated pipeline
│   ├── search/               (ca_recorder/, captcha_solver, property_search, search_automation, ...)
│   ├── download/             (selenium_downloader.py)
│   ├── core/  reports/  tax/  verification/
│   └── titlePro_password.png
│
├── docs/                     ← Shared cross-phase docs only
│   ├── AGENT_INIT_PROMPT.md
│   ├── CUYAHOGA_AGENT_PROMPT.md
│   ├── README_output_verification.md
│   └── TitlePro247 Document Retrieval Selenium Automation Guide.md
│
├── config/                   ← Shared runtime config
│   ├── county_tax_urls.json
│   ├── input_names.example.json
│   ├── mis_pilot_ca_subjects.json
│   ├── mis_pilot_oh_subjects.json
│   ├── names.example.json
│   ├── secrets.json.example
│   └── titlepro247_config.json.example
│
├── tests/                    (pytest suite)
├── pyproject.toml            (defines titlepro package + titlepro-gated-workflow script)
├── requirements.txt
├── README.md
├── secrets.json              (gitignored)
├── titlepro247_config.json   (gitignored)
├── Title_Examination_Notes_System_Prompt.md  ← left at root (actively used by Flask server)
├── CODE_REVIEW.md
├── DESIGN.md
├── titlePro_Backlog.md
└── titlePro_dir_structure.md (this file)
```

## Key Decisions

1. **Python package stays at `src/titlepro/`** — moving it would break `pyproject.toml`, every import, and the `titlepro-gated-workflow` console script. Phase folders hold *docs, specs, scripts, samples, and legacy artifacts* — NOT the live package.

2. **`src/titlepro/automation/` is Ph3 code but lives inside the shared package** because the Ph3 gated pipeline is implemented as Python modules (`cli.py`, `pipeline.py`, etc.) that use other shared package modules (search, download, core, reports).

3. **`src/titlepro/search/ca_recorder/CURE.html`** — Ph1-era single-page UI but still the *working* UI served by the Flask server. Left in place.

4. **Shared assets kept at root**:
   - `Title_Examination_Notes_System_Prompt.md` (read by server.py)
   - `secrets.json`, `titlepro247_config.json` (runtime credentials)
   - `DESIGN.md`, `CODE_REVIEW.md`, `titlePro_Backlog.md` (cross-phase project docs)

5. **Sibling `../titlePro_Ph2/`** — fully moved into `ph2_cure_ui/` and removed.

## Post-Restructure Notes

- **`secrets.json.bak.2026-02-24`** at root contains credentials — was **unstaged** from the checkpoint commit. Recommend deleting or adding a broader `secrets.json*` pattern to `.gitignore`.
- **`src/titlepro/run_mastrangelo.py`** was renamed to `ph1_oneshot/scripts/run_mastrangelo_pkg.py` to avoid clash with the root-level `run_mastrangelo.py`.
- **281 file moves are currently staged** on branch `0422_titlePro_checkpoint`, uncommitted, awaiting your commit decision.
- **Package imports verified**: `import titlepro.{api,automation,search,download}` all resolve correctly.

## Restoring from checkpoint

If the restructure needs to be reverted:
```bash
git reset --hard dd5ebc7   # Back to pre-restructure snapshot
```
The checkpoint commit preserves every uncommitted file (modifications + untracked additions) as of 2026-04-22.
