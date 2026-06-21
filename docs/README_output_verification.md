# Output Structure Verification Utility

This utility checks that the output directory after each test subject run contains all required files, and that key mappings and file types are correct.

## Usage

1. Place this script in `report_generation/`
2. Run after test subject run:

```
python3 report_generation/output_structure_verifier.py --output-dir report_generation/output
```

*Use `--log` to append results to structure_verification.log in the output directory.*

## What It Verifies

- All required output files are present:
    - `report.pdf`
    - `summary.md`
    - `run.log`
    - `metadata.json`
    - `result_map.json`
- That types are correct (.pdf, .md, .json, .log)
- That minimal/spot content checks succeed: test_subject in metadata.json, basic structure in result_map.json, Markdown heading in summary.md.
- Logs results and prints human-friendly report.

## Extending
- Update REQUIRED_FILES or SPOT_CHECKS in the script for new outputs.
