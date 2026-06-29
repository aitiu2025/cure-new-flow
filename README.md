# TitlePro - CURE Title Examination System

Automated property title search and examination system for Florida and California County Recorders. Part of the **CURE** (Comprehensive Understanding & Risk Evaluation) title examination workflow.

## Features

- Automated Orange County Recorder website searches
- Multi-county support (21+ California counties via RecorderWorks and Tyler platforms)
- Florida county support (Broward, Miami-Dade, Duval, Volusia, and more via AcclaimWeb HTTP)
- TitlePro247 Selenium-based document download automation
- Document deduplication across multiple owner names
- Property verification and cross-reference checking
- Deed chain analysis and lien attribution
- Report generation (Markdown, JSON, PDF)
- Tax lookup automation with CAPTCHA solving
- NAT integration — receives jobs from NAT and POSTs results back via callback

---

## Project Structure

```
titlePro/
├── src/titlepro/           # Main package
│   ├── api/                # Flask REST API server (port 5555)
│   │   ├── server.py       # Main server entry point
│   │   └── nat_audit.html  # NAT Audit Panel UI
│   ├── core/               # Core analysis: classification, dedup, workflow
│   ├── download/           # Selenium document downloader
│   ├── search/             # Search automation & county recorder framework
│   │   └── ca_recorder/    # Multi-county CA recorder search
│   │       ├── captcha/    # CAPTCHA solving
│   │       └── counties/   # County implementations & configs
│   ├── verification/       # Property verification & cross-reference
│   ├── reports/            # Report generation (MD, JSON, PDF)
│   └── tax/                # Property tax lookup
├── tests/                  # Test suite
│   ├── unit/               # Unit tests
│   ├── integration/        # Integration & county tests
│   └── fixtures/           # Test data
├── config/                 # Config templates (copy & fill in secrets)
├── docs/                   # Implementation docs & guides
├── requirements.txt
└── pyproject.toml
```

---

## AWS Server Setup Guide (Infrastructure Team)

This section covers everything needed to deploy CURE TitlePro on an AWS EC2 server.

### 1. System Requirements

| Item | Minimum | Recommended |
|---|---|---|
| EC2 Instance | t3.medium (2 vCPU, 4 GB RAM) | t3.large (2 vCPU, 8 GB RAM) |
| OS | Amazon Linux 2023 / CentOS 7+ | Amazon Linux 2023 |
| Python | 3.10 | 3.11 |
| Disk | 20 GB | 40 GB (PDFs accumulate) |

> Browser automation (Selenium + Chrome) is memory-heavy. **Do not use t3.micro or t3.small.**

---

### 2. OS-Level Dependencies

Run as root or with `sudo`:

```bash
# Update system packages
sudo dnf update -y

# Python 3.11
sudo dnf install -y python3.11 python3.11-pip python3.11-devel

# Git
sudo dnf install -y git

# Tesseract OCR (required for CAPTCHA image processing)
sudo dnf install -y tesseract tesseract-langpack-eng

# Google Chrome (for Selenium recorder search)
wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
sudo dnf install -y google-chrome-stable_current_x86_64.rpm

# Headless Chrome dependencies
sudo dnf install -y \
    xorg-x11-server-Xvfb \
    libX11 libXcomposite libXcursor libXdamage libXext \
    libXi libXrandr libXrender libXtst pango atk at-spi2-atk \
    cups-libs libdrm mesa-libgbm libxkbcommon \
    nss nspr alsa-lib

# curl dev libs (required by curl_cffi for Cloudflare counties)
sudo dnf install -y libcurl-devel openssl-devel

# Build tools (for compiling pip packages)
sudo dnf install -y gcc gcc-c++ make
```

---

### 3. Python Virtual Environment

```bash
cd /opt/titlepro

# Create virtual environment
python3.11 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel
```

---

### 4. Project Installation

```bash
# Clone the repository (or extract the uploaded zip)
git clone <REPO_URL> /opt/titlepro
cd /opt/titlepro

# Activate the virtual environment
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Install the project package (enables titlepro.* imports from any directory)
pip install -e .

# Verify the installation
python -c "import titlepro; print('titlepro OK')"
python -c "import flask; print('Flask OK')"
python -c "import curl_cffi; print('curl_cffi OK')"
python -c "import fitz; print('PyMuPDF OK')"
```

---

### 5. Configuration Files

All config files live in `config/`. The following must exist before starting the server:

