#!/usr/bin/env python3
"""
CA Recorder Property Search - CLI Interface

Search California County Recorder websites for property documents
by name and find common documents between two parties.

Usage:
    # Single name search
    python main.py --name1 "Kwa Danny" --county orange

    # Two name search (find common documents)
    python main.py --name1 "Lau Casey" --name2 "Lau Brandi" --county orange

Examples:
    # Single name search with address filter
    python main.py -n1 "Kwa Danny" -c orange --address "12612 Lansdale"

    # Two name search (uses default date range 2010-today)
    python main.py -n1 "Lau Casey" -n2 "Lau Brandi" -c orange

    # Search with custom date range
    python main.py -n1 "Kwa Danny" -c orange --start-date 01/01/2000 --end-date 01/07/2026

    # Save results to JSON file
    python main.py -n1 "Kwa Danny" -c orange -o results.json
"""

import argparse
import sys
import os
from datetime import datetime

# Import county implementations
from titlepro.search.recorder.counties.orange import OrangeCountyRecorder


# Registry of supported counties
SUPPORTED_COUNTIES = {
    "orange": OrangeCountyRecorder,
    # Future: Add more counties here
    # "los_angeles": LosAngelesCountyRecorder,
    # "san_diego": SanDiegoCountyRecorder,
}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Search CA County Recorder websites for property documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --name1 "Kwa Danny" --county orange  (single name search)
  %(prog)s --name1 "Lau Casey" --name2 "Lau Brandi" --county orange  (two name search)
  %(prog)s -n1 "Kwa Danny" -c orange --address "12612 Lansdale" -o results.json

