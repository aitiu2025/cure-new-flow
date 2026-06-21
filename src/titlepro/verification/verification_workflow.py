"""
Verification Workflow Integration Module for CURE Title Examination System

This module provides high-level functions to integrate property verification
and cross-reference checking into the multi-name workflow.

Key Functions:
- verify_documents_batch: Verify all documents match property
- run_full_verification: Complete verification with both property and cross-reference checks
- generate_verification_report: Generate comprehensive verification report
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from titlepro.verification.property_verifier import (
    PropertyVerifier,
    verify_single_document,
    verify_documents_batch,
    extract_apn_from_legal_description,
    validate_california_county,
    compare_legal_descriptions,
    log_info,
    log_debug,
    log_warning,
    log_error
)
from titlepro.verification.cross_reference_checker import (
    CrossReferenceChecker,
    check_documents_cross_reference,
    LienAttributionChecker,
    analyze_liens_for_owners
)

# Debug tag for workflow logs
DEBUG_TAG = "[PROPERTY_VERIFY_DEBUGLOGS]"


# Re-export verify_documents_batch from property_verifier for backward compatibility
# The function is already imported from property_verifier above


def run_verification_for_multi_name_workflow(
    workflow_result: Dict[str, Any],
    property_info: Dict[str, Any],
    skip_property_verification: bool = False,
    skip_cross_reference: bool = False,
    skip_lien_analysis: bool = False
) -> Dict[str, Any]:
    """
    Run complete verification suite for results from multi_name_workflow.

    This function is designed to integrate with MultiNameWorkflow and provides
    comprehensive verification including:
    - Property verification (all documents match target property)
    - Cross-reference checking (all owners appear on shared documents)
    - Lien attribution (liens properly attributed to owners)

    Args:
        workflow_result: Result dictionary from run_multi_name_search() or
                        MultiNameWorkflow.run() containing:
                        - documents: List of document analysis dicts
                        - initial_names: Original search names
                        - discovered_names: Names found from vesting deed
                        - vesting_deed: Vesting deed info (optional)

        property_info: Dictionary with target property details:
                      - address: Street address (required)
                      - city: City name (optional)
                      - county: County name (optional)
                      - apn: APN (optional but recommended)
                      - zip: ZIP code (optional)

        skip_property_verification: Skip property match verification
        skip_cross_reference: Skip cross-reference checking
        skip_lien_analysis: Skip lien attribution analysis

    Returns:
        Dictionary with complete verification results:
        {
            'verification_timestamp': ISO timestamp,
            'workflow_info': { initial_names, discovered_names, total_documents },
            'property_verification': { ... },
            'cross_reference': { ... },
            'lien_analysis': { ... },
            'overall_status': 'PASSED' | 'PARTIAL' | 'FAILED',
            'overall_message': 'Summary message',
            'summary': { combined statistics }
        }

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    log_info(f"{DEBUG_TAG} ============================================================")
    log_info(f"{DEBUG_TAG} STARTING MULTI-NAME WORKFLOW VERIFICATION")
    log_info(f"{DEBUG_TAG} ============================================================")

    # Extract data from workflow result
    documents = workflow_result.get("documents", workflow_result.get("all_documents", []))
    initial_names = workflow_result.get("initial_names", [])
    discovered_names = workflow_result.get("discovered_names", [])
    vesting_deed = workflow_result.get("vesting_deed")

    log_info(f"{DEBUG_TAG} Initial names: {initial_names}")
    log_info(f"{DEBUG_TAG} Discovered names: {discovered_names}")
    log_info(f"{DEBUG_TAG} Total documents: {len(documents)}")

    # Combine all owners
    all_owners = list(set(initial_names + discovered_names))

    # Try to extract more owners from vesting deed analysis if available
    if vesting_deed and isinstance(vesting_deed, dict):
        grantees = vesting_deed.get("grantees_structured", [])
        for grantee in grantees:
            if grantee.get("raw_name"):
                name = grantee["raw_name"].upper()
                if name not in all_owners:
                    all_owners.append(name)

    log_info(f"{DEBUG_TAG} Combined owners for verification: {all_owners}")

    results = {
        "verification_timestamp": datetime.now().isoformat(),
        "workflow_info": {
            "initial_names": initial_names,
            "discovered_names": discovered_names,
            "all_owners": all_owners,
            "total_documents": len(documents),
            "vesting_deed_available": vesting_deed is not None
        },
        "property_info": property_info
    }

    # Step 1: Property Verification
    if not skip_property_verification:
        log_info(f"{DEBUG_TAG} Step 1: Property Verification")
        property_results = verify_documents_batch(documents, property_info)
        results["property_verification"] = property_results
    else:
        log_info(f"{DEBUG_TAG} Step 1: Property Verification SKIPPED")
        results["property_verification"] = {"skipped": True}

    # Step 2: Cross-Reference Checking
    if not skip_cross_reference and len(all_owners) > 1:
        log_info(f"{DEBUG_TAG} Step 2: Cross-Reference Checking")
        cross_ref_results = check_documents_cross_reference(documents, all_owners)
        results["cross_reference"] = cross_ref_results
    else:
        reason = "skipped by request" if skip_cross_reference else "single owner or no owners"
        log_info(f"{DEBUG_TAG} Step 2: Cross-Reference Check SKIPPED ({reason})")
        results["cross_reference"] = {
            "skipped": True,
            "reason": reason,
            "issues_found": 0
        }

    # Step 3: Lien Attribution Analysis
    if not skip_lien_analysis:
        log_info(f"{DEBUG_TAG} Step 3: Lien Attribution Analysis")
        lien_results = analyze_liens_for_owners(documents, all_owners)
        results["lien_analysis"] = lien_results
    else:
        log_info(f"{DEBUG_TAG} Step 3: Lien Analysis SKIPPED")
        results["lien_analysis"] = {"skipped": True}

    # Step 4: Generate combined summary
    results["summary"] = _generate_workflow_summary(results)

    # Step 5: Determine overall status
    property_ok = results.get("property_verification", {}).get("all_verified", True)
    cross_ref_ok = results.get("cross_reference", {}).get("issues_found", 0) == 0
    lien_issues = results.get("lien_analysis", {}).get("summary", {}).get("open_liens", 0)

    if property_ok and cross_ref_ok:
        if lien_issues > 0:
            results["overall_status"] = "PARTIAL"
            results["overall_message"] = f"Verification passed but {lien_issues} open lien(s) found"
        else:
            results["overall_status"] = "PASSED"
            results["overall_message"] = "All verifications passed - no issues found"
    elif property_ok:
        results["overall_status"] = "PARTIAL"
        results["overall_message"] = "Property verification passed but cross-reference issues found"
    elif cross_ref_ok:
        results["overall_status"] = "PARTIAL"
        results["overall_message"] = "Cross-reference passed but property verification issues found"
    else:
        results["overall_status"] = "FAILED"
        results["overall_message"] = "Both property and cross-reference verification have issues"

    log_info(f"{DEBUG_TAG} Verification complete: {results['overall_status']}")
    log_info(f"{DEBUG_TAG} ============================================================")

    return results


