from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


class AgentRunnerError(RuntimeError):
    """Raised when an external AI CLI cannot complete a generation step."""


@dataclass
class AgentRunResult:
    success: bool
    output: str
    provider: str
    command: list[str]
    stdout: str
    stderr: str
    error: Optional[str] = None


def sanitize_markdown_output(text: str) -> str:
    """Remove common fence wrappers and trim whitespace."""
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


class BaseAgentRunner:
    provider_name = "unknown"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        max_budget_usd: Optional[float] = None,
    ):
        self.model = model
        self.timeout_seconds = timeout_seconds
        # Runaway-cost guard. The subprocess `timeout_seconds` already caps
        # wall-clock per call; this caps spend so a model that loops on tool
        # calls is aborted (fail-fast) instead of grinding for hours. None
        # disables the cap. Enforced via `claude -p --max-budget-usd` ONLY.
        # `codex exec` has NO budget flag, so the cap cannot be enforced on the
        # Codex path — CodexCliRunner emits a one-time warning when a budget is
        # set so the no-op is visible rather than silent (the `timeout_seconds`
        # wall-clock cap is the only spend bound there).
        self.max_budget_usd = max_budget_usd

    @staticmethod
    def _combine_prompt(system_prompt: str, user_prompt: str) -> str:
        return (
            "SYSTEM INSTRUCTIONS:\n"
            f"{system_prompt.strip()}\n\n"
            "USER REQUEST:\n"
            f"{user_prompt.strip()}\n\n"
            "OUTPUT CONTRACT:\n"
            "- Return only the final markdown document.\n"
            "- Do not wrap the output in code fences.\n"
            "- Do not add commentary before or after the markdown.\n"
        )

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        raise NotImplementedError


class ClaudeCliRunner(BaseAgentRunner):
    provider_name = "claude"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        cli_path: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
        resolved = cli_path or shutil.which("claude")
        if not resolved:
            raise AgentRunnerError("Claude CLI was not found on PATH.")
        self.cli_path = resolved

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        prompt = self._combine_prompt(system_prompt, user_prompt)

        # On Windows, passing the full prompt as a -p argument causes
        # [WinError 206] when the combined command string exceeds the OS limit
        # (~32 767 chars). Pipe via stdin instead: write the prompt to a temp
        # file in the system temp dir (short path) and feed it to the process.
        import tempfile
        import platform

        cmd = [
            self.cli_path,
            "--print",
            "--allowedTools",
            "",   # no tools — all context is in the prompt; tool calls waste time and money
        ]
        # Per-phase model selection. Previously self.model was stored but
        # never forwarded, so every report ran on the CLI default (Opus
        # tier). Forward it so RAW can stay on Opus while Title/OnE drop to
        # Sonnet. Accepts an alias ("opus"/"sonnet") or a full model id.
        if self.model:
            cmd.extend(["--model", self.model])
        if self.max_budget_usd is not None and self.max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self.max_budget_usd)])

        env = os.environ.copy()
        env["PATH"] = f"{Path(self.cli_path).parent}:{env.get('PATH', '')}"

        # Write prompt to a temp file so stdin piping works even on Windows
        # where NamedTemporaryFile cannot be read while open.
        prompt_file = Path(tempfile.gettempdir()) / "titlepro_agent_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        try:
            with open(prompt_file, encoding="utf-8") as stdin_fh:
                result = subprocess.run(
                    cmd,
                    stdin=stdin_fh,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    cwd=str(cwd),
                    env=env,
                )
        except subprocess.TimeoutExpired as exc:
            raise AgentRunnerError(
                f"Claude generation timed out after {self.timeout_seconds} seconds"
            ) from exc
        finally:
            try:
                prompt_file.unlink(missing_ok=True)
            except PermissionError:
                # Windows holds the stdin handle briefly after subprocess exits;
                # the temp file is overwritten on the next run anyway.
                pass

        output = sanitize_markdown_output(result.stdout or "")
        success = result.returncode == 0 and bool(output)
        return AgentRunResult(
            success=success,
            output=output,
            provider=self.provider_name,
            command=cmd,
            stdout=result.stdout,
            stderr=result.stderr,
            error=None if success else (result.stderr or "Claude returned no markdown output"),
        )


