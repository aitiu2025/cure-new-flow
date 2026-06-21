"""
Report Generator for RAW Two Owner Search Exam

This module generates detailed property reports from:
1. Downloaded PDF documents from TitlePro
2. Document metadata
3. Property/owner information

The report follows the RAW TWO OWNER SEARCH EXAM format.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Try to import tax lookup
try:
    from titlepro.tax.tax_lookup import get_tax_info_for_report
    TAX_LOOKUP_AVAILABLE = True
except ImportError:
    TAX_LOOKUP_AVAILABLE = False
    get_tax_info_for_report = None

# Base paths
BASE_DIR = Path(__file__).resolve().parent
from titlepro import DOWNLOAD_DIR


def load_metadata(folder_path: Path) -> Dict:
    """Load document metadata from folder."""
    metadata_path = folder_path / "document_metadata.json"
    if metadata_path.exists():
        return json.loads(metadata_path.read_text())
    return {}


def load_documents_found(folder_path: Path) -> List[Dict]:
    """Load documents_found.json if available."""
    docs_path = folder_path / "documents_found.json"
    if docs_path.exists():
        return json.loads(docs_path.read_text())
    return []


def load_existing_report(folder_path: Path) -> Optional[Dict]:
    """Load existing FINAL_REPORT.json if available."""
    report_path = folder_path / "FINAL_REPORT.json"
    if report_path.exists():
        return json.loads(report_path.read_text())
    return None


def load_existing_markdown(folder_path: Path) -> Optional[str]:
    """Load existing RAW_TWO_OWNER_SEARCH_EXAM.md if available."""
    md_path = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
    if md_path.exists():
        return md_path.read_text()
    return None


def get_pdf_files(folder_path: Path) -> List[Path]:
    """Get all PDF files in folder."""
    return sorted(folder_path.glob("*.pdf"))


def generate_report_from_data(
    owner_name: str,
    property_address: str,
    metadata: Dict,
    documents_found: List[Dict],
    pdf_files: List[Path]
) -> Dict:
    """
    Generate a report structure from available data.

    This creates the FINAL_REPORT.json structure.
    For full AI-powered extraction, this would need to analyze PDF contents.
    """
    report = {
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "property": {
            "address": property_address,
            "county": "Orange",
        },
        "current_owners": {
            "names": owner_name.replace("_", " ").upper(),
        },
        "documents_downloaded": [],
        "documents_metadata": metadata,
        "source_files": [f.name for f in pdf_files]
    }

    # Add document info from metadata
    for inst_num, meta in metadata.items():
        report["documents_downloaded"].append({
            "instrument_number": inst_num,
            "filename": meta.get("filename"),
            "year": meta.get("year"),
            "type": meta.get("type", "DOCUMENT"),
            "downloaded_at": meta.get("downloaded_at")
        })

    return report


def generate_markdown_report(
    owner_name: str,
    property_address: str,
    metadata: Dict,
    report_data: Optional[Dict] = None
) -> str:
    """
    Generate a markdown report.

    If report_data (FINAL_REPORT.json) exists, use it for detailed info.
    Otherwise, generate a basic report from metadata.
    """
    today = datetime.now().strftime("%B %d, %Y")
    clean_owner = owner_name.replace("_", " ").upper()

    # If we have full report data, use it
    if report_data and "property" in report_data:
        return generate_full_markdown_from_json(report_data)

    # Otherwise generate basic report from metadata
    md = f"""# RAW TWO OWNER SEARCH EXAM

**Order Number:** Not Provided
**Subject Property:** {property_address}
**Effective Date:** {today}
**County:** Orange

---

## PROPERTY AND OWNERSHIP INFORMATION

| Field | Value |
|-------|-------|
| Owner(s) | {clean_owner} |
| Street Address | {property_address} |
| County | Orange |

---

## DOCUMENTS DOWNLOADED FROM TITLEPRO

The following documents have been downloaded and are available for review:

| Instrument # | Type | Year | Filename |
|--------------|------|------|----------|
"""

    for inst_num, meta in sorted(metadata.items(), key=lambda x: x[1].get('year', '0000'), reverse=True):
        doc_type = meta.get('type', 'DOCUMENT')
        year = meta.get('year', 'N/A')
        filename = meta.get('filename', 'N/A')
        md += f"| {inst_num} | {doc_type} | {year} | {filename} |\n"

    md += f"""
---

## NEXT STEPS

To complete this report, the downloaded PDF documents need to be analyzed to extract:

