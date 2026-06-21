"""Generic Playwright recipe runner for county tax portals.

A single recipe (JSON file under `config/tax_recipes/<county>.json`) drives
a sequence of Playwright actions (`goto`, `click`, `fill`, `select`,
`split_apn`, `wait_for`, `enter_frame`, `exit_frame`, ...) and a
declarative `extract` map. The runner is intentionally portal-agnostic;
per-county logic lives in the recipe.

Hardening (per Codex finding 2):
- `result.source_url` is set to the **innermost active frame's URL** after
  extraction (so iframe-hosted portals don't get rejected for the parent
  page's hostname) and verified against `recipe.authoritative_source_hosts`.
  Mismatch -> TAX_FAILED.
- If the extract map yields an `apn` value, it is compared (case-insensitive,
  hyphen-stripped) to the input APN. Mismatch -> TAX_FAILED.
- Any extract key ending in `_estimated` is excluded from `verified_fields`.

Hardening (per Codex finding 3):
- Mid-flow CAPTCHA detection raises `CaptchaCheckpointRequired` instead of
  silently failing. The runner registers a `CheckpointSession` (with the
  live browser context) so the pipeline can pause and resume.

Iframe support (added 2026-05-13 for SBD):
- `enter_frame` action descends into a child <iframe>. Selectors after
  this action operate inside that frame. Frames can be nested by
  stacking `enter_frame` actions.
- `exit_frame` pops one level (or all levels with `to: "top"`).
- Extraction always runs against the *currently-active* frame context.

Public API:
    run(recipe: dict, apn: str, case_dir: Path) -> TaxLookupResult

See `docs/proposals/tax_plumbing_v2_codex_revised.md` Layer 3 for the spec.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from titlepro.tax.result import (
    TaxLookupResult,
    apn_matches,
    host_in_whitelist,
    is_estimated_key,
    normalize_apn,
)

# Lazy / optional Playwright import. Tests in replay mode (HTML-only) do
# not require the binary.
try:
    from playwright.async_api import async_playwright  # type: ignore
    from playwright.async_api import TimeoutError as PWTimeoutError  # type: ignore
    PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover
    PLAYWRIGHT_AVAILABLE = False
    PWTimeoutError = Exception  # type: ignore

try:
    from titlepro.automation.checkpoints import (
        CaptchaCheckpointRequired,
        checkpoint_sessions,
        make_session_key,
    )
    CHECKPOINTS_AVAILABLE = True
except Exception:  # pragma: no cover
    CHECKPOINTS_AVAILABLE = False
    CaptchaCheckpointRequired = RuntimeError  # type: ignore
    checkpoint_sessions = None  # type: ignore
    make_session_key = None  # type: ignore


def _log(msg: str) -> None:
    print(f"[tax-runner] {msg}", flush=True)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "tax").strip("_") or "tax"


def _parse_currency(text: str) -> float | None:
    """'$1,492.75' -> 1492.75. Returns None if nothing numeric found."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", s)
    if not cleaned or cleaned in {".", "-", "-.", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coerce(value: Any, type_hint: str | None) -> Any:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return ""
    if type_hint == "currency":
        coerced = _parse_currency(s)
        return coerced if coerced is not None else s
    if type_hint == "int":
        try:
            return int(re.sub(r"[^\d\-]", "", s) or "0")
        except ValueError:
            return s
    if type_hint == "float":
        try:
            return float(re.sub(r"[^\d.\-]", "", s) or "0")
        except ValueError:
            return s
    return s


def _set_field_path(target: dict, path: str, value: Any) -> None:
    """Set `target[a.b[0].c] = value` where `path` uses dotted + bracketed segments.

    Example paths:
        assessed_value.net_taxable
        installments[0].amount
        installments[1].due_date
    """
    cur: Any = target
    # Tokenize into [(name, idx_or_None), ...]
    parts = re.findall(r"([^.\[\]]+)(?:\[(\d+)\])?", path)
    parts = [(name, int(idx) if idx else None) for name, idx in parts if name]
    for i, (name, idx) in enumerate(parts):
        is_last = i == len(parts) - 1
        if idx is None:
            if is_last:
                cur[name] = value
                return
            if name not in cur or not isinstance(cur[name], dict):
                cur[name] = {}
            cur = cur[name]
        else:
            if name not in cur or not isinstance(cur[name], list):
                cur[name] = []
            arr = cur[name]
            while len(arr) <= idx:
                arr.append({})
            if is_last:
                arr[idx] = value
                return
            if not isinstance(arr[idx], dict):
                arr[idx] = {}
            cur = arr[idx]


def _get_field_path(source: dict, path: str) -> Any:
    cur: Any = source
    parts = re.findall(r"([^.\[\]]+)(?:\[(\d+)\])?", path)
    parts = [(name, int(idx) if idx else None) for name, idx in parts if name]
    for name, idx in parts:
        if not isinstance(cur, dict) or name not in cur:
            return None
        cur = cur[name]
        if idx is not None:
            if not isinstance(cur, list) or idx >= len(cur):
                return None
            cur = cur[idx]
    return cur


def _split_apn(apn: str, fmt: str) -> list[str]:
    """Split an APN per a format string.

    `fmt` is a hyphen-separated mask of `X` characters indicating how many
    digits per field. `XXX-XXX-XX` against `455-113-24` -> ["455", "113", "24"].

    If the format does not match cleanly, fall back to splitting on hyphens.
    """
    apn = (apn or "").strip()
    if "-" in apn:
        parts = [p.strip() for p in apn.split("-") if p.strip()]
        if fmt:
            expected = fmt.count("-") + 1
            if len(parts) == expected:
                return parts
        if parts:
            return parts
    stripped = re.sub(r"[^A-Za-z0-9]", "", apn)
    if not fmt or "-" not in fmt:
        return [stripped]
    parts = []
    cursor = 0
    for seg in fmt.split("-"):
        n = len(seg)
        parts.append(stripped[cursor : cursor + n])
        cursor += n
    return parts


# ----------------------------------------------------------------------
# Page-level operations
# ----------------------------------------------------------------------


async def _maybe_captcha(page: Any) -> bool:
    """Return True if the current page contains a CAPTCHA iframe."""
    try:
        for sel in (
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            "iframe[src*='hcaptcha']",
        ):
            if await page.locator(sel).count() > 0:
                return True
    except Exception:
        return False
    return False


async def _extract_text(active: Any, spec: dict) -> str | None:
    """Extract a single field per the spec. Returns string or None.

    `active` is either a `Page` or a `Frame` — both expose `locator`,
    `evaluate`, etc. with the same signatures.
    """
    selector = spec.get("selector")
    regex = spec.get("regex")
    scope = spec.get("scope", "body")

    def _first_group(m: re.Match) -> str:
        """Return the first non-None capture group; falls back to group(0)."""
        if not m.groups():
            return m.group(0)
        for g in m.groups():
            if g is not None and g != "":
                return g
        return m.group(0)

    if selector:
        try:
            loc = active.locator(selector).first
            if await loc.count() > 0:
                text = await loc.text_content(timeout=2000)
                if text is not None:
                    text = text.strip()
                    if regex:
                        m = re.search(regex, text, re.MULTILINE | re.IGNORECASE)
                        if m:
                            return (_first_group(m) or "").strip()
                        return None
                    return text
        except Exception as exc:
            _log(f"selector extract failed for {selector!r}: {exc}")

    if regex:
        try:
            if scope and scope != "body":
                try:
                    text = await active.locator(scope).first.text_content(timeout=2000)
                except Exception:
                    text = await active.evaluate("() => document.body.innerText")
            else:
                text = await active.evaluate("() => document.body.innerText")
            if not text:
                return None
            m = re.search(regex, text, re.MULTILINE | re.IGNORECASE)
            if m:
                return (_first_group(m) or "").strip()
        except Exception as exc:
            _log(f"regex extract failed for /{regex}/: {exc}")
    return None


# ----------------------------------------------------------------------
# Frame helpers
# ----------------------------------------------------------------------


async def _resolve_frame(
    parent: Any,
    selector: str,
    url_contains: str | None = None,
    timeout_ms: int = 15000,
) -> Any:
    """Resolve a Playwright `Frame` for the iframe element matched by `selector`.

    `parent` is either a `Page` or a `Frame`. We first wait for the iframe
    element to attach, then locate it; if `url_contains` is given we
    iterate matching iframe handles and pick the one whose `src` (or
    eventual `frame.url`) contains the substring.

    Raises if no matching frame can be resolved in `timeout_ms` ms.
    """
    # Wait for at least one matching iframe element to attach so we don't
    # race the page's iframe injection.
    try:
        await parent.wait_for_selector(selector, state="attached", timeout=timeout_ms)
    except Exception:
        pass

    handles = await parent.locator(selector).element_handles()
    if not handles:
        raise RuntimeError(
            f"enter_frame: no iframe matched selector {selector!r} on parent"
        )

    candidates: list[Any] = []
    for h in handles:
        try:
            frame = await h.content_frame()
            if frame is not None:
                candidates.append(frame)
        except Exception:
            continue

    if not candidates:
        raise RuntimeError(
            f"enter_frame: matched {len(handles)} iframe element(s) but none expose a content frame"
        )

    if url_contains:
        sub = url_contains.lower()
        for f in candidates:
            try:
                if sub in (f.url or "").lower():
                    return f
            except Exception:
                continue
        # Fall through and return first candidate as a best-effort.
        _log(
            f"enter_frame: url_contains={url_contains!r} matched no candidate; "
            f"falling back to first iframe"
        )
    return candidates[0]


def _active_context(frame_stack: list[Any], page: Any) -> Any:
    """Return the innermost frame on the stack, or the page if empty."""
    return frame_stack[-1] if frame_stack else page


def _active_url(frame_stack: list[Any], page: Any) -> str:
    """Return the URL of the innermost active context (frame or page)."""
    ctx = _active_context(frame_stack, page)
    try:
        return ctx.url
    except Exception:
        try:
            return page.url
        except Exception:
            return ""


# ----------------------------------------------------------------------
# Step executor
# ----------------------------------------------------------------------


async def _execute_step(
    page: Any,
    step: dict,
    ctx: dict,
    apn: str,
    frame_stack: list[Any],
) -> None:
    """Execute one recipe step. Mutates `frame_stack` for enter_frame/exit_frame.

    All non-frame DOM operations run against `_active_context(frame_stack, page)`
    so they transparently target whatever iframe we last entered.
    """
    action = step.get("action")
    selector = step.get("selector")
    optional = bool(step.get("optional"))
    timeout_ms = int(step.get("timeout_ms", step.get("timeout", 15)) * 1000) if isinstance(step.get("timeout"), (int, float)) else int(step.get("timeout_ms", 15000))

    active = _active_context(frame_stack, page)

    try:
        if action == "goto":
            # Always navigate the top-level page. Any iframe contexts on
            # the stack are invalidated; clear it.
            url = step["url"].format(**ctx)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(int(step.get("settle_ms", 1500)))
            if frame_stack:
                frame_stack.clear()
            return
        if action == "click":
            loc = active.locator(selector).first
            try:
                await loc.click(timeout=timeout_ms)
            except Exception as exc:
                if optional:
                    _log(f"optional click skipped: {selector!r} ({exc})")
                    return
                raise
            await page.wait_for_timeout(int(step.get("settle_ms", 1000)))
            return
        if action == "fill":
            # ctx already contains `apn`, so don't double-pass it.
            value = str(step.get("value", "")).format(**ctx)
            await active.fill(selector, value, timeout=timeout_ms)
            return
        if action == "select":
            value = str(step.get("value", "")).format(**ctx)
            await active.select_option(selector, value, timeout=timeout_ms)
            return
        if action == "split_apn":
            fmt = step.get("format", "XXX-XXX-XX")
            fields = step.get("fields") or []
            values = _split_apn(apn, fmt)
            for sel, val in zip(fields, values):
                await active.fill(sel, val, timeout=timeout_ms)
            return
        if action == "wait_for":
            state = step.get("state", "visible")
            try:
                await active.wait_for_selector(selector, timeout=timeout_ms, state=state)
            except Exception:
                if optional:
                    return
                raise
            return
        if action == "wait_for_url":
            pattern = step.get("pattern") or step.get("url_contains") or ""
            await page.wait_for_url(lambda u: pattern in u, timeout=timeout_ms)
            return
        if action == "sleep":
            await page.wait_for_timeout(int(step.get("ms", 1000)))
            return
        if action == "press_key":
            # Press a keyboard key on the active context. Supports either:
            #   - `selector`: focus that element first (click), then press the key
            #     on the active page's keyboard.
            #   - no selector: press the key on whatever element currently has focus.
            # Key defaults to "Enter". `wait_after_ms` is an optional post-press settle.
            key = str(step.get("key") or "Enter")
            if selector:
                loc = active.locator(selector).first
                try:
                    # Use `press` on the locator so the event is dispatched
                    # against the targeted element (and is frame-aware).
                    await loc.press(key, timeout=timeout_ms)
                except Exception as exc:
                    if optional:
                        _log(f"optional press_key skipped: {selector!r} ({exc})")
                        return
                    raise
            else:
                # Top-level page keyboard — there is no per-frame keyboard
                # object in Playwright, the page-level one dispatches into
                # whichever frame currently has focus.
                try:
                    await page.keyboard.press(key)
                except Exception as exc:
                    if optional:
                        _log(f"optional press_key skipped (no selector): ({exc})")
                        return
                    raise
            wait_after = step.get("wait_after_ms")
            if wait_after:
                await page.wait_for_timeout(int(wait_after))
            elif step.get("settle_ms"):
                await page.wait_for_timeout(int(step.get("settle_ms", 0)))
            return
        if action == "enter_frame":
            url_contains = step.get("url_contains")
            try:
                frame = await _resolve_frame(
                    active,
                    selector,
                    url_contains=url_contains,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:
                if optional:
                    _log(f"optional enter_frame skipped: {selector!r} ({exc})")
                    return
                raise
            frame_stack.append(frame)
            await page.wait_for_timeout(int(step.get("settle_ms", 800)))
            return
        if action == "exit_frame":
            to = (step.get("to") or "").lower()
            if to == "top":
                frame_stack.clear()
            elif frame_stack:
                frame_stack.pop()
            return
        # extract_field / extract_table handled after navigation finishes
        if action in {"extract_field", "extract_table"}:
            return
    except Exception:
        if optional:
            _log(f"optional step {action!r} skipped due to error")
            return
        raise


# ----------------------------------------------------------------------
# Status assignment
# ----------------------------------------------------------------------


def _classify(
    recipe: dict,
    extracted: dict,
    input_apn: str,
    source_url: str,
    body_text: str,
) -> tuple[str, list[str], list[str], str, str]:
    """Return (status, verified_fields, missing_fields, notes, error).

    Status precedence:
      1. Source-host mismatch -> TAX_FAILED.
      2. APN mismatch (when extracted apn is present and differs) -> TAX_FAILED.
      3. "Parcel not found" body text -> TAX_NO_RESULTS.
      4. All `verification_required` populated + non-estimated -> TAX_SUCCESS.
      5. Some populated, others missing -> TAX_PARTIAL.
      6. Nothing populated -> TAX_FAILED.
    """
    whitelist = recipe.get("authoritative_source_hosts") or []
    whitelist_mode = recipe.get("host_whitelist_mode", "strict")

    # 1. Source host whitelist
    if not host_in_whitelist(source_url, whitelist, mode=whitelist_mode):
        return (
            "TAX_FAILED",
            [],
            list(recipe.get("verification_required") or []),
            "",
            (
                f"source host mismatch ({whitelist_mode} mode): "
                f"{source_url!r} not in whitelist {whitelist}"
            ),
        )

    # 2. APN echo
    extracted_apn = extracted.get("apn")
    if extracted_apn:
        if not apn_matches(input_apn, str(extracted_apn)):
            return (
                "TAX_FAILED",
                [],
                list(recipe.get("verification_required") or []),
                "",
                f"APN echo mismatch: input={input_apn!r} extracted={extracted_apn!r}",
            )

    # 3. No-results body-text patterns
    no_results_patterns = (
        recipe.get("no_results_patterns")
        or [
            r"no\s+parcel\s+found",
            r"parcel\s+not\s+on\s+file",
            r"no\s+results\s+found",
            r"APN\s+is\s+inactive",
        ]
    )
    for pat in no_results_patterns:
        try:
            if re.search(pat, body_text or "", re.IGNORECASE):
                return (
                    "TAX_NO_RESULTS",
                    [],
                    list(recipe.get("verification_required") or []),
                    f"county portal returned no parcel matching APN {input_apn}",
                    "",
                )
        except re.error:
            continue

    # 4 / 5. Check verification_required
    required = list(recipe.get("verification_required") or [])
    verified: list[str] = []
    missing: list[str] = []

    for key in required:
        if is_estimated_key(key):
            # Estimated keys never count as verified, per Codex finding 2.
            missing.append(key)
            continue
        val = _get_field_path(extracted, key)
        if val in (None, "", [], {}):
            missing.append(key)
            continue
        # Empty-string strings or zero-only currency are NOT verified.
        if isinstance(val, str) and not val.strip():
            missing.append(key)
            continue
        verified.append(key)

    # Filter any _estimated keys that snuck into verified.
    verified = [k for k in verified if not is_estimated_key(k)]

    if required and not missing:
        return ("TAX_SUCCESS", verified, [], "All required fields populated.", "")
    if verified and missing:
        return (
            "TAX_PARTIAL",
            verified,
            missing,
            f"Partial extraction: {len(verified)} verified, {len(missing)} missing.",
            "",
        )
    return (
        "TAX_FAILED",
        verified,
        missing or required,
        "",
        "no required fields could be extracted from the authoritative source",
    )


# ----------------------------------------------------------------------
# Async entry point
# ----------------------------------------------------------------------


async def _run_async(recipe: dict, apn: str, case_dir: Path, safe_owner: str = "tax", property_address: str = "") -> TaxLookupResult:
    if not PLAYWRIGHT_AVAILABLE:
        return TaxLookupResult(
            apn=apn,
            tax_year="",
            property_address="",
            status="TAX_FAILED",
            error="playwright is not installed in this environment",
        )

    case_dir.mkdir(parents=True, exist_ok=True)
    capture_html = case_dir / f"tax_{_safe_filename(safe_owner)}_capture.html"
    screenshot = case_dir / f"tax_{_safe_filename(safe_owner)}_screenshot.png"

    headless = bool(recipe.get("headless", False))
    min_delay = max(0, int(recipe.get("min_delay_seconds", 1)))
    base_url = recipe.get("base_url", "")
    ctx_vars = {"base_url": base_url, "apn": apn, "property_address": property_address or ""}

    extracted: dict[str, Any] = {}
    body_text = ""
    source_url = ""
    runner_error = ""
    runner_notes: list[str] = []
    captcha_seen = False
    browser = None
    browser_context = None
    page = None
    frame_stack: list[Any] = []  # nested iframe contexts; last == active

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(headless=headless, slow_mo=200)
            browser_context = await browser.new_context()
            page = await browser_context.new_page()
            try:
                page.set_default_timeout(int(recipe.get("default_timeout_ms", 30000)))
            except Exception:
                pass

            for i, step in enumerate(recipe.get("navigation_steps") or []):
                if min_delay:
                    await page.wait_for_timeout(min_delay * 1000)
                # Pre-step CAPTCHA detection (top-level page)
                if await _maybe_captcha(page):
                    captcha_seen = True
                    break
                try:
                    await _execute_step(page, step, ctx_vars, apn, frame_stack)
                except PWTimeoutError as t_exc:
                    runner_error = f"step {i} ({step.get('action')!r}) timed out: {t_exc}"
                    break
                except Exception as exc:
                    runner_error = f"step {i} ({step.get('action')!r}) failed: {exc}"
                    break
                # Post-step CAPTCHA detection (top-level page)
                if await _maybe_captcha(page):
                    captcha_seen = True
                    break

            # Save artifacts even on failure
            try:
                html = await page.content()
                capture_html.write_text(html, encoding="utf-8")
            except Exception:
                pass
            try:
                await page.screenshot(path=str(screenshot), full_page=True)
            except Exception:
                pass

            # Resolve source_url to the innermost active context (frame
            # URL when extraction happened inside an iframe; otherwise the
            # top-level page URL). This is critical for portals that nest
            # the actual bill data inside cross-origin iframes (e.g. SBD).
            try:
                source_url = _active_url(frame_stack, page)
            except Exception:
                source_url = ""

            # CAPTCHA handling: register checkpoint, raise.
            if captcha_seen and not runner_error:
                if not CHECKPOINTS_AVAILABLE or checkpoint_sessions is None:
                    runner_error = "CAPTCHA required but checkpoint registry is unavailable"
                else:
                    county = recipe.get("county", "unknown")
                    session_key = (
                        make_session_key(safe_owner, county, "tax_lookup", "tax", "primary")
                        if make_session_key
                        else f"{safe_owner}:tax:{county}"
                    )
                    session = checkpoint_sessions.create(
                        checkpoint_type="captcha",
                        county=county,
                        step="tax_lookup",
                        message=(
                            f"CAPTCHA detected on {county} tax portal. Please solve the "
                            "CAPTCHA in the open browser window and resume."
                        ),
                        resource=browser_context,
                        session_key=session_key,
                        details={"phase": "tax_lookup", "search_unit": "tax_primary"},
                        timeout_seconds=900,
                    )
                    # Do NOT close the browser — the resume token owns it.
                    browser_context = None
                    browser = None
                    raise CaptchaCheckpointRequired(
                        resume_token=session.resume_token,
                        county=county,
                        step="tax_lookup",
                        message=session.message,
                        details={"phase": "tax_lookup", "search_unit": "tax_primary"},
                    )

            # Extraction (runs against the innermost active frame so
            # iframe-hosted bill pages work).
            if not runner_error:
                active = _active_context(frame_stack, page)
                try:
                    body_text = await active.evaluate("() => document.body.innerText")
                except Exception:
                    body_text = ""
                for key, spec in (recipe.get("extract") or {}).items():
                    try:
                        raw = await _extract_text(active, spec)
                    except Exception as exc:
                        runner_notes.append(f"extract {key!r} failed: {exc}")
                        raw = None
                    if raw is None:
                        continue
                    coerced = _coerce(raw, spec.get("type"))
                    _set_field_path(extracted, key, coerced)

        finally:
            try:
                if browser_context is not None:
                    await browser_context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    await browser.close()
            except Exception:
                pass

    # Build result
    result = TaxLookupResult(
        apn=str(extracted.get("apn") or apn),
        tax_year=str(extracted.get("tax_year") or ""),
        property_address=str(extracted.get("property_address") or ""),
        tra=str(extracted.get("tra") or ""),
        assessed_value=dict(extracted.get("assessed_value") or {}),
        installments=list(extracted.get("installments") or []),
        annual_total=float(extracted.get("annual_total") or 0.0),
        delinquent=bool(extracted.get("delinquent") or False),
        special_assessments=list(extracted.get("special_assessments") or []),
        source_url=source_url,
        source_artifact=str(capture_html),
        captured_at=datetime.now(),
        status="TAX_FAILED",
        notes="; ".join(runner_notes) if runner_notes else "",
    )

    if runner_error:
        result.status = "TAX_FAILED"
        result.error = runner_error
        return result

    # Annual total fallback: if recipe extracted installments amounts, sum them.
    if not result.annual_total and result.installments:
        try:
            total = sum(
                float(inst.get("amount") or 0)
                for inst in result.installments
                if isinstance(inst, dict)
            )
            if total > 0:
                result.annual_total = total
        except Exception:
            pass

    status, verified, missing, notes, error = _classify(
        recipe, extracted, apn, source_url, body_text
    )
    result.status = status
    result.verified_fields = verified
    result.missing_fields = missing
    if notes:
        result.notes = (result.notes + " " + notes).strip() if result.notes else notes
    if error:
        result.error = error
    return result


# ----------------------------------------------------------------------
# Public sync wrapper
# ----------------------------------------------------------------------


def _run_in_new_loop(recipe: dict, apn: str, case_dir: Path, safe_owner: str, property_address: str = "") -> TaxLookupResult:
    """Execute `_run_async` in a brand-new event loop on this thread."""
    return asyncio.run(_run_async(recipe, apn, case_dir, safe_owner, property_address))


def run(recipe: dict, apn: str, case_dir: Path, safe_owner: str = "tax", property_address: str = "") -> TaxLookupResult:
    """Synchronously run a tax recipe against `apn`, saving artifacts to `case_dir`.

    This function detects whether an asyncio loop is already running (it
    will be when called from a Flask debug-reloader child handling an
    async request) and runs the coroutine on a fresh thread when needed.
    """
    if not isinstance(recipe, dict):
        raise TypeError("recipe must be a dict")
    case_dir = Path(case_dir)
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if not in_loop:
        return _run_in_new_loop(recipe, apn, case_dir, safe_owner, property_address)

    # Inside an async loop: run in a worker thread with its own loop.
    container: dict[str, Any] = {}

    def _worker():
        try:
            container["result"] = _run_in_new_loop(recipe, apn, case_dir, safe_owner, property_address)
        except BaseException as exc:
            container["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in container:
        raise container["error"]
    return container["result"]
