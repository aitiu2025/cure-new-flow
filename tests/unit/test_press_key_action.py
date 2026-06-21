"""Unit tests for the `press_key` recipe action (added 2026-05-13).

Covers:
- Schema validator accepts `press_key` actions (with / without `selector`,
  with / without `key`, with `wait_after_ms`).
- Schema validator rejects malformed `press_key` (non-string `key`,
  non-numeric `wait_after_ms`).
- The runner's async `_execute_step` dispatches a `press_key` step against
  a mock page / locator without raising.

The runner test uses an asyncio event loop + lightweight async mocks; it
does NOT touch a real Playwright browser (CI has no browser binaries
installed).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from titlepro.tax.playwright_runner import _execute_step
from titlepro.tax.recipe_schema import ALLOWED_ACTIONS, validate_recipe


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _wrap_step(step: dict) -> dict:
    """Wrap a single navigation step in a minimal valid recipe shell."""
    return {
        "county": "test",
        "platform": "playwright_form",
        "base_url": "https://example.com/",
        "authoritative_source_hosts": ["example.com"],
        "navigation_steps": [step],
    }


def test_schema_allows_press_key_action_name():
    assert "press_key" in ALLOWED_ACTIONS


def test_schema_accepts_press_key_with_selector_and_key():
    recipe = _wrap_step(
        {
            "action": "press_key",
            "selector": "#mat-input-1",
            "key": "Enter",
            "wait_after_ms": 2000,
        }
    )
    errors = validate_recipe(recipe, source_label="press_key_full.json")
    assert errors == [], f"unexpected errors: {errors}"


def test_schema_accepts_press_key_without_selector():
    # press_key with no selector is legal — presses on whatever has focus.
    recipe = _wrap_step({"action": "press_key", "key": "Tab"})
    errors = validate_recipe(recipe, source_label="press_key_no_sel.json")
    assert errors == [], f"unexpected errors: {errors}"


def test_schema_accepts_press_key_without_explicit_key():
    # `key` defaults to "Enter" in the runner; the schema must accept its
    # omission without flagging an error.
    recipe = _wrap_step({"action": "press_key", "selector": "#mat-input-1"})
    errors = validate_recipe(recipe, source_label="press_key_default_key.json")
    assert errors == [], f"unexpected errors: {errors}"


def test_schema_rejects_press_key_with_non_string_key():
    recipe = _wrap_step({"action": "press_key", "key": 42})
    errors = validate_recipe(recipe, source_label="press_key_bad_key.json")
    assert any("press_key" in e and "key" in e for e in errors), (
        f"expected a key-type error, got: {errors}"
    )


def test_schema_rejects_press_key_with_empty_key():
    recipe = _wrap_step({"action": "press_key", "key": "   "})
    errors = validate_recipe(recipe, source_label="press_key_empty_key.json")
    assert any("press_key" in e and "key" in e for e in errors), (
        f"expected a key-type error, got: {errors}"
    )


def test_schema_rejects_press_key_with_bad_wait_after_ms():
    recipe = _wrap_step(
        {
            "action": "press_key",
            "selector": "#x",
            "key": "Enter",
            "wait_after_ms": "soon",
        }
    )
    errors = validate_recipe(recipe, source_label="press_key_bad_wait.json")
    assert any("wait_after_ms" in e for e in errors), (
        f"expected a wait_after_ms error, got: {errors}"
    )


# ---------------------------------------------------------------------------
# Runner dispatch — exercise _execute_step against a mock page
# ---------------------------------------------------------------------------


class _AsyncCall:
    """Records args and is awaitable."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return None


class _MockLocator:
    def __init__(self) -> None:
        self.press = _AsyncCall()
        self.click = _AsyncCall()
        self.first = self  # `.first` returns self so .press is reachable


class _MockPage:
    """Bare minimum surface of a Playwright Page used by `press_key`."""

    def __init__(self) -> None:
        self._locator = _MockLocator()
        self.keyboard = SimpleNamespace(press=_AsyncCall())
        self.wait_for_timeout = _AsyncCall()
        self.url = "https://example.com/test"

    def locator(self, selector: str) -> _MockLocator:
        # Same locator object every time so tests can inspect call args.
        self._locator.last_selector = selector
        return self._locator


def _run(coro):
    """Drive a coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


def test_runner_executes_press_key_with_selector():
    page = _MockPage()
    step = {
        "action": "press_key",
        "selector": "#mat-input-1",
        "key": "Enter",
        "wait_after_ms": 50,
    }

    _run(_execute_step(page, step, {"apn": "259-34-015"}, "259-34-015", []))

    # press was dispatched on the locator with the requested key.
    assert page._locator.press.calls, "press_key did not call locator.press"
    args, kwargs = page._locator.press.calls[0]
    assert args[0] == "Enter"
    # And the post-press settle delay was applied via wait_for_timeout.
    assert page.wait_for_timeout.calls, "wait_after_ms did not trigger wait_for_timeout"
    assert page.wait_for_timeout.calls[0][0][0] == 50


def test_runner_executes_press_key_default_enter():
    page = _MockPage()
    step = {"action": "press_key", "selector": "#x"}
    _run(_execute_step(page, step, {}, "ignored", []))
    args, _ = page._locator.press.calls[0]
    # No `key` field provided -> runner falls back to "Enter".
    assert args[0] == "Enter"


def test_runner_executes_press_key_without_selector_uses_page_keyboard():
    page = _MockPage()
    step = {"action": "press_key", "key": "Tab"}
    _run(_execute_step(page, step, {}, "ignored", []))
    # No selector -> uses page-level keyboard.press
    assert page.keyboard.press.calls, "page.keyboard.press should be called when no selector"
    args, _ = page.keyboard.press.calls[0]
    assert args[0] == "Tab"
    # And we should NOT have used the locator.
    assert not page._locator.press.calls


def test_runner_press_key_propagates_error_when_not_optional():
    page = _MockPage()

    class _BoomLocator(_MockLocator):
        def __init__(self) -> None:
            super().__init__()

            async def _boom(*a, **kw):
                raise RuntimeError("element not found")

            self.press = _boom  # type: ignore[assignment]

    page._locator = _BoomLocator()
    step = {"action": "press_key", "selector": "#nope", "key": "Enter"}
    with pytest.raises(RuntimeError):
        _run(_execute_step(page, step, {}, "ignored", []))


def test_runner_press_key_swallows_error_when_optional():
    page = _MockPage()

    class _BoomLocator(_MockLocator):
        def __init__(self) -> None:
            super().__init__()

            async def _boom(*a, **kw):
                raise RuntimeError("element not found")

            self.press = _boom  # type: ignore[assignment]

    page._locator = _BoomLocator()
    step = {
        "action": "press_key",
        "selector": "#nope",
        "key": "Enter",
        "optional": True,
    }
    # Must not raise.
    _run(_execute_step(page, step, {}, "ignored", []))
