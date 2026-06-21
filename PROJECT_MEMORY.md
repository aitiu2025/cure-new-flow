# TitlePro CURE — Project Memory File
**Created:** 2026-06-21 | **Author:** Claude (Sonnet 4.6) working with Amit Anturkar (aanturkar@tiuconsulting.com)
**Purpose:** Complete project understanding for any future Claude session. Read this before touching any code.

---

## 1. WHAT THIS PROJECT IS

**TitlePro CURE** is an automated title examination pipeline for Florida (and some California) real estate properties. It:

1. Searches county recorder portals for documents tied to a property owner
2. Downloads all found PDFs
3. OCR-extracts text from each PDF
4. Runs AI (Claude) to generate professional title examination reports
5. Produces three deliverables:
   - **RAW Report** (`RAW_TWO_OWNER_SEARCH_EXAM.md/.pdf`) — internal engineering view, all raw facts
   - **Title Examination Notes** (`Title_Examination_Notes.md/.pdf`) — abstractor's complete report
   - **OnE Report** (`OnE_Report_<OWNER>.md/.pdf/.docx`) — client-facing Ownership & Encumbrance report

**Business context:** Used by TIU Consulting to automate what title abstractors do manually — searching county recorders, classifying mortgages, verifying addresses, building chain-of-title, and producing client-ready reports.

---

## 2. PROJECT STRUCTURE

```
Amit-0422_titlePro_checkpoint\
│
├── CLAUDE.md                          ← Tony Roveda's 6 directives — READ FIRST
├── PROJECT_MEMORY.md                  ← THIS FILE
│
├── src/titlepro/
│   ├── __init__.py                    ← defines DOWNLOAD_DIR (output root)
│   ├── automation/
│   │   ├── cli.py                     ← Main entry point (titlepro-gated-workflow command)
│   │   ├── pipeline.py                ← Core pipeline — all 12 phases live here
│   │   ├── agent_runners.py           ← Claude CLI subprocess wrapper
│   │   └── renderers.py              ← Markdown → PDF conversion (weasyprint/xhtml2pdf)
│   ├── search/recorder/counties/      ← County adapter registry
│   │   ├── registry.py               ← get_recorder(county_slug) lookup
│   │   └── fl/
│   │       ├── acclaimweb_http_adapter.py   ← Broward (HTTP, curl_cffi)
│   │       ├── hillsborough_http.py         ← Hillsborough (bare HTTP, no auth)
│   │       ├── palm_beach_landmark.py       ← Palm Beach (Landmark portal)
│   │       └── ... (other counties)
│   ├── tax/
│   │   └── grant_street_http.py       ← Tax lookup adapter
│   ├── property_appraiser/counties/
│   │   └── broward_bcpa.py           ← BCPA property appraiser adapter
│   ├── verification/
│   │   ├── subject_address_verifier.py    ← SIMMONS gate (verifies deed address)
│   │   ├── released_mortgage_linker.py    ← Links satisfactions to mortgages
│   │   ├── vesting_chain_walker.py        ← Walks deed chain (Tony directive)
│   │   └── report_sanitizer.py           ← Strips operator memos before client delivery
│   └── api/downloaded_doc/            ← ALL CASE OUTPUT GOES HERE
│       └── <OWNER_NAME>/              ← e.g. HABER_DANA_M/
│
├── docs/
│   └── Cure_Response/
│       ├── RAW_Report_Generation_System_Prompt.md      ← RAW report AI prompt
│       ├── Title_Examination_Notes_System_Prompt.md    ← Title Notes AI prompt (FL version)
│       ├── OnE_Report_SystemPrompt_v1.2.md             ← OnE report AI prompt (v1.7 content)
│       ├── render_one_report_docx.py                   ← Standalone pandoc DOCX renderer
│       └── OnE_v1.7_Amendment_PriorVesting_Chain.md   ← OnE v1.7 spec doc
│
├── Title_Examination_Notes_System_Prompt.md  ← OLD CA-style prompt (root) — NOT used now
│
└── venv/                              ← Python virtual environment
```

