================================================================================
  CURE TitlePro — AWS Server Setup & Deployment Guide
  For: Infrastructure / DevOps Team
  Application owner: TIU Consulting
================================================================================

TABLE OF CONTENTS
-----------------
1.  Overview
2.  System Requirements (AWS EC2)
3.  OS-Level Dependencies
4.  Python Setup
5.  Project Installation
6.  Configuration Files
7.  Environment Variables (.env)
8.  Secrets (credentials)
9.  Folder Permissions & Storage
10. Running the Server
11. Running as a systemd Service (recommended for production)
12. Firewall / Security Group Rules
13. API Endpoints & Health Check
14. NAT Integration Notes
15. Troubleshooting


================================================================================
1. OVERVIEW
================================================================================

CURE TitlePro is a Python/Flask backend server that automates property title
searches across Florida and California county recorders. It exposes a REST API
consumed by the NAT (Network Automation Toolkit) front-end application.

The server runs on port 5555 by default.

Key tech stack:
  - Python 3.10+
  - Flask (web framework)
  - Selenium + ChromeDriver (browser automation for recorder search)
  - curl_cffi (HTTP impersonation for Cloudflare-protected counties)
  - Anthropic Claude API (AI report generation)
  - PyMuPDF / Tesseract (PDF processing / OCR)


================================================================================
2. SYSTEM REQUIREMENTS (AWS EC2)
================================================================================

Recommended instance: t3.medium or larger (2 vCPU, 4 GB RAM minimum)
  - Browser automation (Selenium/Chrome) is memory-heavy.
  - t3.large (2 vCPU, 8 GB RAM) is preferred for production workloads.

OS: Amazon Linux 2023 (CentOS 7/8 also supported)
Disk: 20 GB minimum (downloaded PDFs accumulate in /home/natdt/dt-dropoff)
Python: 3.10, 3.11, or 3.12


================================================================================
3. OS-LEVEL DEPENDENCIES
================================================================================

Run as root or with sudo:

    # Update system packages
    sudo dnf update -y          # Amazon Linux 2023
    # OR
    sudo yum update -y          # CentOS/Amazon Linux 2

    # Python 3.10+ (Amazon Linux 2023 ships Python 3.9 by default; upgrade if needed)
    sudo dnf install -y python3.11 python3.11-pip python3.11-devel

    # Git
    sudo dnf install -y git

    # Tesseract OCR (required by pytesseract for CAPTCHA image processing)
    sudo dnf install -y tesseract tesseract-langpack-eng

    # Chrome/Chromium for Selenium browser automation
    # Option A: Google Chrome stable
    sudo dnf install -y wget
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
    sudo dnf install -y google-chrome-stable_current_x86_64.rpm

    # Option B: Chromium (if Chrome RPM unavailable)
    sudo dnf install -y chromium

    # Dependencies for headless Chrome
    sudo dnf install -y \
        xorg-x11-server-Xvfb \
        libX11 libXcomposite libXcursor libXdamage libXext \
        libXi libXrandr libXrender libXtst pango atk at-spi2-atk \
        cups-libs libdrm mesa-libgbm libxkbcommon \
        nss nspr alsa-lib

    # curl dev libs (required by curl_cffi)
    sudo dnf install -y libcurl-devel openssl-devel

    # Build tools (for compiling some pip packages)
    sudo dnf install -y gcc gcc-c++ make


================================================================================
4. PYTHON SETUP
================================================================================

It is strongly recommended to run the application inside a Python virtual
environment to avoid package conflicts.

    # Create a virtual environment (run from the project root)
    python3.11 -m venv venv

    # Activate it
    source venv/bin/activate

    # Upgrade pip
    pip install --upgrade pip setuptools wheel


================================================================================
5. PROJECT INSTALLATION
================================================================================

    # Clone the repository (or upload the project zip and extract)
    git clone <REPO_URL> /opt/titlepro
    cd /opt/titlepro

    # Activate the virtual environment (if not already active)
    source venv/bin/activate

    # Install all dependencies
    pip install -r requirements.txt

    # Install the project package itself in editable mode
    # (this registers the 'titlepro' package so imports work from any directory)
    pip install -e .

    # Verify the installation
    python -c "import titlepro; print('titlepro package OK')"
    python -c "import flask; print('Flask OK')"
    python -c "import curl_cffi; print('curl_cffi OK')"
    python -c "import fitz; print('PyMuPDF OK')"