1. **Legal Description** - From the Grant Deed or Deed of Trust
2. **Deed Chain** - Complete chain of title with grantors/grantees
3. **Tax Information** - Current property tax status
4. **Mortgages/Deeds of Trust** - Open and closed encumbrances
5. **Judgments, Liens, UCCs** - Any recorded liens

---

## DISCLAIMER

This report is for informational purposes only and does not guarantee title. This is not a commitment to insure title. The information contained herein has been obtained from public records and is believed to be accurate but is not warranted.

---

*Report Generated: {today}*
*County Searched: Orange County, California*
"""

    return md


def format_owner_names(names) -> str:
    """Format owner names - handle list or string."""
    if isinstance(names, list):
        return '; '.join(names)
    return names or 'N/A'


def generate_vesting_section(deed_analysis: Dict, all_grantees: List[Dict]) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Generate the Title Vested As section.

    Output format:
    **TITLE VESTED AS:** John Smith AND Mary Smith, Husband and Wife

    Or for trusts:
    **TITLE VESTED AS:** Smith Family Trust

    Args:
        deed_analysis: Dictionary containing current_owners info with names and vesting
        all_grantees: List of grantee dictionaries from deed chain

    Returns:
        Formatted string for Title Vested As section
    """
    print("[REPORT_FORMAT_DEBUGLOGS] generate_vesting_section called")

    owners = deed_analysis.get('current_owners', {})
    owner_names = owners.get('names', '')
    vesting = owners.get('vesting', '')

    print(f"[REPORT_FORMAT_DEBUGLOGS] owner_names: {owner_names}, vesting: {vesting}")

    # Handle list of names
    if isinstance(owner_names, list):
        owner_names = ' AND '.join(owner_names)

    if not owner_names:
        # Try to get from most recent grantee in deed chain
        if all_grantees:
            latest_grantee = all_grantees[0] if isinstance(all_grantees, list) else all_grantees
            if isinstance(latest_grantee, dict):
                owner_names = latest_grantee.get('grantee', 'N/A')
            else:
                owner_names = str(latest_grantee)
        else:
            owner_names = 'N/A'

    # Determine vesting type and format appropriately
    vesting_display = _format_vesting_type(owner_names, vesting)

    print(f"[REPORT_FORMAT_DEBUGLOGS] vesting_display: {vesting_display}")

    return vesting_display


def _format_vesting_type(names: str, vesting: str) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Format the vesting type based on ownership pattern.

    Args:
        names: Owner name(s) as string
        vesting: Vesting type description

    Returns:
        Formatted vesting string
    """
    print(f"[REPORT_FORMAT_DEBUGLOGS] _format_vesting_type: names={names}, vesting={vesting}")

    if not names or names == 'N/A':
        return 'N/A'

    names_upper = names.upper()
    vesting_upper = (vesting or '').upper()

    # Check for Trust ownership
    if 'TRUST' in names_upper or 'TRUSTEE' in names_upper:
        return names

    # Check for various vesting patterns
    if vesting:
        # Husband and Wife patterns
        if 'HUSBAND AND WIFE' in vesting_upper or 'H/W' in vesting_upper:
            if 'JOINT TENANT' in vesting_upper:
                return f"{names}, Husband and Wife as Joint Tenants"
            elif 'COMMUNITY PROPERTY' in vesting_upper:
                if 'SURVIVORSHIP' in vesting_upper:
                    return f"{names}, Husband and Wife as Community Property with Right of Survivorship"
                return f"{names}, Husband and Wife as Community Property"
            return f"{names}, Husband and Wife"

        # Joint Tenants (non-spousal)
        if 'JOINT TENANT' in vesting_upper:
            return f"{names}, as Joint Tenants with Right of Survivorship"

        # Tenants in Common
        if 'TENANT' in vesting_upper and 'COMMON' in vesting_upper:
            return f"{names}, as Tenants in Common"

        # Single individual indicators
        if 'SINGLE' in vesting_upper or 'UNMARRIED' in vesting_upper:
            return f"{names}, a Single Person"

        # If vesting is provided but doesn't match patterns, use as-is
        return f"{names}, {vesting}"

    # No vesting information - return names only
    # Try to detect patterns from names
    if ' AND ' in names_upper:
        # Multiple people, unknown vesting
        return names

    # Single owner, unknown vesting
    return names


def extract_parties_from_liens(liens_data: str, mortgages: List[Dict]) -> Dict[str, List[Dict]]:
    """
    [REPORT_FORMAT_DEBUGLOGS] Extract and group liens/encumbrances by party.

    Args:
        liens_data: String or dict containing liens/judgments information
        mortgages: List of mortgage/deed of trust records

    Returns:
        Dictionary mapping party names to their liens
    """
    print(f"[REPORT_FORMAT_DEBUGLOGS] extract_parties_from_liens called")

    parties = {}

    # Extract parties from mortgages/deeds of trust
    for mortgage in (mortgages or []):
        trustor = mortgage.get('trustor', '')
        if trustor:
            # Parse multiple trustors (split by AND)
            trustor_names = [n.strip() for n in trustor.upper().split(' AND ') if n.strip()]
            for name in trustor_names:
                # Clean up the name (remove vesting info)
                clean_name = _extract_individual_name(name)
                if clean_name and clean_name not in parties:
                    parties[clean_name] = []

    print(f"[REPORT_FORMAT_DEBUGLOGS] Parties extracted: {list(parties.keys())}")
    return parties


def _extract_individual_name(full_name: str) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Extract individual name from full vesting string.

    Args:
        full_name: Full name possibly with vesting info

    Returns:
        Cleaned individual name
    """
    if not full_name:
        return ''

    # Remove common vesting phrases
    name = full_name.upper()
    for phrase in [', HUSBAND AND WIFE', ', AS JOINT TENANTS',
                   'AS JOINT TENANTS', 'HUSBAND AND WIFE',
                   ', A SINGLE PERSON', 'A SINGLE PERSON',
                   ', TRUSTEE', 'TRUSTEE', ', AS TRUSTEES', 'AS TRUSTEES']:
        name = name.replace(phrase, '')

    return name.strip().strip(',').strip()