**Output location (IMPORTANT):**
```
src\titlepro\api\downloaded_doc\<SAFE_OWNER_NAME>\
```
Not in the project root — always in this subfolder. `SAFE_OWNER_NAME` = owner name uppercased with spaces → underscores (e.g. `HABER DANA M` → `HABER_DANA_M`).

---

## 3. PIPELINE — 12 PHASES (current, after session fixes)

```
search → download → validate_downloads → extract_text →
extract_legal_descriptions → phase1_verifications → tax_lookup →
generate_raw_report → generate_title_notes → generate_one_report →
render_pdfs → serialize_reports
```

| # | Phase | Description | Key Output |
|---|-------|-------------|-----------|
| 1 | `search` | Searches county recorder for all names | `documents_found.json` |
| 2 | `download` | Downloads PDFs via recorder portal | PDFs in case folder |
| 3 | `validate_downloads` | Confirms all PDFs present | `download_validation.json` |
| 4 | `extract_text` | OCR via PyMuPDF + pytesseract | `*_extracted.md` per doc |
| 5 | `extract_legal_descriptions` | Extracts APN + legal description from deeds | `legal_descriptions.json` |
| 6 | `phase1_verifications` | Address verify, mortgage classify, vesting chain | `phase1_verifications.json` |
| 7 | `tax_lookup` | Tax data from county portal | `tax_<OWNER>.json` |
| 8 | `generate_raw_report` | Claude Opus → RAW engineering report | `RAW_TWO_OWNER_SEARCH_EXAM.md` |
| 9 | `generate_title_notes` | Claude Sonnet → Title Examination Notes | `Title_Examination_Notes.md` |
| 10 | `generate_one_report` | Claude Sonnet → OnE client report + DOCX | `OnE_Report_<OWNER>.md/.docx` |
| 11 | `render_pdfs` | MD → PDF for RAW + Title + OnE | `*.pdf` |
| 12 | `serialize_reports` | JSON + XML structured export | `report.json`, `report.xml` |

**Resume behaviour:** Completed phases are automatically skipped on re-run. Safe to re-run any time.

---

## 4. HOW TO RUN (Full Command Reference)

### Entry point
```powershell
titlepro-gated-workflow [flags]
```
Installed as a console script via `pip install -e .` inside the venv.

### All CLI flags
| Flag | Default | Purpose |
|------|---------|---------|
| `--owner "LAST FIRST"` | required | Primary owner (used as case folder name) |
| `--county fl_<slug>` | required | County slug — FL needs `fl_` prefix |
| `--state FL` | FL | State code |
| `--address "..."` | `""` | Subject property address |
| `--apn "00-00-..."` | none | Parcel number — required for tax lookup |
| `--name "Last First"` | owner | Recorder search name — repeat for each person |
| `--start-date MM/DD/YYYY` | 01/01/2000 | Search window start |
| `--end-date MM/DD/YYYY` | today | Search window end |
| `--output-folder NAME` | derived | Override case subfolder name |
| `--stop-after <phase>` | run all | Stop pipeline after named phase |
| `--skip-tax` | false | Skip tax_lookup phase |
| `--skip-one` | false | Skip generate_one_report phase |
| `--raw-prompt PATH` | auto | Custom RAW prompt file |
| `--title-prompt PATH` | auto | Custom Title prompt file |
| `--one-prompt PATH` | auto | Custom OnE prompt file |
| `--config PATH` | none | Legacy: load full config from JSON file |

### Full example (Palm Beach / HABER case — tested and working)
```powershell
titlepro-gated-workflow --owner "HABER DANA M" --county fl_palm_beach --state FL --address "21831 Palm Grass Dr, Boca Raton, FL" --name "Haber Dana M" --name "Haber Mark" --apn "00-41-47-22-04-000-1090"
```

