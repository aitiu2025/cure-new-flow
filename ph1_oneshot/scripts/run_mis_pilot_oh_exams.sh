#!/bin/bash
# =============================================================================
# MIS PILOT - OH Cuyahoga County Title Exam Orchestrator
# Runs Claude CLI agent for 3 OH Cuyahoga County properties from the MIS Pilot sheet
# Generated: 2026-04-03
# Properties: Kincannon/Callister, Hendricks, Maldonado
#
# Tax navigation instructions from Tony Roveda (National Attorney Title CEO):
#   Step 1: https://myplace.cuyahogacounty.gov/
#   Step 2: Search → Click property → left sidebar shows TAXES section
#   Step 3: Click "Tax By Year" → gets parcel number, assessed values, tax table
# =============================================================================

set -e

# --- Config ---
TITLEPRO_DIR="/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
CLAUDE_CLI="/Users/ag/.local/bin/claude"
API_PORT=5555
LOG_DIR="${TITLEPRO_DIR}/logs/mis_pilot_oh_$(date +%Y%m%d_%H%M%S)"
CA_AGENT_PROMPT_FILE="${TITLEPRO_DIR}/docs/AGENT_INIT_PROMPT.md"
OH_AGENT_PROMPT_FILE="${TITLEPRO_DIR}/docs/CUYAHOGA_AGENT_PROMPT.md"

# Cuyahoga County env vars (passed to each agent subprocess)
export CUYAHOGA_RECORDER_URL="https://cr.cuyahogacounty.us/"
export CUYAHOGA_MYPLACE_URL="https://myplace.cuyahogacounty.gov/"
export CUYAHOGA_AUDITOR_URL="https://auditor.cuyahogacounty.gov/"
export CUYAHOGA_COURT_URL="https://cpdocket.cp.cuyahogacounty.us/"
export CUYAHOGA_TAX_SEARCH_METHOD="owner_or_address"
export CUYAHOGA_TAX_NAV_STEPS="3"
export CUYAHOGA_TAX_CLICK_SEQUENCE="search_results > property_detail > sidebar_taxes > tax_by_year"
export CUYAHOGA_PARCEL_FORMAT="NNN-NN-NNN"
export COUNTY_TAX_URLS_CONFIG="${TITLEPRO_DIR}/config/county_tax_urls.json"
export COUNTY_NAME="cuyahoga"
export STATE_CODE="OH"

mkdir -p "$LOG_DIR"

echo "================================================================"
echo "  MIS PILOT - OH Cuyahoga County Title Exam Runner"
echo "  Date: $(date)"
echo "  Log dir: $LOG_DIR"
echo "================================================================"

# --- Step 1: Activate venv & install dependencies ---
echo ""
echo "[SETUP] Activating virtual environment..."
cd "$TITLEPRO_DIR"
source venv/bin/activate

echo "[SETUP] Installing titlepro package (pip install -e .)..."
pip install -e . --quiet 2>&1 | tail -3

# --- Step 2: Start Flask API Server (if not already running) ---
echo ""
echo "[API] Checking if Flask API server is running on port ${API_PORT}..."
if lsof -Pi :${API_PORT} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "[API] Server already running on port ${API_PORT} - OK"
else
    echo "[API] Starting Flask API server on port ${API_PORT}..."
    nohup python -m titlepro.api.server > "${LOG_DIR}/api_server.log" 2>&1 &
    API_PID=$!
    echo "[API] Server PID: $API_PID"
    sleep 5
    if lsof -Pi :${API_PORT} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo "[API] Server started successfully"
    else
        echo "[API] WARNING: Server may not have started. Check ${LOG_DIR}/api_server.log"
        echo "[API] Continuing anyway - agent will use direct web access..."
    fi
fi