def generate_documents_examined_section(
    documents_examined: List[Dict],
    search_summary: Dict = None
) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Generate the Documents Examined section with deduplication notation.

    Args:
        documents_examined: List of document dictionaries with found_via info
        search_summary: Optional search summary with name-to-document mappings

    Returns:
        Formatted markdown for Documents Examined section

    Output format:
    ## DOCUMENTS EXAMINED

    | Doc # | Type | Date | Found Via |
    |-------|------|------|-----------|
    | 2023-0003138 | Grant Deed | 06/08/2023 | John Smith, Mary Smith |
    | 2024-0001234 | Judgment Lien | 06/15/2024 | Mary Smith |
    """
    print("[REPORT_FORMAT_DEBUGLOGS] generate_documents_examined_section called")
    print(f"[REPORT_FORMAT_DEBUGLOGS] documents_examined count: {len(documents_examined) if documents_examined else 0}")

    if not documents_examined:
        return ""

    md = "---\n\n## DOCUMENTS EXAMINED\n\n"
    md += "| Doc # | Type | Date | Found Via |\n"
    md += "|-------|------|------|----------|\n"

    for doc in documents_examined:
        doc_num = doc.get('document_number', doc.get('instrument_number', 'N/A'))
        doc_type = doc.get('type', doc.get('document_type', 'DOCUMENT'))
        doc_date = doc.get('date', doc.get('recording_date', 'N/A'))

        # Found Via - which names led to discovering this document
        found_via = doc.get('found_via', [])
        if isinstance(found_via, list):
            found_via_str = ', '.join(found_via) if found_via else 'N/A'
        else:
            found_via_str = str(found_via) if found_via else 'N/A'

        md += f"| {doc_num} | {doc_type} | {doc_date} | {found_via_str} |\n"

    md += "\n"
    return md


def generate_search_summary_section(search_summary: Dict) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Generate the Search Summary section showing workflow transparency.

    Args:
        search_summary: Dictionary containing search workflow data

    Returns:
        Formatted markdown for Search Summary section

    Output format:
    ## SEARCH SUMMARY

    **Original Search Names:** John Smith
    **Names Discovered from Vesting Deed:** Mary Smith
    **Total Names Searched:** 2

    **Documents by Search:**
    - John Smith: 7 documents found
    - Mary Smith: 8 documents found (3 unique, 5 overlap)
    - Total Unique Documents: 10
    """
    print("[REPORT_FORMAT_DEBUGLOGS] generate_search_summary_section called")
    print(f"[REPORT_FORMAT_DEBUGLOGS] search_summary: {search_summary}")

    if not search_summary:
        return ""

    md = "---\n\n## SEARCH SUMMARY\n\n"

    # Original search names
    original_names = search_summary.get('original_search_names', [])
    if isinstance(original_names, list):
        original_str = ', '.join(original_names) if original_names else 'N/A'
    else:
        original_str = str(original_names) if original_names else 'N/A'
    md += f"**Original Search Names:** {original_str}\n\n"

    # Discovered names from vesting deed
    discovered_names = search_summary.get('discovered_names', [])
    if isinstance(discovered_names, list):
        discovered_str = ', '.join(discovered_names) if discovered_names else 'None'
    else:
        discovered_str = str(discovered_names) if discovered_names else 'None'

    if discovered_names:
        md += f"**Names Discovered from Vesting Deed:** {discovered_str}\n\n"

    # Total names searched
    total_names = search_summary.get('total_names_searched', 0)
    if not total_names:
        # Calculate from original + discovered
        if isinstance(original_names, list):
            total_names = len(original_names)
        else:
            total_names = 1 if original_names else 0
        if isinstance(discovered_names, list):
            total_names += len(discovered_names)
        elif discovered_names:
            total_names += 1

    md += f"**Total Names Searched:** {total_names}\n\n"

    # Documents by search
    docs_by_search = search_summary.get('documents_by_search', {})
    if docs_by_search:
        md += "**Documents by Search:**\n\n"
        for name, stats in docs_by_search.items():
            if isinstance(stats, dict):
                total = stats.get('total', 0)
                unique = stats.get('unique', total)
                overlap = stats.get('overlap', 0)
                if overlap > 0:
                    md += f"- {name}: {total} documents found ({unique} unique, {overlap} overlap)\n"
                else:
                    md += f"- {name}: {total} documents found\n"
            else:
                # Simple count
                md += f"- {name}: {stats} documents found\n"

        # Total unique documents
        total_unique = search_summary.get('total_unique_documents', 0)
        if total_unique:
            md += f"- **Total Unique Documents:** {total_unique}\n"

        md += "\n"

    return md


