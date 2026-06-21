"""
Document Deduplicator Module for CURE System.

This module provides document deduplication functionality for title searches
where the same document may be found under multiple owner names.

Key features:
- Tracks documents by document_number as unique key
- Tracks which search name(s) each document was found under
- Merges document metadata from multiple sources
- Returns deduplicated list with name associations

[DEDUPLICATION_DEBUGLOGS] - All logging tagged for easy filtering
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field, asdict

# Set up module logger
logger = logging.getLogger(__name__)


def log_debug(msg: str) -> None:
    """Log debug message with DEDUPLICATION tag."""
    logger.debug(f"[DEDUPLICATION_DEBUGLOGS] {msg}")
    print(f"[DEDUPLICATION_DEBUGLOGS][DEBUG] {msg}", flush=True)


def log_info(msg: str) -> None:
    """Log info message with DEDUPLICATION tag."""
    logger.info(f"[DEDUPLICATION_DEBUGLOGS] {msg}")
    print(f"[DEDUPLICATION_DEBUGLOGS][INFO] {msg}", flush=True)


def log_warn(msg: str) -> None:
    """Log warning message with DEDUPLICATION tag."""
    logger.warning(f"[DEDUPLICATION_DEBUGLOGS] {msg}")
    print(f"[DEDUPLICATION_DEBUGLOGS][WARN] {msg}", flush=True)


def log_error(msg: str) -> None:
    """Log error message with DEDUPLICATION tag."""
    logger.error(f"[DEDUPLICATION_DEBUGLOGS] {msg}")
    print(f"[DEDUPLICATION_DEBUGLOGS][ERROR] {msg}", flush=True)


@dataclass
class DocumentRecord:
    """
    Represents a unique document with metadata from potentially multiple sources.

    Attributes:
        document_number: Unique instrument/document number (primary key)
        year: Recording year
        document_type: Type of document (GRANT DEED, DEED OF TRUST, etc.)
        recording_date: Date document was recorded
        grantors: Grantor names
        grantees: Grantee names
        pages: Number of pages
        found_via_names: List of search names this document was found under
        first_found_at: Timestamp when document was first discovered
        last_updated_at: Timestamp when document was last updated
        is_party_specific: Whether document is specific to one party only
        additional_metadata: Any extra metadata from different sources
    """
    document_number: str
    year: str = ""
    document_type: str = ""
    recording_date: str = ""
    grantors: str = ""
    grantees: str = ""
    pages: str = ""
    found_via_names: List[str] = field(default_factory=list)
    first_found_at: str = ""
    last_updated_at: str = ""
    is_party_specific: bool = False
    additional_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, handling nested structures."""
        return {
            "document_number": self.document_number,
            "year": self.year,
            "document_type": self.document_type,
            "recording_date": self.recording_date,
            "grantors": self.grantors,
            "grantees": self.grantees,
            "pages": self.pages,
            "found_via_names": list(self.found_via_names),
            "first_found_at": self.first_found_at,
            "last_updated_at": self.last_updated_at,
            "is_party_specific": self.is_party_specific,
            "additional_metadata": dict(self.additional_metadata)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentRecord":
        """Create DocumentRecord from dictionary."""
        return cls(
            document_number=data.get("document_number", ""),
            year=data.get("year", ""),
            document_type=data.get("document_type", ""),
            recording_date=data.get("recording_date", ""),
            grantors=data.get("grantors", ""),
            grantees=data.get("grantees", ""),
            pages=str(data.get("pages", "")),
            found_via_names=list(data.get("found_via_names", [])),
            first_found_at=data.get("first_found_at", ""),
            last_updated_at=data.get("last_updated_at", ""),
            is_party_specific=data.get("is_party_specific", False),
            additional_metadata=dict(data.get("additional_metadata", {}))
        )


class DocumentDeduplicator:
    """
    Deduplicates documents across multiple name searches.

    This class tracks documents by their document_number as a unique key
    and maintains associations of which search name(s) each document was found under.

    Usage:
        deduplicator = DocumentDeduplicator()

        # Add documents from first search
        deduplicator.add_documents(docs_from_search_1, "SMITH JOHN")

        # Add documents from second search
        deduplicator.add_documents(docs_from_search_2, "SMITH JANE")

        # Get deduplicated list
        unique_docs = deduplicator.get_deduplicated()

        # Check stats
        print(f"Unique documents: {deduplicator.get_unique_count()}")
        print(f"Total found: {deduplicator.get_total_found_count()}")
    """

    def __init__(self):
        """Initialize the deduplicator."""
        self.documents: Dict[str, DocumentRecord] = {}  # doc_number -> DocumentRecord
        self.name_to_documents: Dict[str, Set[str]] = {}  # search_name -> set of doc_numbers
        self._total_found_count: int = 0
        self._created_at: str = datetime.now().isoformat()
        log_info("DocumentDeduplicator initialized")

    def _normalize_doc_number(self, doc_num: str) -> str:
        """
        Normalize document number for consistent comparison.

        Removes leading zeros from year portion while preserving document sequence.
        Example: "2023-0003138" stays as-is, but leading/trailing whitespace is stripped.
        """
        if not doc_num:
            return ""
        return str(doc_num).strip()

    def _normalize_name(self, name: str) -> str:
        """
        Normalize search name for consistent tracking.

        Converts to uppercase and removes extra whitespace.
        """
        if not name:
            return ""
        return " ".join(name.upper().split())

    def _extract_year_from_doc(self, doc: Dict[str, Any]) -> str:
        """
        Extract year from document, trying multiple fields.
        """
        # Try explicit year field
        if doc.get("year"):
            return str(doc["year"])

        # Try to extract from document_number (format: YYYY-XXXXXXX)
        doc_num = doc.get("document_number", "")
        if "-" in doc_num:
            year_part = doc_num.split("-")[0]
            if len(year_part) == 4 and year_part.isdigit():
                return year_part

        # Try to extract from recording_date
        rec_date = doc.get("recording_date", "")
        if rec_date:
            # Try MM/DD/YYYY format
            parts = rec_date.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                return parts[2]
            # Try YYYY-MM-DD format
            parts = rec_date.split("-")
            if len(parts) == 3 and len(parts[0]) == 4:
                return parts[0]

        return ""

    def _merge_document_data(self, existing: DocumentRecord, new_doc: Dict[str, Any]) -> None:
        """
        Merge new document data into existing record.

        Updates fields only if the new value is more complete (non-empty when existing is empty).
        """
        now = datetime.now().isoformat()
        existing.last_updated_at = now

        # Update fields if new data is more complete
        if not existing.year and new_doc.get("year"):
            existing.year = str(new_doc["year"])

        if not existing.document_type and new_doc.get("document_type"):
            existing.document_type = new_doc["document_type"]

        if not existing.recording_date and new_doc.get("recording_date"):
            existing.recording_date = new_doc["recording_date"]

        if not existing.grantors and new_doc.get("grantors"):
            existing.grantors = new_doc["grantors"]

        if not existing.grantees and new_doc.get("grantees"):
            existing.grantees = new_doc["grantees"]

        if not existing.pages and new_doc.get("pages"):
            existing.pages = str(new_doc["pages"])

        # Merge additional metadata
        for key, value in new_doc.items():
            if key not in ["document_number", "year", "document_type", "recording_date",
                          "grantors", "grantees", "pages", "found_via_names"]:
                if value and key not in existing.additional_metadata:
                    existing.additional_metadata[key] = value

    def add_document(self, doc: Dict[str, Any], source_name: str) -> Tuple[bool, str]:
        """
        Add a single document, tracking which name it was found under.

        Args:
            doc: Document dictionary with at minimum 'document_number' field
            source_name: The search name this document was found under

        Returns:
            Tuple of (is_new, doc_number):
                - is_new: True if this is a new document, False if duplicate
                - doc_number: The normalized document number
        """
        doc_num = self._normalize_doc_number(doc.get("document_number", ""))
        if not doc_num:
            log_warn("Attempted to add document without document_number, skipping")
            return (False, "")

        normalized_name = self._normalize_name(source_name)
        self._total_found_count += 1

        # Track name -> documents mapping
        if normalized_name not in self.name_to_documents:
            self.name_to_documents[normalized_name] = set()
        self.name_to_documents[normalized_name].add(doc_num)

        # Check if document already exists
        if doc_num in self.documents:
            # Document exists - add the new source name and merge data
            existing = self.documents[doc_num]
            if normalized_name not in existing.found_via_names:
                existing.found_via_names.append(normalized_name)
                log_debug(f"Document {doc_num} also found via '{normalized_name}' (now {len(existing.found_via_names)} names)")

            self._merge_document_data(existing, doc)
            return (False, doc_num)

        # New document
        now = datetime.now().isoformat()
        year = self._extract_year_from_doc(doc)

        record = DocumentRecord(
            document_number=doc_num,
            year=year,
            document_type=doc.get("document_type", ""),
            recording_date=doc.get("recording_date", ""),
            grantors=doc.get("grantors", ""),
            grantees=doc.get("grantees", ""),
            pages=str(doc.get("pages", "")),
            found_via_names=[normalized_name],
            first_found_at=now,
            last_updated_at=now,
            is_party_specific=False
        )

        # Copy any additional fields
        for key, value in doc.items():
            if key not in ["document_number", "year", "document_type", "recording_date",
                          "grantors", "grantees", "pages"]:
                record.additional_metadata[key] = value

        self.documents[doc_num] = record
        log_debug(f"Added new document {doc_num} ({record.document_type}) via '{normalized_name}'")

        return (True, doc_num)

    def add_documents(self, docs: List[Dict[str, Any]], source_name: str) -> Dict[str, Any]:
        """
        Add multiple documents from a single search.

        Args:
            docs: List of document dictionaries
            source_name: The search name these documents were found under

        Returns:
            Dictionary with statistics:
                - total: Total documents in input
                - new: Number of new (unique) documents added
                - duplicates: Number of documents that were already known
                - doc_numbers: List of all document numbers processed
        """
        log_info(f"Adding {len(docs)} documents from search for '{source_name}'")

        new_count = 0
        duplicate_count = 0
        doc_numbers = []

        for doc in docs:
            is_new, doc_num = self.add_document(doc, source_name)
            if doc_num:
                doc_numbers.append(doc_num)
                if is_new:
                    new_count += 1
                else:
                    duplicate_count += 1

        result = {
            "total": len(docs),
            "new": new_count,
            "duplicates": duplicate_count,
            "doc_numbers": doc_numbers
        }

        log_info(f"Results for '{source_name}': {new_count} new, {duplicate_count} duplicates")
        return result

    def get_deduplicated(self) -> List[Dict[str, Any]]:
        """
        Return deduplicated documents with name associations.

        Documents are sorted by document_number (most recent first).

        Returns:
            List of document dictionaries with 'found_via_names' field populated
        """
        docs = [record.to_dict() for record in self.documents.values()]

        # Sort by document number (most recent first - higher numbers are newer)
        docs.sort(key=lambda d: d.get("document_number", ""), reverse=True)

        log_info(f"Returning {len(docs)} deduplicated documents")
        return docs

    def get_unique_count(self) -> int:
        """Return count of unique documents."""
        return len(self.documents)

    def get_total_found_count(self) -> int:
        """Return total number of documents found across all searches (including duplicates)."""
        return self._total_found_count

    def get_duplicate_count(self) -> int:
        """Return number of duplicate finds (documents found under multiple names)."""
        return self._total_found_count - len(self.documents)

    def get_documents_for_name(self, name: str) -> List[Dict[str, Any]]:
        """
        Return all documents associated with a specific search name.

        Args:
            name: The search name to filter by

        Returns:
            List of document dictionaries found under this name
        """
        normalized_name = self._normalize_name(name)
        doc_numbers = self.name_to_documents.get(normalized_name, set())

        docs = []
        for doc_num in doc_numbers:
            if doc_num in self.documents:
                docs.append(self.documents[doc_num].to_dict())

        docs.sort(key=lambda d: d.get("document_number", ""), reverse=True)
        log_debug(f"Found {len(docs)} documents for name '{name}'")
        return docs

    def get_multi_name_documents(self) -> List[Dict[str, Any]]:
        """
        Return documents that were found under multiple search names.

        These are documents that appear in searches for different parties,
        indicating they involve multiple people (e.g., joint ownership transfers).

        Returns:
            List of document dictionaries found under 2+ names
        """
        multi_name_docs = []
        for record in self.documents.values():
            if len(record.found_via_names) > 1:
                multi_name_docs.append(record.to_dict())

        multi_name_docs.sort(key=lambda d: d.get("document_number", ""), reverse=True)
        log_debug(f"Found {len(multi_name_docs)} documents with multiple name associations")
        return multi_name_docs

    def get_single_name_documents(self) -> List[Dict[str, Any]]:
        """
        Return documents that were found under only one search name.

        These might be party-specific documents (e.g., individual mortgages).

        Returns:
            List of document dictionaries found under exactly 1 name
        """
        single_name_docs = []
        for record in self.documents.values():
            if len(record.found_via_names) == 1:
                record.is_party_specific = True
                single_name_docs.append(record.to_dict())

        single_name_docs.sort(key=lambda d: d.get("document_number", ""), reverse=True)
        log_debug(f"Found {len(single_name_docs)} single-name documents")
        return single_name_docs

    def get_names_searched(self) -> List[str]:
        """Return list of all names that have been searched."""
        return list(self.name_to_documents.keys())

    def get_statistics(self) -> Dict[str, Any]:
        """
        Return comprehensive statistics about the deduplication.

        Returns:
            Dictionary with various statistics
        """
        multi_name_count = sum(1 for r in self.documents.values() if len(r.found_via_names) > 1)
        single_name_count = len(self.documents) - multi_name_count

        stats = {
            "created_at": self._created_at,
            "names_searched": list(self.name_to_documents.keys()),
            "total_searches": len(self.name_to_documents),
            "total_found": self._total_found_count,
            "unique_documents": len(self.documents),
            "duplicates_removed": self._total_found_count - len(self.documents),
            "multi_name_documents": multi_name_count,
            "single_name_documents": single_name_count,
            "documents_per_name": {
                name: len(docs) for name, docs in self.name_to_documents.items()
            }
        }

        log_info(f"Statistics: {stats['unique_documents']} unique from {stats['total_found']} total ({stats['duplicates_removed']} duplicates)")
        return stats

    def clear(self) -> None:
        """Clear all stored data."""
        self.documents.clear()
        self.name_to_documents.clear()
        self._total_found_count = 0
        log_info("Deduplicator cleared")

    def to_enhanced_metadata(self) -> Dict[str, Dict[str, Any]]:
        """
        Convert to enhanced metadata format for document_metadata.json.

        This format is compatible with the existing metadata structure
        but adds the found_via_names and is_party_specific fields.

        Returns:
            Dictionary mapping doc_number -> metadata dict
        """
        metadata = {}
        for doc_num, record in self.documents.items():
            metadata[doc_num] = {
                "year": record.year,
                "document_type": record.document_type,
                "recording_date": record.recording_date,
                "grantors": record.grantors,
                "grantees": record.grantees,
                "pages": record.pages,
                "found_via_names": record.found_via_names,
                "is_party_specific": len(record.found_via_names) == 1,
                "first_found_at": record.first_found_at,
                "last_updated_at": record.last_updated_at
            }
            # Include any additional metadata
            metadata[doc_num].update(record.additional_metadata)

        return metadata

    def save_to_file(self, filepath: Path) -> None:
        """
        Save deduplication state to JSON file.

        Args:
            filepath: Path to save the JSON file
        """
        data = {
            "version": "1.0",
            "created_at": self._created_at,
            "saved_at": datetime.now().isoformat(),
            "statistics": self.get_statistics(),
            "documents": {doc_num: record.to_dict() for doc_num, record in self.documents.items()},
            "name_to_documents": {name: list(docs) for name, docs in self.name_to_documents.items()}
        }

        filepath.write_text(json.dumps(data, indent=2))
        log_info(f"Saved deduplication state to {filepath}")

    @classmethod
    def load_from_file(cls, filepath: Path) -> "DocumentDeduplicator":
        """
        Load deduplication state from JSON file.

        Args:
            filepath: Path to the JSON file

        Returns:
            DocumentDeduplicator instance with loaded state
        """
        data = json.loads(filepath.read_text())

        dedup = cls()
        dedup._created_at = data.get("created_at", datetime.now().isoformat())

        # Restore documents
        for doc_num, doc_data in data.get("documents", {}).items():
            dedup.documents[doc_num] = DocumentRecord.from_dict(doc_data)

        # Restore name mappings
        for name, doc_nums in data.get("name_to_documents", {}).items():
            dedup.name_to_documents[name] = set(doc_nums)

        # Calculate total found count
        dedup._total_found_count = sum(len(docs) for docs in dedup.name_to_documents.values())

        log_info(f"Loaded deduplication state from {filepath}: {len(dedup.documents)} documents")
        return dedup


class BatchDownloadDeduplicator:
    """
    Specialized deduplicator for batch download operations.

    This class extends DocumentDeduplicator with download-specific functionality:
    - Tracks which documents have been downloaded
    - Generates download queues with duplicate detection
    - Provides download status reporting
    """

    def __init__(self, download_dir: Optional[Path] = None):
        """
        Initialize the batch download deduplicator.

        Args:
            download_dir: Directory where documents are downloaded
        """
        self.deduplicator = DocumentDeduplicator()
        self.download_dir = download_dir
        self.downloaded: Set[str] = set()  # doc_numbers that have been downloaded
        self.skipped: Set[str] = set()  # doc_numbers skipped as duplicates
        self.failed: Set[str] = set()  # doc_numbers that failed to download
        log_info(f"BatchDownloadDeduplicator initialized (download_dir: {download_dir})")

    def add_search_results(self, docs: List[Dict[str, Any]], source_name: str) -> Dict[str, Any]:
        """
        Add documents from a search and return deduplication info.

        Args:
            docs: List of documents from search
            source_name: Name the search was performed for

        Returns:
            Dictionary with deduplication statistics
        """
        return self.deduplicator.add_documents(docs, source_name)

    def get_download_queue(self, skip_existing: bool = True) -> List[Dict[str, Any]]:
        """
        Get the queue of documents to download.

        Args:
            skip_existing: If True, exclude documents that already exist locally

        Returns:
            List of documents to download
        """
        queue = []
        existing_files = set()

        # Check for existing files if requested
        if skip_existing and self.download_dir and self.download_dir.exists():
            existing_files = {f.name for f in self.download_dir.glob("*.pdf")}

            # Also check metadata for doc_number -> filename mapping
            metadata_path = self.download_dir / "document_metadata.json"
            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text())
                    for doc_num, meta in metadata.items():
                        if meta.get("filename") in existing_files:
                            self.downloaded.add(doc_num)
                except json.JSONDecodeError:
                    pass

        for doc_num, record in self.deduplicator.documents.items():
            # Skip if already downloaded
            if doc_num in self.downloaded:
                self.skipped.add(doc_num)
                continue

            # Check if file exists by doc_num in filename
            file_exists = False
            for existing in existing_files:
                if doc_num in existing:
                    file_exists = True
                    self.downloaded.add(doc_num)
                    self.skipped.add(doc_num)
                    break

            if not file_exists:
                queue.append(record.to_dict())

        log_info(f"Download queue: {len(queue)} to download, {len(self.skipped)} skipped (existing/duplicate)")
        return queue

    def mark_downloaded(self, doc_num: str, filename: str) -> None:
        """Mark a document as successfully downloaded."""
        self.downloaded.add(doc_num)
        if doc_num in self.deduplicator.documents:
            self.deduplicator.documents[doc_num].additional_metadata["filename"] = filename
            self.deduplicator.documents[doc_num].additional_metadata["downloaded_at"] = datetime.now().isoformat()
        log_debug(f"Marked {doc_num} as downloaded: {filename}")

    def mark_failed(self, doc_num: str, error: str) -> None:
        """Mark a document as failed to download."""
        self.failed.add(doc_num)
        if doc_num in self.deduplicator.documents:
            self.deduplicator.documents[doc_num].additional_metadata["download_error"] = error
            self.deduplicator.documents[doc_num].additional_metadata["failed_at"] = datetime.now().isoformat()
        log_warn(f"Marked {doc_num} as failed: {error}")

    def get_download_summary(self) -> Dict[str, Any]:
        """
        Get summary of download operation.

        Returns:
            Dictionary with download statistics
        """
        return {
            "total_unique": self.deduplicator.get_unique_count(),
            "total_found": self.deduplicator.get_total_found_count(),
            "duplicates_removed": self.deduplicator.get_duplicate_count(),
            "downloaded": len(self.downloaded),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "remaining": self.deduplicator.get_unique_count() - len(self.downloaded) - len(self.failed),
            "names_searched": self.deduplicator.get_names_searched()
        }

    def save_enhanced_metadata(self, filepath: Path) -> None:
        """
        Save enhanced metadata with deduplication info.

        This updates/creates document_metadata.json with the enhanced format.

        Args:
            filepath: Path to document_metadata.json
        """
        # Load existing metadata if present
        existing = {}
        if filepath.exists():
            try:
                existing = json.loads(filepath.read_text())
            except json.JSONDecodeError:
                pass

        # Merge with new deduplication data
        enhanced = self.deduplicator.to_enhanced_metadata()

        # Preserve existing filename and downloaded_at for documents that have them
        for doc_num, meta in enhanced.items():
            if doc_num in existing:
                if existing[doc_num].get("filename"):
                    meta["filename"] = existing[doc_num]["filename"]
                if existing[doc_num].get("downloaded_at"):
                    meta["downloaded_at"] = existing[doc_num]["downloaded_at"]

        # Add new documents to existing
        existing.update(enhanced)

        filepath.write_text(json.dumps(existing, indent=2))
        log_info(f"Saved enhanced metadata to {filepath} ({len(existing)} documents)")


