# TitlePro - CURE Title Examination System

Automated property title search and examination system for California County Recorders. Part of the **CURE** (Comprehensive Understanding & Risk Evaluation) title examination workflow.

## Features

- Automated Orange County Recorder website searches
- Multi-county support (21+ California counties via RecorderWorks and Tyler platforms)
- TitlePro247 Selenium-based document download automation
- Document deduplication across multiple owner names
- Property verification and cross-reference checking
- Deed chain analysis and lien attribution
- Report generation (Markdown, JSON, PDF)
- Tax lookup automation with CAPTCHA solving

## Project Structure

```
titlePro/
├── src/titlepro/           # Main package
│   ├── api/                # Flask REST API server (port 5555)
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
├── downloaded_doc/         # Downloaded documents (gitignored)
├── requirements.txt
└── pyproject.toml
```

## Setup

### Prerequisites

- Python 3.10+
- Google Chrome (for Selenium automation)
- TitlePro247 account credentials

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd titlePro

# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Install in development mode (enables titlepro.* imports)
pip install -e .

# Set up config files
cp config/secrets.json.example secrets.json
cp config/titlepro247_config.json.example titlepro247_config.json
# Edit both files with your actual credentials
```

### Running

```bash
# Start the API server
python -m titlepro.api.server

# Run county recorder search CLI
python -m titlepro.search.ca_recorder.main

# Run tests
pytest
```

## Configuration

1. Copy `config/secrets.json.example` to `secrets.json` (project root)
2. Copy `config/titlepro247_config.json.example` to `titlepro247_config.json` (project root)
3. Fill in your TitlePro247 credentials

**Never commit `secrets.json` or `titlepro247_config.json` to git.**

## CURE Workflow

1. **Initial Search** - Search county recorder by owner name(s)
2. **Vesting Deed ID** - Identify current vesting deed from results
3. **Name Extraction** - Extract all grantees from vesting deed
4. **Discovery** - Auto-search any newly discovered names
5. **Deduplication** - Combine & deduplicate results across all names
6. **Verification** - Verify documents match target property
7. **Analysis** - Classify documents, attribute liens to parties
8. **Report** - Generate Two Owner Search Exam report

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run specific test suite
pytest tests/unit/
pytest tests/integration/
```
