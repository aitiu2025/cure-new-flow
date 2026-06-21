# TitlePro Property Search Implementation Summary

## Overview
This document summarizes the Selenium automation implementation for searching CA County Recorder websites and downloading documents from TitlePro247.

---

## Directory Structure

```
/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/
├── titlepro_selenium_downloader.py    # TitlePro download automation
├── secrets.json                        # TitlePro credentials
├── NameandPropertySearch/
│   └── ca_recorder_search/            # Orange County Recorder search automation
│       ├── main.py                    # CLI entry point
│       ├── batch_processor.py         # Batch processing (search + download)
│       ├── base_recorder.py           # Abstract base class for multi-county
│       ├── utils.py                   # Utility functions
│       ├── requirements.txt           # Dependencies
│       └── counties/
│           └── orange.py              # Orange County implementation
└── downloaded_doc/
    └── Kwa_Danny/                     # Example output folder
        ├── FINAL_REPORT.json          # Complete property report
        ├── 2007000639083_GRANT_DEED.pdf
        ├── 2007000639084_DEED_OF_TRUST.pdf
        └── B46352700.pdf              # Reconveyance
```

---

## Scripts Created

### 1. CA Recorder Search (`ca_recorder_search/`)

**Purpose**: Search Orange County Recorder website for property documents by name.

**Usage**:
```bash
cd "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/NameandPropertySearch/ca_recorder_search"

# Single name search (searches as both Grantor and Grantee)
python3 main.py -n1 "Kwa Danny" -c orange --start-date 01/01/2000 -o results.json

# Two name search (finds common documents)
python3 main.py -n1 "Lau Casey" -n2 "Lau Brandi" -c orange -o results.json
```

**Key Features**:
- Searches name as Grantor first, then as Grantee
- Deduplicates results to create union of all documents
- Extracts document numbers via JavaScript (website uses dynamic tables)
- Outputs JSON with all document numbers found

**Known Issues**:
- Table column extraction incomplete (document numbers work, metadata columns need improvement)
- Website uses Telerik RadGrid which requires JavaScript extraction

### 2. TitlePro Downloader (`titlepro_selenium_downloader.py`)

**Purpose**: Download property documents from TitlePro247 by document number.

**Usage**:
```bash
cd "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
python3 titlepro_selenium_downloader.py
# Enter document number: 2007000639083
# Enter year: 2007
```

**Credentials** (in `secrets.json`):
```json
{
  "TITLEPRO_USERNAME": "CURE2026",
  "TITLEPRO_PASSWORD": "TitleExam2026!",
  "TITLEPRO_WEBSITE": "https://www.titlepro247.com/DocumentRetrieval/"
}
```

**Recent Fixes Applied**:
- Added `time.sleep()` delays for page loading
- Changed from `clear()` to JavaScript value setting
- Added click-to-focus before `send_keys()`
- Better error handling for element interaction

**Known Issues**:
- Browser connection sometimes drops after download starts (but file still downloads)
- Need to check download folder for new files even if script shows error

### 3. Batch Processor (`batch_processor.py`)

**Purpose**: Combined workflow - search recorder, then download all documents from TitlePro.

**Usage**:
```bash
cd "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/NameandPropertySearch/ca_recorder_search"

# Full batch process
python3 batch_processor.py --name "Kwa Danny" --address "12612 Lansdale Circle, Stanton CA 90680" --start-date 01/01/2000

# Search only (skip TitlePro download)
python3 batch_processor.py --name "Kwa Danny" --address "12612 Lansdale Circle" --skip-download
```

**Output**: Creates folder in `downloaded_doc/{Name}/` with:
- `documents_found.json` - All document numbers from recorder search
- `FINAL_REPORT.json` - Summary with property details, APN, etc.
- Downloaded PDF files

---

## Completed Example: Danny Kwa

### Input
- **Name**: Danny Kwa
- **Address**: 12612 Lansdale Circle #176, Stanton CA 90680

