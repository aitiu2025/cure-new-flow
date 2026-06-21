"""Benchmark the post-download report-gen pipeline on Hillsborough FROMER.

Measures per-phase wall-clock for the changes shipped 2026-06-15:
  #1 per-phase model selection (RAW=opus-4-8, Title=sonnet-4-6)
  #3 deterministic legal-description splice (runs before the validator)

Run:  cd <project root> && source venv/bin/activate && PYTHONPATH=src \
      python tools/bench_fromer.py

Targets the v1 case folder whose config already points output_folder_name at
itself (so the tax filename matches and case_dir resolves correctly). Reuses
the 52 already-downloaded PDFs; re-runs OCR + both LLM report phases fresh so
the timing reflects a real cold generation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from titlepro.automation.pipeline import WorkflowConfig, RecorderAutomationPipeline

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "src/titlepro/api/downloaded_doc/0526/Hillsborough_FROMER_v1"
RESULTS = ROOT / "tools/bench_fromer_results.txt"

PHASES = [
    "extract_text",
    "extract_legal_descriptions",
    "generate_raw_report",
    "generate_title_notes",
    "render_pdfs",
]

lines: list[str] = []


def emit(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def ensure_document_metadata() -> None:
    """extract_text -> load_metadata() needs document_metadata.json mapping
    doc# -> {filename, ...}. Reconstruct from documents_found.json + on-disk
    <doc#>.pdf when absent (download phase normally writes it)."""
    meta_path = CASE / "document_metadata.json"
    if meta_path.exists():
        emit(f"  document_metadata.json present")
        return
    docs = json.loads((CASE / "documents_found.json").read_text())
    meta = {}
    for e in docs:
        dn = str(e["document_number"])
        if (CASE / f"{dn}.pdf").exists():
            meta[dn] = {**e, "filename": f"{dn}.pdf"}
    meta_path.write_text(json.dumps(meta, indent=2))
    emit(f"  RECONSTRUCTED document_metadata.json with {len(meta)} entries")


def main() -> None:
    emit("=" * 64)
    emit("FROMER post-download benchmark")
    emit("=" * 64)
    ensure_document_metadata()

    cfg = WorkflowConfig.from_file(CASE / "workflow_config.json")
    # The case config disables these; force-running a phase only bypasses the
    # resume-skip, not the enabled-flag, so flip them on in memory.
    cfg.extract_legal_descriptions = True
    cfg.generate_title_notes = True
    # Uncap budget for an accurate generation time (the 900s timeout still caps
    # wall-clock); the $5 default could abort a large FROMER prompt mid-run.
    cfg.ai.max_budget_usd = 25.0

    pipe = RecorderAutomationPipeline(cfg)
    emit(f"  case_dir: {pipe.case_dir}")
    emit(f"  resolved models -> raw: {pipe._resolve_phase_model('raw')} | "
         f"title: {pipe._resolve_phase_model('title')}")
    emit(f"  splice enabled: {cfg.splice_legal_descriptions} | "
         f"validate enabled: {cfg.validate_legal_descriptions}")
    emit("")

    timings: list[tuple[str, float, str]] = []
    for ph in PHASES:
        t0 = time.perf_counter()
        try:
            state = pipe.run_phase(ph, force=True)
            dt = time.perf_counter() - t0
            timings.append((ph, dt, "ok"))
            emit(f"[{ph}] {dt:7.1f}s  OK")
            if ph in ("generate_raw_report", "generate_title_notes"):
                # run_phase() returns the FULL state store, not the phase
                # `details`. The splice/validation summaries are persisted under
                # phases[<phase>].details (see WorkflowStateStore.mark_completed
                # + workflow_status.json), so reach into that nested node.
                det = state.get("phases", {}).get(ph, {}).get("details", {})
                rep = det.get("legal_description_repair")
                val = det.get("legal_description_validation")
                emit(f"     splice: {rep}")
                emit(f"     validation: {val}")
        except Exception as exc:  # noqa: BLE001 - benchmark records failures
            dt = time.perf_counter() - t0
            timings.append((ph, dt, f"FAIL: {exc}"))
            emit(f"[{ph}] {dt:7.1f}s  FAIL: {exc}")

    emit("")
    emit("-" * 64)
    emit(f"{'PHASE':<30}{'SECONDS':>10}{'MINUTES':>10}  STATUS")
    emit("-" * 64)
    total = 0.0
    for ph, dt, status in timings:
        total += dt
        emit(f"{ph:<30}{dt:>10.1f}{dt/60:>10.2f}  {status.split(':')[0]}")
    emit("-" * 64)
    emit(f"{'TOTAL post-download':<30}{total:>10.1f}{total/60:>10.2f}")
    emit("=" * 64)

    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nResults written to {RESULTS}", flush=True)


if __name__ == "__main__":
    main()
