#!/usr/bin/env python3
"""
CURE System Test Suite Runner (Pre-flight Validation)
Checks that all required modules, configs, and directories exist before running
the full CURE test suite across all 21 county test subjects.

Usage (from project root):
    python -m tests.integration.test_suite_runner
"""

import sys
import os
import json
import traceback
import datetime
from pathlib import Path

# Project root is two levels up from tests/integration/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# Add src/ to Python path so `from titlepro.xxx import ...` works
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ---- CONFIGURATION ----
TEST_DATA_PATH = "/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/Jan 2026 Requirements/CURE_County_Test_Subjects.json"
LOG_PATH = PROJECT_ROOT / "test_suite_results.log"

# Test phases from the JSON file
PHASES = {
    "phase1_no_captcha": {
        "name": "Tyler Counties WITHOUT CAPTCHA",
        "test_ids": [11, 14, 15, 18],
        "priority": "HIGH"
    },
    "phase2_recorderworks": {
        "name": "RecorderWorks Counties",
        "test_ids": [1, 5, 10, 17],
        "priority": "HIGH"
    },
    "phase3_tyler_captcha": {
        "name": "Tyler Counties WITH CAPTCHA",
        "test_ids": [2, 3, 4, 6, 7, 8, 9, 12, 13, 16, 19, 20, 21],
        "priority": "MEDIUM"
    }
}


def color(msg, c):
    """Add ANSI color codes to message"""
    codes = {
        'red': '\033[31m',
        'green': '\033[32m',
        'yellow': '\033[33m',
        'blue': '\033[34m',
        'cyan': '\033[36m',
        'reset': '\033[0m'
    }
    return f"{codes.get(c, '')}{msg}{codes['reset']}"


def load_test_subjects():
    """Load test subjects from JSON file"""
    try:
        with open(TEST_DATA_PATH, 'r') as f:
            data = json.load(f)
        return data.get('test_subjects', [])
    except Exception as e:
        print(color(f"ERROR: Failed to load test subjects: {e}", 'red'))
        return []


def get_test_subject_by_id(subjects, test_id):
    """Get a test subject by its ID"""
    for subject in subjects:
        if subject.get('id') == test_id:
            return subject
    return None