class AnthropicApiRunner(BaseAgentRunner):
    """Calls the Anthropic Messages API directly — no subprocess, no tool calls, predictable cost."""

    provider_name = "anthropic_api"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        api_key: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(model=model, timeout_seconds=timeout_seconds, max_budget_usd=max_budget_usd)
        # Priority: explicit arg > env var > secrets.json
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or self._read_secrets_key()

    @staticmethod
    def _read_secrets_key() -> Optional[str]:
        try:
            secrets_path = Path(__file__).parent.parent.parent.parent / "config" / "secrets.json"
            return json.loads(secrets_path.read_text(encoding="utf-8")).get("ANTHROPIC_API_KEY")
        except Exception:
            return None

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        try:
            import anthropic
        except ImportError:
            raise AgentRunnerError(
                "anthropic package not installed. Run: pip install anthropic"
            )

        if not self._api_key:
            raise AgentRunnerError(
                "No ANTHROPIC_API_KEY found. Set it in config/secrets.json or env."
            )

        model = self.model or "claude-sonnet-4-6"
        client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=float(self.timeout_seconds),
        )

        message = client.messages.create(
            model=model,
            max_tokens=16384,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        output = "".join(
            block.text for block in message.content if hasattr(block, "text")
        ).strip()

        success = bool(output)
        return AgentRunResult(
            success=success,
            output=output,
            provider=self.provider_name,
            command=[f"anthropic.messages.create(model={model})"],
            stdout=output,
            stderr="",
            error=None if success else "Anthropic API returned empty response",
        )


class GoogleAIRunner(BaseAgentRunner):
    """Calls Google AI Studio (Gemini) API directly — no subprocess, no tool calls."""

    provider_name = "google_ai"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        api_key: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(model=model, timeout_seconds=timeout_seconds, max_budget_usd=max_budget_usd)
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY") or self._read_secrets_key()

    @staticmethod
    def _read_secrets() -> dict:
        try:
            secrets_path = Path(__file__).parent.parent.parent.parent / "config" / "secrets.json"
            return json.loads(secrets_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _read_secrets_key() -> Optional[str]:
        return GoogleAIRunner._read_secrets().get("GOOGLE_API_KEY")

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        try:
            import google.generativeai as genai
        except ImportError:
            raise AgentRunnerError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )

        if not self._api_key:
            raise AgentRunnerError(
                "No GOOGLE_API_KEY found. Set it in config/secrets.json or env."
            )

        import re as _re
        import time as _time

        import os as _os
        model_name = self.model or "gemini-2.0-flash"
        # Prefer service account JSON (bypasses free-tier API key quota limits)
        _sa_json = self._read_secrets().get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if _sa_json and _os.path.exists(_sa_json):
            try:
                from google.oauth2 import service_account as _sa
                _creds = _sa.Credentials.from_service_account_file(
                    _sa_json,
                    scopes=["https://www.googleapis.com/auth/generative-language"],
                )
                genai.configure(credentials=_creds)
            except Exception as _sa_exc:
                print(f"[Gemini] Service account load failed ({_sa_exc}), falling back to API key", flush=True)
                genai.configure(api_key=self._api_key)
        elif self._api_key:
            genai.configure(api_key=self._api_key)
        else:
            raise AgentRunnerError("No GOOGLE_API_KEY or GOOGLE_SERVICE_ACCOUNT_JSON found in secrets.json")
        model_obj = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
        )

        _max_retries = 5
        _attempt = 0
        while True:
            try:
                response = model_obj.generate_content(
                    user_prompt,
                    generation_config=genai.GenerationConfig(max_output_tokens=16384),
                )
                break  # success
            except Exception as _exc:
                _msg = str(_exc)
                _is_429 = "429" in _msg or "ResourceExhausted" in type(_exc).__name__ or "quota" in _msg.lower()
                if _is_429 and _attempt < _max_retries:
                    # Parse "Please retry in X.Xs" from the error message
                    _delay_match = _re.search(r"retry in\s+([\d.]+)s", _msg, _re.IGNORECASE)
                    _delay = float(_delay_match.group(1)) + 2 if _delay_match else min(30 * (2 ** _attempt), 120)
                    print(f"[Gemini] 429 rate-limit on attempt {_attempt + 1} — waiting {_delay:.1f}s before retry…", flush=True)
                    _time.sleep(_delay)
                    _attempt += 1
                    continue
                raise

        output = (response.text or "").strip()
        success = bool(output)
        return AgentRunResult(
            success=success,
            output=output,
            provider=self.provider_name,
            command=[f"google.generativeai.generate_content(model={model_name})"],
            stdout=output,
            stderr="",
            error=None if success else "Google AI returned empty response",
        )


class GroqAIRunner(BaseAgentRunner):
    """Calls Groq API (LLaMA / Mixtral) — very fast inference, no tool calls."""

    provider_name = "groq_ai"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        api_key: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(model=model, timeout_seconds=timeout_seconds, max_budget_usd=max_budget_usd)
        self._api_key = api_key or os.environ.get("GROQ_API_KEY") or self._read_secrets_key()

    @staticmethod
    def _read_secrets_key() -> Optional[str]:
        try:
            secrets_path = Path(__file__).parent.parent.parent.parent / "config" / "secrets.json"
            return json.loads(secrets_path.read_text(encoding="utf-8")).get("GROQ_API_KEY")
        except Exception:
            return None

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        try:
            from groq import Groq
        except ImportError:
            raise AgentRunnerError(
                "groq package not installed. Run: pip install groq"
            )

        if not self._api_key:
            raise AgentRunnerError(
                "No GROQ_API_KEY found. Set it in config/secrets.json or env."
            )

        model_name = self.model or "llama-3.3-70b-versatile"
        client = Groq(api_key=self._api_key, timeout=float(self.timeout_seconds))

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=16384,
            temperature=0.2,
        )

        output = (response.choices[0].message.content or "").strip()
        success = bool(output)
        return AgentRunResult(
            success=success,
            output=output,
            provider=self.provider_name,
            command=[f"groq.chat.completions.create(model={model_name})"],
            stdout=output,
            stderr="",
            error=None if success else "Groq returned empty response",
        )


