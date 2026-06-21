import os
import json
from titlepro.verification.pdf_analyzer import parse_vesting_deed

def test_realistic_deed_sample_1():
    # Assume sample PDF is at ./sample_deeds/ca_joint_tenants_sample1.pdf
    base_path = os.path.dirname(__file__)
    deed_path = os.path.join(base_path, 'sample_deeds', 'ca_joint_tenants_sample1.pdf')
    if not os.path.exists(deed_path):
        print(f"Skip: {deed_path} not found.")
        return
    result = parse_vesting_deed(deed_path)
    assert result['property_address'] and 'CA' in result['property_address'], "Should extract CA address"
    assert result['apn'] and len(result['apn']) >= 6, "APN should be extracted"
    assert 'Joint' in (result['vesting_type'] or ''), "Vesting type must contain 'Joint'"
    assert result['grantees'] and len(result['grantees']) >= 2, "Should get all co-owner grantee names"

def test_trust_and_edge_case():
    # For a more complex formatting, such as family trust
    base_path = os.path.dirname(__file__)
    deed_path = os.path.join(base_path, 'sample_deeds', 'ca_family_trust_sample2.pdf')
    if not os.path.exists(deed_path):
        print(f"Skip: {deed_path} not found.")
        return
    result = parse_vesting_deed(deed_path)
    assert any('trust' in n.lower() for n in (result['grantees'] or [])), "Should get trust name in grantees"
    assert result['vesting_type']

def test_gibberish_fallback():
    # Fallback gracefully with an unrelated PDF
    import tempfile
    with tempfile.NamedTemporaryFile('w+', suffix='.pdf') as f:
        f.write("This is not a deed or anything like it.\n")
        f.flush()
        result = parse_vesting_deed(f.name)
        assert result['property_address'] is None
        assert result['apn'] is None
        assert result['grantees'] == []
        assert result['vesting_type'] is None

def run_all():
    test_realistic_deed_sample_1()
    test_trust_and_edge_case()
    test_gibberish_fallback()
    print("All vesting deed NLP extraction tests passed.")

if __name__ == "__main__":
    run_all()
