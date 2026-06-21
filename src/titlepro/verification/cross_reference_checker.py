"""
Cross-Reference Checker Module for CURE Title Examination System

This module verifies that all parties appear correctly on shared documents.
For deeds and mortgages involving multiple owners, this checks that all
expected parties are present.

Key Features:
- Name matching with fuzzy comparison
- Detection of missing parties on shared documents
- Identification of partial ownership transfers
- Generation of report sections for cross-reference issues
"""

import re
import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from datetime import datetime

# Configure logging with debug tag
logger = logging.getLogger(__name__)

# Debug tag for all logs from this module
DEBUG_TAG = "[PROPERTY_VERIFY_DEBUGLOGS]"


def log_debug(message: str) -> None:
    """Log debug message with module tag."""
    logger.debug(f"{DEBUG_TAG} {message}")
    print(f"{DEBUG_TAG} DEBUG: {message}")


def log_info(message: str) -> None:
    """Log info message with module tag."""
    logger.info(f"{DEBUG_TAG} {message}")
    print(f"{DEBUG_TAG} INFO: {message}")


def log_warning(message: str) -> None:
    """Log warning message with module tag."""
    logger.warning(f"{DEBUG_TAG} {message}")
    print(f"{DEBUG_TAG} WARNING: {message}")


def log_error(message: str) -> None:
    """Log error message with module tag."""
    logger.error(f"{DEBUG_TAG} {message}")
    print(f"{DEBUG_TAG} ERROR: {message}")


# Document types that typically require all owners to sign
JOINT_SIGNATURE_DOC_TYPES = {
    "GRANT DEED",
    "DEED",
    "DEED OF TRUST",
    "MORTGAGE",
    "QUITCLAIM DEED",
    "WARRANTY DEED",
    "INTERSPOUSAL TRANSFER DEED",
    "TRUST TRANSFER DEED",
    "SPECIAL WARRANTY DEED",
    "GIFT DEED",
}

# Document types that may only require one party
SINGLE_PARTY_DOC_TYPES = {
    "RECONVEYANCE",
    "FULL RECONVEYANCE",
    "SUBSTITUTION OF TRUSTEE",
    "ASSIGNMENT",
    "MODIFICATION AGREEMENT",
    "LIS PENDENS",
    "NOTICE OF DEFAULT",
    "NOTICE OF TRUSTEE SALE",
    "ABSTRACT OF JUDGMENT",
    "RELEASE",
}

# Common name suffixes and titles to normalize
NAME_SUFFIXES = {
    "JR", "JR.", "JUNIOR",
    "SR", "SR.", "SENIOR",
    "II", "III", "IV", "V",
    "ESQ", "ESQ.",
    "MD", "M.D.",
    "PHD", "PH.D.",
}

NAME_TITLES = {
    "MR", "MR.",
    "MRS", "MRS.",
    "MS", "MS.",
    "DR", "DR.",
    "MISS",
}

# Vesting types that indicate shared ownership
SHARED_VESTING_TYPES = {
    "JOINT TENANTS",
    "JOINT TENANCY",
    "COMMUNITY PROPERTY",
    "TENANTS IN COMMON",
    "TENANCY IN COMMON",
    "COMMUNITY PROPERTY WITH RIGHT OF SURVIVORSHIP",
    "HUSBAND AND WIFE",
    "MARRIED COUPLE",
    "DOMESTIC PARTNERS",
}

# Lien document types requiring special debtor/creditor handling
LIEN_DOCUMENT_TYPES = {
    "ABSTRACT OF JUDGMENT",
    "JUDGMENT LIEN",
    "MONEY JUDGMENT",
    "LIS PENDENS",
    "NOTICE OF PENDING ACTION",
    "NOTICE OF PENDENCY",
    "FEDERAL TAX LIEN",
    "STATE TAX LIEN",
    "TAX LIEN",
    "MECHANICS LIEN",
    "MATERIALMAN'S LIEN",
    "CLAIM OF LIEN",
    "UCC FILING",
    "UCC-1",
    "FINANCING STATEMENT",
    "CHILD SUPPORT LIEN",
    "HOA LIEN",
    "ASSESSMENT LIEN",
    "ATTACHMENT",
    "WRIT OF ATTACHMENT",
}


@dataclass
class CrossReferenceIssue:
    """Represents a cross-reference issue found in document analysis."""
    document_file: str
    document_type: str
    instrument_number: str
    issue_type: str  # 'missing_party', 'partial_ownership', 'name_mismatch'
    severity: str  # 'HIGH', 'MEDIUM', 'LOW'
    missing_parties: List[str] = field(default_factory=list)
    found_parties: List[str] = field(default_factory=list)
    expected_parties: List[str] = field(default_factory=list)
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "document_file": self.document_file,
            "document_type": self.document_type,
            "instrument_number": self.instrument_number,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "missing_parties": self.missing_parties,
            "found_parties": self.found_parties,
            "expected_parties": self.expected_parties,
            "message": self.message,
            "details": self.details
        }


@dataclass
class CrossReferenceResult:
    """Result of cross-reference check for a single document."""
    has_issue: bool
    issue_type: Optional[str]
    missing_parties: List[str] = field(default_factory=list)
    found_parties: List[str] = field(default_factory=list)
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "has_issue": self.has_issue,
            "issue_type": self.issue_type,
            "missing_parties": self.missing_parties,
            "found_parties": self.found_parties,
            "message": self.message,
            "details": self.details
        }


