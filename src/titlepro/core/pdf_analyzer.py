import os
import re
import json
from typing import Tuple, List, Dict
from collections import Counter
try:
    from pdfminer.high_level import extract_text
except ImportError:
    print("pdfminer.six is required. Install with: pip install pdfminer.six")
    exit(1)

doc_types = {
    'DOT': [r'deed of trust', r'trust deed', r'deed to secure debt'],
    'Reconveyance': [r'reconveyance', r'release of deed', r'full reconveyance'],
    'JL': [r'judgment lien', r'abstract of judgment', r'lien'],
    'Grant Deed': [r'grant deed'],
    'Quitclaim Deed': [r'quitclaim deed'],
    'Assignment': [r'assignment', r'assign'],
    # Add more as needed
}

party_patterns = [
    (r'grantor[s]?:\s*(.+?)(?:\n|$)', 'grantor'),
    (r'grantee[s]?:\s*(.+?)(?:\n|$)', 'grantee'),
    (r'trustor[s]?:\s*(.+?)(?:\n|$)', 'grantor'),
    (r'beneficiary[:]?\s*(.+?)(?:\n|$)', 'grantee'),
]

dollar_patterns = [
    r'\$[0-9,]+(?:\.[0-9]{2})?',
    r'the sum of ([ ]*\$[0-9,]+(?:\.[0-9]{2})?)',
    r'in the amount of ([ ]*\$[0-9,]+(?:\.[0-9]{2})?)',
]

property_patterns = [
    r'APN[: ]+([0-9\-]+)',
    r'Assessor[’\']?s Parcel Number[: ]+([0-9\-]+)',
    r'legal description[:\n]+(.+?)(?:parcel|apn|\n)',
]

def classify_document(text: str) -> Tuple[str, float]:
    """
    Classifies document type by keyword frequency and returns (type, confidence score).
    """
    text_lower = text.lower()
    scores = {}
    for doc_type, patterns in doc_types.items():
        score = sum(bool(re.search(pattern, text_lower)) for pattern in patterns)
        scores[doc_type] = score
    # Pick highest scoring type
    if not scores or max(scores.values()) == 0:
        return ("Unknown", 0.0)
    best_type = max(scores, key=scores.get)
    total = sum(scores.values())
    conf = scores[best_type] / (total if total else 1)
    return (best_type, conf)

def extract_parties(text: str) -> Dict[str, List[str]]:
    parties = {'grantor': [], 'grantee': []}
    for pattern, role in party_patterns:
        for match in re.findall(pattern, text, re.I):
            cleaned = match.strip().replace('\n', ' ')
            if cleaned and cleaned not in parties[role]:
                parties[role].append(cleaned)
    # Try to extract Grantor/Grantee from common phrases if empty
    if not parties['grantor']:
        m = re.search(r'between\s+(.+?)\s+and\s+(.+?)(?:\.|,|\n)', text, re.I)
        if m:
            parties['grantor'].append(m.group(1).strip())
            parties['grantee'].append(m.group(2).strip())
    # Remove duplicates
    parties['grantor'] = list(dict.fromkeys(parties['grantor']))
    parties['grantee'] = list(dict.fromkeys(parties['grantee']))
    return parties

def extract_amount(text: str) -> str:
    for patt in dollar_patterns:
        m = re.search(patt, text)
        if m:
            if isinstance(m, str):
                amt = m
            elif m.lastindex:
                amt = m.group(1)
            else:
                amt = m.group(0)
            return amt.strip()
    return ''

def extract_property_data(text: str) -> Dict[str, str]:
    prop = {}
    for pattern in property_patterns:
        m = re.search(pattern, text, re.I | re.S)
        if m:
            key = 'APN' if 'APN' in pattern else 'legal_description'
            prop[key] = m.group(1).strip().replace('\n',' ')
    # Remove newlines from property fields
    for k in list(prop.keys()):
        prop[k] = re.sub(r'\s+', ' ', prop[k])
    return prop

def analyze_pdf(path: str) -> Dict:
    try:
        text = extract_text(path)
    except Exception as e:
        return {"error": f"Failed to read {os.path.basename(path)}: {e}"}
    doc_type, conf = classify_document(text)
    parties = extract_parties(text)
    amount = extract_amount(text)
    property_data = extract_property_data(text)
    result = {
        "file": os.path.basename(path),
        "doc_type": doc_type,
        "confidence": round(conf, 3),
        "grantor": parties['grantor'],
        "grantee": parties['grantee'],
        "amount": amount,
        "property": property_data,
    }
    return result

def main():
    from titlepro import DOWNLOAD_DIR
    input_dir = str(DOWNLOAD_DIR)
    out_path = str(DOWNLOAD_DIR / 'nlp_analysis_results.json')
    results = []
    pdfs = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
    for fname in pdfs:
        fpath = os.path.join(input_dir, fname)
        print(f"Analyzing {fname} ...")
        res = analyze_pdf(fpath)
        results.append(res)
    # Optional: filter out low-confidence or add summary/report
    with open(out_path, 'w') as outf:
        json.dump(results, outf, indent=2)
    print(f"Analysis complete. Results written to {out_path}")

if __name__ == '__main__':
    main()
