"""audit_existing_case.py - re-run not_needed audit + linker on a case folder."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

# Add src/ to path
REPO_ROOT = Path("/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro")
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from titlepro.verification.not_needed_audit import (
    audit_not_needed,
    _extract_mortgage_metadata,
)
from titlepro.verification.released_mortgage_linker import classify_mortgages
from titlepro.verification.document_type_classifier import classify_all_documents


def load_documents(case_dir: Path) -> List[dict]:
    p = case_dir / "documents_found.json"
    if not p.exists():
        raise FileNotFoundError(f"documents_found.json missing in {case_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_extracted_texts(case_dir: Path) -> Dict[str, str]:
    texts: Dict[str, str] = {}
    for md in case_dir.glob("*_extracted.md"):
        stem = md.stem
        if stem.endswith("_extracted"):
            stem = stem[: -len("_extracted")]
        texts[stem] = md.read_text(encoding="utf-8", errors="replace")
    return texts


def main(case_dir: Path, write: bool = True) -> int:
    case_dir = case_dir.resolve()
    print(f"[audit] case_dir={case_dir}")

    documents = load_documents(case_dir)
    extracted_texts = load_extracted_texts(case_dir)
    print(f"[audit] loaded {len(documents)} documents, {len(extracted_texts)} extracted texts")

    classifications = classify_all_documents(documents, extracted_texts)
    inferred_types = {n: c.inferred_type for n, c in classifications.items()}

    mortgage_docs = [
        d for d in documents
        if inferred_types.get(
            d.get("doc_number") or d.get("document_number") or ""
        ) == "MORTGAGE"
    ]
    known_mortgages = _extract_mortgage_metadata(mortgage_docs, extracted_texts)
    print(f"[audit] known_mortgages: {list(known_mortgages.keys())}")
    for k, v in known_mortgages.items():
        print(f"   {k}: book={v.book} page={v.page} min={v.min_number} principal={v.original_principal}")

    audit_result = None
    if known_mortgages:
        try:
            audit_result = audit_not_needed(case_dir, known_mortgages)
            print(f"[audit] recovered {len(audit_result.recovered)} doc(s)")
            for rec in audit_result.recovered:
                print(f"   recovered: {rec.doc_number} -> mortgage {rec.target_mortgage_doc} via {rec.match_method} (conf={rec.classification_confidence:.2f})")
            print(f"[audit] ledger: {len(audit_result.ledger)} entry(ies)")
            for e in audit_result.ledger:
                print(f"   ledger: {e.doc_number} | {e.classified_type} | {e.disposition} | {e.reason[:80]}")
        except Exception as e:
            print(f"[audit] FAILED: {e}")

    recovered = audit_result.recovered if audit_result else None
    mortgage_classifications = classify_mortgages(
        documents,
        extracted_texts,
        inferred_types=inferred_types,
        recovered_docs=recovered,
    )

    pv_path = case_dir / "phase1_verifications.json"
    if pv_path.exists():
        data = json.loads(pv_path.read_text(encoding="utf-8"))
    else:
        data = {}

    print("\n[audit] BEFORE mortgage_classifications:")
    for num, mc in data.get("mortgage_classifications", {}).items():
        print(f"   {num}: status={mc.get('status')} chain={mc.get('release_chain')} mods={mc.get('related_modifications')}")

    data["mortgage_classifications"] = {
        num: mc.to_dict() for num, mc in mortgage_classifications.items()
    }
    if audit_result:
        data["recovered_from_not_needed"] = [r.to_dict() for r in audit_result.recovered]
        data["not_needed_ledger"] = [e.to_dict() for e in audit_result.ledger]
    else:
        data.setdefault("recovered_from_not_needed", [])
        data.setdefault("not_needed_ledger", [])

    print("\n[audit] AFTER mortgage_classifications:")
    for num, mc in mortgage_classifications.items():
        chain_disp = [
            f"{l.satisfaction_doc_number}({l.satisfaction_type})"
            for l in mc.release_chain
        ]
        print(f"   {num}: status={mc.status} chain={chain_disp} mods={mc.related_modifications}")

    if write:
        backup = pv_path.with_suffix(".json.bak_pre_audit")
        if pv_path.exists() and not backup.exists():
            backup.write_bytes(pv_path.read_bytes())
            print(f"\n[audit] backed up phase1_verifications.json -> {backup.name}")
        pv_path.write_text(
            json.dumps(data, indent=2, sort_keys=False),
            encoding="utf-8",
        )
        print(f"[audit] wrote {pv_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python audit_existing_case.py <case_dir> [--no-write]")
        sys.exit(2)
    case_dir = Path(sys.argv[1])
    write = "--no-write" not in sys.argv
    sys.exit(main(case_dir, write=write))