| File | Action Required |
|---|---|
| `config/secrets.json` | Copy from `secrets.json.example`, fill in TitlePro247 credentials |
| `config/county_property_appraiser_urls.json` | Already in repo — do not edit |
| `config/county_tax_urls.json` | Already in repo — do not edit |
| `config/tax_recipes/` | Already in repo — read-only |

```bash
cp config/secrets.json.example config/secrets.json
# Edit config/secrets.json and fill in real credentials (see Section 7)
chmod 600 config/secrets.json
```

---

### 6. Environment Variables (.env)

Create `.env` at the project root. **Never commit this file to git.**

```bash
# Create the .env file
nano /opt/titlepro/.env
```

Paste and fill in the following:

```env
# ── Anthropic Claude AI ────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXX

# ── CAPTCHA solving (2captcha.com — requires funded account) ───────────────
CAPTCHA_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
CAPTCHA_SERVICE=2captcha

# ── NAT Integration ────────────────────────────────────────────────────────
# URL where CURE POSTs results back to NAT after a title run completes.
# Same server:    http://localhost/api/nat/cure-result
# Separate server: http://<NAT-SERVER-IP>/api/nat/cure-result
NAT_CALLBACK_URL=http://localhost/api/nat/cure-result

# Shared secret — MUST match Cure.authToken in NAT's app_local.php exactly.
# Generate a strong value: python3 -c "import secrets; print(secrets.token_hex(32))"
NAT_AUTH_TOKEN=cure-nat-shared-secret-change-me

NAT_AI_ENGINE=claude

# ── DataTrace document drop-off folder ────────────────────────────────────
# NAT drops DataTrace documents here; CURE reads from here.
# Linux/AWS:  /home/natdt/dt-dropoff
# Windows dev: C:\dt-dropoff
DT_DROPOFF_BASE=/home/natdt/dt-dropoff

# ── Claude model (optional — defaults shown) ──────────────────────────────
CLAUDE_MODEL=claude-sonnet-4-6
MAX_CONCURRENT_NAT_JOBS=3
```

**Key variables explained:**

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — get from console.anthropic.com |
| `CAPTCHA_API_KEY` | 2Captcha key — requires $3–5 balance at 2captcha.com |
| `NAT_CALLBACK_URL` | Where CURE sends results back to NAT |
| `NAT_AUTH_TOKEN` | Shared secret — must match NAT's `app_local.php` |
| `DT_DROPOFF_BASE` | Folder shared between NAT and CURE for DataTrace files |
| `MAX_CONCURRENT_NAT_JOBS` | Concurrent title job limit (default: 3) |

---

### 7. Secrets — TitlePro247 Credentials

File: `config/secrets.json`

```json
{
    "TITLEPRO_USERNAME": "your_titlepro247_username",
    "TITLEPRO_PASSWORD": "your_titlepro247_password",
    "TITLEPRO_WEBSITE": "https://www.titlepro247.com/DocumentRetrieval/"
}
```

Set file permissions after editing:

```bash
chmod 600 config/secrets.json
```

---

### 8. Folder Permissions & Storage

```bash
# DataTrace document drop-off folder (shared with NAT)
sudo mkdir -p /home/natdt/dt-dropoff
sudo chown <app_user>:<app_user> /home/natdt/dt-dropoff
sudo chmod 755 /home/natdt/dt-dropoff

# Downloaded PDFs folder (inside project)
mkdir -p /opt/titlepro/src/titlepro/api/downloaded_doc

# Make sure the app user owns the entire project
sudo chown -R <app_user>:<app_user> /opt/titlepro
```

---

### 9. Running the Server

**Manual / foreground (for testing only):**

```bash
cd /opt/titlepro
source venv/bin/activate
python src/titlepro/api/server.py
```

**Health check:**

```bash
curl http://localhost:5555/status
```

Expected response: `{"status": "online", "message": "TitlePro API Server is running", ...}`

**UI access:**
- CURE UI: `http://<EC2-PUBLIC-IP>:5555/`
- NAT Audit Panel: `http://<EC2-PUBLIC-IP>:5555/nat-audit`

---

### 10. Running as a systemd Service (Production)

Create the service file:

```bash
sudo nano /etc/systemd/system/titlepro.service
```

Paste:

```ini
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
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable titlepro
sudo systemctl start titlepro
sudo systemctl status titlepro
```

View logs:

```bash
sudo journalctl -u titlepro -f
```

---

