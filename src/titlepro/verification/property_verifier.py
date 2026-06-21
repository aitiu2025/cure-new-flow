"""
Property Verifier Module for CURE Title Examination System

This module verifies that downloaded documents match the target property
by comparing addresses, APNs, cities, and other identifying information.

Key Features:
- Address normalization (ST vs STREET, AVE vs AVENUE, etc.)
- APN normalization (removes dashes, spaces for comparison)
- Fuzzy matching with similarity scores
- Confidence scoring for verification results
"""

import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from difflib import SequenceMatcher

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


# California county names for validation
CA_COUNTIES = {
    "ALAMEDA", "ALPINE", "AMADOR", "BUTTE", "CALAVERAS", "COLUSA", "CONTRA COSTA",
    "DEL NORTE", "EL DORADO", "FRESNO", "GLENN", "HUMBOLDT", "IMPERIAL", "INYO",
    "KERN", "KINGS", "LAKE", "LASSEN", "LOS ANGELES", "MADERA", "MARIN", "MARIPOSA",
    "MENDOCINO", "MERCED", "MODOC", "MONO", "MONTEREY", "NAPA", "NEVADA", "ORANGE",
    "PLACER", "PLUMAS", "RIVERSIDE", "SACRAMENTO", "SAN BENITO", "SAN BERNARDINO",
    "SAN DIEGO", "SAN FRANCISCO", "SAN JOAQUIN", "SAN LUIS OBISPO", "SAN MATEO",
    "SANTA BARBARA", "SANTA CLARA", "SANTA CRUZ", "SHASTA", "SIERRA", "SISKIYOU",
    "SOLANO", "SONOMA", "STANISLAUS", "SUTTER", "TEHAMA", "TRINITY", "TULARE",
    "TUOLUMNE", "VENTURA", "YOLO", "YUBA"
}


# Address abbreviation mappings for normalization
ADDRESS_ABBREVIATIONS = {
    # Street types
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "CIRCLE": "CIR",
    "PLACE": "PL",
    "TERRACE": "TER",
    "TRAIL": "TRL",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "FREEWAY": "FWY",
    "EXPRESSWAY": "EXPY",
    "WAY": "WAY",
    "ALLEY": "ALY",
    "PLAZA": "PLZ",
    "SQUARE": "SQ",
    # Directional
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    # Unit types
    "APARTMENT": "APT",
    "SUITE": "STE",
    "UNIT": "UNIT",
    "BUILDING": "BLDG",
    "FLOOR": "FL",
    "ROOM": "RM",
    "#": "UNIT",
    "NUMBER": "#",
}

# Create reverse mapping (abbreviation -> full word)
ABBREVIATION_TO_FULL = {v: k for k, v in ADDRESS_ABBREVIATIONS.items()}


@dataclass
class VerificationResult:
    """Result of a property verification check."""
    matches: bool
    confidence: float
    address_match: bool
    apn_match: bool
    city_match: bool
    county_match: bool
    zip_match: bool
    issues: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "matches": self.matches,
            "confidence": round(self.confidence, 3),
            "address_match": self.address_match,
            "apn_match": self.apn_match,
            "city_match": self.city_match,
            "county_match": self.county_match,
            "zip_match": self.zip_match,
            "issues": self.issues,
            "details": self.details
        }


