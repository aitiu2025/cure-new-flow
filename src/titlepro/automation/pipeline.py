from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import fitz

from titlepro import DOWNLOAD_DIR
from titlepro.download.selenium_downloader import download_document, load_metadata, save_metadata
from titlepro.search.recorder.counties.registry import get_recorder

from .agent_runners import AgentRunnerError, build_agent_runner, sanitize_markdown_output
from .checkpoints import (
    CaptchaCheckpointRequired,
    HumanCheckpointRequired,
    RetryableSubmitError,
    checkpoint_sessions,
    make_session_key,
)
from .renderers import RAW_DOC_TYPE, TITLE_DOC_TYPE, render_markdown_pdf

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional runtime dependency
    Image = None

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional runtime dependency
    pytesseract = None


RAW_REQUIRED_SECTIONS = [
    "## PHASE 1: RECORDER NAME SEARCHES",
    "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION",
    "## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION",
    "## PHASE 4: TAX & PROPERTY LOOKUP",
    "## PHASE 5: RAW EXAM REPORT",
]

TITLE_REQUIRED_SECTIONS = [
    "# Abstractor Notes/Chain",
    "## TITLE EXAMINATION SUMMARY",
    "## CHAIN OF TITLE",
    "## LEGAL DESCRIPTION (EXHIBIT A)",
    "## DEEDS OF TRUST / MORTGAGES",
    "## DOCUMENTS EXAMINED",
]

ONE_REQUIRED_SECTIONS = [
    "# Ownership and Encumbrance Report",
    "## 1.",
    "## 2.",
    "## 3.",
    "## 6.",
    "## 8.",
]


# ---------------------------------------------------------------------------
# Per-phase model defaults (2026-06-14).
# RAW report carries the heavy analytical work (deed-first chain + mortgage
# classification) so it stays on Opus 4.8. Title notes and OnE are
# re-presentations/trims of RAW's facts, so they default to Sonnet for speed.
# Override per case via workflow_config.ai.{raw_model,title_model,one_model}
# or the global ai.model (which wins for all phases when set).
# ---------------------------------------------------------------------------
DEFAULT_RAW_MODEL = "claude-sonnet-4-6"
DEFAULT_TITLE_MODEL = "claude-sonnet-4-6"
DEFAULT_ONE_MODEL = "claude-sonnet-4-6"
# Runaway-cost guard per agent call (USD). The 900s subprocess timeout is the
# hard wall-clock cap; this aborts a call that loops on tool use before it can
# silently grind for an hour. Generous so normal runs never hit it. None/0 off.
DEFAULT_AGENT_MAX_BUDGET_USD = 5.0


