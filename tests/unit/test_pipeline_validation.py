"""Tests for `generate_title_notes` and `generate_raw_report` validation.

Both methods must raise `WorkflowError` when the agent output is missing
required H2 sections (so we do NOT persist garbage markdown to disk).
This mirrors the existing pattern in `_enforce_tax_status_in_raw`.

These tests stub out `_run_agent` and the prompt-file lookups so no real
LLM call is made; only the validation path is exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.automation import pipeline as pipeline_module
from titlepro.automation.pipeline import (
    RecorderAutomationPipeline,
    TITLE_REQUIRED_SECTIONS,
    RAW_REQUIRED_SECTIONS,
    WorkflowConfig,
    WorkflowError,
)


@pytest.fixture
def case_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)
    return tmp_path


def _build_pipeline(case_dir: Path) -> RecorderAutomationPipeline:
    cfg = WorkflowConfig.from_dict({
        "owner_name": "AMAYA JANINE",
        "county": "fresno",
        "search_requests": [{"name": "AMAYA JANINE"}],
        "output_folder_name": "Fresno_AMAYA_Janine",
        "apn": "455-113-24",
        # Tests stub out the agent + prompt resolution, so don't touch
        # the filesystem for the system-prompt file.
        "ai": {"provider": "stub"},
    })
    return RecorderAutomationPipeline(cfg)


def _stub_prompt_pipeline(pipeline, monkeypatch, agent_output: str) -> None:
    """Patch the methods that would otherwise touch real prompt files / LLM."""
    monkeypatch.setattr(
        pipeline,
        "_build_system_prompt",
        lambda *_a, **_kw: "STUB SYSTEM PROMPT",
        raising=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_resolve_prompt_path",
        lambda *_a, **_kw: Path("/tmp/stub_prompt.md"),
        raising=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_title_user_prompt",
        lambda: "STUB TITLE USER PROMPT",
        raising=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_build_raw_user_prompt",
        lambda: "STUB RAW USER PROMPT",
        raising=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_save_prompt_bundle",
        lambda *a, **kw: None,
        raising=True,
    )
    monkeypatch.setattr(
        pipeline,
        "_run_agent",
        lambda *_a, **_kw: agent_output,
        raising=True,
    )


# ---------------------------------------------------------------------------
# Title notes validation
# ---------------------------------------------------------------------------


def _good_title_md() -> str:
    """A title markdown containing every required H2/H1."""
    return "\n\n".join(TITLE_REQUIRED_SECTIONS) + "\n\nbody body body\n"


def test_title_notes_with_all_required_sections_does_not_raise(case_dir, monkeypatch):
    pipeline = _build_pipeline(case_dir)
    # The raw md must exist for the upstream guard.
    pipeline.raw_markdown_path().parent.mkdir(parents=True, exist_ok=True)
    pipeline.raw_markdown_path().write_text(
        "\n\n".join(RAW_REQUIRED_SECTIONS) + "\n",
        encoding="utf-8",
    )
    _stub_prompt_pipeline(pipeline, monkeypatch, agent_output=_good_title_md())
    result = pipeline.generate_title_notes()
    assert result["success"] is True
    assert pipeline.title_markdown_path().exists()
    # Validation summary must report success and no missing sections.
    val = result["validation"]
    assert val["success"] is True
    assert val.get("missing_sections", []) == []


def test_title_notes_missing_chain_section_raises(case_dir, monkeypatch):
    pipeline = _build_pipeline(case_dir)
    pipeline.raw_markdown_path().parent.mkdir(parents=True, exist_ok=True)
    pipeline.raw_markdown_path().write_text(
        "\n\n".join(RAW_REQUIRED_SECTIONS) + "\n",
        encoding="utf-8",
    )
    # Build a bad title md missing the CHAIN OF TITLE section.
    bad_sections = [s for s in TITLE_REQUIRED_SECTIONS if "CHAIN OF TITLE" not in s.upper()]
    bad_md = "\n\n".join(bad_sections) + "\n\nbody\n"
    _stub_prompt_pipeline(pipeline, monkeypatch, agent_output=bad_md)
    with pytest.raises(WorkflowError, match="CHAIN OF TITLE"):
        pipeline.generate_title_notes()
    # Crucially: the bad title md must NOT have been persisted.
    assert not pipeline.title_markdown_path().exists()


def test_title_notes_missing_summary_section_raises(case_dir, monkeypatch):
    pipeline = _build_pipeline(case_dir)
    pipeline.raw_markdown_path().parent.mkdir(parents=True, exist_ok=True)
    pipeline.raw_markdown_path().write_text(
        "\n\n".join(RAW_REQUIRED_SECTIONS) + "\n",
        encoding="utf-8",
    )
    bad_sections = [
        s for s in TITLE_REQUIRED_SECTIONS if "TITLE EXAMINATION SUMMARY" not in s.upper()
    ]
    bad_md = "\n\n".join(bad_sections) + "\n\nbody\n"
    _stub_prompt_pipeline(pipeline, monkeypatch, agent_output=bad_md)
    with pytest.raises(WorkflowError, match="TITLE EXAMINATION SUMMARY"):
        pipeline.generate_title_notes()
    assert not pipeline.title_markdown_path().exists()


# ---------------------------------------------------------------------------
# RAW report validation (parallel fix — also raises on missing sections)
# ---------------------------------------------------------------------------


def _good_raw_md() -> str:
    body = "\n\n".join(RAW_REQUIRED_SECTIONS) + "\n\nTAX STATUS NOT VERIFIED\n"
    return body


def test_raw_report_with_all_required_sections_does_not_raise(case_dir, monkeypatch):
    pipeline = _build_pipeline(case_dir)
    # `generate_raw_report` calls `_extraction_summary` which checks for
    # docs_for_report.json. Stub it.
    monkeypatch.setattr(
        pipeline,
        "_extraction_summary",
        lambda raise_on_failure: {"success": True, "extracted_count": 0},
        raising=True,
    )
    # No tax_lookup_status.json => _enforce_tax_status_in_raw treats as missing
    # which (because fetch_tax=True) demands "TAX STATUS NOT VERIFIED" in the md.
    _stub_prompt_pipeline(pipeline, monkeypatch, agent_output=_good_raw_md())
    result = pipeline.generate_raw_report()
    assert result["success"] is True
    assert pipeline.raw_markdown_path().exists()


def test_raw_report_missing_phase_section_raises(case_dir, monkeypatch):
    pipeline = _build_pipeline(case_dir)
    monkeypatch.setattr(
        pipeline,
        "_extraction_summary",
        lambda raise_on_failure: {"success": True, "extracted_count": 0},
        raising=True,
    )
    # Drop PHASE 3 from the output.
    bad_sections = [s for s in RAW_REQUIRED_SECTIONS if "PHASE 3" not in s.upper()]
    bad_md = "\n\n".join(bad_sections) + "\n\nTAX STATUS NOT VERIFIED\n"
    _stub_prompt_pipeline(pipeline, monkeypatch, agent_output=bad_md)
    with pytest.raises(WorkflowError, match="PHASE 3"):
        pipeline.generate_raw_report()
    # The bad RAW md must NOT have been persisted.
    assert not pipeline.raw_markdown_path().exists()
