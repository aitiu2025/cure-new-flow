#!/usr/bin/env python3
"""
Verifies output directory structure and files for EvictSure project runs.
Checks for required .pdf, .md, .log, .json, etc. files per specification.
Performs content spot-check mapping validation.
"""
import os
import json
import glob
from pathlib import Path

# SETTINGS
OUTPUT_DIR = Path('report_generation/output')  # Standard output dir (update per spec if different)
REQUIRED_FILES = [
    {
        'name': 'report.pdf',
        'type': 'pdf',
    },
    {
        'name': 'summary.md',
        'type': 'md',
    },
    {
        'name': 'run.log',
        'type': 'log',
    },
    {
        'name': 'metadata.json',
        'type': 'json',
    },
    {
        'name': 'result_map.json',
        'type': 'json',
    }
]

SPOT_CHECKS = [
    # (file, check function)
    ('metadata.json', lambda data: 'test_subject' in data),
    ('result_map.json', lambda data: isinstance(data.get('mappings'), dict)),
    ('summary.md', lambda text: '# TITLE PROPERTY REPORT' in text or 'Summary' in text),
]

def verify_file_exists(path: Path, filetype: str) -> (bool, str):
    """
    Check that file at path exists and is of the expected type.
    """
    if not path.exists():
        return False, f"Missing: {path.name}"
    if filetype == 'pdf' and not path.name.lower().endswith('.pdf'):
        return False, f"Expected PDF: {path.name}"
    if filetype == 'md' and not path.name.lower().endswith('.md'):
        return False, f"Expected Markdown: {path.name}"
    if filetype == 'log' and not path.name.lower().endswith('.log'):
        return False, f"Expected Log: {path.name}"
    if filetype == 'json' and not path.name.lower().endswith('.json'):
        return False, f"Expected JSON: {path.name}"
    return True, ''

def spot_check_file(path: Path, check_fn):
    """
    Quick spot-check of content mapping.
    """
    try:
        if path.suffix == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return check_fn(data)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = f.read(4096)  # Read only a little for md/checks
            return check_fn(data)
    except Exception as e:
        return False

def verify_output_structure(base_dir: Path = OUTPUT_DIR):
    """
    Main verification routine.
    """
    results = {
        'missing_files': [],
        'bad_type': [],
        'spot_check_failed': [],
        'ok': [],
    }
    for spec in REQUIRED_FILES:
        fpath = base_dir / spec['name']
        exists, msg = verify_file_exists(fpath, spec['type'])
        if not exists:
            results['missing_files'].append(msg)
        else:
            results['ok'].append(f'{fpath.name}: present')
    # Spot content checks
    for fname, checkfn in SPOT_CHECKS:
        fpath = base_dir / fname
        if fpath.exists():
            if not spot_check_file(fpath, checkfn):
                results['spot_check_failed'].append(fname)
    return results

def print_report(results, output_to_log=False, base_dir: Path = OUTPUT_DIR):
    """
    Print and optionally log the verification report.
    """
    status = 'PASS' if not (results['missing_files'] or results['spot_check_failed']) else 'FAIL'
    summary = f"Verification result for {base_dir.resolve()} [{status}]\n"
    details = ''
    if results['missing_files']:
        details += f"Missing files: {results['missing_files']}\n"
    if results['spot_check_failed']:
        details += f"File spot checks failed: {results['spot_check_failed']}\n"
    for msg in results['ok']:
        details += f"OK: {msg}\n"
    print(summary + details)
    if output_to_log:
        with open(base_dir / 'structure_verification.log', 'a') as flog:
            flog.write(summary + details)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Verify output directory structure and files.')
    parser.add_argument('--output-dir', type=str, default=str(OUTPUT_DIR), help='Path to output directory to verify')
    parser.add_argument('--log', action='store_true', help='Log verification results to a structure_verification.log file')
    args = parser.parse_args()
    base_dir = Path(args.output_dir)
    results = verify_output_structure(base_dir)
    print_report(results, output_to_log=args.log, base_dir=base_dir)

if __name__ == '__main__':
    main()