def _generate_workflow_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate summary for multi-name workflow verification."""
    property_v = results.get("property_verification", {})
    cross_ref = results.get("cross_reference", {})
    lien_analysis = results.get("lien_analysis", {})

    summary = {
        "total_documents": results.get("workflow_info", {}).get("total_documents", 0),
        "total_owners": len(results.get("workflow_info", {}).get("all_owners", [])),
        "property_verified": property_v.get("verified_count", 0) if not property_v.get("skipped") else "N/A",
        "property_flagged": len(property_v.get("flagged_documents", [])) if not property_v.get("skipped") else "N/A",
        "cross_ref_issues": cross_ref.get("issues_found", 0) if not cross_ref.get("skipped") else "N/A",
        "total_liens": lien_analysis.get("total_liens", 0) if not lien_analysis.get("skipped") else "N/A",
        "open_liens": lien_analysis.get("summary", {}).get("open_liens", 0) if not lien_analysis.get("skipped") else "N/A",
        "average_confidence": property_v.get("confidence_average", 0) if not property_v.get("skipped") else "N/A"
    }

    # Collect all issues
    all_issues = []

    # Property verification issues
    if not property_v.get("skipped"):
        for flagged in property_v.get("flagged_documents", []):
            all_issues.append({
                "type": "property_mismatch",
                "severity": flagged.get("severity", "MEDIUM"),
                "document": flagged.get("document_file"),
                "message": "; ".join(flagged.get("issues", []))
            })

    # Cross-reference issues
    if not cross_ref.get("skipped"):
        for issue in cross_ref.get("issues", []):
            all_issues.append({
                "type": "cross_reference",
                "severity": issue.get("severity", "MEDIUM"),
                "document": issue.get("document_file"),
                "message": issue.get("message")
            })

    # Lien issues (open liens are flagged)
    if not lien_analysis.get("skipped"):
        for lien in lien_analysis.get("liens", []):
            if lien.get("status") == "OPEN":
                all_issues.append({
                    "type": "open_lien",
                    "severity": "MEDIUM",
                    "document": lien.get("document_file"),
                    "message": f"{lien.get('lien_type', 'Lien')}: {lien.get('amount', 'Amount unknown')} - {lien.get('creditor', 'Unknown creditor')}"
                })

    summary["all_issues"] = all_issues
    summary["total_issues"] = len(all_issues)
    summary["high_priority_issues"] = len([i for i in all_issues if i.get("severity") == "HIGH"])
    summary["medium_priority_issues"] = len([i for i in all_issues if i.get("severity") == "MEDIUM"])

    return summary


def run_full_verification(
    documents: List[Dict[str, Any]],
    property_info: Dict[str, Any],
    all_owners: Optional[List[str]] = None,
    include_lien_analysis: bool = True
) -> Dict[str, Any]:
    """
    Run complete verification including property matching, cross-reference checking,
    and lien attribution analysis.

    This is the main entry point for comprehensive document verification.

    Args:
        documents: List of document analysis dictionaries
        property_info: Dictionary with target property details
        all_owners: List of all property owner names (optional)
                   If not provided, attempts to extract from documents
        include_lien_analysis: Whether to include lien attribution analysis

    Returns:
        Dictionary with complete verification results

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    log_info(f"{DEBUG_TAG} ============================================================")
    log_info(f"{DEBUG_TAG} STARTING FULL VERIFICATION")
    log_info(f"{DEBUG_TAG} ============================================================")

    results = {
        "verification_timestamp": datetime.now().isoformat(),
        "property_info": property_info,
        "total_documents": len(documents)
    }

    # Step 1: Property verification
    log_info(f"{DEBUG_TAG} Step 1: Property Verification")
    property_results = verify_documents_batch(documents, property_info)
    results["property_verification"] = property_results

    # Step 2: Extract owners if not provided
    if not all_owners:
        all_owners = _extract_owners_from_documents(documents, property_info)
        log_info(f"{DEBUG_TAG} Extracted {len(all_owners)} owners from documents: {all_owners}")

    results["owners"] = all_owners

    # Step 3: Cross-reference checking (only if we have multiple owners)
    if all_owners and len(all_owners) > 1:
        log_info(f"{DEBUG_TAG} Step 2: Cross-Reference Checking")
        cross_ref_results = check_documents_cross_reference(documents, all_owners)
        results["cross_reference"] = cross_ref_results
    else:
        log_info(f"{DEBUG_TAG} Step 2: Cross-Reference Check SKIPPED (single owner or no owners found)")
        results["cross_reference"] = {
            "skipped": True,
            "reason": "Single owner or no owners found",
            "issues_found": 0
        }

    # Step 4: Lien Attribution Analysis (if requested)
    if include_lien_analysis and all_owners:
        log_info(f"{DEBUG_TAG} Step 3: Lien Attribution Analysis")
        lien_results = analyze_liens_for_owners(documents, all_owners)
        results["lien_analysis"] = lien_results
    else:
        log_info(f"{DEBUG_TAG} Step 3: Lien Analysis SKIPPED")
        results["lien_analysis"] = {
            "skipped": True,
            "reason": "Not requested or no owners found"
        }

    # Step 5: Generate combined summary
    results["summary"] = _generate_combined_summary(results)

    # Step 6: Generate overall status
    property_ok = property_results.get("all_verified", False)
    cross_ref_ok = results["cross_reference"].get("issues_found", 0) == 0
    lien_issues = results.get("lien_analysis", {}).get("summary", {}).get("open_liens", 0)

    if property_ok and cross_ref_ok:
        if lien_issues > 0:
            results["overall_status"] = "PARTIAL"
            results["overall_message"] = f"All documents verified but {lien_issues} open lien(s) require attention"
        else:
            results["overall_status"] = "PASSED"
            results["overall_message"] = "All documents verified and cross-references confirmed"
    elif property_ok:
        results["overall_status"] = "PARTIAL"
        results["overall_message"] = "Property verification passed but cross-reference issues found"
    elif cross_ref_ok:
        results["overall_status"] = "PARTIAL"
        results["overall_message"] = "Cross-reference passed but property verification issues found"
    else:
        results["overall_status"] = "FAILED"
        results["overall_message"] = "Both property and cross-reference verification have issues"

    log_info(f"{DEBUG_TAG} Full verification complete: {results['overall_status']}")
    log_info(f"{DEBUG_TAG} ============================================================")

    return results


