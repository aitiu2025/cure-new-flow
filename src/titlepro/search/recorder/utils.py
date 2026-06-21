"""
Utility functions for CA Recorder Search.

Enhanced for CURE multi-name workflow (Priority 1):
- Trust name parsing with trustee extraction
- Grantee extraction from deed analysis
- Multi-name discovery support
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging for multi-name workflow
logger = logging.getLogger("recorder_search.utils")
logger.setLevel(logging.DEBUG)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    Set up logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file path

    Returns:
        Configured logger
    """
    logger = logging.getLogger("recorder_search")
    logger.setLevel(getattr(logging, level.upper()))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def export_to_json(data: Dict, filename: str, pretty: bool = True) -> str:
    """
    Export data to JSON file.

    Args:
        data: Dictionary to export
        filename: Output filename
        pretty: Whether to format with indentation

    Returns:
        Full path to created file
    """
    filepath = Path(filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        if pretty:
            json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            json.dump(data, f, ensure_ascii=False)

    return str(filepath.absolute())


def format_document_numbers(documents: List[Dict]) -> List[str]:
    """
    Extract just the document numbers from a list of document records.

    Args:
        documents: List of document dictionaries

    Returns:
        List of document number strings
    """
    return [doc.get("document_number", "") for doc in documents if doc.get("document_number")]


def generate_output_filename(name1: str, name2: str, county: str) -> str:
    """
    Generate a timestamped output filename.

    Args:
        name1: First name searched
        name2: Second name searched
        county: County name

    Returns:
        Generated filename string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Clean names for filename
    clean_name1 = name1.replace(" ", "_").replace("/", "-")[:20]
    clean_name2 = name2.replace(" ", "_").replace("/", "-")[:20]

    return f"{county}_{clean_name1}_{clean_name2}_{timestamp}.json"


def validate_date_format(date_str: str) -> bool:
    """
    Validate date string is in MM/DD/YYYY format.

    Args:
        date_str: Date string to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        datetime.strptime(date_str, "%m/%d/%Y")
        return True
    except ValueError:
        return False


def format_name_for_search(first_name: str, last_name: str) -> str:
    """
    Format name in "Last First" format for Orange County Recorder search.

    Args:
        first_name: First name
        last_name: Last name

    Returns:
        Formatted name string (e.g., "Lau Casey")
    """
    return f"{last_name.strip()} {first_name.strip()}"


def parse_owner_names(raw: str) -> List[str]:
    """
    Parse an owner string into one or more "Last First" names.

    Examples:
        "Lau Casey Brandi" -> ["Lau Casey", "Lau Brandi"]
        "Lau Casey, Lau Brandi" -> ["Lau Casey", "Lau Brandi"]
        "Lau Casey & Brandi" -> ["Lau Casey", "Lau Brandi"]
        "Lau Casey Smith John" -> ["Lau Casey", "Smith John"]
    """
    if not raw:
        return []

    cleaned = " ".join(raw.replace("\n", " ").split())
    if not cleaned:
        return []

    parts = re.split(r"\s*(?:,|;|/|\||\band\b|&)\s*", cleaned, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]

    names: List[str] = []
    shared_surname = None

    for part in parts:
        tokens = part.split()
        if len(tokens) >= 2:
            shared_surname = tokens[0]
            if len(tokens) == 2:
                names.append(f"{tokens[0]} {tokens[1]}")
            else:
                if len(tokens) % 2 == 0 and len(parts) == 1:
                    for i in range(0, len(tokens), 2):
                        names.append(f"{tokens[i]} {tokens[i + 1]}")
                else:
                    for first in tokens[1:]:
                        names.append(f"{tokens[0]} {first}")
        elif len(tokens) == 1:
            if shared_surname:
                names.append(f"{shared_surname} {tokens[0]}")
            else:
                names.append(tokens[0])

    seen = set()
    deduped: List[str] = []
    for name in names:
        normalized = " ".join(name.split())
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)

    return deduped


