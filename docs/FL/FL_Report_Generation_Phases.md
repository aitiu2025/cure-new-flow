# Florida Report Generation Phases for RAW, Title/Abstractor, and O&E Reports

This document describes the case-level workflow used to generate CURE TitlePro reports for Florida counties and subjects. It is written for operators and engineers who need to understand which phases run, which artifacts each phase produces, and where Florida-specific sidecars such as the Property Appraiser anchor fit into the run.

The executable workflow lives in `src/titlepro/automation/pipeline.py` as `RecorderAutomationPipeline`. The current code order is:

```text
search -> download -> validate_downloads -> extract_text -> extract_legal_descriptions
-> phase1_verifications -> tax_lookup -> generate_raw_report -> generate_title_notes
-> render_pdfs -> serialize_reports
```

The shorthand operational order is often stated as `search -> download -> validate -> extract_text/OCR -> extract_legal -> phase1_verifications -> tax_lookup -> generate_raw_report -> generate_title_notes -> render_pdfs`. That is correct for the report-producing path. The active runner also has the final `serialize_reports` phase, which writes JSON and XML versions of the generated RAW and Title reports when `generate_json_xml_reports` is enabled.

## Scope and outputs

Each run is one county/subject case. The workflow config provides the subject owner name, subject ID, county, state, property address, APN when known, date range, output folder, and `search_requests`. For Florida, `state` should be `FL`; unless `use_titlepro` is explicitly set, downloads route through the recorder adapter's direct `download_pdf()` method rather than the legacy TitlePro247 path used for California.

The case folder is created under the package download root, currently `src/titlepro/api/downloaded_doc/<output_folder_name>`. This folder is the single working directory for recorder results, downloaded PDFs, OCR text, tax data, prompts, markdown reports, rendered files, and sidecars.

The main outputs are:

| Output family | Canonical files | Notes |
|---|---|---|
| RAW engineering report | `RAW_TWO_OWNER_SEARCH_EXAM.md`, `.pdf`, `.json`, `.xml` | Full working exam report. Required H2 sections are `PHASE 1` through `PHASE 5`. |
| Title / Abstractor report | `Title_Examination_Notes.md`, `.pdf`, `.json`, `.xml` | Internal abstractor/title notes. The H1 must be `# Abstractor Notes/Chain`. |
| O&E / OnE client report | `OnE_Report_<Subject>.md`, `OnE_Report_<Subject>.docx` | Generated after Title notes from the OnE v1.7 prompt. This is not currently a `phase_order` phase in `RecorderAutomationPipeline`. |
| Audit sidecars | `documents_found.json`, `search_results.json`, `document_metadata.json`, `legal_descriptions.json`, `phase1_verifications.json`, `tax_*.json`, `tax_lookup_status.json` | Inputs and evidence consumed by later phases and review. |

## Phase 0: County and subject readiness

Before running a Florida subject, the county must have four practical capabilities: a recorder adapter/config, direct document retrieval, a Property Appraiser anchor path, and a tax lookup path. Recorder configs live under `src/titlepro/search/recorder/counties/config/fl/`. Tax routes are registered through `config/county_tax_urls.json` and `titlepro.tax.fetch_tax()`. Property Appraiser routes are registered through `config/county_property_appraiser_urls.json` and `titlepro.property_appraiser.fetch_property_appraiser()`.

The Property Appraiser anchor is mandatory for Florida quality, but it is not a first-class phase in the current `phase_order`. It is a pre-seeded case sidecar: `phase1_property_appraiser.json` plus `phase1_reconciliation.json`. Prior completed Florida case folders include this pair. The anchor provides the authoritative APN/folio, owner of record, situs address, short legal, assessed values, homestead indicators, and sale history. The reconciliation file ties the PA sale history back to recorder instruments and flags different-property documents. Treat this as a required pre-run or pre-reporting artifact until the PA fetch/reconciliation step is formally wired into the orchestrator.