def _extract_owners_from_documents(
    documents: List[Dict[str, Any]],
    property_info: Dict[str, Any]
) -> List[str]:
    """
    Extract owner names from documents (typically from most recent grant deed).

    Looks for grantee names in grant deeds, which represent current owners.
    """
    log_debug("Extracting owners from documents...")

    # Look for grant deeds first (most reliable source)
    grant_deeds = [
        d for d in documents
        if "GRANT DEED" in d.get("document_type", "").upper()
    ]

    # Sort by recording date if available (most recent first)
    def get_date(doc):
        date_str = doc.get("recording_date", "")
        try:
            return datetime.strptime(date_str, "%m/%d/%Y")
        except (ValueError, TypeError):
            return datetime.min

    grant_deeds.sort(key=get_date, reverse=True)

    # Get grantees from most recent grant deed
    if grant_deeds:
        grantee = grant_deeds[0].get("grantee", "")
        if grantee:
            # Parse multiple names
            from titlepro.verification.cross_reference_checker import CrossReferenceChecker
            names = CrossReferenceChecker._extract_names(grantee)
            if names:
                log_debug(f"Found owners from grant deed: {names}")
                return names

    # Fallback: check property_info for owner field
    if property_info.get("owner") or property_info.get("owners"):
        owner_field = property_info.get("owner") or property_info.get("owners")
        if isinstance(owner_field, list):
            return owner_field
        if isinstance(owner_field, str):
            from titlepro.verification.cross_reference_checker import CrossReferenceChecker
            return CrossReferenceChecker._extract_names(owner_field)

    log_warning("Could not extract owners from documents or property_info")
    return []


