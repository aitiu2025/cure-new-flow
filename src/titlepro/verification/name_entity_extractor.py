import re
from typing import List, Dict, Tuple, Set

class NameEntityExtractor:
    TRUST_REGEX = re.compile(r'([A-Z][\w\s,.]+? Trust)(?:,?\s*([A-Z][\w\s,\.]+)? Trustee)?', re.IGNORECASE)
    TRUSTEE_REGEX = re.compile(r'(?:trustee[s]? of|, trustee[s]?)(.*?)(?= and |,|$)', re.IGNORECASE)
    
    @staticmethod
    def extract_entities(grantees_raw: str) -> Dict[str, Set[str]]:
        """
        Extract trusts, trustees, and individual names from grantee block.
        Return dict: {'trusts': set(...), 'trustees': set(...), 'individuals': set(...)}
        """
        trusts = set()
        trustees = set()
        individuals = set()

        # Find possible trusts
        for match in NameEntityExtractor.TRUST_REGEX.finditer(grantees_raw):
            trust_name = match.group(1).strip()
            trusts.add(trust_name)
            # If a trustee is mentioned alongside
            if match.group(2):
                trustees.add(match.group(2).strip())
        
        # Find more explicit trustees in trust wording
        for trustee_match in re.finditer(r'(?:[A-Z][a-zA-Z ]+?)(?:,? trustee[s]? of [A-Z][\w\s,.]+ Trust)', grantees_raw):
            possible_trustee = trustee_match.group(0).split(',')[0]
            if possible_trustee and 'Trust' not in possible_trustee:
                trustees.add(possible_trustee.strip())

        # Split names on "and", commas, semicolons (but exclude trust names already extracted)
        for name in re.split(r'\band\b|,|;', grantees_raw):
            name = name.strip()
            if not name:
                continue
            # Exclude already found trusts/trustees
            if any(trust in name for trust in trusts):
                continue
            if any(trustee in name for trustee in trustees):
                continue
            if 'trust' in name.lower():
                continue  # Likely a partial trust entity
            # Filter for individual names: likely two or more 'words' and not generic words
            words = name.split()
            if 1 < len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()):
                individuals.add(name)
        
        return {
            'trusts': trusts,
            'trustees': trustees,
            'individuals': individuals
        }

    @staticmethod
    def filter_new_entities(extracted: Dict[str, Set[str]], original_subject_names: Set[str]) -> Dict[str, Set[str]]:
        """
        Given extracted sets and original subject names, return only the new names (not including original subject names)
        """
        def normalize(n):
            return re.sub(r'\s+', ' ', n.strip().lower())
        orig_norm = {normalize(n) for n in original_subject_names}

        filtered = {}
        for etype, nameset in extracted.items():
            filtered[etype] = set()
            for n in nameset:
                if normalize(n) not in orig_norm:
                    filtered[etype].add(n)
        return filtered
