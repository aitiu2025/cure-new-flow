import os
import re
import json

# Define supported file types / file reading handlers
def read_document_text(filepath):
    """
    Reads the text content of a file.
    Only supports .txt directly. For .pdf or other types, could expand (currently skipped).
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.txt':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    # Placeholder: expand pdf/docx support if needed
    # elif ext == '.pdf': ...
    # elif ext == '.docx': ...
    return None

def normalize_addr(addr):
    """
    Normalize addresses for comparison (simple, can improve with external libraries if needed)
    """
    if not addr:
        return None
    # Lowercase, remove common punctuations, condense whitespace
    addr = addr.lower().replace(',', '').replace('.', '').strip()
    addr = re.sub(r'\s+', ' ', addr)
    return addr

def find_instrument_number(text):
    """
    Tries to extract Instrument # from text (supports multiple common phrasings)
    """
    if not text:
        return None
    patterns = [
        r'Instrument[\s#:-]*([A-Za-z0-9-]+)',
        r'Document[\s#:-]*([A-Za-z0-9-]+)',
        r'Record[\s#:-]*([A-Za-z0-9-]+)'
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def find_address_in_text(text):
    """
    Tries to find an address in the document text via a simple pattern.<br>
    More complex NLP can be done, but for now basic regex for street/number.
    """
    # This basic regex matches: number+word (St/Dr/Ave/Blvd etc.)
    pat = re.compile(r'(\d{2,7} [^\n,]+ (St|Street|Dr|Drive|Ave|Avenue|Blvd|Boulevard|Rd|Road|Ln|Lane|Ct|Court)[^\n,]*)', re.IGNORECASE)
    m = pat.search(text)
    if m:
        return m.group(1).strip()
    return None

def find_apn_in_text(text):
    """
    Tries to find an APN (Assessor's Parcel Number) using basic patterns.
    """
    patterns = [
        r'(APN[\s#:-]*[\d-]+)',
        r'Parcel[\s#:-]*([\d-]+)'
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            grp = m.group(0)
            apn = re.search(r'[\d-]+', grp)
            if apn:
                return apn.group(0)
    return None

def verify_documents(property_address, property_apn, instrument_number, docs_dir=None):
    """
    Verifies documents in docs_dir.
    Args:
        property_address (str): Input property address
        property_apn (str): Input property APN
        instrument_number (str): Input instrument/document number
        docs_dir (str): Directory with doc files to be checked.
    Returns:
        list of dict: Verification result for each doc
    """
    if docs_dir is None:
        from titlepro import DOWNLOAD_DIR
        docs_dir = str(DOWNLOAD_DIR)
    # Normalize input
    norm_addr = normalize_addr(property_address)
    result = []
    for fname in os.listdir(docs_dir):
        filepath = os.path.join(docs_dir, fname)
        if not os.path.isfile(filepath):
            continue
        doc_data = {
            "filename": fname,
            "address_match": False,
            "apn_match": False,
            "instrument_number_match": False,
            "fallback_used": False,
            "matched_on": [],
            "notes": ""
        }
        doc_text = read_document_text(filepath)
        if not doc_text:
            doc_data["notes"] = "Could not parse file."
            result.append(doc_data)
            continue
        # Address check. The regex-extracted doc address is usually the
        # comma-truncated street portion ("123 main st") of the full input
        # ("123 main st los angeles ca 90001"), so containment must be
        # checked in BOTH directions.
        doc_addr = find_address_in_text(doc_text)
        norm_doc_addr = normalize_addr(doc_addr)
        if norm_addr and norm_doc_addr and (
            norm_addr in norm_doc_addr or norm_doc_addr in norm_addr
        ):
            doc_data["address_match"] = True
            doc_data["matched_on"].append("address")
        # APN check
        doc_apn = find_apn_in_text(doc_text)
        if property_apn and doc_apn and property_apn == doc_apn:
            doc_data["apn_match"] = True
            doc_data["matched_on"].append("apn")
        # If address & apn BOTH missing, use instrument fallback
        if not doc_data["address_match"] and not doc_data["apn_match"]:
            doc_instrument = find_instrument_number(doc_text)
            if instrument_number and doc_instrument and instrument_number == doc_instrument:
                doc_data["instrument_number_match"] = True
                doc_data["fallback_used"] = True
                doc_data["matched_on"].append("instrument_number")
        result.append(doc_data)
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Verify property docs against input address/APN, with instrument# fallback.")
    parser.add_argument('--address', type=str, required=False, help='Input property address (full)')
    parser.add_argument('--apn', type=str, required=False, help='Input property APN')
    parser.add_argument('--instrument', type=str, required=False, help='Instrument/document number (for fallback)')
    parser.add_argument('--docs_dir', type=str, default=None, help='Directory with deed/doc files')
    parser.add_argument('--output', type=str, help='Output JSON file for results')
    args = parser.parse_args()
    res = verify_documents(args.address, args.apn, args.instrument, docs_dir=args.docs_dir)
    print(json.dumps(res, indent=2))
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(res, f, indent=2)
