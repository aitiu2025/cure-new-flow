import json

import pytest

from titlepro.automation.checkpoints import CaptchaCheckpointRequired, checkpoint_sessions
from titlepro.automation.agent_runners import sanitize_markdown_output
from titlepro.automation.pipeline import RecorderAutomationPipeline, WorkflowConfig, WorkflowError
from titlepro.search.recorder.counties.adapters.tyler_adapter import TylerAdapter


def test_sanitize_markdown_output_strips_code_fences():
    raw = "```markdown\n# Hello\n\nBody\n```"
    assert sanitize_markdown_output(raw) == "# Hello\n\nBody"


def test_workflow_config_uses_search_names_when_search_requests_missing():
    config = WorkflowConfig.from_dict(
        {
            "owner_name": "Example Owner",
            "county": "orange",
            "search_names": ["Owner Example", "Coowner Example"],
        }
    )
    assert [item.name for item in config.search_requests] == ["Owner Example", "Coowner Example"]


def test_workflow_config_accepts_explicit_apn():
    config = WorkflowConfig.from_dict(
        {
            "owner_name": "Example Owner",
            "county": "fresno",
            "apn": "455-113-24",
        }
    )
    assert config.apn == "455-113-24"


def test_markdown_validator_reports_missing_sections():
    summary = RecorderAutomationPipeline._validate_markdown_content(
        "# RAW Two-Owner Title Search Examination Report\n\n## PHASE 1: RECORDER NAME SEARCHES",
        [
            "## PHASE 1: RECORDER NAME SEARCHES",
            "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION",
        ],
        label="raw",
    )
    assert summary["success"] is False
    assert summary["missing_sections"] == ["## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION"]


class _FakeCaptchaFrame:
    pass


class _FakeDriver:
    current_url = "https://example.test/search"

    def __init__(self):
        self.quit_called = False

    def find_elements(self, by, selector):
        return [_FakeCaptchaFrame()]

    def execute_script(self, script):
        return ""

    def quit(self):
        self.quit_called = True


class _FakeSolver:
    def __init__(self):
        self.called = False

    def solve_recaptcha_v2(self, site_key, page_url):
        self.called = True
        return "token"


def test_tyler_captcha_raises_resumable_checkpoint_and_ignores_solver():
    adapter = TylerAdapter(
        {
            "county_name": "Fresno",
            "captcha_required": True,
            "captcha_type": "recaptcha_v2",
            "manual_captcha_timeout_seconds": 900,
            "allow_automated_captcha_solver": False,
        }
    )
    fake_solver = _FakeSolver()
    adapter.set_captcha_solver(fake_solver)
    adapter.driver = _FakeDriver()

    with pytest.raises(CaptchaCheckpointRequired) as exc_info:
        adapter._handle_captcha()

    checkpoint = exc_info.value.to_dict()
    assert checkpoint["type"] == "captcha"
    assert checkpoint["resume_token"]
    assert checkpoint["details"]["manual_only"] is True
    assert fake_solver.called is False
    assert adapter.captcha_solver is None

    checkpoint_sessions.complete(checkpoint["resume_token"], close_resource=True)
    assert adapter.driver is None


def test_tax_lookup_missing_apn_raises_and_writes_skipped_status(tmp_path, monkeypatch):
    monkeypatch.setattr("titlepro.automation.pipeline.DOWNLOAD_DIR", tmp_path)
    config = WorkflowConfig.from_dict(
        {
            "owner_name": "Example Owner",
            "county": "fresno",
            "output_folder_name": "Example_Owner",
            "fetch_tax": True,
        }
    )
    pipeline = RecorderAutomationPipeline(config)

    with pytest.raises(WorkflowError, match="Tax lookup requires an APN"):
        pipeline.tax_lookup()

    status = json.loads(pipeline.tax_lookup_status_path().read_text(encoding="utf-8"))
    assert status["success"] is False
    assert status["status"] == "skipped"
    assert status["reason"] == "missing_apn"