def _generate_combined_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a combined summary of all verification results."""
    property_v = results.get("property_verification", {})
    cross_ref = results.get("cross_reference", {})
    lien_analysis = results.get("lien_analysis", {})

    summary = {
        "total_documents": results.get("total_documents", 0),
        "property_verified": property_v.get("verified_count", 0) if not property_v.get("skipped") else "N/A",
        "property_flagged": len(property_v.get("flagged_documents", [])) if not property_v.get("skipped") else "N/A",
        "cross_ref_issues": cross_ref.get("issues_found", 0) if not cross_ref.get("skipped") else "N/A",
        "owners_checked": len(results.get("owners", [])),
        "average_confidence": property_v.get("confidence_average", 0) if not property_v.get("skipped") else "N/A",
        "total_liens": lien_analysis.get("total_liens", 0) if not lien_analysis.get("skipped") else "N/A",
        "open_liens": lien_analysis.get("summary", {}).get("open_liens", 0) if not lien_analysis.get("skipped") else "N/A",
        "unattributed_liens": len(lien_analysis.get("unattributed_liens", [])) if not lien_analysis.get("skipped") else "N/A"
    }

    # Count issues by severity across all checks
    all_issues = []

    # Property verification issues
    if not property_v.get("skipped"):
        for flagged in property_v.get("flagged_documents", []):
            all_issues.append({
                "type": "property_mismatch",
                "severity": flagged.get("severity", "MEDIUM"),
                "document": flagged.get("document_file"),
                "message": "; ".join(flagged.get("issues", []))
            })

    # Cross-reference issues
    if not cross_ref.get("skipped"):
        for issue in cross_ref.get("issues", []):
            all_issues.append({
                "type": "cross_reference",
                "severity": issue.get("severity", "MEDIUM"),
                "document": issue.get("document_file"),
                "message": issue.get("message")
            })

    # Lien issues (open liens are flagged as medium priority, unattributed as high)
    if not lien_analysis.get("skipped"):
        # Open liens
        for lien in lien_analysis.get("liens", []):
            if lien.get("status") == "OPEN":
                all_issues.append({
                    "type": "open_lien",
                    "severity": "MEDIUM",
                    "document": lien.get("document_file"),
                    "message": f"{lien.get('lien_type', 'Lien')}: {lien.get('amount', 'Amount unknown')} owed to {lien.get('creditor', 'Unknown')}"
                })

        # Unattributed liens (higher priority - need review)
        for lien in lien_analysis.get("unattributed_liens", []):
            all_issues.append({
                "type": "unattributed_lien",
                "severity": "HIGH",
                "document": lien.get("document_file"),
                "message": f"Unattributed {lien.get('lien_type', 'lien')}: Debtor '{lien.get('debtor')}' does not match any known owner"
            })

    summary["all_issues"] = all_issues
    summary["total_issues"] = len(all_issues)
    summary["high_priority_issues"] = len([i for i in all_issues if i.get("severity") == "HIGH"])
    summary["medium_priority_issues"] = len([i for i in all_issues if i.get("severity") == "MEDIUM"])

    return summary


def generate_verification_report(
    verification_results: Dict[str, Any],
    output_format: str = "markdown"
) -> str:
    """
    Generate a formatted verification report.

    Args:
        verification_results: Results from run_full_verification
        output_format: 'markdown' or 'text'

    Returns:
        Formatted report string
    """
    if output_format == "markdown":
        return _generate_markdown_report(verification_results)
    else:
        return _generate_text_report(verification_results)


def _generate_markdown_report(results: Dict[str, Any]) -> str:
    """Generate markdown-formatted verification report."""
    timestamp = results.get("verification_timestamp", datetime.now().isoformat())
    property_info = results.get("property_info", {})
    summary = results.get("summary", {})

    status = results.get("overall_status", "UNKNOWN")
    status_icon = "OK" if status == "PASSED" else "!!" if status == "PARTIAL" else "!!!"

    # Handle N/A values for display
    def format_val(val):
        if val == "N/A" or val is None:
            return "N/A"
        if isinstance(val, float):
            return f"{val:.1%}"
        return str(val)

    report = f"""# Document Verification Report

