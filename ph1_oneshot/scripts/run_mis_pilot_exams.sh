#!/bin/bash
# =============================================================================
# MIS PILOT - CA Orange County Title Exam Orchestrator
# Runs Claude CLI agent for 3 CA Orange County properties from the MIS Pilot sheet
# Generated: 2026-04-03
# Properties: Mastrangelo (Trust), Vondran, Herron/Hench
# =============================================================================

set -e

# --- Config ---
TITLEPRO_DIR="/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
CLAUDE_CLI="/Users/ag/.local/bin/claude"
API_PORT=5555
LOG_DIR="${TITLEPRO_DIR}/logs/mis_pilot_$(date +%Y%m%d_%H%M%S)"
AGENT_PROMPT_FILE="${TITLEPRO_DIR}/docs/AGENT_INIT_PROMPT.md"

mkdir -p "$LOG_DIR"

echo "================================================================"
echo "  MIS PILOT - CA Orange County Title Exam Runner"
echo "  Date: $(date)"
echo "  Log dir: $LOG_DIR"
echo "================================================================"

# --- Step 1: Activate venv & install dependencies ---
echo ""
echo "[SETUP] Activating virtual environment..."
cd "$TITLEPRO_DIR"
source venv/bin/activate

# Ensure titlepro package is installed in venv
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
        echo "[API] ERROR: Server failed to start. Check ${LOG_DIR}/api_server.log"
        exit 1
    fi
fi

# --- Helper: Run Claude CLI agent for a single property ---
run_title_exam() {
    local SUBJECT_ID="$1"
    local LABEL="$2"
    local NAME1="$3"
    local NAME2="$4"
    local ADDRESS="$5"
    local TRUST_INFO="$6"

    echo ""
    echo "================================================================"
    echo "  STARTING: Subject ${SUBJECT_ID} - ${LABEL}"
    echo "  Name 1 (Last First): ${NAME1}"
    echo "  Name 2 (Last First): ${NAME2}"
    echo "  Address: ${ADDRESS}"
    if [ -n "$TRUST_INFO" ]; then
        echo "  Trust: ${TRUST_INFO}"
    fi
    echo "================================================================"

    local SUBJECT_LOG="${LOG_DIR}/subject_${SUBJECT_ID}_$(echo "$LABEL" | tr ' ' '_').log"

    # Build the agent prompt
    local AGENT_PROMPT="You are the CURE TitlePro agent. Read the AGENT_INIT_PROMPT.md at ${AGENT_PROMPT_FILE} for full instructions.

TASK: Run a complete Two-Owner Title Search Exam for the following property:

Subject ID: ${SUBJECT_ID}
Label: ${LABEL}
Primary Name (Last First format): ${NAME1}
Secondary Name (Last First format): ${NAME2}
Property Address: ${ADDRESS}
County: Orange
State: CA
Start Date: 01/01/2000
End Date: $(date +%m/%d/%Y)"

    if [ -n "$TRUST_INFO" ]; then
        AGENT_PROMPT="${AGENT_PROMPT}
Trust / Trustee Info: ${TRUST_INFO}
NOTE: For trust properties, search ALL of: the trustee name(s) AND the trust name itself."
    fi

    AGENT_PROMPT="${AGENT_PROMPT}

WORKFLOW TO FOLLOW:
1. Run PHASE 1 - Search OC Recorder for all names (Grantor + Grantee searches)
   - Use: python -m titlepro.search.ca_recorder.main -n1 \"${NAME1}\" -n2 \"${NAME2}\" -c orange --start-date 01/01/2000 -o results_${SUBJECT_ID}.json
   - Also run individual name searches if needed
2. Identify vesting deed from results
3. Download key documents from TitlePro247 (use selenium downloader or API)
4. Extract: APN, legal description, grantor/grantee names, loan amounts, recording dates
5. Search for current property tax info using the APN (OC Treasurer-Tax Collector)
6. Run PHASE 2 - Generate RAW_TWO_OWNER_SEARCH_EXAM.md report
7. Generate final Title Examination Notes PDF
8. Save all outputs to: ${TITLEPRO_DIR}/downloaded_doc/

Working directory: ${TITLEPRO_DIR}

Start now. Run all searches and generate both the RAW exam file and Title Examination Notes."

    echo "[AGENT] Launching Claude CLI for Subject ${SUBJECT_ID}..."
    echo "[AGENT] Logging to: $SUBJECT_LOG"

    "$CLAUDE_CLI" \
        --allowedTools "Bash,Read,Write,WebSearch,WebFetch" \
        -p "$AGENT_PROMPT" \
        2>&1 | tee "$SUBJECT_LOG"

    local EXIT_CODE=${PIPESTATUS[0]}

    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "[SUCCESS] Subject ${SUBJECT_ID} - ${LABEL} completed"
    else
        echo ""
        echo "[ERROR] Subject ${SUBJECT_ID} - ${LABEL} failed with exit code $EXIT_CODE"
        echo "        Check log: $SUBJECT_LOG"
    fi

    echo ""
    echo "Waiting 10 seconds before next subject..."
    sleep 10
}

# =============================================================================
# SUBJECT 1: MASTRANGELO (TRUST)
# Borrowers: Anthony Michael Mastrangelo & Georgiann Irene Mastrangelo
# Address: 5915 E Calle Principia, Anaheim, CA (Orange County)
# Note: Trustees of the Mastrangelo Family Trust
# =============================================================================
run_title_exam \
    "1" \
    "Mastrangelo 5915 E Calle Principia Anaheim" \
    "Mastrangelo Anthony" \
    "Mastrangelo Georgiann" \
    "5915 E Calle Principia, Anaheim, CA" \
    "ANTHONY MICHAEL MASTRANGELO AND GEORGIANN IRENE MASTRANGELO TRUSTEES OF THE MASTRANGELO FAMILY TRUST - also search: Mastrangelo Family Trust"

# =============================================================================
# SUBJECT 2: VONDRAN
# Borrowers: David John Vondran & Theresa Ann Vondran (Married)
# Address: 22 Calle Cabrillo, Foothill Ranch, CA (Orange County)
# =============================================================================
run_title_exam \
    "2" \
    "Vondran 22 Calle Cabrillo Foothill Ranch" \
    "Vondran David" \
    "Vondran Theresa" \
    "22 Calle Cabrillo, Foothill Ranch, CA" \
    ""

# =============================================================================
# SUBJECT 3: HERRON / HENCH
# Borrowers: David R Herron & Sandra D Hench (Married)
# Address: 21942 Via Del Lago, Trabuco Canyon, CA (Orange County)
# =============================================================================
run_title_exam \
    "3" \
    "Herron-Hench 21942 Via Del Lago Trabuco Canyon" \
    "Herron David" \
    "Hench Sandra" \
    "21942 Via Del Lago, Trabuco Canyon, CA" \
    ""

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "================================================================"
echo "  MIS PILOT EXAM RUN COMPLETE"
echo "  Logs saved to: $LOG_DIR"
echo "  Output reports in: ${TITLEPRO_DIR}/downloaded_doc/"
echo "  $(date)"
echo "================================================================"
echo ""
echo "Check these output files for each subject:"
echo "  downloaded_doc/{Name}/RAW_TWO_OWNER_SEARCH_EXAM.md"
echo "  downloaded_doc/{Name}/Title_Examination_Notes.md"
echo "  downloaded_doc/{Name}/FINAL_REPORT.json"
