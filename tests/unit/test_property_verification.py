import os
import shutil
import pytest
from titlepro.verification import property_verification

def setup_module(module):
    os.makedirs('downloaded_doc', exist_ok=True)
    # Doc 1: address match, no apn/instrument
    with open('downloaded_doc/deed1.txt', 'w') as f:
        f.write('123 Main St, Los Angeles, CA 90001\nAPN: 123-456-789\nInstrument #: 20240101-001')
    # Doc 2: APN match only
    with open('downloaded_doc/deed2.txt', 'w') as f:
        f.write('Some property\nParcel: 123-456-789\nRandom line')
    # Doc 3: Instrument fallback
    with open('downloaded_doc/deed3.txt', 'w') as f:
        f.write('No address here\nInstrument: 20240101-002')

def teardown_module(module):
    shutil.rmtree('downloaded_doc')

def test_address_apn_match():
    res = property_verification.verify_documents(
        '123 Main St, Los Angeles, CA 90001',
        '123-456-789',
        '20240101-001',
        docs_dir='downloaded_doc'
    )
    # deed1: address+apn, deed2: apn, deed3: fallback inst num fails (inst num diff)
    # But test with instrument that matches deed3
    assert any(d['filename']=='deed1.txt' and d['address_match'] for d in res)
    assert any(d['filename']=='deed2.txt' and d['apn_match'] for d in res)

def test_instrument_fallback():
    res = property_verification.verify_documents(
        '456 Elm St, Los Angeles, CA 90002',  # does not match in docs
        '999-000-111',  # does not match in docs
        '20240101-002',  # matches deed3 instrument number
        docs_dir='downloaded_doc'
    )
    assert any(d['filename']=='deed3.txt' and d['instrument_number_match'] and d['fallback_used'] for d in res)
    for d in res:
        if d['filename']=='deed3.txt':
            assert not d['address_match'] and not d['apn_match']
