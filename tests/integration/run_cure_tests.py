#!/usr/bin/env python3
"""
CURE System Full Test Execution Script

Runs the complete CURE workflow for all 21 test subjects from CURE_County_Test_Subjects.json.
Executes tests one by one, logging results and generating reports.

Usage (from project root):
    python -m tests.integration.run_cure_tests                    # Run all tests
    python -m tests.integration.run_cure_tests --phase 1         # Run Phase 1 only (Tyler no-captcha)
    python -m tests.integration.run_cure_tests --phase 2         # Run Phase 2 only (RecorderWorks)
    python -m tests.integration.run_cure_tests --phase 3         # Run Phase 3 only (Tyler with-captcha)
    python -m tests.integration.run_cure_tests --test-id 11      # Run specific test ID
    python -m tests.integration.run_cure_tests --dry-run         # Show what would be run without executing
    python -m tests.integration.run_cure_tests --start-from 15   # Start from test 15
"""

import sys
import os
import json
import argparse
import traceback
from datetime import datetime
from pathlib import Path
import time

# Project root is two levels up from tests/integration/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# Add src/ to Python path so `from titlepro.xxx import ...` works
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Configuration
TEST_DATA_PATH = "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/Jan 2026 Requirements/CURE_County_Test_Subjects.json"
RESULTS_DIR = PROJECT_ROOT / "test_results"
LOG_FILE = PROJECT_ROOT / "cure_test_execution.log"

# Test phases
PHASES = {
    1: {
        "name": "Tyler Counties WITHOUT CAPTCHA",
        "test_ids": [11, 14, 15, 18],
        "priority": "HIGH"
    },
    2: {
        "name": "RecorderWorks Counties",
        "test_ids": [1, 5, 10, 17],
        "priority": "HIGH"
    },
    3: {
        "name": "Tyler Counties WITH CAPTCHA",
        "test_ids": [2, 3, 4, 6, 7, 8, 9, 12, 13, 16, 19, 20, 21],
        "priority": "MEDIUM"
    }
}


def color(msg, c):
    """Add ANSI color codes."""
    codes = {
        'red': '\033[31m', 'green': '\033[32m', 'yellow': '\033[33m',
        'blue': '\033[34m', 'cyan': '\033[36m', 'bold': '\033[1m',
        'reset': '\033[0m'
    }
    return f"{codes.get(c, '')}{msg}{codes['reset']}"