Subject readiness is separate from county readiness. Every provided owner, spouse, trustee, prior owner, alias, or current legal name variant that needs a lien sweep should be represented in `search_requests`. Florida name format is generally `Last First`. The pipeline runs all configured names and party types, then deduplicates documents by instrument number.

## Phase 1: Search

The `search` phase builds a recorder adapter with `get_recorder(county, start_date, end_date)`, navigates to the search page, and runs each configured `search_request`. For each name, it loops through the configured party types unless the county config is marked `combined_name_search`, in which case one search is treated as covering all roles. Results are deduplicated by document number and sorted newest first by recording date.

The phase writes `documents_found.json`, which is the canonical inventory for every later phase, and `search_results.json`, which records each run, parameters, counts, and document hits. When an adapter has internal IDs needed for later direct retrieval, the phase also writes `recorder_internal_ids.json`.

The search phase has a state-contamination guard. If three or more searches produce the signature `[N, 0, 0, ...]`, the workflow raises `StateContaminationDetected` rather than shipping a partial result set. Search can also raise a human checkpoint for CAPTCHA or retryable submission problems. Checkpoint resume is currently implemented for search only.

## Phase 2: Download

The `download` phase loads `documents_found.json` and downloads the PDFs for every document that is not marked prohibited or examined-and-excluded. For Florida, the normal path is recorder-adapter direct retrieval. The pipeline warms one adapter session, rehydrates any `recorder_internal_ids.json`, and calls `adapter.download_pdf(doc_num, dest_path)` for each document. This reuse matters for Florida portals because disclaimer cookies, Cloudflare clearance, and CAPTCHA state can be session-sensitive.

Successful downloads create or update `document_metadata.json`, mapping each instrument number to its PDF filename, download timestamp, source method, document type, and search-name provenance. The phase writes `download_manifest.json` with per-document success/error/skipped statuses and attempt counts. Existing PDFs with matching metadata are skipped when `resume: true`.

For California legacy cases the phase may route through TitlePro247, but for Florida counties the expected route is direct recorder download. If an FL adapter does not implement `download_pdf()`, the phase should fail clearly unless the config explicitly opts into the legacy fallback.

## Phase 3: Validate downloads

The `validate_downloads` phase checks that every expected document has both metadata and a file on disk. It writes `download_validation.json` with expected document count, metadata count, missing metadata, missing files, and excluded documents.

Documents marked `examined_and_excluded` or `prohibited` are allowed to lack a PDF. This is important for Florida records that cannot be downloaded because of statutory restrictions or access limitations. They still remain part of the report inventory and must be itemized in the final report, but they do not block extraction.

With `strict_downloads: true`, missing metadata or missing files fail the run. With `resume: true`, the search and download phases can be skipped only if this validation summary succeeds.

## Phase 4: Extract text and OCR

The `extract_text` phase reads every downloaded PDF and writes one extracted markdown file per document, named `<pdf_stem>_extracted.md`. The extractor first uses the native PDF text layer through PyMuPDF. If the page text is below `min_page_text_chars`, and OCR fallback is enabled, it rasterizes the page and runs Tesseract OCR through Pillow/pytesseract.

The phase writes `extracted_documents.json`, including the document number, source filename, extracted markdown filename, total character count, and whether OCR was used. A very small extraction result fails the phase because downstream legal description extraction, subject-address verification, mortgage linking, and report generation all depend on usable text.

Excluded/prohibited documents receive stub extraction entries rather than PDFs. This keeps the corpus complete while respecting the fact that no document body is available.

## Phase 5: Extract legal descriptions and APNs

The `extract_legal_descriptions` phase is deterministic. It inspects deed-shaped documents, reads the extracted text, and tries to capture the verbatim legal description from anchors such as `EXHIBIT A`, `LEGAL DESCRIPTION`, `THE LAND REFERRED TO`, and similar phrases. It also extracts APN/parcel candidates and preserves the longest APN form so trailing check digits are not dropped.

