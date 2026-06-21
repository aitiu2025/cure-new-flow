"""Unit tests for per-phase model selection (#1, 2026-06-14).

RAW report stays on Opus 4.8; Title/OnE default to Sonnet. An explicit global
`ai.model` overrides every phase (back-compat). The ClaudeCliRunner must now
actually forward `--model` (previously stored but never passed) and the
runaway-cost `--max-budget-usd` cap.
"""
from __future__ import annotations

import logging
from pathlib import Path

from titlepro.automation import pipeline as P
from titlepro.automation.agent_runners import ClaudeCliRunner, CodexCliRunner


class _StubPipeline:
    """Minimal stand-in exposing `.config.ai` for `_resolve_phase_model`."""

    def __init__(self, ai: P.AIConfig):
        self.config = type("C", (), {"ai": ai})()


def _resolve(ai: P.AIConfig, phase: str):
    return P.RecorderAutomationPipeline._resolve_phase_model(_StubPipeline(ai), phase)


def test_default_mapping_raw_opus_title_sonnet():
    ai = P.AIConfig.from_dict({})
    assert _resolve(ai, "raw") == P.DEFAULT_RAW_MODEL == "claude-opus-4-8"
    assert _resolve(ai, "title") == P.DEFAULT_TITLE_MODEL == "claude-sonnet-4-6"
    assert _resolve(ai, "one") == P.DEFAULT_ONE_MODEL == "claude-sonnet-4-6"


def test_global_model_wins_everywhere():
    ai = P.AIConfig.from_dict({"model": "claude-haiku-4-5-20251001"})
    assert _resolve(ai, "raw") == "claude-haiku-4-5-20251001"
    assert _resolve(ai, "title") == "claude-haiku-4-5-20251001"


def test_per_phase_override_beats_default_but_not_global():
    ai = P.AIConfig.from_dict({"title_model": "claude-opus-4-8"})
    assert _resolve(ai, "title") == "claude-opus-4-8"
    # raw still falls to its default
    assert _resolve(ai, "raw") == "claude-opus-4-8"  # default RAW is opus anyway
    ai2 = P.AIConfig.from_dict({"raw_model": "claude-haiku-4-5-20251001"})
    assert _resolve(ai2, "raw") == "claude-haiku-4-5-20251001"


def test_budget_default_present_and_overridable():
    assert P.AIConfig.from_dict({}).max_budget_usd == P.DEFAULT_AGENT_MAX_BUDGET_USD
    assert P.AIConfig.from_dict({"max_budget_usd": None}).max_budget_usd is None
    assert P.AIConfig.from_dict({"max_budget_usd": 2.5}).max_budget_usd == 2.5


def test_claude_runner_emits_model_and_budget_flags(monkeypatch):
    """The runner must forward --model and --max-budget-usd into the argv."""
    captured = {}

    class _Done:
        returncode = 0
        stdout = "ok markdown"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Done()

    # Avoid PATH dependency on a real `claude` binary.
    runner = ClaudeCliRunner.__new__(ClaudeCliRunner)
    runner.model = "claude-opus-4-8"
    runner.timeout_seconds = 900
    runner.max_budget_usd = 5.0
    runner.cli_path = "/usr/bin/claude"

    import titlepro.automation.agent_runners as ar

    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    from pathlib import Path

    result = runner.run("sys", "user", cwd=Path("."))
    assert result.success is True
    cmd = captured["cmd"]
    assert "--model" in cmd and "claude-opus-4-8" in cmd
    assert "--max-budget-usd" in cmd and "5.0" in cmd


def test_claude_runner_omits_flags_when_unset(monkeypatch):
    captured = {}

    class _Done:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Done()

    runner = ClaudeCliRunner.__new__(ClaudeCliRunner)
    runner.model = None
    runner.timeout_seconds = 900
    runner.max_budget_usd = None
    runner.cli_path = "/usr/bin/claude"

    import titlepro.automation.agent_runners as ar

    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    from pathlib import Path

    runner.run("sys", "user", cwd=Path("."))
    cmd = captured["cmd"]
    assert "--model" not in cmd
    assert "--max-budget-usd" not in cmd


# --- P3: max_budget_usd silently no-ops for the Codex provider ---------------

def test_codex_warns_once_when_budget_set(caplog):
    """`codex exec` has no budget flag, so a configured cap cannot be enforced.
    The runner must emit a VISIBLE warning when a budget is set (not silently
    drop it), and must NOT crash the run."""
    # Reset the one-time guard so the warning can fire in this test.
    CodexCliRunner._budget_warning_emitted = False
    with caplog.at_level(logging.WARNING, logger="titlepro.automation.agent_runners"):
        CodexCliRunner(
            model="gpt-5.1-codex",
            timeout_seconds=900,
            cli_path="/usr/bin/codex",
            max_budget_usd=5.0,
        )
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("max_budget_usd" in m and "codex exec" in m for m in msgs), msgs


def test_codex_no_warning_when_budget_unset(caplog):
    CodexCliRunner._budget_warning_emitted = False
    with caplog.at_level(logging.WARNING, logger="titlepro.automation.agent_runners"):
        CodexCliRunner(
            model="gpt-5.1-codex",
            timeout_seconds=900,
            cli_path="/usr/bin/codex",
            max_budget_usd=None,
        )
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_codex_budget_command_has_no_budget_flag(monkeypatch, tmp_path):
    """The Codex argv must not contain a (nonexistent) budget flag, but the run
    must still succeed — the no-op is warned, not enforced or crashed."""
    CodexCliRunner._budget_warning_emitted = False
    captured = {}

    class _Done:
        returncode = 0
        stdout = "ok markdown"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # Codex writes its output to --output-last-message; emulate that.
        out_idx = cmd.index("--output-last-message") + 1
        Path(cmd[out_idx]).write_text("ok markdown", encoding="utf-8")
        return _Done()

    import titlepro.automation.agent_runners as ar

    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    runner = CodexCliRunner(
        model="gpt-5.1-codex",
        timeout_seconds=900,
        cli_path="/usr/bin/codex",
        max_budget_usd=5.0,
    )
    result = runner.run("sys", "user", cwd=tmp_path)
    assert result.success is True
    cmd = captured["cmd"]
    # No budget flag is forwarded to `codex exec` (it has none); only -m <model>.
    assert "--max-budget-usd" not in cmd
    assert not any(str(tok).startswith("--max-budget") for tok in cmd)
    assert "-m" in cmd and "gpt-5.1-codex" in cmd