class PropertyVerifier:
    """
    Verifies that downloaded documents match the target property.

    This class compares property identifiers from document analysis
    against the known property details to ensure we have the correct
    documents for our title examination.
    """

    # Confidence thresholds
    HIGH_CONFIDENCE = 0.90
    MEDIUM_CONFIDENCE = 0.70
    LOW_CONFIDENCE = 0.50

    # Weight factors for different matching criteria
    WEIGHTS = {
        "address": 0.35,   # Address is a strong identifier
        "apn": 0.35,       # APN is definitive when available
        "city": 0.15,      # City helps confirm location
        "county": 0.10,    # County is broader context
        "zip": 0.05,       # ZIP is additional confirmation
    }

    def __init__(
        self,
        input_address: str,
        input_city: str = None,
        input_county: str = None,
        input_apn: str = None,
        input_zip: str = None
    ):
        """
        Initialize with property details from search input.

        Args:
            input_address: Street address of the target property
            input_city: City name (optional)
            input_county: County name (optional)
            input_apn: Assessor's Parcel Number (optional)
            input_zip: ZIP code (optional)
        """
        self.input_address = input_address or ""
        self.input_city = input_city or ""
        self.input_county = input_county or ""
        self.input_apn = input_apn or ""
        self.input_zip = input_zip or ""

        # Normalize inputs for comparison
        self.normalized_address = self.normalize_address(self.input_address)
        self.normalized_city = self._normalize_text(self.input_city)
        self.normalized_county = self._normalize_county(self.input_county)
        self.normalized_apn = self.normalize_apn(self.input_apn)
        self.normalized_zip = self._normalize_zip(self.input_zip)

        log_info(f"PropertyVerifier initialized for: {self.input_address}")
        log_debug(f"Normalized address: {self.normalized_address}")
        log_debug(f"Normalized APN: {self.normalized_apn}")
        log_debug(f"Normalized city: {self.normalized_city}")
        log_debug(f"Normalized county: {self.normalized_county}")
        log_debug(f"Normalized ZIP: {self.normalized_zip}")

    def verify_document(self, doc_analysis: Dict[str, Any]) -> VerificationResult:
        """
        Verify that a document matches our target property.

        Args:
            doc_analysis: Dictionary containing extracted document data
                         (as returned by pdf_analyzer.py)

        Returns:
            VerificationResult with match status, confidence, and issues
        """
        log_info(f"Verifying document: {doc_analysis.get('_source_file', 'Unknown')}")

        issues = []
        details = {
            "document_file": doc_analysis.get("_source_file"),
            "document_type": doc_analysis.get("document_type"),
            "instrument_number": doc_analysis.get("instrument_number") or doc_analysis.get("_instrument_number"),
        }

        # Extract property info from document
        doc_address = doc_analysis.get("property_address", "")
        doc_apn = doc_analysis.get("apn", "")
        doc_legal_desc = doc_analysis.get("legal_description", "")

        # Try to extract city from address or other fields
        doc_city = self._extract_city_from_address(doc_address)

        # Compare each field
        address_result = self._compare_addresses(doc_address)
        apn_result = self._compare_apn(doc_apn)
        city_result = self._compare_city(doc_city)
        county_result = self._compare_county(doc_analysis)
        zip_result = self._compare_zip(doc_address)

        details["address_comparison"] = {
            "document": doc_address,
            "expected": self.input_address,
            "similarity": address_result["similarity"],
            "normalized_doc": address_result.get("normalized_doc"),
            "normalized_expected": self.normalized_address
        }

        details["apn_comparison"] = {
            "document": doc_apn,
            "expected": self.input_apn,
            "match": apn_result["match"],
            "normalized_doc": apn_result.get("normalized_doc"),
            "normalized_expected": self.normalized_apn
        }

        # Calculate weighted confidence score
        confidence = self._calculate_confidence(
            address_result,
            apn_result,
            city_result,
            county_result,
            zip_result
        )

        # Collect issues
        if not address_result["match"] and doc_address:
            issues.append(
                f"Address mismatch: found '{doc_address}', expected '{self.input_address}' "
                f"(similarity: {address_result['similarity']:.1%})"
            )
        elif not doc_address:
            issues.append("No property address found in document")

        if not apn_result["match"] and doc_apn and self.input_apn:
            issues.append(
                f"APN mismatch: found '{doc_apn}', expected '{self.input_apn}'"
            )
        elif not doc_apn and self.input_apn:
            issues.append("No APN found in document to verify against expected APN")

        if not city_result["match"] and doc_city and self.input_city:
            issues.append(
                f"City mismatch: found '{doc_city}', expected '{self.input_city}'"
            )

        # Determine overall match status
        # Document matches if confidence is above threshold AND no critical issues
        matches = confidence >= self.MEDIUM_CONFIDENCE

        # If we have APN and it doesn't match, that's a strong indicator of mismatch
        if self.input_apn and doc_apn and not apn_result["match"]:
            matches = False
            log_warning(f"APN mismatch is a strong indicator - marking as non-match")

        result = VerificationResult(
            matches=matches,
            confidence=confidence,
            address_match=address_result["match"],
            apn_match=apn_result["match"],
            city_match=city_result["match"],
            county_match=county_result["match"],
            zip_match=zip_result["match"],
            issues=issues,
            details=details
        )

        log_info(f"Verification result: matches={matches}, confidence={confidence:.2%}")
        if issues:
            for issue in issues:
                log_warning(f"Issue: {issue}")

        return result

    @staticmethod
    def normalize_address(address: str) -> str:
        """
        Normalize address for comparison.

        Handles common variations:
        - ST vs STREET
        - AVE vs AVENUE
        - N vs NORTH
        - Case insensitivity
        - Extra whitespace
        - Punctuation removal

        Args:
            address: Raw address string

        Returns:
            Normalized address string
        """
        if not address:
            return ""

        # Convert to uppercase
        normalized = address.upper().strip()

        # Remove common punctuation
        normalized = re.sub(r'[.,;:#]', ' ', normalized)

        # Normalize whitespace
        normalized = ' '.join(normalized.split())

        # Expand abbreviations to full words, then back to standard abbreviations
        # This ensures consistency (e.g., both "ST" and "STREET" become "ST")
        words = normalized.split()
        normalized_words = []

        for word in words:
            # Check if it's an abbreviation that should be expanded
            if word in ABBREVIATION_TO_FULL:
                # Convert to standard abbreviation form
                normalized_words.append(word)
            elif word in ADDRESS_ABBREVIATIONS:
                # Convert full word to abbreviation
                normalized_words.append(ADDRESS_ABBREVIATIONS[word])
            else:
                normalized_words.append(word)

        return ' '.join(normalized_words)

    @staticmethod
    def normalize_apn(apn: str) -> str:
        """
        Normalize APN (Assessor's Parcel Number) for comparison.

        Removes dashes, spaces, and other separators to get just digits.
        Some APNs may have letters (e.g., check digits), which are preserved.

        Args:
            apn: Raw APN string

        Returns:
            Normalized APN string (alphanumeric only)
        """
        if not apn:
            return ""

        # Remove common separators
        normalized = re.sub(r'[-\s./]', '', apn.upper().strip())

        return normalized

    def compare_addresses(self, addr1: str, addr2: str) -> float:
        """
        Return similarity score 0.0-1.0 for two addresses.

        Uses normalized comparison with sequence matching.

        Args:
            addr1: First address
            addr2: Second address

        Returns:
            Similarity score between 0.0 and 1.0
        """
        norm1 = self.normalize_address(addr1)
        norm2 = self.normalize_address(addr2)

        if not norm1 or not norm2:
            return 0.0

        # Use SequenceMatcher for fuzzy matching
        similarity = SequenceMatcher(None, norm1, norm2).ratio()

        # Bonus for exact street number match
        num1 = self._extract_street_number(norm1)
        num2 = self._extract_street_number(norm2)

        if num1 and num2:
            if num1 == num2:
                # Boost similarity if street numbers match exactly
                similarity = min(1.0, similarity + 0.1)
            else:
                # Penalize if street numbers differ
                similarity = max(0.0, similarity - 0.2)

        log_debug(f"Address comparison: '{addr1}' vs '{addr2}' = {similarity:.3f}")

        return similarity

    def _compare_addresses(self, doc_address: str) -> Dict[str, Any]:
        """Compare document address against expected address."""
        if not doc_address and not self.input_address:
            # Both empty - neutral match
            return {"match": True, "similarity": 1.0}

        if not doc_address or not self.input_address:
            # One is empty - cannot verify
            return {"match": False, "similarity": 0.0}

        normalized_doc = self.normalize_address(doc_address)
        similarity = self.compare_addresses(doc_address, self.input_address)

        # Consider it a match if similarity is above threshold
        match = similarity >= self.MEDIUM_CONFIDENCE

        return {
            "match": match,
            "similarity": similarity,
            "normalized_doc": normalized_doc
        }

    def _compare_apn(self, doc_apn: str) -> Dict[str, Any]:
        """Compare document APN against expected APN."""
        if not doc_apn and not self.input_apn:
            # Both empty - neutral match
            return {"match": True, "normalized_doc": ""}

        if not doc_apn or not self.input_apn:
            # One is empty - cannot verify
            return {"match": False, "normalized_doc": self.normalize_apn(doc_apn)}

        normalized_doc = self.normalize_apn(doc_apn)

        # APNs should match exactly after normalization
        match = normalized_doc == self.normalized_apn

        log_debug(f"APN comparison: '{normalized_doc}' vs '{self.normalized_apn}' = {match}")

        return {
            "match": match,
            "normalized_doc": normalized_doc
        }

    def _compare_city(self, doc_city: str) -> Dict[str, Any]:
        """Compare document city against expected city."""
        if not doc_city and not self.input_city:
            return {"match": True}

        if not doc_city or not self.input_city:
            return {"match": False}

        normalized_doc = self._normalize_text(doc_city)
        match = normalized_doc == self.normalized_city

        # Also check for common city name variations
        if not match:
            # Try fuzzy match for minor spelling differences
            similarity = SequenceMatcher(None, normalized_doc, self.normalized_city).ratio()
            match = similarity >= 0.85

        return {"match": match}

    def _compare_county(self, doc_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Compare document county against expected county."""
        if not self.input_county:
            return {"match": True}

        # Try to find county from document
        doc_county = ""

        # Check common fields where county might appear
        for field in ["county", "jurisdiction", "recorder_county"]:
            if doc_analysis.get(field):
                doc_county = doc_analysis[field]
                break

        # Sometimes county is in the legal description
        legal_desc = doc_analysis.get("legal_description", "")
        if not doc_county and legal_desc:
            county_match = re.search(r'COUNTY\s+OF\s+(\w+)', legal_desc.upper())
            if county_match:
                doc_county = county_match.group(1)

        if not doc_county:
            return {"match": False}

        normalized_doc = self._normalize_county(doc_county)
        match = normalized_doc == self.normalized_county

        return {"match": match}

    def _compare_zip(self, doc_address: str) -> Dict[str, Any]:
        """Extract and compare ZIP code from address."""
        if not self.input_zip:
            return {"match": True}

        if not doc_address:
            return {"match": False}

        # Try to extract ZIP from address
        zip_pattern = r'\b(\d{5})(?:-\d{4})?\b'
        match = re.search(zip_pattern, doc_address)

        if not match:
            return {"match": False}

        doc_zip = match.group(1)
        return {"match": doc_zip == self.normalized_zip}

    def _calculate_confidence(
        self,
        address_result: Dict,
        apn_result: Dict,
        city_result: Dict,
        county_result: Dict,
        zip_result: Dict
    ) -> float:
        """
        Calculate overall confidence score based on individual matches.

        Uses weighted scoring where definitive matches (like APN) have
        higher weight than contextual matches (like ZIP).
        """
        score = 0.0
        total_weight = 0.0

        # Address scoring
        if address_result.get("similarity", 0) > 0:
            score += self.WEIGHTS["address"] * address_result["similarity"]
            total_weight += self.WEIGHTS["address"]

        # APN scoring (binary match)
        if self.input_apn:
            if apn_result["match"]:
                score += self.WEIGHTS["apn"]
            total_weight += self.WEIGHTS["apn"]

        # City scoring
        if self.input_city:
            if city_result["match"]:
                score += self.WEIGHTS["city"]
            total_weight += self.WEIGHTS["city"]

        # County scoring
        if self.input_county:
            if county_result["match"]:
                score += self.WEIGHTS["county"]
            total_weight += self.WEIGHTS["county"]

        # ZIP scoring
        if self.input_zip:
            if zip_result["match"]:
                score += self.WEIGHTS["zip"]
            total_weight += self.WEIGHTS["zip"]

        # Normalize to 0-1 range
        if total_weight > 0:
            return score / total_weight

        # If we have no data to compare, return low confidence
        return 0.0

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Basic text normalization (uppercase, trim, single spaces)."""
        if not text:
            return ""
        return ' '.join(text.upper().strip().split())

    @staticmethod
    def _normalize_county(county: str) -> str:
        """Normalize county name (remove 'County' suffix, etc.)."""
        if not county:
            return ""

        normalized = county.upper().strip()

        # Remove common suffixes
        for suffix in [" COUNTY", " CO", " CO."]:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]

        return normalized.strip()

    @staticmethod
    def _normalize_zip(zip_code: str) -> str:
        """Normalize ZIP code (first 5 digits only)."""
        if not zip_code:
            return ""

        # Extract first 5 digits
        match = re.search(r'(\d{5})', zip_code)
        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _extract_street_number(address: str) -> Optional[str]:
        """Extract street number from beginning of address."""
        if not address:
            return None

        match = re.match(r'^(\d+)', address)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _extract_city_from_address(address: str) -> str:
        """
        Try to extract city from a full address string.

        Looks for patterns like "Street, City, State ZIP"
        """
        if not address:
            return ""

        # Common pattern: Street, City, State ZIP
        # or: Street City, CA 92614

        # Try comma-separated pattern
        parts = [p.strip() for p in address.split(',')]
        if len(parts) >= 2:
            # City is usually the second-to-last part before state/zip
            potential_city = parts[-2] if len(parts) >= 3 else parts[-1]

            # Remove any state abbreviation or ZIP
            potential_city = re.sub(r'\b[A-Z]{2}\b', '', potential_city)
            potential_city = re.sub(r'\b\d{5}(-\d{4})?\b', '', potential_city)

            return potential_city.strip()

        return ""