### Run one phase at a time
```powershell
titlepro-gated-workflow --owner "SMITH JOHN" --county fl_palm_beach --state FL --address "123 Oak St, Boca Raton, FL" --name "Smith John" --name "Smith Jane" --apn "00-00-00-00-00-000-0000" --stop-after search
# then next:
titlepro-gated-workflow ... --stop-after download
# ... and so on through all 12 phases
```

### Skip OnE (Title Notes only, original behaviour)
```powershell
titlepro-gated-workflow ... --skip-one --stop-after render_pdfs
```

---

## 5. COUNTY ADAPTER STATUS

| County | Slug | Adapter | Status | Notes |
|--------|------|---------|--------|-------|
| Palm Beach | `fl_palm_beach` | `palm_beach_landmark.py` | ✓ Working | APN not in search results — get from pbcpao.gov, pass via `--apn` |
| Hillsborough | `fl_hillsborough` | `hillsborough_http.py` | ✓ Working | No APN issues |
| Broward | `fl_broward` | `acclaimweb_http_adapter.py` | ✓ Working | Needs `curl_cffi` for Cloudflare bypass |
| Duval | `fl_duval` | unknown | Untested | Not tested in this session |
| Miami-Dade | `fl_miami_dade` | stub | ✗ Broken | `setup_driver()` raises `NotImplementedError` — adapter not built |

### County slug rule
- **Florida:** `fl_<county>` — e.g. `fl_palm_beach`, `fl_hillsborough`, `fl_broward`
- **California:** `<county>` — e.g. `orange`, `fresno`, `san_diego`

### Cloudflare counties (Broward, Miami-Dade)
Only `curl_cffi` with `safari17_2_ios` impersonation passes Cloudflare. Plain `requests`, `urllib`, and `cloudscraper` are blocked. Do NOT switch off `curl_cffi` for these counties.

---

## 6. AI REPORT GENERATION — How It Works

All three AI phases use the same `ClaudeCliRunner` in `agent_runners.py`:

1. System prompt + user prompt combined into one string via `_combine_prompt()`
2. Written to `%TEMP%\titlepro_agent_prompt.txt`
3. Piped via stdin to `claude --print --allowedTools Read,Bash`
4. Output captured with `encoding="utf-8", errors="replace"` (Windows fix)
5. Validated against required section headers
6. Saved to case folder

### Prompt files used
| Report | Prompt file | Model |
|--------|------------|-------|
| RAW | `docs/Cure_Response/RAW_Report_Generation_System_Prompt.md` | Claude Opus 4.8 |
| Title Notes | `docs/Cure_Response/Title_Examination_Notes_System_Prompt.md` | Claude Sonnet 4.6 |
| OnE | `docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md` | Claude Sonnet 4.6 |

### Required section validation
Each AI output is checked for exact H2 headers before being saved:

**RAW:** `## PHASE 1` through `## PHASE 5`
**Title Notes:** `# Abstractor Notes/Chain` + five `##` sections
**OnE:** `# Ownership and Encumbrance Report` + `## 1.` through `## 8.`

If validation fails → draft saved as `*_DRAFT.md` for inspection → `WorkflowError` raised.

### Saved prompt bundles (for debugging)
Every run saves the exact prompts used:
```
<case_folder>/_workflow_prompts/
├── raw_system_prompt.md
├── raw_user_prompt.md
├── title_system_prompt.md
├── title_user_prompt.md
├── one_system_prompt.md
└── one_user_prompt.md
```

---

## 7. PDF RENDERING

**File:** `src/titlepro/automation/renderers.py`

Two PDF backends tried in order:
1. `weasyprint` — preferred (supports `@page` CSS, page numbers in footer)
2. `xhtml2pdf` — fallback (pure Python, easier on Windows)

**Install:** `pip install xhtml2pdf` (weasyprint needs GTK — complex on Windows)

