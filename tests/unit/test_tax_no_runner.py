"""Codex finding 3 — TAX_NO_RUNNER must be non-blocking.

A county with no recipe + no legacy scraper entry must produce
`status=TAX_NO_RUNNER` from the dispatcher, and (by default) the pipeline
phase must NOT raise. Only with `strict_tax_no_runner=True` does it raise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.tax import fetch_tax
from titlepro.tax.result import TaxLookupResult


def test_unknown_county_returns_tax_no_runner(tmp_path):
    """A county that does not exist in county_tax_urls.json returns TAX_NO_RUNNER."""
    result = fetch_tax(
        county_id="some_unknown_county_xyz",
        apn="123-456-78",
        owner_name="TEST OWNER",
        property_address="123 Anywhere St",
        case_dir=tmp_path,
    )
    assert isinstance(result, TaxLookupResult)
    assert result.status == "TAX_NO_RUNNER"
    assert "some_unknown_county_xyz" in result.notes


def test_direct_platform_without_recipe_returns_tax_no_runner(tmp_path):
    """A county whose platform is 'direct' (no recipe declared) returns TAX_NO_RUNNER.

    Per county_tax_urls.json, many CA counties currently sit on
    platform="direct" with no implemented runner; they must NOT hard-fail
    the pipeline phase.
    """
    # 'kern' is still platform='direct' in the current config; it has no
    # recipe file, so the dispatcher should yield TAX_NO_RUNNER.
    # (sacramento was flipped to playwright_form when its recipe landed 2026-05-13.)
    result = fetch_tax(
        county_id="kern",
        apn="123-456-78",
        owner_name="TEST OWNER",
        property_address="123 Anywhere St",
        case_dir=tmp_path,
    )
    assert isinstance(result, TaxLookupResult)
    assert result.status == "TAX_NO_RUNNER"


def test_pipeline_lenient_pass_through_for_no_runner(tmp_path, monkeypatch):
    """End-to-end: pipeline.tax_lookup with strict_tax_no_runner=False (default)
    must NOT raise when the dispatcher returns TAX_NO_RUNNER."""
    from titlepro.automation import pipeline as pipeline_module
    from titlepro.automation.pipeline import RecorderAutomationPipeline, WorkflowConfig

    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)

    cfg = WorkflowConfig.from_dict({
        "owner_name": "TEST",
        "county": "some_unknown_county_xyz",
        "search_requests": [{"name": "TEST"}],
        "fetch_tax": True,
        "apn": "123-456-78",
        "strict_tax_no_runner": False,
    })
    pipeline = RecorderAutomationPipeline(cfg)
    out = pipeline.tax_lookup()
    assert out["success"] is True
    assert out["status"] == "TAX_NO_RUNNER"

    # Sidecar must record the explicit TAX_NO_RUNNER status so downstream
    # RAW generation can enforce "TAX STATUS NOT VERIFIED".
    sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
    assert sidecar["status"] == "TAX_NO_RUNNER"
    assert sidecar["tax_status"] == "TAX_NO_RUNNER"


def test_pipeline_strict_mode_raises_for_no_runner(tmp_path, monkeypatch):
    """With strict_tax_no_runner=True, TAX_NO_RUNNER becomes a hard failure."""
    from titlepro.automation import pipeline as pipeline_module
    from titlepro.automation.pipeline import (
        RecorderAutomationPipeline,
        WorkflowConfig,
        WorkflowError,
    )

    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)

    cfg = WorkflowConfig.from_dict({
        "owner_name": "TEST",
        "county": "some_unknown_county_xyz",
        "search_requests": [{"name": "TEST"}],
        "fetch_tax": True,
        "apn": "123-456-78",
        "strict_tax_no_runner": True,
    })
    pipeline = RecorderAutomationPipeline(cfg)
    with pytest.raises(WorkflowError, match="no runner"):
        pipeline.tax_lookup()
