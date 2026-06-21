from titlepro.verification.name_entity_extractor import NameEntityExtractor
from titlepro.search.search_trigger import trigger_followup_searches
from typing import List, Set

def handle_discovered_names(vesting_deed_text: str, original_subject_names: List[str], property_id: str = None):
    """
    Main handler: (1) parse vesting deed grantee section, (2) extract all name entities, (3) compute new names (vs. original subject),
    (4) trigger automated searches for all, no user input.
    Returns list of new entities for confirmation/logging.
    """
    extracted = NameEntityExtractor.extract_entities(vesting_deed_text)
    new_entities = NameEntityExtractor.filter_new_entities(extracted, set(original_subject_names))
    trigger_followup_searches(new_entities, property_id)
    return new_entities

# Example usage (remove in prod):
if __name__ == "__main__":
    vesting_sample = "John Doe and Jane Smith, as Trustees of the Doe Family Trust, U/D/T dated March 16, 2012"
    orig_subject = ["John Doe"]
    print('New Entities:', handle_discovered_names(vesting_sample, orig_subject, property_id="CA12345"))