class CrossReferenceChecker:
    """
    Verifies that all parties appear correctly on shared documents.

    For deeds and mortgages involving multiple owners, this class checks
    that all expected parties are present as grantors, grantees, or
    trustors as appropriate.
    """

    # Similarity threshold for name matching
    NAME_MATCH_THRESHOLD = 0.85

    def __init__(self, all_owners: List[str]):
        """
        Initialize with list of all property owners.

        Args:
            all_owners: List of owner names (e.g., ["JOHN SMITH", "MARY SMITH"])
        """
        self.owners = all_owners
        self.normalized_owners = [self._normalize_name(name) for name in all_owners]
        self.issues: List[CrossReferenceIssue] = []

        log_info(f"CrossReferenceChecker initialized with {len(all_owners)} owners:")
        for i, (original, normalized) in enumerate(zip(all_owners, self.normalized_owners)):
            log_debug(f"  Owner {i+1}: '{original}' -> '{normalized}'")

    def check_document(self, doc: Dict[str, Any]) -> CrossReferenceResult:
        """
        Check if document properly references all expected parties.

        For deeds and mortgages, all owners should typically appear.
        For other document types, requirements may differ.

        Args:
            doc: Document analysis dictionary from pdf_analyzer

        Returns:
            CrossReferenceResult with check results
        """
        doc_type = self._get_doc_type(doc)
        doc_file = doc.get("_source_file", "Unknown")
        instrument = doc.get("instrument_number") or doc.get("_instrument_number", "Unknown")

        log_info(f"Checking document: {doc_file} ({doc_type})")

        # Determine what field to check based on document type
        parties_field = self._get_parties_field(doc_type)

        if not parties_field:
            log_debug(f"Document type '{doc_type}' does not require all-party check")
            return CrossReferenceResult(
                has_issue=False,
                issue_type=None,
                message="Document type does not require all-party verification"
            )

        # Get parties from document
        parties_value = doc.get(parties_field, "")
        found_parties = self._extract_names(parties_value)

        log_debug(f"Found parties in '{parties_field}': {found_parties}")

        # Check if document type requires all owners
        requires_all_owners = self._requires_all_owners(doc_type)

        if not requires_all_owners:
            # For single-party documents, just verify at least one owner appears
            matched_any = any(
                self._name_matches_any(party, self.normalized_owners)
                for party in found_parties
            )

            if not matched_any and found_parties:
                log_debug(f"Single-party doc: No matching owners found in {found_parties}")

            return CrossReferenceResult(
                has_issue=False,
                issue_type=None,
                found_parties=found_parties,
                message="Single-party document - no all-party requirement"
            )

        # For joint documents, check that ALL owners appear
        missing_parties = []
        matched_owners = []

        for i, (owner, normalized_owner) in enumerate(zip(self.owners, self.normalized_owners)):
            found_match = False

            for party in found_parties:
                normalized_party = self._normalize_name(party)
                if self._names_match(normalized_party, normalized_owner):
                    found_match = True
                    matched_owners.append(owner)
                    log_debug(f"Owner '{owner}' matched with party '{party}'")
                    break

            if not found_match:
                missing_parties.append(owner)
                log_warning(f"Owner '{owner}' NOT found in document")

        # Determine if there's an issue
        has_issue = len(missing_parties) > 0

        if has_issue:
            message = self._generate_issue_message(
                doc_type, missing_parties, matched_owners, found_parties
            )

            # Record the issue
            issue = CrossReferenceIssue(
                document_file=doc_file,
                document_type=doc_type,
                instrument_number=instrument,
                issue_type="missing_party",
                severity="HIGH" if doc_type in ["DEED OF TRUST", "GRANT DEED"] else "MEDIUM",
                missing_parties=missing_parties,
                found_parties=found_parties,
                expected_parties=self.owners.copy(),
                message=message,
                details={
                    "parties_field": parties_field,
                    "raw_parties_value": parties_value
                }
            )
            self.issues.append(issue)
            log_warning(f"Cross-reference issue recorded: {message}")

            return CrossReferenceResult(
                has_issue=True,
                issue_type="missing_party",
                missing_parties=missing_parties,
                found_parties=found_parties,
                message=message
            )

        return CrossReferenceResult(
            has_issue=False,
            issue_type=None,
            found_parties=found_parties,
            message="All expected parties found in document"
        )

    def check_all_documents(self, documents: List[Dict[str, Any]]) -> List[CrossReferenceIssue]:
        """
        Check all documents and return list of issues.

        Args:
            documents: List of document analysis dictionaries

        Returns:
            List of CrossReferenceIssue objects for documents with issues
        """
        log_info(f"Checking {len(documents)} documents for cross-reference issues")

        self.issues = []  # Reset issues

        for doc in documents:
            self.check_document(doc)

        log_info(f"Cross-reference check complete. Found {len(self.issues)} issues.")

        return self.issues

    def generate_report_section(self) -> str:
        """
        Generate cross-reference section for title examination report.

        Returns:
            Markdown-formatted report section
        """
        if not self.issues:
            return """## CROSS-REFERENCE VERIFICATION

All documents properly reference the expected parties. No discrepancies found.

"""

        report = """## CROSS-REFERENCE VERIFICATION

**ISSUES FOUND:** The following documents may have party discrepancies:

"""

        for i, issue in enumerate(self.issues, 1):
            severity_icon = "!!!" if issue.severity == "HIGH" else "!!" if issue.severity == "MEDIUM" else "!"

            report += f"""### {severity_icon} Issue {i}: {issue.document_type}

| Field | Value |
|-------|-------|
| Document | {issue.document_file} |
| Instrument # | {issue.instrument_number} |
| Issue Type | {issue.issue_type.replace('_', ' ').title()} |
| Severity | **{issue.severity}** |
| Expected Parties | {', '.join(issue.expected_parties)} |
| Found Parties | {', '.join(issue.found_parties) if issue.found_parties else 'None identified'} |
| Missing Parties | **{', '.join(issue.missing_parties)}** |

**Analysis:** {issue.message}

"""

        report += """### RECOMMENDATIONS

"""

        # Generate recommendations based on issues
        high_severity = [i for i in self.issues if i.severity == "HIGH"]
        if high_severity:
            report += """1. **HIGH PRIORITY**: Review the following documents for potential title defects:
"""
            for issue in high_severity:
                report += f"   - {issue.document_type} (Inst# {issue.instrument_number})\n"
            report += "\n"

        report += """2. Verify vesting from most recent deed matches all expected owners
3. Consider whether partial signatures may affect ownership rights
4. Consult with title officer if discrepancies cannot be resolved

"""

        return report

    def get_issues_summary(self) -> Dict[str, Any]:
        """
        Get summary of all cross-reference issues.

        Returns:
            Dictionary with summary statistics and issues list
        """
        return {
            "total_issues": len(self.issues),
            "high_severity": len([i for i in self.issues if i.severity == "HIGH"]),
            "medium_severity": len([i for i in self.issues if i.severity == "MEDIUM"]),
            "low_severity": len([i for i in self.issues if i.severity == "LOW"]),
            "issue_types": list(set(i.issue_type for i in self.issues)),
            "issues": [i.to_dict() for i in self.issues]
        }

    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize a name for comparison.

        - Converts to uppercase
        - Removes titles (Mr., Mrs., etc.)
        - Removes suffixes (Jr., Sr., III, etc.)
        - Normalizes whitespace
        - Removes punctuation
        """
        if not name:
            return ""

        # Convert to uppercase
        normalized = name.upper().strip()

        # Remove titles
        for title in NAME_TITLES:
            normalized = re.sub(rf'\b{re.escape(title)}\b', '', normalized)

        # Remove suffixes
        for suffix in NAME_SUFFIXES:
            normalized = re.sub(rf'\b{re.escape(suffix)}\b', '', normalized)

        # Remove punctuation
        normalized = re.sub(r'[.,;:\'"()-]', ' ', normalized)

        # Normalize whitespace
        normalized = ' '.join(normalized.split())

        return normalized

    def _names_match(self, name1: str, name2: str) -> bool:
        """
        Check if two names match (using fuzzy matching).

        Handles variations like:
        - JOHN SMITH vs JOHN A SMITH
        - SMITH, JOHN vs JOHN SMITH
        """
        if not name1 or not name2:
            return False

        # Exact match after normalization
        if name1 == name2:
            return True

        # Try reordering (LAST, FIRST -> FIRST LAST)
        name1_parts = name1.split()
        name2_parts = name2.split()

        # If one has comma, try to reorder
        if ',' in name1:
            name1_reordered = ' '.join(reversed(name1.replace(',', '').split()))
        else:
            name1_reordered = name1

        if ',' in name2:
            name2_reordered = ' '.join(reversed(name2.replace(',', '').split()))
        else:
            name2_reordered = name2

        if name1_reordered == name2_reordered:
            return True

        # Fuzzy match
        similarity = SequenceMatcher(None, name1, name2).ratio()
        if similarity >= self.NAME_MATCH_THRESHOLD:
            log_debug(f"Fuzzy name match: '{name1}' ~ '{name2}' ({similarity:.2%})")
            return True

        # Check if one name is contained in the other (handles middle initials)
        # e.g., "JOHN SMITH" should match "JOHN A SMITH"
        name1_words = set(name1_parts)
        name2_words = set(name2_parts)

        # If all words of the shorter name are in the longer name
        if name1_words.issubset(name2_words) or name2_words.issubset(name1_words):
            # But require at least 2 words to match
            common_words = name1_words.intersection(name2_words)
            if len(common_words) >= 2:
                log_debug(f"Subset name match: '{name1}' ~ '{name2}'")
                return True

        return False

    def _name_matches_any(self, name: str, owner_names: List[str]) -> bool:
        """Check if a name matches any of the owner names."""
        normalized_name = self._normalize_name(name)

        for owner in owner_names:
            if self._names_match(normalized_name, owner):
                return True

        return False

    @staticmethod
    def _extract_names(names_value: Any) -> List[str]:
        """
        Extract individual names from a names field.

        Handles various formats:
        - "JOHN SMITH AND MARY SMITH"
        - "JOHN SMITH; MARY SMITH"
        - ["JOHN SMITH", "MARY SMITH"]
        - "JOHN SMITH, A MARRIED MAN"
        """
        if not names_value:
            return []

        # If already a list, normalize each
        if isinstance(names_value, list):
            return [CrossReferenceChecker._normalize_name(n) for n in names_value if n]

        # Convert to string
        names_str = str(names_value).upper()

        # Split on common separators
        # Replace common connectors with semicolons for uniform splitting
        names_str = re.sub(r'\s+AND\s+', ';', names_str)
        names_str = re.sub(r'\s*,\s*(?=[A-Z])', ';', names_str)  # Comma followed by capital letter
        names_str = re.sub(r'\s*/\s*', ';', names_str)

        # Split and clean
        parts = names_str.split(';')
        names = []

        for part in parts:
            cleaned = part.strip()

            # Remove common descriptors
            cleaned = re.sub(r'\s*,?\s*(A\s+)?(SINGLE|MARRIED|UNMARRIED)\s+(MAN|WOMAN|PERSON).*$', '', cleaned)
            cleaned = re.sub(r'\s*,?\s*(AS\s+)?(HIS|HER|THEIR)\s+.*$', '', cleaned)
            cleaned = re.sub(r'\s*,?\s*(HUSBAND|WIFE)\s*$', '', cleaned)
            cleaned = re.sub(r'\s*,?\s*ET\s*(UX|AL|VIR)\.?\s*$', '', cleaned)

            # Clean up any remaining issues
            cleaned = CrossReferenceChecker._normalize_name(cleaned)

            if cleaned and len(cleaned) > 2:  # Skip single letters
                names.append(cleaned)

        return names

    @staticmethod
    def _get_doc_type(doc: Dict[str, Any]) -> str:
        """Extract and normalize document type."""
        doc_type = doc.get("document_type", "UNKNOWN")
        if doc_type:
            return doc_type.upper().strip()
        return "UNKNOWN"

    @staticmethod
    def _get_parties_field(doc_type: str) -> Optional[str]:
        """
        Determine which field contains the relevant parties for verification.

        For deeds: Check grantor (the sellers/owners)
        For deeds of trust: Check grantor/trustor (the borrowers/owners)
        """
        doc_upper = doc_type.upper()

        # For deeds, the grantor is the party transferring (should be all owners)
        if any(t in doc_upper for t in ["GRANT DEED", "QUITCLAIM", "WARRANTY DEED", "GIFT DEED"]):
            return "grantor"

        # For deeds of trust, the trustor/grantor is the borrower (should be all owners)
        if "DEED OF TRUST" in doc_upper or "MORTGAGE" in doc_upper:
            return "grantor"  # Often stored as grantor even for DOTs

        # For reconveyances and releases, don't require all owners
        if any(t in doc_upper for t in ["RECONVEYANCE", "RELEASE", "SUBSTITUTION"]):
            return None

        # Default to checking grantor for unknown deed types
        if "DEED" in doc_upper:
            return "grantor"

        return None

    @staticmethod
    def _requires_all_owners(doc_type: str) -> bool:
        """Determine if document type requires all owners to sign."""
        doc_upper = doc_type.upper()

        # Check against known joint signature types
        for joint_type in JOINT_SIGNATURE_DOC_TYPES:
            if joint_type in doc_upper:
                return True

        # Check against known single party types
        for single_type in SINGLE_PARTY_DOC_TYPES:
            if single_type in doc_upper:
                return False

        # Default to requiring all owners for deeds
        return "DEED" in doc_upper

    @staticmethod
    def _generate_issue_message(
        doc_type: str,
        missing_parties: List[str],
        matched_owners: List[str],
        found_parties: List[str]
    ) -> str:
        """Generate descriptive message for cross-reference issue."""
        if len(missing_parties) == 1:
            return (
                f"Document appears to be missing {missing_parties[0]} as a party. "
                f"For a {doc_type}, all owners typically must sign. "
                f"Verify if this is intentional or a potential title defect."
            )

        return (
            f"Document may not include all parties. "
            f"Missing: {', '.join(missing_parties)}. "
            f"Found: {', '.join(found_parties) if found_parties else 'Unable to parse parties'}. "
            f"For a {doc_type}, verify all owners signed or if a partial transfer was intended."
        )


# ---------------------------------------------------------------------------
# Module-level functional API
#
# Lightweight, stateless helpers for callers (and tests) that work from raw
# OCR/extracted text rather than pre-parsed document dictionaries. The
# class-based API above remains the primary path for pipeline integration.
# ---------------------------------------------------------------------------

# Roles whose named party is the debtor/obligor side of a lien instrument
_DEBTOR_SIDE_ROLES = ("GRANTOR", "TRUSTOR", "DEBTOR")

_PARTY_ROLES = (
    "GRANTOR", "GRANTEE", "TRUSTOR", "TRUSTEE", "BENEFICIARY",
    "DEBTOR", "SECURED PARTY",
)

_PARTY_LINE_RE = re.compile(
    rf"^\s*({'|'.join(_PARTY_ROLES)})\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_RELEASE_KEYWORDS = (
    "RECONVEY", "RELEASE", "SATISFACTION", "SATISFIED", "DISCHARGE",
    "WITHDRAWAL", "TERMINATION",
)


def normalize_party(name: str) -> str:
    """Normalize a party name for comparison (uppercase, no punctuation/titles)."""
    return CrossReferenceChecker._normalize_name(name)


def extract_parties(text: str) -> Dict[str, List[str]]:
    """
    Extract labeled parties from document text.

    Recognizes "ROLE: Name" lines for the standard recorder roles
    (GRANTOR, GRANTEE, TRUSTOR, TRUSTEE, BENEFICIARY, DEBTOR, SECURED PARTY).
    Returns a dict keyed by uppercase role with lists of names as written.
    """
    parties: Dict[str, List[str]] = {role: [] for role in _PARTY_ROLES}
    for match in _PARTY_LINE_RE.finditer(text or ""):
        role = match.group(1).upper()
        name = match.group(2).strip()
        if name and name not in parties[role]:
            parties[role].append(name)
    return parties


def extract_lien_type(text: str) -> str:
    """
    Classify the lien/instrument type from raw document text.

    Returns one of: UCC, MECHANIC, DEED OF TRUST, MORTGAGE, JL (judgment
    lien), TAX LIEN, HOA, LIS PENDENS, or OTHER.
    """
    upper = (text or "").upper()
    if "UCC" in upper or "FINANCING STATEMENT" in upper:
        return "UCC"
    if "MECHANIC" in upper or "MATERIALMAN" in upper:
        return "MECHANIC"
    if "DEED OF TRUST" in upper:
        return "DEED OF TRUST"
    if "MORTGAGE" in upper:
        return "MORTGAGE"
    if re.search(r"\bJL\b", upper) or "JUDGMENT" in upper or "ABSTRACT OF JUDGMENT" in upper:
        return "JL"
    if "TAX LIEN" in upper:
        return "TAX LIEN"
    if "LIS PENDENS" in upper:
        return "LIS PENDENS"
    if "HOA" in upper or "ASSESSMENT LIEN" in upper:
        return "HOA"
    return "OTHER"


def detect_release_status(text: str) -> str:
    """Return RELEASED if the text indicates a release/reconveyance, else OPEN."""
    upper = (text or "").upper()
    if any(keyword in upper for keyword in _RELEASE_KEYWORDS):
        return "RELEASED"
    return "OPEN"


def extract_lien_indexing(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a lien index from a list of raw documents.

    Each doc dict needs a 'text' key (extracted/OCR text); 'index' and
    'recorded_date' are carried through when present. Liens are attributed
    to the debtor-side parties (GRANTOR/TRUSTOR/DEBTOR) in normalized form.

    Returns {'all_parties': [...], 'liens_attributed': [...]} where each
    attributed entry has doc_type, attributed_parties, dot_status, and the
    full parsed parties dict.
    """
    all_parties: Set[str] = set()
    liens_attributed: List[Dict[str, Any]] = []

    for doc in docs:
        text = doc.get("text", "")
        parties = extract_parties(text)
        for names in parties.values():
            all_parties.update(normalize_party(n) for n in names)

        attributed = []
        for role in _DEBTOR_SIDE_ROLES:
            for name in parties[role]:
                normalized = normalize_party(name)
                if normalized not in attributed:
                    attributed.append(normalized)

        liens_attributed.append({
            "index": doc.get("index"),
            "recorded_date": doc.get("recorded_date"),
            "doc_type": extract_lien_type(text),
            "dot_status": detect_release_status(text),
            "attributed_parties": attributed,
            "parties": parties,
        })

    return {
        "all_parties": sorted(all_parties),
        "liens_attributed": liens_attributed,
    }


