import os
from typing import List, Dict, Optional
from datetime import datetime

class VestingDeedIdentifier:
    def __init__(self, docs: List[Dict], borrower_names: List[str]):
        """
        docs: list of document record dicts with at least:
              - 'type' (e.g., 'GRANT DEED')
              - 'recording_date' (str: 'YYYY-MM-DD' or similar)
              - 'grantee' (str or list)
              - any identifier fields like 'document_id'
        borrower_names: list of legal names, e.g., ['Jane Q Public', ...]
        """
        self.docs = docs
        self.borrower_names = [self.norm(n) for n in borrower_names]

    def norm(self, name: str) -> str:
        return name.strip().upper().replace(',', '')

    def name_matches(self, grantee) -> bool:
        if isinstance(grantee, str):
            normed = self.norm(grantee)
            return any(n in normed or normed in n for n in self.borrower_names)
        if isinstance(grantee, list):
            return any(self.name_matches(g) for g in grantee)
        return False

    def parse_date(self, datestr: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%b %d %Y"):
            try:
                return datetime.strptime(datestr, fmt)
            except Exception:
                continue
        return None

    def get_current_vesting_deed(self) -> Optional[Dict]:
        # 1. Filter only GRANT DEEDs with borrower as grantee
        candidate_deeds = []
        for doc in self.docs:
            doc_type = doc.get('type', '').strip().upper()
            if doc_type != 'GRANT DEED':
                continue
            grantee = doc.get('grantee')
            if not grantee:
                continue
            if self.name_matches(grantee):
                candidate_deeds.append(doc)
        if not candidate_deeds:
            return None
        # 2. Pick the one with latest recording_date
        # If recording_date missing, treat as 1900-01-01
        def deed_date(doc):
            dt = self.parse_date(doc.get('recording_date', ''))
            if dt:
                return dt
            # fallback: extremely old date
            return datetime(1900,1,1)
        candidate_deeds.sort(key=deed_date, reverse=True)
        most_recent_date = deed_date(candidate_deeds[0])
        # 3. Edge case: multiple on the same most recent date
        top_deeds = [d for d in candidate_deeds if deed_date(d)==most_recent_date]
        if len(top_deeds)==1:
            return top_deeds[0]
        # 4. Further tiebreak: if any with full borrower names as grantee
        fully_match = []
        full_set = set(self.borrower_names)
        for d in top_deeds:
            grantee = d.get('grantee')
            if isinstance(grantee, str):
                found_names = set([self.norm(grantee)])
            elif isinstance(grantee, list):
                found_names = set([self.norm(name) for name in grantee])
            else:
                found_names = set()
            if full_set == found_names:
                fully_match.append(d)
        if fully_match:
            return fully_match[0]
        # 5. Otherwise just return the first (most recent)
        return top_deeds[0]
