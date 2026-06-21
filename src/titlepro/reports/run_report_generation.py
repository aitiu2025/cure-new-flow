import json
import os
from pathlib import Path
from collections import OrderedDict
from titlepro.reports.report_generator_v2 import generate_reports_for_subject

def dedupe_documents(docs):
    # Deduplicate based on doc_id and retain order
    seen = set()
    deduped = []
    for d in docs:
        key = d.get('doc_id')
        if key not in seen:
            deduped.append(d)
            seen.add(key)
    return deduped

def main(data_path='test_subjects.json', output_dir='generated_reports'):
    with open(data_path, 'r', encoding='utf-8') as f:
        subjects = json.load(f)["subjects"]
    for subject, data in subjects.items():
        data = data.copy()
        data['documents'] = dedupe_documents(data.get('documents', []))
        md, pdf = generate_reports_for_subject(subject, data, output_dir)
        print(f"[OK] Reports for '{subject}' written to: {md} and {pdf}")

if __name__ == "__main__":
    main()