### 11. Firewall / EC2 Security Group Rules

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 5555 | TCP | NAT server's private IP only | CURE TitlePro API |
| 22 | TCP | Infra team's IP only | SSH |
| 80 / 443 | TCP | NAT server IP (or VPC CIDR) | Optional — if Nginx proxy is added |

> **Do not expose port 5555 to the public internet.** CURE should only be reachable from the NAT server's IP or within the VPC.

---

### 12. API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status` | Health check |
| GET | `/` | CURE UI |
| GET | `/nat-audit` | NAT Audit Panel UI |
| POST | `/search-recorder` | Search county recorder by owner name |
| GET | `/search-recorder-status/<job_id>` | Poll background search job |
| POST | `/search-recorder-multiname` | Multi-name search with deduplication |
| POST | `/download` | Download a single document |
| GET | `/download/<job_id>` | Check single download status |
| POST | `/batch-download` | Batch download multiple documents |
| POST | `/batch-download-deduplicated` | Deduplicated batch download |
| GET | `/batch-status/<batch_id>` | Poll batch download status |
| POST | `/check-files` | Check which documents exist on disk |
| GET | `/api/counties` | List all supported counties |
| POST | `/analyze-documents` | AI-powered document analysis |
| POST | `/tax-lookup` | Property tax lookup by APN |
| GET | `/pdf/<owner>/<filename>` | Serve a downloaded PDF |

---

### 13. NAT ↔ CURE Integration

1. NAT sends a POST to CURE with case details (owner name, address, county, etc.)
2. CURE runs the title search pipeline and generates the report.
3. CURE POSTs results back to NAT at `NAT_CALLBACK_URL` with `X-Cure-Auth: <NAT_AUTH_TOKEN>`.

**Items that must be aligned with the NAT developer:**

- `NAT_CALLBACK_URL` in `.env` must match NAT's listening endpoint.
- `NAT_AUTH_TOKEN` in `.env` must **exactly** match `Cure.authToken` in NAT's `app_local.php`.
- `DT_DROPOFF_BASE` must point to a folder both NAT and CURE can read/write.
- Port 5555 must be reachable from the NAT server.

---

### 14. Troubleshooting

**Server does not start / ImportError**
```bash
pip install -r requirements.txt
```

**`curl_cffi` fails to install**
```bash
sudo dnf install -y libcurl-devel openssl-devel
pip install curl_cffi
```

**`tesseract not found`**
```bash
sudo dnf install -y tesseract tesseract-langpack-eng
```

**Selenium / Chrome crash on headless server**
```bash
sudo dnf install -y xorg-x11-server-Xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 &
```

**CAPTCHA errors**
- Verify `CAPTCHA_API_KEY` in `.env` is correct.
- Check 2captcha.com account balance (minimum $3–5 required).

**NAT callback returns 401 Unauthorized**
- `NAT_AUTH_TOKEN` in `.env` does not match `Cure.authToken` in NAT's `app_local.php`.

**`DT_DROPOFF_BASE` folder not found**
```bash
sudo mkdir -p /home/natdt/dt-dropoff
sudo chown <app_user>:<app_user> /home/natdt/dt-dropoff
```

**Port 5555 already in use**
```bash
sudo lsof -i :5555
sudo kill -9 <PID>
```

**Anthropic API errors**
```bash
curl https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01"
```

---

## Local Development Setup

```bash
# Clone and install
git clone <repo-url>
cd titlePro
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
pip install -e ".[dev]"

# Copy and fill in config files
cp config/secrets.json.example config/secrets.json
# Edit config/secrets.json with TitlePro247 credentials

# Copy .env and fill in API keys
cp .env.example .env   # or create .env manually

# Start the API server
python src/titlepro/api/server.py

# Run tests
pytest tests/
pytest tests/unit/
pytest tests/integration/
```

> **Never commit `config/secrets.json` or `.env` to git.**

---

## CURE Workflow

1. **Initial Search** — Search county recorder by owner name(s)
2. **Vesting Deed ID** — Identify current vesting deed from results
3. **Name Extraction** — Extract all grantees from vesting deed
4. **Discovery** — Auto-search any newly discovered names
5. **Deduplication** — Combine & deduplicate results across all names
6. **Verification** — Verify documents match the target property
7. **Analysis** — Classify documents, attribute liens to parties
8. **Report** — Generate Two Owner Search Exam report (RAW + Title + OnE)

---

*For questions contact: apatle@tiuconsulting.com*