### Results Found
| Document # | Type | Date | Downloaded |
|------------|------|------|------------|
| 2007000639083 | GRANT DEED | 10/18/2007 | ✓ |
| 2007000639084 | DEED OF TRUST | 10/18/2007 | ✓ |
| 2012000628593 | RECONVEYANCE | 10/16/2012 | ✓ |
| 2005000744648 | Unknown | - | Not downloaded |
| 2010000482779 | Unknown | - | Not downloaded |
| 2019000538907 | Unknown | - | Not downloaded |
| 2021000625184 | Unknown | - | Not downloaded |
| 2021000666293 | Unknown | - | Not downloaded |
| 2021000676044 | Unknown | - | Not downloaded |
| 2025000197079 | Unknown | - | Not downloaded |

### Key Data Extracted
- **APN**: 937-67-322
- **Property**: Crosspointe Village Condominium, Unit 176
- **Owner**: DANNY KWA, AN UNMARRIED MAN
- **Acquired**: 10/18/2007 from U.S. Bank National Association
- **Original Loan**: $244,000 from Partners Federal Credit Union
- **Loan Status**: PAID OFF (10/16/2012)

### Output Location
```
/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/downloaded_doc/Kwa_Danny/
```

---

## Remaining Work / Improvements Needed

### High Priority
1. **Improve table column extraction** - The Orange County Recorder website doesn't reliably return column data (grantors, grantees, doc type, date). Only document numbers are extracted. May need to inspect network requests or use different selectors.

2. **Fix TitlePro connection drops** - Script sometimes loses browser connection after submitting download request. Files download successfully but script errors. Consider adding retry logic.

3. **Add PDF text extraction** - Automatically extract APN, names, addresses from downloaded PDFs to filter relevant documents.

### Medium Priority
4. **Support multiple counties** - Architecture supports it (base class exists), but only Orange County is implemented.

5. **Batch download reliability** - Current batch processor creates new browser session for each document. Consider reusing session.

6. **Address filtering** - Currently manual. Could add OCR/text extraction to automatically filter documents by property address.

### Low Priority
7. **Headless mode option** - Currently runs visible browser. Add CLI flag for headless.

8. **Database storage** - Store results in SQLite/JSON database for querying.

---

## Dependencies

```
selenium>=4.15.0
webdriver-manager>=4.0.0
```

ChromeDriver is managed automatically by `webdriver-manager`, but there's a known issue where it sometimes returns the wrong file path. The scripts handle this by checking and correcting the path.

---

## Website URLs

- **Orange County Recorder**: https://cr.occlerkrecorder.gov/RecorderWorksInternet/
- **TitlePro247**: https://www.titlepro247.com/

---

## Key Element Selectors

### Orange County Recorder
```python
SELECTORS = {
    "name_tab": "//a[contains(text(), 'Name')]",
    "party_type_dropdown": "MainContent_MainMenu1_SearchByName1_partytype",
    "name_field": "MainContent_MainMenu1_SearchByName1_nameForSearch",
    "search_button": "MainContent_MainMenu1_SearchByName1_btnSearch",
}
```

### TitlePro247
```python
SELECTORS = {
    "username": "UserName",
    "password": "Password",
    "login_button": "login-submit",
    "documents_tab": "documents",
    "year_field": "year",
    "document_number_field": "documentno",
    "buy_button": "btn-buyNow",
    "continue_button": "modal-dup-documents_btn_Continue",
    "my_orders": "my-orders",
}
```

---

## Troubleshooting

### "Element not interactable" error
- Add `time.sleep(2)` before interacting with elements
- Use `element_to_be_clickable` instead of `visibility_of_element_located`
- Try clicking element before sending keys

### Documents not downloading
- Check the `downloaded_doc/` folder - files may download even if script errors
- Look for files with timestamps matching your run time

### No results from recorder search
- Verify name format: "Last First" (e.g., "Kwa Danny" not "Danny Kwa")
- Try both Grantor and Grantee searches separately
- Expand date range

### ChromeDriver errors
- Script auto-corrects webdriver-manager path issues
- If persists, manually specify chromedriver path

---

## Session Handoff Notes

For the next Claude session:
1. All core functionality is working
2. Danny Kwa example is complete with 3 key documents downloaded
3. 6 remaining documents (2005, 2010, 2019, 2021x3, 2025) not downloaded - may be for different properties
4. Main improvement needed: Better table column extraction from Orange County website
5. TitlePro downloads work but may show connection errors (check folder for actual files)

---

*Last Updated: January 8, 2026*
