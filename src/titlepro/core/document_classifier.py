"""
Document Classifier for Title Documents - Lien Attribution System

This module classifies property documents and identifies:
1. Whether a document is a LIEN type
2. The specific lien type
3. The affected party (debtor)
4. The amount (if applicable)

Part of the CURE (Comprehensive Understanding & Risk Evaluation) system.
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Debug log tag
DEBUG_TAG = "[LIEN_ATTRIBUTION_DEBUGLOGS]"


class DocumentCategory(Enum):
    """High-level document categories for title examination."""
    OWNERSHIP = "ownership"      # Deeds, transfers
    ENCUMBRANCE = "encumbrance"  # Mortgages, DOTs
    LIEN = "lien"                # Judgments, tax liens, mechanics liens
    RELEASE = "release"          # Reconveyances, releases, satisfactions
    NOTICE = "notice"            # Lis pendens, notices
    UCC = "ucc"                  # UCC filings
    OTHER = "other"


class LienType(Enum):
    """Specific lien types that require party attribution."""
    JUDGMENT = "JUDGMENT LIEN"
    ABSTRACT_OF_JUDGMENT = "ABSTRACT OF JUDGMENT"
    LIS_PENDENS = "LIS PENDENS"
    NOTICE_OF_PENDENCY = "NOTICE OF PENDENCY"
    UCC_FILING = "UCC FILING"
    FINANCING_STATEMENT = "FINANCING STATEMENT"
    FEDERAL_TAX_LIEN = "FEDERAL TAX LIEN"
    STATE_TAX_LIEN = "STATE TAX LIEN"
    TAX_LIEN = "TAX LIEN"
    MECHANICS_LIEN = "MECHANICS LIEN"
    CHILD_SUPPORT_LIEN = "CHILD SUPPORT LIEN"
    HOA_LIEN = "HOA LIEN"
    ATTACHMENT = "ATTACHMENT"
    UNKNOWN_LIEN = "UNKNOWN LIEN"


# Document type patterns for classification
LIEN_TYPE_PATTERNS = {
    LienType.JUDGMENT: [
        r"judgment\s*lien",
        r"money\s*judgment",
        r"civil\s*judgment",
        r"default\s*judgment",
    ],
    LienType.ABSTRACT_OF_JUDGMENT: [
        r"abstract\s*of\s*judgment",
        r"abstract\s*judgment",
        r"certified\s*abstract",
    ],
    LienType.LIS_PENDENS: [
        r"lis\s*pendens",
        r"notice\s*of\s*pending\s*action",
        r"litigation\s*pending",
    ],
    LienType.NOTICE_OF_PENDENCY: [
        r"notice\s*of\s*pendency",
        r"pendency\s*of\s*action",
    ],
    LienType.UCC_FILING: [
        r"ucc[\s-]*\d",
        r"ucc\s*filing",
        r"uniform\s*commercial\s*code",
    ],
    LienType.FINANCING_STATEMENT: [
        r"financing\s*statement",
        r"security\s*interest",
    ],
    LienType.FEDERAL_TAX_LIEN: [
        r"federal\s*tax\s*lien",
        r"irs\s*lien",
        r"internal\s*revenue",
        r"notice\s*of\s*federal\s*tax\s*lien",
    ],
    LienType.STATE_TAX_LIEN: [
        r"state\s*tax\s*lien",
        r"franchise\s*tax\s*board",
        r"ftb\s*lien",
        r"employment\s*development\s*department",
        r"edd\s*lien",
    ],
    LienType.TAX_LIEN: [
        r"tax\s*lien",
        r"property\s*tax\s*lien",
    ],
    LienType.MECHANICS_LIEN: [
        r"mechanic['s]*\s*lien",
        r"materialman['s]*\s*lien",
        r"construction\s*lien",
        r"contractor['s]*\s*lien",
        r"claim\s*of\s*lien",
    ],
    LienType.CHILD_SUPPORT_LIEN: [
        r"child\s*support\s*lien",
        r"support\s*lien",
        r"dcss\s*lien",
        r"department\s*of\s*child\s*support",
    ],
    LienType.HOA_LIEN: [
        r"hoa\s*lien",
        r"homeowner['s]*\s*association\s*lien",
        r"assessment\s*lien",
        r"coa\s*lien",
    ],
    LienType.ATTACHMENT: [
        r"attachment",
        r"writ\s*of\s*attachment",
    ],
}

# Document types that are NOT liens (ownership/transfer documents)
NON_LIEN_PATTERNS = [
    r"grant\s*deed",
    r"warranty\s*deed",
    r"quitclaim\s*deed",
    r"trust\s*transfer\s*deed",
    r"deed\s*of\s*trust",
    r"mortgage(?!\s*lien)",
    r"reconveyance",
    r"full\s*reconveyance",
    r"substitution\s*of\s*trustee",
    r"assignment\s*of\s*deed\s*of\s*trust",
    r"release\s*of\s*lien",
    r"satisfaction",
    r"subordination",
    r"affidavit",
    r"power\s*of\s*attorney",
    r"easement",
    r"covenant",
    r"restriction",
]


@dataclass
class LienClassification:
    """Result of document classification for liens."""
    is_lien: bool
    lien_type: Optional[str]
    affected_party: Optional[str]
    amount: Optional[str]
    creditor: Optional[str]
    case_number: Optional[str]
    recording_date: Optional[str]
    document_type: str
    category: DocumentCategory
    confidence: float  # 0.0 to 1.0
    raw_data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_lien": self.is_lien,
            "lien_type": self.lien_type,
            "affected_party": self.affected_party,
            "amount": self.amount,
            "creditor": self.creditor,
            "case_number": self.case_number,
            "recording_date": self.recording_date,
            "document_type": self.document_type,
            "category": self.category.value,
            "confidence": self.confidence,
        }


def normalize_name(name: str) -> str:
    """
    Normalize a name for comparison.

    Args:
        name: Raw name string

    Returns:
        Normalized name (uppercase, trimmed, standardized spacing)
    """
    if not name:
        return ""

    # Convert to uppercase and strip
    normalized = name.upper().strip()

    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized)

    # Remove common suffixes that might vary
    suffixes = [r'\s+JR\.?$', r'\s+SR\.?$', r'\s+III$', r'\s+II$', r'\s+IV$']
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)

    return normalized


def extract_amount(text: str) -> Optional[str]:
    """
    Extract monetary amount from text.

    Args:
        text: Text that may contain a dollar amount

    Returns:
        Formatted amount string or None
    """
    if not text:
        return None

    # Pattern for dollar amounts
    amount_patterns = [
        r'\$[\d,]+(?:\.\d{2})?',  # $1,234.56
        r'(?:USD\s*)?[\d,]+(?:\.\d{2})?\s*(?:dollars?)?',  # 1234.56 dollars
    ]

    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(0)
            # Ensure it starts with $
            if not amount_str.startswith('$'):
                # Extract just the number
                number_match = re.search(r'[\d,]+(?:\.\d{2})?', amount_str)
                if number_match:
                    return f"${number_match.group(0)}"
            return amount_str

    return None


def extract_case_number(text: str) -> Optional[str]:
    """
    Extract case number from text.

    Args:
        text: Text that may contain a case number

    Returns:
        Case number string or None
    """
    if not text:
        return None

    # Common case number patterns
    case_patterns = [
        r'(?:case\s*(?:no\.?|number|#)?\s*:?\s*)([A-Z0-9\-]+)',
        r'(?:civil\s*(?:no\.?|number|#)?\s*:?\s*)([A-Z0-9\-]+)',
        r'(?:docket\s*(?:no\.?|number|#)?\s*:?\s*)([A-Z0-9\-]+)',
        r'\b(\d{2}[A-Z]{2}\d{5,})\b',  # Common court case format
        r'\b([A-Z]{2,4}\d{6,})\b',  # Another common format
    ]

    for pattern in case_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    return None


def identify_lien_type(doc_type: str, full_text: str = "") -> Tuple[Optional[LienType], float]:
    """
    Identify the specific lien type from document type and content.

    Args:
        doc_type: Document type string
        full_text: Full document text for additional context

    Returns:
        Tuple of (LienType, confidence)
    """
    if not doc_type:
        return None, 0.0

    combined_text = f"{doc_type} {full_text}".lower()

    logger.debug(f"{DEBUG_TAG} Identifying lien type for: {doc_type[:100]}")

    # Check for non-lien documents first
    for pattern in NON_LIEN_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            logger.debug(f"{DEBUG_TAG} Document matches non-lien pattern: {pattern}")
            return None, 0.0

    # Check each lien type pattern
    best_match = None
    best_confidence = 0.0

    for lien_type, patterns in LIEN_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                # Calculate confidence based on pattern specificity
                confidence = 0.9 if len(pattern) > 15 else 0.8

                if confidence > best_confidence:
                    best_match = lien_type
                    best_confidence = confidence
                    logger.debug(f"{DEBUG_TAG} Matched lien pattern: {pattern} -> {lien_type.value}")

    return best_match, best_confidence


def classify_document(doc_analysis: Dict[str, Any]) -> LienClassification:
    """
    Classify a document and extract lien information.

    Args:
        doc_analysis: Dictionary containing extracted document data from PDF analyzer
            Expected fields:
            - document_type: str
            - grantor: str (may be debtor for liens)
            - grantee: str (may be creditor for liens)
            - loan_amount: str (may contain lien amount)
            - notes: str (may contain additional context)
            - recording_date: str

    Returns:
        LienClassification with all extracted lien data
    """
    logger.info(f"{DEBUG_TAG} Classifying document: {doc_analysis.get('document_type', 'UNKNOWN')}")

    doc_type = doc_analysis.get("document_type", "") or ""
    notes = doc_analysis.get("notes", "") or ""
    full_text = f"{doc_type} {notes}"

    # Identify lien type
    lien_type, confidence = identify_lien_type(doc_type, full_text)
    is_lien = lien_type is not None

    # Determine document category
    if is_lien:
        if lien_type in [LienType.UCC_FILING, LienType.FINANCING_STATEMENT]:
            category = DocumentCategory.UCC
        elif lien_type in [LienType.LIS_PENDENS, LienType.NOTICE_OF_PENDENCY]:
            category = DocumentCategory.NOTICE
        else:
            category = DocumentCategory.LIEN
    elif re.search(r'reconveyance|release|satisfaction', doc_type, re.IGNORECASE):
        category = DocumentCategory.RELEASE
    elif re.search(r'deed\s*of\s*trust|mortgage', doc_type, re.IGNORECASE):
        category = DocumentCategory.ENCUMBRANCE
    elif re.search(r'deed|grant', doc_type, re.IGNORECASE):
        category = DocumentCategory.OWNERSHIP
    else:
        category = DocumentCategory.OTHER

    # Extract affected party (debtor)
    # For liens, the grantor is typically the debtor
    affected_party = None
    if is_lien:
        # Check various fields that might contain debtor name
        affected_party = (
            doc_analysis.get("debtor") or
            doc_analysis.get("defendant") or
            doc_analysis.get("grantor") or
            doc_analysis.get("trustor")
        )
        logger.debug(f"{DEBUG_TAG} Affected party identified: {affected_party}")

    # Extract creditor
    creditor = None
    if is_lien:
        creditor = (
            doc_analysis.get("creditor") or
            doc_analysis.get("plaintiff") or
            doc_analysis.get("grantee") or
            doc_analysis.get("beneficiary") or
            doc_analysis.get("lender")
        )
        logger.debug(f"{DEBUG_TAG} Creditor identified: {creditor}")

    # Extract amount
    amount = None
    if is_lien:
        # Try specific amount fields first
        amount = doc_analysis.get("lien_amount") or doc_analysis.get("judgment_amount")

        # Fall back to loan_amount for some lien types
        if not amount:
            amount = doc_analysis.get("loan_amount")

        # Try to extract from notes
        if not amount and notes:
            amount = extract_amount(notes)

        logger.debug(f"{DEBUG_TAG} Amount identified: {amount}")

    # Extract case number
    case_number = doc_analysis.get("case_number")
    if not case_number and notes:
        case_number = extract_case_number(notes)

    result = LienClassification(
        is_lien=is_lien,
        lien_type=lien_type.value if lien_type else None,
        affected_party=affected_party,
        amount=amount,
        creditor=creditor,
        case_number=case_number,
        recording_date=doc_analysis.get("recording_date"),
        document_type=doc_type,
        category=category,
        confidence=confidence,
        raw_data=doc_analysis
    )

    logger.info(f"{DEBUG_TAG} Classification result: is_lien={is_lien}, type={lien_type}, party={affected_party}")

    return result


def classify_documents_batch(documents: List[Dict[str, Any]]) -> List[LienClassification]:
    """
    Classify multiple documents.

    Args:
        documents: List of document analysis dictionaries

    Returns:
        List of LienClassification objects
    """
    logger.info(f"{DEBUG_TAG} Batch classifying {len(documents)} documents")

    results = []
    for doc in documents:
        try:
            classification = classify_document(doc)
            results.append(classification)
        except Exception as e:
            logger.error(f"{DEBUG_TAG} Error classifying document: {e}")
            # Create a default classification for errors
            results.append(LienClassification(
                is_lien=False,
                lien_type=None,
                affected_party=None,
                amount=None,
                creditor=None,
                case_number=None,
                recording_date=doc.get("recording_date"),
                document_type=doc.get("document_type", "UNKNOWN"),
                category=DocumentCategory.OTHER,
                confidence=0.0,
                raw_data=doc
            ))

    return results


def get_lien_summary(classifications: List[LienClassification]) -> Dict[str, Any]:
    """
    Generate a summary of liens from classifications.

    Args:
        classifications: List of LienClassification objects

    Returns:
        Summary dictionary with lien statistics
    """
    liens = [c for c in classifications if c.is_lien]

    lien_types = {}
    total_amount = 0.0
    affected_parties = set()
    creditors = set()

    for lien in liens:
        # Count by type
        lien_type = lien.lien_type or "UNKNOWN"
        lien_types[lien_type] = lien_types.get(lien_type, 0) + 1

        # Sum amounts
        if lien.amount:
            try:
                # Parse amount string
                amount_str = lien.amount.replace('$', '').replace(',', '')
                total_amount += float(amount_str)
            except (ValueError, AttributeError):
                pass

        # Collect parties
        if lien.affected_party:
            affected_parties.add(normalize_name(lien.affected_party))
        if lien.creditor:
            creditors.add(normalize_name(lien.creditor))

    return {
        "total_documents": len(classifications),
        "total_liens": len(liens),
        "lien_types": lien_types,
        "estimated_total_amount": f"${total_amount:,.2f}" if total_amount > 0 else None,
        "affected_parties": list(affected_parties),
        "creditors": list(creditors),
        "liens": [lien.to_dict() for lien in liens]
    }


# Utility function for testing
def test_classification():
    """Test document classification with sample data."""
    test_docs = [
        {
            "document_type": "GRANT DEED",
            "grantor": "John Smith",
            "grantee": "Mary Johnson",
            "recording_date": "01/15/2020"
        },
        {
            "document_type": "ABSTRACT OF JUDGMENT",
            "grantor": "Robert Brown",
            "grantee": "ABC Collections Inc",
            "loan_amount": "$45,000.00",
            "notes": "Case No. 2019CV123456",
            "recording_date": "03/22/2021"
        },
        {
            "document_type": "DEED OF TRUST",
            "grantor": "Mary Johnson",
            "grantee": "Bank of America",
            "loan_amount": "$500,000.00",
            "recording_date": "01/15/2020"
        },
        {
            "document_type": "NOTICE OF FEDERAL TAX LIEN",
            "grantor": "Robert Brown",
            "grantee": "Internal Revenue Service",
            "loan_amount": "$25,000.00",
            "recording_date": "06/15/2022"
        },
        {
            "document_type": "MECHANICS LIEN",
            "grantor": "Mary Johnson",
            "grantee": "XYZ Construction LLC",
            "loan_amount": "$12,500.00",
            "notes": "For unpaid construction work",
            "recording_date": "08/30/2023"
        },
        {
            "document_type": "LIS PENDENS",
            "grantor": "Mary Johnson",
            "grantee": "First National Bank",
            "notes": "Foreclosure action Case No. 2023FC789012",
            "recording_date": "09/15/2023"
        },
    ]

    print("=" * 60)
    print("Document Classification Test")
    print("=" * 60)

    classifications = classify_documents_batch(test_docs)

    for i, classification in enumerate(classifications):
        print(f"\nDocument {i+1}: {classification.document_type}")
        print(f"  Category: {classification.category.value}")
        print(f"  Is Lien: {classification.is_lien}")
        if classification.is_lien:
            print(f"  Lien Type: {classification.lien_type}")
            print(f"  Affected Party: {classification.affected_party}")
            print(f"  Creditor: {classification.creditor}")
            print(f"  Amount: {classification.amount}")
            print(f"  Case Number: {classification.case_number}")
            print(f"  Confidence: {classification.confidence:.1%}")

    print("\n" + "=" * 60)
    print("LIEN SUMMARY")
    print("=" * 60)

    summary = get_lien_summary(classifications)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    test_classification()