def generate_liens_section_by_party(
    liens_data,
    owners: Dict,
    mortgages: List[Dict],
    judgments: List[Dict] = None
) -> str:
    """
    [REPORT_FORMAT_DEBUGLOGS] Generate the liens/encumbrances section grouped by party.

    Args:
        liens_data: String or list containing liens/judgments information
        owners: Current owners dictionary
        mortgages: List of mortgage/deed of trust records
        judgments: Optional list of judgment lien records

    Returns:
        Formatted markdown string for liens section

    Output format:
    ## LIENS & ENCUMBRANCES

    ### John Smith
    - No liens found

    ### Mary Smith
    - **Judgment Lien:** $50,000, Doc# 2024-0001234, Recorded 06/15/2024
      - Creditor: ABC Collections
      - Status: OPEN
    """
    print("[REPORT_FORMAT_DEBUGLOGS] generate_liens_section_by_party called")

    md = "---\n\n## LIENS & ENCUMBRANCES\n\n"

    # Extract all party names from owners
    owner_names = owners.get('names', '')
    if isinstance(owner_names, list):
        parties = owner_names
    elif owner_names:
        # Split by AND to get individual parties
        parties = [n.strip() for n in owner_names.upper().split(' AND ') if n.strip()]
    else:
        parties = []

    # Clean up party names (remove vesting info)
    clean_parties = []
    for p in parties:
        clean_name = _extract_individual_name(p)
        if clean_name:
            clean_parties.append(clean_name)

    print(f"[REPORT_FORMAT_DEBUGLOGS] Parties for liens section: {clean_parties}")

    if not clean_parties:
        # Fallback if no parties extracted
        if isinstance(liens_data, str) and liens_data:
            md += f"{liens_data}\n\n"
        else:
            md += "No party information available to group liens.\n\n"
        return md

    # Parse judgments if provided as structured data
    party_liens = {party: [] for party in clean_parties}

    # If judgments is a list of structured data, process it
    if judgments and isinstance(judgments, list):
        for judgment in judgments:
            # Try to match judgment to a party
            debtor = judgment.get('debtor', '').upper()
            for party in clean_parties:
                if party in debtor or debtor in party:
                    party_liens[party].append(judgment)
                    break
            else:
                # If no specific party match, add to first party
                if clean_parties:
                    party_liens[clean_parties[0]].append(judgment)

    # Generate section for each party
    for party in clean_parties:
        md += f"### {party.title()}\n\n"

        liens = party_liens.get(party, [])
        if not liens:
            # Check if liens_data string mentions this party
            if isinstance(liens_data, str):
                if 'NO JUDGMENT' in liens_data.upper() or 'NO LIEN' in liens_data.upper() or 'NONE' in liens_data.upper():
                    md += "- No liens found\n\n"
                elif liens_data.strip():
                    # General lien info exists, include it
                    md += f"- {liens_data}\n\n"
                else:
                    md += "- No liens found\n\n"
            else:
                md += "- No liens found\n\n"
        else:
            for lien in liens:
                lien_type = lien.get('type', 'Lien')
                amount = lien.get('amount', 'N/A')
                doc_num = lien.get('document_number', lien.get('instrument_number', 'N/A'))
                recorded = lien.get('recording_date', 'N/A')
                creditor = lien.get('creditor', '')
                status = lien.get('status', 'OPEN')

                # Format with CSS class for styling
                status_class = 'lien-open' if 'OPEN' in status.upper() else 'lien-released'
                md += f"- **{lien_type}:** {amount}, Doc# {doc_num}, Recorded {recorded}\n"
                if creditor:
                    md += f"  - Creditor: {creditor}\n"
                md += f"  - Status: **{status}**\n\n"

    return md