def check_documents_cross_reference(
    documents: List[Dict[str, Any]],
    all_owners: List[str]
) -> Dict[str, Any]:
    """
    Convenience function to check all documents for cross-reference issues.

    Args:
        documents: List of document analysis dictionaries
        all_owners: List of all property owner names

    Returns:
        Dictionary with cross-reference check results
    """
    log_info(f"Starting cross-reference check for {len(documents)} documents with {len(all_owners)} owners")

    checker = CrossReferenceChecker(all_owners)
    issues = checker.check_all_documents(documents)

    return {
        "total_documents": len(documents),
        "total_owners": len(all_owners),
        "owners": all_owners,
        "issues_found": len(issues),
        "issues": [i.to_dict() for i in issues],
        "report_section": checker.generate_report_section(),
        "summary": checker.get_issues_summary()
    }


@dataclass
class LienAttribution:
    """Attribution of a lien to a specific party (debtor)."""
    document_file: str
    document_type: str
    instrument_number: str
    lien_type: str
    debtor: str
    creditor: str
    amount: Optional[str] = None
    case_number: Optional[str] = None
    court_name: Optional[str] = None
    recording_date: Optional[str] = None
    expiration_date: Optional[str] = None
    status: str = "OPEN"  # OPEN, RELEASED, EXPIRED, UNKNOWN
    attributed_to_owner: Optional[str] = None  # Which owner this lien belongs to
    confidence: float = 1.0  # How confident we are in the attribution

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "document_file": self.document_file,
            "document_type": self.document_type,
            "instrument_number": self.instrument_number,
            "lien_type": self.lien_type,
            "debtor": self.debtor,
            "creditor": self.creditor,
            "amount": self.amount,
            "case_number": self.case_number,
            "court_name": self.court_name,
            "recording_date": self.recording_date,
            "expiration_date": self.expiration_date,
            "status": self.status,
            "attributed_to_owner": self.attributed_to_owner,
            "confidence": self.confidence
        }