Note:
  Use "Last First" name format for best results (e.g., "Kwa Danny" not "Danny Kwa")
        """
    )

    # Required arguments
    parser.add_argument(
        "-n1", "--name1",
        required=True,
        help="First name to search (use 'Last First' format)"
    )
    parser.add_argument(
        "-n2", "--name2",
        required=False,
        default=None,
        help="Second name to search (optional - use 'Last First' format)"
    )
    parser.add_argument(
        "-c", "--county",
        required=True,
        choices=list(SUPPORTED_COUNTIES.keys()),
        help=f"County to search. Supported: {', '.join(SUPPORTED_COUNTIES.keys())}"
    )

    # Optional arguments
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON filename (default: prints to console)"
    )
    parser.add_argument(
        "--address",
        default=None,
        help="Property address to filter results (partial match)"
    )
    parser.add_argument(
        "--start-date",
        default="01/01/2010",
        help="Search start date MM/DD/YYYY (default: 01/01/2010)"
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Search end date MM/DD/YYYY (default: today)"
    )
    parser.add_argument(
        "--party-type",
        default="Grantor/Grantee",
        choices=["All", "Grantor", "Grantee", "Grantor/Grantee"],
        help="Party type filter (default: Grantor/Grantee)"
    )

    return parser.parse_args()


def print_results_summary(results: dict, single_name_mode: bool = False):
    """Print a formatted summary of search results to console."""
    params = results.get("search_params", {})
    summary = results.get("summary", {})

    print("\n" + "=" * 70)
    print("SEARCH RESULTS SUMMARY")
    print("=" * 70)

    print(f"\nSearch Parameters:")
    print(f"  County: {params.get('county', 'N/A')}")
    print(f"  Name 1: {params.get('name1', 'N/A')}")
    if not single_name_mode:
        print(f"  Name 2: {params.get('name2', 'N/A')}")
    print(f"  Date Range: {params.get('date_range', ['N/A', 'N/A'])}")
    print(f"  Party Type: {params.get('party_type', 'N/A')}")
    if params.get('address_filter'):
        print(f"  Address Filter: {params.get('address_filter')}")

    if single_name_mode:
        # Single name mode - show all documents
        all_docs = results.get("all_documents", [])
        print(f"\nResults Summary:")
        print(f"  Total documents found: {len(all_docs)}")

        if all_docs:
            print(f"\nDocuments Found:")
            print("-" * 70)
            for i, doc in enumerate(all_docs, 1):
                print(f"\n  {i}. Document Number: {doc.get('document_number', 'N/A')}")
                print(f"     Type: {doc.get('document_type', 'N/A')}")
                print(f"     Recording Date: {doc.get('recording_date', 'N/A')}")
                print(f"     Pages: {doc.get('pages', 'N/A')}")
                print(f"     Grantors: {doc.get('grantors', 'N/A')}")
                print(f"     Grantees: {doc.get('grantees', 'N/A')}")
        else:
            print("\n  No documents found.")
    else:
        # Two name mode - show common documents
        common_docs = results.get("common_documents", [])
        print(f"\nResults Summary:")
        print(f"  Documents common to both names: {summary.get('total_common', 0)}")
        print(f"  Documents only for Name 1: {summary.get('total_name1_only', 0)}")
        print(f"  Documents only for Name 2: {summary.get('total_name2_only', 0)}")

        if common_docs:
            print(f"\nCommon Documents (Joint Ownership):")
            print("-" * 70)
            for i, doc in enumerate(common_docs, 1):
                print(f"\n  {i}. Document Number: {doc.get('document_number', 'N/A')}")
                print(f"     Type: {doc.get('document_type', 'N/A')}")
                print(f"     Recording Date: {doc.get('recording_date', 'N/A')}")
                print(f"     Pages: {doc.get('pages', 'N/A')}")
                print(f"     Grantors: {doc.get('grantors', 'N/A')}")
                print(f"     Grantees: {doc.get('grantees', 'N/A')}")
        else:
            print("\n  No common documents found between the two names.")

    print("\n" + "=" * 70)


def main():
    """Main entry point."""
    args = parse_args()

    # Get the county recorder class
    RecorderClass = SUPPORTED_COUNTIES.get(args.county.lower())
    if not RecorderClass:
        print(f"Error: County '{args.county}' is not supported.")
        print(f"Supported counties: {', '.join(SUPPORTED_COUNTIES.keys())}")
        sys.exit(1)

    # Set end date to today if not provided
    end_date = args.end_date or datetime.now().strftime("%m/%d/%Y")

    # Determine if single name mode
    single_name_mode = args.name2 is None

    print("\n" + "=" * 70)
    print("CA RECORDER PROPERTY SEARCH")
    print("=" * 70)
    print(f"\nStarting search with parameters:")
    print(f"  Name 1: {args.name1}")
    if not single_name_mode:
        print(f"  Name 2: {args.name2}")
    else:
        print(f"  Mode: Single name search (all documents for this name)")
    print(f"  County: {args.county.title()}")
    print(f"  Date Range: {args.start_date} to {end_date}")
    print(f"  Party Type: {args.party_type}")
    if args.address:
        print(f"  Address Filter: {args.address}")

    try:
        # Create recorder instance and perform search
        with RecorderClass(start_date=args.start_date, end_date=end_date) as recorder:
            recorder.navigate_to_search()

            if single_name_mode:
                # Single name search - search as Grantor first, then as Grantee
                all_documents = {}  # Use dict to deduplicate by document number

                # Search 1: As Grantor
                print("\n--- Search 1: As Grantor ---")
                search_result1 = recorder.search_name(args.name1, "Grantor")
                for doc in search_result1.documents:
                    all_documents[doc.document_number] = doc
                print(f"  Found {len(search_result1.documents)} document(s) as Grantor")

                # Return to search for next query
                recorder.return_to_search()

                # Search 2: As Grantee
                print("\n--- Search 2: As Grantee ---")
                search_result2 = recorder.search_name(args.name1, "Grantee")
                for doc in search_result2.documents:
                    all_documents[doc.document_number] = doc
                print(f"  Found {len(search_result2.documents)} document(s) as Grantee")

                # Build results dictionary
                results = {
                    "search_params": {
                        "name1": args.name1,
                        "county": recorder.county_name,
                        "party_type": "Combined (Grantor + Grantee)",
                        "date_range": [args.start_date, end_date],
                        "address_filter": args.address,
                        "search_timestamp": datetime.now().isoformat()
                    },
                    "search_breakdown": {
                        "grantor_count": len(search_result1.documents),
                        "grantee_count": len(search_result2.documents),
                        "total_unique": len(all_documents)
                    },
                    "all_documents": [doc.to_dict() for doc in all_documents.values()]
                }

                print(f"\n  Combined: {len(all_documents)} unique document(s) from both searches")

                # Filter by address if provided
                if args.address:
                    address_lower = args.address.lower()
                    filtered_docs = []
                    for doc in results["all_documents"]:
                        # Check if address appears in grantors, grantees, or grantor_grantees fields
                        doc_text = f"{doc.get('grantors', '')} {doc.get('grantees', '')} {doc.get('grantor_grantees', '')}".lower()
                        if address_lower in doc_text:
                            filtered_docs.append(doc)

                    results["all_documents"] = filtered_docs
                    results["filter_applied"] = f"Address filter: {args.address}"
                    print(f"\n  Filtered to {len(filtered_docs)} documents matching address")
            else:
                # Two name search
                results = recorder.search_two_names(
                    args.name1,
                    args.name2,
                    party_type=args.party_type
                )

            # Print summary to console
            print_results_summary(results, single_name_mode=single_name_mode)

            # Export to JSON if output file specified
            if args.output:
                recorder.export_json(results, args.output)
                print(f"\nResults saved to: {args.output}")

    except KeyboardInterrupt:
        print("\n\nSearch cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during search: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nSearch completed successfully.")


if __name__ == "__main__":
    main()
