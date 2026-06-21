# Gated Automation Workflow

This workflow replaces the fragile one-shot report generation path with a strict sequence:

1. Recorder search
2. TitlePro Selenium download
3. Download validation
4. Local PDF text extraction
5. AI RAW report generation
6. AI Title Examination Notes generation
7. PDF rendering

The workflow stops immediately when a phase fails. Report generation never runs until every expected document has both metadata and a local file.

## Configurable Download Portal

The download step supports a configurable document-image portal URL.

Use these config keys:

- `download_base_url`
- `download_portal_county`

Examples:

- California TitlePro:
  `download_base_url: "https://www.titlepro247.com/"`
  `download_portal_county: "orange"`
- Alternate or non-California portal:
  `download_base_url: "https://your-other-document-portal.example/"`
  `download_portal_county: null`

If `download_portal_county` is `null`, the downloader skips the California county-selection step before requesting the document.

## Entry Point

```bash
cd "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
python3 -m titlepro.automation.cli --config config/workflow_case.example.json
```

You can stop after a phase for inspection:

```bash
python3 -m titlepro.automation.cli --config config/workflow_case.example.json --stop-after validate_downloads
```

## Output Folder

Each case runs inside:

```text
src/titlepro/api/downloaded_doc/<SAFE_OWNER>/
```

The workflow writes:

- `documents_found.json`
- `search_results.json`
- `download_manifest.json`
- `download_validation.json`
- `extracted_documents.json`
- `workflow_status.json`
- `_workflow_prompts/*.md`
- `RAW_TWO_OWNER_SEARCH_EXAM.md`
- `Title_Examination_Notes.md`
- versioned `.md`, `.html`, and `.pdf` artifacts

## AI Providers

`ai.provider` supports:

- `claude`
- `codex`

Both providers are run in a controlled prompt-driven step after download validation passes.

## Prompt Resolution

The workflow supports the prompt assets you used manually from `~/Downloads/0414_CA_Exams/`.

Configurable prompt fields:

- `ai.raw_prompt_path`
- `ai.title_prompt_path`
- `ai.design_system_path`

If `ai.raw_prompt_path` is omitted, the workflow falls back to `docs/RAW_Report_Generation_System_Prompt.md`.
If `ai.title_prompt_path` is omitted, it falls back to `Title_Examination_Notes_System_Prompt.md`.

## Resume Behavior

`resume: true` lets the workflow skip phases whose artifacts already exist and still validate cleanly.
If validation fails, the workflow re-runs or stops at the broken phase instead of blindly continuing.
