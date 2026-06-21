"""
Claude Client Abstraction - Supports both CLI (local) and API (server) modes.

Configuration in secrets.json:
{
    "CLAUDE_MODE": "cli" | "api",      // Default: "cli"
    "ANTHROPIC_API_KEY": "sk-ant-...", // Required if CLAUDE_MODE is "api"
    "CLAUDE_CLI_PATH": "/path/to/claude" // Optional, default: /Users/ag/.local/bin/claude
}

Usage:
    from titlepro.api.claude_client import get_claude_client, ClaudeResponse

    client = get_claude_client()
    response = client.run(prompt, allowed_tools=['Read', 'Write'], cwd='/path/to/dir')

    if response.success:
        print(response.output)
    else:
        print(response.error)
"""

import json
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Try to import anthropic SDK (only needed for API mode)
try:
    import anthropic
    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    ANTHROPIC_SDK_AVAILABLE = False


@dataclass
class ClaudeResponse:
    """Standardized response from Claude (CLI or API)."""
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None


class ClaudeClientBase(ABC):
    """Abstract base class for Claude clients."""

    @abstractmethod
    def run(
        self,
        prompt: str,
        allowed_tools: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        timeout: int = 300,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None
    ) -> ClaudeResponse:
        """Run a prompt through Claude and return the response."""
        pass

    @property
    @abstractmethod
    def mode(self) -> str:
        """Return the mode name ('cli' or 'api')."""
        pass


