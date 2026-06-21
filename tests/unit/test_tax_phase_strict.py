"""Strict-mode tests for the tax_lookup phase (post tax_plumbing v2).

These exercise the phase gate without invoking a real Playwright runner.
We monkey-patch `titlepro.tax.fetch_tax` (the v2 dispatcher) so each test
can simulate a specific `TaxLookupResult.status`.
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
from titlepro.tax.result import TaxLookupResult


@pytest.fixture
def case_dir(tmp_path, monkeypatch):
    """Point DOWNLOAD_DIR at a fresh tmp dir so case folders are isolated."""
    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)
    return tmp_path


def _build_pipeline(
    case_dir: Path,
    *,
    fetch_tax=True,
    apn=None,
    allow_skip=False,
    strict_no_runner=False,
) -> RecorderAutomationPipeline:
    cfg = WorkflowConfig.from_dict({
        "owner_name": "AMAYA JANINE",
        "county": "fresno",
        "search_requests": [{"name": "AMAYA JANINE"}],
        "output_folder_name": "Fresno_AMAYA_Janine",
        "fetch_tax": fetch_tax,
        "apn": apn,
        "allow_tax_skip_on_missing_apn": allow_skip,
        "strict_tax_no_runner": strict_no_runner,
    })
    return RecorderAutomationPipeline(cfg)


def _patch_dispatcher(monkeypatch, result: TaxLookupResult) -> None:
    """Patch the import-site so the pipeline's `from titlepro.tax import fetch_tax`
    resolves to a stub returning the given result."""
    def _fake(**kwargs):
        return result
    # The pipeline does `from titlepro.tax import fetch_tax as _fetch_tax`
    # at call time, so we need to patch the attribute on the tax module.
    import titlepro.tax as tax_pkg
    monkeypatch.setattr(tax_pkg, "fetch_tax", _fake, raising=True)


class TestDisabledPath:
    def test_disabled_writes_sidecar_and_returns_success(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=False)
        result = pipeline.tax_lookup()
        assert result["success"] is True
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "disabled"
        assert sidecar["reason"] == "fetch_tax_disabled"


class TestMissingApnPath:
    def test_missing_apn_fails_by_default(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn=None)
        with pytest.raises(WorkflowError, match="APN"):
            pipeline.tax_lookup()
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "skipped"
        assert sidecar["reason"] == "apn_missing"

    def test_missing_apn_skips_when_allowed(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn=None, allow_skip=True)
        result = pipeline.tax_lookup()
        assert result["success"] is True
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "skipped"


class TestSuccessPath:
    def test_success_writes_success_sidecar(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24")
        ok = TaxLookupResult(
            apn="455-113-24",
            tax_year="2025-26",
            property_address="5041 E HEDGES",
            assessed_value={"net_taxable": 228569},
            installments=[{"label": "first", "amount": 1492.75}],
            annual_total=2985.50,
            source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
            status="TAX_SUCCESS",
            verified_fields=["assessed_value.net_taxable", "annual_total"],
        )
        _patch_dispatcher(monkeypatch, ok)
        out = pipeline.tax_lookup()
        assert out["success"] is True
        assert out["status"] == "TAX_SUCCESS"
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "success"
        assert sidecar["tax_status"] == "TAX_SUCCESS"
        assert "annual_total" in sidecar["verified_fields"]


class TestPartialPath:
    def test_partial_passes_with_partial_sidecar(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24")
        partial = TaxLookupResult(
            apn="455-113-24",
            tax_year="2025-26",
            property_address="",
            source_url="https://fcacttcptr.fresnocountyca.gov/Home/Index",
            status="TAX_PARTIAL",
            verified_fields=["assessed_value.net_taxable"],
            missing_fields=["annual_total"],
            notes="2 of 3 verified",
        )
        _patch_dispatcher(monkeypatch, partial)
        out = pipeline.tax_lookup()
        assert out["success"] is True
        assert out["status"] == "TAX_PARTIAL"
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "TAX_PARTIAL"


class TestNoRunnerPath:
    def test_no_runner_lenient_pass_through(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24", strict_no_runner=False)
        nr = TaxLookupResult(
            apn="455-113-24",
            tax_year="",
            property_address="",
            status="TAX_NO_RUNNER",
            notes="No runner for county 'fresno'.",
        )
        _patch_dispatcher(monkeypatch, nr)
        out = pipeline.tax_lookup()
        assert out["success"] is True
        assert out["status"] == "TAX_NO_RUNNER"
        sidecar = json.loads(pipeline.tax_lookup_status_path().read_text())
        assert sidecar["status"] == "TAX_NO_RUNNER"

    def test_no_runner_strict_raises(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24", strict_no_runner=True)
        nr = TaxLookupResult(
            apn="455-113-24",
            tax_year="",
            property_address="",
            status="TAX_NO_RUNNER",
            notes="No runner for county 'fresno'.",
        )
        _patch_dispatcher(monkeypatch, nr)
        with pytest.raises(WorkflowError, match="no runner"):
            pipeline.tax_lookup()


class TestFailedPath:
    def test_failed_raises_workflow_error(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24")
        failed = TaxLookupResult(
            apn="455-113-24",
            tax_year="",
            property_address="",
            status="TAX_FAILED",
            error="source host mismatch",
        )
        _patch_dispatcher(monkeypatch, failed)
        with pytest.raises(WorkflowError, match="tax_lookup failed"):
            pipeline.tax_lookup()


class TestNoResultsPath:
    def test_no_results_raises_workflow_error(self, case_dir, monkeypatch):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="455-113-24")
        nores = TaxLookupResult(
            apn="455-113-24",
            tax_year="",
            property_address="",
            status="TAX_NO_RESULTS",
            notes="county portal reports parcel not on file",
        )
        _patch_dispatcher(monkeypatch, nores)
        with pytest.raises(WorkflowError, match="no parcel"):
            pipeline.tax_lookup()


class TestRawTaxStatusEnforcement:
    def test_unverified_raw_without_phrase_raises(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="123")
        pipeline.tax_lookup_status_path().write_text(
            json.dumps({"status": "failed", "reason": "x"}),
            encoding="utf-8",
        )
        with pytest.raises(WorkflowError, match="tax-status integrity"):
            pipeline._enforce_tax_status_in_raw("## PHASE 4: TAX\nTax current. Paid up.\n")

    def test_unverified_raw_with_phrase_passes(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="123")
        pipeline.tax_lookup_status_path().write_text(
            json.dumps({"status": "failed", "reason": "x"}),
            encoding="utf-8",
        )
        pipeline._enforce_tax_status_in_raw("## PHASE 4: TAX\nTAX STATUS NOT VERIFIED — see sidecar.\n")

    def test_success_status_skips_phrase_check(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="123")
        pipeline.tax_lookup_status_path().write_text(
            json.dumps({"status": "success"}),
            encoding="utf-8",
        )
        pipeline._enforce_tax_status_in_raw("## PHASE 4: TAX\nTax current.\n")

    def test_v2_tax_success_status_skips_phrase_check(self, case_dir):
        pipeline = _build_pipeline(case_dir, fetch_tax=True, apn="123")
        pipeline.tax_lookup_status_path().write_text(
            json.dumps({"status": "success", "tax_status": "TAX_SUCCESS"}),
            encoding="utf-8",
        )
        # New status form also acknowledged.
        pipeline._enforce_tax_status_in_raw("## PHASE 4: TAX\nTax current.\n")


class TestTaxValidator:
    """Legacy `_validate_tax_payload` helper is retained for back-compat.
    These tests confirm it still recognizes the legacy `tax_information`
    shape used by older case-dir artifacts."""

    def test_minimal_complete_payload(self, case_dir):
        pipeline = _build_pipeline(case_dir, apn="455-113-24")
        verified, missing = pipeline._validate_tax_payload(
            {
                "tax_information": {
                    "apn": "455-113-24",
                    "tax_year": "2024-2025",
                    "verification_url": "https://x",
                    "assessed_value_total": "$100,000",
                }
            },
            "455-113-24",
        )
        assert not missing
        assert {"apn", "tax_year", "source_url"}.issubset(set(verified))

    def test_lookup_metadata_only_source(self, case_dir):
        pipeline = _build_pipeline(case_dir, apn="1")
        verified, missing = pipeline._validate_tax_payload(
            {
                "lookup_metadata": {"verification_url": "https://x"},
                "tax_information": {
                    "apn": "1",
                    "tax_year": "2024",
                    "annual_tax": "$1",
                },
            },
            "1",
        )
        assert "source_url" in verified
        assert not missing