# --- Helper: Run Claude CLI agent for a single OH property ---
run_oh_title_exam() {
    local SUBJECT_ID="$1"
    local LABEL="$2"
    local NAME1="$3"       # Last First format
    local NAME2="$4"       # Last First format
    local ADDRESS="$5"
    local CITY="$6"

    echo ""
    echo "================================================================"
    echo "  STARTING: Subject ${SUBJECT_ID} - ${LABEL}"
    echo "  Name 1 (Last First): ${NAME1}"
    echo "  Name 2 (Last First): ${NAME2}"
    echo "  Address: ${ADDRESS}, ${CITY}, OH"
    echo "================================================================"

    local SUBJECT_LOG="${LOG_DIR}/subject_${SUBJECT_ID}_$(echo "$LABEL" | tr ' /' '__').log"

    # Build the agent prompt — include full Cuyahoga workflow instructions inline
    local AGENT_PROMPT="You are the CURE TitlePro agent for OHIO / CUYAHOGA COUNTY.

CRITICAL: Read BOTH prompt files before starting:
1. General context: ${CA_AGENT_PROMPT_FILE}
2. Cuyahoga-specific workflow: ${OH_AGENT_PROMPT_FILE}

============================================================
TASK: Run a complete Two-Owner Title Search Exam for:
============================================================
Subject ID:      ${SUBJECT_ID}
Label:           ${LABEL}
Primary Name:    ${NAME1}  (Last First format)
Secondary Name:  ${NAME2}  (Last First format)
Address:         ${ADDRESS}, ${CITY}, OH
County:          Cuyahoga
State:           OH
Date Range:      01/01/2000 – $(date +%m/%d/%Y)

============================================================
PHASE 1 — CUYAHOGA COUNTY RECORDER SEARCH
============================================================
Recorder URL: ${CUYAHOGA_RECORDER_URL}

Search for EACH name as both Grantor and Grantee.
Document types: Deed (Warranty/Quit Claim), Mortgage, Release of Mortgage,
Discharge of Mortgage, Satisfaction of Mortgage, Assignment of Mortgage.

Search strategy:
1. Search '${NAME1}' as Grantor → note all instruments
2. Search '${NAME1}' as Grantee → note all instruments
3. Search '${NAME2}' as Grantor → note all instruments
4. Search '${NAME2}' as Grantee → note all instruments
5. If 0 results for full name, retry with last name only

For each instrument found, record:
  - Instrument Number
  - Document Type
  - Recording Date
  - Grantor(s) full name(s)
  - Grantee(s) full name(s)
  - Number of pages

============================================================
PHASE 1b — TAX LOOKUP VIA MYPLACE (EXACTLY 3 STEPS DEEP)
============================================================
Tax Portal URL: ${CUYAHOGA_MYPLACE_URL}

STEP 1: Go to ${CUYAHOGA_MYPLACE_URL}
  - Use WebFetch to load the page
  - Search options: Owner tab, Parcel tab, Address tab
  - Search by Owner: type '${NAME1}' OR search by Address: '${ADDRESS}'
  - Click 'Search Results'

STEP 2: From the results page, click on the matching property.
  - The property detail page has a LEFT SIDEBAR with these sections:
    PROPERTY DATA (General Information, Transfers, Values, Land,
    Building Information, Building Sketch, Other Improvements,
    Permits, Property Summary Report)
    TAXES (Tax By Year, Pay Your Taxes Online)  ← TARGET THIS SECTION
    LEGAL RECORDINGS (Get a Document List)
    ACTIVITY (Informal Reviews, Board of Revisions Cases)

STEP 3: In the left sidebar under TAXES, click 'Tax By Year'
  - This shows the full tax table. Extract ALL of:
    * Parcel Number (format: NNN-NN-NNN)  ← THIS IS THE OH EQUIVALENT OF APN
    * Primary Owner name
    * Property Address (verify it matches ${ADDRESS})
    * Property Class (e.g., SINGLE FAMILY DWELLING)
    * Taxset (city/municipality name)
    * Tax Year (use 2025 Pay 2026 dropdown)
    * Taxable Market Values: Land, Building, Total
    * Taxable Assessed Values: Land, Building, Total
    * Gross Tax amount
    * 920 Reduction amount (Ohio owner-occupancy credit)
    * Half Year Net Taxes → Annual Tax = Half Year Net × 2

  Note: If the page has a Tax Year dropdown, select '2025 Pay 2026'

============================================================
PHASE 2 — GENERATE RAW EXAM REPORT
============================================================
After completing searches, generate these output files in:
  ${TITLEPRO_DIR}/downloaded_doc/${SUBJECT_ID}_$(echo "$LABEL" | tr ' /' '__')/

Required files:
1. RAW_TWO_OWNER_SEARCH_EXAM.md — Full exam using the template in CUYAHOGA_AGENT_PROMPT.md
2. FINAL_REPORT.json — Machine-readable summary with all findings
3. EXECUTION_SUMMARY.md — What was found, what was blocked, next steps

The RAW exam must include:
  - Vesting/ownership section with instrument number
  - Property description with Parcel Number
  - Tax information section (from MyPlace)
  - Open mortgages table (or NONE FOUND)
  - Release/discharge history
  - Deed chain/transfer history
  - Judgment/lien search notes
  - Examiner certification

============================================================
ENVIRONMENT VARIABLES (already set in this shell):
  CUYAHOGA_RECORDER_URL = ${CUYAHOGA_RECORDER_URL}
  CUYAHOGA_MYPLACE_URL  = ${CUYAHOGA_MYPLACE_URL}
  CUYAHOGA_PARCEL_FORMAT = ${CUYAHOGA_PARCEL_FORMAT}
  COUNTY_TAX_URLS_CONFIG = ${COUNTY_TAX_URLS_CONFIG}
============================================================

Working directory: ${TITLEPRO_DIR}

START NOW. Read CUYAHOGA_AGENT_PROMPT.md first, then run all searches and generate the RAW exam."

    echo "[AGENT] Launching Claude CLI for Subject ${SUBJECT_ID}..."
    echo "[AGENT] Logging to: $SUBJECT_LOG"

    "$CLAUDE_CLI" \
        --allowedTools "Bash,Read,Write,WebSearch,WebFetch" \
        -p "$AGENT_PROMPT" \
        2>&1 | tee "$SUBJECT_LOG"

    local EXIT_CODE=${PIPESTATUS[0]}

    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "[SUCCESS] Subject ${SUBJECT_ID} – ${LABEL} completed"
    else
        echo ""
        echo "[ERROR] Subject ${SUBJECT_ID} – ${LABEL} failed (exit code $EXIT_CODE)"
        echo "        Check log: $SUBJECT_LOG"
    fi

    echo ""
    echo "Waiting 10 seconds before next subject..."
    sleep 10
}