**Generated:** {timestamp}
**Status:** {status_icon} **{status}**
**Property:** {property_info.get('address', 'Unknown')}

---

## Summary

| Metric | Value |
|--------|-------|
| Total Documents | {summary.get('total_documents', 0)} |
| Property Verified | {format_val(summary.get('property_verified'))} |
| Property Flagged | {format_val(summary.get('property_flagged'))} |
| Cross-Ref Issues | {format_val(summary.get('cross_ref_issues'))} |
| Total Liens | {format_val(summary.get('total_liens'))} |
| Open Liens | {format_val(summary.get('open_liens'))} |
| Average Confidence | {format_val(summary.get('average_confidence'))} |
| Total Issues | {summary.get('total_issues', 0)} |

"""

    # Property Verification Section
    property_v = results.get("property_verification", {})

    if property_v.get("skipped"):
        report += f"""---

## Property Verification

*Skipped: {property_v.get('reason', 'Not requested')}*

"""
    else:
        report += """---

## Property Verification

"""

        if property_v.get("all_verified"):
            report += "All documents verified to match the target property.\n\n"
        else:
            flagged = property_v.get("flagged_documents", [])
            if flagged:
                report += f"**{len(flagged)} document(s) flagged for review:**\n\n"
                for doc in flagged:
                    severity_icon = "!!!" if doc.get("severity") == "HIGH" else "!!"
                    report += f"### {severity_icon} {doc.get('document_file', 'Unknown')}\n\n"
                    report += f"- **Type:** {doc.get('document_type', 'Unknown')}\n"
                    report += f"- **Confidence:** {doc.get('confidence', 0):.1%}\n"
                    report += f"- **Severity:** {doc.get('severity', 'Unknown')}\n"
                    if doc.get("issues"):
                        report += "- **Issues:**\n"
                        for issue in doc["issues"]:
                            report += f"  - {issue}\n"
                    report += "\n"

    # Cross-Reference Section
    cross_ref = results.get("cross_reference", {})

    if cross_ref.get("skipped"):
        report += f"""---

