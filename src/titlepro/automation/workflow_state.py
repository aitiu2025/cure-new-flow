"""
Workflow state model for the CAPTCHA-aware, resumable recorder/tax pipeline.

This module is the canonical typed surface adapters and orchestrators use to
report workflow outcomes back to the caller. It is deliberately import-light:
no Flask, no Selenium, no IO — so the pipeline, adapter, and test layers can
all depend on it cheaply.

See `docs/captcha_llm_implementation_updated.md` for the full design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# The exhaustive list of workflow statuses adapters may emit. Keep this
# synchronized with `WorkflowStatus` consumers (UI badges, pipeline state
# machine, automated tests).
WorkflowStatus = Literal[
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
]

# Runtime-checkable set mirroring the Literal above. Useful in tests and any
# code that needs to validate a status string at call time.
WORKFLOW_STATUSES = frozenset(
    (
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
    )
)


@dataclass
class WorkflowResult:
    """Typed adapter/orchestrator result.

    Fields:
        status:          One of WORKFLOW_STATUSES.
        county:          Display name of the county (e.g. "Fresno").
        step:            Phase/sub-step name (e.g. "recorder_search_submit").
        message:         Human-readable summary.
        resume_token:    Set when the workflow paused on a human checkpoint.
        artifact_paths:  Filesystem paths of artifacts produced by this step.
        data:            Free-form structured payload (search counts, etc).
    """

    status: str
    county: str
    step: str
    message: str
    resume_token: str | None = None
    artifact_paths: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in WORKFLOW_STATUSES:
            raise ValueError(
                f"Unknown WorkflowStatus '{self.status}'. "
                f"Valid: {sorted(WORKFLOW_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "county": self.county,
            "step": self.step,
            "message": self.message,
            "resume_token": self.resume_token,
            "artifact_paths": list(self.artifact_paths),
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowResult":
        return cls(
            status=data["status"],
            county=data.get("county", ""),
            step=data.get("step", ""),
            message=data.get("message", ""),
            resume_token=data.get("resume_token"),
            artifact_paths=list(data.get("artifact_paths") or []),
            data=dict(data.get("data") or {}),
        )

    @property
    def needs_human(self) -> bool:
        return self.status in {"NEEDS_HUMAN_CAPTCHA", "NEEDS_HUMAN_LOGIN"}

    @property
    def is_success(self) -> bool:
        return self.status in {"SUCCESS", "SEARCH_READY"}

    @property
    def is_terminal_failure(self) -> bool:
        return self.status in {"FATAL_ERROR", "TAX_FAILED", "DOWNLOAD_FAILED", "PARSE_FAILED"}
