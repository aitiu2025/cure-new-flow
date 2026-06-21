import os
import json
from collections import defaultdict

# Directory paths
from titlepro import DOWNLOAD_DIR
NAMES_PATH = 'NameandPropertySearch/names.json'  # assumed file storing processed names
DOCUMENTS_PATH = str(DOWNLOAD_DIR) + '/'
DOCUMENT_METADATA_PATH = 'document_metadata.json'
DEDUPLICATION_LOG_PATH = 'deduplication_log.json'

class DeduplicationTracker:
    def __init__(self, names_path=NAMES_PATH, docs_path=DOCUMENTS_PATH,
                 metadata_path=DOCUMENT_METADATA_PATH,
                 log_path=DEDUPLICATION_LOG_PATH):
        self.names_path = names_path
        self.docs_path = docs_path
        self.metadata_path = metadata_path
        self.log_path = log_path
        self.name_to_docs = defaultdict(list)
        self.deduplication_log = []
    
    def load_processed_names(self):
        '''
        Returns a list of search names.
        '''
        with open(self.names_path, 'r') as f:
            names = json.load(f)
        return names

    def scan_documents(self):
        '''
        Returns a list of all documents in the downloaded_doc folder.
        '''
        docs = [f for f in os.listdir(self.docs_path)
                if os.path.isfile(os.path.join(self.docs_path, f))]
        return docs

    def extract_mapping(self, names, docs):
        '''
        Maps names to documents based on filename convention:
        Expects files like 'John-Doe_propertyA.pdf' or similar. Adjust here as needed.
        '''
        mapping = defaultdict(list)
        log = []
        used_docs_set = set()

        for name in names:
            matched = []
            for doc in docs:
                # Example: simple presence check
                name_normalized = name.replace(' ', '_').lower()
                doc_lower = doc.lower()
                if name_normalized in doc_lower:
                    matched.append(doc)
                    used_docs_set.add(doc)
            if matched:
                mapping[name] = matched
                log.append({
                    'name': name,
                    'documents': matched,
                    'status': 'matched',
                    'info': f"{len(matched)} documents found for name {name}"
                })
            else:
                log.append({
                    'name': name,
                    'documents': [],
                    'status': 'no_match',
                    'info': "No documents matched for name"
                })
        unused_docs = [doc for doc in docs if doc not in used_docs_set]
        if unused_docs:
            log.append({
                'unused_documents': unused_docs,
                'status': 'unmatched_documents',
                'info': f"{len(unused_docs)} documents were not matched to any name"
            })
        return mapping, log

    def run(self):
        if not os.path.exists(self.names_path):
            raise FileNotFoundError(f"Names file not found: {self.names_path}")
        if not os.path.isdir(self.docs_path):
            raise NotADirectoryError(f"Documents directory not found: {self.docs_path}")
        names = self.load_processed_names()
        docs = self.scan_documents()
        mapping, log = self.extract_mapping(names, docs)
        # Write logs
        self._save_json(self.metadata_path, mapping)
        self._save_json(self.log_path, log)
        print(f"[DeduplicationTracker] Generated {self.metadata_path} and {self.log_path}")
    
    @staticmethod
    def _save_json(filepath, data):
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

def main():
    tracker = DeduplicationTracker()
    tracker.run()

if __name__ == "__main__":
    main()
