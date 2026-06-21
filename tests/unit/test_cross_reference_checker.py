import pytest
from titlepro.verification.cross_reference_checker import *

def test_extract_parties():
    txt = '''GRANTOR: John Q. Public
GRANTEE: Jane Smith
TRUSTOR: Michael Lee
TRUSTEE: CA Title Corp
BENEFICIARY: Lender LLC'''
    res = extract_parties(txt)
    assert 'John Q. Public' in res['GRANTOR']
    assert 'Jane Smith' in res['GRANTEE']
    assert 'Lender LLC' in res['BENEFICIARY']

def test_extract_lien_type():
    txt = 'CALIFORNIA UCC FINANCING STATEMENT filed by ABC BANK against John Q. Public.'
    typ = extract_lien_type(txt)
    assert typ=='UCC'
    txt2 = 'DEED OF TRUST recorded in favor of LENDER CORP.'
    assert extract_lien_type(txt2)=='DEED OF TRUST'
    txt3 = 'MECHANIC LIEN by contractor.'
    assert extract_lien_type(txt3)=='MECHANIC'

def test_detect_release_status():
    assert detect_release_status('Reconveyance of Deed of Trust recorded')=='RELEASED'
    assert detect_release_status('Deed of Trust for $400,000')=='OPEN'
    assert detect_release_status('Release of Judgment Lien')=='RELEASED'

def test_extract_lien_indexing():
    docs = [
        {
            'index': 'doc1',
            'text': 'GRANTOR: John Q. Public\nGRANTEE: Jane Smith\nJL\n',
            'recorded_date': '2024-01-01'
        },
        {
            'index': 'doc2',
            'text': 'TRUSTOR: John Q. Public\nTRUSTEE: Title Co\nBENEFICIARY: Lender Inc\nDEED OF TRUST',
            'recorded_date': '2024-02-10'
        },
        {
            'index': 'doc3',
            'text': 'RELEASE OF DEED OF TRUST\nTRUSTOR: John Q. Public\n',
            'recorded_date': '2024-05-11'
        },
        {
            'index': 'doc4',
            'text': 'UCC FINANCING STATEMENT\nDEBTOR: John Q. Public\nSECURED PARTY: ABC Bank\n',
            'recorded_date': '2024-03-05'
        },
    ]
    result = extract_lien_indexing(docs)
    partyset = set([normalize_party('John Q. Public')])
    assert set(result['all_parties']) >= partyset
    jls = [d for d in result['liens_attributed'] if d['doc_type']=='JL']
    assert any('JOHN Q PUBLIC' in d['attributed_parties'] for d in jls)
    dots = [d for d in result['liens_attributed'] if d['doc_type'] in ('DOT','DEED OF TRUST')]
    assert any(d['dot_status']=='OPEN' for d in dots)
    released = [d for d in result['liens_attributed'] if d['dot_status']=='RELEASED']
    assert released
    uccs = [d for d in result['liens_attributed'] if d['doc_type']=='UCC']
    assert any('JOHN Q PUBLIC' in d['attributed_parties'] for d in uccs)