# Convenience function for simple deduplication
def deduplicate_documents(searches: List[Tuple[List[Dict[str, Any]], str]]) -> List[Dict[str, Any]]:
    """
    Simple function to deduplicate documents from multiple searches.

    Args:
        searches: List of (documents, source_name) tuples

    Returns:
        Deduplicated list of documents

    Example:
        results = deduplicate_documents([
            (search_1_docs, "SMITH JOHN"),
            (search_2_docs, "SMITH JANE"),
        ])
    """
    dedup = DocumentDeduplicator()
    for docs, name in searches:
        dedup.add_documents(docs, name)
    return dedup.get_deduplicated()


# Module test/demo
if __name__ == "__main__":
    # Demo usage
    print("=" * 60)
    print("Document Deduplicator Demo")
    print("=" * 60)

    # Sample documents (simulating searches for two people)
    docs_person1 = [
        {"document_number": "2023-0001234", "document_type": "GRANT DEED", "grantors": "SMITH JOHN", "grantees": "JONES BOB"},
        {"document_number": "2023-0001235", "document_type": "DEED OF TRUST", "grantors": "SMITH JOHN", "grantees": "BANK OF AMERICA"},
        {"document_number": "2022-0009999", "document_type": "GRANT DEED", "grantors": "DOE JANE", "grantees": "SMITH JOHN & SMITH JANE"},
    ]

    docs_person2 = [
        {"document_number": "2022-0009999", "document_type": "GRANT DEED", "grantors": "DOE JANE", "grantees": "SMITH JOHN & SMITH JANE"},  # Duplicate!
        {"document_number": "2023-0001236", "document_type": "DEED OF TRUST", "grantors": "SMITH JANE", "grantees": "WELLS FARGO"},
    ]

    # Create deduplicator and add documents
    dedup = DocumentDeduplicator()

    print("\nAdding documents for SMITH JOHN...")
    result1 = dedup.add_documents(docs_person1, "SMITH JOHN")
    print(f"  Result: {result1}")

    print("\nAdding documents for SMITH JANE...")
    result2 = dedup.add_documents(docs_person2, "SMITH JANE")
    print(f"  Result: {result2}")

    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)
    stats = dedup.get_statistics()
    print(f"Total found across searches: {stats['total_found']}")
    print(f"Unique documents: {stats['unique_documents']}")
    print(f"Duplicates removed: {stats['duplicates_removed']}")
    print(f"Multi-name documents: {stats['multi_name_documents']}")
    print(f"Single-name documents: {stats['single_name_documents']}")

    print("\n" + "=" * 60)
    print("DEDUPLICATED DOCUMENTS")
    print("=" * 60)
    for doc in dedup.get_deduplicated():
        print(f"  {doc['document_number']}: {doc['document_type']}")
        print(f"    Found via: {', '.join(doc['found_via_names'])}")

    print("\n" + "=" * 60)
    print("MULTI-NAME DOCUMENTS (Joint ownership indicator)")
    print("=" * 60)
    for doc in dedup.get_multi_name_documents():
        print(f"  {doc['document_number']}: Found under {len(doc['found_via_names'])} names")