def log(message, level="INFO"):
    """Log message to console and file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)

    with open(LOG_FILE, 'a') as f:
        f.write(log_line + "\n")


def load_test_subjects():
    """Load test subjects from JSON."""
    with open(TEST_DATA_PATH, 'r') as f:
        data = json.load(f)
    return data.get('test_subjects', [])


def get_subject_by_id(subjects, test_id):
    """Get test subject by ID."""
    for s in subjects:
        if s.get('id') == test_id:
            return s
    return None


def run_single_test(test_subject, dry_run=False):
    """
    Run the complete CURE workflow for a single test subject.

    Returns dict with:
        - success: bool
        - test_id: int
        - county: str
        - borrowers: list
        - steps: list of step results
        - error: str or None
        - duration_seconds: float
    """
    test_id = test_subject['id']
    county = test_subject['county']
    county_id = test_subject['county_id']
    platform = test_subject['platform']

    # Extract borrower names
    borrowers = []
    if test_subject.get('borrower1'):
        borrowers.append(test_subject['borrower1'])
    if test_subject.get('borrower2'):
        borrowers.append(test_subject['borrower2'])
    if test_subject.get('borrower3'):
        borrowers.append(test_subject['borrower3'])

    property_info = test_subject.get('property', {})

    result = {
        'test_id': test_id,
        'county': county,
        'county_id': county_id,
        'platform': platform,
        'borrowers': [b.get('full_name') for b in borrowers],
        'property': property_info,
        'steps': [],
        'success': False,
        'error': None,
        'duration_seconds': 0,
        'started_at': datetime.now().isoformat(),
        'documents_found': 0,
        'documents_downloaded': 0,
        'vesting_deed_found': False,
        'discovered_names': [],
        'report_generated': False
    }

    if dry_run:
        result['success'] = True
        result['steps'].append({'step': 'dry_run', 'status': 'skipped', 'message': 'Dry run mode'})
        return result

    start_time = time.time()

    try:
        # Import workflow modules
        log(f"  Importing workflow modules...")

        from titlepro.core.multi_name_workflow import MultiNameWorkflow

        # Step 1: Initialize workflow
        log(f"  Step 1: Initializing workflow for {county} ({platform})...")
        result['steps'].append({'step': 'init', 'status': 'running'})

        workflow = MultiNameWorkflow(county=county_id)
        result['steps'][-1]['status'] = 'completed'

        # Step 2: Prepare search names
        log(f"  Step 2: Preparing search names...")
        result['steps'].append({'step': 'prepare_names', 'status': 'running'})

        search_names = []
        for borrower in borrowers:
            search_format = borrower.get('search_format')
            if search_format:
                search_names.append(search_format)

        log(f"    Search names: {search_names}")
        result['steps'][-1]['status'] = 'completed'
        result['steps'][-1]['names'] = search_names

        # Step 3: Run the multi-name workflow
        log(f"  Step 3: Running multi-name workflow...")
        result['steps'].append({'step': 'workflow_run', 'status': 'running'})

        workflow_result = workflow.run(
            owner_names=search_names,
            start_date="01/01/2000",
            end_date=datetime.now().strftime("%m/%d/%Y"),
            download_vesting_deed=True,
            analyze_vesting_deed=True
        )

        result['steps'][-1]['status'] = 'completed' if workflow_result.success else 'failed'
        result['documents_found'] = len(workflow_result.all_documents)
        result['discovered_names'] = workflow_result.discovered_names
        result['vesting_deed_found'] = workflow_result.vesting_deed is not None

        log(f"    Workflow success: {workflow_result.success}")
        log(f"    Documents found: {len(workflow_result.all_documents)}")
        log(f"    Discovered names: {workflow_result.discovered_names}")

        if workflow_result.vesting_deed:
            log(f"    Vesting deed: {workflow_result.vesting_deed.document_number}")

        # Step 4: Download all documents (batch)
        if workflow_result.all_documents:
            log(f"  Step 4: Downloading documents...")
            result['steps'].append({'step': 'download_docs', 'status': 'running'})

            from titlepro.download.selenium_downloader import download_document

            downloaded = 0
            for doc in workflow_result.all_documents[:10]:  # Limit to first 10 for testing
                doc_num = doc.get('document_number') or doc.get('inst_num')
                year = doc.get('year') or doc.get('recording_date', '')[:4]

                if doc_num:
                    try:
                        owner_folder = borrowers[0].get('full_name', 'Unknown').replace(' ', '_')
                        dl_result = download_document(
                            doc_num=doc_num,
                            year=year,
                            headless=True,
                            owner_name=owner_folder,
                            county=county_id
                        )
                        if dl_result.get('status') == 'success':
                            downloaded += 1
                    except Exception as e:
                        log(f"    Warning: Failed to download {doc_num}: {e}", "WARN")

            result['documents_downloaded'] = downloaded
            result['steps'][-1]['status'] = 'completed'
            result['steps'][-1]['downloaded'] = downloaded
            log(f"    Downloaded {downloaded} documents")

        # Step 5: Generate report
        log(f"  Step 5: Generating report...")
        result['steps'].append({'step': 'generate_report', 'status': 'running'})

        try:
            from titlepro.reports.report_generator import generate_markdown_report, generate_pdf_report

            owner_folder = borrowers[0].get('full_name', 'Unknown').replace(' ', '_')
            output_dir = PROJECT_ROOT / "downloaded_doc" / f"{county}_{owner_folder}"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save workflow result as JSON
            result_json = output_dir / "workflow_result.json"
            with open(result_json, 'w') as f:
                json.dump({
                    'success': workflow_result.success,
                    'initial_names': workflow_result.initial_names,
                    'discovered_names': workflow_result.discovered_names,
                    'documents_count': len(workflow_result.all_documents),
                    'county': county,
                    'workflow_log': workflow_result.workflow_log[-20:]  # Last 20 entries
                }, f, indent=2)

            result['report_generated'] = True
            result['steps'][-1]['status'] = 'completed'
            log(f"    Report saved to: {output_dir}")

        except Exception as e:
            result['steps'][-1]['status'] = 'failed'
            result['steps'][-1]['error'] = str(e)
            log(f"    Report generation failed: {e}", "WARN")

        result['success'] = workflow_result.success

    except Exception as e:
        result['error'] = str(e)
        result['steps'].append({
            'step': 'error',
            'status': 'failed',
            'error': traceback.format_exc()
        })
        log(f"  ERROR: {e}", "ERROR")

    result['duration_seconds'] = time.time() - start_time
    result['completed_at'] = datetime.now().isoformat()

    return result


def save_test_result(result, results_dir):
    """Save individual test result to JSON file."""
    results_dir.mkdir(parents=True, exist_ok=True)

    test_id = result['test_id']
    county = result['county']
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = results_dir / f"test_{test_id}_{county}_{timestamp}.json"

    with open(filename, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    return filename


def main():
    parser = argparse.ArgumentParser(description='Run CURE system tests')
    parser.add_argument('--phase', type=int, choices=[1, 2, 3], help='Run specific phase only')
    parser.add_argument('--test-id', type=int, help='Run specific test ID only')
    parser.add_argument('--dry-run', action='store_true', help='Show what would run without executing')
    parser.add_argument('--start-from', type=int, help='Start from specific test ID')
    args = parser.parse_args()

    # Clear log file
    LOG_FILE.unlink(missing_ok=True)

    print(f"\n{'='*70}")
    print(color("  CURE System Full Test Execution", 'bold'))
    print(f"{'='*70}")
    print(f"  Started: {datetime.now()}")
    print(f"  Results dir: {RESULTS_DIR}")
    if args.dry_run:
        print(color("  MODE: DRY RUN (no actual execution)", 'yellow'))
    print(f"{'='*70}\n")

    log("Starting CURE test execution")

    # Load test subjects
    subjects = load_test_subjects()
    log(f"Loaded {len(subjects)} test subjects")

    # Determine which tests to run
    tests_to_run = []

    if args.test_id:
        # Single test
        subject = get_subject_by_id(subjects, args.test_id)
        if subject:
            tests_to_run.append(subject)
        else:
            log(f"Test ID {args.test_id} not found!", "ERROR")
            sys.exit(1)
    elif args.phase:
        # Specific phase
        phase_config = PHASES.get(args.phase)
        if phase_config:
            for test_id in phase_config['test_ids']:
                subject = get_subject_by_id(subjects, test_id)
                if subject:
                    tests_to_run.append(subject)
    else:
        # All tests in phase order
        for phase_num in [1, 2, 3]:
            phase_config = PHASES[phase_num]
            for test_id in phase_config['test_ids']:
                subject = get_subject_by_id(subjects, test_id)
                if subject:
                    tests_to_run.append(subject)

    # Apply start-from filter
    if args.start_from:
        tests_to_run = [t for t in tests_to_run if t['id'] >= args.start_from]

    log(f"Will run {len(tests_to_run)} tests")

    # Track results
    all_results = []
    successful = 0
    failed = 0

    # Run tests
    for i, subject in enumerate(tests_to_run, 1):
        test_id = subject['id']
        county = subject['county']
        platform = subject['platform']
        borrower = subject.get('borrower1', {}).get('full_name', 'Unknown')

        print(f"\n{'-'*70}")
        print(color(f"Test {i}/{len(tests_to_run)}: ID={test_id} | {county} ({platform})", 'cyan'))
        print(f"  Borrower: {borrower}")
        print(f"{'-'*70}")

        log(f"Running test {test_id}: {county} - {borrower}")

        # Run the test
        result = run_single_test(subject, dry_run=args.dry_run)
        all_results.append(result)

        # Save result
        result_file = save_test_result(result, RESULTS_DIR)

        # Update counts
        if result['success']:
            successful += 1
            print(color(f"  RESULT: SUCCESS", 'green'))
        else:
            failed += 1
            print(color(f"  RESULT: FAILED", 'red'))
            if result.get('error'):
                print(f"  Error: {result['error'][:100]}")

        print(f"  Duration: {result['duration_seconds']:.1f}s")
        print(f"  Documents found: {result.get('documents_found', 0)}")
        print(f"  Documents downloaded: {result.get('documents_downloaded', 0)}")
        print(f"  Result saved to: {result_file.name}")

        # Pause between tests to avoid rate limiting
        if i < len(tests_to_run) and not args.dry_run:
            log("Pausing 5 seconds before next test...")
            time.sleep(5)

    # Final summary
    print(f"\n{'='*70}")
    print(color("  TEST EXECUTION SUMMARY", 'bold'))
    print(f"{'='*70}")
    print(f"  Total tests: {len(all_results)}")
    print(color(f"  Successful:  {successful}", 'green'))
    print(color(f"  Failed:      {failed}", 'red'))
    print(f"  Success rate: {successful/len(all_results)*100:.1f}%")
    print(f"\n  Results saved to: {RESULTS_DIR}")
    print(f"  Log file: {LOG_FILE}")
    print(f"{'='*70}\n")

    # Save summary
    summary = {
        'execution_time': datetime.now().isoformat(),
        'total_tests': len(all_results),
        'successful': successful,
        'failed': failed,
        'success_rate': successful/len(all_results)*100 if all_results else 0,
        'dry_run': args.dry_run,
        'results': all_results
    }

    summary_file = RESULTS_DIR / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    log(f"Summary saved to: {summary_file}")

    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