def format_legal_description(legal_desc) -> str:
    """Format legal description - handle dict or string."""
    if not legal_desc:
        return "Legal description to be extracted from deed documents."

    if isinstance(legal_desc, str):
        return legal_desc

    if isinstance(legal_desc, dict):
        parts = []

        # Summary first
        if legal_desc.get('summary'):
            parts.append(f"**Summary:** {legal_desc['summary']}")

        # Full description with parcels
        full_desc = legal_desc.get('full_description')
        if full_desc:
            if isinstance(full_desc, dict):
                for key in sorted(full_desc.keys()):
                    parcel_name = key.replace('_', ' ').upper()
                    parts.append(f"**{parcel_name}:** {full_desc[key]}")
            else:
                parts.append(str(full_desc))

        # Mineral exception
        if legal_desc.get('mineral_exception'):
            parts.append(f"**MINERAL EXCEPTION:** {legal_desc['mineral_exception']}")

        return '\n\n'.join(parts)

    return str(legal_desc)


def generate_full_markdown_from_json(report_data: Dict) -> str:
    """Generate full markdown report from FINAL_REPORT.json structure."""
    print("[REPORT_FORMAT_DEBUGLOGS] generate_full_markdown_from_json called")

    today = report_data.get("report_date", datetime.now().strftime("%Y-%m-%d"))
    prop = report_data.get("property", {})
    owners = report_data.get("current_owners", {})
    tax = report_data.get("tax_information", {})
    deed_chain = report_data.get("deed_chain", [])
    mortgages = report_data.get("mortgages_and_deeds_of_trust", [])
    reconveyances = report_data.get("reconveyances", [])
    other_docs = report_data.get("other_documents", [])
    issues = report_data.get("critical_issues", [])
    notes = report_data.get("notes", [])
    liens_text = report_data.get("judgments_liens_ucc", "")

    # Search summary data (for discovered names section)
    search_summary = report_data.get("search_summary", {})
    documents_examined = report_data.get("documents_examined", [])

    address = f"{prop.get('address', '')}, {prop.get('city', '')}, {prop.get('state', '')} {prop.get('zip', '')}"

    # Format owner names properly (handle list)
    owner_names = format_owner_names(owners.get('names'))

    # Generate Title Vested As section
    vesting_display = generate_vesting_section(report_data, deed_chain)

    print(f"[REPORT_FORMAT_DEBUGLOGS] vesting_display for report: {vesting_display}")

    md = f"""# RAW TWO OWNER SEARCH EXAM

**Order Number:** Not Provided
**Subject Property:** {address.strip(', ')}
**Effective Date:** {today}
**County:** {prop.get('county', 'Orange')}

---

## TITLE VESTED AS

**{vesting_display}**

---

## PROPERTY AND OWNERSHIP INFORMATION

| Field | Value |
|-------|-------|
| Owner(s) | {owner_names} |
| Vesting | {owners.get('vesting', 'N/A')} |
| Street Address | {prop.get('address', 'N/A')} |
| City/State/ZIP | {prop.get('city', '')}, {prop.get('state', '')} {prop.get('zip', '')} |
| APN/Parcel | {prop.get('apn', 'N/A')} |
| County | {prop.get('county', 'Orange')} |
"""

    if prop.get('planned_unit_development'):
        md += f"| Planned Unit Development | {prop['planned_unit_development']} |\n"

    md += "\n---\n\n## LEGAL DESCRIPTION\n\n"

    legal_desc = prop.get('legal_description')
    if legal_desc:
        # Handle nested legal description structure
        if isinstance(legal_desc, dict):
            # Summary first
            if legal_desc.get('summary'):
                md += f"**Summary:** {legal_desc['summary']}\n\n"

            # Full description with parcels
            full_desc = legal_desc.get('full_description')
            if full_desc:
                if isinstance(full_desc, dict):
                    # Iterate through parcels
                    for key in sorted(full_desc.keys()):
                        parcel_name = key.replace('_', ' ').upper()
                        md += f"**{parcel_name}:** {full_desc[key]}\n\n"
                else:
                    md += f"{full_desc}\n\n"

            # Mineral exception
            if legal_desc.get('mineral_exception'):
                md += f"**MINERAL EXCEPTION:** {legal_desc['mineral_exception']}\n\n"
        else:
            # Simple string format
            md += f"{legal_desc}\n\n"

        if prop.get('legal_description_source'):
            md += f"*Legal description derived from {prop['legal_description_source']}*\n"
    else:
        md += "Legal description to be extracted from deed documents.\n"

    md += "\n---\n\n## DEED CHAIN\n\n"

    for deed in deed_chain:
        md += f"""### {deed.get('document_type', 'Deed')}

| Field | Value |
|-------|-------|
| Instrument Type | {deed.get('document_type', 'N/A')} |
| Date Recorded | {deed.get('recording_date', 'N/A')} |
| Instrument Number | {deed.get('instrument_number', 'N/A')} |
| Grantor(s) | {deed.get('grantor', 'N/A')} |
| Grantee(s) | {deed.get('grantee', 'N/A')} |

"""

    if tax:
        md += """---

## TAX INFORMATION

| Field | Value |
|-------|-------|
"""
        # Support both old and new tax field formats
        md += f"| Tax Year | {tax.get('tax_year', 'N/A')} |\n"
        md += f"| APN | {tax.get('apn', 'N/A')} |\n"

        # Annual tax amount
        annual_tax = tax.get('annual_tax_estimated') or tax.get('annual_tax')
        if annual_tax and annual_tax != 'N/A':
            md += f"| Annual Tax | {annual_tax} |\n"

        # Installment amounts and status
        first_amt = tax.get('first_installment_amount')
        first_status = tax.get('first_installment_status')
        second_amt = tax.get('second_installment_amount')
        second_status = tax.get('second_installment_status')

        if first_amt or first_status:
            first_display = first_amt or ''
            if first_status:
                first_display = f"{first_display} ({first_status})" if first_display else first_status
            md += f"| 1st Installment | {first_display} |\n"

        if second_amt or second_status:
            second_display = second_amt or ''
            if second_status:
                second_display = f"{second_display} ({second_status})" if second_display else second_status
            md += f"| 2nd Installment | {second_display} |\n"

        # Due dates
        first_due = tax.get('first_installment_due')
        second_due = tax.get('second_installment_due')
        if first_due and first_due != 'N/A':
            md += f"| 1st Installment Due | {first_due} |\n"
        if second_due and second_due != 'N/A':
            md += f"| 2nd Installment Due | {second_due} |\n"

        # Additional tax fields
        if tax.get('tax_status'):
            md += f"| Tax Status | {tax['tax_status']} |\n"
        if tax.get('exemptions_noted'):
            md += f"| Exemptions | {tax['exemptions_noted']} |\n"
        if tax.get('supplemental_taxes'):
            md += f"| Supplemental Taxes | {tax['supplemental_taxes']} |\n"

        # Verification link
        verification_url = tax.get('verification_url')
        if verification_url:
            md += f"\n*Verify tax amounts at: {verification_url}*\n"

        md += "\n"

    if mortgages:
        md += "---\n\n## MORTGAGES AND DEEDS OF TRUST\n\n"
        for mort in mortgages:
            status_label = "OPEN ENCUMBRANCE" if "OPEN" in mort.get('status', '') else "RELEASED"
            md += f"""### **{status_label} - {mort.get('document_type', 'DEED OF TRUST')}**

| Field | Value |
|-------|-------|
| Instrument Type | {mort.get('document_type', 'N/A')} |
| Date Recorded | {mort.get('recording_date', 'N/A')} |
| Instrument Number | {mort.get('instrument_number', 'N/A')} |
| Original Amount | **{mort.get('original_amount', 'N/A')}** |
| Trustor(s) | {mort.get('trustor', 'N/A')} |
| Lender | {mort.get('lender', 'N/A')} |
| **Status** | **{mort.get('status', 'N/A')}** |

"""

    # Liens and Judgments - Now grouped by party
    judgments_list = report_data.get("judgments", [])  # Structured judgment data if available

    # Use the new party-grouped liens section
    liens_section = generate_liens_section_by_party(
        liens_data=liens_text,
        owners=owners,
        mortgages=mortgages,
        judgments=judgments_list
    )
    md += liens_section

    # Other documents
    if other_docs:
        md += "---\n\n## OTHER DOCUMENTS\n\n"
        for doc in other_docs:
            md += f"- **{doc.get('instrument_number', 'N/A')}** - {doc.get('document_type', 'DOCUMENT')} "
            md += f"(Recorded: {doc.get('recording_date', 'N/A')})"
            if doc.get('notes'):
                md += f" - {doc['notes']}"
            md += "\n"
        md += "\n"

    if issues:
        md += "---\n\n## CRITICAL ISSUES AND FLAGS\n\n"
        for i, issue in enumerate(issues, 1):
            severity = issue.get('severity', 'MEDIUM')
            severity_icon = "!!!" if severity == "HIGH" else "!!" if severity == "MEDIUM" else "!"
            md += f"### {severity_icon} {i}. {issue.get('issue', 'Issue')} - {severity} PRIORITY\n\n"
            md += f"{issue.get('description', '')}\n\n"

    if notes:
        md += "---\n\n## NOTES\n\n"
        for i, note in enumerate(notes, 1):
            md += f"{i}. {note}\n\n"

    # Documents Examined section with deduplication notation (Task 5.3)
    if documents_examined:
        docs_section = generate_documents_examined_section(documents_examined, search_summary)
        md += docs_section

    # Search Summary section showing workflow transparency (Task 5.4)
    if search_summary:
        summary_section = generate_search_summary_section(search_summary)
        md += summary_section

    md += f"""---

## DISCLAIMER

This report is for informational purposes only and does not guarantee title. This is not a commitment to insure title. The information contained herein has been obtained from public records and is believed to be accurate but is not warranted. Liability is limited to the fee paid for this report.

---

*Report Generated: {today}*
*County Searched: Orange County, California*
"""

    return md


