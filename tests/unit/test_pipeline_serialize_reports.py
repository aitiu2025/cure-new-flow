"""Tests for the `serialize_reports` pipeline phase.

The phase wraps `build_json_xml_reports.build_case` and must:
- be present in `phase_order` after `render_pdfs`
- be gated by `WorkflowConfig.generate_json_xml_reports`
- produce <stem>.json + <stem>.xml that parse cleanly
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from titlepro.automation import pipeline as pipeline_module
from titlepro.automation.pipeline import RecorderAutomationPipeline, WorkflowConfig


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
        "ai": {"provider": "stub"},
    })
    return RecorderAutomationPipeline(cfg)


def _seed_raw_markdown(pipeline: RecorderAutomationPipeline) -> None:
    md = pipeline.raw_markdown_path()
    md.write_text(
        "# RAW TWO-OWNER TITLE SEARCH EXAMINATION REPORT\n"
        "\n"
        "Preamble paragraph for the synthetic case.\n"
        "\n"
        "## PHASE 1: RECORDER NAME SEARCHES\n"
        "\n"
        "Phase 1 body.\n"
        "\n"
        "## PHASE 2: DOCUMENT REVIEW\n"
        "\n"
        "Phase 2 body.\n",
        encoding="utf-8",
    )


def _seed_minimal_artifacts(pipeline: RecorderAutomationPipeline) -> None:
    (pipeline.case_dir / "workflow_config.json").write_text(
        json.dumps({"owner_name": "AMAYA JANINE", "county": "fresno"}), encoding="utf-8",
    )
    (pipeline.case_dir / "documents_found.json").write_text(json.dumps([]), encoding="utf-8")


def test_phase_registered_after_render_pdfs():
    order = RecorderAutomationPipeline.phase_order
    assert "serialize_reports" in order
    assert order.index("serialize_reports") == order.index("render_pdfs") + 1


def test_phase_enabled_reflects_flag(case_dir):
    pipeline = _build_pipeline(case_dir)
    assert pipeline.phase_enabled("serialize_reports") is True
    pipeline.config.generate_json_xml_reports = False
    assert pipeline.phase_enabled("serialize_reports") is False


def test_serialize_reports_writes_json_and_xml(case_dir):
    pipeline = _build_pipeline(case_dir)
    _seed_raw_markdown(pipeline)
    _seed_minimal_artifacts(pipeline)

    result = pipeline.serialize_reports()

    assert result["success"] is True
    outputs = result["outputs"]
    assert any(item["stem"] == "RAW_TWO_OWNER_SEARCH_EXAM" and item.get("status") == "written" for item in outputs)

    json_path = pipeline.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json"
    xml_path = pipeline.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.xml"
    assert json_path.exists()
    assert xml_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["section_count"] == 2
    assert data["report_metadata"]["source_input_used"] == "markdown"
    assert data["report_metadata"]["generator_version"] == "1.0"

    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    assert root.tag == "RAW_TWO_OWNER_SEARCH_EXAM"


def test_serialize_summary_success_when_outputs_present(case_dir):
    pipeline = _build_pipeline(case_dir)
    _seed_raw_markdown(pipeline)
    _seed_minimal_artifacts(pipeline)
    pipeline.serialize_reports()
    summary = pipeline._serialize_summary(raise_on_failure=False)
    assert summary["success"] is True
    assert summary["details"]["raw_json"] is True
    assert summary["details"]["raw_xml"] is True


def test_serialize_summary_fails_when_outputs_missing(case_dir):
    pipeline = _build_pipeline(case_dir)
    _seed_raw_markdown(pipeline)
    summary = pipeline._serialize_summary(raise_on_failure=False)
    assert summary["success"] is False
