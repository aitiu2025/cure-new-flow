"""
TitlePro API Server - Real document downloading and file management.

Run with: python titlepro_api_server.py
Server runs on http://localhost:5555

Endpoints:
    POST /search-recorder - Search county recorder for documents
    POST /download - Download a single document
    POST /batch-download - Download multiple documents
    POST /batch-download-deduplicated - Download with deduplication across multiple names
    GET /check-files - Check which files exist in a folder
    GET /status - Check server status
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import threading
import time
import os
import subprocess
import json
import re
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

# Load .env (CAPTCHA_API_KEY etc.) before any adapter is instantiated
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass
from pathlib import Path
from titlepro.download.selenium_downloader import download_document, DOWNLOAD_DIRNAME
from titlepro.core.document_deduplicator import DocumentDeduplicator, BatchDownloadDeduplicator, log_info as dedup_log_info, log_debug as dedup_log_debug, log_warn as dedup_log_warn

app = Flask(__name__)
CORS(app)  # Enable CORS for browser requests

# Track active downloads
active_downloads = {}
batch_jobs = {}
dedup_batch_jobs = {}  # Track deduplicated batch jobs
search_jobs = {}  # Track background recorder search jobs
workflow_jobs = {}  # Track gated workflow phase jobs

# Default timeout for recorder search (seconds). 5 minutes per search mode.
SEARCH_MODE_TIMEOUT = 180  # 3 minutes per mode
SEARCH_TOTAL_TIMEOUT = 600  # 10 minutes total

MAX_RESULTS_BEFORE_TIGHTEN = 30
RECORDER_NOTE = "Recorder search returns document numbers only; download documents from TitlePro."

# Base directory for downloads
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_BASE = BASE_DIR / DOWNLOAD_DIRNAME

RECORDER_IMPORT_ERROR = None

# Multi-county support imports
try:
    from titlepro.search.recorder.counties.registry import (
        get_recorder,
        get_supported_counties,
        get_county_info,
        list_counties,
        get_counties_without_captcha
    )
    from titlepro.search.recorder.utils import (
        parse_owner_names,
        build_search_strategy,
        filter_documents_by_first_names,
        extract_surname
    )
    MULTI_COUNTY_AVAILABLE = True
except Exception as e:
    get_recorder = None
    get_supported_counties = None
    get_county_info = None
    list_counties = None
    get_counties_without_captcha = None
    parse_owner_names = None
    build_search_strategy = None
    filter_documents_by_first_names = None
    extract_surname = None
    MULTI_COUNTY_AVAILABLE = False
    RECORDER_IMPORT_ERROR = str(e)

# Legacy import for backwards compatibility
try:
    from titlepro.search.recorder.counties.orange import OrangeCountyRecorder
except:
    OrangeCountyRecorder = None

WORKFLOW_IMPORT_ERROR = None
try:
    from titlepro.automation.pipeline import RecorderAutomationPipeline, WorkflowConfig, WorkflowError
    from titlepro.automation.checkpoints import HumanCheckpointRequired, checkpoint_sessions
    WORKFLOW_AVAILABLE = True
except Exception as e:
    RecorderAutomationPipeline = None
    WorkflowConfig = None
    WorkflowError = RuntimeError
    HumanCheckpointRequired = RuntimeError
    checkpoint_sessions = None
    WORKFLOW_AVAILABLE = False
    WORKFLOW_IMPORT_ERROR = str(e)


# Validate every shipped tax recipe at startup. Failures are loud but
# non-fatal — they should not crash the server, but operators must see
# them in the logs.
def _validate_tax_recipes_on_startup() -> None:
    try:
        from titlepro.tax.recipe_schema import validate_all_recipes
    except Exception as exc:
        print(f"[startup] recipe_schema unavailable: {exc}", flush=True)
        return
    # server.py path: <project_root>/src/titlepro/api/server.py
    # parents[3] -> project_root
    recipes_dir = Path(__file__).resolve().parents[3] / "config" / "tax_recipes"
    results = validate_all_recipes(recipes_dir)
    if not results:
        print(f"[startup] tax recipes: 0 found at {recipes_dir}", flush=True)
        return
    valid = [name for name, errs in results.items() if not errs]
    invalid = {name: errs for name, errs in results.items() if errs}
    print(
        f"[startup] tax recipes: {len(valid)} valid ({', '.join(valid) or 'none'}); "
        f"{len(invalid)} invalid",
        flush=True,
    )
    for name, errs in invalid.items():
        print(f"[startup]   {name}:", flush=True)
        for err in errs:
            print(f"[startup]     - {err}", flush=True)


_validate_tax_recipes_on_startup()


@app.route('/', methods=['GET'])
def serve_ui():
    """Serve the CURE.html UI"""
    cure_path = BASE_DIR.parent / "search" / "recorder" / "CURE.html"
    if cure_path.exists():
        return send_file(cure_path)
    return jsonify({"error": "CURE.html not found", "path": str(cure_path)}), 404


@app.route('/nat-audit', methods=['GET'])
def serve_nat_audit():
    """Serve the NAT Audit Panel UI — job queue, history, submit form, manual workbench."""
    audit_path = BASE_DIR / "nat_audit.html"
    if audit_path.exists():
        return send_file(audit_path)
    return jsonify({"error": "nat_audit.html not found", "path": str(audit_path)}), 404


@app.route('/pdf/<owner>/<filename>', methods=['GET'])
def serve_pdf(owner, filename):
    """Serve PDF files from the downloaded_doc folder.

    This endpoint allows the browser to load PDFs without file:// restrictions.
    URL format: /pdf/{owner_folder}/{filename.pdf}
    """
    # Sanitize inputs to prevent path traversal
    safe_owner = owner.replace('..', '').replace('/', '').replace('\\', '')
    safe_filename = filename.replace('..', '').replace('/', '').replace('\\', '')

    pdf_path = DOWNLOAD_BASE / safe_owner / safe_filename

    if pdf_path.exists() and pdf_path.suffix.lower() == '.pdf':
        return send_file(pdf_path, mimetype='application/pdf')

    return jsonify({"error": "PDF not found", "path": str(pdf_path)}), 404


@app.route('/status', methods=['GET'])
def status():
    """Health check endpoint"""
    supported = get_supported_counties() if get_supported_counties else ["orange"]
    return jsonify(with_note({
        "status": "online",
        "message": "TitlePro API Server is running",
        "active_downloads": len(active_downloads),
        "batch_jobs": len(batch_jobs),
        "multi_county_available": MULTI_COUNTY_AVAILABLE,
        "supported_counties": len(supported)
    }))


@app.route('/api/counties', methods=['GET'])
def get_counties_list():
    """
    Get list of all supported counties.

    Returns:
        JSON with list of counties and their metadata
    """
    if not list_counties:
        # Fallback to Orange only
        return jsonify({
            "counties": [{
                "id": "orange",
                "name": "Orange County",
                "platform": "recorderworks",
                "captcha_required": False
            }],
            "total": 1,
            "message": "Multi-county support not available"
        })

    counties = list_counties()
    return jsonify({
        "counties": counties,
        "total": len(counties),
        "no_captcha_counties": get_counties_without_captcha() if get_counties_without_captcha else ["orange"]
    })


def with_note(payload):
    if isinstance(payload, dict):
        data = dict(payload)
        data.setdefault("note", RECORDER_NOTE)
        return data
    return payload


def workflow_safe_owner(owner_name, output_folder_name=None):
    base = output_folder_name or owner_name or ""
    return re.sub(r"[^A-Za-z0-9_]+", "_", base.replace(",", "")).strip("_")


def workflow_config_path_for_safe_owner(safe_owner):
    return DOWNLOAD_BASE / safe_owner / "workflow_config.json"


def load_workflow_config_from_request(data):
    if not WORKFLOW_AVAILABLE:
        raise RuntimeError(
            "Workflow automation is unavailable."
            + (f" Import error: {WORKFLOW_IMPORT_ERROR}" if WORKFLOW_IMPORT_ERROR else "")
        )

    config_data = data.get("config") if isinstance(data, dict) else None
    if isinstance(config_data, dict):
        return WorkflowConfig.from_dict(config_data)

    safe_owner = (data or {}).get("safe_owner")
    if not safe_owner:
        safe_owner = workflow_safe_owner(
            (data or {}).get("owner_name"),
            (data or {}).get("output_folder_name"),
        )

    if not safe_owner:
        raise WorkflowError("Provide a workflow config or owner_name to locate a saved workflow case.")

    config_path = workflow_config_path_for_safe_owner(safe_owner)
    if not config_path.exists():
        raise WorkflowError(f"Saved workflow config not found for case '{safe_owner}'.")
    return WorkflowConfig.from_file(config_path)


def save_workflow_config(pipeline):
    config_path = pipeline.config_path()
    config_path.write_text(json.dumps(asdict(pipeline.config), indent=2), encoding="utf-8")
    return config_path


def collect_workflow_artifacts(case_dir, safe_owner, limit=80):
    artifacts = []
    if not case_dir.exists():
        return artifacts

    for item in case_dir.rglob("*"):
        if not item.is_file():
            continue
        rel_path = item.relative_to(case_dir)
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        stat = item.stat()
        artifacts.append({
            "name": item.name,
            "relative_path": rel_path.as_posix(),
            "path": f"{safe_owner}/{rel_path.as_posix()}",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })

    artifacts.sort(key=lambda item: item["modified"], reverse=True)
    return artifacts[:limit]


def build_workflow_status_payload(config, save_config_file=False):
    pipeline = RecorderAutomationPipeline(config)
    if save_config_file:
        save_workflow_config(pipeline)

    state = pipeline.state_store.load()
    phase_statuses = {}
    next_phase = None

    for phase in pipeline.phase_order:
        enabled = pipeline.phase_enabled(phase)
        entry = state.get("phases", {}).get(phase, {})
        artifact_valid = False
        if enabled:
            try:
                artifact_valid = pipeline._can_skip_phase(phase)
            except Exception:
                artifact_valid = False

        display_status = "disabled"
        if enabled:
            state_status = entry.get("status", "pending")
            display_status = "completed" if artifact_valid else state_status

        phase_statuses[phase] = {
            "enabled": enabled,
            "state_status": entry.get("status", "pending"),
            "display_status": display_status,
            "artifact_valid": artifact_valid,
            "details": entry.get("details", {}),
            "checkpoint": entry.get("checkpoint"),
            "error": entry.get("error") if display_status == "failed" else None,
            "started_at": entry.get("started_at"),
            "completed_at": entry.get("completed_at"),
            "failed_at": entry.get("failed_at"),
            "checkpoint_at": entry.get("checkpoint_at"),
        }

        if enabled and next_phase is None and not artifact_valid:
            next_phase = phase

    active_jobs = [
        {
            "job_id": job_id,
            "phase": job.get("phase"),
            "status": job.get("status"),
            "started_at": job.get("started_at"),
            "message": job.get("message"),
            "resume_token": job.get("resume_token"),
            "checkpoint": job.get("checkpoint"),
        }
        for job_id, job in workflow_jobs.items()
        if job.get("safe_owner") == config.safe_owner and job.get("status") in {"starting", "running", "needs_human"}
    ]

    # Active CAPTCHA/human checkpoints registered for this safe_owner so the
    # UI can render Resume / Renew / Cancel controls with a live countdown.
    checkpoints_list = []
    if checkpoint_sessions:
        try:
            for cp in checkpoint_sessions.list_active():
                details = cp.get("details") or {}
                if details.get("safe_owner") and details.get("safe_owner") != config.safe_owner:
                    continue
                checkpoints_list.append(cp)
        except Exception:
            checkpoints_list = []

    return {
        "success": True,
        "workflow_available": WORKFLOW_AVAILABLE,
        "safe_owner": config.safe_owner,
        "case_dir": str(pipeline.case_dir),
        "config_path": str(pipeline.config_path()),
        "workflow_status_path": str(pipeline.state_store.path),
        "workflow_config": asdict(config),
        "phase_order": pipeline.phase_order,
        "enabled_phases": pipeline.enabled_phases(),
        "next_phase": next_phase,
        "phase_statuses": phase_statuses,
        "state": state,
        "artifacts": collect_workflow_artifacts(pipeline.case_dir, config.safe_owner),
        "active_jobs": active_jobs,
        "checkpoints": checkpoints_list,
    }


@app.route('/search-recorder', methods=['POST'])
def search_recorder():
    """
    Search the county recorder for documents by owner name.

    This endpoint launches a background search job and returns a job_id.
    The client should poll /search-recorder-status/<job_id> for progress.

    Request body (JSON):
        owner_name: Owner name in "Last First" format (required)
        county: County identifier (optional, default: orange)
        start_date: Start date MM/DD/YYYY (optional)
        end_date: End date MM/DD/YYYY (optional)
        timeout: Total timeout in seconds (optional, default: 600)

    Returns:
        JSON with job_id for polling, or immediate results for fast searches.
    """
    data = request.get_json()

    if not data:
        return jsonify(with_note({"success": False, "error": "JSON body required"})), 400

    owner_name = data.get('owner_name') or data.get('name')
    county = (data.get('county') or 'orange').lower()
    start_date = data.get('start_date') or "01/01/2000"
    end_date = data.get('end_date') or datetime.now().strftime("%m/%d/%Y")
    total_timeout = int(data.get('timeout', SEARCH_TOTAL_TIMEOUT))

    if not owner_name:
        return jsonify(with_note({"success": False, "error": "owner_name is required"})), 400

    # Normalize county ID
    county = county.lower().replace(" ", "_").replace("-", "_")

    # Check if county is supported
    if get_supported_counties:
        supported = get_supported_counties()
        if county not in supported:
            return jsonify(with_note({
                "success": False,
                "error": f"Unsupported county: {county}",
                "supported_counties": supported
            })), 400
    elif county != "orange":
        return jsonify(with_note({"success": False, "error": f"Unsupported county: {county}"})), 400

    if parse_owner_names is None:
        return jsonify(with_note({
            "success": False,
            "error": "Recorder search is unavailable. Selenium dependencies may be missing.",
            "details": RECORDER_IMPORT_ERROR
        })), 500

    # Get county display name
    county_info = get_county_info(county) if get_county_info else {"display_name": "Orange County"}
    county_display_name = county_info.get("display_name", county.replace("_", " ").title() + " County")

    names = parse_owner_names(owner_name)
    if not names:
        return jsonify(with_note({"success": False, "error": "No valid owner names provided"})), 400

    # Create a background search job
    import hashlib
    job_id = hashlib.md5(f"{owner_name}:{county}:{time.time()}".encode()).hexdigest()[:10]

    search_jobs[job_id] = {
        "status": "running",
        "phase": "initializing",
        "current_mode": None,
        "current_name": None,
        "modes_completed": 0,
        "modes_total": 0,
        "documents_found": 0,
        "started_at": time.time(),
        "timeout": total_timeout,
        "county": county,
        "county_name": county_display_name,
        "owner_name": owner_name,
        "names": names,
        "progress_log": [],
        "error": None
    }

    def _log_progress(job, message):
        """Append a timestamped progress message."""
        elapsed = round(time.time() - job["started_at"], 1)
        entry = f"[{elapsed}s] {message}"
        job["progress_log"].append(entry)
        print(f"  [search-job:{job_id}] {entry}")

    def run_search_job():
        """Background thread for recorder search."""
        job = search_jobs[job_id]
        search_start = time.time()

        all_documents = {}
        errors = {}
        grantor_count = 0
        grantee_count = 0
        search_details = []

        try:
            _log_progress(job, f"Starting search in {county_display_name} for: {owner_name}")
            _log_progress(job, f"Parsed names: {names}")
            _log_progress(job, f"Timeout: {total_timeout}s")

            # Build intelligent search strategy
            strategy = None
            if build_search_strategy:
                strategy = build_search_strategy(names)
                _log_progress(job, f"Strategy: {strategy.get('type', 'individual')}")
                if strategy.get('common_surname'):
                    _log_progress(job, f"Common surname: {strategy['common_surname']}")

            # Get recorder for the specified county
            if get_recorder:
                recorder_instance = get_recorder(county, start_date=start_date, end_date=end_date)
            elif OrangeCountyRecorder and county == "orange":
                recorder_instance = OrangeCountyRecorder(start_date=start_date, end_date=end_date)
            else:
                job["status"] = "error"
                job["error"] = f"No recorder available for county: {county}"
                return

            job["phase"] = "navigating"
            _log_progress(job, "Launching browser and navigating to search page...")

            with recorder_instance as recorder:
                recorder.navigate_to_search()
                _log_progress(job, "Browser ready, search page loaded")

                def check_timeout():
                    """Check if we've exceeded the total timeout."""
                    elapsed = time.time() - search_start
                    if elapsed >= total_timeout:
                        return True
                    return False

                def run_search_modes(search_term, partial_match, label, detail):
                    nonlocal grantor_count, grantee_count
                    doc_map = {}
                    mode_counts = {}
                    modes = ["All", "Grantor", "Grantee"]

                    job["phase"] = "searching"

                    for party_type in modes:
                        if check_timeout():
                            _log_progress(job, f"TIMEOUT reached during {party_type} mode for '{search_term}'")
                            errors[f"{label}:{party_type}:{search_term}"] = "Search timed out"
                            break

                        job["current_mode"] = party_type
                        job["current_name"] = search_term
                        _log_progress(job, f"Searching '{search_term}' as {party_type} (partial={partial_match})")

                        recorder.set_partial_match(partial_match)
                        try:
                            result = recorder.search_name(search_term, party_type)
                            mode_counts[party_type] = len(result.documents)
                            _log_progress(job, f"  {party_type}: found {len(result.documents)} documents")

                            if party_type == "Grantor":
                                grantor_count += len(result.documents)
                            elif party_type == "Grantee":
                                grantee_count += len(result.documents)

                            for doc in result.documents:
                                if doc.document_number:
                                    doc_map[doc.document_number] = doc.to_dict()

                            job["modes_completed"] += 1
                            job["documents_found"] = len(all_documents) + len(doc_map)
                        except Exception as e:
                            _log_progress(job, f"  {party_type}: ERROR - {str(e)[:200]}")
                            errors[f"{label}:{party_type}:{search_term}"] = str(e)
                        finally:
                            recorder.return_to_search()

                    detail["attempts"].append({
                        "label": label,
                        "search_term": search_term,
                        "partial_match": partial_match,
                        "mode_counts": mode_counts,
                        "total_unique": len(doc_map)
                    })

                    return doc_map

                # Calculate total modes for progress tracking
                if strategy and strategy.get("type") == "shared_surname":
                    job["modes_total"] = 3  # 3 modes for one surname search
                else:
                    job["modes_total"] = len(names) * 3  # 3 modes per name

                # Use intelligent search strategy if available
                if strategy and strategy.get("type") == "shared_surname":
                    surname = strategy["common_surname"]
                    first_names = strategy.get("first_names_to_filter", [])

                    detail = {
                        "name": surname,
                        "strategy": "shared_surname",
                        "original_names": strategy.get("searches", [{}])[0].get("original_names", names),
                        "attempts": []
                    }

                    doc_map = run_search_modes(surname, partial_match=True, label="surname_search", detail=detail)
                    unique_count = len(doc_map)

                    if unique_count > 0 and first_names and filter_documents_by_first_names:
                        docs_list = list(doc_map.values())
                        filtered_docs = filter_documents_by_first_names(docs_list, first_names)
                        detail["filtered_count"] = len(filtered_docs)
                        detail["filter_first_names"] = first_names
                        doc_map = {d["document_number"]: d for d in filtered_docs}

                    if unique_count >= MAX_RESULTS_BEFORE_TIGHTEN and not check_timeout():
                        tightened_map = run_search_modes(surname, partial_match=False, label="tightened_exact", detail=detail)
                        if tightened_map:
                            doc_map = tightened_map

                    for doc_num, doc in doc_map.items():
                        all_documents[doc_num] = doc

                    search_details.append(detail)

                else:
                    for idx, search_name in enumerate(names, start=1):
                        if check_timeout():
                            _log_progress(job, f"TIMEOUT: skipping remaining names (completed {idx-1}/{len(names)})")
                            break

                        _log_progress(job, f"--- Name {idx}/{len(names)}: {search_name} ---")

                        detail = {
                            "name": search_name,
                            "attempts": []
                        }

                        doc_map = run_search_modes(search_name, partial_match=True, label="full_name", detail=detail)
                        unique_count = len(doc_map)
                        search_term = search_name

                        if unique_count == 0 and not check_timeout():
                            surname = extract_surname(search_name) if extract_surname else search_name.split()[0]
                            if surname and surname.lower() != search_name.lower():
                                doc_map = run_search_modes(surname, partial_match=True, label="surname_fallback", detail=detail)
                                unique_count = len(doc_map)
                                search_term = surname

                        if unique_count >= MAX_RESULTS_BEFORE_TIGHTEN and not check_timeout():
                            tightened_map = run_search_modes(search_term, partial_match=False, label="tightened_exact", detail=detail)
                            if tightened_map:
                                doc_map = tightened_map

                        for doc_num, doc in doc_map.items():
                            all_documents[doc_num] = doc

                        search_details.append(detail)

            # Search completed (or timed out with partial results)
            documents = list(all_documents.values())
            documents.sort(key=lambda d: d.get("document_number", ""), reverse=True)

            # Save documents_found.json
            safe_owner = owner_name.replace(" ", "_").replace(",", "")
            folder_path = DOWNLOAD_BASE / safe_owner
            folder_path.mkdir(parents=True, exist_ok=True)
            docs_path = folder_path / "documents_found.json"
            docs_path.write_text(json.dumps(documents, indent=2))

            elapsed = round(time.time() - search_start, 1)
            timed_out = elapsed >= total_timeout

            job["status"] = "completed"
            job["phase"] = "done"
            job["current_mode"] = None
            job["current_name"] = None
            job["timed_out"] = timed_out
            job["elapsed"] = elapsed
            job["result"] = {
                "success": True,
                "timed_out": timed_out,
                "message": (
                    f"Search timed out after {elapsed}s with {len(documents)} partial results for {county_display_name}."
                    if timed_out else
                    f"Recorder search completed for {county_display_name}. {len(documents)} documents found."
                ),
                "documents": documents,
                "search_params": {
                    "owner_name": owner_name,
                    "names_searched": names,
                    "county": county,
                    "county_name": county_display_name,
                    "start_date": start_date,
                    "end_date": end_date
                },
                "search_details": search_details,
                "summary": {
                    "grantor_count": grantor_count,
                    "grantee_count": grantee_count,
                    "total_unique": len(documents)
                },
                "folder_path": str(folder_path),
                "elapsed_seconds": elapsed
            }
            if errors:
                job["result"]["warnings"] = errors

            _log_progress(job, f"Search {'TIMED OUT' if timed_out else 'COMPLETED'}: {len(documents)} unique documents in {elapsed}s")

        except Exception as e:
            import traceback
            traceback.print_exc()
            elapsed = round(time.time() - search_start, 1)
            _log_progress(job, f"FATAL ERROR after {elapsed}s: {str(e)}")
            job["status"] = "error"
            job["phase"] = "failed"
            job["error"] = str(e)
            job["elapsed"] = elapsed
            # Include partial results if any
            if all_documents:
                documents = list(all_documents.values())
                documents.sort(key=lambda d: d.get("document_number", ""), reverse=True)
                job["result"] = {
                    "success": True,
                    "timed_out": True,
                    "message": f"Search failed with error after {elapsed}s, returning {len(documents)} partial results.",
                    "documents": documents,
                    "search_params": {
                        "owner_name": owner_name,
                        "county": county,
                        "county_name": county_display_name,
                    },
                    "summary": {"total_unique": len(documents)},
                    "error": str(e)
                }

    thread = threading.Thread(target=run_search_job, daemon=True)
    thread.start()

    print(f"[search-recorder] Started background job {job_id} for {county_display_name}: {owner_name}")

    return jsonify(with_note({
        "success": True,
        "job_id": job_id,
        "status": "started",
        "message": f"Search started for {county_display_name}. Poll /search-recorder-status/{job_id} for progress.",
        "county_name": county_display_name,
        "names": names
    }))


