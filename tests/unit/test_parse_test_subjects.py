import os

import pytest

from tests.unit.parse_test_subjects import load_test_subjects, TestSubjectsParser
import json

# Local data file with borrower test subjects — intentionally NOT committed
# (contains PII). The test only runs in checkouts where it has been placed
# manually; everywhere else it skips instead of failing the suite.
_TEST_JSON = os.path.join(
    os.path.dirname(__file__), '..', 'CURE_County_Test_Subjects.json'
)


@pytest.mark.skipif(
    not os.path.exists(_TEST_JSON),
    reason="CURE_County_Test_Subjects.json (uncommitted PII data file) not present",
)
def test_load_and_parse_subjects():
    test_json = _TEST_JSON
    batch = load_test_subjects(test_json)
    assert len(batch) == 21, f"Expected 21 test subjects, but got {len(batch)}"
    # Check >99% key parsing accuracy for borrowers/properties/counties
    borrower_missing = sum(1 for s in batch if not s['borrower'])
    property_missing = sum(1 for s in batch if not s['property_address'])
    county_missing = sum(1 for s in batch if not s['county'])
    assert borrower_missing <= 0, f"Missing borrower in {borrower_missing} subjects"
    assert property_missing/21.0 < 0.05, f"Property address missing in >1 subject!"
    assert county_missing/21.0 < 0.05, f"County missing in >1 subject!"
    # Print for manual review
    print("Parsed subjects:\n", json.dumps(batch, indent=2))

if __name__ == '__main__':
    test_load_and_parse_subjects()