def enrich_tax_information(report_data: Dict, force_lookup: bool = False) -> Dict:
    """
    Enrich tax information in the report by looking up from OC Treasurer.

    Only performs lookup if:
    - force_lookup is True, OR
    - tax_information is missing key fields like tax_year or annual_tax_estimated
    """
    tax_info = report_data.get("tax_information", {})
    apn = tax_info.get("apn") or report_data.get("property", {}).get("apn")

    if not apn:
        return report_data

    # Check if we need to enrich
    needs_enrichment = force_lookup or not tax_info.get("tax_year") or tax_info.get("tax_year") == "N/A"

    if needs_enrichment and TAX_LOOKUP_AVAILABLE and get_tax_info_for_report:
        try:
            print(f"Attempting to fetch tax info for APN: {apn}")
            fetched_tax = get_tax_info_for_report(apn)

            # Merge fetched data with existing (fetched takes precedence for missing fields)
            for key, value in fetched_tax.items():
                if value and (not tax_info.get(key) or tax_info.get(key) == "N/A"):
                    tax_info[key] = value

            report_data["tax_information"] = tax_info
        except Exception as e:
            print(f"Tax lookup failed: {e}")

    return report_data


def load_tax_file(folder_path: Path) -> Optional[Dict]:
    """
    Load tax data from a tax_*.json file in the owner folder.
    These files are created by the /tax-lookup endpoint.
    Returns the tax_information dict if found, or None.
    """
    tax_files = list(folder_path.glob("tax_*.json"))
    if not tax_files:
        return None
    # Use the most recently modified tax file
    tax_file = max(tax_files, key=lambda p: p.stat().st_mtime)
    try:
        data = json.loads(tax_file.read_text())
        tax_info = data.get("tax_information", {})
        if tax_info:
            print(f"Loaded tax data from {tax_file.name}")
            return tax_info
    except (json.JSONDecodeError, Exception) as e:
        print(f"Warning: Could not read tax file {tax_file}: {e}")
    return None