def print_document_table(documents: List[Dict], title: str = "Documents"):
    """
    Print documents in a formatted table.

    Args:
        documents: List of document dictionaries
        title: Table title
    """
    if not documents:
        print(f"\n{title}: None found")
        return

    print(f"\n{title} ({len(documents)} documents):")
    print("-" * 100)
    print(f"{'Doc Number':<18} {'Type':<20} {'Date':<12} {'Pages':<6} {'Grantors':<20}")
    print("-" * 100)

    for doc in documents:
        doc_num = doc.get('document_number', 'N/A')[:17]
        doc_type = doc.get('document_type', 'N/A')[:19]
        rec_date = doc.get('recording_date', 'N/A')[:11]
        pages = doc.get('pages', 'N/A')[:5]
        grantors = doc.get('grantors', 'N/A')[:19]

        print(f"{doc_num:<18} {doc_type:<20} {rec_date:<12} {pages:<6} {grantors:<20}")

    print("-" * 100)


def extract_surname(name: str) -> str:
    """
    Extract surname (first word) from a "Last First" formatted name.

    Args:
        name: Name in "Last First" format

    Returns:
        Surname
    """
    parts = name.strip().split()
    return parts[0] if parts else ""


def check_common_surname(names: List[str]) -> Optional[str]:
    """
    Check if all names share the same surname.

    Args:
        names: List of names in "Last First" format

    Returns:
        Common surname if shared, None otherwise
    """
    if not names or len(names) < 2:
        return None

    surnames = [extract_surname(name).lower() for name in names]
    if len(set(surnames)) == 1:
        return surnames[0]
    return None


def get_first_names(names: List[str], common_surname: str) -> List[str]:
    """
    Extract first names from names with a common surname.

    Args:
        names: List of names in "Last First" format
        common_surname: The shared surname

    Returns:
        List of first names
    """
    first_names = []
    for name in names:
        parts = name.strip().split()
        if len(parts) >= 2:
            first_names.append(parts[1])
    return first_names


def build_search_strategy(names: List[str]) -> Dict:
    """
    Build an intelligent search strategy for the given names.

    Strategy:
    1. If two names have the same surname, search surname once and filter for both first names
    2. Otherwise, search each name individually
    3. If full name returns 0 results, fall back to surname-only search

    Args:
        names: List of names in "Last First" format

    Returns:
        Dictionary describing the search strategy
    """
    strategy = {
        "type": "individual",  # or "shared_surname"
        "searches": [],
        "common_surname": None,
        "first_names_to_filter": []
    }

    if not names:
        return strategy

    common_surname = check_common_surname(names)

    if common_surname:
        # Same surname - search once with surname only
        strategy["type"] = "shared_surname"
        strategy["common_surname"] = common_surname.upper()
        strategy["first_names_to_filter"] = [n.upper() for n in get_first_names(names, common_surname)]
        strategy["searches"] = [{
            "name": common_surname.upper(),
            "is_surname_only": True,
            "original_names": names
        }]
    else:
        # Different surnames - search individually
        strategy["type"] = "individual"
        for name in names:
            strategy["searches"].append({
                "name": name,
                "is_surname_only": False,
                "surname": extract_surname(name).upper()
            })

    return strategy


def filter_documents_by_first_names(documents: List[Dict], first_names: List[str]) -> List[Dict]:
    """
    Filter documents to only those containing any of the specified first names.

    Args:
        documents: List of document dictionaries
        first_names: List of first names to filter for

    Returns:
        Filtered list of documents
    """
    if not first_names:
        return documents

    filtered = []
    first_names_upper = [n.upper() for n in first_names]

    for doc in documents:
        # Check all name fields
        text_to_check = " ".join([
            doc.get("grantors", ""),
            doc.get("grantees", ""),
            doc.get("grantor_grantees", "")
        ]).upper()

        # Check if any first name appears
        for first_name in first_names_upper:
            if first_name in text_to_check:
                filtered.append(doc)
                break

    return filtered