================================================================================
6. CONFIGURATION FILES
================================================================================

All config files live in:  <project_root>/config/

Files that MUST exist before the server starts:

  config/secrets.json
    - TitlePro247 login credentials (see Section 8 below)
    - Copy from template:  cp config/secrets.json.example config/secrets.json
    - Fill in real credentials.

  config/county_property_appraiser_urls.json
    - Already committed in the repo. Do not modify unless adding a new county.

  config/county_tax_urls.json
    - Already committed in the repo. Do not modify unless adding a new county.

  config/tax_recipes/
    - Pre-built JSON recipes for tax lookups per county.
    - Already committed. Read-only — do not edit.

  .env  (project root)
    - Environment secrets. See Section 7.
    - NEVER commit .env to git.


================================================================================
7. ENVIRONMENT VARIABLES (.env)
================================================================================

Create the file at the project root:  <project_root>/.env

Copy the template and fill in values:

    cp .env.example .env    # if an example exists
    # OR create from scratch with the variables listed below

Required variables
------------------

  ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXX
    Your Anthropic API key for Claude AI report generation.
    Get it from: https://console.anthropic.com/

  CAPTCHA_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    2Captcha API key for solving reCAPTCHA on county recorder portals.
    Get it from: https://2captcha.com (requires a funded account, $3-5 minimum)

  CAPTCHA_SERVICE=2captcha
    CAPTCHA service provider. Options: "2captcha" or "anticaptcha"

NAT Integration variables
--------------------------

  NAT_CALLBACK_URL=http://<NAT-SERVER-HOST>/api/nat/cure-result
    URL where CURE posts results back to NAT after a title run completes.
    - Local dev:     http://localhost/nat_2/api/nat/cure-result
    - UAT/Prod:      http://localhost/api/nat/cure-result
      (NAT is the root app on UAT — no /nat_2 subfolder)
    Change this to point at the actual NAT server hostname/IP on AWS.

  NAT_AUTH_TOKEN=cure-nat-shared-secret-change-me
    Shared secret used in the X-Cure-Auth HTTP header for NAT callbacks.
    MUST match the value of Cure.authToken in NAT's app_local.php.
    Generate a strong random value for production, e.g.:
      python3 -c "import secrets; print(secrets.token_hex(32))"

  NAT_AI_ENGINE=claude
    AI engine for report generation. Default: claude

  DT_DROPOFF_BASE=/home/natdt/dt-dropoff
    Base folder where NAT drops DataTrace documents for CURE to process.
    On Linux/AWS this is typically: /home/natdt/dt-dropoff
    On Windows dev it was: C:\dt-dropoff
    Make sure this directory exists and is writable by the app user.

Optional variables
------------------

  CLAUDE_MODEL=claude-sonnet-4-6
    Claude model ID to use. Default: claude-sonnet-4-6

  CLAUDE_CLI_PATH=/usr/local/bin/claude
    Path to the Claude CLI binary if used for sub-process invocations.

  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4o
    Only needed if AI_ENGINE is set to openai.

  GOOGLE_API_KEY=...
  GOOGLE_MODEL=gemini-1.5-pro
    Only needed if AI_ENGINE is set to google.

  GROQ_API_KEY=...
  GROQ_MODEL=llama3-70b-8192
    Only needed if AI_ENGINE is set to groq.

  CUYAHOGA_EMAIL=...
  CUYAHOGA_PASSWORD=...
    Credentials for Cuyahoga County (Ohio) portal, if that county is in scope.

  MAX_CONCURRENT_NAT_JOBS=3
    Maximum number of simultaneous NAT title jobs. Default: 3

Full .env example (replace all <...> values):

    ANTHROPIC_API_KEY=sk-ant-api03-<YOUR_KEY>
    CAPTCHA_API_KEY=<YOUR_2CAPTCHA_KEY>
    CAPTCHA_SERVICE=2captcha
    NAT_CALLBACK_URL=http://<NAT_HOST>/api/nat/cure-result
    NAT_AUTH_TOKEN=<STRONG_RANDOM_SECRET>
    NAT_AI_ENGINE=claude
    DT_DROPOFF_BASE=/home/natdt/dt-dropoff
    CLAUDE_MODEL=claude-sonnet-4-6
    MAX_CONCURRENT_NAT_JOBS=3


