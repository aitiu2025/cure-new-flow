# TitlePro Property Search System - Technical Implementation Specification

**Date:** January 10, 2026
**Version:** 1.0
**Status:** Phase 1 Complete, Phase 2 In Progress

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Command Line (CLI) Components](#command-line-cli-components)
4. [Web UI Components](#web-ui-components)
5. [API Server](#api-server)
6. [Data Structures](#data-structures)
7. [Implementation Status Matrix](#implementation-status-matrix)
8. [Gap Analysis & Next Steps](#gap-analysis--next-steps)

---

## System Overview

TitlePro is a property title search automation system for California County Recorders, primarily Orange County. The system consists of:

1. **CLI Tools** - Selenium-based automation for searching county recorder websites and downloading documents from TitlePro247
2. **Web UI (CURE.html)** - Browser-based interface for property search and report generation
3. **Flask API Server** - Backend API connecting UI to automation scripts
4. **Report Generator** - Creates RAW Two Owner Search Exam reports

### Primary Workflow

```
User Input (Name/Address)
    ↓
County Recorder Search (Selenium)
    ↓
Document Numbers Found
    ↓
TitlePro247 Download (Selenium)
    ↓
PDF Documents Saved
    ↓
Report Generation
    ↓
RAW Two Owner Search Exam
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CURE.html (Web UI)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ Input Form   │  │ Status Steps │  │ Documents    │  │ Report Viewer    │ │
│  │ - Owner Name │  │ 1. Connect   │  │ Table        │  │ - Markdown       │ │
│  │ - Address    │  │ 2. Check     │  │ - View       │  │ - Download DOCX  │ │
│  │ - Date Range │  │ 3. Download  │  │ - Download   │  │ - Copy           │ │
│  │ - County     │  │ 4. Verify    │  │              │  │                  │ │
│  │              │  │ 5. Report    │  │              │  │                  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTP (localhost:5555)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        titlepro_api_server.py (Flask)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ /status      │  │ /check-files │  │ /download    │  │ /generate-report │ │
│  │ /list-files  │  │              │  │ /batch-down  │  │ /get-report      │ │
│  │              │  │              │  │ /batch-stat  │  │                  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                    │                           │                    │
          ┌─────────┘                           │                    └─────────┐
          ▼                                     ▼                              ▼
┌───────────────────┐              ┌───────────────────┐           ┌───────────────────┐
│ County Recorder   │              │ TitlePro247       │           │ Report Generator  │
│ Search (Selenium) │              │ Downloader        │           │                   │
│                   │              │ (Selenium)        │           │ report_generator  │
│ - main.py         │              │                   │           │ .py               │
│ - batch_processor │              │ titlepro_selenium │           │                   │
│ - counties/orange │              │ _downloader.py    │           │                   │
└───────────────────┘              └───────────────────┘           └───────────────────┘
          │                                     │                              │
          ▼                                     ▼                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         downloaded_doc/{OwnerName}/                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ *.pdf        │  │ document_    │  │ documents_   │  │ FINAL_REPORT     │ │
│  │ (Documents)  │  │ metadata.json│  │ found.json   │  │ .json            │ │
│  │              │  │              │  │              │  │                  │ │
│  │              │  │              │  │              │  │ RAW_TWO_OWNER_   │ │
│  │              │  │              │  │              │  │ SEARCH_EXAM.md   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Command Line (CLI) Components

### 1. County Recorder Search (`main.py`)

**Location:** `NameandPropertySearch/ca_recorder_search/main.py`

**Purpose:** Search Orange County Recorder website for property documents by name.

**Status:** ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| Single name search (Grantor + Grantee) | ✅ Complete | Unions results from both searches |
| Two name search (intersection) | ✅ Complete | Finds common documents |
| Party type filter | ✅ Complete | All, Grantor, Grantee, Grantor/Grantee |
| Date range filter | ✅ Complete | Start/end date support |
| Address filter | ✅ Complete | Partial match on results |
| JSON export | ✅ Complete | -o flag saves to file |
| Console output formatting | ✅ Complete | Formatted results summary |

**Usage:**
```bash
cd "NameandPropertySearch/ca_recorder_search"

# Single name search
python3 main.py -n1 "Kwa Danny" -c orange --start-date 01/01/2000 -o results.json

# Two name search (find common documents)
python3 main.py -n1 "Lau Casey" -n2 "Lau Brandi" -c orange -o results.json

# With address filter
python3 main.py -n1 "Kwa Danny" -c orange --address "12612 Lansdale" -o results.json
```

---

### 2. Orange County Recorder Implementation (`counties/orange.py`)

**Location:** `NameandPropertySearch/ca_recorder_search/counties/orange.py`

**Purpose:** Selenium automation for Orange County Clerk-Recorder website.

**Status:** ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| Navigate to search page | ✅ Complete | Clicks Name tab |
| Set party type dropdown | ✅ Complete | Uses Select element |
| Set date range | ✅ Complete | JavaScript injection for speed |
| Enable partial match | ✅ Complete | Multiple selector strategies |
| Execute search | ✅ Complete | Waits for results |
| Extract results (JavaScript) | ✅ Complete | 3-strategy extraction |
| Return to search | ✅ Complete | For sequential searches |
| Error handling | ✅ Complete | Graceful fallbacks |

**Known Limitation:**
- ⚠️ Table column extraction sometimes incomplete - only document numbers are reliably extracted, Grantor/Grantee/Type columns sometimes empty due to RadGrid DOM structure.

---

### 3. TitlePro Selenium Downloader (`titlepro_selenium_downloader.py`)

**Location:** `titlepro_selenium_downloader.py`

**Purpose:** Download property documents from TitlePro247 by document number.

**Status:** ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| Login to TitlePro247 | ✅ Complete | Uses credentials from secrets.json |
| Navigate to Documents tab | ✅ Complete | Opens document request form |
| Submit document request | ✅ Complete | Year + document number |
| Handle duplicate modal | ✅ Complete | Clicks Continue if shown |
| Open order and download | ✅ Complete | Navigates to My Orders, finds document |
| Wait for download | ✅ Complete | Monitors folder for new files |
| Headless mode | ✅ Complete | --headless flag |
| Visible mode | ✅ Complete | --visible flag (default) |
| Owner subfolder | ✅ Complete | --owner flag organizes by name |
| Metadata tracking | ✅ Complete | Saves instrument# → filename mapping |
| Command-line args | ✅ Complete | --doc, --year, --owner, --headless |
| Reusable function | ✅ Complete | download_document() for API use |

**Usage:**
```bash
cd "/path/to/titlePro"

# Interactive mode
python3 titlepro_selenium_downloader.py
# Enter document number: 2007000639083
# Enter year: 2007

# Command-line mode
python3 titlepro_selenium_downloader.py --doc 2007000639083 --year 2007 --owner "Kwa_Danny" --headless
```

**Known Limitation:**
- ⚠️ Connection sometimes drops after download starts but file still downloads. Check folder for files even if script errors.

---

### 4. Batch Processor (`batch_processor.py`)

**Location:** `NameandPropertySearch/ca_recorder_search/batch_processor.py`

**Purpose:** Combined workflow - search recorder, then download all documents from TitlePro.

**Status:** ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| Search as Grantor | ✅ Complete | First search |
| Search as Grantee | ✅ Complete | Second search |
| Union results | ✅ Complete | Deduplicates by document number |
| Save documents_found.json | ✅ Complete | All document numbers |
| Download from TitlePro | ✅ Complete | Each document sequentially |
| Create report.json | ✅ Complete | Summary with download status |
| Skip download flag | ✅ Complete | --skip-download for search only |
| Output directory | ✅ Complete | Custom or auto-generated |

**Usage:**
```bash
cd "NameandPropertySearch/ca_recorder_search"

# Full batch process
python3 batch_processor.py --name "Kwa Danny" --address "12612 Lansdale Circle" --start-date 01/01/2000

# Search only (skip downloads)
python3 batch_processor.py --name "Kwa Danny" --skip-download
```

---

### 5. Batch Verify Documents (`batch_verify_documents.py`)

**Location:** `batch_verify_documents.py`

**Purpose:** Verify which documents are available on TitlePro for a given list.

**Status:** ✅ COMPLETE

| Feature | Status | Notes |
|---------|--------|-------|
| Test each document | ✅ Complete | Attempts download |
| Report availability | ✅ Complete | Shows ✓ or ✗ for each |
| Generate update code | ✅ Complete | Outputs JavaScript for CURE.html |

---

### 6. Report Generator (`report_generator.py`)

**Location:** `report_generator.py`

**Purpose:** Generate RAW Two Owner Search Exam reports from downloaded documents.

**Status:** ⚠️ PARTIAL

| Feature | Status | Notes |
|---------|--------|-------|
| Load metadata.json | ✅ Complete | Maps instrument# to filename |
| Load documents_found.json | ✅ Complete | All document numbers |
| Load existing FINAL_REPORT.json | ✅ Complete | If available |
| Generate basic report | ✅ Complete | Lists downloaded documents |
| Generate full report from JSON | ✅ Complete | If FINAL_REPORT.json is detailed |
| Save FINAL_REPORT.json | ✅ Complete | Auto-generated |
| Save RAW_TWO_OWNER_SEARCH_EXAM.md | ✅ Complete | Markdown format |
| PDF text extraction (OCR) | ❌ NOT IMPLEMENTED | PDFs are scanned images |
| Auto-extract legal description | ❌ NOT IMPLEMENTED | Requires OCR/AI |
| Auto-extract deed chain | ❌ NOT IMPLEMENTED | Requires OCR/AI |
| Auto-fetch tax information | ❌ NOT IMPLEMENTED | Requires web scraping |

---

### 7. Base Recorder Class (`base_recorder.py`)

**Location:** `NameandPropertySearch/ca_recorder_search/base_recorder.py`

**Purpose:** Abstract base class for multi-county support.

**Status:** ✅ COMPLETE (Architecture Only)

| Feature | Status | Notes |
|---------|--------|-------|
| DocumentRecord dataclass | ✅ Complete | Standard document structure |
| SearchResult dataclass | ✅ Complete | Container with metadata |
| Abstract methods defined | ✅ Complete | For county implementations |
| find_common_documents() | ✅ Complete | Intersection logic |
| find_unique_documents() | ✅ Complete | Difference logic |
| search_two_names() | ✅ Complete | Combined workflow |
| export_json() | ✅ Complete | File export |
| Context manager support | ✅ Complete | with statement |

**Supported Counties:**
- ✅ Orange County (`counties/orange.py`)
- ❌ Los Angeles County (placeholder in code)
- ❌ San Diego County (placeholder in code)

---

## Web UI Components

### CURE.html

**Location:** `NameandPropertySearch/ca_recorder_search/CURE.html`

**Purpose:** Browser-based UI for property search and report generation.

**Status:** ⚠️ PARTIAL

#### Input Panel (Left Column)

| Feature | Status | Notes |
|---------|--------|-------|
| Owner Name input | ✅ Complete | Text field |
| Property Address input | ✅ Complete | Text field |
| Start Date input | ✅ Complete | Date picker |
| End Date input | ✅ Complete | Date picker |
| County Recorder dropdown | ✅ Complete | Links to recorder site |
| Show Browser checkbox | ✅ Complete | Toggle headless mode |
| TitlePro Quick Download section | ✅ Complete | Manual doc download |
| Generate Report button | ✅ Complete | Triggers workflow |

#### Status Panel (Middle Column)

| Feature | Status | Notes |
|---------|--------|-------|
| Step 1: Connect to API | ✅ Complete | Checks /status endpoint |
| Step 2: Check existing files | ✅ Complete | Calls /check-files |
| Step 3: Download from TitlePro | ✅ Complete | Calls /batch-download |
| Step 4: Verify files | ✅ Complete | Re-checks /check-files |
| Step 5: Generate report | ✅ Complete | Calls /generate-report |
| Status icons (✓, spinner, ✗) | ✅ Complete | Visual feedback |
| Documents table | ✅ Complete | Shows all documents |
| Document status (Downloaded/Pending) | ✅ Complete | Per-document status |
| View button per document | ✅ Complete | Opens modal |
| Download button per document | ✅ Complete | Individual download |
| Folder path display | ✅ Complete | Shows output folder |
| Copy path button | ✅ Complete | Copies to clipboard |

#### Report Viewer (Middle Column)

| Feature | Status | Notes |
|---------|--------|-------|
| Display markdown report | ✅ Complete | Monospace formatting |
| Copy Report button | ✅ Complete | Copies to clipboard |
| Download MD button | ✅ Complete | Downloads .md file |
| Download DOCX button | ⚠️ Partial | JavaScript-only DOCX |
| Expand View button | ✅ Complete | Opens modal |

#### Summary Panel (Right Column)

| Feature | Status | Notes |
|---------|--------|-------|
| Property info display | ✅ Complete | Address, APN, Owner |
| Key Findings table | ✅ Complete | Title status, mortgages |
| Tax Information section | ✅ Complete | Tax year, amounts, dues |
| Files Generated section | ✅ Complete | Click to view |
| Notes section | ✅ Complete | Bullet points |

#### Modal & Notifications

| Feature | Status | Notes |
|---------|--------|-------|
| Document viewer modal | ✅ Complete | Full-screen overlay |
| Toast notifications | ✅ Complete | Success messages |
| Error handling | ✅ Complete | Displays errors |

---

### JavaScript Functions (CURE.html)

| Function | Status | Notes |
|----------|--------|-------|
| quickDownloadDoc() | ✅ Complete | TitlePro quick download |
| pollDownloadStatus() | ✅ Complete | Polls job status |
| showDownloadStatus() | ✅ Complete | Updates status display |
| updateDocumentStatus() | ✅ Complete | Updates doc table |
| refreshDocumentsTable() | ✅ Complete | Re-renders table |
| checkApiStatus() | ✅ Complete | On page load |
| startSearch() | ✅ Complete | Main workflow |
| pollBatchStatus() | ✅ Complete | Batch download polling |
| updateStep() | ✅ Complete | Step status update |
| showResults() | ✅ Complete | Shows report |
| viewDocument() | ✅ Complete | Opens modal |
| closeModal() | ✅ Complete | Closes modal |
| copyReport() | ✅ Complete | Clipboard copy |
| downloadMd() | ✅ Complete | Downloads MD |
| downloadDocx() | ⚠️ Partial | Basic DOCX only |
| showToast() | ✅ Complete | Notifications |

---

## API Server

### titlepro_api_server.py

**Location:** `titlepro_api_server.py`

**Purpose:** Flask API server connecting CURE.html to automation scripts.

**Status:** ✅ COMPLETE

**Server:** `http://localhost:5555`

| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/status` | GET | ✅ Complete | Health check |
| `/check-files` | POST | ✅ Complete | Check which files exist |
| `/download` | POST | ✅ Complete | Download single document |
| `/download/<job_id>` | GET | ✅ Complete | Check download status |
| `/batch-download` | POST | ✅ Complete | Download multiple documents |
| `/batch-status/<batch_id>` | GET | ✅ Complete | Check batch status |
| `/list-files/<owner>` | GET | ✅ Complete | List files in folder |
| `/generate-report` | POST | ✅ Complete | Generate report |
| `/get-report/<owner>` | GET | ✅ Complete | Get existing report |

**Request/Response Examples:**

```bash
# Health check
GET /status
Response: { "status": "online", "message": "TitlePro API Server is running" }

# Check files
POST /check-files
Body: { "owner_name": "Kwa Danny", "documents": [{ "num": "2007000639083" }] }
Response: { "folder_exists": true, "documents": [{ "num": "...", "file_exists": true }] }

# Single download
POST /download
Body: { "doc_num": "2007000639083", "year": "2007", "owner_name": "Kwa_Danny" }
Response: { "status": "started", "job_id": "2007000639083_2007" }

# Batch download
POST /batch-download
Body: { "owner_name": "Kwa_Danny", "documents": [...], "show_browser": true }
Response: { "status": "started", "batch_id": "batch_..." }

# Generate report
POST /generate-report
Body: { "owner_name": "Kwa_Danny", "property_address": "12612 Lansdale Circle" }
Response: { "success": true, "report_markdown": "...", "report_json": {...} }
```

---

## Data Structures

### 1. documents_found.json

**Generated by:** Recorder search (main.py, batch_processor.py)

```json
[
  {
    "document_number": "2007000639083",
    "grantors": "U.S. BANK NATIONAL ASSOCIATION",
    "grantees": "DANNY KWA",
    "grantor_grantees": "",
    "document_type": "GRANT DEED",
    "recording_date": "10/18/2007",
    "pages": "5"
  }
]
```

### 2. document_metadata.json

**Generated by:** TitlePro downloader

```json
{
  "2007000639083": {
    "filename": "D205918446.pdf",
    "year": "2007",
    "downloaded_at": "2026-01-10T00:09:00",
    "type": "GRANT DEED"
  }
}
```

### 3. FINAL_REPORT.json (Basic - Auto-generated)

```json
{
  "report_date": "2026-01-10",
  "property": {
    "address": "12612 Lansdale Circle #176, Stanton, CA 90680",
    "county": "Orange"
  },
  "current_owners": {
    "names": "KWA DANNY"
  },
  "documents_downloaded": [...],
  "documents_metadata": {...},
  "source_files": [...]
}
```

### 4. FINAL_REPORT.json (Detailed - Manual/AI-generated)

```json
{
  "report_date": "2026-01-08",
  "property": {
    "address": "8615 E Canyon Vista Drive",
    "city": "Anaheim",
    "state": "CA",
    "zip": "92808",
    "county": "Orange",
    "apn": "354-243-17",
    "legal_description": "Lot 17, Tract 12989...",
    "legal_description_source": "Deed of Trust, Inst# 2006000857680"
  },
  "current_owners": {
    "names": "CASEY STEPHEN LAU AND BRANDI HEATHER LAU",
    "vesting": "HUSBAND AND WIFE AS JOINT TENANTS",
    "acquisition_date": "December 22, 2006"
  },
  "tax_information": {
    "tax_year": "2025-2026",
    "apn": "354-243-17",
    "annual_tax_estimated": "$6,800.00"
  },
  "deed_chain": [...],
  "mortgages_and_deeds_of_trust": [...],
  "critical_issues": [...],
  "notes": [...]
}
```

---

## Implementation Status Matrix

### Legend
- ✅ = Complete
- ⚠️ = Partial/Needs Work
- ❌ = Not Implemented

### CLI Components

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| County Recorder Search | main.py | ✅ | Fully functional |
| Orange County Impl | counties/orange.py | ✅ | RadGrid extraction works |
| TitlePro Downloader | titlepro_selenium_downloader.py | ✅ | Headless + metadata |
| Batch Processor | batch_processor.py | ✅ | Search + download |
| Batch Verify | batch_verify_documents.py | ✅ | Test document availability |
| Report Generator | report_generator.py | ⚠️ | Basic only, no OCR |
| Base Recorder | base_recorder.py | ✅ | Architecture ready |
| LA County | counties/la.py | ❌ | Not implemented |
| San Diego County | counties/san_diego.py | ❌ | Not implemented |

### UI Components

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| Input Form | CURE.html | ✅ | All fields working |
| Status Steps | CURE.html | ✅ | 5-step workflow |
| Documents Table | CURE.html | ✅ | Dynamic updates |
| Report Viewer | CURE.html | ✅ | Markdown display |
| Summary Panel | CURE.html | ⚠️ | Static data, not dynamic |
| Modal Viewer | CURE.html | ✅ | Document viewing |
| DOCX Export | CURE.html | ⚠️ | Basic JS-only DOCX |

### API Server

| Endpoint | Status | Notes |
|----------|--------|-------|
| /status | ✅ | Health check |
| /check-files | ✅ | Uses metadata mapping |
| /download | ✅ | Single document |
| /batch-download | ✅ | Multiple documents |
| /batch-status | ✅ | Polling |
| /list-files | ✅ | Folder listing |
| /generate-report | ✅ | Calls report_generator |
| /get-report | ✅ | Get existing |

### Report Generation

| Feature | Status | Notes |
|---------|--------|-------|
| List downloaded documents | ✅ | From metadata |
| Basic report structure | ✅ | NEXT STEPS section |
| Full report from JSON | ✅ | If FINAL_REPORT.json exists |
| PDF OCR extraction | ❌ | Scanned images not readable |
| Auto legal description | ❌ | Requires OCR/AI |
| Auto deed chain | ❌ | Requires OCR/AI |
| Auto tax lookup | ❌ | Requires web scraping |

---

## Gap Analysis & Next Steps

### COMPLETED (January 10, 2026)

#### 1. PDF Content Extraction (OCR/AI) - IMPLEMENTED

**Implementation:** Created `pdf_analyzer.py` with:
- Claude Vision API integration for document analysis
- PDF to image conversion using pdf2image
- Structured data extraction (legal description, grantor/grantee, loan amounts, etc.)
- Batch folder analysis capability
- Auto-generation of FINAL_REPORT.json structure

**Also:** Claude Code can directly read PDFs for interactive analysis without needing the API module.

---

#### 2. Create Detailed FINAL_REPORT.json for Test Cases - COMPLETED

**Implementation:** Created comprehensive FINAL_REPORT.json for Kwa_Danny with:
- Full legal description (8 parcels for condo)
- Complete deed chain (3 deeds: 2007 Grant Deed, 2010 Quitclaim to Trust, 2021 Confirmatory)
- Mortgage information (2007 DOT to Partners FCU - RELEASED in 2012)
- All reconveyances documented
- Tax information template
- Critical issues assessment (none for this property)
- Detailed notes section

---

#### 3. Tax Information Integration - IMPLEMENTED

**Implementation:** Created `tax_lookup.py` with:
- Selenium automation for OC Treasurer website
- APN-based lookup
- Results parsing for tax amounts, due dates, status
- `get_tax_info_for_report()` function for integration with FINAL_REPORT.json

---

#### 4. Connection Error Handling - FIXED

**Implementation:** Updated `titlepro_selenium_downloader.py`:
- Added post-error file check
- If PDFs exist despite connection error, reports success
- Saves metadata even after connection drops
- Graceful driver cleanup

---

#### 5. Dynamic Summary Panel - IMPLEMENTED

**Implementation:** Updated CURE.html with `updateSummaryPanel(reportData)` function that:
- Updates property address, APN, owner name
- Calculates title status based on critical issues
- Shows mortgage status (open/released)
- Extracts acquisition info from deed chain
- Updates tax information fields
- Handles trust transfer detection

---

#### 6. DOCX Export Improvement - ENHANCED

**Implementation:** Improved `convertMarkdownToWordHtml()` in CURE.html:
- Handles bullet and numbered lists
- Processes code blocks and inline code
- Better table conversion
- Preserves bold/italic formatting
- Proper HTML escaping

---

#### 7. CLI/UI Output Consistency - IMPLEMENTED

**Implementation:** Updated `batch_processor.py` to:
- Call `report_generator.generate_report_for_owner()` after processing
- Use same FINAL_REPORT.json -> Markdown pipeline as UI
- Both CLI and UI now produce identical RAW_TWO_OWNER_SEARCH_EXAM.md

---

### REMAINING (LOW PRIORITY)

#### 8. Add More Counties

**Current State:** Only Orange County implemented.

**Solution:** Create new files in `counties/` folder following `orange.py` pattern.

---

#### 9. Database Storage

**Current State:** All data stored as JSON files.

**Solution:** Add SQLite database for search history and document tracking.

---

#### 10. Headless Mode Flag in UI for Recorder Search

**Current State:** "Show Browser" checkbox works for downloads only.

**Solution:** Add headless option to batch_processor and API for recorder search.

---

## Testing Checklist

### To Test Full Workflow:

1. **Start API Server:**
```bash
cd "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
python titlepro_api_server.py
```

2. **Open CURE.html in browser:**
```bash
open "NameandPropertySearch/ca_recorder_search/CURE.html"
```

3. **Hard refresh:** Cmd+Shift+R

4. **Enter test data:**
   - Owner Name: "Kwa Danny"
   - Property Address: "12612 Lansdale Circle #176, Stanton CA 90680"
   - Start Date: 01/01/2000

5. **Click "Generate Report"**

6. **Verify:**
   - [ ] Step 1: API connects
   - [ ] Step 2: Files checked
   - [ ] Step 3: Downloads complete (or skipped if exist)
   - [ ] Step 4: Verification passes
   - [ ] Step 5: Report generated

7. **Check output folder:**
```bash
ls -la downloaded_doc/Kwa_Danny/
```

---

## Key File Paths

```
/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/
├── AGENT_INIT_PROMPT.md              # Agent documentation
├── Implementation_0110.md            # This file
├── secrets.json                      # TitlePro credentials (DO NOT COMMIT)
├── titlepro_selenium_downloader.py   # TitlePro automation (UPDATED: error handling)
├── titlepro_api_server.py            # Flask API
├── report_generator.py               # Report generation (UPDATED: detailed JSON support)
├── pdf_analyzer.py                   # NEW: Claude Vision PDF analysis
├── tax_lookup.py                     # NEW: OC Treasurer tax lookup
├── batch_verify_documents.py         # Document verification
├── NameandPropertySearch/
│   └── ca_recorder_search/
│       ├── main.py                   # CLI entry point
│       ├── batch_processor.py        # Combined workflow (UPDATED: calls report_generator)
│       ├── base_recorder.py          # Abstract base class
│       ├── CURE.html                 # Web UI (UPDATED: dynamic summary, DOCX export)
│       └── counties/
│           └── orange.py             # Orange County impl
└── downloaded_doc/
    ├── Kwa_Danny/
    │   ├── document_metadata.json
    │   ├── FINAL_REPORT.json         # UPDATED: Full detailed report
    │   ├── RAW_TWO_OWNER_SEARCH_EXAM.md
    │   └── *.pdf (9 documents)
    └── Lau_Casey_Brandi/
        ├── FINAL_REPORT.json         # Detailed example
        └── *.pdf
```

---

*Document generated: January 10, 2026*