def merge_results(results_list: List[Dict]) -> Dict:
    """
    Merge multiple search results into a single result set.

    Args:
        results_list: List of result dictionaries from multiple searches

    Returns:
        Merged result dictionary
    """
    if not results_list:
        return {}

    merged = {
        "search_params": {
            "merged_from": len(results_list),
            "search_timestamp": datetime.now().isoformat()
        },
        "all_documents": []
    }

    seen_doc_numbers = set()

    for results in results_list:
        for doc in results.get("common_documents", []):
            doc_num = doc.get("document_number")
            if doc_num and doc_num not in seen_doc_numbers:
                merged["all_documents"].append(doc)
                seen_doc_numbers.add(doc_num)

    return merged


# ============================================================================
# MULTI-NAME WORKFLOW FUNCTIONS (Priority 1 - CURE System)
# ============================================================================

def parse_trust_name(name: str) -> Dict[str, Optional[str]]:
    """
    Parse a trust name to extract trustee and trust name components.

    This function handles common trust naming patterns found in property deeds:
    - "John Smith, Trustee of Smith Family Trust"
    - "John Smith, as Trustee of the Smith Family Trust"
    - "John Smith, Successor Trustee of Smith Family Trust"
    - "John Smith AND Jane Smith, Trustees of Smith Family Trust"
    - "Smith Family Trust"
    - "John Smith" (individual, not a trust)

    Args:
        name: The name string to parse

    Returns:
        Dictionary with:
            - trustee: Trustee name(s) if identified, None otherwise
            - trust_name: Trust name if identified, None otherwise
            - type: "trust", "individual", or "entity"

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] parse_trust_name called with: {name}")

    result = {
        "trustee": None,
        "trust_name": None,
        "type": "individual"
    }

    if not name:
        return result

    name = name.strip()
    name_upper = name.upper()

    # Check for entity types first
    entity_patterns = [
        r'\bLLC\b', r'\bL\.L\.C\.', r'\bINC\b', r'\bINC\.', r'\bINCORPORATED\b',
        r'\bCORP\b', r'\bCORPORATION\b', r'\bLP\b', r'\bL\.P\.', r'\bLIMITED PARTNERSHIP\b',
        r'\bLLP\b', r'\bL\.L\.P\.', r'\bPARTNERSHIP\b', r'\bCOMPANY\b', r'\bCO\.'
    ]
    for pattern in entity_patterns:
        if re.search(pattern, name_upper):
            result["type"] = "entity"
            logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Classified as entity: {name}")
            return result

    # Check if this is a trust
    trust_indicators = [
        "TRUST", "LIVING TRUST", "FAMILY TRUST", "REVOCABLE TRUST",
        "IRREVOCABLE TRUST", "TESTAMENTARY TRUST", "INTER VIVOS"
    ]
    is_trust = any(indicator in name_upper for indicator in trust_indicators)

    if not is_trust:
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Classified as individual: {name}")
        return result

    result["type"] = "trust"

    # Pattern 1: Multiple trustees - "A AND B, Trustees of Trust"
    pattern_multi = re.compile(
        r'^(.+?(?:\s+AND\s+.+?)?),?\s*(?:as\s+)?(?:co-?)?trustees?\s+of\s+(?:the\s+)?(.+)$',
        re.IGNORECASE
    )
    match = pattern_multi.match(name)
    if match:
        result["trustee"] = match.group(1).strip()
        result["trust_name"] = match.group(2).strip()
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Multi-trustee pattern match: trustee={result['trustee']}, trust={result['trust_name']}")
        return result

    # Pattern 2: Single trustee - "Name, [as] [Successor] Trustee of [the] Trust"
    pattern_single = re.compile(
        r'^(.+?),?\s*(?:as\s+)?(?:successor\s+)?trustee\s+of\s+(?:the\s+)?(.+)$',
        re.IGNORECASE
    )
    match = pattern_single.match(name)
    if match:
        result["trustee"] = match.group(1).strip()
        result["trust_name"] = match.group(2).strip()
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Single-trustee pattern match: trustee={result['trustee']}, trust={result['trust_name']}")
        return result

    # Pattern 3: Just a trust name (no "Trustee of" present)
    if "TRUSTEE OF" not in name_upper and "TRUSTEE" not in name_upper:
        result["trust_name"] = name
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Trust-only pattern match: trust={result['trust_name']}")

    return result


def extract_all_grantees_from_analysis(deed_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all grantees from a deed analysis result.

    This function takes the output from pdf_analyzer.analyze_pdf() and extracts
    a structured list of all grantees for the multi-name workflow.

    Args:
        deed_analysis: Dictionary from analyze_pdf() containing document extraction

    Returns:
        List of grantee dictionaries, each containing:
            - raw_name: Original name as written
            - type: "individual", "trust", or "entity"
            - trust_name: Trust name if applicable, None otherwise
            - trustee: Trustee name if identified, None otherwise
            - search_names: List of names to use for recorder search

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    logger.debug("[MULTI_NAME_WORKFLOW_DEBUGLOGS] extract_all_grantees_from_analysis called")

    grantees = []

    if not deed_analysis:
        logger.debug("[MULTI_NAME_WORKFLOW_DEBUGLOGS] Empty deed_analysis provided")
        return grantees

    # Check if structured grantees already exist
    if deed_analysis.get("grantees") and isinstance(deed_analysis["grantees"], list):
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found {len(deed_analysis['grantees'])} pre-structured grantees")
        for grantee in deed_analysis["grantees"]:
            processed = _process_grantee_entry(grantee)
            if processed:
                grantees.append(processed)
        return grantees

    # Fall back to parsing from grantee string
    grantee_str = deed_analysis.get("grantee") or deed_analysis.get("grantees_raw") or ""
    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Parsing from grantee string: {grantee_str[:100]}...")

    if not grantee_str:
        return grantees

    # Parse the grantee string
    grantees = _parse_grantees_string(grantee_str)
    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Parsed {len(grantees)} grantees from string")

    return grantees


def _process_grantee_entry(grantee: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Process a single grantee entry and add search names.

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    if not grantee or not grantee.get("raw_name"):
        return None

    raw_name = grantee.get("raw_name", "")
    grantee_type = grantee.get("type", "individual")

    result = {
        "raw_name": raw_name,
        "type": grantee_type,
        "trust_name": grantee.get("trust_name"),
        "trustee": grantee.get("trustee"),
        "search_names": []
    }

    # Generate search names based on type
    if grantee_type == "trust":
        # For trusts, search both trustee (if known) and trust name
        if result["trustee"]:
            # Convert trustee name to "Last First" format
            trustee_names = _convert_to_search_format(result["trustee"])
            result["search_names"].extend(trustee_names)

        if result["trust_name"]:
            # Search trust name as-is (recorders index by first word)
            # Extract first word of trust name for search
            trust_first_word = result["trust_name"].split()[0] if result["trust_name"] else ""
            if trust_first_word:
                result["search_names"].append(trust_first_word.upper())

    elif grantee_type == "entity":
        # For entities, extract first word for search
        entity_first_word = raw_name.split()[0] if raw_name else ""
        if entity_first_word:
            result["search_names"].append(entity_first_word.upper())

    else:
        # Individual - convert to "Last First" format
        names = _convert_to_search_format(raw_name)
        result["search_names"].extend(names)

    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Processed grantee: {result}")
    return result


def _parse_grantees_string(grantee_str: str) -> List[Dict[str, Any]]:
    """
    Parse a grantee string into structured list.

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    grantees = []

    if not grantee_str:
        return grantees

    # First, try to identify if there are trust patterns that shouldn't be split
    # Pattern: "Name, Trustee of Trust AND Name2"
    trust_pattern = re.compile(
        r'(.+?(?:,?\s*(?:as\s+)?(?:successor\s+)?trustees?\s+of\s+(?:the\s+)?.+?))',
        re.IGNORECASE
    )

    # Split on " AND " but preserve trust clauses
    # More careful split - don't split within "Trustee of X"
    parts = []
    remaining = grantee_str

    # Handle common separators while preserving trust names
    # Split on " AND " that's not followed by trust terms
    split_pattern = re.compile(r'\s+AND\s+(?!.*(?:TRUSTEE|TRUST))', re.IGNORECASE)

    # Simple split by AND
    raw_parts = re.split(r'\s+AND\s+', grantee_str, flags=re.IGNORECASE)

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue

        # Also split by comma if not a trust pattern
        if "TRUSTEE" not in part.upper():
            sub_parts = [p.strip() for p in part.split(',') if p.strip()]
            parts.extend(sub_parts)
        else:
            parts.append(part)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Parse the name
        parsed = parse_trust_name(part)

        grantee = {
            "raw_name": part,
            "type": parsed["type"],
            "trust_name": parsed["trust_name"],
            "trustee": parsed["trustee"],
            "search_names": []
        }

        # Generate search names
        processed = _process_grantee_entry(grantee)
        if processed:
            grantees.append(processed)

    return grantees


