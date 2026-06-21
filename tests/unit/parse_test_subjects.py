import json
from typing import List, Dict, Any, Optional
import os

class TestSubject:
    def __init__(self, borrower: str, property_address: str, county: str, test_id: str, other_data: Optional[Dict[str, Any]] = None):
        self.borrower = borrower
        self.property_address = property_address
        self.county = county
        self.test_id = test_id
        self.other_data = other_data or {}
    def to_dict(self):
        return {
            'borrower': self.borrower,
            'property_address': self.property_address,
            'county': self.county,
            'test_id': self.test_id,
            'other_data': self.other_data
        }

class TestSubjectsParser:
    def __init__(self, json_path: str):
        self.json_path = json_path
        self.subjects: List[TestSubject] = []
    def load(self) -> List[TestSubject]:
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(f"File not found: {self.json_path}")
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.subjects = self._parse_subjects(data)
        return self.subjects
    def _parse_subjects(self, data) -> List[TestSubject]:
        subjects = []
        if isinstance(data, dict):
            subjects_raw = data.get('subjects', [])
        else:
            subjects_raw = data
        for subj in subjects_raw:
            # Borrower name logic
            borrower = subj.get('borrower') or subj.get('Borrower')
            property_address = subj.get('property') or subj.get('property_address') or subj.get('Property Address') or subj.get('address')
            county = subj.get('county') or subj.get('County')
            test_id = subj.get('test_id') or subj.get('id') or subj.get('TestID') or subj.get('Test Id')
            # Basic fallback for missing test_id
            if not test_id:
                test_id = str(subj.get('index', len(subjects)+1))
            # Remaining data
            other = {k: v for k, v in subj.items() if k.lower() not in {'borrower', 'property', 'property_address', 'property address', 'address', 'county', 'test_id', 'id', 'testid', 'test id', 'index'}}
            subjects.append(TestSubject(
                borrower=borrower if borrower else '',
                property_address=property_address if property_address else '',
                county=county if county else '',
                test_id=str(test_id),
                other_data=other
            ))
        return subjects
    def get_batch_execution_list(self) -> List[Dict[str, Any]]:
        '''
        Returns a list suitable for batch execution
        '''
        return [s.to_dict() for s in self.subjects]

# Standalone routine for direct usage

def load_test_subjects(json_path: str) -> List[Dict[str, Any]]:
    parser = TestSubjectsParser(json_path)
    parser.load()
    return parser.get_batch_execution_list()