**CSS types:**
- `RAW_DOC_TYPE` → white background → used for RAW report and OnE report
- `TITLE_DOC_TYPE` → cream/yellow (`#FFFDF0`) background → ONLY for Title Examination Notes

**Known issue fixed:** `xhtml2pdf` crashes on `@bottom-center` / `@bottom-right` inside `@page {}`. Fixed by stripping nested at-rules with regex before passing to xhtml2pdf. Side effect: no "Page X of Y" footer when using xhtml2pdf.

---

## 8. OnE REPORT — DOCX OUTPUT

The OnE report also produces a `.docx` (Word-editable) file via pandoc.

**Install pandoc:**
```powershell
winget install pandoc
```

If pandoc not installed → `.md` is saved, `.docx` is skipped with a warning (no crash).

The PDF is rendered by the `render_pdfs` phase automatically.

---

## 9. ALL CODE FIXES MADE IN SESSION (2026-06-21)

### Fix 1 — CLI: Inline arguments (no JSON config needed)
**File:** `cli.py` — Added `--owner`, `--county`, `--state`, `--address`, `--apn`, `--name`, `--start-date`, `--end-date`, `--output-folder`. Made `--config` optional.

### Fix 2 — CLI: `--skip-tax` flag
**File:** `cli.py` — Sets `fetch_tax: false`. Use when APN unknown (Palm Beach doesn't return APN in search results).

### Fix 3 — CLI: `--raw-prompt` and `--title-prompt` flags
**File:** `cli.py` — Override default prompt search locations.

### Fix 4 — Pipeline: RAW prompt wrong folder
**File:** `pipeline.py` — Added `docs/Cure_Response/` as candidate. RAW prompt is at `docs/Cure_Response/RAW_Report_Generation_System_Prompt.md`, not `docs/` root.

### Fix 5 — Agent runner: Windows command line too long (WinError 206)
**File:** `agent_runners.py` — Changed from passing prompt as `-p "..."` CLI arg to piping via stdin through temp file. Windows has ~32,767 char limit on CreateProcess command line.

### Fix 6 — Agent runner: UnicodeDecodeError (cp1252 vs UTF-8)
**File:** `agent_runners.py` — Added `encoding="utf-8", errors="replace"` to subprocess.run. Also added `result.stdout or ""` guard.

### Fix 7 — Pipeline: Title prompt wrong candidate
**File:** `pipeline.py` — Added `docs/Cure_Response/Title_Examination_Notes_System_Prompt.md` as first candidate. The root `Title_Examination_Notes_System_Prompt.md` is an old CA hybrid that causes validation failures.

### Fix 8 — Pipeline: Save draft on title validation failure
**File:** `pipeline.py` — Saves `Title_Examination_Notes_DRAFT.md` (and `OnE_Report_DRAFT.md`) before raising error, so operator can inspect what Claude generated.

### Fix 9 — Renderer: xhtml2pdf crashes on `@page` nested CSS
**File:** `renderers.py` — Strips `@bottom-center` / `@bottom-right` from CSS before passing to xhtml2pdf using `re.sub()`.

### Fix 10 — Pipeline: Added `generate_one_report` phase
**Files:** `pipeline.py`, `cli.py` — Full new phase: reads Title Notes → runs Claude Sonnet → validates → saves MD → renders DOCX via pandoc. Added `--skip-one` and `--one-prompt` CLI flags.

### Fix 11 — Pipeline: OnE PDF in `render_pdfs`
**File:** `pipeline.py` — Added OnE PDF rendering in `render_pdfs` using `RAW_DOC_TYPE`. Also updated `_render_summary()` to include OnE PDF in completion check.

---

## 10. MISSING PACKAGES (not in requirements.txt)

```powershell
pip install beautifulsoup4    # Hillsborough adapter (bs4)
pip install curl_cffi         # Broward/Miami-Dade Cloudflare bypass
pip install python-dotenv     # .env file loading for API key
pip install xhtml2pdf         # PDF rendering fallback
pip install playwright        # Some tax lookups (+ playwright install chromium)
```

---

## 11. PALM BEACH APN ISSUE

The Palm Beach Landmark portal does not return APN/PCN in recorder search results. All `apn` fields in `documents_found.json` are empty.

**Workaround:** Look up the PCN manually on the Palm Beach County Property Appraiser website:
`https://www.pbcpao.gov/` → search by address → copy the PCN number → pass as `--apn`

**Example:** `--apn "00-41-47-22-04-000-1090"`

---

## 12. WORKFLOW STATUS FILE

Every run maintains `workflow_status.json` in the case folder. Shows each phase status:
- `"completed"` — done, will be skipped on re-run
- `"failed"` — will retry on re-run
- `"skipped"` — phase disabled (e.g. `fetch_tax: false`)

---

## 13. TESTED CASES

### HABER DANA M — Palm Beach FL (full pipeline ✓)
```powershell
titlepro-gated-workflow --owner "HABER DANA M" --county fl_palm_beach --state FL --address "21831 Palm Grass Dr, Boca Raton, FL" --name "Haber Dana M" --name "Haber Mark" --apn "00-41-47-22-04-000-1090"
```
- 37 documents found and downloaded
- RAW report: 22,367 chars
- Title Notes: 41,809 chars
- OnE report: 9,677 chars
- All 3 PDFs rendered

### DEL MONTE ANGEL — Hillsborough FL (search only ✓)
```powershell
titlepro-gated-workflow --owner "DEL MONTE ANGEL" --county fl_hillsborough --state FL --address "13519 Estshire Dr, Tampa, FL" --name "Del Monte Angel" --name "Del Monte Christine" --stop-after search
```
- 3 documents found

---

## 14. SUMMARY FILES LOCATION

All documentation and guides saved at:
```
D:\10X Door CURE AI\Amit New Flow Of Cure\Summary Files Amit-0422_titlePro_checkpoint\
├── PROJECT_DEEP_SCAN_SUMMARY.md       ← Full project structure scan
├── HOW_TO_RUN_GUIDE.md                ← 13-part operational guide
├── HOW_TO_RUN_SUMMARY.md              ← One-page quick reference
├── CASE_DEL_MONTE_COMMANDS.md         ← Del Monte case commands
├── FIXES_AND_CHANGES_SUMMARY.md       ← All 11 fixes with code details
└── ONE_REPORT_PIPELINE_GUIDE.md       ← OnE report + full pipeline guide
```

---

## 15. KEY ARCHITECTURAL DECISIONS (from CLAUDE.md)

1. **No Selenium in search** — use HTTP via `curl_cffi` + `safari17_2_ios` for Cloudflare counties
2. **Deed-first search** — first search must be `DocType=DEED`, then APN re-search
3. **All names searched** — husband + wife always; spouse-delta applied
4. **Address verification on every deed** — `subject_address_verifier.py` (SIMMONS gate)
5. **Every document examined** — nothing dropped silently; exclusions itemized in report
6. **Released-mortgage exclusion** — `released_mortgage_linker.py` classifies mortgages post-extraction
7. **`[N,0,0,0,0,0]` pattern = state contamination bug** — raises `StateContaminationDetected`

---

## 16. QUICK START FOR NEW CLAUDE SESSION

1. Read `CLAUDE.md` (Tony's 6 directives — mandatory)
2. Read this file (`PROJECT_MEMORY.md`)
3. Check `Summary Files Amit-0422_titlePro_checkpoint\FIXES_AND_CHANGES_SUMMARY.md` for all code changes
4. The pipeline entry point is `src/titlepro/automation/cli.py`
5. All 12 phases are in `src/titlepro/automation/pipeline.py`
6. Output always goes to `src/titlepro/api/downloaded_doc/<OWNER_NAME>/`
7. Always activate venv first: `.\venv\Scripts\Activate.ps1`