## Cross-Reference Verification

*Skipped: {cross_ref.get('reason', 'Unknown reason')}*

"""
    elif cross_ref.get("report_section"):
        report += f"""---

{cross_ref['report_section']}
"""
    else:
        report += """---

## Cross-Reference Verification

No cross-reference issues found.

"""

    # Lien Analysis Section
    lien_analysis = results.get("lien_analysis", {})

    if lien_analysis.get("skipped"):
        report += f"""---

## Lien Analysis

*Skipped: {lien_analysis.get('reason', 'Not requested')}*

"""
    elif lien_analysis.get("report_section"):
        report += f"""---

{lien_analysis['report_section']}
"""
    else:
        lien_summary = lien_analysis.get("summary", {})
        total_liens = lien_summary.get("total_liens", 0)
        open_liens = lien_summary.get("open_liens", 0)

        report += """---

## Lien Analysis

"""

        if total_liens == 0:
            report += "No liens found affecting the property.\n\n"
        else:
            report += f"**{total_liens} lien(s) found, {open_liens} open:**\n\n"

            # Group by owner
            liens_by_owner = lien_analysis.get("liens_by_owner", {})
            for owner, liens in liens_by_owner.items():
                report += f"### {owner.title()}\n\n"
                if not liens:
                    report += "- No liens\n\n"
                else:
                    for lien in liens:
                        status_str = "OPEN" if lien.get("status") == "OPEN" else "Released"
                        report += f"- **{lien.get('lien_type', 'Lien')}** ({status_str})\n"
                        if lien.get("amount"):
                            report += f"  - Amount: {lien['amount']}\n"
                        report += f"  - Creditor: {lien.get('creditor', 'Unknown')}\n"
                        if lien.get("case_number"):
                            report += f"  - Case #: {lien['case_number']}\n"
                        report += "\n"

            # Unattributed liens
            unattributed = lien_analysis.get("unattributed_liens", [])
            if unattributed:
                report += "### Unattributed Liens (Require Review)\n\n"
                for lien in unattributed:
                    report += f"- **{lien.get('lien_type', 'Lien')}**: Debtor '{lien.get('debtor')}'\n"

    # Recommendations
    all_issues = summary.get("all_issues", [])
    high_priority = [i for i in all_issues if i.get("severity") == "HIGH"]

    if high_priority:
        report += """---

