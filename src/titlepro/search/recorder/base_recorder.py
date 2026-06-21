"""
Base class for California County Recorder search automation.
Each county implementation extends this class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime
import json


@dataclass
class DocumentRecord:
    """Represents a single document from recorder search results."""
    document_number: str
    grantors: str
    grantees: str
    grantor_grantees: str
    document_type: str
    recording_date: str
    pages: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SearchResult:
    """Container for search results with metadata."""
    name_searched: str
    party_type: str
    start_date: str
    end_date: str
    documents: List[DocumentRecord]
    search_timestamp: str = None

    def __post_init__(self):
        if self.search_timestamp is None:
            self.search_timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "name_searched": self.name_searched,
            "party_type": self.party_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "search_timestamp": self.search_timestamp,
            "result_count": len(self.documents),
            "documents": [doc.to_dict() for doc in self.documents]
        }


class BaseRecorderSearch(ABC):
    """
    Abstract base class for county recorder search automation.

    Each county has different website structures, so subclasses must
    implement the abstract methods for their specific website.
    """

    def __init__(self, start_date: str = "01/01/2010", end_date: str = None):
        """
        Initialize the recorder search.

        Args:
            start_date: Search start date in MM/DD/YYYY format
            end_date: Search end date in MM/DD/YYYY format (defaults to today)
        """
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime("%m/%d/%Y")
        self.driver = None
        self.results: Dict[str, SearchResult] = {}

    @property
    @abstractmethod
    def county_name(self) -> str:
        """Return the county name."""
        pass

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the base URL for the recorder website."""
        pass

    @abstractmethod
    def setup_driver(self):
        """Initialize and configure the Selenium WebDriver."""
        pass

    @abstractmethod
    def navigate_to_search(self):
        """Navigate to the name search page."""
        pass

    @abstractmethod
    def perform_search(self, name: str, party_type: str = "Grantor/Grantee") -> List[DocumentRecord]:
        """
        Perform a name search and return results.

        Args:
            name: Name to search for (format varies by county)
            party_type: Party type filter

        Returns:
            List of DocumentRecord objects
        """
        pass

    @abstractmethod
    def extract_results(self) -> List[DocumentRecord]:
        """Extract results from the current results page."""
        pass

    @abstractmethod
    def return_to_search(self):
        """Navigate back to search form for next search."""
        pass

    def search_name(self, name: str, party_type: str = "Grantor/Grantee") -> SearchResult:
        """
        Execute a complete search for a name.

        Args:
            name: Name to search
            party_type: Party type filter

        Returns:
            SearchResult object with all found documents
        """
        documents = self.perform_search(name, party_type)
        result = SearchResult(
            name_searched=name,
            party_type=party_type,
            start_date=self.start_date,
            end_date=self.end_date,
            documents=documents
        )
        self.results[name] = result
        return result

    def find_common_documents(self, results1: SearchResult, results2: SearchResult) -> List[DocumentRecord]:
        """
        Find documents that appear in both search results (intersection).

        Args:
            results1: First search results
            results2: Second search results

        Returns:
            List of DocumentRecord objects found in both searches
        """
        # Create sets of document numbers for fast lookup
        docs1_by_number = {doc.document_number: doc for doc in results1.documents}
        docs2_numbers = {doc.document_number for doc in results2.documents}

        # Find intersection
        common_numbers = set(docs1_by_number.keys()) & docs2_numbers

        # Return full document records for common documents
        return [docs1_by_number[num] for num in common_numbers]

    def find_unique_documents(self, results1: SearchResult, results2: SearchResult) -> tuple:
        """
        Find documents unique to each search result.

        Args:
            results1: First search results
            results2: Second search results

        Returns:
            Tuple of (docs only in results1, docs only in results2)
        """
        docs1_by_number = {doc.document_number: doc for doc in results1.documents}
        docs2_by_number = {doc.document_number: doc for doc in results2.documents}

        only_in_1 = set(docs1_by_number.keys()) - set(docs2_by_number.keys())
        only_in_2 = set(docs2_by_number.keys()) - set(docs1_by_number.keys())

        return (
            [docs1_by_number[num] for num in only_in_1],
            [docs2_by_number[num] for num in only_in_2]
        )

    def search_two_names(self, name1: str, name2: str,
                         party_type: str = "Grantor/Grantee") -> Dict:
        """
        Search for two names and find common documents.

        Args:
            name1: First name to search
            name2: Second name to search
            party_type: Party type filter

        Returns:
            Dictionary with search results and analysis
        """
        print(f"\n{'='*60}")
        print(f"Searching {self.county_name} County Recorder")
        print(f"{'='*60}")

        # Search first name
        print(f"\nSearching for: {name1}")
        results1 = self.search_name(name1, party_type)
        print(f"  Found {len(results1.documents)} document(s)")

        # Return to search form
        self.return_to_search()

        # Search second name
        print(f"\nSearching for: {name2}")
        results2 = self.search_name(name2, party_type)
        print(f"  Found {len(results2.documents)} document(s)")

        # Find common and unique documents
        common_docs = self.find_common_documents(results1, results2)
        name1_only, name2_only = self.find_unique_documents(results1, results2)

        print(f"\n{'='*60}")
        print(f"RESULTS SUMMARY")
        print(f"{'='*60}")
        print(f"Documents common to both names: {len(common_docs)}")
        print(f"Documents only for {name1}: {len(name1_only)}")
        print(f"Documents only for {name2}: {len(name2_only)}")

        return {
            "search_params": {
                "name1": name1,
                "name2": name2,
                "county": self.county_name,
                "party_type": party_type,
                "date_range": [self.start_date, self.end_date],
                "search_timestamp": datetime.now().isoformat()
            },
            "summary": {
                "total_common": len(common_docs),
                "total_name1_only": len(name1_only),
                "total_name2_only": len(name2_only)
            },
            "common_documents": [doc.to_dict() for doc in common_docs],
            "name1_only_documents": [doc.to_dict() for doc in name1_only],
            "name2_only_documents": [doc.to_dict() for doc in name2_only],
            "full_results": {
                "name1": results1.to_dict(),
                "name2": results2.to_dict()
            }
        }

    def export_json(self, data: Dict, filename: str):
        """
        Export results to JSON file.

        Args:
            data: Results dictionary
            filename: Output filename
        """
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nResults exported to: {filename}")

    def close(self):
        """Close the browser and clean up."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def __enter__(self):
        """Context manager entry."""
        self.setup_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