class CodexCliRunner(BaseAgentRunner):
    provider_name = "codex"

    # Set once a budget-unsupported warning has been emitted, so a multi-phase
    # run that constructs several Codex runners only warns the operator once.
    _budget_warning_emitted = False

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = 900,
        cli_path: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
    ):
        super().__init__(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
        resolved = cli_path or shutil.which("codex")
        if not resolved:
            raise AgentRunnerError("Codex CLI was not found on PATH.")
        self.cli_path = resolved
        # `codex exec` has no spend/budget flag, so `max_budget_usd` cannot be
        # enforced here. Surface that clearly (once) instead of silently
        # ignoring the configured cap. The `timeout_seconds` wall-clock cap
        # still applies and is the only spend bound on the Codex path.
        if (
            self.max_budget_usd is not None
            and self.max_budget_usd > 0
            and not CodexCliRunner._budget_warning_emitted
        ):
            logger.warning(
                "max_budget_usd=%s is set but `codex exec` has no budget flag; "
                "the spend cap is NOT enforced on the Codex provider. Only the "
                "%ss wall-clock timeout bounds Codex runs.",
                self.max_budget_usd,
                self.timeout_seconds,
            )
            CodexCliRunner._budget_warning_emitted = True

    def run(
        self,
        system_prompt: str,
        user_prompt: str,
        cwd: Path,
        extra_dirs: Iterable[Path] = (),
    ) -> AgentRunResult:
        prompt = self._combine_prompt(system_prompt, user_prompt)
        with tempfile.TemporaryDirectory(prefix="titlepro_codex_") as temp_dir:
            output_path = Path(temp_dir) / "last_message.txt"
            cmd = [
                self.cli_path,
                "exec",
                "-",
                "-C",
                str(cwd),
                "-s",
                "read-only",
                "-a",
                "never",
                "--output-last-message",
                str(output_path),
            ]
            if self.model:
                cmd.extend(["-m", self.model])

            seen_dirs: set[Path] = set()
            for extra_dir in extra_dirs:
                resolved = extra_dir.resolve()
                if resolved == cwd.resolve() or resolved in seen_dirs:
                    continue
                seen_dirs.add(resolved)
                cmd.extend(["--add-dir", str(resolved)])

            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=str(cwd),
                )
            except subprocess.TimeoutExpired as exc:
                raise AgentRunnerError(
                    f"Codex generation timed out after {self.timeout_seconds} seconds"
                ) from exc

            output = ""
            if output_path.exists():
                output = sanitize_markdown_output(output_path.read_text(encoding="utf-8"))
            if not output:
                output = sanitize_markdown_output(result.stdout)

            success = result.returncode == 0 and bool(output)
            return AgentRunResult(
                success=success,
                output=output,
                provider=self.provider_name,
                command=cmd,
                stdout=result.stdout,
                stderr=result.stderr,
                error=None if success else (result.stderr or "Codex returned no markdown output"),
            )


def build_agent_runner(
    provider: str,
    model: Optional[str],
    timeout_seconds: int,
    max_budget_usd: Optional[float] = None,
) -> BaseAgentRunner:
    normalized = provider.strip().lower()
    # Groq (LLaMA / Mixtral) — set AI_ENGINE=groq in secrets.json to activate.
    if normalized in ("groq", "groq_ai"):
        return GroqAIRunner(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
    # Google AI Studio — set AI_ENGINE=google in secrets.json to activate.
    if normalized in ("google", "google_ai", "gemini"):
        return GoogleAIRunner(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
    # Direct Anthropic API — no subprocess, no tool calls, predictable cost.
    # Triggered by AI_ENGINE=claude (or CLAUDE_MODE=api) in secrets.json.
    if normalized in ("api", "anthropic", "anthropic_api"):
        return AnthropicApiRunner(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
    if normalized == "claude":
        return ClaudeCliRunner(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
    if normalized == "codex":
        return CodexCliRunner(
            model=model,
            timeout_seconds=timeout_seconds,
            max_budget_usd=max_budget_usd,
        )
    raise AgentRunnerError(f"Unsupported AI provider: {provider}")
