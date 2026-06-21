"""Generate RAW + Title reports for a county case into the 0616 batch folder.

Reuse path: copy a prior case folder's downloaded docs/sidecars into
`downloaded_doc/0616/<label>/`, reconstruct any missing metadata/extraction
summary FROM the cached `*_extracted.md` (no re-OCR), then run the LLM report
phases with the per-phase model defaults (RAW=opus-4-8, Title=sonnet-4-6) and
the deterministic legal-description splice.

Usage:
  python tools/gen_0616_case.py --source <src_case_dir> --label <County_NAME> [--no-llm]

  --source   path (abs or repo-relative) to the prior case folder to reuse
  --label    destination folder name under 0616/ (e.g. Duval_SKINNER)
  --no-llm   set up the folder + extraction only; skip RAW/Title/render
             (used to validate setup cheaply before spending on generation)

OnE is authored separately by the orchestrating agent (it is not a pipeline
phase) using docs/Cure_Response/OnE_Report_SystemPrompt_v1.2.md + the canonical
DOCX renderer.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from titlepro.automation.pipeline import WorkflowConfig, RecorderAutomationPipeline

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = ROOT / "src/titlepro/api/downloaded_doc"

# Outputs/state that must NOT carry over from the source run (regenerate fresh).
_STALE = (
    "workflow_status.json",
    "extraction_summary.json",
)
_STALE_GLOBS = (
    "RAW_TWO_OWNER_SEARCH_EXAM*",
    "Title_Examination_Notes*",
    "OnE_Report*",
    "*.prebench.bak",
)


def emit(msg: str) -> None:
    print(msg, flush=True)


def setup_dest(source: Path, label: str) -> Path:
    dest = DOWNLOADS / "0616" / label
    dest.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_dir():
            continue
        shutil.copy2(item, dest / item.name)
    # Drop stale outputs/state so phases regenerate.
    for name in _STALE:
        (dest / name).unlink(missing_ok=True)
    for pat in _STALE_GLOBS:
        for p in dest.glob(pat):
            p.unlink(missing_ok=True)
    emit(f"  dest: {dest}")
    return dest


def reconstruct_metadata(dest: Path) -> None:
    """document_metadata.json maps doc# -> {filename,...}. Reconstruct from
    documents_found.json + on-disk <doc#>.pdf (or the *_extracted.md stem)."""
    meta_path = dest / "document_metadata.json"
    if meta_path.exists():
        return
    df = dest / "documents_found.json"
    if not df.exists():
        emit("  WARN: no documents_found.json; cannot reconstruct metadata")
        return
    docs = json.loads(df.read_text())
    meta = {}
    for e in docs:
        dn = str(e["document_number"])
        pdf = dest / f"{dn}.pdf"
        ext = dest / f"{dn}_extracted.md"
        if pdf.exists():
            meta[dn] = {**e, "filename": f"{dn}.pdf"}
        elif ext.exists():
            meta[dn] = {**e, "filename": f"{dn}.pdf", "_extracted_only": True}
    meta_path.write_text(json.dumps(meta, indent=2))
    emit(f"  reconstructed document_metadata.json ({len(meta)} entries)")


def reconstruct_extraction_summary(dest: Path) -> bool:
    """If extraction_summary.json is missing but *_extracted.md exist, rebuild
    it from the cached markdown so generate_raw_report's gate passes WITHOUT
    re-OCR. Returns True when extraction is satisfied (cached or rebuilt),
    False when extract_text must be run (no cached markdown)."""
    summ = dest / "extraction_summary.json"
    if summ.exists():
        return True
    df = dest / "documents_found.json"
    docs = json.loads(df.read_text()) if df.exists() else []
    results = []
    for e in docs:
        dn = str(e["document_number"])
        ext = dest / f"{dn}_extracted.md"
        if not ext.exists():
            continue
        text = ext.read_text(encoding="utf-8", errors="ignore")
        results.append({
            "document_number": dn,
            "filename": f"{dn}.pdf",
            "extracted_markdown": ext.name,
            "total_chars": len(text),
            "ocr_used": "(ocr)" in text.lower(),
        })
    if not results:
        return False  # no cached extraction -> caller runs extract_text
    summ.write_text(json.dumps({
        "success": True,
        "validated_documents": len(results),
        "extracted_documents": len(results),
        "documents": results,
    }, indent=2))
    emit(f"  rebuilt extraction_summary.json from {len(results)} cached _extracted.md")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    source = Path(args.source)
    if not source.is_absolute():
        source = (ROOT / source).resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")

    emit("=" * 64)
    emit(f"0616 case generation: {args.label}")
    emit(f"  source: {source}")
    dest = setup_dest(source, args.label)
    reconstruct_metadata(dest)
    have_extraction = reconstruct_extraction_summary(dest)

    cfg = WorkflowConfig.from_file(dest / "workflow_config.json")
    cfg.output_folder_name = f"0616/{args.label}"
    cfg.extract_legal_descriptions = True
    cfg.generate_title_notes = True
    cfg.generate_raw_pdf = True
    cfg.generate_title_pdf = True
    cfg.ai.max_budget_usd = 25.0  # accurate gen time; 900s timeout still caps

    pipe = RecorderAutomationPipeline(cfg)
    emit(f"  case_dir: {pipe.case_dir}")
    emit(f"  models -> raw: {pipe._resolve_phase_model('raw')} | title: {pipe._resolve_phase_model('title')}")
    emit(f"  extraction satisfied from cache: {have_extraction}")

    phases = []
    if not have_extraction:
        phases.append("extract_text")
    phases += ["extract_legal_descriptions", "generate_raw_report",
               "generate_title_notes", "render_pdfs"]

    if args.no_llm:
        emit(f"  --no-llm: setup complete. Would run: {phases}")
        # still produce the legal sidecar so OnE/splice have it
        try:
            t0 = time.perf_counter()
            det = pipe.run_phase("extract_legal_descriptions", force=True)
            emit(f"  [extract_legal_descriptions] {time.perf_counter()-t0:.1f}s -> {det.get('with_legal_description')} legal / {det.get('with_apn')} apn")
        except Exception as exc:  # noqa: BLE001
            emit(f"  extract_legal_descriptions FAILED: {exc}")
        return

    timings = []
    for ph in phases:
        t0 = time.perf_counter()
        try:
            det = pipe.run_phase(ph, force=True)
            dt = time.perf_counter() - t0
            timings.append((ph, dt, "ok"))
            emit(f"[{ph}] {dt:7.1f}s OK")
        except Exception as exc:  # noqa: BLE001
            dt = time.perf_counter() - t0
            timings.append((ph, dt, f"FAIL: {exc}"))
            emit(f"[{ph}] {dt:7.1f}s FAIL: {exc}")

    total = sum(t for _, t, _ in timings)
    emit("-" * 64)
    for ph, dt, st in timings:
        emit(f"  {ph:<28}{dt:8.1f}s  {st.split(':')[0]}")
    emit(f"  {'TOTAL':<28}{total:8.1f}s ({total/60:.1f} min)")
    emit("=" * 64)


if __name__ == "__main__":
    main()