# =============================================================================
# SUBJECT 1: KINCANNON / CALLISTER
# Borrowers: Joel R Kincannon & Rebecca L Callister (Married)
# Address: 3352 Dellwood Rd, Cleveland Heights, OH (Cuyahoga County)
# =============================================================================
run_oh_title_exam \
    "1" \
    "Kincannon-Callister 3352 Dellwood Rd Cleveland Heights" \
    "Kincannon Joel" \
    "Callister Rebecca" \
    "3352 Dellwood Rd" \
    "Cleveland Heights"

# =============================================================================
# SUBJECT 2: HENDRICKS
# Borrowers: Barry Hendricks & Kelly A Hendricks (Married)
# Address: 50 Locust Ln, Chagrin Falls, OH (Cuyahoga County)
# =============================================================================
run_oh_title_exam \
    "2" \
    "Hendricks 50 Locust Ln Chagrin Falls" \
    "Hendricks Barry" \
    "Hendricks Kelly" \
    "50 Locust Ln" \
    "Chagrin Falls"

# =============================================================================
# SUBJECT 3: MALDONADO
# Borrowers: Adrian Maldonado & Laurie Maldonado (Married)
# Address: 661 Grayton Rd, Berea, OH (Cuyahoga County)
# =============================================================================
run_oh_title_exam \
    "3" \
    "Maldonado 661 Grayton Rd Berea" \
    "Maldonado Adrian" \
    "Maldonado Laurie" \
    "661 Grayton Rd" \
    "Berea"

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "================================================================"
echo "  MIS PILOT OH EXAM RUN COMPLETE"
echo "  Logs saved to: $LOG_DIR"
echo "  Output reports in: ${TITLEPRO_DIR}/downloaded_doc/"
echo "  $(date)"
echo "================================================================"
echo ""
echo "Check these output files for each subject:"
echo "  downloaded_doc/{Name}/RAW_TWO_OWNER_SEARCH_EXAM.md"
echo "  downloaded_doc/{Name}/FINAL_REPORT.json"
echo "  downloaded_doc/{Name}/EXECUTION_SUMMARY.md"