class ClaudeCLIClient(ClaudeClientBase):
    """Claude CLI client - runs Claude as a subprocess."""

    def __init__(self, cli_path: str = '/Users/ag/.local/bin/claude'):
        self.cli_path = cli_path
        if not Path(cli_path).exists():
            raise FileNotFoundError(f"Claude CLI not found at {cli_path}")

    @property
    def mode(self) -> str:
        return 'cli'

    def run(
        self,
        prompt: str,
        allowed_tools: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        timeout: int = 300,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None
    ) -> ClaudeResponse:
        """Run prompt via Claude CLI."""
        try:
            # For CLI mode with system prompt, prepend it to the user prompt
            effective_prompt = prompt
            if system_prompt:
                effective_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{prompt}"

            cmd = [self.cli_path, '-p', effective_prompt]

            if allowed_tools:
                cmd.extend(['--allowedTools', ','.join(allowed_tools)])

            env = os.environ.copy()
            env['PATH'] = f"{Path(self.cli_path).parent}:{env.get('PATH', '')}"

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env
            )

            if result.returncode == 0:
                return ClaudeResponse(
                    success=True,
                    output=result.stdout,
                    raw_response={'returncode': 0, 'stdout': result.stdout, 'stderr': result.stderr}
                )
            else:
                return ClaudeResponse(
                    success=False,
                    error=result.stderr or f"CLI exited with code {result.returncode}",
                    output=result.stdout,
                    raw_response={'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                )

        except subprocess.TimeoutExpired:
            return ClaudeResponse(success=False, error=f"CLI timed out after {timeout} seconds")
        except FileNotFoundError:
            return ClaudeResponse(success=False, error=f"Claude CLI not found at {self.cli_path}")
        except Exception as e:
            return ClaudeResponse(success=False, error=str(e))


class ClaudeAPIClient(ClaudeClientBase):
    """Claude API client - uses Anthropic SDK directly."""

    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-20250514'):
        if not ANTHROPIC_SDK_AVAILABLE:
            raise ImportError(
                "anthropic SDK not installed. Run: pip install anthropic"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    @property
    def mode(self) -> str:
        return 'api'

    def run(
        self,
        prompt: str,
        allowed_tools: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        timeout: int = 300,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None
    ) -> ClaudeResponse:
        """
        Run prompt via Anthropic API.

        Note: allowed_tools and cwd are CLI-specific and ignored in API mode.
        For file operations, include file contents in the prompt.
        """
        try:
            # For API mode, we use a simple message completion
            # Tool use would require more complex implementation
            kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            message = self.client.messages.create(**kwargs)

            # Extract text from response
            output_text = ""
            for block in message.content:
                if hasattr(block, 'text'):
                    output_text += block.text

            return ClaudeResponse(
                success=True,
                output=output_text,
                raw_response={
                    'id': message.id,
                    'model': message.model,
                    'stop_reason': message.stop_reason,
                    'usage': {
                        'input_tokens': message.usage.input_tokens,
                        'output_tokens': message.usage.output_tokens
                    }
                }
            )

        except anthropic.APIConnectionError as e:
            return ClaudeResponse(success=False, error=f"API connection error: {e}")
        except anthropic.RateLimitError as e:
            return ClaudeResponse(success=False, error=f"Rate limit exceeded: {e}")
        except anthropic.APIStatusError as e:
            return ClaudeResponse(success=False, error=f"API error {e.status_code}: {e.message}")
        except Exception as e:
            return ClaudeResponse(success=False, error=str(e))


# Global client instance (lazy loaded)
_client: Optional[ClaudeClientBase] = None
_config_loaded = False


def load_config() -> dict:
    """Load configuration from secrets.json."""
    # Look for secrets.json in project root
    possible_paths = [
        Path(__file__).resolve().parent.parent.parent.parent / 'secrets.json',  # project root
        Path(__file__).resolve().parent / 'secrets.json',  # api folder
        Path.cwd() / 'secrets.json',  # current directory
    ]

    for path in possible_paths:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                continue

    return {}


def get_claude_client(force_mode: Optional[str] = None) -> ClaudeClientBase:
    """
    Get the Claude client based on configuration.

    Args:
        force_mode: Override config and force 'cli' or 'api' mode

    Returns:
        ClaudeClientBase instance (CLI or API client)

    Raises:
        ValueError: If configuration is invalid
        ImportError: If API mode requested but anthropic SDK not installed
        FileNotFoundError: If CLI mode requested but claude CLI not found
    """
    global _client, _config_loaded

    config = load_config()
    mode = force_mode or config.get('CLAUDE_MODE', 'cli').lower()

    # Check if we need to recreate client (mode changed)
    if _client is not None and _client.mode == mode:
        return _client

    if mode == 'api':
        api_key = config.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Add it to secrets.json or set as environment variable."
            )
        model = config.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        _client = ClaudeAPIClient(api_key=api_key, model=model)

    elif mode == 'cli':
        cli_path = config.get('CLAUDE_CLI_PATH', '/Users/ag/.local/bin/claude')
        _client = ClaudeCLIClient(cli_path=cli_path)

    else:
        raise ValueError(f"Invalid CLAUDE_MODE: {mode}. Must be 'cli' or 'api'.")

    _config_loaded = True
    return _client


def reset_client():
    """Reset the global client (useful for testing or config changes)."""
    global _client, _config_loaded
    _client = None
    _config_loaded = False


# Convenience function for simple prompts
def run_claude(
    prompt: str,
    allowed_tools: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    timeout: int = 300,
    force_mode: Optional[str] = None,
    max_tokens: int = 4096,
    system_prompt: Optional[str] = None
) -> ClaudeResponse:
    """
    Convenience function to run a Claude prompt.

    Args:
        prompt: The prompt to send to Claude
        allowed_tools: List of tools to allow (CLI mode only)
        cwd: Working directory (CLI mode only)
        timeout: Timeout in seconds
        force_mode: Override config and force 'cli' or 'api' mode
        max_tokens: Max tokens for API response (default 4096)
        system_prompt: System prompt for API mode / prepended for CLI mode

    Returns:
        ClaudeResponse with success status and output/error
    """
    client = get_claude_client(force_mode=force_mode)
    return client.run(prompt, allowed_tools=allowed_tools, cwd=cwd, timeout=timeout,
                      max_tokens=max_tokens, system_prompt=system_prompt)
