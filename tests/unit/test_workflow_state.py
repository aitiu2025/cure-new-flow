"""Unit tests for ``titlepro.automation.workflow_state``."""
from __future__ import annotations

import pytest

from titlepro.automation.workflow_state import (
    WORKFLOW_STATUSES,
    WorkflowResult,
)


class TestWorkflowResult:
    def test_minimum_construction(self):
        result = WorkflowResult(
            status="SUCCESS",
            county="Fresno",
            step="recorder_ready",
            message="ok",
        )
        assert result.is_success
        assert not result.needs_human
        assert result.artifact_paths == []
        assert result.data == {}

    def test_needs_human_predicate(self):
        captcha = WorkflowResult(
            status="NEEDS_HUMAN_CAPTCHA",
            county="Fresno",
            step="recorder_search_submit",
            message="Solve CAPTCHA.",
            resume_token="captcha_fresno_abc",
        )
        login = WorkflowResult(
            status="NEEDS_HUMAN_LOGIN",
            county="Fresno",
            step="portal_login",
            message="Log in.",
            resume_token="login_fresno_def",
        )
        assert captcha.needs_human
        assert login.needs_human
        assert not captcha.is_success

    def test_terminal_failure_predicate(self):
        assert WorkflowResult(
            status="FATAL_ERROR", county="x", step="y", message="z"
        ).is_terminal_failure
        assert WorkflowResult(
            status="DOWNLOAD_FAILED", county="x", step="y", message="z"
        ).is_terminal_failure
        assert not WorkflowResult(
            status="RETRYABLE_ERROR", county="x", step="y", message="z"
        ).is_terminal_failure

    def test_rejects_unknown_status(self):
        with pytest.raises(ValueError, match="Unknown WorkflowStatus"):
            WorkflowResult(status="MAGIC", county="x", step="y", message="z")

    def test_roundtrip_dict(self):
        original = WorkflowResult(
            status="NEEDS_HUMAN_CAPTCHA",
            county="Fresno",
            step="recorder_search_submit",
            message="Solve.",
            resume_token="captcha_fresno_xyz",
            artifact_paths=["/tmp/a.json"],
            data={"unit": "AMAYA JANINE"},
        )
        copy = WorkflowResult.from_dict(original.to_dict())
        assert copy.to_dict() == original.to_dict()

    def test_all_documented_statuses_valid(self):
        # Every literal value in the WorkflowStatus type must be constructable.
        expected = {
            "SUCCESS",
            "NEEDS_HUMAN_CAPTCHA",
            "NEEDS_HUMAN_LOGIN",
            "NO_RESULTS",
            "TAX_SKIPPED",
            "TAX_FAILED",
            "RETRYABLE_ERROR",
            "FATAL_ERROR",
            "CAPTCHA_TIMEOUT",
            "SESSION_EXPIRED",
            "SEARCH_READY",
            "DOWNLOAD_FAILED",
            "PARSE_FAILED",
        }
        assert WORKFLOW_STATUSES == expected
        for status in expected:
            WorkflowResult(status=status, county="x", step="y", message="z")
