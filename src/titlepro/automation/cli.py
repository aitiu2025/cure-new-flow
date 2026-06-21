from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .pipeline import RecorderAutomationPipeline, WorkflowConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the strict TitlePro search -> download -> validate -> AI report workflow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using a JSON config file (existing behaviour):
  titlepro-gated-workflow --config cases/SMITH_JOHN.json

  # Inline — single owner name:
  titlepro-gated-workflow --owner "SMITH JOHN" --county broward --state FL \\
      --address "123 Main St, Fort Lauderdale, FL 33301" --stop-after search

  # Inline — husband + wife (repeat --name for each person to search):
  titlepro-gated-workflow --owner "SMITH JOHN" --county broward --state FL \\
      --address "123 Main St, Fort Lauderdale, FL 33301" \\
      --name "Smith John" --name "Smith Jane" --stop-after search

  # Inline — with APN:
  titlepro-gated-workflow --owner "HERRON DAVID R" --county orange --state CA \\
      --address "21942 Via del Lago, Trabuco Canyon, CA 92679" \\
      --apn "934-461-11" --name "Herron David R" --name "Hench Sandra D"
""",
    )

    # --- Config file (optional when inline args are provided) ---
    parser.add_argument(
        "--config",
        help="Path to a workflow JSON config file. When provided, all other "
             "case arguments are ignored.",
    )

    # --- Inline case arguments ---
    parser.add_argument(
        "--owner",
        metavar="NAME",
        help='Primary owner name in "LAST FIRST" format, e.g. "SMITH JOHN".',
    )
    parser.add_argument(
        "--county",
        metavar="COUNTY",
        help='County slug, e.g. "broward", "orange", "manatee".',
    )
    parser.add_argument(
        "--state",
        metavar="STATE",
        default="FL",
        help='State code: "FL" or "CA". Default: FL.',
    )
    parser.add_argument(
        "--address",
        metavar="ADDRESS",
        default="",
        help="Subject property address.",
    )
    parser.add_argument(
        "--apn",
        metavar="APN",
        default=None,
        help="Assessor Parcel Number (used for tax lookup).",
    )
    parser.add_argument(
        "--name",
        metavar="NAME",
        action="append",
        dest="names",
        help="Name to search on the recorder portal. Repeat for each person "
             '(husband, wife, trust). E.g. --name "Smith John" --name "Smith Jane". '
             "When omitted, --owner is used as the sole search name.",
    )
    parser.add_argument(
        "--start-date",
        metavar="MM/DD/YYYY",
        default="01/01/2000",
        help="Search start date. Default: 01/01/2000.",
    )
    parser.add_argument(
        "--end-date",
        metavar="MM/DD/YYYY",
        default=None,
        help="Search end date. Default: today.",
    )
    parser.add_argument(
        "--output-folder",
        metavar="FOLDER",
        default=None,
        help="Output subfolder name under downloaded_doc/. Default: derived from --owner.",
    )

    # --- Pipeline control ---
    parser.add_argument(
        "--stop-after",
        choices=RecorderAutomationPipeline.phase_order,
        help="Run through this phase then stop.",
    )
    parser.add_argument(
        "--skip-tax",
        action="store_true",
        default=False,
        help="Skip the tax_lookup phase. Use when APN is unknown or no tax adapter exists for the county.",
    )
    parser.add_argument(
        "--raw-prompt",
        metavar="PATH",
        default=None,
        help="Path to the RAW report system prompt file. Overrides the default search locations.",
    )
    parser.add_argument(
        "--title-prompt",
        metavar="PATH",
        default=None,
        help="Path to the Title report system prompt file. Overrides the default search locations.",
    )
    parser.add_argument(
        "--skip-one",
        action="store_true",
        default=False,
        help="Skip the generate_one_report phase (OnE client report).",
    )
    parser.add_argument(
        "--one-prompt",
        metavar="PATH",
        default=None,
        help="Path to the OnE report system prompt file. Overrides the default search locations.",
    )

    return parser.parse_args()


def _build_inline_config(args: argparse.Namespace) -> WorkflowConfig:
    """Build a WorkflowConfig from command-line arguments (no JSON file needed)."""
    if not args.owner:
        print("ERROR: --owner is required when --config is not provided.", file=sys.stderr)
        print('  Example: --owner "SMITH JOHN"', file=sys.stderr)
        sys.exit(1)
    if not args.county:
        print("ERROR: --county is required when --config is not provided.", file=sys.stderr)
        print('  Example: --county broward', file=sys.stderr)
        sys.exit(1)

    end_date = args.end_date or datetime.now().strftime("%m/%d/%Y")

    # Build search_requests: one entry per --name, or fall back to --owner
    names = args.names or [args.owner.title()]
    search_requests = [
        {"name": name, "party_types": ["Grantor", "Grantee", "Grantor/Grantee"]}
        for name in names
    ]

    data = {
        "owner_name": args.owner,
        "county": args.county,
        "state": args.state,
        "property_address": args.address,
        "apn": args.apn,
        "start_date": args.start_date,
        "end_date": end_date,
        "output_folder_name": args.output_folder,
        "search_requests": search_requests,
        "fetch_tax": not args.skip_tax,
        "generate_one_report": not args.skip_one,
        "ai": {
            "provider": "claude",
            "timeout_seconds": 900,
            "raw_prompt_path": args.raw_prompt,
            "title_prompt_path": args.title_prompt,
            "one_prompt_path": args.one_prompt,
        },
    }
    return WorkflowConfig.from_dict(data)


def main() -> None:
    args = parse_args()

    if args.config:
        config = WorkflowConfig.from_file(Path(args.config).expanduser().resolve())
    else:
        config = _build_inline_config(args)

    pipeline = RecorderAutomationPipeline(config)
    result = pipeline.run(stop_after=args.stop_after)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
