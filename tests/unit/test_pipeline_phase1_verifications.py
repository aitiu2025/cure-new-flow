"""Tests for the `phase1_verifications` pipeline phase (2026-06-10).

Until this phase existed, phase1_verifications.json was only written by
per-case run_e2e.py scripts — the rendering layer
(_build_phase1_verifications_block) was wired but nothing populated the
v1.6 keys (vesting_chain_walker / noc_termination_bundles /
title_affidavit_pairings) in a normal pipeline run.

These tests seed a synthetic case folder (documents_found.json +
document_metadata.json + *_extracted.md) and run the phase directly —
no LLM, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.automation import pipeline as pipeline_module
from titlepro.automation.pipeline import (
    RecorderAutomationPipeline,
    WorkflowConfig,
    WorkflowError,
)


@pytest.fixture
def case_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)
    return tmp_path


def _build_pipeline(config_overrides: dict | None = None) -> RecorderAutomationPipeline:
    data = {
        "owner_name": "SMITH JOHN",
        "county": "broward",
        "state": "FL",
        "search_requests": [{"name": "SMITH JOHN"}, {"name": "SMITH JANE"}],
        "output_folder_name": "Broward_SMITH_test",
        "apn": "504210010010",
        "property_address": "123 MAIN ST, FORT LAUDERDALE, FL 33301",
        "ai": {"provider": "stub"},
    }
    data.update(config_overrides or {})
    return RecorderAutomationPipeline(WorkflowConfig.from_dict(data))


def _seed_case(pipeline: RecorderAutomationPipeline) -> None:
    """Two deeds (vesting WD + older WD), one released mortgage, one open."""
    documents = [
        {
            "document_number": "120000001",
            "document_type": "WARRANTY DEED",
            "recording_date": "06/15/2020",
            "grantors": "JONES ROBERT",
            "grantees": "SMITH JOHN; SMITH JANE",
        },
        {
            "document_number": "110000001",
            "document_type": "WARRANTY DEED",
            "recording_date": "03/01/2011",
            "grantors": "MILLER ALICE",
            "grantees": "JONES ROBERT",
        },
        {
            "document_number": "120000002",
            "document_type": "MORTGAGE",
            "recording_date": "06/15/2020",
            "grantors": "SMITH JOHN; SMITH JANE",
            "grantees": "FAIRWAY MORTGAGE",
        },
        {
            "document_number": "115000001",
            "document_type": "MORTGAGE",
            "recording_date": "02/01/2015",
            "grantors": "JONES ROBERT",
            "grantees": "SUNTRUST BANK",
        },
        {
            "document_number": "121000001",
            "document_type": "SATISFACTION OF MORTGAGE",
            "recording_date": "01/10/2021",
            "grantors": "SUNTRUST BANK",
            "grantees": "JONES ROBERT",
        },
    ]
    pipeline.documents_found_path().write_text(
        json.dumps(documents, indent=2), encoding="utf-8"
    )

    texts = {
        "120000001": (
            "WARRANTY DEED\n\nJONES ROBERT, grantor, conveys to SMITH JOHN "
            "and SMITH JANE, grantees, the property located at 123 MAIN ST, "
            "FORT LAUDERDALE, FL 33301."
        ),
        "110000001": (
            "WARRANTY DEED\n\nMILLER ALICE conveys to JONES ROBERT the "
            "property at 123 MAIN ST, FORT LAUDERDALE, FL 33301."
        ),
        "120000002": (
            "MORTGAGE\n\nSMITH JOHN and SMITH JANE mortgage to FAIRWAY "
            "MORTGAGE the property at 123 MAIN ST, FORT LAUDERDALE, FL 33301."
        ),
        "115000001": (
            "MORTGAGE\n\nJONES ROBERT mortgages to SUNTRUST BANK the "
            "property at 123 MAIN ST, FORT LAUDERDALE, FL 33301."
        ),
        "121000001": (
            "SATISFACTION OF MORTGAGE\n\nThis Satisfaction of Mortgage "
            "hereby satisfies Mortgage recorded as Instrument 115000001 in "
            "the Official Records of Broward County, Florida."
        ),
    }
    metadata = {}
    for doc_num, body in texts.items():
        filename = f"{doc_num}.pdf"
        metadata[doc_num] = {"filename": filename}
        (pipeline.case_dir / f"{doc_num}_extracted.md").write_text(
            body, encoding="utf-8"
        )
    (pipeline.case_dir / "document_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def test_phase_in_order_between_extraction_and_tax():
    order = RecorderAutomationPipeline.phase_order
    assert "phase1_verifications" in order
    assert order.index("extract_legal_descriptions") < order.index("phase1_verifications")
    assert order.index("phase1_verifications") < order.index("tax_lookup")


def test_phase_enabled_respects_config_flag(case_root):
    assert _build_pipeline().phase_enabled("phase1_verifications") is True
    disabled = _build_pipeline({"run_phase1_verifications": False})
    assert disabled.phase_enabled("phase1_verifications") is False


def test_phase_requires_documents(case_root):
    pipeline = _build_pipeline()
    with pytest.raises(WorkflowError):
        pipeline.phase1_verifications()


def test_phase_populates_all_v16_keys(case_root):
    pipeline = _build_pipeline()
    _seed_case(pipeline)

    details = pipeline.phase1_verifications()

    assert details["success"] is True
    assert details["documents"] == 5
    assert details["documents_with_text"] == 5

    sidecar = json.loads(pipeline.phase1_verifications_path().read_text())
    for key in (
        "subject_address_verification",
        "document_type_classifications",
        "mortgage_classifications",
        "recovered_from_not_needed",
        "not_needed_ledger",
        "vesting_chain_walker",
        "noc_termination_bundles",
        "title_affidavit_pairings",
        "generated_at",
    ):
        assert key in sidecar, f"missing sidecar key: {key}"

    assert sidecar["subject_address"] == "123 MAIN ST, FORT LAUDERDALE, FL 33301"
    assert sidecar["subject_owners"] == ["SMITH JOHN", "SMITH JANE"]

    # Tony #6: satisfied SunTrust mortgage classified released, Fairway open.
    mtg = sidecar["mortgage_classifications"]
    assert mtg["115000001"]["status"] == "released"
    assert mtg["120000002"]["status"] == "open"
    assert details["mortgages_released"] == 1

    # Tony #4: every doc with text got an address verdict against subject.
    addr = sidecar["subject_address_verification"]
    assert addr["120000001"]["status"] == "MATCH"

    # Walker ran (2011→2020 gap, different parties → PASS-shaped outcome).
    assert sidecar["vesting_chain_walker"]["status"]
    # No not_needed/ dir in this fixture — note recorded, nothing recovered.
    assert sidecar["recovered_from_not_needed"] == []
    assert "not_needed_audit_note" in sidecar


def test_merge_preserves_unknown_sidecar_keys(case_root):
    pipeline = _build_pipeline()
    _seed_case(pipeline)
    pipeline.phase1_verifications_path().write_text(
        json.dumps({"custom_manual_key": {"kept": True}}), encoding="utf-8"
    )

    pipeline.phase1_verifications()

    sidecar = json.loads(pipeline.phase1_verifications_path().read_text())
    assert sidecar["custom_manual_key"] == {"kept": True}
    assert "vesting_chain_walker" in sidecar


def test_skip_validator_rejects_legacy_sidecar(case_root):
    pipeline = _build_pipeline()
    assert pipeline._phase1_verifications_skip_ok() is False

    # Legacy (pre-v1.6) sidecar — subject-address + mortgage keys only.
    pipeline.phase1_verifications_path().write_text(
        json.dumps({
            "subject_address_verification": {},
            "mortgage_classifications": {},
        }),
        encoding="utf-8",
    )
    assert pipeline._phase1_verifications_skip_ok() is False

    _seed_case(pipeline)
    pipeline.phase1_verifications()
    assert pipeline._phase1_verifications_skip_ok() is True


def test_sidecar_feeds_prompt_renderer(case_root):
    """End-to-end within the pipeline: populated sidecar renders into the
    LLM prompt block with the released-mortgage reporting rule."""
    pipeline = _build_pipeline()
    _seed_case(pipeline)
    pipeline.phase1_verifications()

    block = pipeline._build_phase1_verifications_block()
    assert "Phase-1 Verifications" in block
    assert "115000001" in block
    assert "released" in block
    assert "Tony #6 directive" in block