The output is `legal_descriptions.json`, keyed by document number. Each entry includes document type, recording date, filename, verbatim legal description, verbatim APN, anchor used, source, confidence, and extraction timestamp. Later RAW and Title prompts inject this sidecar as the authoritative legal description source.

After report generation, the pipeline can splice the canonical legal description back into RAW and Title markdown and then run a strict similarity validator. This protects against LLM paraphrase, missing Exhibit A continuations, and APN normalization errors.

## Phase 6: Phase-1 verifications

The `phase1_verifications` phase writes `phase1_verifications.json`. Despite the name, it runs after text extraction because it needs the downloaded document text. It classifies document types, verifies each document's extracted address against the subject address, classifies mortgages as open/released/modified/subordinate, audits any `not_needed/` folder, walks the vesting chain, detects NOC termination bundles, and links title affidavits to judgments.

This sidecar enforces several Florida quality rules. A deed whose address does not match the subject must not be used as vesting. A mortgage linked to a recorded satisfaction must appear as released, not open. Documents initially filtered out must be recovered or listed as examined-and-excluded with a reason. Same-day refi or estate-planning interim deeds must not stop the prior-vesting chain prematurely.

The RAW and Title prompt builders inject this verification block directly. OnE v1.7 also relies on the same sidecar concepts, especially the vesting-chain walker, NOC bundle statuses, and title-affidavit pairings.

## Phase 7: Tax lookup

The `tax_lookup` phase resolves the APN from workflow config or extracted artifacts and dispatches to `titlepro.tax.fetch_tax()`. It writes a canonical `tax_<safe_owner>.json` plus `tax_lookup_status.json`. Status values include `TAX_SUCCESS`, `TAX_PARTIAL`, `TAX_NO_RUNNER`, `TAX_FAILED`, `TAX_NO_RESULTS`, and `NEEDS_HUMAN`.

Successful and partial results are allowed to proceed according to config. Hard failures and no-results usually stop the run. If the county has no tax runner, the behavior depends on `strict_tax_no_runner`. If APN is missing, the run fails unless `allow_tax_skip_on_missing_apn` is true.

The RAW prompt always receives a tax status block. If tax is not verified, the generated RAW report must contain the literal phrase `TAX STATUS NOT VERIFIED` and must not label taxes as paid, current, or verified. This guard prevents stale or missing tax data from becoming a false customer-facing fact.

## Phase 8: Generate RAW report

The `generate_raw_report` phase builds a system prompt from the RAW prompt file and a user prompt from the case artifacts: recorder inventory, document metadata, tax status/data, verbatim legal descriptions, phase1 verification output, and clipped document text excerpts. The default model for RAW is Opus because this is the heavy analytical pass.

The output is validated before it is written. The RAW markdown must include the five exact required sections:

```text
## PHASE 1: RECORDER NAME SEARCHES
## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION
## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION
## PHASE 4: TAX & PROPERTY LOOKUP
## PHASE 5: RAW EXAM REPORT
```

After generation, the legal description repair and validator run. The canonical output is `RAW_TWO_OWNER_SEARCH_EXAM.md`, with a timestamped versioned copy. Invalid output is not persisted because it would poison Title generation and rendering.

## Phase 9: Generate Title / Abstractor notes

The `generate_title_notes` phase takes the validated RAW report, injects the verbatim legal description block and phase1 verification block, and asks the model to produce the Title/Abstractor markdown. Title notes are a complete internal report and should remain the superset of the client-facing OnE. Released mortgage detail, full documents examined inventory, PA sale-history/back-chain ledger, APN anchor, subject-address verification, and examiner recommendations belong here when relevant.

The output must start with `# Abstractor Notes/Chain` and include these required sections:

```text
## TITLE EXAMINATION SUMMARY
## CHAIN OF TITLE
## LEGAL DESCRIPTION (EXHIBIT A)
## DEEDS OF TRUST / MORTGAGES
## DOCUMENTS EXAMINED
```