def generate_report_for_owner(owner_name: str, property_address: str = "", force_regenerate: bool = False, fetch_tax: bool = False) -> Dict:
    """
    Main function to generate a report for an owner.

    Returns dict with:
    - success: bool
    - report_json: dict (FINAL_REPORT.json content)
    - report_markdown: str (RAW_TWO_OWNER_SEARCH_EXAM.md content)
    - folder_path: str

    Args:
        owner_name: Owner name (folder name)
        property_address: Property address for basic report
        force_regenerate: Force regeneration even if report exists
        fetch_tax: Attempt to fetch tax info from OC Treasurer website
    """
    safe_owner = owner_name.replace(" ", "_").replace(",", "")
    folder_path = DOWNLOAD_DIR / safe_owner

    if not folder_path.exists():
        return {
            "success": False,
            "error": f"Folder not found: {folder_path}",
            "folder_path": str(folder_path)
        }

    # Load existing data
    metadata = load_metadata(folder_path)
    documents_found = load_documents_found(folder_path)
    existing_report = load_existing_report(folder_path)
    pdf_files = get_pdf_files(folder_path)

    # Check if existing report is detailed (has deed_chain or full property info)
    has_detailed_report = existing_report and (
        existing_report.get("deed_chain") or
        existing_report.get("property", {}).get("legal_description") or
        existing_report.get("mortgages_and_deeds_of_trust")
    )

    # If we have a detailed report, always regenerate markdown from it
    if has_detailed_report:
        # Load tax data from tax_*.json file if available (created by /tax-lookup endpoint)
        tax_file_data = load_tax_file(folder_path)
        if tax_file_data:
            tax_info = existing_report.get("tax_information", {})
            # These fields should always be overwritten by fresh tax lookup data
            priority_fields = [
                "tax_year", "annual_tax_estimated", "first_installment_amount",
                "first_installment_status", "second_installment_amount",
                "second_installment_status", "verification_url", "data_source",
                "delinquent", "assessed_value_land", "assessed_value_improvements",
                "assessed_value_total"
            ]
            for key, value in tax_file_data.items():
                if key in priority_fields and value:
                    # Always overwrite priority fields with fresh data
                    tax_info[key] = value
                elif value and (not tax_info.get(key) or tax_info.get(key) in ("", "N/A")):
                    # For other fields, only fill in if missing
                    tax_info[key] = value
            existing_report["tax_information"] = tax_info
            print(f"[report] Merged tax data from tax_*.json: {list(tax_file_data.keys())}")

        # Optionally enrich tax information via live scrape (fallback)
        if fetch_tax and not tax_file_data:
            existing_report = enrich_tax_information(existing_report, force_lookup=True)

        # Save updated report
        report_json_path = folder_path / "FINAL_REPORT.json"
        report_json_path.write_text(json.dumps(existing_report, indent=2))

        report_markdown = generate_full_markdown_from_json(existing_report)

        # Save the regenerated markdown
        report_md_path = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
        report_md_path.write_text(report_markdown)

        return {
            "success": True,
            "report_json": existing_report,
            "report_markdown": report_markdown,
            "folder_path": str(folder_path),
            "source": "detailed_json",
            "pdf_count": len(pdf_files),
            "metadata_count": len(metadata)
        }

    # Otherwise generate basic report from metadata
    report_json = generate_report_from_data(
        owner_name, property_address, metadata, documents_found, pdf_files
    )

    report_markdown = generate_markdown_report(owner_name, property_address, metadata)

    # Save generated files
    report_json_path = folder_path / "FINAL_REPORT.json"
    report_md_path = folder_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"

    report_json_path.write_text(json.dumps(report_json, indent=2))
    report_md_path.write_text(report_markdown)

    return {
        "success": True,
        "report_json": report_json,
        "report_markdown": report_markdown,
        "folder_path": str(folder_path),
        "source": "generated_basic",
        "pdf_count": len(pdf_files),
        "metadata_count": len(metadata)
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python report_generator.py <owner_name> [property_address]")
        sys.exit(1)

    owner = sys.argv[1]
    address = sys.argv[2] if len(sys.argv) > 2 else ""

    result = generate_report_for_owner(owner, address)

    if result["success"]:
        print(f"Report generated successfully!")
        print(f"Folder: {result['folder_path']}")
        print(f"Source: {result['source']}")
        print("\n--- Markdown Report ---\n")
        print(result["report_markdown"])
    else:
        print(f"Error: {result['error']}")