## Recommendations

**HIGH PRIORITY actions required:**

"""
        for i, issue in enumerate(high_priority, 1):
            report += f"{i}. Review **{issue.get('document', 'Unknown')}** - {issue.get('message', 'Issue detected')}\n"

        report += "\nPlease verify these documents manually before proceeding with the title examination.\n"
    else:
        medium_issues = [i for i in all_issues if i.get("severity") == "MEDIUM"]
        if medium_issues:
            report += """---

## Recommendations

**MEDIUM PRIORITY items to review:**

"""
            for i, issue in enumerate(medium_issues[:5], 1):  # Show top 5
                report += f"{i}. {issue.get('type', 'Issue').replace('_', ' ').title()}: {issue.get('message', 'Review needed')}\n"

            if len(medium_issues) > 5:
                report += f"\n*...and {len(medium_issues) - 5} more medium-priority items*\n"
        else:
            report += """---

## Recommendations

No high-priority issues detected. Standard review procedures apply.

"""

    report += f"""
---

*Report generated by CURE Title Examination System*
*{timestamp}*
"""

    return report


def _generate_text_report(results: Dict[str, Any]) -> str:
    """Generate plain text verification report."""
    lines = []
    lines.append("=" * 60)
    lines.append("DOCUMENT VERIFICATION REPORT")
    lines.append("=" * 60)

    timestamp = results.get("verification_timestamp", "Unknown")
    status = results.get("overall_status", "UNKNOWN")

    lines.append(f"Generated: {timestamp}")
    lines.append(f"Status: {status}")
    lines.append(f"Property: {results.get('property_info', {}).get('address', 'Unknown')}")
    lines.append("")

    summary = results.get("summary", {})
    lines.append("-" * 40)
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total Documents: {summary.get('total_documents', 0)}")
    lines.append(f"  Property Verified: {summary.get('property_verified', 0)}")
    lines.append(f"  Issues Found: {summary.get('total_issues', 0)}")
    lines.append(f"  High Priority: {summary.get('high_priority_issues', 0)}")
    lines.append("")

    property_v = results.get("property_verification", {})
    flagged = property_v.get("flagged_documents", [])

    if flagged:
        lines.append("-" * 40)
        lines.append("FLAGGED DOCUMENTS")
        lines.append("-" * 40)
        for doc in flagged:
            lines.append(f"  [{doc.get('severity', '?')}] {doc.get('document_file', 'Unknown')}")
            for issue in doc.get("issues", []):
                lines.append(f"      - {issue}")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


def save_verification_results(
    results: Dict[str, Any],
    output_dir: Path,
    base_name: str = "verification_results"
) -> Dict[str, Path]:
    """
    Save verification results to files.

    Args:
        results: Results from run_full_verification
        output_dir: Directory to save files
        base_name: Base name for output files

    Returns:
        Dictionary mapping file type to path
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files = {}

    # Save JSON results
    json_path = output_dir / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    saved_files["json"] = json_path
    log_info(f"Saved JSON results to: {json_path}")

    # Save markdown report
    md_path = output_dir / f"{base_name}.md"
    md_content = generate_verification_report(results, "markdown")
    md_path.write_text(md_content)
    saved_files["markdown"] = md_path
    log_info(f"Saved markdown report to: {md_path}")

    # Save text report
    txt_path = output_dir / f"{base_name}.txt"
    txt_content = generate_verification_report(results, "text")
    txt_path.write_text(txt_content)
    saved_files["text"] = txt_path
    log_info(f"Saved text report to: {txt_path}")

    return saved_files


