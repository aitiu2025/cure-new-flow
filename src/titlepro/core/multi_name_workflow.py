"""
Multi-Name Workflow Orchestrator for CURE System

This module orchestrates the multi-name discovery and search workflow:
1. Initial search with provided names
2. Finding the current vesting deed (most recent grant deed where name is grantee)
3. Downloading and analyzing the vesting deed
4. Extracting all grantees
5. Identifying NEW names to search (not in original input)
6. Automatically searching each discovered name
7. Handling trust names (search both trustee AND trust name)
8. Returning combined results

Priority 1 - CRITICAL for CURE system multi-name workflow.

Usage:
    from multi_name_workflow import MultiNameWorkflow

    workflow = MultiNameWorkflow(county="orange")
    results = await workflow.run(
        owner_names=["Smith John", "Smith Jane"],
        start_date="01/01/2000",
        end_date="01/28/2026"
    )
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("multi_name_workflow")
logger.setLevel(logging.DEBUG)

# BASE_DIR for download base path compatibility
BASE_DIR = Path(__file__).resolve().parent
from titlepro import DOWNLOAD_DIR

# Import dependencies
try:
    from titlepro.core.pdf_analyzer import analyze_pdf, pdf_to_images, analyze_document_with_claude
    PDF_ANALYZER_AVAILABLE = True
except ImportError as e:
    PDF_ANALYZER_AVAILABLE = False
    logger.warning(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] pdf_analyzer not available: {e}")

try:
    from titlepro.search.recorder.utils import (
        parse_owner_names,
        parse_trust_name,
        extract_all_grantees_from_analysis,
        get_new_names_to_search,
        build_search_strategy,
        filter_documents_by_first_names,
        extract_surname
    )
    UTILS_AVAILABLE = True
except ImportError as e:
    UTILS_AVAILABLE = False
    logger.warning(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] utils not available: {e}")

try:
    from titlepro.search.recorder.counties.registry import get_recorder, get_supported_counties
    RECORDER_AVAILABLE = True
except ImportError as e:
    RECORDER_AVAILABLE = False
    logger.warning(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] county recorder not available: {e}")

try:
    from titlepro.download.selenium_downloader import download_document, DOWNLOAD_DIRNAME
    DOWNLOADER_AVAILABLE = True
except ImportError as e:
    DOWNLOADER_AVAILABLE = False
    DOWNLOAD_DIRNAME = "downloaded_doc"
    logger.warning(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] titlepro_selenium_downloader not available: {e}")

# Constants
DOWNLOAD_BASE = DOWNLOAD_DIR
GRANT_DEED_TYPES = ["GRANT DEED", "WARRANTY DEED", "QUITCLAIM DEED", "DEED"]


@dataclass
class SearchResult:
    """Result from a single name search."""
    name: str
    documents: List[Dict[str, Any]] = field(default_factory=list)
    search_type: str = "initial"  # "initial" or "discovered"
    source_name: Optional[str] = None  # Name that led to discovery
    error: Optional[str] = None


@dataclass
class VestingDeed:
    """Information about a vesting deed."""
    document_number: str
    document_type: str
    recording_date: str
    year: str
    grantors: str
    grantees_raw: str
    grantees_structured: List[Dict[str, Any]] = field(default_factory=list)
    filename: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowResult:
    """Complete result from multi-name workflow."""
    success: bool
    initial_names: List[str]
    discovered_names: List[str]
    all_documents: List[Dict[str, Any]]
    vesting_deed: Optional[VestingDeed]
    search_results: List[SearchResult]
    error: Optional[str] = None
    county: str = "orange"
    start_date: str = ""
    end_date: str = ""
    workflow_log: List[str] = field(default_factory=list)


class MultiNameWorkflow:
    """
    Orchestrates the multi-name discovery and search workflow.

    This class handles the complete flow of:
    1. Searching county recorder with initial names
    2. Identifying the vesting deed (most recent grant deed)
    3. Downloading and analyzing the vesting deed
    4. Discovering additional grantees from the deed
    5. Recursively searching discovered names
    6. Combining all results

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """

    def __init__(
        self,
        county: str = "orange",
        download_base: Optional[Path] = None,
        max_recursion_depth: int = 2
    ):
        """
        Initialize the multi-name workflow.

        Args:
            county: County identifier (default: "orange")
            download_base: Base directory for downloads (optional)
            max_recursion_depth: Maximum depth for recursive name discovery
        """
        self.county = county.lower()
        self.download_base = download_base or DOWNLOAD_BASE
        self.max_recursion_depth = max_recursion_depth

        self._searched_names: Set[str] = set()
        self._all_documents: Dict[str, Dict] = {}  # Keyed by document number
        self._search_results: List[SearchResult] = []
        self._workflow_log: List[str] = []

        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Initialized MultiNameWorkflow for county: {county}")
        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Download base: {self.download_base}")

        # Verify dependencies
        self._verify_dependencies()

    def _verify_dependencies(self):
        """Verify all required dependencies are available."""
        missing = []
        if not PDF_ANALYZER_AVAILABLE:
            missing.append("pdf_analyzer")
        if not UTILS_AVAILABLE:
            missing.append("utils")
        if not RECORDER_AVAILABLE:
            missing.append("county_recorder")
        if not DOWNLOADER_AVAILABLE:
            missing.append("titlepro_selenium_downloader")

        if missing:
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] WARNING: Missing dependencies: {missing}")

    def _log(self, message: str):
        """Log a message and add to workflow log."""
        logger.debug(message)
        self._workflow_log.append(f"[{datetime.now().isoformat()}] {message}")

    def run(
        self,
        owner_names: List[str],
        start_date: str = "01/01/2000",
        end_date: Optional[str] = None,
        download_vesting_deed: bool = True,
        analyze_vesting_deed: bool = True
    ) -> WorkflowResult:
        """
        Run the complete multi-name workflow.

        Args:
            owner_names: List of owner names in "Last First" format
            start_date: Start date for search (MM/DD/YYYY)
            end_date: End date for search (MM/DD/YYYY), defaults to today
            download_vesting_deed: Whether to download the vesting deed
            analyze_vesting_deed: Whether to analyze the vesting deed with Claude

        Returns:
            WorkflowResult with all search results and discovered names
        """
        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Starting workflow with names: {owner_names}")

        if not end_date:
            end_date = datetime.now().strftime("%m/%d/%Y")

        # Reset state
        self._searched_names = set()
        self._all_documents = {}
        self._search_results = []

        # Parse owner names
        parsed_names = []
        for name in owner_names:
            if UTILS_AVAILABLE:
                parsed = parse_owner_names(name)
                parsed_names.extend(parsed)
            else:
                parsed_names.append(name)

        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Parsed names: {parsed_names}")

        # Step 1: Initial search with provided names
        try:
            self._search_names(parsed_names, start_date, end_date, search_type="initial")
        except Exception as e:
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Error in initial search: {e}")
            return WorkflowResult(
                success=False,
                initial_names=parsed_names,
                discovered_names=[],
                all_documents=list(self._all_documents.values()),
                vesting_deed=None,
                search_results=self._search_results,
                error=str(e),
                county=self.county,
                start_date=start_date,
                end_date=end_date,
                workflow_log=self._workflow_log
            )

        # Step 2: Find the vesting deed
        vesting_deed = self._find_vesting_deed(parsed_names)
        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found vesting deed: {vesting_deed.document_number if vesting_deed else 'None'}")

        # Step 3: Download and analyze vesting deed
        discovered_names = []
        if vesting_deed and download_vesting_deed:
            try:
                vesting_deed = self._download_vesting_deed(vesting_deed, owner_names[0])

                if analyze_vesting_deed and vesting_deed.filename:
                    vesting_deed = self._analyze_vesting_deed(vesting_deed, owner_names[0])

                    # Step 4: Extract grantees and find new names
                    if vesting_deed.analysis and UTILS_AVAILABLE:
                        grantees = extract_all_grantees_from_analysis(vesting_deed.analysis)
                        vesting_deed.grantees_structured = grantees
                        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Extracted {len(grantees)} grantees from analysis")

                        # Get new names to search
                        new_grantees = get_new_names_to_search(grantees, list(self._searched_names))
                        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found {len(new_grantees)} new names to search")

                        # Step 5: Search discovered names
                        for grantee in new_grantees:
                            for search_name in grantee.get("search_names", []):
                                if search_name not in self._searched_names:
                                    discovered_names.append(search_name)
                                    self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Will search discovered name: {search_name}")

                        # Search discovered names
                        if discovered_names:
                            self._search_names(
                                discovered_names,
                                start_date,
                                end_date,
                                search_type="discovered",
                                source_name=vesting_deed.document_number
                            )

            except Exception as e:
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Error processing vesting deed: {e}")

        return WorkflowResult(
            success=True,
            initial_names=parsed_names,
            discovered_names=discovered_names,
            all_documents=list(self._all_documents.values()),
            vesting_deed=vesting_deed,
            search_results=self._search_results,
            county=self.county,
            start_date=start_date,
            end_date=end_date,
            workflow_log=self._workflow_log
        )

    def _search_names(
        self,
        names: List[str],
        start_date: str,
        end_date: str,
        search_type: str = "initial",
        source_name: Optional[str] = None,
        depth: int = 0
    ):
        """
        Search the county recorder for a list of names.

        [MULTI_NAME_WORKFLOW_DEBUGLOGS]
        """
        if depth > self.max_recursion_depth:
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Max recursion depth reached, stopping")
            return

        if not RECORDER_AVAILABLE:
            self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] Recorder not available, skipping search")
            return

        for name in names:
            normalized = name.upper().strip()
            if normalized in self._searched_names:
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Skipping already-searched name: {name}")
                continue

            self._searched_names.add(normalized)
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Searching for: {name}")

            try:
                recorder = get_recorder(self.county, start_date=start_date, end_date=end_date)

                with recorder:
                    recorder.navigate_to_search()
                    documents = []

                    # Search in all modes
                    for party_type in ["All", "Grantor", "Grantee"]:
                        recorder.set_partial_match(True)
                        result = recorder.search_name(name, party_type)

                        for doc in result.documents:
                            if doc.document_number:
                                doc_dict = doc.to_dict()
                                if doc.document_number not in self._all_documents:
                                    self._all_documents[doc.document_number] = doc_dict
                                documents.append(doc_dict)

                        recorder.return_to_search()

                search_result = SearchResult(
                    name=name,
                    documents=documents,
                    search_type=search_type,
                    source_name=source_name
                )
                self._search_results.append(search_result)
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found {len(documents)} documents for {name}")

            except Exception as e:
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Error searching for {name}: {e}")
                self._search_results.append(SearchResult(
                    name=name,
                    documents=[],
                    search_type=search_type,
                    source_name=source_name,
                    error=str(e)
                ))

    def _find_vesting_deed(self, owner_names: List[str]) -> Optional[VestingDeed]:
        """
        Find the vesting deed (most recent grant deed where name is grantee).

        [MULTI_NAME_WORKFLOW_DEBUGLOGS]
        """
        self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] Finding vesting deed...")

        # Normalize names for comparison
        normalized_names = [name.upper() for name in owner_names]

        # Filter for grant deeds where owner is grantee
        grant_deeds = []
        for doc_num, doc in self._all_documents.items():
            doc_type = (doc.get("document_type") or "").upper()

            # Check if it's a grant deed type
            is_grant_deed = any(gd in doc_type for gd in GRANT_DEED_TYPES)
            if not is_grant_deed:
                continue

            # Check if owner is grantee
            grantees = (doc.get("grantees") or doc.get("grantor_grantees") or "").upper()
            is_grantee = any(name in grantees for name in normalized_names)

            if is_grantee:
                grant_deeds.append(doc)
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found grant deed: {doc_num} - {doc.get('recording_date')}")

        if not grant_deeds:
            self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] No grant deeds found where owner is grantee")
            return None

        # Sort by recording date (most recent first)
        def parse_date(doc):
            date_str = doc.get("recording_date", "")
            try:
                return datetime.strptime(date_str, "%m/%d/%Y")
            except:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except:
                    return datetime.min

        grant_deeds.sort(key=parse_date, reverse=True)

        # Return the most recent
        most_recent = grant_deeds[0]
        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Most recent vesting deed: {most_recent.get('document_number')}")

        # Extract year from document number or date
        doc_num = most_recent.get("document_number", "")
        year = ""
        if doc_num:
            # Try to extract year from document number (often YYYY-NNNNNN format)
            import re
            year_match = re.match(r'^(\d{4})', doc_num)
            if year_match:
                year = year_match.group(1)
            else:
                # Try from recording date
                date_str = most_recent.get("recording_date", "")
                try:
                    parsed = parse_date(most_recent)
                    year = str(parsed.year)
                except:
                    year = ""

        return VestingDeed(
            document_number=doc_num,
            document_type=most_recent.get("document_type", ""),
            recording_date=most_recent.get("recording_date", ""),
            year=year,
            grantors=most_recent.get("grantors", ""),
            grantees_raw=most_recent.get("grantees") or most_recent.get("grantor_grantees", "")
        )

    def _download_vesting_deed(self, vesting_deed: VestingDeed, owner_name: str) -> VestingDeed:
        """
        Download the vesting deed PDF.

        [MULTI_NAME_WORKFLOW_DEBUGLOGS]
        """
        if not DOWNLOADER_AVAILABLE:
            self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] Downloader not available")
            return vesting_deed

        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Downloading vesting deed: {vesting_deed.document_number}")

        try:
            result = download_document(
                doc_num=vesting_deed.document_number,
                year=vesting_deed.year,
                headless=True,
                owner_name=owner_name,
                county=self.county
            )

            if result.get("status") == "success" and result.get("files"):
                vesting_deed.filename = result["files"][0]
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Downloaded to: {vesting_deed.filename}")
            else:
                self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Download failed: {result.get('message')}")

        except Exception as e:
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Download error: {e}")

        return vesting_deed

    def _analyze_vesting_deed(self, vesting_deed: VestingDeed, owner_name: str) -> VestingDeed:
        """
        Analyze the vesting deed PDF with Claude.

        [MULTI_NAME_WORKFLOW_DEBUGLOGS]
        """
        if not PDF_ANALYZER_AVAILABLE:
            self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] PDF analyzer not available")
            return vesting_deed

        if not vesting_deed.filename:
            self._log("[MULTI_NAME_WORKFLOW_DEBUGLOGS] No filename to analyze")
            return vesting_deed

        # Build full path
        safe_owner = owner_name.replace(" ", "_").replace(",", "")
        folder_path = self.download_base / safe_owner
        pdf_path = folder_path / vesting_deed.filename

        if not pdf_path.exists():
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] PDF not found: {pdf_path}")
            return vesting_deed

        self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Analyzing PDF: {pdf_path}")

        try:
            analysis = analyze_pdf(
                pdf_path,
                document_type=vesting_deed.document_type,
                instrument_number=vesting_deed.document_number
            )
            vesting_deed.analysis = analysis
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Analysis complete, grantee: {analysis.get('grantee', '')[:50]}...")

        except Exception as e:
            self._log(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Analysis error: {e}")

        return vesting_deed

    def get_combined_documents(self) -> List[Dict[str, Any]]:
        """Get all unique documents from all searches."""
        return list(self._all_documents.values())

    def get_workflow_log(self) -> List[str]:
        """Get the workflow execution log."""
        return self._workflow_log.copy()


# Convenience function for simple usage
def run_multi_name_search(
    owner_names: List[str],
    county: str = "orange",
    start_date: str = "01/01/2000",
    end_date: Optional[str] = None,
    download_vesting: bool = True,
    analyze_vesting: bool = True
) -> Dict[str, Any]:
    """
    Run the multi-name workflow and return results as a dictionary.

    This is a convenience function for simple usage from other modules.

    Args:
        owner_names: List of owner names
        county: County identifier
        start_date: Start date (MM/DD/YYYY)
        end_date: End date (MM/DD/YYYY)
        download_vesting: Download the vesting deed
        analyze_vesting: Analyze the vesting deed

    Returns:
        Dictionary with workflow results

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    workflow = MultiNameWorkflow(county=county)
    result = workflow.run(
        owner_names=owner_names,
        start_date=start_date,
        end_date=end_date,
        download_vesting_deed=download_vesting,
        analyze_vesting_deed=analyze_vesting
    )

    return {
        "success": result.success,
        "initial_names": result.initial_names,
        "discovered_names": result.discovered_names,
        "total_documents": len(result.all_documents),
        "documents": result.all_documents,
        "vesting_deed": {
            "document_number": result.vesting_deed.document_number,
            "document_type": result.vesting_deed.document_type,
            "recording_date": result.vesting_deed.recording_date,
            "grantees_raw": result.vesting_deed.grantees_raw,
            "grantees_structured": result.vesting_deed.grantees_structured,
            "filename": result.vesting_deed.filename
        } if result.vesting_deed else None,
        "search_results": [
            {
                "name": sr.name,
                "document_count": len(sr.documents),
                "search_type": sr.search_type,
                "source_name": sr.source_name,
                "error": sr.error
            }
            for sr in result.search_results
        ],
        "county": result.county,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "error": result.error,
        "workflow_log": result.workflow_log
    }