================================================================================
8. SECRETS (credentials)
================================================================================

File:  config/secrets.json
Template at:  config/secrets.json.example

This file holds TitlePro247 login credentials used to download deed documents.

    {
        "TITLEPRO_USERNAME": "your_titlepro247_username",
        "TITLEPRO_PASSWORD": "your_titlepro247_password",
        "TITLEPRO_WEBSITE": "https://www.titlepro247.com/DocumentRetrieval/"
    }

Steps:
  1. Copy the example:  cp config/secrets.json.example config/secrets.json
  2. Edit config/secrets.json and fill in the real TitlePro247 credentials.
  3. Set file permissions so only the app user can read it:
        chmod 600 config/secrets.json


================================================================================
9. FOLDER PERMISSIONS & STORAGE
================================================================================

Downloaded PDFs and case folders are written to:
  <project_root>/src/titlepro/api/downloaded_doc/

DataTrace document drop-off folder (set in DT_DROPOFF_BASE):
  /home/natdt/dt-dropoff/     (create this directory if it does not exist)

Commands to set up storage:

    # Create the dt-dropoff folder
    sudo mkdir -p /home/natdt/dt-dropoff
    sudo chown <app_user>:<app_user> /home/natdt/dt-dropoff
    sudo chmod 755 /home/natdt/dt-dropoff

    # Create the downloaded_doc folder inside the project
    mkdir -p /opt/titlepro/src/titlepro/api/downloaded_doc

    # Make sure the app user owns the entire project directory
    sudo chown -R <app_user>:<app_user> /opt/titlepro


================================================================================
10. RUNNING THE SERVER
================================================================================

Manual / foreground run (for testing):

    cd /opt/titlepro
    source venv/bin/activate
    python src/titlepro/api/server.py

The server starts on http://0.0.0.0:5555 by default.

Test the health check endpoint:
    curl http://localhost:5555/status

Expected response (truncated):
    {"status": "online", "message": "TitlePro API Server is running", ...}

Access the CURE UI in a browser:
    http://<EC2-PUBLIC-IP>:5555/

Access the NAT Audit Panel:
    http://<EC2-PUBLIC-IP>:5555/nat-audit


================================================================================
11. RUNNING AS A systemd SERVICE (RECOMMENDED FOR PRODUCTION)
================================================================================

Create a systemd unit file:

    sudo nano /etc/systemd/system/titlepro.service

Paste the following (adjust paths and user as needed):

    [Unit]
    Description=CURE TitlePro API Server
    After=network.target

    [Service]
    Type=simple
    User=<app_user>
    WorkingDirectory=/opt/titlepro
    EnvironmentFile=/opt/titlepro/.env
    ExecStart=/opt/titlepro/venv/bin/python src/titlepro/api/server.py
    Restart=on-failure
    RestartSec=10
    StandardOutput=journal
    StandardError=journal

    [Install]
    WantedBy=multi-user.target

Enable and start the service:

    sudo systemctl daemon-reload
    sudo systemctl enable titlepro
    sudo systemctl start titlepro

Check status:
    sudo systemctl status titlepro

View logs:
    sudo journalctl -u titlepro -f


================================================================================
12. FIREWALL / SECURITY GROUP RULES
================================================================================

Add the following inbound rules to the EC2 Security Group:

  Port 5555 (TCP)
    - Source: NAT server's private IP (or VPC CIDR)
    - Purpose: CURE TitlePro API

  Port 22 (TCP)
    - Source: Infra team's IP only
    - Purpose: SSH access

  Port 80 / 443 (TCP) — only if you put Nginx/Apache in front
    - Source: 0.0.0.0/0 or NAT server IP

  IMPORTANT: Do NOT expose port 5555 to the public internet.
  CURE should only be reachable from the NAT server's IP.

If NAT and CURE run on the same EC2 instance, no inbound rule for 5555 is
needed — traffic stays on localhost.


================================================================================
13. API ENDPOINTS & HEALTH CHECK
================================================================================