if __name__ == "__main__":
    # Test the workflow integration
    print("=" * 60)
    print("Verification Workflow Integration Test")
    print("=" * 60)

    # Sample property info
    property_info = {
        "address": "123 Main Street",
        "city": "Irvine",
        "county": "Orange",
        "apn": "123-456-78",
        "zip": "92614"
    }

    # Sample documents (simulating pdf_analyzer output)
    sample_documents = [
        {
            "_source_file": "grant_deed_2020.pdf",
            "document_type": "GRANT DEED",
            "instrument_number": "2020000123456",
            "recording_date": "01/15/2020",
            "property_address": "123 Main St, Irvine, CA 92614",
            "apn": "123-456-78",
            "grantor": "JOHN DOE AND JANE DOE, HUSBAND AND WIFE",
            "grantee": "JOHN SMITH AND MARY SMITH, HUSBAND AND WIFE AS JOINT TENANTS"
        },
        {
            "_source_file": "deed_of_trust_2020.pdf",
            "document_type": "DEED OF TRUST",
            "instrument_number": "2020000123457",
            "recording_date": "01/15/2020",
            "property_address": "123 Main Street, Irvine CA 92614",
            "apn": "123-456-78",
            "grantor": "JOHN SMITH",  # Missing Mary Smith!
            "loan_amount": "$500,000.00",
            "lender": "ABC BANK"
        },
        {
            "_source_file": "reconveyance_2023.pdf",
            "document_type": "FULL RECONVEYANCE",
            "instrument_number": "2023000654321",
            "recording_date": "06/01/2023",
            "property_address": "123 Main St",
            "grantor": "FIRST AMERICAN TITLE AS TRUSTEE"
        },
        {
            "_source_file": "judgment_lien_2024.pdf",
            "document_type": "ABSTRACT OF JUDGMENT",
            "instrument_number": "2024000789012",
            "recording_date": "03/15/2024",
            "is_lien_document": True,
            "lien_type": "JUDGMENT",
            "debtor": "JOHN SMITH",
            "creditor": "ABC COLLECTIONS INC",
            "lien_amount": "$15,000.00",
            "case_number": "30-2023-CV-12345",
            "court_name": "ORANGE COUNTY SUPERIOR COURT"
        }
    ]

    # Test batch verification
    print("\n--- Testing Batch Verification ---")
    batch_results = verify_documents_batch(sample_documents, property_info)
    print(f"Summary: {batch_results['summary']}")
    print(f"Average Confidence: {batch_results['confidence_average']:.2%}")
    print(f"Flagged: {len(batch_results['flagged_documents'])}")

    # Test full verification with lien analysis
    print("\n--- Testing Full Verification with Lien Analysis ---")
    full_results = run_full_verification(
        sample_documents,
        property_info,
        all_owners=["JOHN SMITH", "MARY SMITH"],
        include_lien_analysis=True
    )
    print(f"Overall Status: {full_results['overall_status']}")
    print(f"Overall Message: {full_results['overall_message']}")

    # Print lien analysis summary
    lien_summary = full_results.get("lien_analysis", {}).get("summary", {})
    print(f"Liens Found: {lien_summary.get('total_liens', 0)}")
    print(f"Open Liens: {lien_summary.get('open_liens', 0)}")

    # Test multi-name workflow verification
    print("\n--- Testing Multi-Name Workflow Verification ---")
    mock_workflow_result = {
        "documents": sample_documents,
        "initial_names": ["SMITH JOHN"],
        "discovered_names": ["SMITH MARY"],
        "vesting_deed": {
            "document_number": "2020000123456",
            "grantees_structured": [
                {"raw_name": "JOHN SMITH", "type": "individual"},
                {"raw_name": "MARY SMITH", "type": "individual"}
            ]
        }
    }

    workflow_results = run_verification_for_multi_name_workflow(
        mock_workflow_result,
        property_info
    )
    print(f"Workflow Verification Status: {workflow_results['overall_status']}")
    print(f"Summary: {workflow_results['summary']}")

    # Generate report
    print("\n--- Generated Report ---")
    report = generate_verification_report(full_results, "markdown")
    print(report)

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