if __name__ == "__main__":
    """Command-line interface for testing the multi-name workflow."""
    import argparse

    parser = argparse.ArgumentParser(description="Run multi-name search workflow")
    parser.add_argument("names", nargs="+", help="Owner names in 'Last First' format")
    parser.add_argument("--county", default="orange", help="County (default: orange)")
    parser.add_argument("--start-date", default="01/01/2000", help="Start date MM/DD/YYYY")
    parser.add_argument("--end-date", default=None, help="End date MM/DD/YYYY")
    parser.add_argument("--no-download", action="store_true", help="Skip downloading vesting deed")
    parser.add_argument("--no-analyze", action="store_true", help="Skip analyzing vesting deed")
    parser.add_argument("--output", "-o", help="Output JSON file")

    args = parser.parse_args()

    print("=" * 60)
    print("CURE Multi-Name Workflow")
    print("=" * 60)
    print(f"Names: {args.names}")
    print(f"County: {args.county}")
    print(f"Date range: {args.start_date} - {args.end_date or 'today'}")
    print("")

    result = run_multi_name_search(
        owner_names=args.names,
        county=args.county,
        start_date=args.start_date,
        end_date=args.end_date,
        download_vesting=not args.no_download,
        analyze_vesting=not args.no_analyze
    )

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Success: {result['success']}")
    print(f"Initial names: {result['initial_names']}")
    print(f"Discovered names: {result['discovered_names']}")
    print(f"Total documents: {result['total_documents']}")

    if result['vesting_deed']:
        print(f"\nVesting Deed:")
        print(f"  Document: {result['vesting_deed']['document_number']}")
        print(f"  Type: {result['vesting_deed']['document_type']}")
        print(f"  Date: {result['vesting_deed']['recording_date']}")
        print(f"  Grantees: {result['vesting_deed']['grantees_raw'][:80]}...")

    if result['error']:
        print(f"\nError: {result['error']}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to: {args.output}")