def run_single_test(test_subject):
    """
    Run a single test subject through the CURE workflow.
    Returns dict with outcome and details.
    """
    test_id = test_subject.get('id')
    county = test_subject.get('county')
    borrower1 = test_subject.get('borrower1', {}).get('full_name', 'Unknown')

    result = {
        'test_id': test_id,
        'county': county,
        'borrower': borrower1,
        'outcome': 'PENDING',
        'steps_completed': [],
        'steps_failed': [],
        'error': None
    }

    try:
        # Step 1: Check if required modules exist
        required_modules = {
            'api_server': SRC_DIR / 'titlepro' / 'api' / 'server.py',
            'multi_name_workflow': SRC_DIR / 'titlepro' / 'core' / 'multi_name_workflow.py',
            'pdf_analyzer': SRC_DIR / 'titlepro' / 'core' / 'pdf_analyzer.py',
            'report_generator': SRC_DIR / 'titlepro' / 'reports' / 'report_generator.py',
            'selenium_downloader': SRC_DIR / 'titlepro' / 'download' / 'selenium_downloader.py',
            'cross_reference_checker': SRC_DIR / 'titlepro' / 'verification' / 'cross_reference_checker.py',
            'property_verifier': SRC_DIR / 'titlepro' / 'verification' / 'property_verifier.py',
            'document_deduplicator': SRC_DIR / 'titlepro' / 'core' / 'document_deduplicator.py',
            'county_tax_lookup': SRC_DIR / 'titlepro' / 'tax' / 'county_tax_lookup.py',
            'vesting_deed_identifier': SRC_DIR / 'titlepro' / 'verification' / 'vesting_deed_identifier.py',
        }

        for module_name, module_path in required_modules.items():
            if module_path.exists():
                result['steps_completed'].append(f"Module exists: {module_name}")
            else:
                result['steps_failed'].append(f"Missing module: {module_name} (expected: {module_path})")

        # Step 1b: Verify modules can be imported
        try:
            import titlepro.core.multi_name_workflow
            result['steps_completed'].append("Import OK: titlepro.core.multi_name_workflow")
        except ImportError as e:
            result['steps_failed'].append(f"Import failed: titlepro.core.multi_name_workflow ({e})")

        # Step 2: Check county configuration
        county_id = test_subject.get('county_id')
        platform = test_subject.get('platform')

        county_config_path = SRC_DIR / "titlepro" / "search" / "recorder" / "counties" / "config" / f"{county_id}.json"
        if county_config_path.exists():
            result['steps_completed'].append(f"County config exists: {county_id}")
        else:
            result['steps_failed'].append(f"Missing county config: {county_id}")

        # Step 3: Check for CAPTCHA requirements
        if test_subject.get('captcha'):
            captcha_type = test_subject.get('captcha_type', 'unknown')
            result['steps_completed'].append(f"CAPTCHA required: {captcha_type}")

            # Check captcha solver exists
            captcha_solver_path = SRC_DIR / "titlepro" / "search" / "recorder" / "captcha" / "recaptcha_solver.py"
            if captcha_solver_path.exists():
                result['steps_completed'].append("CAPTCHA solver available")
            else:
                result['steps_failed'].append("CAPTCHA solver missing")
        else:
            result['steps_completed'].append("No CAPTCHA required")

        # Step 4: Check output directory structure
        borrower_lastname = borrower1.split()[-1] if borrower1 else "Unknown"
        output_dir = PROJECT_ROOT / "downloaded_doc" / f"{county}_{borrower_lastname}"

        if output_dir.exists():
            result['steps_completed'].append(f"Output directory exists: {output_dir.name}")

            # Check for expected output files
            expected_files = [
                'document_metadata.json',
                'documents_found.json'
            ]
            for expected_file in expected_files:
                if (output_dir / expected_file).exists():
                    result['steps_completed'].append(f"Output file exists: {expected_file}")
        else:
            result['steps_completed'].append(f"Output directory would be: {output_dir.name}")

        # Determine overall outcome
        if result['steps_failed']:
            result['outcome'] = 'INCOMPLETE'
        else:
            result['outcome'] = 'READY'

    except Exception as e:
        result['outcome'] = 'ERROR'
        result['error'] = traceback.format_exc()

    return result


def log_to_file(logpath, lines):
    """Append lines to log file"""
    with open(logpath, 'a', encoding='utf8') as f:
        for line in lines:
            f.write(str(line) + "\n")


