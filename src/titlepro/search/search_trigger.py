import threading
from typing import Set, Dict
from titlepro.search.property_search import search_by_name

def trigger_followup_searches(new_entities: Dict[str, Set[str]], property_id: str = None):
    """
    For each new entity found (trusts, trustees, individuals), trigger property/name searches.
    Uses threading to run searches in background.
    property_id: optional; if known, associate with search.
    """
    def search_wrapper(name, entity_type):
        search_by_name(name, entity_type, property_id)

    for entity_type, nameset in new_entities.items():
        for name in nameset:
            t = threading.Thread(target=search_wrapper, args=(name, entity_type))
            t.daemon = True
            t.start()
# No user interaction: all searches are automatic.
