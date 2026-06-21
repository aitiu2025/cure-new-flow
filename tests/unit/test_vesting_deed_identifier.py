import unittest
from titlepro.verification.vesting_deed_identifier import VestingDeedIdentifier
from datetime import datetime

class TestVestingDeedIdentifier(unittest.TestCase):
    def setUp(self):
        self.sample_docs = [
            {'type': 'GRANT DEED', 'recording_date': '2020-01-15', 'grantee': 'Jane Q Public'},
            {'type': 'QUITCLAIM DEED', 'recording_date': '2021-02-20', 'grantee': 'Jane Q Public'},
            {'type': 'GRANT DEED', 'recording_date': '2022-03-10', 'grantee': ['Jane Q Public', 'John Public']},
            {'type': 'GRANT DEED', 'recording_date': '2022-03-10', 'grantee': 'Jane Q Public'},
            {'type': 'GRANT DEED', 'recording_date': '2022-04-20', 'grantee': 'Other Party'},
            {'type': 'GRANT DEED', 'recording_date': '2022-05-05', 'grantee': ['Jane Q Public', 'John Public']},
            {'type': 'GRANT DEED', 'recording_date': '2022-05-05', 'grantee': 'John Public'}
        ]
        self.borrower_names = ['Jane Q Public', 'John Public']

    def test_select_most_recent(self):
        identifier = VestingDeedIdentifier(self.sample_docs, self.borrower_names)
        best = identifier.get_current_vesting_deed()
        self.assertEqual(best['recording_date'], '2022-05-05')
        self.assertIn('Jane Q Public', best['grantee'])
        self.assertIn('John Public', best['grantee'])

    def test_no_matching_grant_deed(self):
        docs = [{'type': 'GRANT DEED', 'recording_date': '2022-01-01', 'grantee': 'Someone Else'}]
        identifier = VestingDeedIdentifier(docs, self.borrower_names)
        self.assertIsNone(identifier.get_current_vesting_deed())

    def test_edge_case_multiple_same_date(self):
        docs = [
            {'type': 'GRANT DEED', 'recording_date': '2023-06-01', 'grantee': ['Jane Q Public', 'John Public']},
            {'type': 'GRANT DEED', 'recording_date': '2023-06-01', 'grantee': 'Jane Q Public'},
        ]
        identifier = VestingDeedIdentifier(docs, self.borrower_names)
        # Should select the deed listing both borrower names
        vest = identifier.get_current_vesting_deed()
        self.assertEqual(vest['grantee'], ['Jane Q Public', 'John Public'])

    def test_nonstandard_date_formats(self):
        docs = [
            {'type': 'GRANT DEED', 'recording_date': '01/14/2024', 'grantee': 'Jane Q Public'},
            {'type': 'GRANT DEED', 'recording_date': '2023-12-31', 'grantee': 'Jane Q Public'},
        ]
        identifier = VestingDeedIdentifier(docs, ['Jane Q Public'])
        vest = identifier.get_current_vesting_deed()
        self.assertEqual(vest['recording_date'], '01/14/2024')

if __name__ == '__main__':
    unittest.main()