After the server starts, the following endpoints are available:

  GET  /status                    — Health check (always returns HTTP 200 if up)
  GET  /                          — Serves the CURE UI (CURE.html)
  GET  /nat-audit                 — Serves the NAT Audit Panel UI

  POST /search-recorder           — Search county recorder by owner name
  GET  /search-recorder-status/<job_id>  — Poll background search job status
  POST /search-recorder-multiname — Search with multiple owner names (deduped)

  POST /download                  — Download a single document
  GET  /download/<job_id>         — Check single download job status
  POST /batch-download            — Batch download multiple documents
  POST /batch-download-deduplicated — Deduplicated batch download
  GET  /batch-status/<batch_id>   — Poll batch download status
  POST /check-files               — Check which documents already exist on disk

  GET  /api/counties              — List all supported counties

  POST /analyze-documents         — AI-powered document analysis (Claude)
  POST /tax-lookup                — Property tax lookup by APN

  GET  /pdf/<owner>/<filename>    — Serve a downloaded PDF to the browser

Quick smoke test after deploy:

    curl -s http://localhost:5555/status | python3 -m json.tool


================================================================================
14. NAT INTEGRATION NOTES
================================================================================

CURE integrates with NAT (the PHP front-end) as follows:

1. NAT sends a POST request to CURE with case details (owner name, address, etc.)
2. CURE processes the title search (recorder + AI analysis).
3. CURE POSTs the result back to NAT at NAT_CALLBACK_URL using NAT_AUTH_TOKEN
   in the X-Cure-Auth header.

Key config items to align with the NAT developer:

  a) NAT_CALLBACK_URL in .env must match NAT's listening endpoint.
     - If NAT runs on the same server: http://localhost/api/nat/cure-result
     - If separate servers: http://<NAT-SERVER-IP>/api/nat/cure-result

  b) NAT_AUTH_TOKEN in .env must EXACTLY match Cure.authToken in NAT's
     app_local.php. Mismatched tokens cause 401 errors on callbacks.

  c) DT_DROPOFF_BASE in .env must point to the shared folder where NAT drops
     DataTrace documents. Both NAT and CURE must have read/write access.
     Typical path on CentOS/AWS: /home/natdt/dt-dropoff

  d) The CURE server port (5555) must be reachable from NAT. If they are on
     different servers, ensure the Security Group allows traffic from NAT's IP.


================================================================================
15. TROUBLESHOOTING
================================================================================

--- Server does not start ---
  Check:
    python src/titlepro/api/server.py
  Look for ImportError messages. Usually means a pip package is missing.
  Fix: pip install -r requirements.txt

--- "curl_cffi" import error ---
  curl_cffi requires libcurl with TLS support.
  Fix: sudo dnf install -y libcurl-devel openssl-devel && pip install curl_cffi

--- "pytesseract" / "tesseract not found" error ---
  Fix: sudo dnf install -y tesseract tesseract-langpack-eng

--- Selenium / ChromeDriver error ---
  webdriver-manager auto-downloads ChromeDriver matching the installed Chrome.
  If Chrome is not in PATH: sudo dnf install -y google-chrome-stable
  On headless servers, Chrome needs Xvfb:
    sudo dnf install -y xorg-x11-server-Xvfb
    export DISPLAY=:99
    Xvfb :99 -screen 0 1024x768x24 &

--- CAPTCHA errors ---
  Ensure CAPTCHA_API_KEY in .env is valid and the 2captcha account has balance.
  Test at: https://2captcha.com/enterpage

--- NAT callback fails (401 Unauthorized) ---
  Check that NAT_AUTH_TOKEN in .env matches Cure.authToken in NAT's app_local.php.

--- DT_DROPOFF_BASE folder not found ---
  Create it: sudo mkdir -p /home/natdt/dt-dropoff
  Check permissions: ls -la /home/natdt/

--- Port 5555 already in use ---
  Find the process: sudo lsof -i :5555
  Kill it: sudo kill -9 <PID>

--- Anthropic API errors ---
  Check ANTHROPIC_API_KEY in .env is correct and account has credits.
  Test: curl https://api.anthropic.com/v1/models \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01"

--- Logs ---
  If running as systemd service: sudo journalctl -u titlepro -f --since "1 hour ago"
  If running manually: output goes to stdout/stderr in the terminal.


================================================================================
  END OF DOCUMENT
  For questions contact: apatle@tiuconsulting.com
================================================================================