@app.route('/search-recorder-status/<job_id>', methods=['GET'])
def search_recorder_status(job_id):
    """
    Poll the status of a background recorder search job.

    Returns current phase, progress, and results when complete.
    """
    if job_id not in search_jobs:
        return jsonify(with_note({"status": "not_found", "error": f"Search job {job_id} not found"})), 404

    job = search_jobs[job_id]
    elapsed = round(time.time() - job["started_at"], 1)

    response = {
        "job_id": job_id,
        "status": job["status"],
        "phase": job["phase"],
        "current_mode": job.get("current_mode"),
        "current_name": job.get("current_name"),
        "modes_completed": job.get("modes_completed", 0),
        "modes_total": job.get("modes_total", 0),
        "documents_found": job.get("documents_found", 0),
        "elapsed": elapsed,
        "timeout": job.get("timeout", SEARCH_TOTAL_TIMEOUT),
        "county_name": job.get("county_name", ""),
        "progress_log": job.get("progress_log", [])[-20:]  # Last 20 log entries
    }

    if job["status"] == "completed" and "result" in job:
        response["result"] = job["result"]
    elif job["status"] == "error":
        response["error"] = job.get("error", "Unknown error")
        if "result" in job:
            response["result"] = job["result"]  # Partial results on error

    return jsonify(with_note(response))


def load_metadata(folder_path):
    """Load metadata file from folder."""
    metadata_path = folder_path / "document_metadata.json"
    if metadata_path.exists():
        try:
            import json
            return json.loads(metadata_path.read_text())
        except:
            return {}
    return {}


@app.route('/search-recorder-multiname', methods=['POST'])
def search_recorder_multiname():
    """
    Search county recorder for documents using multiple names with deduplication.

    [DEDUPLICATION_DEBUGLOGS] - Multi-name search endpoint with deduplication

    This endpoint accepts a list of names to search and returns deduplicated
    results, tracking which names each document was found under. This is essential
    for title searches where documents may be found under multiple owner names.

    Request body (JSON):
        names: List of names to search (required) - e.g., ["SMITH JOHN", "SMITH JANE"]
        county: County identifier (optional, default: orange)
        start_date: Start date MM/DD/YYYY (optional)
        end_date: End date MM/DD/YYYY (optional)
        owner_name: Primary owner name for folder organization (optional)

    Returns:
        JSON with:
        - deduplicated_documents: List of unique documents with found_via_names
        - search_summaries: Per-name search statistics
        - deduplication_stats: Overall deduplication statistics
        - multi_name_documents: Documents found under multiple names
        - single_name_documents: Documents found under only one name

    Example request:
        {
            "names": ["ROSENKRANS TERRY", "ROSENKRANS VALERIE"],
            "county": "amador",
            "owner_name": "ROSENKRANS TERRY & VALERIE"
        }
    """
    data = request.get_json()

    if not data:
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] search-recorder-multiname: No JSON body")
        return jsonify(with_note({"success": False, "error": "JSON body required"})), 400

    names_to_search = data.get('names', [])
    county = (data.get('county') or 'orange').lower()
    start_date = data.get('start_date') or "01/01/2000"
    end_date = data.get('end_date') or datetime.now().strftime("%m/%d/%Y")
    owner_name = data.get('owner_name', '')

    if not names_to_search:
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] search-recorder-multiname: No names provided")
        return jsonify(with_note({"success": False, "error": "names list is required"})), 400

    if not isinstance(names_to_search, list):
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] search-recorder-multiname: names must be a list")
        return jsonify(with_note({"success": False, "error": "names must be a list of strings"})), 400

    # Normalize county ID
    county = county.lower().replace(" ", "_").replace("-", "_")

    # Check if county is supported
    if get_supported_counties:
        supported = get_supported_counties()
        if county not in supported:
            return jsonify(with_note({
                "success": False,
                "error": f"Unsupported county: {county}",
                "supported_counties": supported
            })), 400
    elif county != "orange":
        return jsonify(with_note({"success": False, "error": f"Unsupported county: {county}"})), 400

    if parse_owner_names is None:
        return jsonify(with_note({
            "success": False,
            "error": "Recorder search is unavailable. Selenium dependencies may be missing.",
            "details": RECORDER_IMPORT_ERROR
        })), 500

    # Get county display name
    county_info = get_county_info(county) if get_county_info else {"display_name": "Orange County"}
    county_display_name = county_info.get("display_name", county.replace("_", " ").title() + " County")

    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Multi-name search for {len(names_to_search)} names in {county_display_name}")

    # Create deduplicator to track results
    deduplicator = DocumentDeduplicator()
    search_summaries = []
    all_errors = {}
    total_grantor = 0
    total_grantee = 0

    try:
        # Get recorder for the specified county
        if get_recorder:
            recorder_instance = get_recorder(county, start_date=start_date, end_date=end_date)
        elif OrangeCountyRecorder and county == "orange":
            recorder_instance = OrangeCountyRecorder(start_date=start_date, end_date=end_date)
        else:
            return jsonify(with_note({
                "success": False,
                "error": f"No recorder available for county: {county}"
            })), 500

        with recorder_instance as recorder:
            recorder.navigate_to_search()

            # Search for each name
            for search_name in names_to_search:
                dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Searching for: {search_name}")

                name_docs = {}
                name_grantor = 0
                name_grantee = 0
                name_errors = {}

                # Parse the name (may expand to multiple search terms)
                parsed_names = parse_owner_names(search_name) if parse_owner_names else [search_name]

                for parsed_name in parsed_names:
                    modes = ["All", "Grantor", "Grantee"]

                    for party_type in modes:
                        try:
                            recorder.set_partial_match(True)
                            result = recorder.search_name(parsed_name, party_type)

                            if party_type == "Grantor":
                                name_grantor += len(result.documents)
                            elif party_type == "Grantee":
                                name_grantee += len(result.documents)

                            for doc in result.documents:
                                if doc.document_number:
                                    name_docs[doc.document_number] = doc.to_dict()

                        except Exception as e:
                            name_errors[f"{parsed_name}:{party_type}"] = str(e)
                            dedup_log_warn(f"[DEDUPLICATION_DEBUGLOGS] Search error: {parsed_name}:{party_type} - {e}")
                        finally:
                            recorder.return_to_search()

                # Add all documents found for this name to the deduplicator
                docs_list = list(name_docs.values())
                dedup_result = deduplicator.add_documents(docs_list, search_name)

                search_summaries.append({
                    "name": search_name,
                    "parsed_names": parsed_names,
                    "total_found": len(docs_list),
                    "new_unique": dedup_result.get('new', 0),
                    "duplicates": dedup_result.get('duplicates', 0),
                    "grantor_count": name_grantor,
                    "grantee_count": name_grantee,
                    "errors": name_errors if name_errors else None
                })

                total_grantor += name_grantor
                total_grantee += name_grantee
                all_errors.update(name_errors)

                dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] {search_name}: {len(docs_list)} found, {dedup_result.get('new', 0)} new, {dedup_result.get('duplicates', 0)} duplicates")

    except Exception as e:
        import traceback
        traceback.print_exc()
        dedup_log_warn(f"[DEDUPLICATION_DEBUGLOGS] Search failed: {e}")
        return jsonify(with_note({"success": False, "error": str(e)})), 500

    # Get deduplicated results
    deduplicated_docs = deduplicator.get_deduplicated()
    stats = deduplicator.get_statistics()
    multi_name_docs = deduplicator.get_multi_name_documents()
    single_name_docs = deduplicator.get_single_name_documents()

    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Final: {stats.get('unique_documents', 0)} unique from {stats.get('total_found', 0)} total")

    # Save results to folder if owner_name provided
    folder_path = None
    if owner_name:
        safe_owner = owner_name.replace(" ", "_").replace(",", "")
        folder_path = DOWNLOAD_BASE / safe_owner
        folder_path.mkdir(parents=True, exist_ok=True)

        # Save documents_found.json with deduplication info
        docs_path = folder_path / "documents_found.json"
        docs_path.write_text(json.dumps(deduplicated_docs, indent=2))

        # Save deduplication state
        dedup_state_path = folder_path / "deduplication_state.json"
        deduplicator.save_to_file(dedup_state_path)

        dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Saved results to {folder_path}")

    response = {
        "success": True,
        "message": f"Multi-name search completed for {county_display_name}. {stats.get('unique_documents', 0)} unique documents from {stats.get('total_found', 0)} total.",
        "deduplicated_documents": deduplicated_docs,
        "search_params": {
            "names": names_to_search,
            "county": county,
            "county_name": county_display_name,
            "start_date": start_date,
            "end_date": end_date
        },
        "search_summaries": search_summaries,
        "deduplication_stats": stats,
        "summary": {
            "total_names_searched": len(names_to_search),
            "total_found": stats.get('total_found', 0),
            "unique_documents": stats.get('unique_documents', 0),
            "duplicates_removed": stats.get('duplicates_removed', 0),
            "multi_name_documents": len(multi_name_docs),
            "single_name_documents": len(single_name_docs),
            "grantor_count": total_grantor,
            "grantee_count": total_grantee
        },
        "multi_name_documents": multi_name_docs[:50],  # Limit response size
        "single_name_documents": single_name_docs[:50]
    }

    if folder_path:
        response["folder_path"] = str(folder_path)

    if all_errors:
        response["warnings"] = all_errors

    return jsonify(with_note(response))


@app.route('/check-files', methods=['POST'])
def check_files():
    """
    Check which files exist in the download folder.

    Request body (JSON):
        owner_name: Owner name for subfolder (required)
        documents: List of document objects with 'num' field (required)

    Returns:
        JSON with file existence status for each document
    """
    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    owner_name = data.get('owner_name')
    documents = data.get('documents', [])

    if not owner_name:
        return jsonify(with_note({"error": "owner_name is required"})), 400

    # Build folder path
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner

    # Check if folder exists
    if not folder_path.exists():
        return jsonify(with_note({
            "folder_exists": False,
            "folder_path": str(folder_path),
            "documents": [{**doc, "file_exists": False, "filename": None} for doc in documents]
        }))

    # Get all PDF files in folder
    existing_files = list(folder_path.glob("*.pdf"))
    existing_filenames = [f.name for f in existing_files]

    # Load metadata mapping (instrument number -> filename)
    metadata = load_metadata(folder_path)

    # Check each document
    results = []
    for doc in documents:
        doc_num = doc.get('num', '')

        # Check if any file contains this document number OR matches known filename
        found_file = None
        known_filename = doc.get('filename')

        # First check metadata for this instrument number
        if doc_num in metadata:
            meta_filename = metadata[doc_num].get('filename')
            if meta_filename and meta_filename in existing_filenames:
                found_file = meta_filename

        # Then check if known filename exists
        if not found_file and known_filename and known_filename in existing_filenames:
            found_file = known_filename

        # Finally search for file containing the document number
        if not found_file:
            for filename in existing_filenames:
                if doc_num in filename:
                    found_file = filename
                    break

        results.append({
            **doc,
            "file_exists": found_file is not None,
            "filename": found_file
        })

    return jsonify(with_note({
        "folder_exists": True,
        "folder_path": str(folder_path),
        "total_files": len(existing_files),
        "metadata_entries": len(metadata),
        "documents": results
    }))


@app.route('/download', methods=['POST'])
def trigger_download():
    """
    Trigger a single document download.

    Request body (JSON):
        doc_num: Document/instrument number (required)
        year: Year in YYYY format (required)
        county: County name or code (e.g., "amador", "06005") (optional but recommended)
        show_browser: If true, show browser window (default: false)
        owner_name: Owner name for folder organization (optional)

    Returns:
        JSON with job_id and status
    """
    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    doc_num = data.get('doc_num')
    year = data.get('year')
    county = data.get('county')
    show_browser = data.get('show_browser', False)
    owner_name = data.get('owner_name')

    if not doc_num:
        return jsonify(with_note({"error": "doc_num is required"})), 400
    if not year:
        return jsonify(with_note({"error": "year is required"})), 400

    job_id = f"{doc_num}_{year}"

    def run_download():
        try:
            active_downloads[job_id] = {"status": "running", "doc_num": doc_num, "year": year, "county": county}
            result = download_document(
                doc_num=str(doc_num),
                year=str(year),
                headless=not show_browser,
                owner_name=owner_name,
                county=county
            )
            active_downloads[job_id] = result
        except BaseException as e:
            import traceback
            traceback.print_exc()
            active_downloads[job_id] = {"status": "error", "message": str(e)}

    thread = threading.Thread(target=run_download)
    thread.start()

    return jsonify(with_note({
        "status": "started",
        "job_id": job_id,
        "message": f"Download started for document #{doc_num} ({year})",
        "show_browser": show_browser
    }))


@app.route('/batch-download', methods=['POST'])
def batch_download():
    """
    Download multiple documents sequentially.

    Request body (JSON):
        owner_name: Owner name for folder organization (required)
        documents: List of {num, year, type} objects (required)
        county: County name or code for all documents (optional but recommended)
        show_browser: If true, show browser window (default: false)
        skip_existing: If true, skip documents that already exist (default: true)

    Returns:
        JSON with batch_id and status
    """
    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    owner_name = data.get('owner_name')
    documents = data.get('documents', [])
    county = data.get('county')  # County for all documents in batch
    show_browser = data.get('show_browser', False)
    skip_existing = data.get('skip_existing', True)

    if not owner_name:
        return jsonify(with_note({"error": "owner_name is required"})), 400
    if not documents:
        return jsonify(with_note({"error": "documents list is required"})), 400

    batch_id = f"batch_{owner_name}_{int(time.time())}"

    def run_batch():
        safe_owner = owner_name.replace(" ", "_").replace(",", "")
        folder_path = DOWNLOAD_BASE / safe_owner
        folder_path.mkdir(parents=True, exist_ok=True)

        # Get existing files if skip_existing
        existing_files = []
        metadata = {}
        if skip_existing and folder_path.exists():
            existing_files = [f.name for f in folder_path.glob("*.pdf")]
            metadata = load_metadata(folder_path)

        results = []
        total = len(documents)

        batch_jobs[batch_id] = {
            "status": "running",
            "total": total,
            "completed": 0,
            "current": None,
            "county": county,
            "results": results
        }

        for i, doc in enumerate(documents):
            doc_num = doc.get('num')
            year = doc.get('year')
            doc_type = doc.get('type', 'DOCUMENT')
            known_filename = doc.get('filename')
            # Allow per-document county override
            doc_county = doc.get('county', county)

            batch_jobs[batch_id]["current"] = doc_num
            batch_jobs[batch_id]["completed"] = i

            # Check if file already exists (via metadata, known filename, or doc_num in filename)
            file_exists = False
            if skip_existing:
                # Check metadata mapping first (instrument number -> filename)
                if doc_num and doc_num in metadata:
                    meta_filename = metadata[doc_num].get('filename')
                    if meta_filename and meta_filename in existing_files:
                        file_exists = True
                # Then check known filename
                if not file_exists and known_filename and known_filename in existing_files:
                    file_exists = True
                # Finally check if doc_num appears in any filename
                if not file_exists and doc_num:
                    for f in existing_files:
                        if doc_num in f:
                            file_exists = True
                            break

            if file_exists:
                results.append({
                    "doc_num": doc_num,
                    "year": year,
                    "type": doc_type,
                    "status": "skipped",
                    "message": "File already exists",
                    "filename": known_filename
                })
                continue

            # Download the document
            try:
                result = download_document(
                    doc_num=str(doc_num),
                    year=str(year),
                    headless=not show_browser,
                    owner_name=owner_name,
                    county=doc_county
                )

                results.append({
                    "doc_num": doc_num,
                    "year": year,
                    "type": doc_type,
                    "status": result.get("status", "unknown"),
                    "message": result.get("message", ""),
                    "files": result.get("files", [])
                })

                # Update existing files list
                if result.get("files"):
                    existing_files.extend(result["files"])

            except Exception as e:
                results.append({
                    "doc_num": doc_num,
                    "year": year,
                    "type": doc_type,
                    "status": "error",
                    "message": str(e)
                })

            # Small delay between downloads
            if i < total - 1:
                time.sleep(2)

        batch_jobs[batch_id] = {
            "status": "completed",
            "total": total,
            "completed": total,
            "current": None,
            "results": results,
            "folder_path": str(folder_path)
        }

    thread = threading.Thread(target=run_batch)
    thread.start()

    return jsonify(with_note({
        "status": "started",
        "batch_id": batch_id,
        "message": f"Batch download started for {len(documents)} documents",
        "total_documents": len(documents)
    }))


