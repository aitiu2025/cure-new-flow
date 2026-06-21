import os
import re
from typing import Dict, Any, List, Optional
import fitz  # PyMuPDF

class DeedExtractionError(Exception):
    pass

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from all pages of the PDF.

    Corrupt / non-PDF files (failed downloads, HTML error pages saved with a
    .pdf name) return empty text rather than raising — callers treat empty
    text as "nothing extractable" and degrade to all-None results.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    full_text = ""
    for page in doc:
        text = page.get_text("text")
        full_text += text + "\n"
    return full_text

def extract_property_address(text: str) -> Optional[str]:
    # Address patterns (handles typical CA address notation)
    pat = r'(?:\bAddress(?:\s*of\s*property)?[:\-\s]*|Property Address[:\-\s]*)?([0-9]{1,5}\s+[\w., ]+(Avenue|Ave|Street|St|Boulevard|Blvd|Lane|Ln|Road|Rd|Drive|Dr|Court|Ct|Parkway|Pkwy)[\w., \-]*(?:,?\s*[\w.,]+)+)'
    matches = re.findall(pat, text, re.IGNORECASE)
    if matches:
        # Return the first, most complete address match
        return matches[0][0].strip()
    # As fallback, look for 'Commonly known as: ...'
    pat2 = r'Commonly known as[:\-\s]*([^\n]+)'
    m2 = re.search(pat2, text)
    if m2:
        return m2.group(1).strip()
    return None

def extract_apn(text: str) -> Optional[str]:
    pat = r'(?:(?:Assessor[’\']?s|Parcel|APN)\s*(?:number|No\.|#|:)\s*|APN[:\s]*)(\d{2,4}[- ]?\d{2,4}[- ]?\d{1,4})'
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        return m.group(1).replace(' ', '').strip()
    return None

def extract_legal_description(text: str) -> Optional[str]:
    # Try to extract between 'LEGAL DESCRIPTION' and next ALLCAPS section or end
    pat = r'LEGAL DESCRIPTION[\s:\-]*([\s\S]{50,}?)(?:\n[A-Z \-,]+:|\n\n|\nEND OF LEGAL)' # legal descr. usually has at least 50 chars
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: look for 'described as:'
    pat2 = r'(?:described as[:\s]*)([\s\S]{30,140})\n'
    m2 = re.search(pat2, text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None

def extract_grantees_and_vesting(text: str) -> Dict[str, Any]:
    """
    Looks for the section that typically starts with 'hereby grant(s) to', 'grantee(s):', or 'to:'
    Tries to robustly extract all named parties (handles trusts, co-ownership, weird formatting)
    Returns dict: {grantees: [..], vesting_type: str}
    """
    # This is the trickiest. We'll use a few layered regexes.
    grant_pat = r'(?:hereby grant(?:s)?(?:,?\s*)?to|grantee(?:s)?:|to:)\s+([\s\S]{20,200})'
    grant_match = re.search(grant_pat, text, re.IGNORECASE)
    all_names = []
    vesting_type = None
    if grant_match:
        block = grant_match.group(1)
        # Attempt to split names and vesting by safe punctuation or lines
        # e.g., JOHN DOE AND JANE DOE, AS JOINT TENANTS
        #          ^ grantees         ^ vesting type
        main_split = re.split(r',\s*AS\s+|\s+AS\s+', block, maxsplit=1, flags=re.IGNORECASE)
        names_str = main_split[0].strip()
        # Grantee names are often separated by 'and', commas, or slashes
        candidate_names = re.split(r'\b(?:and|/|,)\b', names_str, flags=re.IGNORECASE)
        for name in candidate_names:
            named = name.strip()
            # Filter out tokens that look like vesting or are too short
            if named and not re.search(r'(joint|tenant|trust|community property|survivorship|husband|wife|spouse|as\s+)', named, re.IGNORECASE):
                all_names.append(named)
            # Accept trust entities (eg, 'DOE FAMILY TRUST')
            elif re.search(r'trust', named, re.IGNORECASE) and len(named) > 10:
                all_names.append(named)
        # Vesting type
        if len(main_split) > 1:
            vesting_str = main_split[1].strip()
            # e.g. 'Joint Tenants', 'Community Property', etc
            vesting_type = re.split(r'[\.,\n]', vesting_str, 1)[0]
    if not all_names:
        # Fallback: Look for 'Grantee(s):' on its own line, or "to: <names> as ..."
        pats = [r'Grantee(?:s)?[:\-]\s*([^\n]+)',
                r'to[:\-]\s*([^\n]+)']
        for pat in pats:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                line = m.group(1)
                names = [n.strip() for n in re.split(r'\s+and\s+|,|/|\band\b', line) if n.strip()]
                all_names += names
    # Clean up grantee names: remove vesting keywords, odd chars
    all_names = [re.sub(r'\b(as|as\s+joint tenants?|community property|trust(\s+under)?|with right.*|of\s+survivorship|husband and wife|married|single man|single woman)\b', '', n, flags=re.IGNORECASE).strip(' ,;:.\n') for n in all_names]
    all_names = [n for n in all_names if n and len(n) > 2]
    # Try vesting type identification from text if missing
    if not vesting_type:
        # All common vesting types
        common_vestings = r"joint tenants|joint tenancy|tenants in common|community property|with right of survivorship|as trustee|as tenants by the entirety|as separate property|married|unmarried|single man|single woman|as beneficiary(ies)? of trust|living trust"
        m = re.search(common_vestings, text, re.IGNORECASE)
        if m:
            vesting_type = m.group(0)
    return {"grantees": all_names, "vesting_type": vesting_type.strip() if vesting_type else None}

def parse_vesting_deed(pdf_path: str) -> Dict[str, Any]:
    """Main invocation for vesting deed NLP extraction."""
    if not os.path.exists(pdf_path):
        raise DeedExtractionError(f"File not found: {pdf_path}")
    text = extract_text_from_pdf(pdf_path)
    address = extract_property_address(text)
    apn = extract_apn(text)
    legal = extract_legal_description(text)
    grantee_info = extract_grantees_and_vesting(text)
    
    return {
        "property_address": address,
        "apn": apn,
        "legal_description": legal,
        "grantees": grantee_info.get("grantees"),
        "vesting_type": grantee_info.get("vesting_type")
    }

if __name__ == "__main__":
    # Example direct invocation for manual test
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_analyzer.py <vesting deed PDF file>")
        sys.exit(1)
    result = parse_vesting_deed(sys.argv[1])
    import json
    print(json.dumps(result, indent=2))