def verify_single_document(
    doc_analysis: Dict[str, Any],
    property_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Convenience function to verify a single document.

    Args:
        doc_analysis: Extracted document data from pdf_analyzer
        property_info: Dictionary with property details:
                      - address: Street address
                      - city: City name (optional)
                      - county: County name (optional)
                      - apn: APN (optional)
                      - zip: ZIP code (optional)

    Returns:
        Verification result as dictionary
    """
    log_info(f"Verifying single document against property: {property_info.get('address')}")

    verifier = PropertyVerifier(
        input_address=property_info.get("address", ""),
        input_city=property_info.get("city"),
        input_county=property_info.get("county"),
        input_apn=property_info.get("apn"),
        input_zip=property_info.get("zip")
    )

    result = verifier.verify_document(doc_analysis)
    return result.to_dict()


def verify_documents_batch(
    documents: List[Dict[str, Any]],
    property_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Verify all documents match the target property.

    This function creates a PropertyVerifier with the given property information
    and checks each document for property matches.

    Args:
        documents: List of document analysis dictionaries (from pdf_analyzer)
                   Each should contain fields like:
                   - _source_file: filename
                   - document_type: type of document
                   - property_address: address found in document
                   - apn: APN found in document
                   - grantor/grantee: party names

        property_info: Dictionary with target property details:
                      - address: Street address (required)
                      - city: City name (optional)
                      - county: County name (optional)
                      - apn: APN (optional but recommended)
                      - zip: ZIP code (optional)

    Returns:
        Dictionary with verification results:
        {
            'all_verified': True/False,
            'verification_results': [...],
            'flagged_documents': [...],
            'summary': 'X of Y documents verified',
            'confidence_average': 0.0-1.0,
            'issues_by_severity': {'HIGH': [], 'MEDIUM': [], 'LOW': []}
        }

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    log_info(f"{DEBUG_TAG} Starting batch verification for {len(documents)} documents")
    log_info(f"{DEBUG_TAG} Target property: {property_info.get('address', 'Unknown')}")

    # Validate inputs
    if not documents:
        log_warning(f"{DEBUG_TAG} No documents provided for verification")
        return {
            "all_verified": True,
            "verification_results": [],
            "flagged_documents": [],
            "summary": "No documents to verify",
            "confidence_average": 1.0,
            "issues_by_severity": {"HIGH": [], "MEDIUM": [], "LOW": []}
        }

    if not property_info.get("address"):
        log_warning(f"{DEBUG_TAG} No address provided in property_info - verification may be limited")

    # Create verifier
    verifier = PropertyVerifier(
        input_address=property_info.get("address", ""),
        input_city=property_info.get("city"),
        input_county=property_info.get("county"),
        input_apn=property_info.get("apn"),
        input_zip=property_info.get("zip")
    )

    # Track results
    verification_results = []
    flagged_documents = []
    total_confidence = 0.0
    verified_count = 0

    # Process each document
    for i, doc in enumerate(documents):
        doc_file = doc.get("_source_file", f"Document {i+1}")
        log_debug(f"{DEBUG_TAG} Verifying document {i+1}/{len(documents)}: {doc_file}")

        try:
            result = verifier.verify_document(doc)
            result_dict = result.to_dict()
            result_dict["document_index"] = i
            result_dict["document_file"] = doc_file
            result_dict["document_type"] = doc.get("document_type", "UNKNOWN")
            result_dict["instrument_number"] = doc.get("instrument_number") or doc.get("_instrument_number")

            verification_results.append(result_dict)
            total_confidence += result.confidence

            if result.matches:
                verified_count += 1
            else:
                # Categorize severity
                if result.confidence < 0.3:
                    severity = "HIGH"
                elif result.confidence < 0.6:
                    severity = "MEDIUM"
                else:
                    severity = "LOW"

                flagged_doc = {
                    "document_file": doc_file,
                    "document_type": doc.get("document_type"),
                    "instrument_number": result_dict["instrument_number"],
                    "confidence": result.confidence,
                    "severity": severity,
                    "issues": result.issues
                }
                flagged_documents.append(flagged_doc)
                log_warning(f"{DEBUG_TAG} Document flagged: {doc_file} (confidence: {result.confidence:.2%})")

        except Exception as e:
            log_error(f"{DEBUG_TAG} Error verifying document {doc_file}: {str(e)}")
            verification_results.append({
                "document_index": i,
                "document_file": doc_file,
                "matches": False,
                "confidence": 0.0,
                "error": str(e)
            })
            flagged_documents.append({
                "document_file": doc_file,
                "severity": "HIGH",
                "issues": [f"Verification error: {str(e)}"]
            })

    # Calculate averages and organize results
    confidence_average = total_confidence / len(documents) if documents else 0.0
    all_verified = verified_count == len(documents)

    # Organize issues by severity
    issues_by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for flagged in flagged_documents:
        severity = flagged.get("severity", "MEDIUM")
        issues_by_severity[severity].append(flagged)

    # Generate summary
    summary = f"{verified_count} of {len(documents)} documents verified"
    if flagged_documents:
        high_count = len(issues_by_severity["HIGH"])
        medium_count = len(issues_by_severity["MEDIUM"])
        summary += f" ({high_count} HIGH, {medium_count} MEDIUM priority issues)"

    log_info(f"{DEBUG_TAG} Batch verification complete: {summary}")
    log_info(f"{DEBUG_TAG} Average confidence: {confidence_average:.2%}")

    return {
        "all_verified": all_verified,
        "verified_count": verified_count,
        "total_documents": len(documents),
        "verification_results": verification_results,
        "flagged_documents": flagged_documents,
        "summary": summary,
        "confidence_average": round(confidence_average, 3),
        "issues_by_severity": issues_by_severity,
        "property_info_used": property_info
    }


def extract_apn_from_legal_description(legal_description: str) -> Optional[str]:
    """
    Extract APN from a legal description string.

    Legal descriptions sometimes include APN references like:
    - "APN: 123-456-78"
    - "ASSESSOR'S PARCEL NUMBER 123-456-78"
    - "PARCEL NO. 123-456-78"

    Args:
        legal_description: The legal description text

    Returns:
        Extracted APN or None

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    if not legal_description:
        return None

    legal_upper = legal_description.upper()

    # Common APN patterns in legal descriptions
    patterns = [
        r"APN[:\s]+(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})",
        r"A\.P\.N\.[:\s]+(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})",
        r"ASSESSOR'?S?\s+PARCEL\s+(?:NO\.?|NUMBER)[:\s]+(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})",
        r"PARCEL\s+(?:NO\.?|NUMBER)[:\s]+(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})",
        r"PARCEL\s+ID[:\s]+(\d{3}[-\s]?\d{3}[-\s]?\d{2,4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, legal_upper)
        if match:
            apn = match.group(1)
            log_debug(f"{DEBUG_TAG} Extracted APN from legal description: {apn}")
            return apn

    return None


def validate_california_county(county: str) -> bool:
    """
    Validate that a county name is a valid California county.

    Args:
        county: County name to validate

    Returns:
        True if valid California county, False otherwise

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    if not county:
        return False

    normalized = county.upper().strip()

    # Remove common suffixes
    for suffix in [" COUNTY", " CO", " CO."]:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)]

    return normalized in CA_COUNTIES


def compare_legal_descriptions(legal1: str, legal2: str) -> Dict[str, Any]:
    """
    Compare two legal descriptions to determine if they describe the same property.

    This is a more sophisticated comparison that looks for key matching elements:
    - Lot numbers
    - Block numbers
    - Tract names/numbers
    - Subdivision names
    - Section, Township, Range for metes and bounds

    Args:
        legal1: First legal description
        legal2: Second legal description

    Returns:
        Dictionary with comparison results:
        {
            'match': True/False,
            'confidence': 0.0-1.0,
            'matching_elements': [...],
            'differing_elements': [...]
        }

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    log_debug(f"{DEBUG_TAG} Comparing legal descriptions")

    result = {
        "match": False,
        "confidence": 0.0,
        "matching_elements": [],
        "differing_elements": [],
        "details": {}
    }

    if not legal1 or not legal2:
        log_debug(f"{DEBUG_TAG} One or both legal descriptions are empty")
        return result

    legal1_upper = legal1.upper()
    legal2_upper = legal2.upper()

    # Extract key elements from each description
    elements1 = _extract_legal_elements(legal1_upper)
    elements2 = _extract_legal_elements(legal2_upper)

    result["details"]["elements1"] = elements1
    result["details"]["elements2"] = elements2

    # Compare extracted elements
    matching = []
    differing = []
    total_weight = 0.0
    match_weight = 0.0

    # Compare lots (high weight)
    if elements1.get("lot") and elements2.get("lot"):
        total_weight += 0.3
        if elements1["lot"] == elements2["lot"]:
            matching.append(f"Lot: {elements1['lot']}")
            match_weight += 0.3
        else:
            differing.append(f"Lot mismatch: {elements1['lot']} vs {elements2['lot']}")

    # Compare blocks (high weight)
    if elements1.get("block") and elements2.get("block"):
        total_weight += 0.25
        if elements1["block"] == elements2["block"]:
            matching.append(f"Block: {elements1['block']}")
            match_weight += 0.25
        else:
            differing.append(f"Block mismatch: {elements1['block']} vs {elements2['block']}")

    # Compare tract (medium weight)
    if elements1.get("tract") and elements2.get("tract"):
        total_weight += 0.2
        if elements1["tract"] == elements2["tract"]:
            matching.append(f"Tract: {elements1['tract']}")
            match_weight += 0.2
        else:
            differing.append(f"Tract mismatch: {elements1['tract']} vs {elements2['tract']}")

    # Compare subdivision name (medium weight)
    if elements1.get("subdivision") and elements2.get("subdivision"):
        total_weight += 0.15
        # Fuzzy comparison for subdivision names
        similarity = SequenceMatcher(None, elements1["subdivision"], elements2["subdivision"]).ratio()
        if similarity > 0.8:
            matching.append(f"Subdivision: {elements1['subdivision']}")
            match_weight += 0.15 * similarity
        else:
            differing.append(f"Subdivision differs: {elements1['subdivision']} vs {elements2['subdivision']}")

    # Compare unit/apartment (low weight but important for condos)
    if elements1.get("unit") and elements2.get("unit"):
        total_weight += 0.1
        if elements1["unit"] == elements2["unit"]:
            matching.append(f"Unit: {elements1['unit']}")
            match_weight += 0.1
        else:
            differing.append(f"Unit mismatch: {elements1['unit']} vs {elements2['unit']}")

    result["matching_elements"] = matching
    result["differing_elements"] = differing

    # Calculate confidence
    if total_weight > 0:
        result["confidence"] = round(match_weight / total_weight, 3)
    else:
        # Fall back to string similarity if no elements extracted
        result["confidence"] = round(SequenceMatcher(None, legal1_upper, legal2_upper).ratio(), 3)

    # Determine match status
    result["match"] = result["confidence"] >= 0.7 and len(differing) == 0

    log_debug(f"{DEBUG_TAG} Legal description comparison: confidence={result['confidence']}, match={result['match']}")

    return result


def _extract_legal_elements(legal: str) -> Dict[str, Any]:
    """
    Extract key elements from a legal description.

    [PROPERTY_VERIFY_DEBUGLOGS]
    """
    elements = {}

    # Extract lot number
    lot_match = re.search(r'LOT\s+(\d+[A-Z]?)', legal)
    if lot_match:
        elements["lot"] = lot_match.group(1)

    # Extract block number
    block_match = re.search(r'BLOCK\s+([A-Z]|\d+)', legal)
    if block_match:
        elements["block"] = block_match.group(1)

    # Extract tract number
    tract_match = re.search(r'TRACT\s+(?:NO\.?\s*)?(\d+)', legal)
    if tract_match:
        elements["tract"] = tract_match.group(1)

    # Extract unit number (for condos)
    unit_match = re.search(r'UNIT\s+(?:NO\.?\s*)?(\d+[A-Z]?)', legal)
    if unit_match:
        elements["unit"] = unit_match.group(1)

    # Extract subdivision name
    # Common patterns: "SUBDIVISION OF..." or "...SUBDIVISION"
    subdiv_match = re.search(r'(?:IN\s+)?([A-Z][A-Z\s]+?)\s*SUBDIVISION', legal)
    if subdiv_match:
        elements["subdivision"] = subdiv_match.group(1).strip()

    # Extract book/page references
    book_match = re.search(r'BOOK\s+(\d+)', legal)
    page_match = re.search(r'PAGE\s+(\d+)', legal)
    if book_match:
        elements["book"] = book_match.group(1)
    if page_match:
        elements["page"] = page_match.group(1)

    return elements


if __name__ == "__main__":
    # Test the verifier
    print("=" * 60)
    print("PropertyVerifier Test")
    print("=" * 60)

    # Create a test verifier
    verifier = PropertyVerifier(
        input_address="123 Main Street",
        input_city="Irvine",
        input_county="Orange",
        input_apn="123-456-78",
        input_zip="92614"
    )

    # Test address normalization
    print("\nAddress Normalization Tests:")
    test_addresses = [
        "123 MAIN ST",
        "123 Main Street",
        "123 MAIN STREET APT 5",
        "123 MAIN ST, #5",
        "456 OAK AVENUE",
        "456 Oak Ave",
    ]

    for addr in test_addresses:
        normalized = PropertyVerifier.normalize_address(addr)
        print(f"  '{addr}' -> '{normalized}'")

    # Test APN normalization
    print("\nAPN Normalization Tests:")
    test_apns = [
        "123-456-78",
        "123 456 78",
        "12345678",
        "123.456.78",
    ]

    for apn in test_apns:
        normalized = PropertyVerifier.normalize_apn(apn)
        print(f"  '{apn}' -> '{normalized}'")

    # Test address comparison
    print("\nAddress Similarity Tests:")
    pairs = [
        ("123 MAIN ST", "123 Main Street"),
        ("123 MAIN ST", "124 Main Street"),
        ("123 MAIN ST APT 5", "123 Main Street #5"),
        ("456 OAK AVE", "456 Oak Avenue"),
    ]

    for addr1, addr2 in pairs:
        similarity = verifier.compare_addresses(addr1, addr2)
        print(f"  '{addr1}' vs '{addr2}' = {similarity:.2%}")

    # Test document verification
    print("\nDocument Verification Test:")
    test_doc = {
        "_source_file": "test_deed.pdf",
        "document_type": "GRANT DEED",
        "property_address": "123 Main St, Irvine, CA 92614",
        "apn": "123-456-78",
        "grantor": "JOHN SMITH",
        "grantee": "JANE DOE"
    }

    result = verifier.verify_document(test_doc)
    print(f"  Matches: {result.matches}")
    print(f"  Confidence: {result.confidence:.2%}")
    print(f"  Address Match: {result.address_match}")
    print(f"  APN Match: {result.apn_match}")
    if result.issues:
        print(f"  Issues: {result.issues}")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