@app.route('/batch-status/<batch_id>', methods=['GET'])
def get_batch_status(batch_id):
    """Check status of a batch download job"""
    if batch_id in batch_jobs:
        return jsonify(with_note(batch_jobs[batch_id]))
    # Also check deduplicated batch jobs
    if batch_id in dedup_batch_jobs:
        return jsonify(with_note(dedup_batch_jobs[batch_id]))
    return jsonify(with_note({"status": "not_found", "message": f"Batch {batch_id} not found"})), 404


@app.route('/batch-download-deduplicated', methods=['POST'])
def batch_download_deduplicated():
    """
    Download documents from multiple name searches with deduplication.

    [DEDUPLICATION_DEBUGLOGS] - Endpoint for deduplicated batch downloads

    This endpoint accepts documents from multiple name searches, deduplicates
    them based on document_number, and downloads only unique documents.
    It tracks which names each document was found under.

    Request body (JSON):
        owner_name: Primary owner name for folder organization (required)
        searches: List of search results, each containing:
            - name: The name searched for
            - documents: List of {num, year, type} objects
        county: County name or code for all documents (optional but recommended)
        show_browser: If true, show browser window (default: false)
        skip_existing: If true, skip documents that already exist (default: true)

    Returns:
        JSON with batch_id, deduplication statistics, and status

    Example request:
        {
            "owner_name": "SMITH JOHN & JANE",
            "county": "orange",
            "searches": [
                {
                    "name": "SMITH JOHN",
                    "documents": [
                        {"num": "2023-0001234", "year": "2023", "type": "GRANT DEED"},
                        {"num": "2023-0001235", "year": "2023", "type": "DEED OF TRUST"}
                    ]
                },
                {
                    "name": "SMITH JANE",
                    "documents": [
                        {"num": "2023-0001234", "year": "2023", "type": "GRANT DEED"},
                        {"num": "2023-0001236", "year": "2023", "type": "DEED OF TRUST"}
                    ]
                }
            ]
        }
    """
    data = request.get_json()

    if not data:
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] batch-download-deduplicated: No JSON body")
        return jsonify(with_note({"error": "JSON body required"})), 400

    owner_name = data.get('owner_name')
    searches = data.get('searches', [])
    county = data.get('county')
    show_browser = data.get('show_browser', False)
    skip_existing = data.get('skip_existing', True)

    if not owner_name:
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] batch-download-deduplicated: Missing owner_name")
        return jsonify(with_note({"error": "owner_name is required"})), 400

    if not searches:
        dedup_log_warn("[DEDUPLICATION_DEBUGLOGS] batch-download-deduplicated: No searches provided")
        return jsonify(with_note({"error": "searches list is required"})), 400

    batch_id = f"dedup_batch_{owner_name.replace(' ', '_')}_{int(time.time())}"
    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Starting deduplicated batch download: {batch_id}")

    # Calculate folder path
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner
    folder_path.mkdir(parents=True, exist_ok=True)

    # Initialize the batch deduplicator
    batch_dedup = BatchDownloadDeduplicator(download_dir=folder_path)

    # Process all searches and deduplicate
    total_input_docs = 0
    search_summaries = []

    for search in searches:
        search_name = search.get('name', 'Unknown')
        search_docs = search.get('documents', [])
        total_input_docs += len(search_docs)

        # Convert document format to match deduplicator expectations
        normalized_docs = []
        for doc in search_docs:
            normalized_docs.append({
                "document_number": doc.get('num', doc.get('document_number', '')),
                "year": doc.get('year', ''),
                "document_type": doc.get('type', doc.get('document_type', '')),
                "recording_date": doc.get('recording_date', ''),
                "grantors": doc.get('grantors', ''),
                "grantees": doc.get('grantees', ''),
                "pages": doc.get('pages', '')
            })

        result = batch_dedup.add_search_results(normalized_docs, search_name)
        search_summaries.append({
            "name": search_name,
            "input_count": len(search_docs),
            "new_unique": result.get('new', 0),
            "duplicates": result.get('duplicates', 0)
        })

    # Get the deduplicated download queue
    download_queue = batch_dedup.get_download_queue(skip_existing=skip_existing)
    dedup_stats = batch_dedup.deduplicator.get_statistics()

    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Deduplication complete: {total_input_docs} input -> {len(download_queue)} to download")
    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Duplicates removed: {dedup_stats.get('duplicates_removed', 0)}")

    # Initialize job status
    dedup_batch_jobs[batch_id] = {
        "status": "running",
        "phase": "downloading",
        "total_input": total_input_docs,
        "unique_documents": dedup_stats.get('unique_documents', 0),
        "duplicates_removed": dedup_stats.get('duplicates_removed', 0),
        "to_download": len(download_queue),
        "completed": 0,
        "current": None,
        "county": county,
        "search_summaries": search_summaries,
        "results": [],
        "deduplication_stats": dedup_stats
    }

    def run_deduplicated_batch():
        """Background thread for deduplicated batch download."""
        results = []

        # Get existing files if skip_existing
        existing_files = []
        if skip_existing and folder_path.exists():
            existing_files = [f.name for f in folder_path.glob("*.pdf")]

        for i, doc in enumerate(download_queue):
            doc_num = doc.get('document_number', '')
            year = doc.get('year', '')
            doc_type = doc.get('document_type', 'DOCUMENT')
            found_via = doc.get('found_via_names', [])

            dedup_batch_jobs[batch_id]["current"] = doc_num
            dedup_batch_jobs[batch_id]["completed"] = i

            dedup_log_debug(f"[DEDUPLICATION_DEBUGLOGS] Downloading {i+1}/{len(download_queue)}: {doc_num}")

            try:
                # [DEDUPLICATION_DEBUGLOGS] Pass deduplication metadata to download
                result = download_document(
                    doc_num=str(doc_num),
                    year=str(year),
                    headless=not show_browser,
                    owner_name=owner_name,
                    county=county,
                    document_type=doc_type,
                    found_via_names=found_via
                )

                download_result = {
                    "doc_num": doc_num,
                    "year": year,
                    "type": doc_type,
                    "found_via_names": found_via,
                    "status": result.get("status", "unknown"),
                    "message": result.get("message", ""),
                    "files": result.get("files", [])
                }

                results.append(download_result)

                # Mark as downloaded in deduplicator
                if result.get("files"):
                    batch_dedup.mark_downloaded(doc_num, result["files"][0])
                    existing_files.extend(result["files"])
                elif result.get("status") == "error":
                    batch_dedup.mark_failed(doc_num, result.get("message", "Unknown error"))

            except Exception as e:
                dedup_log_warn(f"[DEDUPLICATION_DEBUGLOGS] Download failed for {doc_num}: {e}")
                results.append({
                    "doc_num": doc_num,
                    "year": year,
                    "type": doc_type,
                    "found_via_names": found_via,
                    "status": "error",
                    "message": str(e)
                })
                batch_dedup.mark_failed(doc_num, str(e))

            # Small delay between downloads
            if i < len(download_queue) - 1:
                time.sleep(2)

        # Save enhanced metadata with deduplication info
        metadata_path = folder_path / "document_metadata.json"
        batch_dedup.save_enhanced_metadata(metadata_path)

        # Save deduplication state for future reference
        dedup_state_path = folder_path / "deduplication_state.json"
        batch_dedup.deduplicator.save_to_file(dedup_state_path)

        # Final job status
        download_summary = batch_dedup.get_download_summary()
        dedup_batch_jobs[batch_id] = {
            "status": "completed",
            "phase": "complete",
            "total_input": total_input_docs,
            "unique_documents": dedup_stats.get('unique_documents', 0),
            "duplicates_removed": dedup_stats.get('duplicates_removed', 0),
            "to_download": len(download_queue),
            "completed": len(download_queue),
            "current": None,
            "results": results,
            "download_summary": download_summary,
            "deduplication_stats": dedup_stats,
            "search_summaries": search_summaries,
            "folder_path": str(folder_path),
            "metadata_path": str(metadata_path)
        }

        dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Batch {batch_id} completed: {download_summary}")

    thread = threading.Thread(target=run_deduplicated_batch)
    thread.start()

    return jsonify(with_note({
        "status": "started",
        "batch_id": batch_id,
        "message": f"Deduplicated batch download started",
        "total_input_documents": total_input_docs,
        "unique_documents": dedup_stats.get('unique_documents', 0),
        "duplicates_removed": dedup_stats.get('duplicates_removed', 0),
        "to_download": len(download_queue),
        "search_summaries": search_summaries,
        "deduplication_stats": dedup_stats
    }))


@app.route('/deduplicate-preview', methods=['POST'])
def deduplicate_preview():
    """
    Preview deduplication without downloading.

    [DEDUPLICATION_DEBUGLOGS] - Preview endpoint for deduplication

    This endpoint accepts documents from multiple name searches and returns
    deduplication statistics without actually downloading anything.
    Useful for understanding how many documents will be saved.

    Request body (JSON):
        searches: List of search results, each containing:
            - name: The name searched for
            - documents: List of {num, year, type} objects

    Returns:
        JSON with deduplication preview including:
        - Total documents across all searches
        - Unique documents after deduplication
        - Duplicates that would be removed
        - Documents found under multiple names
    """
    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    searches = data.get('searches', [])
    if not searches:
        return jsonify(with_note({"error": "searches list is required"})), 400

    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Deduplication preview for {len(searches)} searches")

    # Create deduplicator for preview
    dedup = DocumentDeduplicator()

    total_input = 0
    search_summaries = []

    for search in searches:
        search_name = search.get('name', 'Unknown')
        search_docs = search.get('documents', [])
        total_input += len(search_docs)

        # Normalize document format
        normalized_docs = []
        for doc in search_docs:
            normalized_docs.append({
                "document_number": doc.get('num', doc.get('document_number', '')),
                "year": doc.get('year', ''),
                "document_type": doc.get('type', doc.get('document_type', '')),
                "recording_date": doc.get('recording_date', ''),
                "grantors": doc.get('grantors', ''),
                "grantees": doc.get('grantees', '')
            })

        result = dedup.add_documents(normalized_docs, search_name)
        search_summaries.append({
            "name": search_name,
            "input_count": len(search_docs),
            "new_unique": result.get('new', 0),
            "duplicates": result.get('duplicates', 0)
        })

    stats = dedup.get_statistics()
    multi_name_docs = dedup.get_multi_name_documents()
    single_name_docs = dedup.get_single_name_documents()

    dedup_log_info(f"[DEDUPLICATION_DEBUGLOGS] Preview: {total_input} -> {stats.get('unique_documents', 0)} unique")

    return jsonify(with_note({
        "success": True,
        "total_input": total_input,
        "unique_documents": stats.get('unique_documents', 0),
        "duplicates_removed": stats.get('duplicates_removed', 0),
        "savings_percent": round((stats.get('duplicates_removed', 0) / total_input * 100) if total_input > 0 else 0, 1),
        "multi_name_documents": len(multi_name_docs),
        "single_name_documents": len(single_name_docs),
        "search_summaries": search_summaries,
        "documents_per_name": stats.get('documents_per_name', {}),
        "deduplicated_documents": dedup.get_deduplicated(),
        "multi_name_document_details": multi_name_docs[:20]  # Limit to first 20 for response size
    }))


@app.route('/download/<job_id>', methods=['GET'])
def get_download_status(job_id):
    """Check status of a single download job"""
    if job_id in active_downloads:
        return jsonify(with_note(active_downloads[job_id]))
    return jsonify(with_note({"status": "not_found", "message": f"Job {job_id} not found"})), 404


@app.route('/list-files/<owner_name>', methods=['GET'])
def list_files(owner_name):
    """List all files in an owner's folder"""
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner

    if not folder_path.exists():
        return jsonify(with_note({
            "folder_exists": False,
            "folder_path": str(folder_path),
            "files": []
        }))

    files = []
    for f in folder_path.glob("*.pdf"):
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime
        })

    return jsonify(with_note({
        "folder_exists": True,
        "folder_path": str(folder_path),
        "files": sorted(files, key=lambda x: x["modified"], reverse=True)
    }))


@app.route('/analyze-documents', methods=['POST'])
def analyze_documents():
    """
    Analyze downloaded PDFs using Claude CLI to extract structured data.

    This endpoint triggers Claude CLI to read the PDFs and generate a detailed
    FINAL_REPORT.json with deed chain, legal description, mortgages, etc.

    Request body (JSON):
        owner_name: Owner name (required)
        property_address: Property address (optional)

    Returns:
        JSON with analysis status and results
    """
    import subprocess

    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    owner_name = data.get('owner_name')
    property_address = data.get('property_address', '')

    if not owner_name:
        return jsonify(with_note({"error": "owner_name is required"})), 400

    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner

    if not folder_path.exists():
        return jsonify(with_note({"success": False, "error": f"Folder not found: {folder_path}"})), 404

    # Get list of PDFs
    pdf_files = list(folder_path.glob("*.pdf"))
    if not pdf_files:
        return jsonify(with_note({"success": False, "error": "No PDF files found to analyze"})), 400

    # Build the prompt for Claude CLI
    prompt = f'''Analyze the property documents in the folder: {folder_path}

Read each PDF file and extract a detailed FINAL_REPORT.json with:
- property.address, city, state, zip, county, apn, legal_description
- current_owners.names, vesting, acquisition_date
- deed_chain (array of deeds with instrument_number, document_type, recording_date, grantor, grantee)
- mortgages_and_deeds_of_trust (with status: OPEN or RELEASED)
- tax_information
- critical_issues (if any)
- notes

Property address hint: {property_address}

Save the result to {folder_path}/FINAL_REPORT.json and regenerate {folder_path}/RAW_TWO_OWNER_SEARCH_EXAM.md

Return a summary of what you found.'''

    try:
        # Run Claude CLI with the analysis prompt
        # Use full path to claude CLI and set PATH environment
        claude_path = '/Users/ag/.local/bin/claude'
        env = os.environ.copy()
        env['PATH'] = '/Users/ag/.local/bin:' + env.get('PATH', '')

        result = subprocess.run(
            [claude_path, '-p', prompt, '--allowedTools', 'Read,Write,Bash'],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(BASE_DIR),
            env=env
        )

        if result.returncode == 0:
            # Check if FINAL_REPORT.json was created/updated
            final_report_path = folder_path / "FINAL_REPORT.json"
            if final_report_path.exists():
                report_data = json.loads(final_report_path.read_text())
                has_detail = bool(report_data.get("deed_chain") or report_data.get("property", {}).get("legal_description"))

                return jsonify(with_note({
                    "success": True,
                    "message": "Documents analyzed successfully",
                    "has_detailed_report": has_detail,
                    "pdf_count": len(pdf_files),
                    "claude_output": result.stdout[:2000] if result.stdout else "Analysis complete"
                }))
            else:
                return jsonify(with_note({
                    "success": False,
                    "error": "Analysis ran but FINAL_REPORT.json was not created",
                    "claude_output": result.stdout[:2000] if result.stdout else None
                }))
        else:
            return jsonify(with_note({
                "success": False,
                "error": f"Claude CLI failed: {result.stderr[:500] if result.stderr else 'Unknown error'}",
                "returncode": result.returncode
            }))

    except subprocess.TimeoutExpired:
        return jsonify(with_note({"success": False, "error": "Analysis timed out after 5 minutes"}))
    except FileNotFoundError:
        return jsonify(with_note({
            "success": False,
            "error": "Claude CLI not found. Make sure 'claude' is in PATH.",
            "suggestion": "Run analysis manually: claude -p 'Analyze PDFs in {folder_path}'"
        }))
    except Exception as e:
        return jsonify(with_note({"success": False, "error": str(e)}))


def perform_tax_lookup(county, apn, owner_name, property_address='', folder_path=None):
    """
    Underlying tax lookup helper used by both the /tax-lookup Flask route
    and the pipeline `tax_lookup` phase.

    Args:
        county: County name (required)
        apn: Assessor's Parcel Number (required)
        owner_name: Owner name for filename safe_owner generation (required)
        property_address: Optional property address hint
        folder_path: Optional explicit case directory. If None, defaults to
                     DOWNLOAD_BASE / safe_owner.

    Returns:
        dict with keys: success, tax_data (optional), tax_file_path (optional),
        county, method, error (optional). Does NOT call jsonify/with_note —
        callers wrap as needed.
    """
    import subprocess

    if not apn:
        return {"success": False, "error": "apn is required"}
    if not county:
        return {"success": False, "error": "county is required"}
    if not owner_name:
        return {"success": False, "error": "owner_name is required"}

    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    if folder_path is None:
        folder_path = DOWNLOAD_BASE / safe_owner
    folder_path = Path(folder_path)
    folder_path.mkdir(parents=True, exist_ok=True)
    tax_file_path = folder_path / f"tax_{safe_owner}.json"

    # Primary approach: Use Claude CLI with WebSearch to find tax info
    try:
        claude_path = '/Users/ag/.local/bin/claude'
        env = os.environ.copy()
        env['PATH'] = '/Users/ag/.local/bin:' + env.get('PATH', '')

        prompt = f'''Search the internet for the current year property tax information for this property:

APN (Assessor's Parcel Number): {apn}
County: {county} County, California
Property Address: {property_address or "unknown"}

Search the {county} County tax collector website, Zillow, Redfin, or any public tax record source.
Find the most recent tax year's information including:
- Tax year
- Annual tax amount
- 1st installment amount and payment status (PAID/UNPAID)
- 2nd installment amount and payment status (PAID/UNPAID)
- Assessed value (land, improvements, total)
- Any delinquencies or exemptions

Save the results as a JSON file to: {tax_file_path}

Use this exact JSON structure:
{{
  "lookup_metadata": {{
    "county": "{county}",
    "platform": "web_search",
    "lookup_timestamp": "<current ISO timestamp>",
    "apn_searched": "{apn}",
    "data_source": "<the website you found the data from>",
    "verification_url": "<URL where user can verify>"
  }},
  "tax_information": {{
    "tax_year": "<e.g. 2025-2026>",
    "apn": "{apn}",
    "annual_tax_estimated": "<e.g. $2,847.52>",
    "first_installment_amount": "<amount or empty>",
    "first_installment_status": "<PAID or UNPAID or empty>",
    "first_installment_due": "December 10",
    "second_installment_amount": "<amount or empty>",
    "second_installment_status": "<PAID or UNPAID or empty>",
    "second_installment_due": "April 10",
    "assessed_value_land": "<or empty>",
    "assessed_value_improvements": "<or empty>",
    "assessed_value_total": "<or empty>",
    "property_address": "<if found>",
    "delinquent": false,
    "exemptions_noted": "<if any>",
    "verification_url": "<URL>",
    "data_source": "<source website>"
  }}
}}

If you cannot find exact tax data, fill in what you can and leave other fields empty.
IMPORTANT: You must write the JSON file to {tax_file_path}. Do not skip this step.'''

        result = subprocess.run(
            [claude_path, '-p', prompt, '--allowedTools', 'WebSearch,WebFetch,Read,Write,Bash'],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout for tax lookup
            cwd=str(BASE_DIR),
            env=env
        )

        if result.returncode == 0 and tax_file_path.exists():
            try:
                tax_data = json.loads(tax_file_path.read_text())
                return {
                    "success": True,
                    "tax_data": tax_data.get("tax_information", tax_data),
                    "tax_file_path": str(tax_file_path),
                    "county": county,
                    "method": "claude_web_search",
                }
            except json.JSONDecodeError:
                pass

        # If Claude didn't create the file, try extracting from its output
        if result.returncode == 0:
            return {
                "success": False,
                "error": "Claude searched but could not save tax data file",
                "claude_output": result.stdout[:1000] if result.stdout else None,
                "county": county,
                "method": "claude_web_search",
            }

    except FileNotFoundError:
        pass  # Claude CLI not available, fall through to Selenium
    except subprocess.TimeoutExpired:
        pass  # Timed out, fall through
    except Exception as e:
        print(f"[tax-lookup] Claude CLI approach failed: {e}")

    # Fallback: Use Selenium scrapers
    try:
        from titlepro.tax.multi_county_tax import lookup_tax, save_tax_file

        tax_data = lookup_tax(apn, county)
        tax_file_path = save_tax_file(tax_data, folder_path, owner_name)

        return {
            "success": tax_data.get("success", False),
            "tax_data": tax_data,
            "tax_file_path": str(tax_file_path),
            "county": county,
            "method": "selenium_scraper",
        }
    except Exception as e:
        return {"success": False, "error": f"All tax lookup methods failed: {e}"}