As with RAW, legal description repair and validation run before the phase is complete. The canonical output is `Title_Examination_Notes.md`, with a timestamped versioned copy.

## Phase 10: Render PDFs and serialize reports

The `render_pdfs` phase validates the markdown files again and renders PDFs. RAW uses the `RAW_DOC_TYPE` styling. Title/Abstractor notes use the `TITLE_DOC_TYPE` styling, which has the cream/yellow notepad background and Title-specific header. The output files are `RAW_TWO_OWNER_SEARCH_EXAM.pdf` and `Title_Examination_Notes.pdf`, plus timestamped copies.

The `serialize_reports` phase runs after PDF rendering when enabled. It uses `src/titlepro/reports/build_json_xml_reports.py` to parse the RAW and Title markdown/PDF and produce `RAW_TWO_OWNER_SEARCH_EXAM.json`, `RAW_TWO_OWNER_SEARCH_EXAM.xml`, `Title_Examination_Notes.json`, and `Title_Examination_Notes.xml`. These files combine report sections with structured case artifacts for downstream systems.

## O&E / OnE compilation

The O&E report is the client-facing Ownership and Encumbrance report, called OnE in this codebase. It is generated from completed Title Examination Notes using `docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md`, whose current content version is v1.7. The OnE compiler must not add new findings or change classifications. It restructures the Title facts into the client template.

The OnE report has eight numbered sections: Report Header, Vesting, Open Mortgages, Judgments, Bankruptcy, Property Tax Information, conditional Miscellaneous Documents Examined, and Exhibit A. It intentionally omits internal examiner jargon, subject-address verifier statuses, released mortgage ledgers, full PA sale-history ledgers, municipal-search disclaimers, and other Title-only working product. Released mortgage evidence stays in the Title; the OnE mortgage section is open-only.

Canonical OnE output is editable DOCX, not PDF. The expected files are `OnE_Report_<Subject>.md` and `OnE_Report_<Subject>.docx`, rendered with:

```bash
python3 docs/Cure_Response/render_one_report_docx.py OnE_Report_<Subject>.md OnE_Report_<Subject>.docx
```

The helper strips operator-only memo blocks before converting to DOCX and uses pandoc's default table model. Every table must render with visible borders, and the DOCX should be visually checked before delivery.

## Resume behavior

Most phases are artifact-skippable when `resume: true`. Search skips when `documents_found.json` exists and is non-empty. Download and validation skip when download validation succeeds. Text extraction skips when `extracted_documents.json` succeeds and referenced extracted markdown files exist. Legal extraction skips when `legal_descriptions.json` is present and non-empty. Phase1 verification skips only when the v1.6 keys are present. Tax skips on successful, partial, or no-runner status according to the sidecar rules. RAW and Title skip when their markdown files pass required-section validation. Rendering skips when expected PDFs exist. Serialization skips when expected JSON/XML files exist.

This means a normal recovery run can reuse completed search/download artifacts and PDFs on disk. If a sidecar is stale or incomplete, remove that sidecar or run the phase with `force=True` through code. From the CLI, use `--stop-after <phase>` to stop at a boundary for inspection.

```bash
titlepro-gated-workflow --config /path/to/workflow_config.json
titlepro-gated-workflow --config /path/to/workflow_config.json --stop-after generate_raw_report
```

## Operational rule for Florida counties

Do not treat a Florida county as ready just because recorder search works. A shippable county/subject run needs: recorder search, direct PDF retrieval, text extraction, legal/APN extraction, phase1 verifications, tax lookup or explicit tax engineering ticket, Property Appraiser anchor sidecars, RAW report, Title/Abstractor report, OnE DOCX, and verifier sign-off. The Property Appraiser anchor is the current gap most likely to block new Florida counties because it is mandatory quality evidence but not yet a formal pipeline phase.