class LienAttributionChecker:
    """
    Handles attribution of liens to specific property owners.

    This class analyzes lien documents (judgments, tax liens, mechanics liens, etc.)
    and determines which owner(s) the lien should be attributed to.

    [PROPERTY_VERIFY_DEBUGLOGS]
    """

    # Similarity threshold for debtor name matching
    DEBTOR_MATCH_THRESHOLD = 0.80

    def __init__(self, all_owners: List[str]):
        """
        Initialize with list of all property owners.

        Args:
            all_owners: List of owner names (e.g., ["JOHN SMITH", "MARY SMITH"])
        """
        self.owners = all_owners
        self.normalized_owners = [self._normalize_name(name) for name in all_owners]
        self.liens: List[LienAttribution] = []
        self.liens_by_owner: Dict[str, List[LienAttribution]] = {owner: [] for owner in all_owners}
        self.unattributed_liens: List[LienAttribution] = []

        log_info(f"{DEBUG_TAG} LienAttributionChecker initialized with {len(all_owners)} owners")

    def analyze_document(self, doc: Dict[str, Any]) -> Optional[LienAttribution]:
        """
        Analyze a document to determine if it's a lien and attribute it to an owner.

        Args:
            doc: Document analysis dictionary from pdf_analyzer

        Returns:
            LienAttribution if document is a lien, None otherwise

        [PROPERTY_VERIFY_DEBUGLOGS]
        """
        doc_type = self._get_doc_type(doc)
        doc_file = doc.get("_source_file", "Unknown")

        log_debug(f"{DEBUG_TAG} Analyzing document for lien: {doc_file} ({doc_type})")

        # Check if this is a lien document
        if not self._is_lien_document(doc_type, doc):
            log_debug(f"{DEBUG_TAG} Document is not a lien type: {doc_type}")
            return None

        # Extract lien information
        lien = self._extract_lien_info(doc)

        if not lien:
            log_warning(f"{DEBUG_TAG} Could not extract lien info from: {doc_file}")
            return None

        # Attribute the lien to an owner
        self._attribute_lien_to_owner(lien)

        # Store the lien
        self.liens.append(lien)

        if lien.attributed_to_owner:
            self.liens_by_owner[lien.attributed_to_owner].append(lien)
        else:
            self.unattributed_liens.append(lien)

        log_info(f"{DEBUG_TAG} Lien found: {lien.lien_type} for {lien.debtor} -> attributed to: {lien.attributed_to_owner or 'UNATTRIBUTED'}")

        return lien

    def analyze_all_documents(self, documents: List[Dict[str, Any]]) -> List[LienAttribution]:
        """
        Analyze all documents and extract/attribute liens.

        Args:
            documents: List of document analysis dictionaries

        Returns:
            List of LienAttribution objects for all liens found

        [PROPERTY_VERIFY_DEBUGLOGS]
        """
        log_info(f"{DEBUG_TAG} Analyzing {len(documents)} documents for liens")

        # Reset state
        self.liens = []
        self.liens_by_owner = {owner: [] for owner in self.owners}
        self.unattributed_liens = []

        for doc in documents:
            self.analyze_document(doc)

        log_info(f"{DEBUG_TAG} Found {len(self.liens)} liens total")
        log_info(f"{DEBUG_TAG} Unattributed liens: {len(self.unattributed_liens)}")

        return self.liens

    def get_liens_by_owner(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get liens grouped by owner for report generation.

        Returns:
            Dictionary mapping owner name to list of lien dictionaries
        """
        return {
            owner: [lien.to_dict() for lien in liens]
            for owner, liens in self.liens_by_owner.items()
        }

    def generate_liens_report_section(self) -> str:
        """
        Generate the liens section for title examination report, grouped by owner.

        Returns:
            Markdown-formatted report section

        [PROPERTY_VERIFY_DEBUGLOGS]
        """
        log_debug(f"{DEBUG_TAG} Generating liens report section")

        if not self.liens:
            return """## LIENS & ENCUMBRANCES

No liens or encumbrances found affecting the property.

"""

        report = """## LIENS & ENCUMBRANCES

"""

        # Report liens by owner
        for owner in self.owners:
            owner_liens = self.liens_by_owner.get(owner, [])
            report += f"### {owner.title()}\n\n"

            if not owner_liens:
                report += "- No liens found\n\n"
            else:
                for lien in owner_liens:
                    status_icon = "!!" if lien.status == "OPEN" else "OK"
                    report += f"**{status_icon} {lien.lien_type}**\n\n"
                    report += f"| Field | Value |\n"
                    report += f"|-------|-------|\n"
                    report += f"| Instrument # | {lien.instrument_number} |\n"
                    report += f"| Recording Date | {lien.recording_date or 'N/A'} |\n"
                    report += f"| Debtor | {lien.debtor} |\n"
                    report += f"| Creditor | {lien.creditor} |\n"
                    if lien.amount:
                        report += f"| Amount | **{lien.amount}** |\n"
                    if lien.case_number:
                        report += f"| Case Number | {lien.case_number} |\n"
                    if lien.court_name:
                        report += f"| Court | {lien.court_name} |\n"
                    if lien.expiration_date:
                        report += f"| Expiration | {lien.expiration_date} |\n"
                    report += f"| Status | **{lien.status}** |\n"
                    report += "\n"

        # Report unattributed liens (potential issues)
        if self.unattributed_liens:
            report += "### Unattributed Liens (Require Review)\n\n"
            report += "**WARNING:** The following liens could not be attributed to a specific owner:\n\n"

            for lien in self.unattributed_liens:
                report += f"- **{lien.lien_type}**: {lien.debtor} (Creditor: {lien.creditor})\n"
                report += f"  - Instrument #: {lien.instrument_number}\n"
                if lien.amount:
                    report += f"  - Amount: {lien.amount}\n"
                report += "\n"

        return report

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of lien analysis."""
        open_liens = [l for l in self.liens if l.status == "OPEN"]
        total_amount = 0.0

        for lien in open_liens:
            if lien.amount:
                # Parse amount (handle formats like "$50,000.00")
                amount_str = lien.amount.replace("$", "").replace(",", "")
                try:
                    total_amount += float(amount_str)
                except ValueError:
                    pass

        return {
            "total_liens": len(self.liens),
            "open_liens": len(open_liens),
            "released_liens": len([l for l in self.liens if l.status == "RELEASED"]),
            "unattributed_liens": len(self.unattributed_liens),
            "total_open_amount": f"${total_amount:,.2f}" if total_amount > 0 else None,
            "liens_by_owner_count": {
                owner: len(liens) for owner, liens in self.liens_by_owner.items()
            }
        }

    def _is_lien_document(self, doc_type: str, doc: Dict[str, Any]) -> bool:
        """Check if document is a lien document."""
        # Check document type against known lien types
        for lien_type in LIEN_DOCUMENT_TYPES:
            if lien_type in doc_type:
                return True

        # Check is_lien_document flag from pdf_analyzer
        if doc.get("is_lien_document"):
            return True

        # Check if document has debtor/creditor fields (indicator of lien)
        if doc.get("debtor") or doc.get("creditor"):
            return True

        return False

    def _extract_lien_info(self, doc: Dict[str, Any]) -> Optional[LienAttribution]:
        """Extract lien information from document."""
        doc_file = doc.get("_source_file", "Unknown")
        doc_type = doc.get("document_type", "LIEN")
        instrument = doc.get("instrument_number") or doc.get("_instrument_number", "Unknown")

        # Determine lien type
        lien_type = doc.get("lien_type") or self._classify_lien_type(doc_type)

        # Extract debtor (the person who owes)
        debtor = doc.get("debtor") or doc.get("grantor") or ""

        # Extract creditor (the person who is owed)
        creditor = doc.get("creditor") or doc.get("grantee") or doc.get("lender") or ""

        if not debtor:
            log_warning(f"{DEBUG_TAG} No debtor found in lien document: {doc_file}")
            return None

        return LienAttribution(
            document_file=doc_file,
            document_type=doc_type,
            instrument_number=instrument,
            lien_type=lien_type,
            debtor=debtor,
            creditor=creditor,
            amount=doc.get("lien_amount") or doc.get("loan_amount"),
            case_number=doc.get("case_number"),
            court_name=doc.get("court_name"),
            recording_date=doc.get("recording_date"),
            expiration_date=doc.get("expiration_date"),
            status=self._determine_lien_status(doc)
        )

    def _classify_lien_type(self, doc_type: str) -> str:
        """Classify the lien type from document type."""
        doc_upper = doc_type.upper()

        if "JUDGMENT" in doc_upper or "ABSTRACT" in doc_upper:
            return "JUDGMENT LIEN"
        if "TAX LIEN" in doc_upper or "IRS" in doc_upper or "FTB" in doc_upper:
            if "FEDERAL" in doc_upper or "IRS" in doc_upper:
                return "FEDERAL TAX LIEN"
            if "STATE" in doc_upper or "FTB" in doc_upper:
                return "STATE TAX LIEN"
            return "TAX LIEN"
        if "MECHANIC" in doc_upper or "MATERIALMAN" in doc_upper:
            return "MECHANICS LIEN"
        if "UCC" in doc_upper or "FINANCING STATEMENT" in doc_upper:
            return "UCC FILING"
        if "LIS PENDENS" in doc_upper or "PENDING ACTION" in doc_upper:
            return "LIS PENDENS"
        if "CHILD SUPPORT" in doc_upper:
            return "CHILD SUPPORT LIEN"
        if "HOA" in doc_upper or "HOMEOWNER" in doc_upper or "ASSESSMENT" in doc_upper:
            return "HOA/ASSESSMENT LIEN"
        if "ATTACHMENT" in doc_upper:
            return "ATTACHMENT"

        return "OTHER LIEN"

    def _determine_lien_status(self, doc: Dict[str, Any]) -> str:
        """Determine the status of a lien."""
        # Check for explicit status field
        if doc.get("status"):
            status_upper = doc["status"].upper()
            if "RELEASE" in status_upper or "SATISFIED" in status_upper:
                return "RELEASED"
            if "EXPIRED" in status_upper:
                return "EXPIRED"

        # Check document type for releases
        doc_type = doc.get("document_type", "").upper()
        if any(word in doc_type for word in ["RELEASE", "SATISFACTION", "WITHDRAWAL", "DISCHARGE"]):
            return "RELEASED"

        # Check expiration date
        if doc.get("expiration_date"):
            try:
                exp_date = datetime.strptime(doc["expiration_date"], "%m/%d/%Y")
                if exp_date < datetime.now():
                    return "EXPIRED"
            except (ValueError, TypeError):
                pass

        return "OPEN"

    def _attribute_lien_to_owner(self, lien: LienAttribution) -> None:
        """
        Attribute a lien to a specific property owner.

        Compares the debtor name against all known owners to find the best match.
        """
        if not lien.debtor:
            return

        normalized_debtor = self._normalize_name(lien.debtor)
        best_match_owner = None
        best_match_score = 0.0

        for owner, normalized_owner in zip(self.owners, self.normalized_owners):
            score = self._calculate_name_similarity(normalized_debtor, normalized_owner)

            if score > best_match_score and score >= self.DEBTOR_MATCH_THRESHOLD:
                best_match_score = score
                best_match_owner = owner

        if best_match_owner:
            lien.attributed_to_owner = best_match_owner
            lien.confidence = best_match_score
            log_debug(f"{DEBUG_TAG} Attributed lien to {best_match_owner} (confidence: {best_match_score:.2%})")
        else:
            log_debug(f"{DEBUG_TAG} Could not attribute lien debtor '{lien.debtor}' to any owner")

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison."""
        if not name:
            return ""

        normalized = name.upper().strip()

        # Remove titles
        for title in NAME_TITLES:
            normalized = re.sub(rf'\b{re.escape(title)}\b', '', normalized)

        # Remove suffixes
        for suffix in NAME_SUFFIXES:
            normalized = re.sub(rf'\b{re.escape(suffix)}\b', '', normalized)

        # Remove punctuation
        normalized = re.sub(r'[.,;:\'"()-]', ' ', normalized)

        # Normalize whitespace
        normalized = ' '.join(normalized.split())

        return normalized

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names."""
        if not name1 or not name2:
            return 0.0

        # Exact match
        if name1 == name2:
            return 1.0

        # SequenceMatcher similarity
        similarity = SequenceMatcher(None, name1, name2).ratio()

        # Check if one name is contained in the other
        if name1 in name2 or name2 in name1:
            similarity = max(similarity, 0.85)

        # Check for word overlap
        words1 = set(name1.split())
        words2 = set(name2.split())
        common_words = words1.intersection(words2)

        if len(common_words) >= 2:
            word_similarity = len(common_words) / max(len(words1), len(words2))
            similarity = max(similarity, word_similarity)

        return similarity

    @staticmethod
    def _get_doc_type(doc: Dict[str, Any]) -> str:
        """Extract and normalize document type."""
        doc_type = doc.get("document_type", "UNKNOWN")
        if doc_type:
            return doc_type.upper().strip()
        return "UNKNOWN"


def analyze_liens_for_owners(
    documents: List[Dict[str, Any]],
    all_owners: List[str]
) -> Dict[str, Any]:
    """
    Convenience function to analyze all liens and attribute to owners.

    Args:
        documents: List of document analysis dictionaries
        all_owners: List of all property owner names

    Returns:
        Dictionary with lien analysis results

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    log_info(f"{DEBUG_TAG} Analyzing liens for {len(all_owners)} owners from {len(documents)} documents")

    checker = LienAttributionChecker(all_owners)
    liens = checker.analyze_all_documents(documents)

    return {
        "total_documents": len(documents),
        "total_owners": len(all_owners),
        "owners": all_owners,
        "total_liens": len(liens),
        "liens": [l.to_dict() for l in liens],
        "liens_by_owner": checker.get_liens_by_owner(),
        "unattributed_liens": [l.to_dict() for l in checker.unattributed_liens],
        "report_section": checker.generate_liens_report_section(),
        "summary": checker.get_summary()
    }


if __name__ == "__main__":
    # Test the cross-reference checker
    print("=" * 60)
    print("CrossReferenceChecker Test")
    print("=" * 60)

    # Create a test checker with two owners
    owners = ["JOHN SMITH", "MARY SMITH"]
    checker = CrossReferenceChecker(owners)

    # Test name normalization
    print("\nName Normalization Tests:")
    test_names = [
        "John Smith",
        "SMITH, JOHN",
        "Mr. John Smith Jr.",
        "JOHN A. SMITH",
        "john smith, a married man",
    ]

    for name in test_names:
        normalized = checker._normalize_name(name)
        print(f"  '{name}' -> '{normalized}'")

    # Test name extraction
    print("\nName Extraction Tests:")
    test_values = [
        "JOHN SMITH AND MARY SMITH",
        "JOHN SMITH; MARY SMITH",
        "JOHN SMITH, A MARRIED MAN",
        "JOHN SMITH AND MARY SMITH, HUSBAND AND WIFE AS JOINT TENANTS",
    ]

    for value in test_values:
        extracted = checker._extract_names(value)
        print(f"  '{value}'")
        print(f"    -> {extracted}")

    # Test document checking
    print("\nDocument Cross-Reference Tests:")

    # Document with both owners
    doc1 = {
        "_source_file": "good_deed.pdf",
        "document_type": "GRANT DEED",
        "instrument_number": "2024000123456",
        "grantor": "JOHN SMITH AND MARY SMITH, HUSBAND AND WIFE"
    }

    result1 = checker.check_document(doc1)
    print(f"\n  Good Deed (both owners):")
    print(f"    Has Issue: {result1.has_issue}")
    print(f"    Message: {result1.message}")

    # Document with only one owner
    doc2 = {
        "_source_file": "partial_deed.pdf",
        "document_type": "GRANT DEED",
        "instrument_number": "2024000654321",
        "grantor": "JOHN SMITH"
    }

    result2 = checker.check_document(doc2)
    print(f"\n  Partial Deed (one owner only):")
    print(f"    Has Issue: {result2.has_issue}")
    print(f"    Missing: {result2.missing_parties}")
    print(f"    Message: {result2.message}")

    # Reconveyance (doesn't require all owners)
    doc3 = {
        "_source_file": "reconveyance.pdf",
        "document_type": "FULL RECONVEYANCE",
        "instrument_number": "2024000111111",
        "grantor": "SOME BANK TRUSTEE"
    }

    result3 = checker.check_document(doc3)
    print(f"\n  Reconveyance (single party OK):")
    print(f"    Has Issue: {result3.has_issue}")
    print(f"    Message: {result3.message}")

    # Generate report
    print("\n" + "=" * 60)
    print("Generated Report Section:")
    print("=" * 60)
    print(checker.generate_report_section())

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