def _convert_to_search_format(name: str) -> List[str]:
    """
    Convert a name from "First Last" or "First Middle Last" to "Last First" format
    suitable for recorder search.

    Args:
        name: Name in common format (e.g., "John Smith", "John Robert Smith")

    Returns:
        List of "Last First" formatted names

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    if not name:
        return []

    # Clean up the name
    name = name.strip()
    name = re.sub(r'\s+', ' ', name)  # Normalize whitespace

    # Remove common prefixes/suffixes that aren't useful for search
    name = re.sub(r',?\s*(JR\.?|SR\.?|II|III|IV)$', '', name, flags=re.IGNORECASE)

    parts = name.split()

    if len(parts) == 0:
        return []

    if len(parts) == 1:
        return [parts[0].upper()]

    if len(parts) == 2:
        # "First Last" -> "Last First"
        return [f"{parts[1].upper()} {parts[0].upper()}"]

    # Three or more parts - assume last word is surname
    # "First Middle Last" -> "Last First"
    surname = parts[-1]
    first_name = parts[0]
    return [f"{surname.upper()} {first_name.upper()}"]


def get_new_names_to_search(
    discovered_grantees: List[Dict[str, Any]],
    already_searched: List[str]
) -> List[Dict[str, Any]]:
    """
    Identify new names that need to be searched from discovered grantees.

    Compares discovered grantees against already-searched names and returns
    only the new ones that need searching.

    Args:
        discovered_grantees: List of grantee dicts from extract_all_grantees_from_analysis
        already_searched: List of names already searched (in "Last First" or raw format)

    Returns:
        List of grantee dicts for names not yet searched

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] get_new_names_to_search called")
    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Discovered: {len(discovered_grantees)}, Already searched: {len(already_searched)}")

    # Normalize already-searched names for comparison
    normalized_searched = set()
    for name in already_searched:
        normalized = _normalize_name_for_comparison(name)
        normalized_searched.add(normalized)
        logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Already searched (normalized): {normalized}")

    new_grantees = []

    for grantee in discovered_grantees:
        is_new = False
        raw_name = grantee.get("raw_name", "")

        # Check if any of the search names are new
        for search_name in grantee.get("search_names", []):
            normalized = _normalize_name_for_comparison(search_name)
            if normalized and normalized not in normalized_searched:
                is_new = True
                logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] New name found: {search_name}")
                break

        # Also check raw name
        if not is_new:
            normalized_raw = _normalize_name_for_comparison(raw_name)
            if normalized_raw and normalized_raw not in normalized_searched:
                is_new = True
                logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] New raw name found: {raw_name}")

        if is_new:
            new_grantees.append(grantee)

    logger.debug(f"[MULTI_NAME_WORKFLOW_DEBUGLOGS] Found {len(new_grantees)} new names to search")
    return new_grantees


def _normalize_name_for_comparison(name: str) -> str:
    """
    Normalize a name for comparison purposes.

    [MULTI_NAME_WORKFLOW_DEBUGLOGS]
    """
    if not name:
        return ""

    # Uppercase
    normalized = name.upper()
    # Remove punctuation
    normalized = re.sub(r'[^\w\s]', '', normalized)
    # Normalize whitespace
    normalized = ' '.join(normalized.split())

    return normalized
