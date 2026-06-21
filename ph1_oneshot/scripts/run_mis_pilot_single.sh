#!/bin/bash
# =============================================================================
# MIS PILOT - Run a SINGLE property title exam (for parallel execution)
# Usage: ./run_mis_pilot_single.sh <subject_id>
#   subject_id: 1 = Mastrangelo, 2 = Vondran, 3 = Herron/Hench
# =============================================================================

TITLEPRO_DIR="/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro"
CLAUDE_CLI="/Users/ag/.local/bin/claude"
SUBJECT_ID="${1:-1}"

cd "$TITLEPRO_DIR"
source venv/bin/activate

case "$SUBJECT_ID" in
    1)
        LABEL="Mastrangelo 5915 E Calle Principia Anaheim"
        NAME1="Mastrangelo Anthony"
        NAME2="Mastrangelo Georgiann"
        ADDRESS="5915 E Calle Principia, Anaheim, CA"
        TRUST="MASTRANGELO FAMILY TRUST - search trust name too"
        ;;
    2)
        LABEL="Vondran 22 Calle Cabrillo Foothill Ranch"
        NAME1="Vondran David"
        NAME2="Vondran Theresa"
        ADDRESS="22 Calle Cabrillo, Foothill Ranch, CA"
        TRUST=""
        ;;
    3)
        LABEL="Herron-Hench 21942 Via Del Lago Trabuco Canyon"
        NAME1="Herron David"
        NAME2="Hench Sandra"
        ADDRESS="21942 Via Del Lago, Trabuco Canyon, CA"
        TRUST=""
        ;;
    *)
        echo "Invalid subject ID. Use 1, 2, or 3."
        exit 1
        ;;
esac

AGENT_PROMPT="You are the CURE TitlePro agent. Read ${TITLEPRO_DIR}/docs/AGENT_INIT_PROMPT.md for full instructions.

TASK: Run a complete Two-Owner Title Search Exam for:
Subject: ${LABEL}
Name 1 (Last First): ${NAME1}
Name 2 (Last First): ${NAME2}
Address: ${ADDRESS}
County: Orange, CA
Date Range: 01/01/2000 to $(date +%m/%d/%Y)
${TRUST:+Trust info: $TRUST}

WORKFLOW:
1. Search OC Recorder using:
   python -m titlepro.search.ca_recorder.main -n1 \"${NAME1}\" -n2 \"${NAME2}\" -c orange --start-date 01/01/2000
2. Identify vesting deed & key documents
3. Download from TitlePro247
4. Extract APN, legal description, grantor/grantee, loan amounts
5. Look up property taxes via APN (Orange County Treasurer)
6. Generate RAW_TWO_OWNER_SEARCH_EXAM.md
7. Generate Title_Examination_Notes.md
Save to: ${TITLEPRO_DIR}/downloaded_doc/

Start immediately - run all searches and generate all reports."

echo "Starting title exam for Subject ${SUBJECT_ID}: ${LABEL}"
"$CLAUDE_CLI" \
    --allowedTools "Bash,Read,Write,WebSearch,WebFetch" \
    -p "$AGENT_PROMPT"