@app.route('/tax-lookup', methods=['POST'])
def tax_lookup():
    """
    Look up property tax information for a given APN and county.

    Uses Claude CLI with WebSearch to find tax info from county websites,
    Zillow, or Redfin. Falls back to Selenium scrapers if available.

    Request body (JSON):
        apn: Assessor's Parcel Number (required)
        county: County name (required, e.g., "amador", "orange")
        owner_name: Owner name for file saving (required)
        property_address: Property address hint (optional)

    Returns:
        JSON with tax data and file path
    """
    data = request.get_json()
    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    apn = data.get('apn')
    county = data.get('county')
    owner_name = data.get('owner_name')
    property_address = data.get('property_address', '')

    if not apn:
        return jsonify(with_note({"success": False, "error": "apn is required"})), 400
    if not county:
        return jsonify(with_note({"success": False, "error": "county is required"})), 400
    if not owner_name:
        return jsonify(with_note({"success": False, "error": "owner_name is required"})), 400

    result = perform_tax_lookup(
        county=county,
        apn=apn,
        owner_name=owner_name,
        property_address=property_address,
    )
    return jsonify(with_note(result))


@app.route('/generate-report', methods=['POST'])
def generate_report():
    """
    Generate a RAW Two Owner Search Exam report.

    Request body (JSON):
        owner_name: Owner name (required)
        property_address: Property address (optional)
        fetch_tax: Whether to fetch tax info from OC Treasurer (optional, default: true)

    Returns:
        JSON with report_markdown and report_json
    """
    from titlepro.reports.report_generator import generate_report_for_owner

    data = request.get_json()

    if not data:
        return jsonify(with_note({"error": "JSON body required"})), 400

    owner_name = data.get('owner_name')
    property_address = data.get('property_address', '')
    fetch_tax = data.get('fetch_tax', True)  # Default to fetching tax info

    if not owner_name:
        return jsonify(with_note({"error": "owner_name is required"})), 400

    try:
        result = generate_report_for_owner(owner_name, property_address, fetch_tax=fetch_tax)
        return jsonify(with_note(result))
    except Exception as e:
        return jsonify(with_note({"success": False, "error": str(e)})), 500


@app.route('/list-reports', methods=['GET'])
def list_reports():
    """List all owner folders that contain a generated .md report."""
    reports = []
    if DOWNLOAD_BASE.exists():
        for folder in sorted(DOWNLOAD_BASE.iterdir()):
            if folder.is_dir() and not folder.name.startswith('.'):
                md_file = folder / "RAW_TWO_OWNER_SEARCH_EXAM.md"
                if md_file.exists():
                    stat = md_file.stat()
                    reports.append({
                        "owner_folder": folder.name,
                        "display_name": folder.name.replace("_", " "),
                        "modified": stat.st_mtime,
                        "size": stat.st_size
                    })
    # Sort by most recently modified first
    reports.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({"success": True, "reports": reports})


@app.route('/read-report/<owner_folder>', methods=['GET'])
def read_report(owner_folder):
    """Read the markdown content of an existing report."""
    safe_folder = owner_folder.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_folder
    # Path traversal protection
    if not folder_path.resolve().is_relative_to(DOWNLOAD_BASE.resolve()):
        return jsonify({"success": False, "error": "Invalid folder"}), 400
    md_path = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
    if not md_path.exists():
        return jsonify({"success": False, "error": "Report not found"}), 404
    content = md_path.read_text(encoding='utf-8')
    return jsonify({"success": True, "markdown": content, "owner_folder": safe_folder})