def main():
    """Main test suite execution"""
    # Clear old log file
    if LOG_PATH.exists():
        LOG_PATH.unlink()

    print(f"\n{'='*60}")
    print(color("  CURE System Test Suite Runner", 'cyan'))
    print(f"{'='*60}")
    print(f"  Timestamp: {datetime.datetime.now()}")
    print(f"  Test Data: {TEST_DATA_PATH}")
    print(f"{'='*60}\n")

    log_to_file(LOG_PATH, [
        f"CURE System Test Suite Run - {datetime.datetime.now()}",
        f"Test Data: {TEST_DATA_PATH}",
        "=" * 60,
        ""
    ])

    # Load test subjects
    test_subjects = load_test_subjects()
    if not test_subjects:
        print(color("ERROR: No test subjects loaded!", 'red'))
        return

    print(f"Loaded {len(test_subjects)} test subjects\n")

    # Track overall results
    all_results = []
    phase_summaries = []

    # Run tests by phase
    for phase_key, phase_config in PHASES.items():
        phase_name = phase_config['name']
        test_ids = phase_config['test_ids']
        priority = phase_config['priority']

        print(color(f"\n[PHASE: {phase_name}]", 'blue'))
        print(f"  Priority: {priority}")
        print(f"  Test IDs: {test_ids}")
        print("-" * 50)

        log_to_file(LOG_PATH, [
            f"\n[PHASE: {phase_name}]",
            f"Priority: {priority}",
            f"Test IDs: {test_ids}",
            "-" * 50
        ])

        phase_results = []

        for test_id in test_ids:
            subject = get_test_subject_by_id(test_subjects, test_id)

            if not subject:
                print(color(f"  Test {test_id}: NOT FOUND", 'yellow'))
                continue

            county = subject.get('county', 'Unknown')
            borrower = subject.get('borrower1', {}).get('full_name', 'Unknown')
            platform = subject.get('platform', 'unknown')

            print(f"  Test {test_id}: {county} ({platform})")
            print(f"    Borrower: {borrower}")

            # Run the test
            result = run_single_test(subject)
            phase_results.append(result)
            all_results.append(result)

            # Display result
            outcome = result['outcome']
            if outcome == 'READY':
                print(color(f"    Status: {outcome}", 'green'))
            elif outcome == 'INCOMPLETE':
                print(color(f"    Status: {outcome}", 'yellow'))
                for failed in result['steps_failed'][:3]:
                    print(f"      - {failed}")
            else:
                print(color(f"    Status: {outcome}", 'red'))
                if result['error']:
                    print(f"      Error: {result['error'][:100]}")

            print()

            # Log result
            log_to_file(LOG_PATH, [
                f"  Test {test_id}: {county} - {outcome}",
                f"    Borrower: {borrower}",
                f"    Completed: {result['steps_completed']}",
                f"    Failed: {result['steps_failed']}",
                ""
            ])

        # Phase summary
        ready = sum(1 for r in phase_results if r['outcome'] == 'READY')
        incomplete = sum(1 for r in phase_results if r['outcome'] == 'INCOMPLETE')
        errors = sum(1 for r in phase_results if r['outcome'] == 'ERROR')
        total = len(phase_results)

        phase_summary = {
            'phase': phase_name,
            'ready': ready,
            'incomplete': incomplete,
            'errors': errors,
            'total': total
        }
        phase_summaries.append(phase_summary)

        print(color(f"  Phase Summary: READY={ready} INCOMPLETE={incomplete} ERRORS={errors} TOTAL={total}", 'cyan'))
        log_to_file(LOG_PATH, [f"Phase Summary: READY={ready} INCOMPLETE={incomplete} ERRORS={errors} TOTAL={total}", ""])

    # Overall summary
    print(f"\n{'='*60}")
    print(color("  OVERALL TEST SUITE SUMMARY", 'cyan'))
    print(f"{'='*60}")

    total_ready = sum(1 for r in all_results if r['outcome'] == 'READY')
    total_incomplete = sum(1 for r in all_results if r['outcome'] == 'INCOMPLETE')
    total_errors = sum(1 for r in all_results if r['outcome'] == 'ERROR')
    total_tests = len(all_results)

    print(f"  READY      : {total_ready}")
    print(f"  INCOMPLETE : {total_incomplete}")
    print(f"  ERRORS     : {total_errors}")
    print(f"  TOTAL      : {total_tests}")
    print()

    # Phase breakdown
    print("  By Phase:")
    for ps in phase_summaries:
        status = "OK" if ps['ready'] == ps['total'] else "NEEDS WORK"
        print(f"    {ps['phase']}: {ps['ready']}/{ps['total']} ready ({status})")

    log_to_file(LOG_PATH, [
        "",
        "=" * 60,
        "OVERALL SUMMARY",
        "=" * 60,
        f"READY: {total_ready}",
        f"INCOMPLETE: {total_incomplete}",
        f"ERRORS: {total_errors}",
        f"TOTAL: {total_tests}",
        "",
        "By Phase:",
    ] + [f"  {ps['phase']}: {ps['ready']}/{ps['total']}" for ps in phase_summaries])

    print(f"\nFull log written to: {LOG_PATH}\n")

    # Return exit code based on results
    if total_errors > 0:
        sys.exit(1)
    elif total_incomplete > 0:
        sys.exit(0)  # Incomplete is OK, just needs more work
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