# ---------------------------------------------------------------------------
# MANDATORY VERBATIM RULES — appended to RAW + Title user prompts.
# Centralized so both prompt builders stay in sync. See
# docs/audits/legal_description_ordering_audit_2026-05-18.md for the audit
# evidence that motivated these rules.
# ---------------------------------------------------------------------------
MANDATORY_VERBATIM_RULES = (
    "================================================================\n"
    "MANDATORY VERBATIM RULES — LEGAL DESCRIPTIONS, APNs, ORDERING\n"
    "================================================================\n\n"
    "Legal Description Rule:\n"
    "- Copy the legal description WORD-FOR-WORD from the source Deed of "
    "Trust or Grant Deed.\n"
    "- Preserve EXACT casing (VOLUME vs Book), EXACT punctuation "
    "(UNIT NO, 2 not Unit No. 2), and EVERY clause (e.g. \"EXCEPTING "
    "THEREFROM ...\", \"THIS BEING THE SAME PROPERTY CONVEYED ...\").\n"
    "- Do NOT paraphrase. Do NOT normalize. Do NOT summarize. Do NOT "
    "translate book-references.\n"
    "- If multiple deeds reference the same parcel, use the legal "
    "description from the most recent vesting deed (Grant Deed, not "
    "Deed of Trust if both exist).\n\n"
    "Canonical Ordering Rule (applies to every property identification block):\n"
    "When you write Property Identification details, ALWAYS use this exact order:\n"
    "  1. Deed (most recent vesting instrument)\n"
    "  2. Addendum A (if any explicit \"Addendum A\" or supplemental "
    "conveyance attachment exists in the source)\n"
    "  3. Legal Description (verbatim per Legal Description Rule above)\n"
    "  4. APN / PIN / Parcel Number (preserve check digits when present — "
    "e.g. 502-153-010-9, not 502-153-010)\n\n"
    "APN Preservation Rule:\n"
    "- APNs/PINs/Parcel Numbers must be copied verbatim from the source "
    "instrument.\n"
    "- Specifically: do NOT drop trailing check digits (the \"-9\" in "
    "502-153-010-9).\n"
    "- Do NOT normalize hyphenation (the source's exact hyphen positions "
    "are authoritative).\n"
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def repo_prompt_dir() -> Path:
    return project_root() / "docs"


def downloads_prompt_dir() -> Path:
    return Path.home() / "Downloads" / "0414_CA_Exams"


class WorkflowError(RuntimeError):
    """Raised when a strict workflow phase cannot safely continue."""


# ---------------------------------------------------------------------------
# Tax-prompt sanitization helpers
# ---------------------------------------------------------------------------

# Pattern catches:
#   - "County 'foo' not supported for tax lookup. Supported: ['orange', ...]"
#   - "Supported: ['orange', 'amador']"
#   - Generic "not supported" leakage from older runs
_LEGACY_TAX_ERROR_PATTERNS = (
    re.compile(r"County '[^']*' not supported[^.]*\.\s*Supported:\s*\[[^\]]*\]\.?", re.IGNORECASE),
    re.compile(r"\bSupported:\s*\[[^\]]*\]\.?", re.IGNORECASE),
    re.compile(r"\bnot supported\b[^.\n]*", re.IGNORECASE),
)

# Fields of a tax JSON that the RAW prompt is allowed to see. Anything else
# (legacy `error`, raw `data_source`, scraper-internal `notes`) is dropped.
_CANONICAL_TAX_FIELDS = (
    "apn",
    "tax_year",
    "property_address",
    "tra",
    "assessed_value",
    "installments",
    "annual_total",
    "delinquent",
    "special_assessments",
    "source_url",
    "verified_fields",
    "missing_fields",
    "status",
    "captured_at",
    # Dual-year tax echo (v1.6 — 2026-06-03). Optional fields populated
    # by adapters that retrieve the prior tax year from the Tax Collector
    # portal (Grant Street etc.). When None, OnE renders single-column
    # legacy layout; when populated, OnE renders 3-column Current/Prior.
    "prior_year_tax_year",
    "prior_year_annual_amount",
    "prior_year_just_value",
    "prior_year_net_taxable",
    "prior_year_installment_status",
    "prior_year_paid_date",
    "prior_year_source_url",
    "prior_year_captured_at",
)


def _scrub_legacy_text(value: Any) -> Any:
    """Strip legacy 'Supported: [...]' / 'not supported' fragments from a string.

    Non-string values are returned unchanged. Empty / whitespace-only results
    are normalized to empty string.
    """
    if not isinstance(value, str):
        return value
    out = value
    for pat in _LEGACY_TAX_ERROR_PATTERNS:
        out = pat.sub("", out)
    # Collapse the resulting whitespace cleanly
    out = re.sub(r"\s{2,}", " ", out).strip(" .;,")
    return out


def _sanitize_legacy_tax_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `payload` with legacy tax error text scrubbed
    from string fields that the LLM will see (`notes`, `error`, `reason`)."""
    if not isinstance(payload, dict):
        return payload
    cleaned = dict(payload)
    for key in ("notes", "error", "reason"):
        if key in cleaned:
            cleaned[key] = _scrub_legacy_text(cleaned[key])
    return cleaned


def _canonical_tax_payload_for_prompt(tax_data: Any) -> dict[str, Any]:
    """Project a tax_*.json payload down to canonical fields only.

    Excludes legacy keys like `error`, `data_source`, and raw `notes` from
    any prior failed run so they cannot leak into the RAW prompt.
    Supports both flat v2 schema (TaxLookupResult.to_json_dict) and the
    legacy `{lookup_metadata, tax_information}` shape.
    """
    if not isinstance(tax_data, dict):
        return {}

    # Legacy shape: lift tax_information up but preserve apn/timestamps.
    if "tax_information" in tax_data or "lookup_metadata" in tax_data:
        info = tax_data.get("tax_information") or {}
        meta = tax_data.get("lookup_metadata") or {}
        merged = {
            "apn": info.get("apn") or meta.get("apn_searched", ""),
            "tax_year": info.get("tax_year", ""),
            "property_address": info.get("property_address", ""),
            "annual_total": info.get("annual_tax_estimated") or info.get("annual_tax", ""),
            "assessed_value": {
                "land": info.get("assessed_value_land", ""),
                "improvements": info.get("assessed_value_improvements", ""),
                "net_taxable": info.get("assessed_value_total", ""),
            },
            "installments": [
                {
                    "label": "first",
                    "amount": info.get("first_installment_amount", ""),
                    "status": info.get("first_installment_status", ""),
                    "due_date": info.get("first_installment_due", ""),
                },
                {
                    "label": "second",
                    "amount": info.get("second_installment_amount", ""),
                    "status": info.get("second_installment_status", ""),
                    "due_date": info.get("second_installment_due", ""),
                },
            ],
            "delinquent": info.get("delinquent", False),
            "source_url": (
                info.get("verification_url")
                or meta.get("verification_url", "")
            ),
            "status": "TAX_SUCCESS" if meta.get("success") else "TAX_PARTIAL",
            "captured_at": meta.get("lookup_timestamp", ""),
        }
        # Dual-year echo: legacy payloads may carry prior_year_* either inside
        # tax_information or at the top level — lift whichever is populated.
        for key in _CANONICAL_TAX_FIELDS:
            if key.startswith("prior_year_"):
                value = info.get(key, tax_data.get(key))
                if value is not None:
                    merged[key] = value
        return merged

    # v2 / flat shape: copy only canonical keys.
    out: dict[str, Any] = {}
    for key in _CANONICAL_TAX_FIELDS:
        if key in tax_data:
            out[key] = tax_data[key]
    return out


@dataclass
class SearchRequest:
    name: str
    party_types: list[str] = field(default_factory=lambda: ["Grantor", "Grantee", "Grantor/Grantee"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchRequest":
        return cls(
            name=data["name"],
            party_types=list(data.get("party_types") or ["Grantor", "Grantee", "Grantor/Grantee"]),
        )


@dataclass
class AIConfig:
    provider: str = "claude"
    # Per-phase provider overrides. None -> fall back to global `provider`.
    # Use this to mix engines per phase (e.g. claude for big RAW prompt,
    # groq for smaller Title/OnE prompts).
    raw_provider: Optional[str] = None
    title_provider: Optional[str] = None
    one_provider: Optional[str] = None
    # Global model override. When set it wins for EVERY phase (back-compat for
    # callers that pinned a single model). When None, each phase falls back to
    # its per-phase field below, then to the module DEFAULT_*_MODEL constant.
    model: Optional[str] = None
    # Per-phase model overrides. None -> use `model`, else the phase default.
    raw_model: Optional[str] = None
    title_model: Optional[str] = None
    one_model: Optional[str] = None
    timeout_seconds: int = 900
    # Per-call runaway-cost guard (USD). None/0 disables.
    max_budget_usd: Optional[float] = DEFAULT_AGENT_MAX_BUDGET_USD
    raw_prompt_path: Optional[str] = None
    title_prompt_path: Optional[str] = None
    one_prompt_path: Optional[str] = None
    design_system_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIConfig":
        return cls(
            provider=data.get("provider", "claude"),
            raw_provider=data.get("raw_provider"),
            title_provider=data.get("title_provider"),
            one_provider=data.get("one_provider"),
            model=data.get("model"),
            raw_model=data.get("raw_model"),
            title_model=data.get("title_model"),
            one_model=data.get("one_model"),
            timeout_seconds=int(data.get("timeout_seconds", 900)),
            max_budget_usd=(
                data["max_budget_usd"]
                if "max_budget_usd" in data
                else DEFAULT_AGENT_MAX_BUDGET_USD
            ),
            raw_prompt_path=data.get("raw_prompt_path"),
            title_prompt_path=data.get("title_prompt_path"),
            one_prompt_path=data.get("one_prompt_path"),
            design_system_path=data.get("design_system_path"),
        )


@dataclass
class WorkflowConfig:
    owner_name: str
    county: str
    search_requests: list[SearchRequest]
    property_address: str = ""
    apn: Optional[str] = None
    subject_id: str = ""
    state: str = "CA"
    start_date: str = "01/01/2000"
    end_date: str = field(default_factory=lambda: datetime.now().strftime("%m/%d/%Y"))
    output_folder_name: Optional[str] = None
    resume: bool = True
    strict_downloads: bool = True
    download_headless: bool = False
    download_retries: int = 2
    download_retry_delay_seconds: int = 2
    download_base_url: Optional[str] = None
    download_portal_county: Optional[str] = None
    # Download routing flag. When True → use TitlePro247 (legacy CA path).
    # When False → use the recorder adapter's `download_pdf()` method (FL counties).
    # `None` → infer from state ("CA" → True, anything else → False).
    use_titlepro: Optional[bool] = None
    use_ocr_fallback: bool = True
    min_page_text_chars: int = 50
    max_document_chars: int = 6000
    generate_title_notes: bool = True
    generate_raw_pdf: bool = True
    generate_title_pdf: bool = True
    generate_json_xml_reports: bool = True
    fetch_tax: bool = True
    # When True (default) the pipeline runs a deterministic Legal Description
    # + APN extractor after extract_text and writes legal_descriptions.json.
    # See docs/audits/legal_description_ordering_audit_2026-05-18.md.
    extract_legal_descriptions: bool = True
    # When True (default) the pipeline runs a similarity validator after
    # RAW + Title generation to ensure the verbatim Exhibit A from the
    # source survived AI generation. Hard-fail on similarity < 0.95.
    validate_legal_descriptions: bool = True
    # When True (default) the pipeline deterministically splices the canonical
    # verbatim legal description (from legal_descriptions.json) back into the
    # generated RAW/Title Legal Description section BEFORE the similarity
    # validator runs. This self-heals LLM paraphrase instead of hard-failing
    # and forcing a full regeneration (#3, 2026-06-14).
    splice_legal_descriptions: bool = True
    # When True (default) the pipeline runs the Phase-1 verification suite
    # after text extraction and writes phase1_verifications.json: subject-
    # address verifier (Tony #4), doc-type classifier, released-mortgage
    # linker + not_needed audit (Tony #5/#6), vesting-chain walker,
    # NOC-termination bundles, and Title-Affidavit pairings (OnE v1.6).
    run_phase1_verifications: bool = True
    # When True, missing APN skips tax cleanly instead of failing the phase.
    # Default False enforces strict semantics per the CAPTCHA proposal.
    allow_tax_skip_on_missing_apn: bool = False
    # When True, counties with no tax-lookup recipe hard-fail the phase.
    # Default False (lenient) per Codex finding 3: TAX_NO_RUNNER is
    # non-blocking until every CA county we touch has a recipe.
    strict_tax_no_runner: bool = False
    # Manual-CAPTCHA defaults; counties may override via per-county config.
    manual_captcha_timeout_seconds: int = 900
    allow_captcha_timeout_renewal: bool = True
    allow_automated_captcha_solver: bool = False
    raw_required_sections: list[str] = field(default_factory=lambda: list(RAW_REQUIRED_SECTIONS))
    title_required_sections: list[str] = field(default_factory=lambda: list(TITLE_REQUIRED_SECTIONS))
    one_required_sections: list[str] = field(default_factory=lambda: list(ONE_REQUIRED_SECTIONS))
    generate_one_report: bool = True
    ai: AIConfig = field(default_factory=AIConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowConfig":
        requests = data.get("search_requests") or []
        if not requests and data.get("search_names"):
            requests = [{"name": name} for name in data["search_names"]]
        if not requests:
            requests = [{"name": data["owner_name"]}]

        return cls(
            owner_name=data["owner_name"],
            county=data["county"],
            search_requests=[SearchRequest.from_dict(item) for item in requests],
            property_address=data.get("property_address", ""),
            apn=data.get("apn") or data.get("parcel_number"),
            subject_id=data.get("subject_id", ""),
            state=data.get("state", "CA"),
            start_date=data.get("start_date", "01/01/2000"),
            end_date=data.get("end_date", datetime.now().strftime("%m/%d/%Y")),
            output_folder_name=data.get("output_folder_name"),
            resume=bool(data.get("resume", True)),
            strict_downloads=bool(data.get("strict_downloads", True)),
            download_headless=bool(data.get("download_headless", False)),
            download_retries=int(data.get("download_retries", 2)),
            download_retry_delay_seconds=int(data.get("download_retry_delay_seconds", 2)),
            download_base_url=data.get("download_base_url"),
            download_portal_county=data.get("download_portal_county", data.get("county")),
            use_titlepro=data.get("use_titlepro"),  # None → infer from state at use-site
            use_ocr_fallback=bool(data.get("use_ocr_fallback", True)),
            min_page_text_chars=int(data.get("min_page_text_chars", 50)),
            max_document_chars=int(data.get("max_document_chars", 6000)),
            generate_title_notes=bool(data.get("generate_title_notes", True)),
            generate_raw_pdf=bool(data.get("generate_raw_pdf", True)),
            generate_title_pdf=bool(data.get("generate_title_pdf", True)),
            generate_json_xml_reports=bool(data.get("generate_json_xml_reports", True)),
            fetch_tax=bool(data.get("fetch_tax", True)),
            extract_legal_descriptions=bool(data.get("extract_legal_descriptions", True)),
            validate_legal_descriptions=bool(data.get("validate_legal_descriptions", True)),
            splice_legal_descriptions=bool(data.get("splice_legal_descriptions", True)),
            run_phase1_verifications=bool(data.get("run_phase1_verifications", True)),
            allow_tax_skip_on_missing_apn=bool(data.get("allow_tax_skip_on_missing_apn", False)),
            strict_tax_no_runner=bool(data.get("strict_tax_no_runner", False)),
            manual_captcha_timeout_seconds=int(data.get("manual_captcha_timeout_seconds", 900)),
            allow_captcha_timeout_renewal=bool(data.get("allow_captcha_timeout_renewal", True)),
            allow_automated_captcha_solver=bool(data.get("allow_automated_captcha_solver", False)),
            raw_required_sections=list(data.get("raw_required_sections") or RAW_REQUIRED_SECTIONS),
            title_required_sections=list(data.get("title_required_sections") or TITLE_REQUIRED_SECTIONS),
            one_required_sections=list(data.get("one_required_sections") or ONE_REQUIRED_SECTIONS),
            generate_one_report=bool(data.get("generate_one_report", True)),
            ai=AIConfig.from_dict(data.get("ai", {})),
        )

    @classmethod
    def from_file(cls, path: Path) -> "WorkflowConfig":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @property
    def case_path(self) -> str:
        """Relative case directory under DOWNLOAD_DIR. May contain '/' for grouping
        (e.g. '0513/Fresno_AMAYA_Janine'). Each segment is sanitized independently."""
        base = (self.output_folder_name or self.owner_name).replace(",", "")
        segments = [
            re.sub(r"[^A-Za-z0-9_]+", "_", seg).strip("_")
            for seg in base.replace("\\", "/").split("/")
        ]
        return "/".join(s for s in segments if s)

    @property
    def safe_owner(self) -> str:
        """Flat identifier (no slashes) used in filenames. Final segment of case_path."""
        cp = self.case_path
        return cp.rsplit("/", 1)[-1] if cp else ""


class WorkflowStateStore:
    def __init__(self, path: Path, case_summary: dict[str, Any]):
        self.path = path
        self.case_summary = case_summary

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "workflow_version": 1,
                "case": self.case_summary,
                "phases": {},
                "updated_at": datetime.now().isoformat(),
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = datetime.now().isoformat()
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def mark_started(self, phase: str, details: Optional[dict[str, Any]] = None) -> None:
        state = self.load()
        state["phases"].setdefault(phase, {})
        state["phases"][phase].update(
            {"status": "running", "started_at": datetime.now().isoformat(), "details": details or {}}
        )
        self.save(state)

    def mark_completed(self, phase: str, details: Optional[dict[str, Any]] = None) -> None:
        state = self.load()
        entry = state["phases"].setdefault(phase, {})
        entry.update(
            {
                "status": "completed",
                "completed_at": datetime.now().isoformat(),
                "details": details or entry.get("details", {}),
            }
        )
        self.save(state)

    def mark_failed(self, phase: str, error: str, details: Optional[dict[str, Any]] = None) -> None:
        state = self.load()
        entry = state["phases"].setdefault(phase, {})
        entry.update(
            {
                "status": "failed",
                "failed_at": datetime.now().isoformat(),
                "error": error,
                "details": details or entry.get("details", {}),
            }
        )
        self.save(state)

    def mark_checkpoint(self, phase: str, checkpoint: dict[str, Any]) -> None:
        state = self.load()
        entry = state["phases"].setdefault(phase, {})
        entry.update(
            {
                "status": "needs_human",
                "checkpoint_at": datetime.now().isoformat(),
                "checkpoint": checkpoint,
                "details": {"checkpoint": checkpoint},
            }
        )
        self.save(state)


class RecorderAutomationPipeline:
    phase_order = [
        "search",
        "download",
        "validate_downloads",
        "extract_text",
        "extract_legal_descriptions",
        "phase1_verifications",
        "tax_lookup",
        "generate_raw_report",
        "generate_title_notes",
        "generate_one_report",
        "render_pdfs",
        "serialize_reports",
    ]

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.repo_root = project_root()
        self.case_dir = DOWNLOAD_DIR / self.config.case_path
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir = self.case_dir / "_workflow_prompts"
        self.prompts_dir.mkdir(exist_ok=True)
        self.state_store = WorkflowStateStore(
            self.case_dir / "workflow_status.json",
            {
                "owner_name": self.config.owner_name,
                "safe_owner": self.config.safe_owner,
                "county": self.config.county,
                "subject_id": self.config.subject_id,
            },
        )

    def config_path(self) -> Path:
        return self.case_dir / "workflow_config.json"

    def phase_enabled(self, phase: str) -> bool:
        if phase == "generate_title_notes":
            return self.config.generate_title_notes
        if phase == "generate_one_report":
            return self.config.generate_one_report
        if phase == "render_pdfs":
            return self.config.generate_raw_pdf or self.config.generate_title_pdf
        if phase == "tax_lookup":
            return self.config.fetch_tax
        if phase == "extract_legal_descriptions":
            return self.config.extract_legal_descriptions
        if phase == "phase1_verifications":
            return self.config.run_phase1_verifications
        if phase == "serialize_reports":
            return self.config.generate_json_xml_reports
        return phase in self.phase_order

    def enabled_phases(self) -> list[str]:
        return [phase for phase in self.phase_order if self.phase_enabled(phase)]

    def run_phase(self, phase: str, force: bool = False) -> dict[str, Any]:
        if phase not in self.phase_order:
            raise WorkflowError(f"Unknown phase '{phase}'. Valid phases: {', '.join(self.phase_order)}")
        if not self.phase_enabled(phase):
            raise WorkflowError(f"Phase '{phase}' is disabled by the current workflow configuration.")

        if self.config.resume and not force and self._can_skip_phase(phase):
            state = self.state_store.load()
            state["phases"].setdefault(phase, {})
            state["phases"][phase].setdefault("status", "completed")
            self.state_store.save(state)
            return state

        try:
            self.state_store.mark_started(phase)
            details = getattr(self, phase)()
            self.state_store.mark_completed(phase, details)
        except HumanCheckpointRequired as checkpoint:
            self._mark_human_checkpoint(phase, checkpoint)
            raise
        except RetryableSubmitError as retry:
            # Surface as needs_human so the UI can show "fix and resume"
            # rather than a hard failure. Wrap in a HumanCheckpointRequired
            # so existing server handlers treat it identically.
            converted = self._wrap_retryable_as_checkpoint(retry, phase)
            self._mark_human_checkpoint(phase, converted)
            raise converted
        except Exception as exc:
            self.state_store.mark_failed(phase, str(exc))
            raise
        return self.state_store.load()

    def _wrap_retryable_as_checkpoint(
        self, error: RetryableSubmitError, phase: str
    ) -> HumanCheckpointRequired:
        session = checkpoint_sessions.create(
            checkpoint_type="retry",
            county=error.county or self.config.county,
            step=error.step or phase,
            message=str(error),
            resource=None,
            details={
                "phase": phase,
                "kind": "retryable_submit_error",
                "safe_owner": self.config.safe_owner,
            },
            timeout_seconds=self.config.manual_captcha_timeout_seconds,
            renewable=self.config.allow_captcha_timeout_renewal,
        )
        return HumanCheckpointRequired(
            resume_token=session.resume_token,
            county=session.county,
            step=session.step,
            message=session.message,
            details=session.public_payload()["details"],
        )

    def run(self, stop_after: Optional[str] = None) -> dict[str, Any]:
        if stop_after and stop_after not in self.phase_order:
            raise WorkflowError(
                f"Unknown stop_after phase '{stop_after}'. Valid phases: {', '.join(self.phase_order)}"
            )

        for phase in self.phase_order:
            if not self.phase_enabled(phase):
                continue
            if self.config.resume and self._can_skip_phase(phase):
                if stop_after == phase:
                    break
                continue
            try:
                self.state_store.mark_started(phase)
                details = getattr(self, phase)()
                self.state_store.mark_completed(phase, details)
            except HumanCheckpointRequired as checkpoint:
                self._mark_human_checkpoint(phase, checkpoint)
                raise
            except Exception as exc:
                self.state_store.mark_failed(phase, str(exc))
                raise
            if stop_after == phase:
                break

        return self.state_store.load()

    def _download_phase_skip_ok(self) -> bool:
        """Return True when the download phase can be skipped on resume.

        Skippable when:
        1. All documents downloaded successfully (validation passes), OR
        2. strict_downloads=False AND the download manifest already exists
           (meaning we already attempted downloads — failures are tolerated).
        """
        if self._download_validation_summary(raise_on_failure=False)["success"]:
            return True
        if not self.config.strict_downloads and self.download_manifest_path().exists():
            return True
        return False

    def _can_skip_phase(self, phase: str) -> bool:
        validators = {
            "search": lambda: self.documents_found_path().exists() and bool(self._load_documents_found()),
            "download": lambda: self._download_phase_skip_ok(),
            "validate_downloads": lambda: self._download_phase_skip_ok(),
            "extract_text": lambda: self._extraction_summary(raise_on_failure=False)["success"],
            "extract_legal_descriptions": lambda: self._legal_descriptions_skip_ok(),
            "phase1_verifications": lambda: self._phase1_verifications_skip_ok(),
            "tax_lookup": lambda: self._tax_lookup_skip_ok(),
            "generate_raw_report": lambda: self._validate_markdown_file(
                self.raw_markdown_path(), self.config.raw_required_sections, raise_on_failure=False
            )["success"],
            "generate_title_notes": lambda: self._validate_markdown_file(
                self.title_markdown_path(), self.config.title_required_sections, raise_on_failure=False
            )["success"],
            "generate_one_report": lambda: self._validate_markdown_file(
                self.one_markdown_path(), self.config.one_required_sections, raise_on_failure=False
            )["success"],
            "render_pdfs": lambda: self._render_summary(raise_on_failure=False)["success"],
            "serialize_reports": lambda: self._serialize_summary(raise_on_failure=False)["success"],
        }
        validator = validators.get(phase)
        return bool(validator and validator())

    def _mark_human_checkpoint(self, phase: str, checkpoint: HumanCheckpointRequired) -> None:
        details = checkpoint.to_dict()
        details.setdefault("details", {})
        details["details"].update(
            {
                "phase": phase,
                "safe_owner": self.config.safe_owner,
                "case_dir": str(self.case_dir),
                "workflow_status_path": str(self.state_store.path),
            }
        )
        checkpoint.details.update(details["details"])
        checkpoint_sessions.update_details(checkpoint.resume_token, details["details"])
        self.state_store.mark_checkpoint(phase, details)

    def documents_found_path(self) -> Path:
        return self.case_dir / "documents_found.json"

    def search_results_path(self) -> Path:
        return self.case_dir / "search_results.json"

    def download_manifest_path(self) -> Path:
        return self.case_dir / "download_manifest.json"

    def download_validation_path(self) -> Path:
        return self.case_dir / "download_validation.json"

    def extraction_summary_path(self) -> Path:
        return self.case_dir / "extracted_documents.json"

    def tax_data_path(self) -> Path:
        return self.case_dir / f"tax_{self.config.safe_owner}.json"

    def legal_descriptions_path(self) -> Path:
        """Sidecar emitted by the `extract_legal_descriptions` phase.

        Keyed by `document_number`. See `extract_legal_descriptions()` for
        the exact shape.
        """
        return self.case_dir / "legal_descriptions.json"

    def _legal_descriptions_skip_ok(self) -> bool:
        """Skippable when the sidecar exists, parses, and is non-empty."""
        path = self.legal_descriptions_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return isinstance(data, dict) and bool(data)

    def tax_lookup_status_path(self) -> Path:
        return self.case_dir / "tax_lookup_status.json"

    def _tax_lookup_skip_ok(self) -> bool:
        """Phase is skippable only when the status sidecar reports success
        (or the older success-shaped tax artifact exists and a strict status
        sidecar has not been written yet — back-compat for existing cases).

        Recognized success forms:
          - legacy `status="success"`
          - new v2 `tax_status="TAX_SUCCESS"`
        Lenient pass-throughs (TAX_PARTIAL, TAX_NO_RUNNER) are also considered
        skippable so re-runs don't fight the phase gate; downstream guards
        in `generate_raw_report` enforce the "not verified" phrase when
        appropriate.
        """
        # Prefer the strict status sidecar when it exists.
        status_path = self.tax_lookup_status_path()
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                return False
            if status.get("status") == "success":
                return True
            if status.get("tax_status") == "TAX_SUCCESS":
                return True
            if status.get("status") in {"TAX_PARTIAL", "TAX_NO_RUNNER"}:
                return True
            # When strict_downloads=False (lenient run), also skip on TAX_FAILED /
            # TAX_NO_RESULTS — re-running cannot recover a CF-blocked or missing-county
            # tax endpoint, and the RAW/Title generation handles the failure inline.
            if not self.config.strict_downloads and status.get("status") in {
                "failed", "TAX_FAILED", "TAX_NO_RESULTS", "skipped", "disabled",
            }:
                return True
            return False

        # Backward compatibility: cases that ran before the strict sidecar
        # existed may have only the tax data file. Treat it as completed
        # only if it parses and does not carry explicit failure flags.
        path = self.tax_data_path()
        try:
            if not path.exists() or path.stat().st_size <= 0:
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("success") is False:
                return False
            if isinstance(data, dict) and data.get("status") in {"skipped", "failed"}:
                return False
            return True
        except (OSError, json.JSONDecodeError):
            return False

    def raw_markdown_path(self) -> Path:
        return self.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.md"

    def raw_pdf_path(self) -> Path:
        return self.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.pdf"

    def title_markdown_path(self) -> Path:
        return self.case_dir / "Title_Examination_Notes.md"

    def title_pdf_path(self) -> Path:
        return self.case_dir / "Title_Examination_Notes.pdf"

    def one_markdown_path(self) -> Path:
        safe = self.config.owner_name.replace(" ", "_").upper()
        return self.case_dir / f"OnE_Report_{safe}.md"

    def one_docx_path(self) -> Path:
        return self.one_markdown_path().with_suffix(".docx")

    def _versioned_path(self, stem: str, suffix: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.case_dir / f"{stem}_{self.config.safe_owner}_{stamp}{suffix}"

    def _load_documents_found(self) -> list[dict[str, Any]]:
        if not self.documents_found_path().exists():
            return []
        return json.loads(self.documents_found_path().read_text(encoding="utf-8"))

    def search(self) -> dict[str, Any]:
        recorder = get_recorder(self.config.county, start_date=self.config.start_date, end_date=self.config.end_date)
        if hasattr(recorder, "set_debug_dir"):
            recorder.set_debug_dir(self.case_dir)

        with recorder:
            return self._run_search_with_recorder(recorder, navigate=True)

    def resume_checkpoint(self, resume_token: str) -> dict[str, Any]:
        session = checkpoint_sessions.require(resume_token)
        if session.checkpoint_type != "captcha":
            raise WorkflowError(f"Unsupported checkpoint type: {session.checkpoint_type}")

        phase = session.details.get("phase") or "search"
        if phase != "search":
            raise WorkflowError(f"Checkpoint resume is only implemented for search, not '{phase}'.")

        recorder = session.resource
        if not recorder:
            raise WorkflowError("Checkpoint session has no live recorder browser to resume.")

        try:
            self.state_store.mark_started("search", {"resumed_from_checkpoint": resume_token})
            summary = self._run_search_with_recorder(recorder, navigate=False)
            self.state_store.mark_completed("search", summary)
            checkpoint_sessions.complete(resume_token, close_resource=True)
            return self.state_store.load()
        except HumanCheckpointRequired as checkpoint:
            checkpoint_sessions.fail(resume_token, close_resource=False)
            self._mark_human_checkpoint("search", checkpoint)
            raise
        except Exception as exc:
            checkpoint_sessions.fail(resume_token, close_resource=True)
            self.state_store.mark_failed("search", str(exc))
            raise

    def _run_search_with_recorder(self, recorder, *, navigate: bool) -> dict[str, Any]:
        documents_by_number: dict[str, dict[str, Any]] = {}
        search_runs: list[dict[str, Any]] = []

        # Per-county capability hints (e.g. Fresno's DOCSEARCH377S1 is a single
        # combined-name page with no Grantor/Grantee filter — one query covers
        # all roles, so we collapse the party_type loop to one run per name).
        try:
            from titlepro.search.recorder.counties.registry import load_county_config
            county_cfg = load_county_config(self.config.county)
        except Exception:
            county_cfg = {}
        combined_name_only = bool(county_cfg.get("combined_name_search"))

        if navigate:
            recorder.navigate_to_search()
        for search_request in self.config.search_requests:
            if combined_name_only:
                # One query per name. Use the first configured party_type as
                # the API param (the adapter will treat it as combined),
                # then tag the resulting docs with all configured party_types.
                primary_party = (search_request.party_types or ["Grantor/Grantee"])[0]
                tag_party_types = list(search_request.party_types or [primary_party])
                iter_party_types = [primary_party]
            else:
                tag_party_types = None  # use per-iteration party_type
                iter_party_types = search_request.party_types

            for party_type in iter_party_types:
                result = recorder.search_name(search_request.name, party_type)
                search_runs.append(result.to_dict())
                for doc in result.documents:
                    existing = documents_by_number.setdefault(doc.document_number, doc.to_dict())
                    existing.setdefault("found_via_names", [])
                    existing.setdefault("found_via_party_types", [])
                    existing.setdefault("search_hits", [])
                    if search_request.name not in existing["found_via_names"]:
                        existing["found_via_names"].append(search_request.name)

                    if tag_party_types is not None:
                        # Combined-name county: stamp the doc with every
                        # configured party_type since one query covers all.
                        for pt in tag_party_types:
                            if pt not in existing["found_via_party_types"]:
                                existing["found_via_party_types"].append(pt)
                            existing["search_hits"].append({
                                "name": search_request.name,
                                "party_type": pt,
                                "via": "combined_name_search"
                            })
                    else:
                        if party_type not in existing["found_via_party_types"]:
                            existing["found_via_party_types"].append(party_type)
                        existing["search_hits"].append({"name": search_request.name, "party_type": party_type})
                recorder.return_to_search()

        ordered_documents = sorted(
            documents_by_number.values(),
            key=lambda item: (
                self._sortable_recording_date(item.get("recording_date")),
                item.get("document_number", ""),
            ),
            reverse=True,
        )
        self.documents_found_path().write_text(json.dumps(ordered_documents, indent=2), encoding="utf-8")

        # Persist per-adapter internal IDs (Tyler doc_id, AcclaimWeb tokens, etc.)
        # so the download phase — which creates a fresh adapter instance — can
        # resolve direct-download URLs without re-running the search.
        # Also persist the Clericus q2 hash cache (_q2_by_instrument → clericus_q2_cache.json)
        # AND session state (cookies + q1) so the download phase can restore the
        # same JSESSIONID that the q2 hashes are tied to.
        for cache_attr, sidecar_name in (
            ("_doc_id_by_number", "recorder_internal_ids.json"),
            ("_q2_by_instrument", "clericus_q2_cache.json"),
            ("_session_cookies", "clericus_session_cookies.json"),
            ("_session_state", "clericus_session_state.json"),
        ):
            cache = getattr(recorder, cache_attr, None)
            if cache:
                (self.case_dir / sidecar_name).write_text(
                    json.dumps(cache, indent=2), encoding="utf-8"
                )
        search_payload = {
            "search_parameters": {
                "owner_name": self.config.owner_name,
                "county": self.config.county,
                "start_date": self.config.start_date,
                "end_date": self.config.end_date,
                "search_requests": [asdict(item) for item in self.config.search_requests],
            },
            "summary": {
                "total_searches": len(search_runs),
                "total_unique_documents": len(ordered_documents),
            },
            "runs": search_runs,
        }
        self.search_results_path().write_text(json.dumps(search_payload, indent=2), encoding="utf-8")

        # State-contamination diagnostic (Tony Roveda 2026-05-22 Broward Test Review).
        # The [N, 0, 0, 0, 0, 0] signature — first search returns N, every subsequent
        # search returns zero — is mathematically near-impossible for legitimate
        # independent searches and historically indicated an adapter form-reset bug
        # (Kendo-vs-Telerik selector miss in acclaimweb_adapter, return_to_search
        # not actually navigating back). Combined-name counties collapse the
        # party-type loop to one run per name, so the assertion only fires when the
        # pipeline actually issued 3+ distinct searches.
        counts = [r.get("result_count", 0) for r in search_runs]
        if (
            len(counts) >= 3
            and counts[0] > 0
            and all(c == 0 for c in counts[1:])
        ):
            raise WorkflowError(
                f"StateContaminationDetected: search counts {counts} match the "
                f"[N, 0, 0, 0, 0, 0] signature. The first search succeeded but every "
                f"subsequent search returned zero -- almost certainly an adapter "
                f"form-reset bug. See state_contamination_assertion memory + "
                f"docs/FL/source/broward_state_bug_repro/ before re-running."
            )

        if not ordered_documents:
            _last_failure = getattr(recorder, "last_failure", None)
            if _last_failure == "needs_cookie_mint":
                raise WorkflowError(
                    "Recorder search completed but found zero documents. "
                    "NEEDS_COOKIE_MINT: this county requires warmed Akamai cookies. "
                    "Run tools/diagnostics/mint_lee_cookies.py from your local workstation "
                    "(residential IP) once, then retry this job."
                )
            raise WorkflowError("Recorder search completed but found zero documents.")
        return search_payload["summary"]

    def _should_use_titlepro(self) -> bool:
        """Resolve `use_titlepro` flag. Explicit config wins; else infer from state.
        CA → TitlePro247 (legacy); anything else (FL etc.) → adapter direct download.
        """
        if self.config.use_titlepro is not None:
            return bool(self.config.use_titlepro)
        return (self.config.state or "CA").upper() == "CA"

    def _build_download_adapter(self):
        """Build + warm a recorder adapter for the download phase. Called once
        per `download()` invocation — the warmed adapter is reused for every
        document, which is critical for cost (2Captcha solves once not N times)
        AND correctness (one stable session preserves disclaimer cookies that
        the PDF GETs depend on).
        """
        from titlepro.search.recorder.counties.registry import get_recorder
        adapter = get_recorder(self.config.county, self.config.start_date, self.config.end_date)
        if not hasattr(adapter, "download_pdf"):
            raise WorkflowError(
                f"Adapter for county {self.config.county!r} does not implement "
                f"download_pdf(). Either implement it (recommended for FL counties) "
                f"or set workflow_config.use_titlepro=true to fall back to TitlePro247."
            )
        sidecar = self.case_dir / "recorder_internal_ids.json"
        if sidecar.exists():
            try:
                ids = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception as exc:
                raise WorkflowError(
                    f"recorder_internal_ids.json exists but is unreadable ({exc}). "
                    f"Re-run the search phase to regenerate it."
                ) from exc
            if not isinstance(ids, dict) or not ids:
                raise WorkflowError(
                    "recorder_internal_ids.json is empty or not a dict. "
                    "Re-run the search phase."
                )
            adapter._doc_id_by_number = ids
        # Reload Clericus cross-phase session state if present (populated during
        # search phase). The q2 hashes are JSESSIONID-bound — the download phase
        # must use the same session cookies + q1 token, not a fresh warm_session.
        q2_sidecar = self.case_dir / "clericus_q2_cache.json"
        if q2_sidecar.exists() and hasattr(adapter, "_q2_by_instrument"):
            try:
                q2_cache = json.loads(q2_sidecar.read_text(encoding="utf-8"))
                if isinstance(q2_cache, dict):
                    adapter._q2_by_instrument.update(q2_cache)
            except Exception:
                pass  # non-fatal — download will fall back to error message
        # Restore the session cookies (JSESSIONID) from the search phase so the
        # download adapter uses the same server-side session as the q2 hashes.
        cookies_sidecar = self.case_dir / "clericus_session_cookies.json"
        state_sidecar = self.case_dir / "clericus_session_state.json"
        if cookies_sidecar.exists() and hasattr(adapter, "_session_cookies"):
            try:
                cookies = json.loads(cookies_sidecar.read_text(encoding="utf-8"))
                if isinstance(cookies, dict) and cookies:
                    for name, value in cookies.items():
                        adapter.session.cookies.set(name, value)
                    adapter._session_cookies = cookies
            except Exception:
                pass
        if state_sidecar.exists() and hasattr(adapter, "_session_state"):
            try:
                state = json.loads(state_sidecar.read_text(encoding="utf-8"))
                if isinstance(state, dict):
                    adapter._session_state = state
                    if state.get("q1"):
                        adapter._q1 = state["q1"]
                    if state.get("action_path"):
                        adapter._action_path = state["action_path"]
                    # Mark session as warmed so warm_session() is not called again
                    # (which would create a new JSESSIONID and invalidate q2 hashes)
                    if state.get("q1"):
                        adapter._session_warmed = True
            except Exception:
                pass
        if hasattr(adapter, "warm_session"):
            try:
                adapter.warm_session()
            except Exception as exc:
                raise WorkflowError(f"warm_session failed: {exc}") from exc
        return adapter

    def _download_one_via_adapter(self, adapter, document: dict, out_dir: Path) -> dict[str, Any]:
        """Download one document using an already-warmed adapter.

        Adapter ownership is the caller's responsibility — this function neither
        builds nor warms it. See `_build_download_adapter` for setup.
        """
        doc_num = document["document_number"]
        out_path = out_dir / f"{doc_num}.pdf"
        try:
            result = adapter.download_pdf(doc_num=doc_num, dest_path=out_path)
        except Exception as exc:
            return {"status": "error", "message": f"download_pdf raised {type(exc).__name__}: {exc}"}
        if result.get("status") == "success":
            return {
                "status": "success",
                "files": [str(out_path.relative_to(self.case_dir))],
                "size": result.get("size"),
                "src_via": result.get("src_via"),
            }
        return {
            "status": result.get("status", "error"),
            "message": result.get("message") or result.get("error") or "download_pdf returned non-success",
        }

    def download(self) -> dict[str, Any]:
        documents = self._load_documents_found()
        if not documents:
            raise WorkflowError("Cannot download documents before search results exist.")

        manifest: dict[str, Any] = {
            "owner_name": self.config.owner_name,
            "safe_owner": self.config.safe_owner,
            "started_at": datetime.now().isoformat(),
            "results": [],
        }
        metadata = load_metadata(self.case_dir)
        use_titlepro = self._should_use_titlepro()
        explicit = self.config.use_titlepro is not None
        state_label = (self.config.state or "CA").upper()
        if use_titlepro:
            routing_label = f"TitlePro247 (CA legacy, {state_label})"
        else:
            routing_label = f"recorder adapter direct ({state_label})"
        print(
            f"  [download] routing: {routing_label} "
            f"[explicit={explicit}, state={state_label}, use_titlepro={self.config.use_titlepro}]"
        )

        adapter = None
        if not use_titlepro:
            adapter = self._build_download_adapter()

        for document in documents:
            doc_num = document["document_number"]
            existing = metadata.get(doc_num)
            if existing and existing.get("filename") and (self.case_dir / existing["filename"]).exists():
                manifest["results"].append(
                    {
                        "document_number": doc_num,
                        "status": "skipped_existing",
                        "filename": existing["filename"],
                        "attempts": 0,
                    }
                )
                continue

            last_result: Optional[dict[str, Any]] = None
            for attempt in range(1, self.config.download_retries + 1):
                if use_titlepro:
                    last_result = download_document(
                        doc_num=doc_num,
                        year=self._document_year(document),
                        headless=self.config.download_headless,
                        owner_name=self.config.case_path,
                        county=self.config.download_portal_county,
                        document_type=document.get("document_type"),
                        found_via_names=document.get("found_via_names"),
                        base_url_override=self.config.download_base_url,
                    )
                else:
                    last_result = self._download_one_via_adapter(adapter, document, self.case_dir)
                if last_result.get("status") == "success" and last_result.get("files"):
                    break
                if attempt < self.config.download_retries:
                    time.sleep(self.config.download_retry_delay_seconds)

            # When the adapter path succeeds, persist a document_metadata.json
            # entry so the validate / extract_text phases can resolve doc_num
            # -> filename. The TitlePro path writes its own metadata inside
            # download_document(); the adapter path used to omit this, which
            # caused extract_text to fail with "Missing metadata for [...]".
            result_status = (last_result or {}).get("status")
            result_files = (last_result or {}).get("files") or []
            if (
                not use_titlepro
                and result_status == "success"
                and result_files
            ):
                primary_relpath = result_files[0]
                primary_name = Path(primary_relpath).name
                doc_entry = {
                    "filename": primary_name,
                    "year": self._document_year(document),
                    "downloaded_at": datetime.now().isoformat(),
                    "all_files": [Path(f).name for f in result_files],
                    "src_via": (last_result or {}).get("src_via") or "adapter.download_pdf",
                }
                doc_type = document.get("document_type")
                if doc_type:
                    doc_entry["document_type"] = doc_type
                found_via = document.get("found_via_names")
                if found_via:
                    doc_entry["found_via_names"] = found_via
                    doc_entry["is_party_specific"] = len(found_via) == 1
                metadata[doc_num] = doc_entry
                save_metadata(self.case_dir, metadata)

            manifest["results"].append(
                {
                    "document_number": doc_num,
                    "status": (last_result or {}).get("status", "error"),
                    "message": (last_result or {}).get("message"),
                    "files": (last_result or {}).get("files", []),
                    "attempts": self.config.download_retries if (last_result or {}).get("status") != "success" else attempt,
                }
            )

        summary = self._download_validation_summary(raise_on_failure=self.config.strict_downloads)
        manifest["completed_at"] = datetime.now().isoformat()
        manifest["summary"] = summary
        self.download_manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return summary

    def validate_downloads(self) -> dict[str, Any]:
        # When strict_downloads=False, validate_downloads is also non-fatal so
        # the pipeline can proceed to extract_text (which handles missing PDFs
        # gracefully as examined_and_excluded). This lets counties with broken
        # download adapters still produce RAW + Title from index-only data.
        return self._download_validation_summary(raise_on_failure=self.config.strict_downloads)

    def _download_validation_summary(self, raise_on_failure: bool) -> dict[str, Any]:
        documents = self._load_documents_found()
        metadata = load_metadata(self.case_dir)
        missing_metadata: list[str] = []
        missing_files: list[str] = []
        examined_and_excluded: list[str] = []

        for document in documents:
            doc_num = document["document_number"]
            # Docs marked `examined_and_excluded` (e.g. statutorily prohibited
            # FL Death Certificates / CPX divorce records) are not required to
            # have a downloaded PDF; the report itemizes them under
            # "INACCESSIBLE / PROHIBITED DOCUMENTS" per Tony directive #5.
            if document.get("examined_and_excluded") or document.get("prohibited"):
                examined_and_excluded.append(doc_num)
                continue
            entry = metadata.get(doc_num)
            if not entry or entry.get("examined_and_excluded") or entry.get("prohibited"):
                # Metadata can also carry the exclusion marker (set by manual
                # post-processing in tools that promote a download failure to
                # examined-and-excluded).
                if entry and (entry.get("examined_and_excluded") or entry.get("prohibited")):
                    examined_and_excluded.append(doc_num)
                    continue
                missing_metadata.append(doc_num)
                continue
            filename = entry.get("filename")
            if not filename or not (self.case_dir / filename).exists():
                missing_files.append(doc_num)

        summary = {
            "success": not missing_metadata and not missing_files,
            "expected_documents": len(documents),
            "metadata_entries": len(metadata),
            "missing_metadata_documents": missing_metadata,
            "missing_file_documents": missing_files,
            "examined_and_excluded_documents": examined_and_excluded,
        }
        self.download_validation_path().write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if raise_on_failure and not summary["success"]:
            raise WorkflowError(
                "Download validation failed. Missing metadata for "
                f"{missing_metadata or 'none'}, missing files for {missing_files or 'none'}."
            )
        return summary

    def extract_text(self) -> dict[str, Any]:
        # Respect strict_downloads so index-only runs (e.g. Atala portals where
        # download is broken) still proceed through extraction with missing PDFs
        # silently promoted to examined_and_excluded below.
        validation = self._download_validation_summary(raise_on_failure=self.config.strict_downloads)
        documents = self._load_documents_found()
        metadata = load_metadata(self.case_dir)
        results: list[dict[str, Any]] = []

        for document in documents:
            doc_num = document["document_number"]
            # Skip examined-and-excluded docs (no PDF on disk by design).
            if document.get("examined_and_excluded") or document.get("prohibited"):
                results.append({
                    "document_number": doc_num,
                    "examined_and_excluded": True,
                    "reason": document.get("exclusion_reason")
                    or document.get("prohibited_reason")
                    or "examined_and_excluded",
                })
                continue
            entry = metadata.get(doc_num) or {}
            if entry.get("examined_and_excluded") or entry.get("prohibited") or not entry.get("filename"):
                results.append({
                    "document_number": doc_num,
                    "examined_and_excluded": True,
                    "reason": entry.get("exclusion_reason")
                    or entry.get("prohibited_reason")
                    or document.get("exclusion_reason")
                    or "examined_and_excluded",
                })
                continue
            filename = entry["filename"]
            pdf_path = self.case_dir / filename
            extracted_path = pdf_path.with_name(f"{pdf_path.stem}_extracted.md")
            extraction = self._extract_pdf(pdf_path)
            extracted_path.write_text(extraction["markdown"], encoding="utf-8")
            if extraction["total_chars"] < self.config.min_page_text_chars:
                # OCR not available (tesseract not installed) or PDF is image-only
                # with no readable text. Promote to examined_and_excluded rather
                # than crashing the whole job — the report will note the doc as
                # unreadable.
                _warn = (
                    f"Extracted text for {pdf_path.name} is too small "
                    f"({extraction['total_chars']} chars) — "
                    f"{'OCR not available (install tesseract + pytesseract)' if pytesseract is None else 'OCR attempted but yielded no text'}. "
                    f"Promoting to examined_and_excluded."
                )
                print(f"[EXTRACT] WARNING: {_warn}", flush=True)
                results.append({
                    "document_number": doc_num,
                    "examined_and_excluded": True,
                    "reason": _warn,
                })
                continue
            results.append(
                {
                    "document_number": doc_num,
                    "filename": filename,
                    "extracted_markdown": extracted_path.name,
                    "total_chars": extraction["total_chars"],
                    "ocr_used": extraction["ocr_used"],
                }
            )

        summary = {
            "success": True,
            "validated_documents": validation["expected_documents"],
            "extracted_documents": len(results),
            "documents": results,
        }
        self.extraction_summary_path().write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    # ------------------------------------------------------------------
    # Legal Description deterministic extractor.
    # Closes audit defect 1 (paraphrase) + defect 2 (silent APN check-digit
    # drop). We extract verbatim Exhibit A + APN per deed-shaped document
    # and inject the result into RAW + Title prompts, bypassing the
    # `max_document_chars` clip that historically lost Exhibit A in long DOTs.
    # ------------------------------------------------------------------

    # Match types that typically carry an Exhibit A / legal description.
    _DEED_TYPE_PATTERNS = re.compile(
        r"(?i)(grant\s+deed|deed\s+of\s+trust|quitclaim|warranty\s+deed|\bdeed\b)"
    )

    # Anchors for the legal-description block (priority order).
    _LEGAL_ANCHORS: tuple[tuple[str, str], ...] = (
        ("EXHIBIT A", r"\bEXHIBIT\s+A\b"),
        ("LEGAL DESCRIPTION", r"\bLEGAL\s+DESCRIPTION\b"),
        ("THE LAND REFERRED TO", r"\bTHE\s+LAND\s+REFERRED\s+TO\b"),
        ("THE FOLLOWING DESCRIBED REAL PROPERTY",
         r"\bTHE\s+FOLLOWING\s+DESCRIBED\s+REAL\s+PROPERTY\b"),
        ("DESCRIBED AS FOLLOWS", r"\bdescribed\s+as\s+follows\b"),
        ("DESCRIBED AS:", r"\bdescribed\s+as[:\s]"),
    )

    # Strong terminators that end a legal description block.
    _LEGAL_TERMINATORS: tuple[str, ...] = (
        r"\bA\s+notary\s+public\s+or\s+other\s+officer\b",
        r"\bSTATE\s+OF\s+CALIFORNIA\b\s*\)?\s*\n",
        r"\bWITNESS\s+my\s+hand\b",
        r"\bPage\s+\d+\s+of\s+\d+\b",
        r"\n##\s+Page\s+\d+",   # OCR page-break marker
        r"\bEND\s+OF\s+(EXHIBIT|LEGAL)\b",
    )

    # APN / parcel-number patterns, preferring longest match (most check digits).
    _APN_PATTERNS: tuple[str, ...] = (
        r"PARCEL\s+NO\.?\s*[:\s]*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
        r"PARCEL\s+NUMBER\s*[:\s]*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
        r"A\.?P\.?N\.?\s*[:#]?\s*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
        r"APN\s*[:#]?\s*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
        r"Parcel\s+No\.?\s*[:\s]*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
        r"Assessor[’'`]?s\s+Parcel\s+(?:No\.?|Number)\s*[:\s]*([0-9]{2,4}(?:-[0-9]{1,4}){2,5})",
    )

    def _extract_legal_block(self, text: str) -> tuple[Optional[str], Optional[str], float]:
        """Return (verbatim_text, anchor_used, confidence). Best-effort."""
        if not text:
            return (None, None, 0.0)

        for anchor_name, pattern in self._LEGAL_ANCHORS:
            match = re.search(pattern, text)
            if not match:
                continue
            start = match.start()
            # Slice from the line-start of the anchor for clean output.
            line_start = text.rfind("\n", 0, start) + 1
            tail = text[line_start:]

            # Search for the earliest terminator after the anchor.
            end_offset = len(tail)
            for term in self._LEGAL_TERMINATORS:
                term_match = re.search(term, tail[match.start() - line_start + 1:])
                if term_match:
                    candidate = match.start() - line_start + 1 + term_match.start()
                    if candidate < end_offset:
                        end_offset = candidate

            block = tail[:end_offset].strip()
            # Cap at a sane length to avoid runaway captures.
            if len(block) > 4000:
                block = block[:4000].rstrip() + "\n[...truncated]"
            # Confidence: higher for stronger anchors.
            confidence = {
                "EXHIBIT A": 0.95,
                "LEGAL DESCRIPTION": 0.9,
                "THE LAND REFERRED TO": 0.9,
                "THE FOLLOWING DESCRIBED REAL PROPERTY": 0.85,
                "DESCRIBED AS FOLLOWS": 0.7,
                "DESCRIBED AS:": 0.6,
            }.get(anchor_name, 0.5)
            if len(block) < 80:
                confidence *= 0.5
            return (block, anchor_name, round(confidence, 2))

        return (None, None, 0.0)

    def _extract_apn_verbatim(self, text: str) -> Optional[str]:
        """Return the longest APN candidate found in `text` (preserving check digits)."""
        candidates: list[str] = []
        for pattern in self._APN_PATTERNS:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                candidate = (m.group(1) or "").strip()
                if candidate:
                    candidates.append(candidate)
        if not candidates:
            return None
        # Longest wins (most check digits preserved).
        candidates.sort(key=lambda s: (s.count("-"), len(s)), reverse=True)
        return candidates[0]

    def extract_legal_descriptions(self) -> dict[str, Any]:
        """Deterministically extract verbatim Exhibit A + APN per deed.

        Closes audit defect 1 (LLM paraphrase) by giving the AI prompt a
        pre-extracted, structured verbatim block independent of the
        `max_document_chars` clip.
        """
        # We must have at least the extracted-text phase complete.
        self._extraction_summary(raise_on_failure=True)
        documents = self._load_documents_found()
        metadata = load_metadata(self.case_dir)

        sidecar: dict[str, dict[str, Any]] = {}
        deed_count = 0
        with_legal = 0
        with_apn = 0

        for document in documents:
            if not isinstance(document, dict):
                continue
            doc_num = document.get("document_number")
            if not doc_num:
                continue
            doc_type = str(document.get("document_type") or "")
            is_deed = bool(self._DEED_TYPE_PATTERNS.search(doc_type))
            if not is_deed:
                continue
            deed_count += 1

            entry: dict[str, Any] = {
                "document_type": doc_type,
                "recording_date": document.get("recording_date", ""),
                "filename": "",
                "legal_description_verbatim": "",
                "apn_verbatim": "",
                "anchor_used": "",
                "extraction_source": "missing",
                "extraction_confidence": 0.0,
                "extracted_at": datetime.now().isoformat(),
            }

            filename = metadata.get(doc_num, {}).get("filename") or ""
            entry["filename"] = filename
            extracted_md_path = None
            if filename:
                stem = Path(filename).stem
                candidate = self.case_dir / f"{stem}_extracted.md"
                if candidate.exists():
                    extracted_md_path = candidate

            text = ""
            source = "missing"
            if extracted_md_path is not None:
                try:
                    text = extracted_md_path.read_text(encoding="utf-8")
                    source = "extracted_md"
                except Exception:
                    text = ""

            # PDF fallback if extracted MD missing or yields nothing useful.
            if not text and filename:
                pdf_path = self.case_dir / filename
                if pdf_path.exists():
                    try:
                        pdf_doc = fitz.open(pdf_path)
                        try:
                            parts = []
                            for page in pdf_doc:
                                parts.append(page.get_text("text"))
                            text = "\n".join(parts)
                            source = "pdf_text_layer"
                        finally:
                            pdf_doc.close()
                    except Exception:
                        text = ""

            entry["extraction_source"] = source if text else "missing"

            if text:
                block, anchor, confidence = self._extract_legal_block(text)
                if block:
                    entry["legal_description_verbatim"] = block
                    entry["anchor_used"] = anchor or ""
                    entry["extraction_confidence"] = confidence
                    with_legal += 1
                apn = self._extract_apn_verbatim(text)
                if apn:
                    entry["apn_verbatim"] = apn
                    with_apn += 1

            sidecar[str(doc_num)] = entry

        self.legal_descriptions_path().write_text(
            json.dumps(sidecar, indent=2, default=str),
            encoding="utf-8",
        )

        return {
            "success": True,
            "deeds_inspected": deed_count,
            "with_legal_description": with_legal,
            "with_apn": with_apn,
            "sidecar": self.legal_descriptions_path().name,
        }

    def _extraction_summary(self, raise_on_failure: bool) -> dict[str, Any]:
        if not self.extraction_summary_path().exists():
            summary = {"success": False, "error": "extraction summary missing"}
            if raise_on_failure:
                raise WorkflowError(summary["error"])
            return summary

        summary = json.loads(self.extraction_summary_path().read_text(encoding="utf-8"))
        missing_files = [
            item["extracted_markdown"]
            for item in summary.get("documents", [])
            if not item.get("examined_and_excluded")
            and "extracted_markdown" in item
            and not (self.case_dir / item["extracted_markdown"]).exists()
        ]
        summary["success"] = summary.get("success", False) and not missing_files
        if missing_files:
            summary["missing_files"] = missing_files
        if raise_on_failure and not summary["success"]:
            raise WorkflowError(f"Extraction validation failed: {summary}")
        return summary

    # ------------------------------------------------------------------
    # Phase-1 verification suite. Populates phase1_verifications.json —
    # the sidecar consumed by _build_phase1_verifications_block() (RAW /
    # Title prompts) and tony_commentary_generator. Until 2026-06-10 this
    # sidecar was only written by per-case run_e2e.py scripts; this phase
    # makes population a first-class pipeline step.
    # ------------------------------------------------------------------

    def phase1_verifications_path(self) -> Path:
        return self.case_dir / "phase1_verifications.json"

    def _load_extracted_texts(self) -> dict[str, str]:
        """Map doc_number -> extracted markdown for the main corpus.

        Resolution mirrors _build_document_excerpt_block: download metadata
        gives the PDF filename; the extraction phase wrote
        `{stem}_extracted.md` next to it. Missing/excluded docs are
        tolerated (verification modules treat absent text as empty).
        """
        texts: dict[str, str] = {}
        metadata = load_metadata(self.case_dir)
        for document in self._load_documents_found():
            doc_num = document.get("document_number")
            if not doc_num:
                continue
            entry = metadata.get(doc_num) or {}
            filename = entry.get("filename")
            if not filename:
                continue
            extracted_path = self.case_dir / f"{Path(filename).stem}_extracted.md"
            if extracted_path.exists():
                texts[doc_num] = extracted_path.read_text(encoding="utf-8")
        return texts

    def phase1_verifications(self) -> dict[str, Any]:
        from titlepro.verification.document_type_classifier import (
            classify_all_documents,
            detect_noc_termination_bundles,
        )
        from titlepro.verification.not_needed_audit import (
            MissingMortgageMetadata,
            _extract_mortgage_metadata,
            audit_not_needed,
        )
        from titlepro.verification.released_mortgage_linker import (
            classify_mortgages,
            is_mortgage,
        )
        from titlepro.verification.subject_address_verifier import (
            extract_subject_address_from_text,
            verify_subject_address,
        )
        from titlepro.verification.title_affidavit_linker import (
            link_title_affidavits_to_judgments,
        )
        from titlepro.verification.vesting_chain_walker import walk_vesting_chain

        documents = self._load_documents_found()
        if not documents:
            raise WorkflowError("phase1_verifications requires documents_found.json with documents.")
        extracted_texts = self._load_extracted_texts()
        subject_address = (self.config.property_address or "").strip()
        subject_owners = [r.name for r in self.config.search_requests]

        # ---- Doc-type classification (shared by every module below) ----
        classifications = classify_all_documents(documents, extracted_texts)
        inferred_types = {num: c.inferred_type for num, c in classifications.items()}
        doc_type_block = {
            num: {
                "raw": next(
                    (d.get("document_type", "") for d in documents
                     if d.get("document_number") == num), ""),
                "inferred": c.inferred_type,
                "confidence": c.confidence,
                "source": c.source,
            }
            for num, c in classifications.items()
        }

        # ---- Subject-address verification (Tony #4) ----
        addr_results: dict[str, dict[str, Any]] = {}
        if subject_address:
            # Hint = street-name portion (strip the leading house number).
            hint = re.sub(r"^\s*\d+\s+", "", subject_address.split(",")[0]).strip() or None
            for document in documents:
                doc_num = document.get("document_number")
                text = extracted_texts.get(doc_num, "")
                if not doc_num or not text.strip():
                    continue
                try:
                    extracted_addr = extract_subject_address_from_text(text, subject_hint=hint)
                except Exception:
                    extracted_addr = None
                if not extracted_addr:
                    addr_results[doc_num] = {
                        "status": "NO_ADDRESS",
                        "similarity": 0.0,
                        "extracted_address": "",
                    }
                    continue
                match = verify_subject_address(extracted_addr, subject_address)
                addr_results[doc_num] = {
                    "extracted_address": extracted_addr,
                    "status": match.status,
                    "similarity": match.similarity,
                    "matched_components": match.matched_components,
                    "evidence": match.evidence,
                }

        # ---- not_needed/ audit (Tony #5) ----
        recovered_dicts: list[dict[str, Any]] = []
        ledger_dicts: list[dict[str, Any]] = []
        recovered_docs = None
        not_needed_dir = self.case_dir / "not_needed"
        audit_note = ""
        if not_needed_dir.is_dir():
            mortgage_docs = [
                d for d in documents
                if is_mortgage(d)
                or inferred_types.get(d.get("document_number", "")) == "MORTGAGE"
            ]
            known_mortgages = _extract_mortgage_metadata(mortgage_docs, extracted_texts)
            try:
                audit = audit_not_needed(self.case_dir, known_mortgages)
                recovered_docs = audit.recovered
                recovered_dicts = [r.to_dict() for r in audit.recovered]
                ledger_dicts = [e.to_dict() for e in audit.ledger]
            except MissingMortgageMetadata as exc:
                # No mortgages (or none with cross-ref fields) — audit cannot
                # link satisfactions. Record why instead of failing the phase.
                audit_note = str(exc)
        else:
            audit_note = "no not_needed/ directory in case folder"

        # ---- Released-mortgage linker (Tony #6) ----
        mortgage_classifications = {
            num: mc.to_dict()
            for num, mc in classify_mortgages(
                documents,
                extracted_texts,
                inferred_types=inferred_types,
                recovered_docs=recovered_docs,
            ).items()
        }

        # ---- OnE v1.6 modules ----
        walker_finding = walk_vesting_chain(
            documents,
            extracted_texts,
            subject_owner_names=subject_owners,
        )
        noc_bundles = detect_noc_termination_bundles(
            documents, extracted_texts, inferred_types=inferred_types
        )
        affidavit_pairings = link_title_affidavits_to_judgments(
            documents, extracted_texts, inferred_types=inferred_types
        )

        # ---- Merge-write the sidecar (preserve unknown keys from any
        # earlier manual run; this phase owns the keys it computes). ----
        sidecar: dict[str, Any] = {}
        if self.phase1_verifications_path().exists():
            try:
                sidecar = json.loads(self.phase1_verifications_path().read_text(encoding="utf-8"))
            except Exception:
                sidecar = {}
        sidecar.update(
            {
                "subject_address": subject_address,
                "subject_apn": self.config.apn or "",
                "subject_owners": subject_owners,
                "subject_address_verification": addr_results,
                "document_type_classifications": doc_type_block,
                "mortgage_classifications": mortgage_classifications,
                "recovered_from_not_needed": recovered_dicts,
                "not_needed_ledger": ledger_dicts,
                "vesting_chain_walker": walker_finding.to_dict(),
                "noc_termination_bundles": [b.to_dict() for b in noc_bundles],
                "title_affidavit_pairings": [p.to_dict() for p in affidavit_pairings],
                "generated_at": datetime.now().isoformat(),
            }
        )
        if audit_note:
            sidecar["not_needed_audit_note"] = audit_note
        self.phase1_verifications_path().write_text(
            json.dumps(sidecar, indent=2, default=str), encoding="utf-8"
        )

        released = sum(
            1 for mc in mortgage_classifications.values()
            if isinstance(mc, dict) and mc.get("status") == "released"
        )
        return {
            "success": True,
            "documents": len(documents),
            "documents_with_text": len(extracted_texts),
            "address_verified": len(addr_results),
            "mortgages_classified": len(mortgage_classifications),
            "mortgages_released": released,
            "recovered_from_not_needed": len(recovered_dicts),
            "vesting_chain_walker_status": walker_finding.status,
            "noc_termination_bundles": len(noc_bundles),
            "title_affidavit_pairings": len(affidavit_pairings),
        }

    def _phase1_verifications_skip_ok(self) -> bool:
        """Resume validator: the sidecar must exist AND carry the v1.6 keys.

        Pre-2026-06 sidecars (subject-address + mortgage keys only) fail
        this check so a resumed run re-populates the new module outputs.
        """
        path = self.phase1_verifications_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        required = (
            "mortgage_classifications",
            "vesting_chain_walker",
            "noc_termination_bundles",
            "title_affidavit_pairings",
        )
        return all(key in data for key in required)

    # Required tax fields that must be present in `tax_<safe_owner>.json` for
    # the lookup to be considered "verified". Mirrors the proposal's
    # "Tax behavior" section.
    TAX_VERIFIED_BASE_FIELDS = ("apn", "tax_year", "source_url")
    TAX_VERIFIED_AMOUNT_FIELDS = ("assessed_value_total", "annual_tax_estimated", "annual_tax")
    TAX_VERIFIED_OPTIONAL_FIELDS = (
        "first_installment_status",
        "second_installment_status",
        "installment_status",
    )

    def tax_lookup(self) -> dict[str, Any]:
        """
        Phase 5: Tax & Property Lookup.

        Routes through `titlepro.tax.fetch_tax()` (v2 dispatcher) which
        returns a `TaxLookupResult`. Status semantics:

          * `fetch_tax=False`                   -> sidecar `status="disabled"`; pass.
          * APN missing                         -> sidecar `status="skipped"`; pass iff
                                                    `allow_tax_skip_on_missing_apn=True`.
          * `TAX_SUCCESS`                       -> sidecar `status="success"`; pass.
          * `TAX_PARTIAL`                       -> sidecar `status="TAX_PARTIAL"`; pass
                                                    (RAW guard will enforce "TAX STATUS NOT VERIFIED").
          * `TAX_NO_RUNNER`                     -> sidecar `status="TAX_NO_RUNNER"`; pass
                                                    unless `strict_tax_no_runner=True`.
          * `TAX_FAILED` / `TAX_NO_RESULTS`     -> hard fail (`WorkflowError`).
          * `NEEDS_HUMAN`                       -> CaptchaCheckpointRequired bubbles up.

        Back-compat: when the dispatcher returns TAX_SUCCESS / TAX_PARTIAL,
        we also write the legacy `tax_<safe_owner>.json` artifact with
        flattened fields so existing report generators that read it
        continue to work.
        """
        county = self.config.county
        owner_name = self.config.output_folder_name or self.config.owner_name
        property_address = self.config.property_address

        # Disabled-by-config case
        if not self.config.fetch_tax:
            status = self._write_tax_lookup_status(
                status="disabled",
                reason="fetch_tax_disabled",
                county=county,
                apn=self.config.apn or "",
                notes="Tax lookup disabled by workflow config (fetch_tax=false).",
            )
            return {"success": True, "status": status, "method": "disabled"}

        apn = (self.config.apn or self._extract_apn_from_artifacts() or "").strip()

        if not apn:
            notes = (
                "Tax lookup requires an APN. Provide workflow config field "
                "'apn'/'parcel_number' or ensure documents_found.json includes an APN field."
            )
            status = self._write_tax_lookup_status(
                status="skipped",
                reason="apn_missing",
                county=county,
                apn="",
                notes=notes,
            )
            if self.config.allow_tax_skip_on_missing_apn:
                return {"success": True, "status": status, "method": "skipped"}
            raise WorkflowError(notes)

        # Dispatch through the v2 fetch_tax dispatcher.
        from titlepro.tax import fetch_tax as _fetch_tax
        from titlepro.tax.result import TaxLookupResult as _TLR

        result: _TLR = _fetch_tax(
            county_id=county,
            apn=apn,
            owner_name=owner_name,
            property_address=property_address,
            case_dir=self.case_dir,
        )

        # Always write the canonical JSON snapshot of the result.
        canonical_path = self.case_dir / f"tax_{self.config.safe_owner}.json"
        canonical_path.write_text(
            json.dumps(result.to_json_dict(), default=str, indent=2),
            encoding="utf-8",
        )

        # Status sidecar
        sidecar_status_map = {
            "TAX_SUCCESS": "success",
            "TAX_PARTIAL": "TAX_PARTIAL",
            "TAX_NO_RUNNER": "TAX_NO_RUNNER",
            "TAX_FAILED": "failed",
            "TAX_NO_RESULTS": "TAX_NO_RESULTS",
            "NEEDS_HUMAN": "needs_human",
        }
        sidecar_status = sidecar_status_map.get(result.status, "unknown")
        status_payload = self._write_tax_lookup_status(
            status=sidecar_status,
            tax_status=result.status,
            method=result.status.lower(),
            reason=result.notes or result.error or "ok",
            county=county,
            apn=apn,
            tax_data_path=str(canonical_path),
            verified_fields=list(result.verified_fields),
            missing_fields=list(result.missing_fields),
            source_url=result.source_url,
            captured_at=result.captured_at.isoformat() if hasattr(result.captured_at, "isoformat") else str(result.captured_at),
            notes=result.notes or result.error or "",
        )

        # Phase gate (Codex finding 3 hardening).
        # In a lenient run (strict_downloads=False), a TAX_FAILED / TAX_NO_RESULTS
        # is NOT fatal: re-running cannot recover a CF-blocked (datacenter-egress
        # HTTP 403) or missing-county tax endpoint, and the RAW/Title generators
        # emit "TAX STATUS NOT VERIFIED" inline. This mirrors the resume-skip logic
        # in _phase_is_complete (see the strict_downloads guard there). Only a
        # strict run hard-fails so the gap surfaces loudly during validation.
        if result.status == "TAX_FAILED":
            if self.config.strict_downloads:
                raise WorkflowError(
                    f"tax_lookup failed: {result.error or result.notes or 'unknown error'}"
                )
            print(
                f"[tax_lookup] TAX_FAILED (lenient pass): {result.error or result.notes or 'unknown error'}"
            )
        elif result.status == "TAX_NO_RESULTS":
            if self.config.strict_downloads:
                raise WorkflowError(
                    f"tax_lookup: county portal reports no parcel for APN {apn}: "
                    f"{result.notes or 'no_results'}"
                )
            print(
                f"[tax_lookup] TAX_NO_RESULTS (lenient pass): APN {apn}: "
                f"{result.notes or 'no_results'}"
            )
        if result.status == "TAX_NO_RUNNER":
            if self.config.strict_tax_no_runner:
                raise WorkflowError(
                    f"tax_lookup: no runner configured for county {county!r} "
                    f"(strict_tax_no_runner=True). {result.notes}"
                )
            print(f"[tax_lookup] TAX_NO_RUNNER (lenient pass): {result.notes}")

        return {
            "success": True,
            "status": result.status,
            "method": result.status.lower(),
            "tax_data_path": str(canonical_path),
            "tax_lookup_status_path": str(self.tax_lookup_status_path()),
            "county": county,
            "apn": apn or "",
            "verified_fields": list(result.verified_fields),
            "missing_fields": list(result.missing_fields),
            "source_url": result.source_url,
            "notes": result.notes or result.error or "",
        }

    def _validate_tax_payload(
        self, payload: dict[str, Any], apn: str
    ) -> tuple[list[str], list[str]]:
        """Return (verified_fields, missing_fields) for the tax artifact.

        Required: APN, tax_year, source_url (or verification_url), AND at
        least one of (assessed_value_total, annual_tax_estimated, annual_tax).
        Installment status is recommended but not required.
        """
        # The downstream perform_tax_lookup helper writes either a flat dict
        # or {"lookup_metadata": ..., "tax_information": ...}. Normalize.
        tax_info = payload if not isinstance(payload, dict) else (
            payload.get("tax_information") or payload
        )
        meta = payload.get("lookup_metadata", {}) if isinstance(payload, dict) else {}

        verified: list[str] = []
        missing: list[str] = []

        def _has(value: Any) -> bool:
            if value in (None, "", [], {}):
                return False
            if isinstance(value, str) and not value.strip():
                return False
            return True

        # APN
        apn_value = tax_info.get("apn") or meta.get("apn_searched") or apn
        if _has(apn_value):
            verified.append("apn")
        else:
            missing.append("apn")

        # tax_year
        if _has(tax_info.get("tax_year")):
            verified.append("tax_year")
        else:
            missing.append("tax_year")

        # source URL: accept several aliases
        source = (
            tax_info.get("source_url")
            or tax_info.get("verification_url")
            or tax_info.get("data_source")
            or meta.get("verification_url")
            or meta.get("data_source")
        )
        if _has(source):
            verified.append("source_url")
        else:
            missing.append("source_url")

        # At least one of assessed_value_total / annual_tax_estimated / annual_tax
        amount_keys = self.TAX_VERIFIED_AMOUNT_FIELDS
        amount_found = next((k for k in amount_keys if _has(tax_info.get(k))), None)
        if amount_found:
            verified.append(amount_found)
        else:
            missing.append("assessed_value_or_annual_tax")

        # Installment status (recommended)
        installment_found = next(
            (k for k in self.TAX_VERIFIED_OPTIONAL_FIELDS if _has(tax_info.get(k))),
            None,
        )
        if installment_found:
            verified.append(installment_found)
        # We do not add to "missing" for installment status — it's optional.

        return verified, missing

    def _write_tax_lookup_status(self, **status: Any) -> dict[str, Any]:
        payload = {
            "timestamp": datetime.now().isoformat(),
            **status,
        }
        self.tax_lookup_status_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def _extract_apn_from_artifacts(self) -> Optional[str]:
        """Best-effort APN extraction across documents_found.json, the
        legal_descriptions.json sidecar, and *_extracted.md text files.
        Returns the LONGEST APN string found (most check digits preserved).

        Audit fix: the previous implementation returned the FIRST hit,
        which favored truncated APNs missing check digits (e.g. it would
        return "502-153-010" when "502-153-010-9" was also available).

        Extended 2026-06-23: also scans *_extracted.md for FL parcel-number
        patterns so tax is not skipped when documents_found.json / legal
        descriptions lack an APN field (seen in VOLLMAN NAT_300701).
        """
        candidates: list[str] = []

        # documents_found.json APN fields
        try:
            documents = self._load_documents_found()
        except Exception:
            documents = []
        candidate_keys = ("APN", "apn", "parcel_number", "parcelNumber", "parcel")
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            for key in candidate_keys:
                value = doc.get(key)
                if value and isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

        # legal_descriptions.json verbatim APNs
        for entry in self._load_legal_descriptions().values():
            if not isinstance(entry, dict):
                continue
            apn = entry.get("apn_verbatim")
            if apn and isinstance(apn, str) and apn.strip():
                candidates.append(apn.strip())

        # *_extracted.md text — scan for common APN/Parcel/Folio patterns.
        # This catches the case where the APN is printed in the deed body but
        # was never stored in documents_found.json or legal_descriptions.json.
        if not candidates:
            _apn_re = re.compile(
                r"(?:Parcel\s+(?:ID|No\.?|Number|Identification)|"
                r"Folio\s*(?:No\.?|Number)?|APN)[:\s#]+([0-9][0-9\-\.]{6,25})",
                re.IGNORECASE,
            )
            for md_path in sorted(self.case_dir.glob("*_extracted.md")):
                try:
                    text = md_path.read_text(encoding="utf-8", errors="ignore")
                    for m in _apn_re.finditer(text):
                        val = m.group(1).strip().rstrip(".")
                        if len(val) >= 8:
                            candidates.append(val)
                except Exception:
                    pass
                if candidates:
                    break  # stop after first file with a hit

        if not candidates:
            return None
        # Longest wins (most check digits preserved); ties broken by
        # original ordering so deterministic across runs.
        candidates.sort(key=lambda s: (s.count("-"), len(s)), reverse=True)
        return candidates[0]

    def generate_raw_report(self) -> dict[str, Any]:
        self._extraction_summary(raise_on_failure=True)
        system_prompt = self._build_system_prompt(
            self._resolve_prompt_path(
                explicit=self.config.ai.raw_prompt_path,
                candidates=[
                    downloads_prompt_dir() / "TitleExam_SystemPrompt_Step1.md",
                    repo_prompt_dir() / "Cure_Response" / "RAW_Report_Generation_System_Prompt.md",
                    repo_prompt_dir() / "RAW_Report_Generation_System_Prompt.md",
                ],
            ),
            include_design_system=False,
        )
        user_prompt = self._build_raw_user_prompt()
        self._save_prompt_bundle("raw", system_prompt, user_prompt)
        output = self._run_agent(
            system_prompt, user_prompt,
            model=self._resolve_phase_model("raw"),
            provider=self._resolve_phase_provider("raw"),
        )
        validation = self._validate_markdown_content(
            output,
            self.config.raw_required_sections,
            label="RAW report",
        )
        # Raise BEFORE persisting bad output. Same rationale as
        # `generate_title_notes`: an invalid RAW md poisons every downstream
        # phase (title notes, PDF render) with a less-helpful error.
        if not validation.get("success", False):
            missing = validation.get("missing_sections") or []
            raise WorkflowError(
                "RAW report validation failed: missing required section(s) "
                f"{missing}. Re-run with a corrected prompt or verify the "
                "agent output before persisting."
            )

        # Tax-status integrity guard: if tax_lookup_status.json is not
        # `success`, the generated RAW markdown MUST acknowledge that. We do
        # not parse the LLM output for "verified" claims; we only require
        # the literal "TAX STATUS NOT VERIFIED" appear so the underwriter
        # cannot miss it.
        self._enforce_tax_status_in_raw(output)

        self.raw_markdown_path().write_text(output, encoding="utf-8")
        # Deterministic legal-description splice (#3) BEFORE validation so an
        # LLM paraphrase self-heals instead of forcing a full regeneration.
        ld_repair = self._repair_legal_description(self.raw_markdown_path(), label="RAW report")
        final_output = self.raw_markdown_path().read_text(encoding="utf-8")
        versioned = self._versioned_path("RAW_TWO_OWNER_SEARCH_EXAM", ".md")
        versioned.write_text(final_output, encoding="utf-8")

        ld_validation = self._validate_legal_description_integrity(
            self.raw_markdown_path(), label="RAW report"
        )

        return {
            "success": True,
            "raw_markdown": self.raw_markdown_path().name,
            "versioned_markdown": versioned.name,
            "validation": validation,
            "legal_description_repair": ld_repair,
            "legal_description_validation": ld_validation,
        }

    def _repair_legal_description(self, md_path: Path, label: str) -> dict[str, Any]:
        """Splice the canonical verbatim legal description into `md_path`
        before validation (#3). Writes the file back in place when changed.
        No-op passthrough when disabled or nothing to splice."""
        summary: dict[str, Any] = {"enabled": self.config.splice_legal_descriptions}
        if not self.config.splice_legal_descriptions:
            summary["status"] = "disabled"
            return summary
        try:
            from titlepro.verification.legal_description_validator import (
                repair_legal_description_section,
            )
        except Exception as exc:  # pragma: no cover - import safety net
            summary["status"] = "repair_import_failed"
            summary["error"] = str(exc)
            return summary

        result = repair_legal_description_section(md_path, self.legal_descriptions_path())
        summary.update(
            {
                "status": "spliced" if result.changed else "unchanged",
                "changed": result.changed,
                "canonical_doc_number": result.canonical_doc_number,
                "reason": result.reason,
            }
        )
        if result.changed:
            md_path.write_text(result.text, encoding="utf-8")
        return summary

    def _validate_legal_description_integrity(
        self, md_path: Path, label: str
    ) -> dict[str, Any]:
        """Run the Legal Description verbatim validator and raise on failure.

        Returns a dict for the phase summary. When
        `config.validate_legal_descriptions` is False, this is a no-op
        passthrough.
        """
        summary: dict[str, Any] = {"enabled": self.config.validate_legal_descriptions}
        if not self.config.validate_legal_descriptions:
            summary["status"] = "disabled"
            return summary
        try:
            from titlepro.verification.legal_description_validator import (
                validate_legal_description,
            )
        except Exception as exc:  # pragma: no cover - import safety net
            summary["status"] = "validator_import_failed"
            summary["error"] = str(exc)
            return summary

        result = validate_legal_description(
            md_path,
            self.legal_descriptions_path(),
            strict=True,
        )
        summary.update(
            {
                "status": "ok" if result.success else "failed",
                "best_similarity": result.best_similarity,
                "best_doc_number": result.best_doc_number,
                "matched_tokens": list(result.matched_tokens),
                "missing_tokens": list(result.missing_tokens),
                "details": result.details,
            }
        )
        if not result.success:
            raise WorkflowError(
                f"Legal description integrity check failed for {label}: "
                f"best similarity {result.best_similarity:.3f}; "
                f"missing tokens: {result.missing_tokens}; "
                f"details: {result.details}"
            )
        return summary

    def _enforce_tax_status_in_raw(self, output: str) -> None:
        """Raise WorkflowError when tax is not verified but the RAW report
        does not say `TAX STATUS NOT VERIFIED` (case-insensitive)."""
        status_path = self.tax_lookup_status_path()
        if not status_path.exists():
            if not self.config.fetch_tax:
                return  # tax is intentionally disabled
            status = {"status": "missing"}
        else:
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                status = {"status": "missing"}
        if status.get("status") == "success" or status.get("tax_status") == "TAX_SUCCESS":
            return
        needle = "TAX STATUS NOT VERIFIED"
        if needle.lower() not in (output or "").lower() and "tax not verified" not in (output or "").lower():
            raise WorkflowError(
                "RAW report fails tax-status integrity check: tax_lookup_status.json status is "
                f"'{status.get('status')}' but the generated markdown is missing the required "
                f"'{needle}' phrase. Re-run with a verified tax lookup or update the prompt."
            )

    def generate_title_notes(self) -> dict[str, Any]:
        self._validate_markdown_file(self.raw_markdown_path(), self.config.raw_required_sections, raise_on_failure=True)
        system_prompt = self._build_system_prompt(
            self._resolve_prompt_path(
                explicit=self.config.ai.title_prompt_path,
                candidates=[
                    downloads_prompt_dir() / "AbstractorNotes_Step2.md",
                    repo_prompt_dir() / "Cure_Response" / "Title_Examination_Notes_System_Prompt.md",
                    project_root() / "Title_Examination_Notes_System_Prompt.md",
                ],
            ),
            include_design_system=True,
        )
        user_prompt = self._build_title_user_prompt()
        self._save_prompt_bundle("title", system_prompt, user_prompt)
        output = self._run_agent(
            system_prompt, user_prompt,
            model=self._resolve_phase_model("title"),
            provider=self._resolve_phase_provider("title"),
        )
        validation = self._validate_markdown_content(
            output,
            self.config.title_required_sections,
            label="Title examination notes",
        )
        # Raise BEFORE persisting bad output to disk. A title md missing
        # required H2 sections poisons the downstream PDF render phase with
        # a less-helpful error, and (worse) gets versioned to the case dir.
        # Mirrors the integrity guard pattern used by `_enforce_tax_status_in_raw`.
        if not validation.get("success", False):
            missing = validation.get("missing_sections") or []
            # Auto-recover from leading truncation: the Claude CLI subprocess on
            # Windows sometimes drops the very beginning of a long response, which
            # cuts off the ## TITLE EXAMINATION SUMMARY header that the AI did
            # generate. If that is the ONLY missing section and the output body is
            # substantial (>500 chars), prepend a recovery header and re-validate
            # rather than failing the entire phase and wasting the AI spend.
            if missing == ["## TITLE EXAMINATION SUMMARY"] and len(output or "") > 500:
                print(
                    "[Title Notes] Leading-truncation recovery: prepending "
                    "## TITLE EXAMINATION SUMMARY block.",
                    flush=True,
                )
                _recovery = (
                    "# Abstractor Notes/Chain &emsp;&emsp;&emsp;&emsp;&emsp;&emsp; LOGO\n\n"
                    "## TITLE EXAMINATION SUMMARY\n\n"
                    "> *[Summary block auto-recovered — beginning of AI output was truncated "
                    "by subprocess. Full examination details are in the sections below.]*\n\n"
                    "---\n\n"
                )
                output = _recovery + output
                validation = self._validate_markdown_content(
                    output,
                    self.config.title_required_sections,
                    label="Title examination notes (truncation-recovered)",
                )

            if not validation.get("success", False):
                # Save draft so the operator can inspect what Claude actually generated
                # before deciding how to fix the prompt or validation.
                draft_path = self.case_dir / "Title_Examination_Notes_DRAFT.md"
                draft_path.write_text(output or "(empty output — agent returned nothing)", encoding="utf-8")
                raise WorkflowError(
                    "Title examination notes validation failed: missing required "
                    f"section(s) {validation.get('missing_sections')}. "
                    f"Draft saved to {draft_path.name} for inspection. "
                    "Re-run with a corrected prompt or verify the agent output before persisting."
                )
        self.title_markdown_path().write_text(output, encoding="utf-8")
        # Deterministic legal-description splice (#3) BEFORE validation.
        ld_repair = self._repair_legal_description(
            self.title_markdown_path(), label="Title examination notes"
        )
        final_output = self.title_markdown_path().read_text(encoding="utf-8")
        versioned = self._versioned_path("Title_Examination_Notes", ".md")
        versioned.write_text(final_output, encoding="utf-8")

        ld_validation = self._validate_legal_description_integrity(
            self.title_markdown_path(), label="Title examination notes"
        )

        return {
            "success": True,
            "title_markdown": self.title_markdown_path().name,
            "versioned_markdown": versioned.name,
            "validation": validation,
            "legal_description_repair": ld_repair,
            "legal_description_validation": ld_validation,
        }

    def generate_one_report(self) -> dict[str, Any]:
        self._validate_markdown_file(
            self.title_markdown_path(), self.config.title_required_sections, raise_on_failure=True
        )
        system_prompt = self._build_system_prompt(
            self._resolve_prompt_path(
                explicit=self.config.ai.one_prompt_path,
                candidates=[
                    repo_prompt_dir() / "Cure_Response" / "OnE_Report_SystemPrompt_v1.2.md",
                ],
            ),
            include_design_system=False,
        )
        title_markdown = self.title_markdown_path().read_text(encoding="utf-8")
        user_prompt = (
            "Generate the OnE Report from the Title Examination Notes below.\n\n"
            f"Owner Name: {self.config.owner_name}\n"
            f"Property Address: {self.config.property_address or '[NOT PROVIDED]'}\n"
            f"County/State: {self.config.county.replace('fl_', '').replace('_', ' ').title()}, {self.config.state}\n\n"
            "--- BEGIN TITLE EXAMINATION NOTES ---\n"
            f"{title_markdown}\n"
            "--- END TITLE EXAMINATION NOTES ---\n\n"
            "MANDATORY OUTPUT CONTRACT:\n"
            "- Return only the final markdown document. No commentary before or after.\n"
            "- Do NOT wrap in code fences.\n"
            "- Line 1 MUST be exactly: # Ownership and Encumbrance Report\n"
            "- MUST contain numbered sections ## 1. through ## 8. in order.\n"
            "- § 7 Miscellaneous is CONDITIONAL — include ONLY if an active NOC or prohibited document exists.\n"
            "- § 3 Open Mortgages is OPEN ONLY — do NOT include released/reconveyed mortgages.\n"
        )
        self._save_prompt_bundle("one", system_prompt, user_prompt)
        output = self._run_agent(
            system_prompt, user_prompt,
            model=self._resolve_phase_model("one"),
            provider=self._resolve_phase_provider("one"),
        )
        validation = self._validate_markdown_content(
            output, self.config.one_required_sections, label="OnE report"
        )
        if not validation.get("success", False):
            missing = validation.get("missing_sections") or []
            draft_path = self.case_dir / "OnE_Report_DRAFT.md"
            draft_path.write_text(output or "(empty output — agent returned nothing)", encoding="utf-8")
            raise WorkflowError(
                f"OnE report validation failed: missing required section(s) {missing}. "
                f"Draft saved to {draft_path.name} for inspection."
            )
        one_md = self.one_markdown_path()
        one_md.write_text(output, encoding="utf-8")
        versioned = self._versioned_path(one_md.stem, ".md")
        shutil.copy2(one_md, versioned)

        # Render to DOCX via pandoc (optional — skipped gracefully if pandoc not installed)
        docx_result = self._render_one_docx(one_md)

        return {
            "success": True,
            "one_markdown": one_md.name,
            "one_docx": docx_result.get("docx"),
            "docx_note": docx_result.get("note"),
            "versioned_markdown": versioned.name,
            "validation": validation,
        }

    def _render_one_docx(self, md_path: Path) -> dict[str, Any]:
        docx_path = self.one_docx_path()
        try:
            result = subprocess.run(
                ["pandoc", str(md_path), "-o", str(docx_path), "--wrap=none"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if result.returncode == 0 and docx_path.exists():
                return {"docx": docx_path.name}
            return {"docx": None, "note": f"pandoc error: {result.stderr.strip()}"}
        except FileNotFoundError:
            return {
                "docx": None,
                "note": "pandoc not installed — OnE DOCX skipped. Install pandoc to enable DOCX output.",
            }
        except Exception as exc:  # noqa: BLE001
            return {"docx": None, "note": f"DOCX render error: {exc}"}

    def render_pdfs(self) -> dict[str, Any]:
        outputs: dict[str, Any] = {"success": True}
        if self.config.generate_raw_pdf:
            self._validate_markdown_file(self.raw_markdown_path(), self.config.raw_required_sections, raise_on_failure=True)
            render_markdown_pdf(
                markdown_path=self.raw_markdown_path(),
                pdf_path=self.raw_pdf_path(),
                title=f"RAW Two Owner Search Exam — {self.config.owner_name}",
                header_left="RAW Two-Owner Title Search",
                doc_type=RAW_DOC_TYPE,
            )
            versioned_raw = self._versioned_path("RAW_TWO_OWNER_SEARCH_EXAM", ".pdf")
            shutil.copy2(self.raw_pdf_path(), versioned_raw)
            outputs["raw_pdf"] = self.raw_pdf_path().name
            outputs["raw_pdf_versioned"] = versioned_raw.name

        if self.config.generate_title_pdf and self.config.generate_title_notes:
            self._validate_markdown_file(self.title_markdown_path(), self.config.title_required_sections, raise_on_failure=True)
            render_markdown_pdf(
                markdown_path=self.title_markdown_path(),
                pdf_path=self.title_pdf_path(),
                title=f"Title Examination Notes — {self.config.owner_name}",
                header_left="Abstractor Notes/Chain",
                doc_type=TITLE_DOC_TYPE,
            )
            versioned_title = self._versioned_path("Title_Examination_Notes", ".pdf")
            shutil.copy2(self.title_pdf_path(), versioned_title)
            outputs["title_pdf"] = self.title_pdf_path().name
            outputs["title_pdf_versioned"] = versioned_title.name

        if self.config.generate_one_report and self.one_markdown_path().exists():
            one_pdf_path = self.one_markdown_path().with_suffix(".pdf")
            render_markdown_pdf(
                markdown_path=self.one_markdown_path(),
                pdf_path=one_pdf_path,
                title=f"Ownership and Encumbrance Report — {self.config.owner_name}",
                header_left="Ownership & Encumbrance Report",
                doc_type=RAW_DOC_TYPE,
            )
            versioned_one = self._versioned_path(self.one_markdown_path().stem, ".pdf")
            shutil.copy2(one_pdf_path, versioned_one)
            outputs["one_pdf"] = one_pdf_path.name
            outputs["one_pdf_versioned"] = versioned_one.name

        return outputs

    def _render_summary(self, raise_on_failure: bool) -> dict[str, Any]:
        success = True
        details = {}
        if self.config.generate_raw_pdf:
            success = success and self.raw_pdf_path().exists()
            details["raw_pdf"] = self.raw_pdf_path().exists()
        if self.config.generate_title_pdf and self.config.generate_title_notes:
            success = success and self.title_pdf_path().exists()
            details["title_pdf"] = self.title_pdf_path().exists()
        if self.config.generate_one_report and self.one_markdown_path().exists():
            one_pdf = self.one_markdown_path().with_suffix(".pdf")
            success = success and one_pdf.exists()
            details["one_pdf"] = one_pdf.exists()
        summary = {"success": success, "details": details}
        if raise_on_failure and not success:
            raise WorkflowError(f"Expected PDF outputs are missing: {details}")
        return summary

    def serialize_reports(self) -> dict[str, Any]:
        from titlepro.reports.build_json_xml_reports import build_case

        summary = build_case(self.case_dir)
        return {"success": True, "outputs": summary}

    def _serialize_summary(self, raise_on_failure: bool) -> dict[str, Any]:
        success = True
        details: dict[str, Any] = {}
        raw_md = self.raw_markdown_path()
        raw_pdf = self.raw_pdf_path()
        if raw_md.exists() or raw_pdf.exists():
            raw_json = (self.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.json").exists()
            raw_xml = (self.case_dir / "RAW_TWO_OWNER_SEARCH_EXAM.xml").exists()
            details["raw_json"] = raw_json
            details["raw_xml"] = raw_xml
            success = success and raw_json and raw_xml
        title_md = self.title_markdown_path()
        title_pdf = self.title_pdf_path()
        if title_md.exists() or title_pdf.exists():
            title_json = (self.case_dir / "Title_Examination_Notes.json").exists()
            title_xml = (self.case_dir / "Title_Examination_Notes.xml").exists()
            details["title_json"] = title_json
            details["title_xml"] = title_xml
            success = success and title_json and title_xml
        summary = {"success": success, "details": details}
        if raise_on_failure and not success:
            raise WorkflowError(f"Expected JSON/XML report outputs are missing: {details}")
        return summary

    def _resolve_phase_model(self, phase: str) -> Optional[str]:
        """Pick the model for an LLM report phase.

        Precedence: explicit global `ai.model` (wins everywhere, back-compat)
        -> the phase-specific override (`ai.raw_model` / `ai.title_model` /
        `ai.one_model`) -> the module DEFAULT_*_MODEL constant.
        """
        if self.config.ai.model:
            return self.config.ai.model
        phase_overrides = {
            "raw": (self.config.ai.raw_model, DEFAULT_RAW_MODEL),
            "title": (self.config.ai.title_model, DEFAULT_TITLE_MODEL),
            "one": (self.config.ai.one_model, DEFAULT_ONE_MODEL),
        }
        override, default = phase_overrides.get(phase, (None, None))
        return override or default

    def _resolve_phase_provider(self, phase: str) -> str:
        """Pick the AI provider for a report phase.

        Precedence: phase-specific override (ai.raw_provider / ai.title_provider
        / ai.one_provider) -> global ai.provider -> "claude" fallback.
        """
        phase_map = {
            "raw":   self.config.ai.raw_provider,
            "title": self.config.ai.title_provider,
            "one":   self.config.ai.one_provider,
        }
        return phase_map.get(phase) or self.config.ai.provider or "claude"

    def _run_agent(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> str:
        agent = build_agent_runner(
            provider=provider if provider is not None else self.config.ai.provider,
            model=model if model is not None else self.config.ai.model,
            timeout_seconds=self.config.ai.timeout_seconds,
            max_budget_usd=self.config.ai.max_budget_usd,
        )
        extra_dirs = []
        for candidate in [
            self._prompt_parent(self.config.ai.raw_prompt_path),
            self._prompt_parent(self.config.ai.title_prompt_path),
            self._prompt_parent(self.config.ai.design_system_path),
            downloads_prompt_dir(),
        ]:
            if candidate and candidate.exists():
                extra_dirs.append(candidate)
        try:
            result = agent.run(system_prompt, user_prompt, cwd=self.repo_root, extra_dirs=extra_dirs)
        except AgentRunnerError as exc:
            raise WorkflowError(str(exc)) from exc
        if not result.success:
            raise WorkflowError(result.error or f"{result.provider} generation failed")
        return sanitize_markdown_output(result.output)

    def _prompt_parent(self, raw_path: Optional[str]) -> Optional[Path]:
        if not raw_path:
            return None
        return Path(raw_path).expanduser().resolve().parent

    def _resolve_prompt_path(self, explicit: Optional[str], candidates: list[Path]) -> Path:
        if explicit:
            path = Path(explicit).expanduser().resolve()
            if not path.exists():
                raise WorkflowError(f"Prompt file not found: {path}")
            return path
        for candidate in candidates:
            candidate = candidate.expanduser()
            if candidate.exists():
                return candidate.resolve()
        raise WorkflowError(
            "Could not resolve a prompt file. Checked: "
            + ", ".join(str(candidate) for candidate in candidates)
        )

    def _build_system_prompt(self, prompt_path: Path, include_design_system: bool) -> str:
        prompt_text = prompt_path.read_text(encoding="utf-8")
        if not include_design_system:
            return prompt_text
        design_text = ""
        explicit = self.config.ai.design_system_path
        if explicit:
            design_path = Path(explicit).expanduser().resolve()
            if not design_path.exists():
                raise WorkflowError(f"Design system file not found: {design_path}")
            design_text = design_path.read_text(encoding="utf-8")
        else:
            default_design = downloads_prompt_dir() / "DESIGN_SYSTEM.md"
            if default_design.exists():
                design_text = default_design.read_text(encoding="utf-8")
        if not design_text:
            return prompt_text
        return (
            f"{prompt_text.strip()}\n\n"
            "--- DESIGN SYSTEM REFERENCE ---\n"
            f"{design_text.strip()}\n"
        )

    def _save_prompt_bundle(self, prefix: str, system_prompt: str, user_prompt: str) -> None:
        (self.prompts_dir / f"{prefix}_system_prompt.md").write_text(system_prompt, encoding="utf-8")
        (self.prompts_dir / f"{prefix}_user_prompt.md").write_text(user_prompt, encoding="utf-8")

    def _load_legal_descriptions(self) -> dict[str, dict[str, Any]]:
        """Load legal_descriptions.json sidecar; empty dict if missing."""
        path = self.legal_descriptions_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    _DOT_BOILERPLATE_MARKERS = (
        "BORROWER COVENANTS",
        "UNIFORM COVENANTS",
        "Security Instrument",
        "Fannie Mae",
        "Freddie Mac",
        "Form 3005",
        "Ellie Mae",
    )

    def _pick_canonical_legal_doc(self, sidecar: dict[str, dict[str, Any]]) -> Optional[str]:
        """Pick the deed whose verbatim legal block is the MOST COMPLETE.

        Heuristic: drop entries with >=3 deed-of-trust boilerplate markers
        (those captured mortgage covenants rather than Exhibit A), require
        the block to mention "LOT" (real legal descriptions reference a
        Lot/Parcel/Tract), then pick the longest. Ties broken by APN length
        (prefer entries that include the check digit).
        """
        candidates: list[tuple[int, int, str]] = []
        for doc_num, entry in sidecar.items():
            if not isinstance(entry, dict):
                continue
            block = (entry.get("legal_description_verbatim") or "").strip()
            if not block:
                continue
            junk = sum(1 for m in self._DOT_BOILERPLATE_MARKERS if m in block)
            if junk >= 3:
                continue
            if "LOT" not in block.upper() and "PARCEL" not in block.upper():
                continue
            apn_len = len((entry.get("apn_verbatim") or "").strip())
            candidates.append((len(block), apn_len, doc_num))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][2]

    def _build_verbatim_legal_block(self) -> str:
        """Build the prompt-injected verbatim Legal Descriptions section.

        Returns an empty string when the sidecar is absent or empty so
        existing prompt formatting is preserved for old cases.
        """
        sidecar = self._load_legal_descriptions()
        if not sidecar:
            return ""
        canonical_doc = self._pick_canonical_legal_doc(sidecar)
        rows: list[str] = []
        for doc_num, entry in sidecar.items():
            if not isinstance(entry, dict):
                continue
            block = (entry.get("legal_description_verbatim") or "").strip()
            apn = (entry.get("apn_verbatim") or "").strip()
            if not block and not apn:
                continue
            doc_type = entry.get("document_type") or "Deed"
            anchor = entry.get("anchor_used") or ""
            source = entry.get("extraction_source") or ""
            marker = "★ CANONICAL — RENDER VERBATIM AS LEGAL DESCRIPTION\n" if doc_num == canonical_doc else ""
            rows.append(
                f"{marker}"
                f"Doc {doc_num} ({doc_type}):\n"
                f"APN: {apn or '[not found in source]'}\n"
                f"Anchor: {anchor}  |  Source: {source}\n"
                "Legal Description (verbatim):\n"
                "```\n"
                f"{block or '[not extractable]'}\n"
                "```\n"
            )
        if not rows:
            return ""
        canonical_note = (
            "The entry marked ★ CANONICAL is the MOST COMPLETE extracted "
            "legal description (longest non-boilerplate block referencing a "
            "Lot/Parcel). In the final report's Legal Description section, "
            "copy that block verbatim — character-for-character, including "
            "any chain-of-title language, property address, and the full "
            "APN with check digit. Do not substitute a shorter version even "
            "if it came from the vesting deed.\n\n"
            if canonical_doc else ""
        )
        return (
            "## Verbatim Legal Descriptions (DO NOT MODIFY)\n"
            "Source: documents_found.json -> legal_descriptions.json\n"
            "These blocks were deterministically extracted from the source "
            "PDFs and are authoritative. Reproduce them character-for-"
            "character in any Legal Description section. Do not paraphrase, "
            "do not add Markdown emphasis, do not drop APN check digits.\n\n"
            + canonical_note
            + "\n".join(rows)
            + "\n"
        )

    def _build_phase1_verifications_block(self) -> str:
        """Render `phase1_verifications.json` (subject-address verifier +
        released-mortgage linker output) as a markdown block for the RAW /
        Title user prompts. Empty string if the sidecar doesn't exist —
        keeps backwards compatibility with pre-0522 case folders.
        """
        verif_path = self.case_dir / "phase1_verifications.json"
        if not verif_path.exists():
            return ""
        try:
            data = json.loads(verif_path.read_text(encoding="utf-8"))
        except Exception:
            return ""

        block = "## Phase-1 Verifications (computed sidecar)\n\n"

        # Subject-address verification — Tony's #4 directive (NLP-verify property address).
        addr_results = data.get("subject_address_verification", {})
        if addr_results:
            subject = data.get("subject_address", "")
            block += f"Subject property: `{subject}`\n\n"
            block += "Per-doc subject-property address match (from extracted PDF text):\n\n"
            block += "| Doc # | Status | Similarity | Extracted Address |\n|---|---|---|---|\n"
            for doc_num, r in sorted(addr_results.items()):
                marker = (
                    "✓ MATCH" if r.get("status") == "MATCH"
                    else "⚠ AMBIGUOUS" if r.get("status") == "AMBIGUOUS"
                    else "✗ NO_MATCH"
                )
                addr_disp = (r.get("extracted_address") or "")[:80].replace("|", "\\|").replace("\n", " ")
                block += f"| {doc_num} | {marker} | {r.get('similarity', 0):.2f} | {addr_disp} |\n"
            block += (
                "\n**Reporting rule (Tony #4 directive):** Any document whose extracted "
                "address is `NO_MATCH` against the subject is for a DIFFERENT property. "
                "Such a document MUST NOT be used as the vesting deed. If a candidate "
                "vesting deed has `NO_MATCH` you MUST flag it as `[CRITICAL] Wrong-Property "
                "Match` in the RAW Critical Issues section and trigger a RED LIGHT for "
                "human review. AMBIGUOUS results require a human-readable note explaining "
                "the partial match.\n\n"
            )

        # Released-mortgage classification — Tony's #6 directive (release linker).
        mtg_classifications = data.get("mortgage_classifications", {})
        if mtg_classifications:
            block += "Per-mortgage classification (released/modified/subordinate/open):\n\n"
            block += "| Mortgage Doc # | Status | Linked Satisfactions / Modifications |\n|---|---|---|\n"
            for doc_num, mc in sorted(mtg_classifications.items()):
                status = mc.get("status", "?")
                links = []
                for r in mc.get("release_chain", []) or []:
                    sat_num = (
                        r.get("satisfaction")
                        or r.get("satisfaction_doc_number")
                        or "?"
                    )
                    sat_type = (
                        r.get("type") or r.get("satisfaction_type") or "?"
                    )
                    links.append(f"satisfied by {sat_num} ({sat_type})")
                for m in mc.get("related_modifications", []) or []:
                    links.append(f"modified by {m}")
                links_disp = "; ".join(links) if links else "—"
                block += f"| {doc_num} | {status} | {links_disp} |\n"
            block += (
                "\n**Reporting rule (Tony #6 directive):** Mortgages classified `released` "
                "MUST appear in the `Released / Satisfied` section of the report, NOT the "
                "`Open Mortgages` section. The linked satisfaction/release document number "
                "MUST be cited as evidence. Mortgages classified `modified` should be "
                "grouped with their parent mortgage and the modification noted.\n\n"
            )

        # Recovered-from-not_needed audit — Tony's #5 directive (examine
        # every document). Lists satisfactions/releases that the upstream
        # search-side filter dropped but the audit module re-recovered
        # by content classification + Book/Page or MIN cross-reference.
        recovered = data.get("recovered_from_not_needed", [])
        if recovered:
            block += "Recovered documents from `not_needed/` (audit splice — Tony #5):\n\n"
            block += "| Doc # | Type | Match Method | Targeted Mortgage | Confidence |\n|---|---|---|---|---|\n"
            for rd in sorted(recovered, key=lambda r: r.get("doc_number", "")):
                doc_n = rd.get("doc_number", "?")
                rtype = rd.get("classified_type", "?")
                method = rd.get("match_method", "?")
                target = rd.get("target_mortgage_doc", "?")
                conf = rd.get("classification_confidence", 0.0)
                conf_disp = f"{float(conf):.2f}" if conf is not None else "?"
                block += (
                    f"| {doc_n} | {rtype} | {method} | {target} | {conf_disp} |\n"
                )
            block += (
                "\n**Reporting rule (Tony #5 directive):** These documents were initially "
                "filtered out by the recorder's search-index column (Broward F9 bug — the "
                "`document_type` column holds the grantee name, not the legal doctype). "
                "They have been re-classified by content and linked to their target mortgages "
                "via Book/Page, MERS MIN, instrument number, or original principal amount. "
                "Treat them as first-class members of the corpus — the mortgages they target "
                "MUST be marked `released` in the Released / Satisfied section.\n\n"
            )

        # Vesting-chain walker — OnE v1.7 §2 Prior-Vesting chain guard.
        # Detects same-day refi-cycle interim deeds and identifies the
        # tenure-commencing walk target. v1.7 renders the full chain and
        # annotates the walk target; it does not hide the interim deed.
        walker = data.get("vesting_chain_walker") or {}
        if walker and walker.get("status"):
            wstatus = walker.get("status", "?")
            current_v = walker.get("current_vesting_doc_number") or "?"
            candidate_v = walker.get("candidate_prior_vesting_doc_number") or "?"
            walk_target = walker.get("recommended_walk_target_doc_number") or "—"
            block += (
                "Vesting-chain walker (Prior-Vesting guard):\n\n"
                "| Field | Value |\n|---|---|\n"
                f"| Walker status | `{wstatus}` |\n"
                f"| Current Vesting | `{current_v}` |\n"
                f"| Candidate Prior Vesting | `{candidate_v}` |\n"
                f"| Candidate age (days from Current) | `{walker.get('candidate_age_days_from_current', '?')}` |\n"
                f"| Party-overlap reason | {walker.get('candidate_party_overlap_reason') or '—'} |\n"
                f"| **Recommended walk target** | `{walk_target}` |\n"
                f"| Walk-target reason | {walker.get('recommended_walk_target_reason') or '—'} |\n"
                f"| Walked-past doc numbers | `{', '.join(walker.get('walked_past_doc_numbers') or []) or '—'}` |\n\n"
            )
            if wstatus == "SAME_DAY_REFI_INTERIM_DETECTED":
                block += (
                    "**Reporting rule (OnE v1.7 §2 — prior-vesting chain guard):** "
                    f"The candidate Prior Vesting `{candidate_v}` is a same-day refi-cycle "
                    "interim or estate-planning conveyance (party overlap with Current Vesting "
                    "inside the 30-day refi window). The OnE Prior Vesting section MUST render "
                    f"the full newest-to-oldest chain including `{candidate_v}`, continue to "
                    f"`{walk_target}`, and annotate `{walk_target}` as the tenure-commencing "
                    "instrument. The prior-owner name sweep target is the grantor of the "
                    "current owner's tenure-commencing acquisition, not the interim-deed grantor.\n\n"
                )
            elif wstatus == "AMBIGUOUS":
                block += (
                    "**Reporting rule (OnE v1.7 §2):** Walker is AMBIGUOUS — candidate is inside "
                    "the refi window but no party overlap was detected. Render the chain and add "
                    "an inline operator-review note on the ambiguous row.\n\n"
                )

        # NOC termination bundles — OnE v1.6 §7 (2026-06-03). Each NOC's
        # termination status (BUNDLE_COMPLETE_CH713 / PARTIAL_* / NO_TERMINATION_FOUND)
        # drives the §7 Status field language and the FL §713.13/§713.132 citations.
        bundles = data.get("noc_termination_bundles") or []
        if bundles:
            block += "NOC termination bundles (FL §713 lien-window analysis):\n\n"
            block += (
                "| NOC | NOT | Final Affidavit | Waiver(s) | Status | Contractor |\n"
                "|---|---|---|---|---|---|\n"
            )
            for b in bundles:
                waivers_disp = ", ".join(b.get("lien_waiver_doc_numbers") or []) or "—"
                block += (
                    f"| `{b.get('noc_doc_number', '?')}` "
                    f"| `{b.get('not_doc_number') or '—'}` "
                    f"| `{b.get('final_affidavit_doc_number') or '—'}` "
                    f"| `{waivers_disp}` "
                    f"| `{b.get('status', '?')}` "
                    f"| {b.get('contractor_name') or '—'} |\n"
                )
            block += (
                "\n**Reporting rule (OnE v1.6 §7 — NOC + Final Affidavit + Waiver-of-Lien chain):** "
                "When status is `BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED`, the OnE §7 Status "
                "field reads `TERMINATED — Ch.713 window definitively closed. NOT + Final Affidavit "
                "+ Waiver(s) all recorded within bundle window. No remaining lien exposure under "
                "FL Ch. 713.` For PARTIAL_* statuses, cite which components are missing and what "
                "operator-verify steps remain. For `NO_TERMINATION_FOUND`, cite the FL §713.13 "
                "one-year expiration and the construction-lien window's open-through date. Do NOT "
                "treat a bare NOT (PARTIAL_NOT_ONLY_UNRATIFIED) as a complete termination — "
                "subcontractors with pre-existing performance may still have a §713 window.\n\n"
            )

        # Title-Affidavit identity-disclaimer pairings — OnE v1.6 §4 (2026-06-03).
        # Surfaces recorded Title Affidavits that disclaim being the debtor in
        # judgments cited by OR Book/Page references.
        pairings = data.get("title_affidavit_pairings") or []
        if pairings:
            block += "Title-Affidavit identity-disclaimer pairings:\n\n"
            block += (
                "| Affidavit Doc # | Recorded | Affiant | Disclaimed OR refs | Matched Judgments |\n"
                "|---|---|---|---|---|\n"
            )
            for p in pairings:
                or_refs = "; ".join(p.get("disclaimed_or_book_page_refs") or []) or "—"
                matched = ", ".join(p.get("matched_judgment_doc_numbers") or []) or "—"
                block += (
                    f"| `{p.get('affidavit_doc_number', '?')}` "
                    f"| {p.get('affidavit_recording_date') or '—'} "
                    f"| {p.get('affiant_name') or '—'} "
                    f"| {or_refs} "
                    f"| `{matched}` |\n"
                )
            block += (
                "\n**Reporting rule (OnE v1.6 §4 — Title-Affidavit identity-disclaimer pairing):** "
                "When a Title Affidavit disclaims OR Book/Page references AND those refs match "
                "judgment documents in this corpus, replace the bare `None of record` bullet in §4 "
                "with an inline disclaimer narrative citing the affidavit instrument # + affiant + "
                "disclaimed OR refs. This surfaces the disclaimer audit trail instead of leaving "
                "it hidden in §7 (Peter Bodonyi 2026-06-03 pattern).\n\n"
            )

        if block == "## Phase-1 Verifications (computed sidecar)\n\n":
            return ""  # nothing useful — don't add an empty header
        return block

    def _build_raw_user_prompt(self) -> str:
        documents = self._load_documents_found()
        metadata = load_metadata(self.case_dir)
        # Merge extraction-summary examined_and_excluded flags into document
        # dicts so _build_document_excerpt_block can skip docs that have no PDF
        # (e.g. when strict_downloads=False and all downloads failed).
        if self.extraction_summary_path().exists():
            try:
                extraction = json.loads(self.extraction_summary_path().read_text(encoding="utf-8"))
                exc_map = {
                    item["document_number"]: item.get("examined_and_excluded", False)
                    for item in extraction.get("documents", [])
                    if "document_number" in item
                }
                documents = [
                    {**doc, "examined_and_excluded": exc_map.get(doc.get("document_number", ""), doc.get("examined_and_excluded", False))}
                    for doc in documents
                ]
            except Exception:
                pass
        excerpts = self._build_document_excerpt_block(documents, metadata)
        verbatim_block = self._build_verbatim_legal_block()
        phase1_verifications_block = self._build_phase1_verifications_block()

        # Tax lookup status sidecar is mandatory context. We always emit a
        # block here even when the lookup is disabled/skipped/failed so the
        # LLM cannot silently treat empty tax data as verified.
        tax_status: dict[str, Any] = {}
        if self.tax_lookup_status_path().exists():
            try:
                tax_status = json.loads(self.tax_lookup_status_path().read_text(encoding="utf-8"))
            except Exception:
                tax_status = {"status": "unknown", "notes": "Status sidecar exists but is unparseable."}
        elif not self.config.fetch_tax:
            tax_status = {
                "status": "disabled",
                "reason": "fetch_tax_disabled",
                "notes": "Tax lookup disabled by workflow config.",
            }
        else:
            tax_status = {
                "status": "missing",
                "reason": "no_status_sidecar",
                "notes": "Tax lookup status sidecar is absent. Treat tax as NOT VERIFIED.",
            }

        # Defensive: scrub any legacy "Supported: [...]" / "not supported"
        # text that may have leaked into the sidecar from older runs.
        tax_status = _sanitize_legacy_tax_text(tax_status)

        is_verified = tax_status.get("status") == "success"
        tax_status_header = (
            "## Tax Lookup Status\n\n"
            f"- Verification State: {'VERIFIED' if is_verified else 'TAX STATUS NOT VERIFIED'}\n"
            f"- Status: {tax_status.get('status', 'missing')}\n"
            f"- Reason: {tax_status.get('reason', 'n/a')}\n"
            f"- Notes: {tax_status.get('notes', '')}\n\n"
            "```json\n"
            f"{json.dumps(tax_status, indent=2)}\n"
            "```\n\n"
        )

        tax_block = tax_status_header
        tax_path = self.case_dir / f"tax_{self.config.safe_owner}.json"
        if is_verified and tax_path.exists():
            try:
                tax_data = json.loads(tax_path.read_text(encoding="utf-8"))
                # Project to canonical fields only. Excludes any stale
                # error/data_source/notes text from prior failed runs.
                canonical = _canonical_tax_payload_for_prompt(tax_data)
                tax_block += (
                    "## Tax & Property Lookup (JSON)\n\n"
                    "```json\n"
                    f"{json.dumps(canonical, indent=2)}\n"
                    "```\n\n"
                )
            except Exception:
                pass
        elif not is_verified:
            tax_block += (
                "\n> IMPORTANT: Tax data is NOT VERIFIED. The Phase 4 / Tax section "
                "of the RAW report MUST contain the literal phrase `TAX STATUS NOT VERIFIED` "
                "and MUST NOT label tax as paid, current, or verified.\n\n"
            )

        # MANDATORY OUTPUT CONTRACT — placed last so it has primacy over any
        # softer header guidance in the external system prompt. The downstream
        # validator (`RAW_REQUIRED_SECTIONS`) and PDF/Title renderers depend on
        # these exact H2 headers in this exact order. Letter-based section
        # headers (`## A.`, `## B.`, etc.) MUST appear only as sub-sections
        # nested WITHIN a phase, never as top-level H2s.
        output_contract = (
            "================================================================\n"
            "MANDATORY OUTPUT CONTRACT — READ BEFORE WRITING A SINGLE LINE\n"
            "================================================================\n\n"
            "You MUST structure your output with these exact H2 section "
            "headers, in this exact order, spelled exactly as shown:\n\n"
            "## PHASE 1: RECORDER NAME SEARCHES\n"
            "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION\n"
            "## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION\n"
            "## PHASE 4: TAX & PROPERTY LOOKUP\n"
            "## PHASE 5: RAW EXAM REPORT\n\n"
            "Rules:\n"
            "1. All five `## PHASE N:` H2 headers MUST be present, even if a "
            "phase has no data — in that case write the header and a brief "
            "explanation such as `Not applicable for this exam.` or "
            "`No data available — see notes below.`\n"
            "2. You MAY add sub-sections at H3 (`### A. Property Information`, "
            "`### B. Legal Description`, etc.) WITHIN each phase. Letter-, "
            "narrative-, or topic-based H2 headers (e.g. `## A. Property "
            "Information`, `## Deed Chain`, `## Tax Information`) are "
            "PROHIBITED at the top level.\n"
            "3. Do NOT add extra top-level H2 sections such as `## COVER`, "
            "`## SUMMARY`, `## PHASE 6`, `## PHASE 7`, `## FINAL_REPORT.JSON`, "
            "or `## HTML + PDF RENDERING`. Phases 6 and 7 are handled "
            "downstream and MUST NOT appear in this markdown.\n"
            "4. Place the cover/summary content (property info, borrowers, "
            "exam date) as H3 sub-sections inside `## PHASE 5: RAW EXAM "
            "REPORT`, NOT as their own top-level H2.\n"
            "5. The validator will REJECT the report if any of the five "
            "`## PHASE N:` headers is missing or renamed. Any such failure "
            "blocks PDF rendering and downstream Title Examination Notes.\n"
        )

        return (
            "Phases 1-4 of the recorder workflow are already complete.\n"
            "Do not browse the web, do not invent new searches, and do not omit any downloaded instrument.\n"
            "Analyze only the provided recorder search metadata and extracted document text.\n\n"
            f"Owner Name: {self.config.owner_name}\n"
            f"Subject ID: {self.config.subject_id or '[NOT PROVIDED]'}\n"
            f"Property Address Hint: {self.config.property_address or '[NOT PROVIDED]'}\n"
            f"County/State: {self.config.county.title()}, {self.config.state}\n"
            f"Search Range: {self.config.start_date} to {self.config.end_date}\n\n"
            "Recorder Search Inventory (JSON):\n"
            f"{json.dumps(documents, indent=2)}\n\n"
            "Downloaded File Metadata (JSON):\n"
            f"{json.dumps(metadata, indent=2)}\n\n"
            f"{tax_block}"
            f"{verbatim_block}"
            f"{phase1_verifications_block}"
            "Document Text Excerpts:\n"
            f"{excerpts}\n\n"
            f"{output_contract}\n"
            f"{MANDATORY_VERBATIM_RULES}"
        )

    def _build_title_user_prompt(self) -> str:
        raw_markdown = self.raw_markdown_path().read_text(encoding="utf-8")
        verbatim_block = self._build_verbatim_legal_block()
        phase1_verifications_block = self._build_phase1_verifications_block()
        # MANDATORY OUTPUT CONTRACT — mirrors the RAW user-prompt pattern.
        # `TITLE_REQUIRED_SECTIONS` (validated by `render_pdfs`) demands these
        # exact headers; without a hard contract the LLM drifts into prettier
        # but non-conforming variants and PDF rendering rejects the file.
        title_contract = (
            "================================================================\n"
            "MANDATORY OUTPUT CONTRACT — READ BEFORE WRITING A SINGLE LINE\n"
            "================================================================\n\n"
            "Your output MUST start with this exact H1 header on line 1:\n\n"
            "# Abstractor Notes/Chain\n\n"
            "And MUST contain these exact H2 section headers, spelled exactly "
            "as shown (case-insensitive match is allowed but prefer ALL CAPS):\n\n"
            "## TITLE EXAMINATION SUMMARY\n"
            "## CHAIN OF TITLE\n"
            "## LEGAL DESCRIPTION (EXHIBIT A)\n"
            "## DEEDS OF TRUST / MORTGAGES\n"
            "## DOCUMENTS EXAMINED\n\n"
            "Rules:\n"
            "1. The `# Abstractor Notes/Chain` H1 is REQUIRED — it drives the "
            "running page header in the rendered PDF. Do NOT replace it with "
            "`# Title Examination Notes`, `# Subject Owner`, or any other H1.\n"
            "2. The five H2 section headers above are REQUIRED. You may add "
            "extra sections (e.g. `## TAX STATUS`, `## DISCLAIMER`, "
            "`## RECOMMENDATIONS`) but you may not rename or omit the "
            "required five.\n"
            "3. The validator will REJECT the report (blocking PDF rendering) "
            "if the H1 or any of the five required H2 headers is missing.\n"
            "4. `## LEGAL DESCRIPTION (EXHIBIT A)` MUST appear between "
            "`## CHAIN OF TITLE` and `## DEEDS OF TRUST / MORTGAGES`. Its "
            "content MUST be the verbatim Exhibit A block from the most "
            "recent vesting Deed (see Verbatim Legal Descriptions block in "
            "this prompt). Do not paraphrase.\n"
        )
        return (
            "Generate the final Title Examination Notes / Abstractor Notes markdown from the RAW report below.\n"
            "Keep the document professional and complete. Do not add any explanatory preamble.\n\n"
            f"Owner Name: {self.config.owner_name}\n"
            f"Property Address Hint: {self.config.property_address or '[NOT PROVIDED]'}\n"
            f"County/State: {self.config.county.title()}, {self.config.state}\n\n"
            f"{verbatim_block}"
            f"{phase1_verifications_block}"
            "--- BEGIN RAW TWO OWNER SEARCH EXAM ---\n"
            f"{raw_markdown}\n"
            "--- END RAW TWO OWNER SEARCH EXAM ---\n\n"
            f"{title_contract}\n"
            f"{MANDATORY_VERBATIM_RULES}"
        )

    def _build_document_excerpt_block(self, documents: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
        chunks: list[str] = []
        for index, document in enumerate(documents, start=1):
            doc_num = document["document_number"]
            md_entry = metadata.get(doc_num, {}) or {}
            # Examined-and-excluded docs (e.g. statutorily prohibited FL Death
            # Certificates) get a stub entry in the excerpt block so the LLM
            # can itemize them in the report's "INACCESSIBLE / PROHIBITED
            # DOCUMENTS" section per Tony directive #5.
            if (
                document.get("examined_and_excluded")
                or document.get("prohibited")
                or md_entry.get("examined_and_excluded")
                or md_entry.get("prohibited")
            ):
                reason = (
                    document.get("prohibited_reason")
                    or md_entry.get("prohibited_reason")
                    or "examined and excluded — document not downloadable"
                )
                chunks.append(
                    f"### Document {index} (EXAMINED AND EXCLUDED — NO PDF AVAILABLE)\n"
                    f"- Instrument Number: {doc_num}\n"
                    f"- Document Type: {document.get('document_type', '[UNKNOWN]')}\n"
                    f"- Recording Date: {document.get('recording_date', '[UNKNOWN]')}\n"
                    f"- Grantors: {document.get('grantors', '')}\n"
                    f"- Grantees: {document.get('grantees', '')}\n"
                    f"- Exclusion Reason: {reason}\n\n"
                    f"[No document body available — list under INACCESSIBLE / PROHIBITED DOCUMENTS.]\n"
                )
                continue
            filename = md_entry.get("filename")
            if not filename:
                raise WorkflowError(f"No downloaded filename found for document {doc_num}")
            extracted_path = self.case_dir / f"{Path(filename).stem}_extracted.md"
            if not extracted_path.exists():
                raise WorkflowError(f"Missing extracted markdown for {filename}: {extracted_path}")
            text = extracted_path.read_text(encoding="utf-8")
            clipped = text[: self.config.max_document_chars]
            chunks.append(
                f"### Document {index}\n"
                f"- Instrument Number: {doc_num}\n"
                f"- Filename: {filename}\n"
                f"- Document Type: {document.get('document_type', '[UNKNOWN]')}\n"
                f"- Recording Date: {document.get('recording_date', '[UNKNOWN]')}\n"
                f"- Grantors: {document.get('grantors', '')}\n"
                f"- Grantees: {document.get('grantees', '')}\n\n"
                f"{clipped}\n"
            )
        return "\n".join(chunks)

    def _validate_markdown_file(
        self,
        path: Path,
        required_sections: list[str],
        raise_on_failure: bool,
    ) -> dict[str, Any]:
        if not path.exists():
            summary = {"success": False, "error": f"Missing markdown file: {path.name}"}
            if raise_on_failure:
                raise WorkflowError(summary["error"])
            return summary
        content = path.read_text(encoding="utf-8")
        summary = self._validate_markdown_content(content, required_sections, label=path.name)
        if raise_on_failure and not summary["success"]:
            raise WorkflowError(f"Markdown validation failed for {path.name}: {summary}")
        return summary

    @staticmethod
    def _validate_markdown_content(content: str, required_sections: list[str], label: str) -> dict[str, Any]:
        upper = content.upper()
        missing = [section for section in required_sections if section.upper() not in upper]
        return {
            "success": not missing,
            "label": label,
            "missing_sections": missing,
            "length": len(content),
        }

    def _extract_pdf(self, pdf_path: Path) -> dict[str, Any]:
        document = fitz.open(pdf_path)
        page_sections: list[str] = [f"# DOCUMENT: {pdf_path.name}", ""]
        total_chars = 0
        ocr_used = False

        try:
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                method = "native"
                if (
                    len(text) < self.config.min_page_text_chars
                    and self.config.use_ocr_fallback
                    and pytesseract is not None
                    and Image is not None
                ):
                    matrix = fitz.Matrix(300 / 72, 300 / 72)
                    pixmap = page.get_pixmap(matrix=matrix)
                    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                    try:
                        text = pytesseract.image_to_string(image).strip()
                    except Exception as _ocr_exc:
                        print(
                            f"[OCR] page {page_index} skipped — "
                            f"{type(_ocr_exc).__name__}: {str(_ocr_exc)[:120]}",
                            flush=True,
                        )
                        text = "[OCR FAILED — PAGE SKIPPED]"
                    method = "ocr"
                    ocr_used = True
                total_chars += len(text)
                page_sections.extend(
                    [
                        f"## Page {page_index} ({method})",
                        text or "[NO TEXT EXTRACTED]",
                        "",
                    ]
                )
        finally:
            document.close()

        return {
            "markdown": "\n".join(page_sections),
            "total_chars": total_chars,
            "ocr_used": ocr_used,
        }

    @staticmethod
    def _sortable_recording_date(recording_date: Optional[str]) -> datetime:
        if not recording_date:
            return datetime.min
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
            try:
                return datetime.strptime(recording_date, fmt)
            except ValueError:
                continue
        return datetime.min

    @staticmethod
    def _document_year(document: dict[str, Any]) -> str:
        doc_num = document.get("document_number", "")
        if len(doc_num) >= 4 and doc_num[:4].isdigit():
            return doc_num[:4]
        recording_date = document.get("recording_date", "")
        match = re.search(r"(20\d{2}|19\d{2})", recording_date)
        if match:
            return match.group(1)
        return datetime.now().strftime("%Y")