@app.route('/check-owner-reports/<owner_name>', methods=['GET'])
def check_owner_reports(owner_name):
    """Check which generated reports exist for an owner (RAW report, Title Exam Notes)."""
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner

    if not folder_path.resolve().is_relative_to(DOWNLOAD_BASE.resolve()):
        return jsonify({"success": False, "error": "Invalid owner"}), 400

    reports = {}

    # Check RAW Two Owner Search Exam
    raw_md = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
    if raw_md.exists():
        stat = raw_md.stat()
        reports["raw_report"] = {
            "exists": True,
            "filename": "RAW_TWO_OWNER_SEARCH_EXAM.md",
            "modified": stat.st_mtime,
            "size": stat.st_size
        }
    else:
        reports["raw_report"] = {"exists": False}

    # Check Title Examination Notes (pattern: Title_Examination_Notes_*.md)
    title_exam_files = sorted(folder_path.glob("Title_Examination_Notes_*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if folder_path.exists() else []
    if title_exam_files:
        latest = title_exam_files[0]
        stat = latest.stat()
        reports["title_exam"] = {
            "exists": True,
            "filename": latest.name,
            "modified": stat.st_mtime,
            "size": stat.st_size
        }
    else:
        reports["title_exam"] = {"exists": False}

    return jsonify({"success": True, "owner": safe_owner, "reports": reports})


@app.route('/get-report/<owner_name>', methods=['GET'])
def get_report(owner_name):
    """Get existing report for an owner."""
    from titlepro.reports.report_generator import generate_report_for_owner

    try:
        result = generate_report_for_owner(owner_name, "")
        return jsonify(with_note(result))
    except Exception as e:
        return jsonify(with_note({"success": False, "error": str(e)})), 500


@app.route('/api/workflow/status', methods=['POST'])
def workflow_status():
    """Load saved or posted gated workflow status for a case."""
    if not WORKFLOW_AVAILABLE:
        return jsonify(with_note({
            "success": False,
            "workflow_available": False,
            "error": WORKFLOW_IMPORT_ERROR or "Workflow automation is unavailable.",
        })), 500

    data = request.get_json(silent=True) or {}

    try:
        config = load_workflow_config_from_request(data)
        payload = build_workflow_status_payload(config, save_config_file=bool(data.get("config")))
        return jsonify(with_note(payload))
    except Exception as e:
        status_code = 404 if "not found" in str(e).lower() else 400
        return jsonify(with_note({
            "success": False,
            "workflow_available": WORKFLOW_AVAILABLE,
            "error": str(e),
        })), status_code


@app.route('/api/workflow/run-phase', methods=['POST'])
def workflow_run_phase():
    """Run one gated workflow phase in the background."""
    if not WORKFLOW_AVAILABLE:
        return jsonify(with_note({
            "success": False,
            "workflow_available": False,
            "error": WORKFLOW_IMPORT_ERROR or "Workflow automation is unavailable.",
        })), 500

    data = request.get_json(silent=True)
    if not data:
        return jsonify(with_note({"success": False, "error": "JSON body required"})), 400

    phase = data.get("phase")
    force = bool(data.get("force", False))

    if not phase:
        return jsonify(with_note({"success": False, "error": "phase is required"})), 400

    try:
        config = load_workflow_config_from_request(data)
        pipeline = RecorderAutomationPipeline(config)
        if phase not in pipeline.phase_order:
            return jsonify(with_note({
                "success": False,
                "error": f"Unknown phase '{phase}'. Valid phases: {', '.join(pipeline.phase_order)}",
            })), 400
        if not pipeline.phase_enabled(phase):
            return jsonify(with_note({
                "success": False,
                "error": f"Phase '{phase}' is disabled by the current workflow configuration.",
            })), 400

        save_workflow_config(pipeline)
    except Exception as e:
        status_code = 404 if "not found" in str(e).lower() else 400
        return jsonify(with_note({"success": False, "error": str(e)})), status_code

    import uuid

    job_id = f"workflow_{str(uuid.uuid4())[:8]}"
    workflow_jobs[job_id] = {
        "status": "starting",
        "success": False,
        "phase": phase,
        "safe_owner": config.safe_owner,
        "message": f"Queued phase '{phase}'.",
        "started_at": datetime.now().isoformat(),
        "force": force,
    }

    def run_phase_job():
        try:
            workflow_jobs[job_id].update({
                "status": "running",
                "message": f"Running phase '{phase}'. Check the Logs tab for live details.",
            })
            pipeline = RecorderAutomationPipeline(config)
            save_workflow_config(pipeline)
            state = pipeline.run_phase(phase, force=force)
            result = build_workflow_status_payload(config, save_config_file=False)
            workflow_jobs[job_id].update({
                "status": "completed",
                "success": True,
                "message": f"Phase '{phase}' completed successfully.",
                "completed_at": datetime.now().isoformat(),
                "state": state,
                "result": result,
            })
        except HumanCheckpointRequired as checkpoint:
            result = None
            try:
                result = build_workflow_status_payload(config, save_config_file=False)
            except Exception:
                result = None
            workflow_jobs[job_id].update({
                "status": "needs_human",
                "success": False,
                "checkpoint": checkpoint.to_dict(),
                "resume_token": checkpoint.resume_token,
                "message": checkpoint.message,
                "completed_at": datetime.now().isoformat(),
                "result": result,
            })
        except Exception as e:
            result = None
            try:
                result = build_workflow_status_payload(config, save_config_file=False)
            except Exception:
                result = None
            workflow_jobs[job_id].update({
                "status": "failed",
                "success": False,
                "error": str(e),
                "message": f"Phase '{phase}' failed: {str(e)}",
                "completed_at": datetime.now().isoformat(),
                "result": result,
            })

    thread = threading.Thread(target=run_phase_job, daemon=True)
    thread.start()

    return jsonify(with_note({
        "success": True,
        "job_id": job_id,
        "phase": phase,
        "safe_owner": config.safe_owner,
        "message": f"Workflow phase '{phase}' started.",
    }))


@app.route('/api/workflow/job/<job_id>', methods=['GET'])
def workflow_job_status(job_id):
    """Poll background workflow phase job status."""
    job = workflow_jobs.get(job_id)
    if not job:
        return jsonify(with_note({"success": False, "error": "Workflow job not found"})), 404
    return jsonify(with_note(job))


@app.route('/api/workflow/resume-checkpoint', methods=['POST'])
def workflow_resume_checkpoint():
    """Resume a gated workflow after a human checkpoint such as CAPTCHA."""
    if not WORKFLOW_AVAILABLE:
        return jsonify(with_note({
            "success": False,
            "workflow_available": False,
            "error": WORKFLOW_IMPORT_ERROR or "Workflow automation is unavailable.",
        })), 500

    data = request.get_json(silent=True)
    if not data:
        return jsonify(with_note({"success": False, "error": "JSON body required"})), 400

    resume_token = data.get("resume_token")
    if not resume_token:
        return jsonify(with_note({"success": False, "error": "resume_token is required"})), 400

    try:
        config = load_workflow_config_from_request(data)
        pipeline = RecorderAutomationPipeline(config)
        save_workflow_config(pipeline)
    except Exception as e:
        status_code = 404 if "not found" in str(e).lower() else 400
        return jsonify(with_note({"success": False, "error": str(e)})), status_code

    import uuid

    job_id = f"workflow_resume_{str(uuid.uuid4())[:8]}"
    workflow_jobs[job_id] = {
        "status": "starting",
        "success": False,
        "phase": "search",
        "safe_owner": config.safe_owner,
        "message": "Queued CAPTCHA checkpoint resume.",
        "started_at": datetime.now().isoformat(),
        "resume_token": resume_token,
    }

    def run_resume_job():
        try:
            workflow_jobs[job_id].update({
                "status": "running",
                "message": "Resuming workflow after human checkpoint.",
            })
            pipeline = RecorderAutomationPipeline(config)
            state = pipeline.resume_checkpoint(resume_token)
            result = build_workflow_status_payload(config, save_config_file=False)
            workflow_jobs[job_id].update({
                "status": "completed",
                "success": True,
                "message": "Checkpoint resumed and search phase completed.",
                "completed_at": datetime.now().isoformat(),
                "state": state,
                "result": result,
            })
        except HumanCheckpointRequired as checkpoint:
            result = None
            try:
                result = build_workflow_status_payload(config, save_config_file=False)
            except Exception:
                result = None
            workflow_jobs[job_id].update({
                "status": "needs_human",
                "success": False,
                "checkpoint": checkpoint.to_dict(),
                "resume_token": checkpoint.resume_token,
                "message": checkpoint.message,
                "completed_at": datetime.now().isoformat(),
                "result": result,
            })
        except Exception as e:
            result = None
            try:
                result = build_workflow_status_payload(config, save_config_file=False)
            except Exception:
                result = None
            workflow_jobs[job_id].update({
                "status": "failed",
                "success": False,
                "error": str(e),
                "message": f"Checkpoint resume failed: {str(e)}",
                "completed_at": datetime.now().isoformat(),
                "result": result,
            })

    thread = threading.Thread(target=run_resume_job, daemon=True)
    thread.start()

    return jsonify(with_note({
        "success": True,
        "job_id": job_id,
        "phase": "search",
        "safe_owner": config.safe_owner,
        "resume_token": resume_token,
        "message": "Workflow checkpoint resume started.",
    }))


@app.route('/api/workflow/resume', methods=['POST'])
def workflow_resume_alias():
    """Alias for /api/workflow/resume-checkpoint matching the proposal's name."""
    return workflow_resume_checkpoint()


@app.route('/api/workflow/renew', methods=['POST'])
def workflow_renew_checkpoint():
    """Extend the expiry of an active human checkpoint."""
    if not WORKFLOW_AVAILABLE or checkpoint_sessions is None:
        return jsonify(with_note({
            "success": False,
            "workflow_available": False,
            "error": WORKFLOW_IMPORT_ERROR or "Workflow automation is unavailable.",
        })), 500

    data = request.get_json(silent=True) or {}
    resume_token = data.get("resume_token")
    if not resume_token:
        return jsonify(with_note({"success": False, "error": "resume_token is required"})), 400
    additional_seconds = data.get("additional_seconds")
    try:
        if additional_seconds is not None:
            additional_seconds = int(additional_seconds)
    except (TypeError, ValueError):
        return jsonify(with_note({"success": False, "error": "additional_seconds must be an integer"})), 400

    try:
        session = checkpoint_sessions.renew(resume_token, additional_seconds)
    except KeyError as e:
        return jsonify(with_note({"success": False, "error": str(e)})), 404
    except Exception as e:
        return jsonify(with_note({"success": False, "error": str(e)})), 400

    return jsonify(with_note({
        "success": True,
        "resume_token": resume_token,
        "expires_at": session.expires_at.isoformat(),
        "session_key": session.session_key,
        "renewable": session.renewable,
        "message": "Checkpoint expiry extended.",
    }))


@app.route('/api/workflow/cancel', methods=['POST'])
def workflow_cancel_checkpoint():
    """Cancel an active human checkpoint and close the live browser session."""
    if not WORKFLOW_AVAILABLE or checkpoint_sessions is None:
        return jsonify(with_note({
            "success": False,
            "workflow_available": False,
            "error": WORKFLOW_IMPORT_ERROR or "Workflow automation is unavailable.",
        })), 500

    data = request.get_json(silent=True) or {}
    resume_token = data.get("resume_token")
    if not resume_token:
        return jsonify(with_note({"success": False, "error": "resume_token is required"})), 400

    session = checkpoint_sessions.cancel(resume_token)

    # Best-effort: mark every workflow job carrying this token as cancelled
    # so the UI poll stops spinning.
    for job in workflow_jobs.values():
        if job.get("resume_token") == resume_token:
            job["status"] = "cancelled"
            job["message"] = "Checkpoint cancelled by user."

    return jsonify(with_note({
        "success": True,
        "resume_token": resume_token,
        "cancelled": session is not None,
        "message": "Checkpoint cancelled and browser closed." if session else "No active checkpoint for that token.",
    }))


title_exam_jobs = {}


def _run_title_exam_generation(job_id, owner_name, raw_markdown, system_prompt, folder_path, safe_owner):
    """Background worker for title exam notes generation."""
    from titlepro.api.claude_client import get_claude_client

    try:
        client = get_claude_client()
        mode = client.mode

        title_exam_jobs[job_id]['status'] = 'running'
        title_exam_jobs[job_id]['message'] = f'Claude ({mode}) is generating Title Examination Notes...'

        user_prompt = f"""Generate Title Examination Notes from the following RAW Two Owner Search Exam report.

Output ONLY the markdown content for the Title Examination Notes document. Do not include any preamble or explanation.

--- BEGIN RAW REPORT ---
{raw_markdown}
--- END RAW REPORT ---"""

        print(f"[title-exam-notes] Generating for {owner_name} using Claude {mode} mode...")

        response = client.run(
            user_prompt,
            system_prompt=system_prompt,
            max_tokens=16000,
            timeout=600,
            allowed_tools=['WebSearch', 'WebFetch', 'Read', 'Write'] if mode == 'cli' else None,
            cwd=str(BASE_DIR) if mode == 'cli' else None
        )

        if response.success and response.output:
            title_exam_markdown = response.output.strip()

            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"Title_Examination_Notes_{safe_owner.upper()}_{date_str}.md"
            output_path = folder_path / filename
            output_path.write_text(title_exam_markdown, encoding='utf-8')

            print(f"[title-exam-notes] Saved to {output_path}")

            title_exam_jobs[job_id].update({
                'status': 'completed',
                'success': True,
                'title_exam_markdown': title_exam_markdown,
                'filename': filename,
                'file_path': str(output_path),
                'claude_mode': mode,
                'message': 'Title Examination Notes generated successfully'
            })
        else:
            error_msg = response.error or "Claude returned no output"
            print(f"[title-exam-notes] Error: {error_msg}")
            title_exam_jobs[job_id].update({
                'status': 'failed',
                'success': False,
                'error': error_msg,
                'claude_mode': mode,
                'message': f'Generation failed: {error_msg}'
            })

    except Exception as e:
        print(f"[title-exam-notes] Exception: {e}")
        import traceback
        traceback.print_exc()
        title_exam_jobs[job_id].update({
            'status': 'failed',
            'success': False,
            'error': str(e),
            'message': f'Error: {str(e)}'
        })


@app.route('/generate-title-exam-notes', methods=['POST'])
def generate_title_exam_notes():
    """Start generating Title Examination Notes (background job)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    owner_name = data.get('owner_name')
    raw_markdown = data.get('raw_markdown')

    if not owner_name:
        return jsonify({"error": "owner_name is required"}), 400
    if not raw_markdown:
        return jsonify({"error": "raw_markdown is required"}), 400

    system_prompt_path = Path(__file__).resolve().parent.parent.parent.parent / 'Title_Examination_Notes_System_Prompt.md'
    if not system_prompt_path.exists():
        return jsonify({"success": False, "error": f"System prompt not found at {system_prompt_path}"}), 500

    system_prompt = system_prompt_path.read_text(encoding='utf-8')

    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner
    folder_path.mkdir(parents=True, exist_ok=True)

    import uuid
    job_id = str(uuid.uuid4())[:8]
    title_exam_jobs[job_id] = {
        'status': 'starting',
        'success': False,
        'owner_name': owner_name,
        'message': 'Starting Claude AI generation...',
        'started_at': datetime.now().isoformat()
    }

    thread = threading.Thread(
        target=_run_title_exam_generation,
        args=(job_id, owner_name, raw_markdown, system_prompt, folder_path, safe_owner),
        daemon=True
    )
    thread.start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "message": "Title Examination Notes generation started. Poll /title-exam-status/<job_id> for results."
    })


@app.route('/title-exam-status/<job_id>', methods=['GET'])
def title_exam_status(job_id):
    """Check status of a title exam notes generation job."""
    job = title_exam_jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    return jsonify(job)


@app.route('/download-pdf', methods=['POST'])
def download_pdf():
    """
    Generate and download a professionally formatted PDF report.

    Request body (JSON):
        owner_name: Owner name (required)
        property_address: Property address (optional)

    Returns:
        PDF file download
    """
    from io import BytesIO
    from datetime import datetime

    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    owner_name = data.get('owner_name')
    if not owner_name:
        return jsonify({"error": "owner_name is required"}), 400

    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_BASE / safe_owner

    # Check for existing markdown report
    md_path = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
    if not md_path.exists():
        return jsonify({"error": f"Report not found at {md_path}. Generate report first."}), 404

    try:
        markdown_content = md_path.read_text(encoding='utf-8')

        # Convert markdown to HTML with professional styling
        html_content = markdown_to_styled_html(markdown_content, owner_name)

        pdf_buffer = BytesIO()
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"RAW_Two_Owner_Search_{safe_owner}_{date_str}.pdf"

        # Try weasyprint first, fall back to xhtml2pdf
        pdf_engine = None
        weasy_err = None
        xhtml2pdf_err = None

        try:
            from weasyprint import HTML as WeasyprintHTML
            WeasyprintHTML(string=html_content).write_pdf(pdf_buffer)
            pdf_engine = "weasyprint"
        except Exception as e:
            weasy_err = str(e)
            print(f"[download-pdf] weasyprint unavailable: {e}")

        if pdf_engine is None:
            try:
                from xhtml2pdf import pisa
                pdf_buffer = BytesIO()
                pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)
                if pisa_status.err:
                    xhtml2pdf_err = f"xhtml2pdf returned {pisa_status.err} error(s)"
                    print(f"[download-pdf] {xhtml2pdf_err}")
                else:
                    pdf_engine = "xhtml2pdf"
            except Exception as e:
                xhtml2pdf_err = str(e)
                print(f"[download-pdf] xhtml2pdf failed: {e}")
                import traceback
                traceback.print_exc()

        if pdf_engine is None:
            err_detail = xhtml2pdf_err or weasy_err or "unknown"
            return jsonify({"success": False, "error": f"PDF generation failed: {err_detail}"}), 500

        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[download-pdf] Error: {e}")
        return jsonify({"success": False, "error": f"PDF generation failed: {str(e)}"}), 500


def markdown_to_styled_html(markdown_content: str, owner_name: str) -> str:
    """
    Convert markdown report to professionally styled HTML for PDF generation.

    Follows professional title report formatting standards.
    """
    import re
    from datetime import datetime

    # Parse markdown sections
    lines = markdown_content.split('\n')
    html_parts = []

    in_table = False
    table_rows = []
    current_section = None

    for line in lines:
        # Skip empty lines in certain contexts
        stripped = line.strip()

        # Headers
        if stripped.startswith('# '):
            if in_table:
                html_parts.append(render_table(table_rows))
                in_table = False
                table_rows = []
            html_parts.append(f'<h1 class="main-title">{stripped[2:]}</h1>')
            continue

        if stripped.startswith('## '):
            if in_table:
                html_parts.append(render_table(table_rows))
                in_table = False
                table_rows = []
            section_title = stripped[3:]
            current_section = section_title
            html_parts.append(f'<h2 class="section-title">{section_title}</h2>')
            continue

        if stripped.startswith('### '):
            if in_table:
                html_parts.append(render_table(table_rows))
                in_table = False
                table_rows = []
            subsection = stripped[4:]
            # Handle bold markers
            subsection = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', subsection)
            html_parts.append(f'<h3 class="subsection-title">{subsection}</h3>')
            continue

        # Horizontal rules
        if stripped == '---':
            if in_table:
                html_parts.append(render_table(table_rows))
                in_table = False
                table_rows = []
            html_parts.append('<hr class="section-divider">')
            continue

        # Bold metadata lines (like **Order Number:** etc)
        if stripped.startswith('**') and ':**' in stripped:
            if in_table:
                html_parts.append(render_table(table_rows))
                in_table = False
                table_rows = []
            # Parse key-value pair
            match = re.match(r'\*\*(.+?):\*\*\s*(.*)', stripped)
            if match:
                key, value = match.groups()
                html_parts.append(f'<p class="meta-line"><strong>{key}:</strong> {value}</p>')
            continue

        # Table handling
        if '|' in stripped and stripped.startswith('|'):
            # Check if it's a separator row
            if re.match(r'\|[-:\s|]+\|', stripped):
                continue  # Skip markdown table separators

            # Parse table row
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if cells:
                if not in_table:
                    in_table = True
                    table_rows = []
                table_rows.append(cells)
            continue

        # If we were in a table and hit non-table content
        if in_table:
            html_parts.append(render_table(table_rows))
            in_table = False
            table_rows = []

        # Numbered list items
        if re.match(r'^\d+\.', stripped):
            text = re.sub(r'^\d+\.\s*', '', stripped)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            html_parts.append(f'<p class="numbered-item">{text}</p>')
            continue

        # Italic text (like *Report Generated:*)
        if stripped.startswith('*') and stripped.endswith('*') and not stripped.startswith('**'):
            text = stripped[1:-1]
            html_parts.append(f'<p class="footer-text"><em>{text}</em></p>')
            continue

        # Regular paragraphs with bold handling
        if stripped:
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            # Handle links
            text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
            html_parts.append(f'<p>{text}</p>')

    # Close any open table
    if in_table:
        html_parts.append(render_table(table_rows))

    body_content = '\n'.join(html_parts)

    # Modern CSS styling for title reports - Calibri with color accents
    # Note: @page uses only simple properties for xhtml2pdf compatibility
    # (nested @bottom-center is weasyprint-only and breaks xhtml2pdf)
    css = '''
    @page {
        size: letter;
        margin: 0.75in 0.75in 1in 0.75in;
    }

    body {
        font-family: Calibri, "Segoe UI", Arial, sans-serif;
        font-size: 11pt;
        line-height: 1.5;
        color: #333;
        max-width: 100%;
    }

    .main-title {
        font-size: 18pt;
        font-weight: bold;
        text-align: center;
        margin-bottom: 20px;
        color: #1a5276;
        text-transform: uppercase;
        letter-spacing: 1px;
        border-bottom: 3px solid #2980b9;
        padding-bottom: 12px;
    }

    .meta-line {
        margin: 5px 0;
        font-size: 10pt;
        color: #444;
    }

    .meta-line strong {
        color: #1a5276;
    }

    .section-title {
        font-size: 13pt;
        font-weight: bold;
        margin-top: 22px;
        margin-bottom: 12px;
        color: #fff;
        text-transform: uppercase;
        background-color: #2980b9;
        padding: 8px 12px;
        border-radius: 4px;
    }

    .subsection-title {
        font-size: 11pt;
        font-weight: bold;
        margin-top: 16px;
        margin-bottom: 8px;
        color: #1a5276;
        border-left: 4px solid #2980b9;
        padding-left: 10px;
    }

    .section-divider {
        border: none;
        border-top: 1px solid #ddd;
        margin: 18px 0;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 18px 0;
        font-size: 10pt;
    }

    th {
        background-color: #2980b9;
        color: #fff;
        font-weight: bold;
        text-align: left;
        padding: 10px 12px;
        border: 1px solid #2471a3;
    }

    td {
        padding: 8px 12px;
        border: 1px solid #ddd;
        vertical-align: top;
    }

    tr:nth-child(even) td {
        background-color: #f8f9fa;
    }

    td:first-child {
        font-weight: 600;
        width: 35%;
        color: #1a5276;
        background-color: #eaf2f8;
    }

    tr:nth-child(even) td:first-child {
        background-color: #d4e6f1;
    }

    .numbered-item {
        margin: 8px 0 8px 24px;
        padding-left: 8px;
        border-left: 2px solid #2980b9;
    }

    p {
        margin: 8px 0;
        text-align: justify;
    }

    strong {
        font-weight: bold;
        color: #1a5276;
    }

    .footer-text {
        font-size: 9pt;
        color: #777;
        margin-top: 24px;
        text-align: center;
        font-style: italic;
    }

    a {
        color: #2980b9;
        text-decoration: none;
    }

    a:hover {
        text-decoration: underline;
    }

    /* Legal description styling */
    .legal-desc {
        font-size: 10pt;
        line-height: 1.6;
        margin: 12px 0;
        text-align: justify;
    }

    /* Disclaimer styling */
    .disclaimer {
        font-size: 9pt;
        color: #555;
        font-style: italic;
        margin-top: 24px;
        padding: 12px;
        border: 1px solid #2980b9;
        background-color: #eaf2f8;
        border-radius: 4px;
    }

    /* [REPORT_FORMAT_DEBUGLOGS] New CSS classes for report format updates */

    /* Party header styling for liens section */
    .party-header {
        font-size: 12pt;
        font-weight: bold;
        color: #1a5276;
        margin-top: 16px;
        margin-bottom: 8px;
        padding: 6px 10px;
        background-color: #d4e6f1;
        border-left: 4px solid #2980b9;
        border-radius: 2px;
    }

    /* Open lien styling - red/warning */
    .lien-open {
        color: #c0392b;
        font-weight: bold;
        background-color: #fadbd8;
        padding: 2px 6px;
        border-radius: 3px;
    }

    /* Released lien styling - green */
    .lien-released {
        color: #27ae60;
        font-weight: bold;
        background-color: #d5f4e6;
        padding: 2px 6px;
        border-radius: 3px;
    }

    /* Discovered name highlight */
    .discovered-name {
        background-color: #fef9e7;
        border: 1px solid #f4d03f;
        padding: 2px 6px;
        border-radius: 3px;
        font-style: italic;
    }

    /* Title Vested As section styling */
    .vesting-section {
        background-color: #eaf2f8;
        border: 2px solid #2980b9;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 16px 0;
        font-size: 11pt;
    }

    .vesting-section strong {
        font-size: 12pt;
        color: #1a5276;
    }

    /* Search summary section styling */
    .search-summary {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 4px;
        padding: 12px 16px;
        margin: 16px 0;
        font-size: 10pt;
    }

    .search-summary strong {
        color: #1a5276;
    }

    /* Documents examined table styling */
    .documents-examined-table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 9pt;
    }

    .documents-examined-table th {
        background-color: #34495e;
        color: white;
        padding: 8px 10px;
        text-align: left;
    }

    .documents-examined-table td {
        padding: 6px 10px;
        border-bottom: 1px solid #dee2e6;
    }

    .documents-examined-table tr:nth-child(even) td {
        background-color: #f8f9fa;
    }

    /* Found Via column styling */
    .found-via {
        font-size: 8pt;
        color: #666;
        font-style: italic;
    }
    '''

    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>RAW Two Owner Search Exam - {owner_name}</title>
    <style>
    {css}
    </style>
</head>
<body>
{body_content}
</body>
</html>'''

    return html


def render_table(rows):
    """Render a markdown table as HTML."""
    if not rows:
        return ''

    html = '<table>'

    # First row is header
    if rows:
        html += '<thead><tr>'
        for cell in rows[0]:
            html += f'<th>{cell}</th>'
        html += '</tr></thead>'

    # Rest are body rows
    if len(rows) > 1:
        html += '<tbody>'
        for row in rows[1:]:
            html += '<tr>'
            for cell in row:
                # Handle bold text in cells
                import re
                cell_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', cell)
                html += f'<td>{cell_html}</td>'
            html += '</tr>'
        html += '</tbody>'

    html += '</table>'
    return html


# ========== FILE BROWSER API ==========

@app.route('/api/files', methods=['GET'])
def api_list_files():
    """
    List files and folders in downloaded_doc directory.

    Query params:
        path: Relative path within downloaded_doc (optional)

    Returns:
        JSON with files and folders list
    """
    relative_path = request.args.get('path', '')

    # Sanitize path to prevent directory traversal
    safe_path = relative_path.replace('..', '').strip('/')

    target_dir = DOWNLOAD_BASE / safe_path if safe_path else DOWNLOAD_BASE

    if not target_dir.exists():
        return jsonify({"success": False, "error": "Directory not found"}), 404

    if not str(target_dir.resolve()).startswith(str(DOWNLOAD_BASE.resolve())):
        return jsonify({"success": False, "error": "Invalid path"}), 400

    files = []
    folders = []
    all_folders = []

    try:
        # Get immediate contents
        for item in target_dir.iterdir():
            if item.name.startswith('.'):
                continue

            if item.is_file():
                files.append({
                    "name": item.name,
                    "path": str(item.relative_to(DOWNLOAD_BASE)),
                    "size": item.stat().st_size,
                    "modified": item.stat().st_mtime
                })
            elif item.is_dir():
                file_count = sum(1 for f in item.iterdir() if f.is_file() and not f.name.startswith('.'))
                folders.append({
                    "name": item.name,
                    "path": str(item.relative_to(DOWNLOAD_BASE)),
                    "file_count": file_count,
                    "parent": safe_path
                })

        # Get all folders recursively for the folder tree
        def get_all_folders(dir_path, depth=0):
            result = []
            try:
                for item in sorted(dir_path.iterdir()):
                    if item.is_dir() and not item.name.startswith('.'):
                        file_count = sum(1 for f in item.iterdir() if f.is_file() and not f.name.startswith('.'))
                        rel_path = str(item.relative_to(DOWNLOAD_BASE))
                        parent_path = str(item.parent.relative_to(DOWNLOAD_BASE)) if item.parent != DOWNLOAD_BASE else ""
                        result.append({
                            "name": item.name,
                            "path": rel_path,
                            "file_count": file_count,
                            "depth": depth,
                            "parent": parent_path
                        })
                        result.extend(get_all_folders(item, depth + 1))
            except PermissionError:
                pass
            return result

        all_folders = get_all_folders(DOWNLOAD_BASE)

        # Sort files by modified time (newest first)
        files.sort(key=lambda x: x.get('modified', 0), reverse=True)

        return jsonify({
            "success": True,
            "path": safe_path,
            "files": files,
            "folders": folders,
            "all_folders": all_folders
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/file/<path:filepath>', methods=['GET'])
def api_get_file(filepath):
    """
    Serve a file from the downloaded_doc directory.

    Path params:
        filepath: Relative path to file within downloaded_doc

    Query params:
        download: If 'true', force download instead of inline display

    Returns:
        The file content
    """
    # Sanitize path
    safe_path = filepath.replace('..', '')
    file_path = DOWNLOAD_BASE / safe_path

    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404

    if not str(file_path.resolve()).startswith(str(DOWNLOAD_BASE.resolve())):
        return jsonify({"error": "Invalid path"}), 400

    if not file_path.is_file():
        return jsonify({"error": "Not a file"}), 400

    # Determine if we should force download
    force_download = request.args.get('download', '').lower() == 'true'

    # Get mimetype
    ext = file_path.suffix.lower()
    mimetypes = {
        '.pdf': 'application/pdf',
        '.json': 'application/json',
        '.md': 'text/markdown',
        '.txt': 'text/plain',
        '.html': 'text/html',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif'
    }
    mimetype = mimetypes.get(ext, 'application/octet-stream')

    if force_download:
        return send_file(file_path, as_attachment=True, download_name=file_path.name)
    else:
        return send_file(file_path, mimetype=mimetype)


# ========== LOGS API ==========

# Circular buffer for server logs
server_logs = []
MAX_LOG_LINES = 500

# Capture stdout/stderr for logs
import sys
import io

class LogCapture:
    def __init__(self, original_stream, log_buffer):
        self.original_stream = original_stream
        self.log_buffer = log_buffer

    def write(self, text):
        if text.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for line in text.strip().split('\n'):
                if line.strip():
                    log_entry = f"[{timestamp}] {line}"
                    self.log_buffer.append(log_entry)
                    # Keep only last MAX_LOG_LINES
                    while len(self.log_buffer) > MAX_LOG_LINES:
                        self.log_buffer.pop(0)
        self.original_stream.write(text)

    def flush(self):
        self.original_stream.flush()

# Install log capture
sys.stdout = LogCapture(sys.stdout, server_logs)
sys.stderr = LogCapture(sys.stderr, server_logs)


# =============================================================================
# NAT INTEGRATION ENDPOINTS
# Fire-and-forget async pipeline API for NAT order management.
# =============================================================================  # noqa — duplicate marker removed below
# Fire-and-forget async pipeline API for NAT order management.
# NAT POSTs an order → CURE ACKs immediately → background thread runs
# RecorderAutomationPipeline → CURE POSTs 47-field callback to NAT.
# =============================================================================

import traceback as _tb
import requests as _requests

# ── Job tracker ───────────────────────────────────────────────────────────────
nat_jobs: dict = {}
NAT_JOBS_DIR = BASE_DIR / ".nat_jobs"
NAT_JOBS_DIR.mkdir(exist_ok=True)
NAT_TRASH_DIR = BASE_DIR / ".nat_trash"
NAT_TRASH_DIR.mkdir(exist_ok=True)

# ── Pipeline concurrency control ───────────────────────────────────────────────
# 1 = serial queue (safest — one job runs, rest wait in order).
# Raise to 2-3 only after confirming recorder/Claude rate limits allow it.
# Configurable via "MAX_CONCURRENT_NAT_JOBS" in config/secrets.json.
def _nat_load_max_concurrent() -> int:
    try:
        _s = json.loads((BASE_DIR / "config" / "secrets.json").read_text(encoding="utf-8"))
        return max(1, int(_s.get("MAX_CONCURRENT_NAT_JOBS", 1)))
    except Exception:
        return 1

MAX_CONCURRENT_NAT_JOBS: int = _nat_load_max_concurrent()
_NAT_PIPELINE_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_NAT_JOBS)
print(f"[NAT] Pipeline concurrency limit: {MAX_CONCURRENT_NAT_JOBS} slot(s)", flush=True)

# ── Per-job in-memory log buffer ──────────────────────────────────────────────
# In-memory: cleared on server restart.
# Disk mirror: DOWNLOAD_BASE/NAT_{nfn}/pipeline_log.jsonl  — appended on each
# _nat_log() call so logs survive server restarts and are "persistent until
# the user clicks Clear" (which calls /api/nat/logs/<nfn>/clear).
_nat_logs: dict = {}   # nfn → list[{"ts": ISO, "msg": str}]
_server_log: list = [] # global stream — all jobs combined, for Console tab
_SERVER_LOG_MAX = 3000


def _nat_log_file(nfn: str) -> "Path":
    return DOWNLOAD_BASE / f"NAT_{nfn}" / "pipeline_log.jsonl"


def _nat_log(nfn: str, msg: str) -> None:
    ts = datetime.utcnow().isoformat()
    entry = {"ts": ts, "msg": msg}
    buf = _nat_logs.setdefault(nfn, [])
    buf.append(entry)
    if len(buf) > 500:
        _nat_logs[nfn] = buf[-500:]
    # Also write to global console stream
    _server_log.append({"ts": ts, "nfn": nfn, "msg": msg})
    if len(_server_log) > _SERVER_LOG_MAX:
        del _server_log[:-_SERVER_LOG_MAX]
    print(f"[NAT:{nfn}] {msg}", flush=True)
    # Persist to disk so logs survive server restart
    log_file = _nat_log_file(nfn)
    if log_file.parent.exists():
        try:
            with open(log_file, "a", encoding="utf-8") as _lf:
                _lf.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# Maps each pipeline phase to the coarse current_stage value used by the NAT modal
_PHASE_TO_STAGE: dict = {
    "search": "search",
    "download": "downloading",
    "validate_downloads": "downloading",
    "extract_text": "tax",
    "extract_legal_descriptions": "tax",
    "phase1_verifications": "tax",
    "tax_lookup": "tax",
    "generate_raw_report": "ai_report_raw",
    "generate_title_notes": "ai_report_abs",
    "generate_one_report": "ai_report_abs",
    "render_pdfs": "ai_report_abs",
    "serialize_reports": "ai_report_abs",
}

_PHASE_LABELS: dict = {
    "search": "Recorder Search",
    "download": "Download PDFs",
    "validate_downloads": "Validate Downloads",
    "extract_text": "Extract Text (OCR)",
    "extract_legal_descriptions": "Extract Legal Descriptions",
    "phase1_verifications": "Phase 1 Verifications",
    "tax_lookup": "Tax Lookup",
    "generate_raw_report": "Generate RAW Report (AI)",
    "generate_title_notes": "Generate Title Notes (AI)",
    "generate_one_report": "Generate OnE Report (AI)",
    "render_pdfs": "Render PDFs",
    "serialize_reports": "Serialize Reports",
}

_NAT_STAGE_PRIORITY: dict = {
    "queued": -1, "search": 0, "downloading": 1, "tax": 2,
    "ai_report_raw": 3, "ai_report_abs": 4, "callback": 5,
}
_NAT_STAGE_TIMEOUTS: dict = {  # minutes per stage
    # "tax" covers: extract_text (OCR, ~30-60 min for large batches), legal descriptions,
    # phase1_verifications, and tax_lookup — 90 min gives OCR room to breathe.
    "search": 10, "downloading": 30, "tax": 90,
    "ai_report_raw": 45, "ai_report_abs": 45, "callback": 5,
}


# ── Persistence helpers ───────────────────────────────────────────────────────

def _nat_job_read(nfn: str) -> dict:
    path = NAT_JOBS_DIR / f"{nfn}.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return nat_jobs.get(nfn, {})


def _nat_job_write(nfn: str, job: dict) -> None:
    nat_jobs[nfn] = job
    path = NAT_JOBS_DIR / f"{nfn}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2, default=str)
    except Exception as exc:
        print(f"[NAT] Job write failed for {nfn}: {exc}", flush=True)


def _nat_checkpoint(job: dict, nfn: str, stage: str) -> None:
    job["current_stage"] = stage
    job["stage_started_at"] = datetime.utcnow().isoformat()
    _nat_job_write(nfn, job)


def _nat_event(job: dict, nfn: str, event_type: str, detail: str = "") -> None:
    job.setdefault("timeline", []).append({
        "event": event_type,
        "detail": detail[:500] if detail else "",
        "ts": datetime.utcnow().isoformat(),
    })
    _nat_job_write(nfn, job)


def _nat_should_run(stage: str, resume_from: str) -> bool:
    return _NAT_STAGE_PRIORITY.get(stage, 0) >= _NAT_STAGE_PRIORITY.get(resume_from, 0)


# ── NAT callback ──────────────────────────────────────────────────────────────

def _nat_call_back_to_nat(payload: dict) -> bool:
    callback_url = os.environ.get(
        "NAT_CALLBACK_URL", "http://localhost/nat_aws_git/api/nat/cure-result"
    )
    auth_token = os.environ.get("NAT_AUTH_TOKEN", "cure-nat-shared-secret-change-me")
    nfn = payload.get("nat_file_number", "?")
    try:
        resp = _requests.post(
            callback_url,
            json=payload,
            headers={"X-Cure-Auth": auth_token, "Content-Type": "application/json"},
            timeout=30,
        )
        print(f"[NAT] Callback {nfn} → {callback_url} → {resp.status_code}", flush=True)
        return resp.status_code in (200, 201)
    except Exception as exc:
        print(f"[NAT] Callback {nfn} FAILED: {exc}", flush=True)
        return False


# ── Async extraction thread ───────────────────────────────────────────────────

def _nat_run_extraction(nfn: str, request_data: dict, resume_from: str = "search") -> None:
    """
    Main background worker.  Runs RecorderAutomationPipeline then fires
    the 47-field callback to NAT.  Called in a daemon thread.
    """
    job = _nat_job_read(nfn)
    if not job:
        print(f"[NAT] _nat_run_extraction: job {nfn} not found on disk — aborting", flush=True)
        return

    print(f"[NAT] Starting extraction for {nfn}, resume_from={resume_from}", flush=True)

    try:
        from titlepro.automation.nat_pipeline_bridge import build_nat_workflow_config
        from titlepro.automation.nat_payload_builder import build_nat_payload

        config = build_nat_workflow_config(request_data, nfn)
        job["county_slug"] = config.county
        _nat_job_write(nfn, job)

        # ── Phase: pipeline (search → download → extract → AI reports) ──
        zero_records = False  # set True when recorder finds no instruments
        # Run pipeline for all resume_from values EXCEPT "callback"
        # (callback-only retry skips the pipeline and re-fires the result).
        # config.resume=True lets the pipeline skip phases already on disk.
        if resume_from != "callback":
            job["status"] = "running"
            _nat_event(job, nfn, "pipeline_started", f"county={config.county} owner={config.owner_name}")

            if not WORKFLOW_AVAILABLE or RecorderAutomationPipeline is None:
                raise RuntimeError("RecorderAutomationPipeline not available — import failed")

            pipeline = RecorderAutomationPipeline(config)
            job.setdefault("phases_progress", {})

            for _phase in pipeline.phase_order:
                # ── Cancellation gate — check at the start of every phase ──
                # Re-read from disk so a cancel from the UI is detected promptly.
                _live_job = _nat_job_read(nfn)
                if not _live_job or _live_job.get("status") == "cancelled":
                    _nat_log(nfn, f"⚠ Job cancelled — stopping pipeline before '{_phase}'")
                    return  # finally in _nat_run_with_queue releases the semaphore

                if not pipeline.phase_enabled(_phase):
                    job["phases_progress"][_phase] = {"status": "skipped"}
                    continue

                # Skip phases already completed from a prior run (resume logic)
                if config.resume and pipeline._can_skip_phase(_phase):
                    if _phase not in job["phases_progress"] or job["phases_progress"][_phase].get("status") != "done":
                        job["phases_progress"][_phase] = {"status": "done", "detail": "already complete"}
                        _nat_log(nfn, f"⏭ {_PHASE_LABELS.get(_phase, _phase)} — already complete")
                        _nat_job_write(nfn, job)
                    continue

                # Update NAT-modal stage before running
                _nat_checkpoint(job, nfn, _PHASE_TO_STAGE.get(_phase, _phase))
                _label = _PHASE_LABELS.get(_phase, _phase)
                _nat_log(nfn, f"▶ {_label}…")
                # For AI phases, log which engine/model will be used
                _AI_PHASE_NAMES = {"generate_raw_report", "generate_title_notes", "generate_one_report"}
                if _phase in _AI_PHASE_NAMES:
                    try:
                        from titlepro.automation.nat_pipeline_bridge import _load_secrets_model, _load_secrets_provider
                        _ai_provider = _load_secrets_provider()
                        _ai_model = _load_secrets_model()
                        _nat_log(nfn, f"   🤖 Engine: {_ai_provider} | Model: {_ai_model}")
                    except Exception:
                        pass
                _phase_t0 = __import__("time").monotonic()
                job["phases_progress"][_phase] = {
                    "status": "running",
                    "started_at": datetime.utcnow().isoformat(),
                }
                _nat_job_write(nfn, job)

                # For long-running AI phases, emit a heartbeat every 2 min so
                # the live-log terminal shows the job is alive (not frozen).
                _AI_PHASES = {"generate_raw_report", "generate_title_notes", "generate_one_report"}
                _hb_stop = threading.Event()
                if _phase in _AI_PHASES:
                    def _heartbeat(_nfn=nfn, _lbl=_label, _stop=_hb_stop):
                        mins = 0
                        while not _stop.wait(120):
                            mins += 2
                            _nat_log(_nfn, f"⏳ {_lbl} — still generating… ({mins} min elapsed)")
                    threading.Thread(target=_heartbeat, daemon=True).start()

                try:
                    pipeline.state_store.mark_started(_phase)
                    _phase_result = getattr(pipeline, _phase)()
                    pipeline.state_store.mark_completed(_phase, _phase_result)
                    _hb_stop.set()  # stop heartbeat

                    job["phases_progress"][_phase]["status"] = "done"
                    job["phases_progress"][_phase]["completed_at"] = datetime.utcnow().isoformat()

                    # Capture useful counts per phase (with elapsed time)
                    _elapsed = __import__("time").monotonic() - _phase_t0
                    _t = f" ({_elapsed:.1f}s)"
                    if _phase == "search":
                        _doc_count = (_phase_result or {}).get("total_unique_documents", "?")
                        job["phases_progress"][_phase]["detail"] = f"Found {_doc_count} documents"
                        _nat_log(nfn, f"✓ Search complete — {_doc_count} documents found{_t}")
                    elif _phase == "download":
                        try:
                            _dm = json.loads(pipeline.download_manifest_path().read_text(encoding="utf-8"))
                            _res = _dm.get("results", [])
                            _ok = sum(1 for r in _res if r.get("status") in ("success", "skipped_existing"))
                            job["phases_progress"][_phase]["detail"] = f"{_ok} / {len(_res)} PDFs"
                            _nat_log(nfn, f"✓ Download complete — {_ok}/{len(_res)} PDFs{_t}")
                        except Exception:
                            _nat_log(nfn, f"✓ {_label} complete{_t}")
                    elif _phase == "extract_text":
                        _ok_ext = (_phase_result or {}).get("extracted_documents", "?")
                        job["phases_progress"][_phase]["detail"] = f"{_ok_ext} docs extracted"
                        _nat_log(nfn, f"✓ Text extraction complete — {_ok_ext} docs{_t}")
                    elif _phase == "tax_lookup":
                        _tax_status = (_phase_result or {}).get("status", "?")
                        _nat_log(nfn, f"✓ Tax lookup complete — status: {_tax_status}{_t}")
                    elif _phase == "generate_raw_report":
                        _nat_log(nfn, f"✓ RAW report generated{_t}")
                    elif _phase == "generate_title_notes":
                        _nat_log(nfn, f"✓ Title Notes generated{_t}")
                    elif _phase == "generate_one_report":
                        _one_docx = (_phase_result or {}).get("one_docx")
                        _docx_note = " (DOCX)" if _one_docx else ""
                        _nat_log(nfn, f"✓ OnE Report generated{_docx_note}{_t}")
                    elif _phase == "render_pdfs":
                        _pdf_list = [v for k, v in (_phase_result or {}).items() if k.endswith("_pdf") and v]
                        _nat_log(nfn, f"✓ PDFs rendered — {len(_pdf_list)} file(s){_t}")
                    elif _phase == "serialize_reports":
                        _nat_log(nfn, f"✓ Reports serialized{_t}")
                    else:
                        _nat_log(nfn, f"✓ {_label} complete{_t}")

                    _nat_job_write(nfn, job)

                except Exception as _phase_exc:
                    _hb_stop.set()  # stop heartbeat on failure too
                    _msg = str(_phase_exc)
                    if _phase == "search" and "zero documents" in _msg.lower():
                        zero_records = True
                        job["phases_progress"][_phase]["status"] = "no_records"
                        if "NEEDS_COOKIE_MINT" in _msg:
                            job["phases_progress"][_phase]["detail"] = "Akamai cookies missing — needs manual mint"
                            _nat_log(nfn, "⚠ Search returned 0 instruments — Akamai cookie jar missing for this county")
                            _nat_log(nfn, "   ACTION: Run tools/diagnostics/mint_lee_cookies.py from your workstation (residential IP), then click Retry")
                        else:
                            job["phases_progress"][_phase]["detail"] = "No instruments found"
                            _nat_log(nfn, "⚠ Search returned zero instruments — continuing with empty result")
                        _nat_event(job, nfn, "pipeline_no_records",
                                   "Recorder returned zero instruments — sending empty payload to NAT")
                        _nat_job_write(nfn, job)
                        break  # skip remaining phases, proceed to callback
                    else:
                        _elapsed_f = __import__("time").monotonic() - _phase_t0
                        pipeline.state_store.mark_failed(_phase, _msg)
                        job["phases_progress"][_phase]["status"] = "failed"
                        job["phases_progress"][_phase]["detail"] = _msg[:500]
                        _nat_log(nfn, f"✗ {_label} FAILED after {_elapsed_f:.1f}s")
                        _nat_log(nfn, f"   ERROR: {_msg[:400]}")
                        _nat_job_write(nfn, job)
                        raise  # propagate to outer except block

            _nat_event(job, nfn, "pipeline_completed")

        # ── Phase: callback ──
        if _nat_should_run("callback", resume_from):
            _nat_checkpoint(job, nfn, "callback")
            output_dir = str(DOWNLOAD_BASE / f"NAT_{nfn}")
            _nat_event(job, nfn, "callback_building_payload")
            cure_data = build_nat_payload(output_dir, request_data)
            if zero_records:
                cure_data["ExamNotes"] = (
                    cure_data.get("ExamNotes") or
                    "Recorder search completed — no instruments found under the provided name and county."
                )

            # Collect generated PDF report files for NAT attachment.
            # Includes the three canonical CURE reports (no-date versions).
            _report_files: list = []
            _out_path = Path(output_dir)
            _exact_pdfs = ["RAW_TWO_OWNER_SEARCH_EXAM.pdf", "Title_Examination_Notes.pdf"]
            for _pdf_name in _exact_pdfs:
                _p = _out_path / _pdf_name
                if _p.exists():
                    _report_files.append(str(_p.resolve()))
            # OnE_Report has an owner-specific filename — pick the first non-dated copy
            for _f in sorted(_out_path.glob("OnE_Report_*.pdf")):
                if "_NAT_" not in _f.name:
                    _report_files.append(str(_f.resolve()))
                    break

            # NAT expects: { nat_file_number, status:"Success"|"Failure",
            #                status_reason, data:{...}, report_files:[...] }
            nat_payload = {
                "nat_file_number": nfn,
                "status": "Success",
                "status_reason": None,
                "data": cure_data,
                "report_files": _report_files,
            }
            ok = _nat_call_back_to_nat(nat_payload)
            job["status"] = "completed" if ok else "callback_failed"
            job["completed_at"] = datetime.utcnow().isoformat()
            # Store cure_data in job["result"]["data"] so the NAT portal's
            # job-status poll can detect it and show the "Save to Exam Receipt" button.
            job["result"] = {"data": cure_data}
            _nat_event(job, nfn, "callback_sent" if ok else "callback_failed")
            _nat_job_write(nfn, job)

            # ── Phase: auto-verify (post-callback, non-blocking) ──────────
            # Runs Tony's 6-directive + Q1-Q4 scorecard after callback fires.
            # Saves verify_report.md + verify_report.json in the job folder.
            if ok and not zero_records:
                _nat_generate_verify_report(nfn, output_dir, job)

    except Exception as exc:
        trace = _tb.format_exc()
        print(f"[NAT] Job {nfn} FAILED: {exc}\n{trace}", flush=True)
        job["status"] = "failed"
        job["error"] = str(exc)[:1000]
        job["error_trace"] = trace[:3000]
        _nat_event(job, nfn, "pipeline_failed", str(exc)[:500])
        _nat_job_write(nfn, job)
        _nat_call_back_to_nat({
            "nat_file_number": nfn,
            "status": "Failure",
            "status_reason": str(exc)[:500],
            "data": {},
            "report_files": [],
        })


# ── Auto-verify phase (runs after callback succeeds) ─────────────────────────

def _nat_generate_verify_report(nfn: str, output_dir: str, job: dict) -> None:
    """
    Post-callback quality-assurance phase.

    Scores the generated RAW / Title / OnE reports against Tony's Six Directives
    and the four Broward-Standard Quality Gates (Q1-Q4).  Saves the result as
    verify_report.md + verify_report.json in the NAT job folder.

    Called inline after a successful callback (already in a background thread).
    Any exception is caught and logged — never re-raises so it cannot kill the job.
    """
    _nat_log(nfn, "▶ Auto-verify: scoring reports against Tony's directives…")
    job.setdefault("phases_progress", {})["verify_report"] = {
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
    }
    _nat_job_write(nfn, job)

    try:
        _t0 = time.monotonic()
        out = Path(output_dir)

        # ── 1. Load report markdown files ──────────────────────────────────
        def _read_text(path_or_glob):
            p = out / path_or_glob
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")
            matches = sorted(out.glob(path_or_glob))
            if matches:
                return matches[0].read_text(encoding="utf-8", errors="replace")
            return None

        raw_md   = _read_text("RAW_TWO_OWNER_SEARCH_EXAM.md")
        title_md = _read_text("Title_Examination_Notes.md")
        one_mds  = sorted(out.glob("OnE_Report_*.md"))
        one_md   = one_mds[0].read_text(encoding="utf-8", errors="replace") if one_mds else None

        if not raw_md and not title_md and not one_md:
            _nat_log(nfn, "⚠ Auto-verify: no report .md files found — skipping")
            job["phases_progress"]["verify_report"]["status"] = "skipped"
            job["phases_progress"]["verify_report"]["detail"] = "No report .md files found"
            _nat_job_write(nfn, job)
            return

        # ── 2. Load JSON artifacts ──────────────────────────────────────────
        def _read_json(fname):
            p = out / fname
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    return {}
            return {}

        search_results  = _read_json("search_results.json")
        docs_found      = _read_json("documents_found.json")
        workflow_cfg    = _read_json("workflow_config.json")
        phase1_verifs   = _read_json("phase1_verifications.json")
        pa_anchor       = _read_json("phase1_property_appraiser.json")

        subject = workflow_cfg.get("property_address") or workflow_cfg.get("subject_address") or "Unknown"
        owner   = workflow_cfg.get("owner_name") or "Unknown"
        county  = workflow_cfg.get("county") or "Unknown"

        # Per-search counts for D3 / state-contamination check
        sr_counts = [r.get("result_count", 0) for r in search_results.get("runs", [])]
        search_names = [
            req.get("name", "") for req in workflow_cfg.get("search_requests", [])
        ]

        # Doc numbers in documents_found (may be a list or a dict)
        if isinstance(docs_found, list):
            doc_nums = [d.get("document_number", "") for d in docs_found]
        else:
            doc_nums = []

        # ── 3. Trim report content to fit prompt budget ─────────────────────
        def _trim(text, max_chars=7000):
            if not text:
                return "(not found)"
            return text[:max_chars] + ("\n\n[... truncated ...]" if len(text) > max_chars else "")

        pa_status = pa_anchor.get("status", "MISSING") if pa_anchor else "MISSING"

        # ── 4. Build the verify prompt ──────────────────────────────────────
        prompt = f"""You are a TitlePro CURE report quality-assurance agent.
Score the CURE reports below against Tony Roveda's Six Directives and the Broward-Standard Quality Gates (Q1-Q4).

## CASE INFO
Owner: {owner}
Subject property: {subject}
County: {county}
Names to search: {search_names}
Per-search result counts from search_results.json: {sr_counts}
Documents found count: {len(doc_nums)}
Property Appraiser anchor status: {pa_status}

## TONY'S SIX DIRECTIVES — SCORE EACH
D1 — No Selenium/Playwright in search phase (HTTP adapter only)
  PASS if no selenium/playwright references in logs; WARN if selenium used but HTTP adapter exists; FAIL if only selenium with no HTTP adapter.

D2 — Deed-first methodology (vesting deed is a WD or Deed type)
  PASS if vesting deed cited is type Warranty Deed / WD / Deed; WARN if all-doctype search used but verifier ran; FAIL if non-deed used as vesting.

D3 — All provided names searched with results
  Names required: {search_names}
  Counts: {sr_counts}
  FAIL if counts pattern is [N, 0, 0, ...] (state contamination — only first search returned results).
  FAIL if fewer searches ran than names provided.
  PASS if all names returned results or any zero-result name is explicitly noted as absence-finding.

D4 — NLP subject-address verification ran on every deed candidate
  Check phase1_verifications subject_address_verification block.
  FAIL if no verification data at all; FAIL if a NO_MATCH deed was used as vesting; PASS if all deed candidates verified MATCH.

D5 — Every indexed document examined; no silent drops
  Documents found: {len(doc_nums)} (from documents_found.json)
  Check that every doc# appears in the RAW report (examined or documented as excluded).
  FAIL if any doc silently missing with no exclusion note.

D6 — Released mortgages excluded from Open Mortgages section
  Check mortgage_classifications in phase1_verifications.
  FAIL if any mortgage classified 'released' appears in the Open Mortgages section.
  PASS if all released mortgages are in a Released/Satisfied section with satisfaction doc# cited.

## QUALITY GATES — SCORE EACH
Q1 — No placeholder language (manual fetch, to be confirmed, not available, outside search window, pending direct pull, not verified)
  Grep the Title/RAW report text for these phrases. Any hit without a statutory citation = FAIL.

Q2 — Tax data present (real annual tax dollar amount in the report)
  FAIL if report contains "TAX STATUS NOT VERIFIED", "tax bill amount not retrieved", or has no dollar amount in the tax section.

Q3 — Property Appraiser anchor present
  PA status from phase1_property_appraiser.json: {pa_status}
  FAIL if status is MISSING or PA_NO_RUNNER; WARN if PA_NO_RESULTS after retry; PASS if PA_SUCCESS.

Q4 — Concrete grantor/grantee in every chain-of-title row
  FAIL if any chain row shows "(Unknown)", "(prior owner)", "unknown grantor", or similar placeholder.

## RAW REPORT (RAW_TWO_OWNER_SEARCH_EXAM.md)
{_trim(raw_md)}

## TITLE EXAMINATION NOTES (Title_Examination_Notes.md)
{_trim(title_md)}

## OnE REPORT
{_trim(one_md)}

## PHASE 1 VERIFICATIONS (phase1_verifications.json)
{json.dumps(phase1_verifs, indent=2)[:2500]}

## OUTPUT FORMAT (produce ONLY this markdown, nothing else)

# CURE Auto-Verify Report — {owner} / {county}

**Verdict:** SHIPPABLE | SHIPPABLE WITH FIXES | BLOCKED

## Directives Scorecard

| # | Check | Status | Evidence |
|---|---|---|---|
| D1 | No Selenium/Playwright | 🟢 PASS / 🟡 WARN / 🔴 FAIL | one-line evidence |
| D2 | Deed-first methodology | ... | ... |
| D3 | All names searched | ... | ... |
| D4 | NLP address verification | ... | ... |
| D5 | No silent drops | ... | ... |
| D6 | Released mortgages excluded | ... | ... |

## Quality Gates

| Gate | Check | Status | Evidence |
|---|---|---|---|
| Q1 | No placeholder language | ... | ... |
| Q2 | Tax data present | ... | ... |
| Q3 | PA anchor present | ... | ... |
| Q4 | Concrete grantor/grantee | ... | ... |

## Fix List
- (one bullet per FAIL/WARN with exact file and remediation)

## Summary
(2-3 sentences, direct and factual)
"""

        # ── 5. Call the configured AI engine ───────────────────────────────
        from titlepro.automation.agent_runners import build_agent_runner
        from titlepro.automation.nat_pipeline_bridge import _load_secrets_provider, _load_secrets_model

        provider = _load_secrets_provider()
        model    = _load_secrets_model()
        _nat_log(nfn, f"   🤖 Verify engine: {provider} | {model}")
        runner = build_agent_runner(provider, model=model, timeout_seconds=180)

        system_prompt = (
            "You are a TitlePro CURE report quality-assurance agent. "
            "Score the provided reports objectively against the listed checks. "
            "Output ONLY the scorecard markdown — no preamble, no extra commentary."
        )

        _run_result = runner.run(system_prompt=system_prompt, user_prompt=prompt, cwd=out)
        verify_md = _run_result.output if _run_result.success else ""
        if not verify_md:
            raise RuntimeError(
                f"AI runner returned empty output: {_run_result.error or 'unknown error'}"
            )

        # ── 6. Derive verdict from scorecard ────────────────────────────────
        has_fail = "🔴 FAIL" in verify_md or ("FAIL" in verify_md and "BLOCKED" in verify_md.upper())
        has_warn = "🟡 WARN" in verify_md
        if "BLOCKED" in verify_md.upper():
            verdict = "BLOCKED"
        elif has_fail:
            verdict = "BLOCKED"
        elif has_warn:
            verdict = "SHIPPABLE WITH FIXES"
        else:
            verdict = "SHIPPABLE"

        # ── 7. Save verify_report.md + verify_report.json ──────────────────
        verify_md_path   = out / "verify_report.md"
        verify_json_path = out / "verify_report.json"

        verify_md_path.write_text(verify_md, encoding="utf-8")
        verify_json_path.write_text(json.dumps({
            "verdict": verdict,
            "has_fail": has_fail,
            "has_warn": has_warn,
            "generated_at": datetime.utcnow().isoformat(),
            "report_md_path": str(verify_md_path),
            "owner": owner,
            "county": county,
        }, indent=2), encoding="utf-8")

        _elapsed = time.monotonic() - _t0
        _nat_log(nfn, f"✓ Auto-verify complete — verdict: {verdict} ({_elapsed:.1f}s)")
        _nat_log(nfn, f"   📄 verify_report.md saved in job folder")

        job["phases_progress"]["verify_report"] = {
            "status": "done",
            "completed_at": datetime.utcnow().isoformat(),
            "detail": verdict,
        }
        job["verify_verdict"] = verdict
        _nat_job_write(nfn, job)

    except Exception as _verify_exc:
        _nat_log(nfn, f"⚠ Auto-verify failed (non-blocking): {str(_verify_exc)[:300]}")
        job["phases_progress"].setdefault("verify_report", {})["status"] = "failed"
        job["phases_progress"]["verify_report"]["detail"] = str(_verify_exc)[:300]
        _nat_job_write(nfn, job)


# ── Queue helpers ─────────────────────────────────────────────────────────────

def _nat_queue_position(nfn: str) -> int:
    """
    Return how many 'pending' jobs are ahead of this one in the queue.
    0 = this job is next; 3 = three jobs ahead of it.
    """
    this_job = _nat_job_read(nfn)
    if not this_job:
        return 0
    this_created = this_job.get("created_at", "")
    pos = 0
    for jf in NAT_JOBS_DIR.glob("*.json"):
        if jf.stem == nfn:
            continue
        try:
            other = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if other.get("status") == "pending" and other.get("created_at", "") < this_created:
            pos += 1
    return pos


def _nat_run_with_queue(nfn: str, data: dict, resume_from: str = "search") -> None:
    """
    Queue wrapper around _nat_run_extraction.

    Blocks on _NAT_PIPELINE_SEMAPHORE until a pipeline slot is free,
    then runs the full extraction and releases the slot on completion.

    With MAX_CONCURRENT_NAT_JOBS=1 this gives a strict serial queue:
    Job 1 runs → Job 2 waits → Job 3 waits → … → each starts only when
    the previous one finishes (success OR failure).
    """
    job = _nat_job_read(nfn)
    if not job:
        return

    pos = _nat_queue_position(nfn)
    if pos > 0:
        _nat_log(nfn, f"⏳ In queue — position #{pos + 1} — waiting for the current job to finish…")
    else:
        _nat_log(nfn, "⏳ Waiting for pipeline slot…")

    # Block here until a slot is free
    _NAT_PIPELINE_SEMAPHORE.acquire()
    try:
        # Re-read after potentially long wait — job may have been cancelled
        job = _nat_job_read(nfn)
        if not job or job.get("status") == "cancelled":
            _nat_log(nfn, "⚠ Job cancelled while waiting in queue — skipping")
            return

        _nat_log(nfn, f"✅ Pipeline slot acquired — starting extraction now…")
        _nat_run_extraction(nfn, data, resume_from)
    finally:
        _NAT_PIPELINE_SEMAPHORE.release()
        # Log how many jobs are still waiting (safe read)
        _pending = 0
        for _jf in NAT_JOBS_DIR.glob("*.json"):
            if _jf.stem == nfn:
                continue
            try:
                if json.loads(_jf.read_text(encoding="utf-8")).get("status") == "pending":
                    _pending += 1
            except Exception:
                pass
        print(f"[NAT] Job {nfn} released pipeline slot — {_pending} job(s) still pending", flush=True)


# ── Fault tolerance: orphan recovery (runs at startup) ───────────────────────

def _nat_recover_orphaned_jobs() -> None:
    """Mark stale running jobs as failed so NAT can show Retry/Restart."""
    import time as _time
    now = _time.time()
    recovered = 0
    for jf in NAT_JOBS_DIR.glob("*.json"):
        try:
            with open(jf, encoding="utf-8") as f:
                job = json.load(f)
        except Exception:
            continue
        if job.get("status") not in ("queued", "running", "downloading", "pending"):
            continue
        started = job.get("created_at") or job.get("stage_started_at", "")
        try:
            import datetime as _dt
            age_s = (
                _dt.datetime.utcnow()
                - _dt.datetime.fromisoformat(started.replace("Z", ""))
            ).total_seconds()
        except Exception:
            age_s = 9999
        if age_s < 600:  # under 10 min — might still be alive
            continue
        nfn = jf.stem
        job["status"] = "failed"
        job["error"] = "Server restarted while job was running (orphan recovery)"
        job.setdefault("timeline", []).append({
            "event": "job_orphaned",
            "detail": f"age_seconds={int(age_s)}",
            "ts": datetime.utcnow().isoformat(),
        })
        _nat_job_write(nfn, job)
        _nat_call_back_to_nat({
            "nat_file_number": nfn,
            "status": "Failure",
            "status_reason": "Server restarted while job was running",
            "data": {},
            "report_files": [],
        })
        recovered += 1
    if recovered:
        print(f"[NAT] Orphan recovery: marked {recovered} stale job(s) as failed", flush=True)


# ── Fault tolerance: watchdog daemon thread ───────────────────────────────────

def _nat_watchdog_loop() -> None:
    """Daemon thread — checks stage timeouts every 60 seconds."""
    import time as _time
    import datetime as _dt
    while True:
        _time.sleep(60)
        for nfn, job in list(nat_jobs.items()):
            if job.get("status") not in ("running", "queued", "downloading"):
                continue
            stage = job.get("current_stage", "search")
            started_str = job.get("stage_started_at", "")
            timeout_m = _NAT_STAGE_TIMEOUTS.get(stage, 30)
            try:
                started = _dt.datetime.fromisoformat(started_str.replace("Z", ""))
                elapsed_m = (
                    _dt.datetime.utcnow() - started
                ).total_seconds() / 60
            except Exception:
                continue
            if elapsed_m > timeout_m:
                print(
                    f"[NAT] Watchdog: job {nfn} timed out at stage={stage} "
                    f"({elapsed_m:.1f}m > {timeout_m}m limit)",
                    flush=True,
                )
                job["status"] = "failed"
                job["error"] = f"Stage '{stage}' exceeded {timeout_m}-minute timeout"
                _nat_event(job, nfn, "watchdog_timeout", f"stage={stage} elapsed={elapsed_m:.1f}m")
                _nat_job_write(nfn, job)
                _nat_call_back_to_nat({
                    "nat_file_number": nfn,
                    "status": "Failure",
                    "status_reason": job["error"],
                    "data": {},
                    "report_files": [],
                })


# ── Endpoint: submit order ────────────────────────────────────────────────────

@app.route('/api/nat/start-extraction', methods=['POST'])
def nat_start_extraction():
    """
    Primary NAT → CURE entry point.
    NAT POSTs order data; CURE ACKs immediately and runs pipeline async.

    Expected JSON body:
        nat_file_number  str  required
        owner_name       str  required
        county           str  required
        state            str  default "FL"
        address          str  optional
        apn              str  optional
        spouse_name      str  optional
    """
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    if not data.get("owner_name"):
        return jsonify({"success": False, "error": "owner_name required"}), 400
    if not data.get("county"):
        return jsonify({"success": False, "error": "county required"}), 400

    # Reject duplicate if already active (pending, queued, or running)
    existing = _nat_job_read(nfn)
    if existing and existing.get("status") in ("pending", "queued", "running"):
        return jsonify({
            "success": False,
            "error": f"Job {nfn} already in progress (status: {existing.get('status')})",
            "status": existing.get("status"),
        }), 409

    # Create job record — status "pending" means waiting in queue for a slot
    job = {
        "nat_file_number": nfn,
        "status": "pending",
        "current_stage": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "request_data": data,
        "timeline": [{"event": "submitted", "ts": datetime.utcnow().isoformat(), "detail": ""}],
        "error": None,
        "completed_at": None,
        "county_slug": None,
    }
    _nat_job_write(nfn, job)

    # Create output folder immediately
    output_dir = DOWNLOAD_BASE / f"NAT_{nfn}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Count how many jobs are already pending/running so we can tell the caller queue position
    _ahead = _nat_queue_position(nfn)
    print(f"[NAT] Job {nfn} added to queue (position #{_ahead + 1}) — output: {output_dir}", flush=True)

    # Fire background thread — it will block on _NAT_PIPELINE_SEMAPHORE until a slot is free
    t = threading.Thread(
        target=_nat_run_with_queue,
        args=(nfn, data, "search"),
        daemon=True,
        name=f"nat-{nfn}",
    )
    t.start()

    return jsonify({
        "success": True,
        "status": "pending",
        "queue_position": _ahead + 1,
        "nat_file_number": nfn,
        "message": f"Job queued at position #{_ahead + 1} — will start automatically when current job finishes" if _ahead > 0 else "Job starting now (no queue)",
    }), 202


# ── Endpoint: poll job status ─────────────────────────────────────────────────

@app.route('/api/nat/job-status/<nfn>', methods=['GET'])
def nat_job_status(nfn):
    """Return full job JSON for a given NAT file number.
    When the job is pending in the queue, also returns queue_position (1=next up).
    """
    job = _nat_job_read(nfn)
    if not job:
        return jsonify({"success": False, "error": f"Job {nfn} not found"}), 404
    resp = {"success": True, "job": job}
    if job.get("status") == "pending":
        resp["queue_position"] = _nat_queue_position(nfn) + 1
    return jsonify(resp)


# ── Endpoint: per-job log stream ─────────────────────────────────────────────

@app.route('/api/nat/logs/<nfn>', methods=['GET'])
def nat_job_logs(nfn):
    """Return buffered per-job log lines.
    Persistent: if in-memory buffer is empty, loads from disk (pipeline_log.jsonl).
    Query param: offset=N — return only lines[N:] for incremental polling.
    """
    offset = request.args.get('offset', 0, type=int)
    logs = _nat_logs.get(nfn, [])
    if not logs:
        # Reload from disk after server restart
        log_file = _nat_log_file(nfn)
        if log_file.exists():
            try:
                lines = log_file.read_text(encoding="utf-8").splitlines()
                disk_logs = [json.loads(ln) for ln in lines if ln.strip()]
                _nat_logs[nfn] = disk_logs
                logs = disk_logs
            except Exception:
                pass
    return jsonify({"success": True, "logs": logs[offset:], "total": len(logs)})


@app.route('/api/nat/logs/<nfn>/clear', methods=['POST'])
def nat_clear_logs(nfn):
    """Clear the persistent log for a job (both memory and disk)."""
    _nat_logs.pop(nfn, None)
    log_file = _nat_log_file(nfn)
    try:
        if log_file.exists():
            log_file.unlink()
    except Exception:
        pass
    return jsonify({"success": True, "message": f"Logs cleared for job {nfn}"})


# ── Endpoint: global console log stream (all jobs combined) ──────────────────

@app.route('/api/nat/console-log', methods=['GET'])
def nat_console_log():
    """Return the global server log stream across all jobs.
    Query param: offset=N — return only entries[N:] for incremental polling.
    """
    offset = request.args.get('offset', 0, type=int)
    return jsonify({"success": True, "logs": _server_log[offset:], "total": len(_server_log)})


# ── Endpoint: retry (stage-aware) ─────────────────────────────────────────────

@app.route('/api/nat/retry/<nfn>', methods=['POST'])
def nat_retry(nfn):
    """
    Stage-aware resume. Skips already-completed stages.
    Optional body: {"force_stage": "search"} to restart from scratch.
    """
    job = _nat_job_read(nfn)
    if not job:
        return jsonify({"success": False, "error": f"Job {nfn} not found"}), 404

    if job.get("status") in ("queued", "running"):
        return jsonify({
            "success": False,
            "error": f"Job {nfn} is already {job.get('status')} — stop it first",
        }), 409

    body = request.get_json(force=True) or {}
    force_stage = body.get("force_stage", "")
    resume_from = force_stage if force_stage else (job.get("current_stage") or "search")

    # If callback already succeeded, just re-fire the callback
    if resume_from == "callback" and job.get("status") == "completed":
        # Rebuild payload from existing files and re-POST
        request_data = job.get("request_data", {})
        output_dir = str(DOWNLOAD_BASE / f"NAT_{nfn}")
        try:
            from titlepro.automation.nat_payload_builder import build_nat_payload
            cure_data = build_nat_payload(output_dir, request_data)
            # Collect generated PDF report files (same logic as _nat_run_extraction)
            _retry_report_files: list = []
            _retry_out = Path(output_dir)
            for _pdf_name in ["RAW_TWO_OWNER_SEARCH_EXAM.pdf", "Title_Examination_Notes.pdf"]:
                _p = _retry_out / _pdf_name
                if _p.exists():
                    _retry_report_files.append(str(_p.resolve()))
            for _f in sorted(_retry_out.glob("OnE_Report_*.pdf")):
                if "_NAT_" not in _f.name:
                    _retry_report_files.append(str(_f.resolve()))
                    break
            nat_payload = {
                "nat_file_number": nfn,
                "status": "Success",
                "status_reason": None,
                "data": cure_data,
                "report_files": _retry_report_files,
            }
            ok = _nat_call_back_to_nat(nat_payload)
            return jsonify({"success": ok, "action": "callback_resent"})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    job["status"] = "pending"
    job["current_stage"] = "pending"
    job["error"] = None
    _nat_event(job, nfn, "retry_queued", f"resume_from={resume_from}")
    _nat_job_write(nfn, job)

    request_data = job.get("request_data", {})
    _ahead = _nat_queue_position(nfn)
    t = threading.Thread(
        target=_nat_run_with_queue,
        args=(nfn, request_data, resume_from),
        daemon=True,
        name=f"nat-retry-{nfn}",
    )
    t.start()
    return jsonify({
        "success": True,
        "status": "pending",
        "queue_position": _ahead + 1,
        "resume_from": resume_from,
        "message": f"Retry queued at position #{_ahead + 1}" if _ahead > 0 else "Retry starting now",
    })


# ── Endpoint: cancel job ──────────────────────────────────────────────────────

@app.route('/api/admin/cancel-job', methods=['POST'])
def nat_cancel_job():
    """Mark a job as cancelled (NAT Stop button)."""
    body = request.get_json(force=True) or {}
    nfn = str(body.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn)
    if not job:
        return jsonify({"success": False, "error": f"Job {nfn} not found"}), 404
    job["status"] = "cancelled"
    _nat_event(job, nfn, "cancelled", "operator stop")
    _nat_job_write(nfn, job)
    return jsonify({"success": True, "status": "cancelled"})


@app.route('/api/admin/reset-queue', methods=['POST'])
def nat_reset_queue():
    """
    Emergency endpoint — releases ALL pipeline semaphore slots and marks every
    pending/running/queued job as 'failed'.

    Use when a stuck job holds the semaphore and new jobs are blocked in 'pending'.
    After calling this, submit new jobs normally — the queue is clean.

    POST /api/admin/reset-queue
    Body: {} (no params needed)
    """
    released = 0
    failed_jobs = []

    # Mark all active jobs as failed so the queue is visually clean
    for jf in NAT_JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        nfn_stuck = jf.stem
        if job.get("status") in ("pending", "queued", "running", "downloading"):
            job["status"] = "failed"
            job["error"] = "Queue forcibly reset by admin (reset-queue endpoint)"
            _nat_event(job, nfn_stuck, "queue_reset", "admin forced reset")
            _nat_job_write(nfn_stuck, job)
            failed_jobs.append(nfn_stuck)

    # Drain the semaphore completely then restore it to MAX_CONCURRENT_NAT_JOBS slots
    # so new jobs can run immediately.
    drained = 0
    while True:
        acquired = _NAT_PIPELINE_SEMAPHORE.acquire(blocking=False)
        if not acquired:
            break
        drained += 1
    # Release MAX_CONCURRENT slots (restore full capacity)
    for _ in range(MAX_CONCURRENT_NAT_JOBS):
        _NAT_PIPELINE_SEMAPHORE.release()
        released += 1

    msg = (
        f"Queue reset complete. "
        f"Marked {len(failed_jobs)} job(s) as failed: {failed_jobs}. "
        f"Semaphore restored to {released} slot(s). "
        f"Submit new jobs now."
    )
    print(f"[NAT] ADMIN reset-queue: {msg}", flush=True)
    return jsonify({
        "success": True,
        "failed_jobs": failed_jobs,
        "semaphore_slots_restored": released,
        "message": msg,
    })


# ── Manual workbench endpoints ────────────────────────────────────────────────

@app.route('/api/nat/manual/initialize', methods=['POST'])
def nat_manual_initialize():
    """Step 0 — create job record (no pipeline yet)."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = {
        "nat_file_number": nfn,
        "status": "initialized",
        "current_stage": "initialized",
        "created_at": datetime.utcnow().isoformat(),
        "request_data": data,
        "timeline": [{"event": "manual_initialized", "ts": datetime.utcnow().isoformat(), "detail": ""}],
        "error": None,
        "completed_at": None,
        "county_slug": None,
    }
    _nat_job_write(nfn, job)
    output_dir = DOWNLOAD_BASE / f"NAT_{nfn}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return jsonify({"success": True, "nat_file_number": nfn, "status": "initialized"})


@app.route('/api/nat/manual/search', methods=['POST'])
def nat_manual_search():
    """Step 1 — run recorder search only (no download, no AI)."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn) or {
        "nat_file_number": nfn, "request_data": data, "timeline": [],
    }
    job["status"] = "running"
    _nat_checkpoint(job, nfn, "search")
    _nat_event(job, nfn, "manual_search_started")

    def _run():
        try:
            from titlepro.automation.nat_pipeline_bridge import build_nat_workflow_config
            config = build_nat_workflow_config(data, nfn)
            if RecorderAutomationPipeline is None:
                raise RuntimeError("RecorderAutomationPipeline not available")
            # Run only search phases (phase 1–2)
            config.generate_title_notes = False
            config.generate_raw_pdf = False
            config.generate_title_pdf = False
            config.fetch_tax = False
            pipeline = RecorderAutomationPipeline(config)
            pipeline.run()
            job["status"] = "search_complete"
            _nat_event(job, nfn, "manual_search_completed")
            _nat_job_write(nfn, job)
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            _nat_event(job, nfn, "manual_search_failed", str(exc))
            _nat_job_write(nfn, job)

    threading.Thread(target=_run, daemon=True, name=f"nat-msearch-{nfn}").start()
    return jsonify({"success": True, "status": "running", "message": "Search started in background"}), 202


@app.route('/api/nat/manual/download', methods=['POST'])
def nat_manual_download():
    """Step 2 — download PDFs only."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn) or {"nat_file_number": nfn, "request_data": data, "timeline": []}
    job["status"] = "downloading"
    _nat_checkpoint(job, nfn, "downloading")
    _nat_event(job, nfn, "manual_download_started")
    _nat_job_write(nfn, job)
    return jsonify({"success": True, "status": "downloading", "message": "Download phase — run full pipeline to execute"})


@app.route('/api/nat/manual/tax', methods=['POST'])
def nat_manual_tax():
    """Step 3 — fetch tax data only."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn) or {"nat_file_number": nfn, "request_data": data, "timeline": []}
    _nat_checkpoint(job, nfn, "tax")
    _nat_event(job, nfn, "manual_tax_started")
    _nat_job_write(nfn, job)
    return jsonify({"success": True, "status": "tax", "message": "Tax phase — run full pipeline to execute"})


@app.route('/api/nat/manual/ai-reports', methods=['POST'])
def nat_manual_ai_reports():
    """Step 4 — generate AI reports only (assumes PDFs already downloaded)."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn) or {"nat_file_number": nfn, "request_data": data, "timeline": []}
    _nat_checkpoint(job, nfn, "ai_report_raw")
    _nat_event(job, nfn, "manual_ai_started")

    def _run():
        try:
            from titlepro.automation.nat_pipeline_bridge import build_nat_workflow_config
            config = build_nat_workflow_config(data, nfn)
            if RecorderAutomationPipeline is None:
                raise RuntimeError("RecorderAutomationPipeline not available")
            config.resume = True
            pipeline = RecorderAutomationPipeline(config)
            pipeline.run()
            job["status"] = "ai_complete"
            _nat_event(job, nfn, "manual_ai_completed")
            _nat_job_write(nfn, job)
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            _nat_event(job, nfn, "manual_ai_failed", str(exc))
            _nat_job_write(nfn, job)

    threading.Thread(target=_run, daemon=True, name=f"nat-mai-{nfn}").start()
    return jsonify({"success": True, "status": "running", "message": "AI report generation started"}), 202


@app.route('/api/nat/manual/send-callback', methods=['POST'])
def nat_manual_send_callback():
    """Step 5 — build 47-field payload from existing files and POST to NAT."""
    data = request.get_json(force=True) or {}
    nfn = str(data.get("nat_file_number", "")).strip()
    if not nfn:
        return jsonify({"success": False, "error": "nat_file_number required"}), 400
    job = _nat_job_read(nfn) or {}
    request_data = job.get("request_data") or data
    output_dir = str(DOWNLOAD_BASE / f"NAT_{nfn}")
    try:
        from titlepro.automation.nat_payload_builder import build_nat_payload
        cure_data = build_nat_payload(output_dir, request_data)
        _manual_report_files: list = []
        _manual_out = Path(output_dir)
        for _pdf_name in ["RAW_TWO_OWNER_SEARCH_EXAM.pdf", "Title_Examination_Notes.pdf"]:
            _p = _manual_out / _pdf_name
            if _p.exists():
                _manual_report_files.append(str(_p.resolve()))
        for _f in sorted(_manual_out.glob("OnE_Report_*.pdf")):
            if "_NAT_" not in _f.name:
                _manual_report_files.append(str(_f.resolve()))
                break
        nat_payload = {
            "nat_file_number": nfn,
            "status": "Success",
            "status_reason": None,
            "data": cure_data,
            "report_files": _manual_report_files,
        }
        # Save full payload to disk for post-send debugging
        _dbg_path = ""
        try:
            _dbg_path = str(Path(output_dir) / "nat_callback_payload_debug.json")
            with open(_dbg_path, "w", encoding="utf-8") as _dbg_f:
                json.dump(nat_payload, _dbg_f, indent=2, default=str)
        except Exception:
            pass
        ok = _nat_call_back_to_nat(nat_payload)
        job["status"] = "completed" if ok else "callback_failed"
        job["result"] = {"data": cure_data}
        _nat_event(job, nfn, "manual_callback_sent" if ok else "manual_callback_failed")
        _nat_job_write(nfn, job)
        vesting_count = len(cure_data.get("vesting_attributes", []))
        mortgage_count = len(cure_data.get("open_mortgage_attributes", []))
        judgment_count = len(cure_data.get("open_judgments_attributes", []))
        return jsonify({
            "success": ok,
            "payload_keys": list(cure_data.keys()),
            "vesting_count": vesting_count,
            "mortgage_count": mortgage_count,
            "judgment_count": judgment_count,
            "tax_apn": cure_data.get("TaxAPNAccount", ""),
            "debug_payload_file": _dbg_path,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── Audit / history endpoints ─────────────────────────────────────────────────

@app.route('/api/nat/history', methods=['GET'])
def nat_history():
    """List all NAT jobs (most recent first). ?active=1 for running only."""
    active_only = request.args.get("active") == "1"
    jobs = []
    for jf in sorted(NAT_JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(jf, encoding="utf-8") as f:
                j = json.load(f)
            if active_only and j.get("status") not in ("queued", "running", "downloading"):
                continue
            # Return summary only (no trace or full timeline)
            jobs.append({
                "nat_file_number": j.get("nat_file_number"),
                "status": j.get("status"),
                "current_stage": j.get("current_stage"),
                "created_at": j.get("created_at"),
                "completed_at": j.get("completed_at"),
                "county_slug": j.get("county_slug"),
                "error": j.get("error"),
            })
        except Exception:
            pass
    return jsonify({"success": True, "jobs": jobs, "count": len(jobs)})


@app.route('/api/nat/history/<nfn>', methods=['GET'])
def nat_history_detail(nfn):
    """Full audit detail for one NAT file number."""
    job = _nat_job_read(nfn)
    if not job:
        return jsonify({"success": False, "error": f"Job {nfn} not found"}), 404
    # Omit the giant error_trace from the main job detail for readability
    job_view = {k: v for k, v in job.items() if k != "error_trace"}
    return jsonify({"success": True, "job": job_view})


@app.route('/api/nat/file/<nfn>/<path:file_path>', methods=['GET'])
def nat_serve_file(nfn, file_path):
    """Serve an artifact file from a NAT job's output folder."""
    safe_nfn = re.sub(r"[^A-Za-z0-9_\-]", "", nfn)
    target = DOWNLOAD_BASE / f"NAT_{safe_nfn}" / file_path
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    # Prevent path traversal
    try:
        target.resolve().relative_to((DOWNLOAD_BASE / f"NAT_{safe_nfn}").resolve())
    except ValueError:
        return jsonify({"error": "Forbidden"}), 403
    return send_file(target)


# ── Delete / Trash endpoints ──────────────────────────────────────────────────

@app.route('/api/nat/delete/<nfn>', methods=['POST'])
def nat_soft_delete(nfn):
    """
    Soft-delete: move job JSON from .nat_jobs/ to .nat_trash/.
    Job disappears from Queue and History; appears in Trash tab.
    Only allowed when job is NOT actively running.
    """
    src = NAT_JOBS_DIR / f"{nfn}.json"
    if not src.exists():
        return jsonify({"success": False, "error": f"Job {nfn} not found"}), 404

    job = _nat_job_read(nfn)
    if job.get("status") in ("queued", "running", "downloading"):
        return jsonify({
            "success": False,
            "error": f"Job {nfn} is still {job.get('status')} — stop it before deleting",
        }), 409

    dst = NAT_TRASH_DIR / f"{nfn}.json"
    deleted_folder = None
    try:
        import shutil as _shutil
        _shutil.move(str(src), str(dst))
        nat_jobs.pop(nfn, None)
        # Also delete the output folder so no orphaned files remain on disk
        output_dir = DOWNLOAD_BASE / f"NAT_{nfn}"
        if output_dir.exists():
            _shutil.rmtree(output_dir)
            deleted_folder = str(output_dir)
        print(f"[NAT] Job {nfn} moved to trash; folder deleted: {deleted_folder}", flush=True)
        return jsonify({
            "success": True,
            "message": f"Job {nfn} moved to trash",
            "deleted_folder": deleted_folder,
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/nat/trash', methods=['GET'])
def nat_list_trash():
    """List all jobs currently in trash."""
    jobs = []
    for jf in sorted(NAT_TRASH_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(jf, encoding="utf-8") as f:
                j = json.load(f)
            jobs.append({
                "nat_file_number": j.get("nat_file_number"),
                "status": j.get("status"),
                "current_stage": j.get("current_stage"),
                "created_at": j.get("created_at"),
                "completed_at": j.get("completed_at"),
                "county_slug": j.get("county_slug"),
                "error": j.get("error"),
            })
        except Exception:
            pass
    return jsonify({"success": True, "jobs": jobs, "count": len(jobs)})


@app.route('/api/nat/trash/<nfn>', methods=['GET'])
def nat_trash_detail(nfn):
    """Return full job record from trash for the audit panel detail view."""
    p = NAT_TRASH_DIR / f"{nfn}.json"
    if not p.exists():
        return jsonify({"success": False, "error": f"Job {nfn} not in trash"}), 404
    try:
        job = json.loads(p.read_text(encoding="utf-8"))
        return jsonify({"success": True, "job": job})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/nat/trash/restore/<nfn>', methods=['POST'])
def nat_restore_from_trash(nfn):
    """Restore a job from trash back to .nat_jobs/ (appears in History again)."""
    src = NAT_TRASH_DIR / f"{nfn}.json"
    if not src.exists():
        return jsonify({"success": False, "error": f"Job {nfn} not in trash"}), 404

    dst = NAT_JOBS_DIR / f"{nfn}.json"
    if dst.exists():
        return jsonify({"success": False, "error": f"Job {nfn} already exists in active jobs"}), 409

    try:
        import shutil as _shutil
        _shutil.move(str(src), str(dst))
        print(f"[NAT] Job {nfn} restored from trash", flush=True)
        return jsonify({"success": True, "message": f"Job {nfn} restored"})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route('/api/nat/trash/delete/<nfn>', methods=['POST'])
def nat_permanent_delete(nfn):
    """
    Permanent delete: remove job JSON from trash AND output folder from disk.
    This cannot be undone.
    """
    trash_file = NAT_TRASH_DIR / f"{nfn}.json"
    if not trash_file.exists():
        return jsonify({"success": False, "error": f"Job {nfn} not in trash — soft-delete it first"}), 404

    deleted = []
    errors = []

    # Remove job JSON from trash
    try:
        trash_file.unlink()
        deleted.append(f".nat_trash/{nfn}.json")
    except Exception as exc:
        errors.append(f"job file: {exc}")

    # Remove output folder if it exists
    output_dir = DOWNLOAD_BASE / f"NAT_{nfn}"
    if output_dir.exists():
        try:
            import shutil as _shutil
            _shutil.rmtree(output_dir)
            deleted.append(f"downloaded_doc/NAT_{nfn}/")
        except Exception as exc:
            errors.append(f"output folder: {exc}")

    print(f"[NAT] Permanent delete {nfn}: removed {deleted}", flush=True)
    return jsonify({
        "success": not errors,
        "deleted": deleted,
        "errors": errors,
        "message": f"Job {nfn} permanently deleted" if not errors else "Partial delete — see errors",
    })


# ─── END NAT INTEGRATION ENDPOINTS ───────────────────────────────────────────


@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    """
    Get server console logs.

    Query params:
        lines: Number of lines to return (default 500, max 500)

    Returns:
        JSON with logs array
    """
    num_lines = min(int(request.args.get('lines', 500)), MAX_LOG_LINES)

    return jsonify({
        "success": True,
        "logs": server_logs[-num_lines:] if server_logs else [],
        "total_lines": len(server_logs)
    })


if __name__ == '__main__':
    # ── NAT fault tolerance startup ───────────────────────────────────────────
    _nat_recover_orphaned_jobs()
    _wdg = threading.Thread(target=_nat_watchdog_loop, daemon=True, name="nat-watchdog")
    _wdg.start()
    # ─────────────────────────────────────────────────────────────────────────

    print("=" * 60)
    print("TitlePro API Server - CURE Multi-County Edition")
    print("=" * 60)
    print(f"Download folder: {DOWNLOAD_BASE}")
    print(f"NAT jobs folder: {NAT_JOBS_DIR}")
    print("")

    # Show multi-county status
    if MULTI_COUNTY_AVAILABLE and get_supported_counties:
        counties = get_supported_counties()
        no_captcha = get_counties_without_captcha() if get_counties_without_captcha else []
        print(f"Multi-county support: ENABLED")
        print(f"  Supported counties: {len(counties)}")
        print(f"  No-CAPTCHA counties: {len(no_captcha)}")
        print(f"  Counties: {', '.join(sorted(counties)[:10])}{'...' if len(counties) > 10 else ''}")
    else:
        print(f"Multi-county support: DISABLED (Orange County only)")
        if RECORDER_IMPORT_ERROR:
            print(f"  Import error: {RECORDER_IMPORT_ERROR}")

    print("")
    print("Starting server on http://localhost:5555")
    print("")
    print("Endpoints:")
    print("  GET  /status                      - Health check")
    print("  GET  /api/counties                - List supported counties")
    print("  GET  /api/files                   - Browse downloaded_doc folder")
    print("  GET  /api/file/<path>             - Get/download file")
    print("  GET  /api/logs                    - Get server console logs")
    print("  POST /api/workflow/status         - Load/save gated workflow status")
    print("  POST /api/workflow/run-phase      - Run one gated workflow phase")
    print("  POST /api/workflow/resume-checkpoint - Resume a human workflow checkpoint")
    print("  POST /api/workflow/resume         - Alias for resume-checkpoint")
    print("  POST /api/workflow/renew          - Extend checkpoint expiry")
    print("  POST /api/workflow/cancel         - Cancel checkpoint + close browser")
    print("  GET  /api/workflow/job/<id>       - Poll gated workflow phase job")
    print("  POST /search-recorder             - Search county recorder (background job)")
    print("  GET  /search-recorder-status/<id> - Poll search job progress")
    print("  POST /search-recorder-multiname   - Search with multiple names + deduplication")
    print("  POST /check-files                 - Check which files exist")
    print("  POST /download                    - Download single document")
    print("  POST /batch-download              - Download multiple documents")
    print("  POST /batch-download-deduplicated - Download with deduplication")
    print("  POST /deduplicate-preview         - Preview deduplication stats")
    print("  GET  /batch-status/<id>           - Check batch job status")
    print("  GET  /download/<id>               - Check single download status")
    print("  GET  /list-files/<owner>          - List files in owner folder")
    print("  POST /generate-report             - Generate RAW Two Owner Search report")
    print("  GET  /get-report/<owner>          - Get existing report for owner")
    print("  POST /download-pdf                - Download report as formatted PDF")
    print("")
    print("NAT Audit Panel:")
    print("  GET  /nat-audit                       - Browser UI (queue, history, workbench)")
    print("")
    print("NAT Integration Endpoints:")
    print("  POST /api/nat/start-extraction        - Submit NAT order (fire-and-forget)")
    print("  GET  /api/nat/job-status/<nfn>        - Poll job status")
    print("  POST /api/nat/retry/<nfn>             - Stage-aware retry/resume")
    print("  POST /api/admin/cancel-job            - Stop a running job")
    print("  POST /api/nat/manual/initialize       - Workbench step 0")
    print("  POST /api/nat/manual/search           - Workbench step 1")
    print("  POST /api/nat/manual/download         - Workbench step 2")
    print("  POST /api/nat/manual/tax              - Workbench step 3")
    print("  POST /api/nat/manual/ai-reports       - Workbench step 4")
    print("  POST /api/nat/manual/send-callback    - Workbench step 5")
    print("  GET  /api/nat/history                 - All jobs list")
    print("  GET  /api/nat/history/<nfn>           - Job audit detail")
    print("  GET  /api/nat/file/<nfn>/<path>       - Serve job artifact")
    print("")
    print(f"Note: {RECORDER_NOTE}")
    print("")
    print("=" * 60)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5555)), debug=True, threaded=True, use_reloader=False)
