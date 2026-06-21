"""
Party Attribution Tracker for CURE Title Examination System

This module tracks which documents and liens affect which parties (owners).
Key functionality:
1. Maintains a registry of all known owners/parties
2. Attributes documents to specific parties based on classification
3. Groups liens by affected party for reporting
4. Supports name matching with fuzzy logic for variations

Part of the CURE (Comprehensive Understanding & Risk Evaluation) system.
Priority 2: Lien Attribution
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Import document classifier
try:
    from titlepro.core.document_classifier import (
        classify_document,
        classify_documents_batch,
        LienClassification,
        DocumentCategory,
        LienType,
        normalize_name,
        get_lien_summary
    )
    CLASSIFIER_AVAILABLE = True
except ImportError:
    CLASSIFIER_AVAILABLE = False
    print("Warning: document_classifier not available. Some features will be limited.")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Debug log tag
DEBUG_TAG = "[LIEN_ATTRIBUTION_DEBUGLOGS]"


@dataclass
class PartyInfo:
    """Information about a party (owner/person) in title chain."""
    name: str
    normalized_name: str
    aliases: Set[str] = field(default_factory=set)
    is_current_owner: bool = False
    first_seen_date: Optional[str] = None
    last_seen_date: Optional[str] = None
    documents: List[Dict[str, Any]] = field(default_factory=list)
    liens: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "aliases": list(self.aliases),
            "is_current_owner": self.is_current_owner,
            "first_seen_date": self.first_seen_date,
            "last_seen_date": self.last_seen_date,
            "document_count": len(self.documents),
            "lien_count": len(self.liens),
            "liens": self.liens
        }


class PartyAttributionTracker:
    """
    Tracks which documents and liens affect which parties.

    This class maintains a registry of all parties encountered in the title chain
    and attributes documents (especially liens) to the appropriate party based on
    document analysis and name matching.
    """

    def __init__(self, all_owners: List[str] = None, current_owners: List[str] = None):
        """
        Initialize the party attribution tracker.

        Args:
            all_owners: List of all owner names in the title chain
            current_owners: List of current owner names (subset of all_owners)
        """
        self.parties: Dict[str, PartyInfo] = {}
        self.name_index: Dict[str, str] = {}  # normalized_name -> primary name
        self.unattributed_documents: List[Dict[str, Any]] = []

        logger.info(f"{DEBUG_TAG} Initializing PartyAttributionTracker")

        # Register initial owners
        if all_owners:
            for owner in all_owners:
                is_current = current_owners and owner in current_owners
                self.register_party(owner, is_current_owner=is_current)

        logger.info(f"{DEBUG_TAG} Registered {len(self.parties)} parties")

    def register_party(self, name: str, is_current_owner: bool = False, aliases: List[str] = None) -> str:
        """
        Register a party in the tracker.

        Args:
            name: Party name
            is_current_owner: Whether this is a current owner
            aliases: Additional name variations

        Returns:
            Normalized name key for the party
        """
        if not name:
            return ""

        normalized = self._normalize_name(name)

        # Check if this name (or a variant) is already registered
        existing_key = self._find_matching_party(name)
        if existing_key:
            # Update existing party
            party = self.parties[existing_key]
            party.aliases.add(name)
            if aliases:
                party.aliases.update(aliases)
            if is_current_owner:
                party.is_current_owner = True
            logger.debug(f"{DEBUG_TAG} Updated existing party: {existing_key}")
            return existing_key

        # Create new party
        party = PartyInfo(
            name=name,
            normalized_name=normalized,
            is_current_owner=is_current_owner,
            aliases=set(aliases) if aliases else set()
        )
        party.aliases.add(name)

        self.parties[normalized] = party
        self.name_index[normalized] = normalized

        # Also index by first/last name variants
        self._index_name_variants(name, normalized)

        logger.info(f"{DEBUG_TAG} Registered new party: {name} -> {normalized}")
        return normalized

    def _normalize_name(self, name: str) -> str:
        """
        Normalize a name for consistent comparison.

        Args:
            name: Raw name string

        Returns:
            Normalized name
        """
        if not name:
            return ""

        # Use classifier's normalize_name if available
        if CLASSIFIER_AVAILABLE:
            return normalize_name(name)

        # Fallback normalization
        normalized = name.upper().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        # Remove common suffixes
        normalized = re.sub(r'\s+(JR\.?|SR\.?|III|II|IV)$', '', normalized, flags=re.IGNORECASE)
        return normalized

    def _index_name_variants(self, name: str, primary_key: str):
        """
        Index common name variants for better matching.

        Args:
            name: Original name
            primary_key: Primary normalized key
        """
        normalized = self._normalize_name(name)

        # Index the full normalized name
        self.name_index[normalized] = primary_key

        # Try to extract first and last name for partial matching
        parts = normalized.split()
        if len(parts) >= 2:
            # Index "LAST, FIRST" format
            last_first = f"{parts[-1]}, {parts[0]}"
            self.name_index[last_first] = primary_key

            # Index "FIRST LAST" if different from normalized
            first_last = f"{parts[0]} {parts[-1]}"
            if first_last != normalized:
                self.name_index[first_last] = primary_key

            # Index just the last name (for broader matching)
            # Note: This could cause false matches, so we only use it as fallback
            # self.name_index[parts[-1]] = primary_key

    def _find_matching_party(self, name: str) -> Optional[str]:
        """
        Find a matching party for a given name.

        Args:
            name: Name to search for

        Returns:
            Primary key of matching party, or None
        """
        if not name:
            return None

        normalized = self._normalize_name(name)

        # Direct match
        if normalized in self.parties:
            return normalized

        # Check name index
        if normalized in self.name_index:
            return self.name_index[normalized]

        # Check aliases of existing parties
        for key, party in self.parties.items():
            if normalized in [self._normalize_name(a) for a in party.aliases]:
                return key

        # Fuzzy matching - check if name contains or is contained by party name
        for key, party in self.parties.items():
            party_normalized = party.normalized_name

            # Check if one name contains the other (with word boundaries)
            if self._names_match_fuzzy(normalized, party_normalized):
                logger.debug(f"{DEBUG_TAG} Fuzzy match: {name} -> {party.name}")
                return key

        return None

    def _names_match_fuzzy(self, name1: str, name2: str) -> bool:
        """
        Check if two names match with fuzzy logic.

        Handles cases like:
        - "JOHN SMITH" matches "JOHN A SMITH"
        - "JOHN SMITH" matches "JOHN SMITH JR"
        - "J SMITH" might match "JOHN SMITH"

        Args:
            name1: First name (normalized)
            name2: Second name (normalized)

        Returns:
            True if names likely refer to same person
        """
        if not name1 or not name2:
            return False

        # Exact match
        if name1 == name2:
            return True

        parts1 = name1.split()
        parts2 = name2.split()

        # Check if last names match
        if parts1[-1] != parts2[-1]:
            return False

        # If last names match and first initial matches, likely same person
        if parts1[0][0] == parts2[0][0]:
            # Additional check: first name is prefix or full match
            if parts1[0].startswith(parts2[0]) or parts2[0].startswith(parts1[0]):
                return True
            # First initial only - could be same person
            if len(parts1[0]) == 1 or len(parts2[0]) == 1:
                return True

        return False

    def attribute_document(self, doc: Dict[str, Any], classification: LienClassification = None) -> Dict[str, Any]:
        """
        Attribute a document to a specific party based on classification.

        Args:
            doc: Document analysis data
            classification: Optional pre-computed classification

        Returns:
            Attribution result with party and document details
        """
        logger.debug(f"{DEBUG_TAG} Attributing document: {doc.get('document_type', 'UNKNOWN')}")

        # Classify document if not already done
        if classification is None and CLASSIFIER_AVAILABLE:
            classification = classify_document(doc)

        result = {
            "document_type": doc.get("document_type"),
            "instrument_number": doc.get("instrument_number") or doc.get("_instrument_number"),
            "recording_date": doc.get("recording_date"),
            "attributed_to": None,
            "attribution_reason": None,
            "is_lien": False,
            "lien_details": None
        }

        # Determine the affected party
        affected_party_name = None
        attribution_reason = None

        if classification and classification.is_lien:
            # For liens, the affected party is the debtor
            result["is_lien"] = True
            result["lien_details"] = classification.to_dict()

            affected_party_name = classification.affected_party
            attribution_reason = f"Debtor on {classification.lien_type or 'lien'}"

            if not affected_party_name:
                # Try to get from doc directly
                affected_party_name = doc.get("debtor") or doc.get("defendant") or doc.get("grantor")
                attribution_reason = "Debtor/Defendant from document"

            logger.debug(f"{DEBUG_TAG} Lien document, affected party: {affected_party_name}")
        else:
            # For non-lien documents, use grantor/grantee
            # The party "affected" depends on context - for ownership docs, both matter
            affected_party_name = doc.get("grantor") or doc.get("grantee")
            attribution_reason = "Party on deed/document"

        # Find matching party
        if affected_party_name:
            party_key = self._find_matching_party(affected_party_name)

            if party_key:
                party = self.parties[party_key]
                result["attributed_to"] = party.name
                result["attribution_reason"] = attribution_reason

                # Add document to party's records
                if classification and classification.is_lien:
                    lien_record = {
                        "instrument_number": result["instrument_number"],
                        "lien_type": classification.lien_type,
                        "amount": classification.amount,
                        "creditor": classification.creditor,
                        "case_number": classification.case_number,
                        "recording_date": classification.recording_date,
                        "document_type": classification.document_type,
                        "raw_data": doc
                    }
                    party.liens.append(lien_record)
                    logger.info(f"{DEBUG_TAG} Attributed lien to {party.name}: {classification.lien_type}")
                else:
                    party.documents.append(doc)
                    logger.debug(f"{DEBUG_TAG} Attributed document to {party.name}")

                # Update date range
                rec_date = doc.get("recording_date")
                if rec_date:
                    if not party.first_seen_date or rec_date < party.first_seen_date:
                        party.first_seen_date = rec_date
                    if not party.last_seen_date or rec_date > party.last_seen_date:
                        party.last_seen_date = rec_date
            else:
                # No matching party found - register new party
                logger.info(f"{DEBUG_TAG} No matching party for {affected_party_name}, registering new")
                new_key = self.register_party(affected_party_name)
                if new_key:
                    result["attributed_to"] = affected_party_name
                    result["attribution_reason"] = f"{attribution_reason} (new party)"

                    # Re-attribute to newly registered party
                    party = self.parties[new_key]
                    if classification and classification.is_lien:
                        lien_record = {
                            "instrument_number": result["instrument_number"],
                            "lien_type": classification.lien_type,
                            "amount": classification.amount,
                            "creditor": classification.creditor,
                            "case_number": classification.case_number,
                            "recording_date": classification.recording_date,
                            "document_type": classification.document_type,
                            "raw_data": doc
                        }
                        party.liens.append(lien_record)
                    else:
                        party.documents.append(doc)
        else:
            # Couldn't determine affected party
            logger.warning(f"{DEBUG_TAG} Could not determine affected party for document")
            self.unattributed_documents.append(doc)
            result["attribution_reason"] = "Could not determine affected party"

        return result

    def attribute_documents_batch(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Attribute multiple documents.

        Args:
            documents: List of document analysis dictionaries

        Returns:
            List of attribution results
        """
        logger.info(f"{DEBUG_TAG} Batch attributing {len(documents)} documents")

        results = []

        # Classify all documents first if classifier available
        if CLASSIFIER_AVAILABLE:
            classifications = classify_documents_batch(documents)
            for doc, classification in zip(documents, classifications):
                result = self.attribute_document(doc, classification)
                results.append(result)
        else:
            for doc in documents:
                result = self.attribute_document(doc)
                results.append(result)

        logger.info(f"{DEBUG_TAG} Attributed {len(results)} documents")
        return results

    def get_liens_by_party(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get liens grouped by affected party.

        Returns:
            Dictionary mapping party name to list of their liens
        """
        result = {}
        for key, party in self.parties.items():
            if party.liens:
                result[party.name] = party.liens
        return result

    def get_party_summary(self, party_name: str) -> Optional[Dict[str, Any]]:
        """
        Get summary for a specific party.

        Args:
            party_name: Name of party to summarize

        Returns:
            Summary dictionary or None if party not found
        """
        party_key = self._find_matching_party(party_name)
        if not party_key:
            logger.warning(f"{DEBUG_TAG} Party not found: {party_name}")
            return None

        party = self.parties[party_key]

        # Calculate total lien amount
        total_lien_amount = 0.0
        for lien in party.liens:
            amount = lien.get("amount")
            if amount:
                try:
                    amount_str = str(amount).replace('$', '').replace(',', '')
                    total_lien_amount += float(amount_str)
                except (ValueError, TypeError):
                    pass

        summary = {
            "name": party.name,
            "normalized_name": party.normalized_name,
            "aliases": list(party.aliases),
            "is_current_owner": party.is_current_owner,
            "first_seen_date": party.first_seen_date,
            "last_seen_date": party.last_seen_date,
            "document_count": len(party.documents),
            "lien_count": len(party.liens),
            "total_lien_amount": f"${total_lien_amount:,.2f}" if total_lien_amount > 0 else None,
            "liens": party.liens,
            "lien_types": list(set(l.get("lien_type") for l in party.liens if l.get("lien_type")))
        }

        return summary

    def get_all_parties_summary(self) -> Dict[str, Any]:
        """
        Get summary of all parties and their liens.

        Returns:
            Comprehensive summary dictionary
        """
        all_parties = []
        parties_with_liens = []
        total_liens = 0
        total_lien_amount = 0.0

        for key, party in self.parties.items():
            party_summary = self.get_party_summary(party.name)
            all_parties.append(party_summary)

            if party.liens:
                parties_with_liens.append(party_summary)
                total_liens += len(party.liens)

                # Sum lien amounts
                for lien in party.liens:
                    amount = lien.get("amount")
                    if amount:
                        try:
                            amount_str = str(amount).replace('$', '').replace(',', '')
                            total_lien_amount += float(amount_str)
                        except (ValueError, TypeError):
                            pass

        return {
            "total_parties": len(self.parties),
            "parties_with_liens": len(parties_with_liens),
            "total_liens": total_liens,
            "total_lien_amount": f"${total_lien_amount:,.2f}" if total_lien_amount > 0 else None,
            "unattributed_documents": len(self.unattributed_documents),
            "parties": all_parties,
            "liens_by_party": self.get_liens_by_party()
        }

    def get_current_owner_liens(self) -> Dict[str, Any]:
        """
        Get liens specifically affecting current owners.

        This is critical for title examination - liens against current owners
        must be satisfied at closing.

        Returns:
            Dictionary with current owner lien information
        """
        current_owner_liens = []
        total_amount = 0.0

        for key, party in self.parties.items():
            if party.is_current_owner and party.liens:
                for lien in party.liens:
                    current_owner_liens.append({
                        "owner": party.name,
                        **lien
                    })
                    amount = lien.get("amount")
                    if amount:
                        try:
                            amount_str = str(amount).replace('$', '').replace(',', '')
                            total_amount += float(amount_str)
                        except (ValueError, TypeError):
                            pass

        return {
            "has_current_owner_liens": len(current_owner_liens) > 0,
            "lien_count": len(current_owner_liens),
            "total_amount": f"${total_amount:,.2f}" if total_amount > 0 else None,
            "liens": current_owner_liens,
            "action_required": "Liens against current owners must be satisfied at closing" if current_owner_liens else None
        }

    def generate_lien_report_section(self) -> str:
        """
        Generate a markdown report section for liens.

        Returns:
            Markdown string for lien section of report
        """
        md = "## JUDGMENTS, LIENS, AND UCCs\n\n"

        liens_by_party = self.get_liens_by_party()

        if not liens_by_party:
            md += "No judgments, liens, or UCCs found affecting any parties in the title chain.\n"
            return md

        for party_name, liens in liens_by_party.items():
            party_key = self._find_matching_party(party_name)
            party = self.parties.get(party_key)

            # Add warning for current owners
            owner_warning = " **[CURRENT OWNER]**" if party and party.is_current_owner else ""

            md += f"### Liens Against: {party_name}{owner_warning}\n\n"

            for lien in liens:
                md += f"#### {lien.get('lien_type', 'LIEN')} - {lien.get('document_type', 'Document')}\n\n"
                md += "| Field | Value |\n"
                md += "|-------|-------|\n"
                md += f"| Instrument # | {lien.get('instrument_number', 'N/A')} |\n"
                md += f"| Recording Date | {lien.get('recording_date', 'N/A')} |\n"
                if lien.get('amount'):
                    md += f"| Amount | **{lien.get('amount')}** |\n"
                if lien.get('creditor'):
                    md += f"| Creditor | {lien.get('creditor')} |\n"
                if lien.get('case_number'):
                    md += f"| Case Number | {lien.get('case_number')} |\n"
                md += "\n"

        # Add summary for current owners
        current_owner_info = self.get_current_owner_liens()
        if current_owner_info["has_current_owner_liens"]:
            md += "---\n\n"
            md += "### CRITICAL: Current Owner Liens\n\n"
            md += f"**{current_owner_info['lien_count']} lien(s) found against current owner(s)**\n\n"
            if current_owner_info['total_amount']:
                md += f"**Total Amount: {current_owner_info['total_amount']}**\n\n"
            md += f"*{current_owner_info['action_required']}*\n\n"

        return md

    def save_to_json(self, filepath: Path) -> None:
        """
        Save attribution data to JSON file.

        Args:
            filepath: Path to save JSON file
        """
        data = {
            "generated_at": datetime.now().isoformat(),
            "summary": self.get_all_parties_summary(),
            "current_owner_liens": self.get_current_owner_liens(),
            "parties": {key: party.to_dict() for key, party in self.parties.items()},
            "unattributed_documents": self.unattributed_documents
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"{DEBUG_TAG} Saved attribution data to {filepath}")


def test_party_attribution():
    """Test party attribution with sample data."""
    print("=" * 60)
    print("Party Attribution Tracker Test")
    print("=" * 60)

    # Initialize with known owners
    all_owners = ["John Smith", "Mary Johnson", "Robert Brown"]
    current_owners = ["Mary Johnson"]

    tracker = PartyAttributionTracker(
        all_owners=all_owners,
        current_owners=current_owners
    )

    # Test documents
    test_docs = [
        {
            "document_type": "GRANT DEED",
            "grantor": "John Smith",
            "grantee": "Mary Johnson",
            "recording_date": "01/15/2020",
            "instrument_number": "2020000012345"
        },
        {
            "document_type": "ABSTRACT OF JUDGMENT",
            "debtor": "Mary Johnson",
            "creditor": "ABC Collections Inc",
            "lien_amount": "$45,000.00",
            "case_number": "2019CV123456",
            "recording_date": "03/22/2021",
            "instrument_number": "2021000034567"
        },
        {
            "document_type": "DEED OF TRUST",
            "grantor": "Mary Johnson",
            "grantee": "Bank of America",
            "loan_amount": "$500,000.00",
            "recording_date": "01/15/2020",
            "instrument_number": "2020000012346"
        },
        {
            "document_type": "NOTICE OF FEDERAL TAX LIEN",
            "debtor": "Robert Brown",
            "creditor": "Internal Revenue Service",
            "lien_amount": "$25,000.00",
            "recording_date": "06/15/2022",
            "instrument_number": "2022000056789"
        },
        {
            "document_type": "MECHANICS LIEN",
            "debtor": "Mary Johnson",
            "creditor": "XYZ Construction LLC",
            "lien_amount": "$12,500.00",
            "recording_date": "08/30/2023",
            "instrument_number": "2023000078901"
        },
        {
            "document_type": "LIS PENDENS",
            "debtor": "Mary Johnson",
            "creditor": "First National Bank",
            "case_number": "2023FC789012",
            "recording_date": "09/15/2023",
            "instrument_number": "2023000089012"
        },
    ]

    # Attribute all documents
    print("\nAttributing documents...")
    results = tracker.attribute_documents_batch(test_docs)

    for result in results:
        print(f"\n{result['document_type']}:")
        print(f"  Attributed to: {result['attributed_to']}")
        print(f"  Reason: {result['attribution_reason']}")
        if result['is_lien']:
            print(f"  Lien Type: {result['lien_details'].get('lien_type')}")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    summary = tracker.get_all_parties_summary()
    print(f"\nTotal Parties: {summary['total_parties']}")
    print(f"Parties with Liens: {summary['parties_with_liens']}")
    print(f"Total Liens: {summary['total_liens']}")
    print(f"Total Lien Amount: {summary['total_lien_amount']}")

    # Print liens by party
    print("\n" + "-" * 40)
    print("LIENS BY PARTY")
    print("-" * 40)

    liens_by_party = tracker.get_liens_by_party()
    for party, liens in liens_by_party.items():
        print(f"\n{party}:")
        for lien in liens:
            print(f"  - {lien['lien_type']}: {lien.get('amount', 'N/A')} ({lien['instrument_number']})")

    # Print current owner liens
    print("\n" + "-" * 40)
    print("CURRENT OWNER LIENS (CRITICAL)")
    print("-" * 40)

    current_owner_liens = tracker.get_current_owner_liens()
    print(f"\nHas current owner liens: {current_owner_liens['has_current_owner_liens']}")
    print(f"Lien count: {current_owner_liens['lien_count']}")
    print(f"Total amount: {current_owner_liens['total_amount']}")
    if current_owner_liens['action_required']:
        print(f"ACTION: {current_owner_liens['action_required']}")

    # Generate report section
    print("\n" + "=" * 60)
    print("MARKDOWN REPORT SECTION")
    print("=" * 60)
    print(tracker.generate_lien_report_section())


if __name__ == "__main__":
    test_party_attribution()
