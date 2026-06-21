"""Hand-rolled validator for tax-recipe JSON files.

Schema is documented in `docs/proposals/tax_plumbing_v2_codex_revised.md`
(Layer 2). We do not require `jsonschema` as a dependency.

Usage:
    from titlepro.tax.recipe_schema import validate_recipe, validate_all_recipes
    errors = validate_recipe(recipe_dict)
    if errors:
        raise ValueError("Recipe failed validation: " + "; ".join(errors))
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Allowed actions in `navigation_steps`. Adding a new action requires
# extending `playwright_runner._execute_step()` too.
#
# Iframe actions (added 2026-05-13 for SBD support):
#   - `enter_frame`: descend into a child <iframe>. Selectors after this
#     run inside the frame's DOM. Use `selector` to pick the iframe
#     element (e.g. "iframe[src*='taxsys']") and optional `url_contains`
#     to disambiguate when more than one iframe matches. Frames may be
#     nested: stack `enter_frame` actions to descend further.
#   - `exit_frame`: pop one level back up the frame stack. `exit_frame`
#     with `to: "top"` pops all the way back to the page.
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "goto",
        "click",
        "fill",
        "select",
        "split_apn",
        "wait_for",
        "wait_for_url",
        "extract_field",
        "extract_table",
        "sleep",
        "enter_frame",
        "exit_frame",
        # `press_key` (added 2026-05-13 for Santa Clara): dispatches a
        # keyboard key on either a focused element (if `selector` given)
        # or whatever element currently has focus. `key` defaults to
        # "Enter". Optional `wait_after_ms` settles the portal after the
        # press triggers a navigation/XHR.
        "press_key",
    }
)

# Allowed `extract.<key>.type` values (controls value coercion).
ALLOWED_EXTRACT_TYPES: frozenset[str] = frozenset({"string", "currency", "int", "float", "date"})

# Allowed `host_whitelist_mode` values (controls source-host matcher behavior).
# - "strict" (default): host must equal one of `authoritative_source_hosts`
#   exactly (case-insensitive).
# - "suffix": host matches if it equals or is a sub-domain of any whitelist
#   entry. Use only for portals that legitimately rotate sub-domains
#   (e.g. `common1.mptsweb.com` vs `common2.mptsweb.com`).
ALLOWED_HOST_WHITELIST_MODES: frozenset[str] = frozenset({"strict", "suffix"})


def validate_recipe(recipe: Any, *, source_label: str = "<inline>") -> list[str]:
    """Return a list of human-readable errors. Empty list = valid.

    The function is intentionally permissive — only the fields we depend
    on are required. Unknown keys are allowed (forward-compat).
    """
    errors: list[str] = []
    if not isinstance(recipe, dict):
        return [f"{source_label}: top-level recipe must be a JSON object"]

    # Required top-level keys
    for key in ("county", "platform", "base_url", "authoritative_source_hosts", "navigation_steps"):
        if key not in recipe:
            errors.append(f"{source_label}: missing required top-level key '{key}'")

    # platform sanity
    platform = recipe.get("platform")
    if platform is not None and not isinstance(platform, str):
        errors.append(f"{source_label}: 'platform' must be a string")

    # authoritative_source_hosts must be a non-empty list of strings
    hosts = recipe.get("authoritative_source_hosts")
    if hosts is None:
        # Already flagged as missing above; skip.
        pass
    elif not isinstance(hosts, list) or not hosts:
        errors.append(
            f"{source_label}: 'authoritative_source_hosts' must be a non-empty list of host strings"
        )
    else:
        for i, h in enumerate(hosts):
            if not isinstance(h, str) or not h.strip():
                errors.append(
                    f"{source_label}: authoritative_source_hosts[{i}] must be a non-empty string"
                )

    # navigation_steps must be a non-empty list of dicts with an 'action'
    steps = recipe.get("navigation_steps")
    if steps is None:
        pass
    elif not isinstance(steps, list) or not steps:
        errors.append(f"{source_label}: 'navigation_steps' must be a non-empty list")
    else:
        for i, step in enumerate(steps):
            step_label = f"{source_label}: navigation_steps[{i}]"
            if not isinstance(step, dict):
                errors.append(f"{step_label} must be an object")
                continue
            action = step.get("action")
            if not isinstance(action, str):
                errors.append(f"{step_label} missing 'action' string")
                continue
            if action not in ALLOWED_ACTIONS:
                errors.append(
                    f"{step_label}: unknown action '{action}'. "
                    f"Allowed: {sorted(ALLOWED_ACTIONS)}"
                )
            # Per-action required keys
            if action in {"click", "fill", "select", "wait_for", "extract_field", "extract_table", "enter_frame"}:
                if not step.get("selector") and action != "wait_for_url":
                    errors.append(f"{step_label}: action '{action}' requires 'selector'")
            if action == "fill" and "value" not in step:
                errors.append(f"{step_label}: action 'fill' requires 'value'")
            if action == "goto" and not step.get("url"):
                errors.append(f"{step_label}: action 'goto' requires 'url'")
            if action == "split_apn":
                fields = step.get("fields")
                if not isinstance(fields, list) or not fields:
                    errors.append(f"{step_label}: action 'split_apn' requires non-empty 'fields' list")
            if action == "press_key":
                # `key` is optional (defaults to "Enter") but must be a
                # non-empty string when present.
                key_val = step.get("key", "Enter")
                if not isinstance(key_val, str) or not key_val.strip():
                    errors.append(
                        f"{step_label}: action 'press_key' requires 'key' to be a non-empty string"
                    )
                wait_after = step.get("wait_after_ms")
                if wait_after is not None and not isinstance(wait_after, (int, float)):
                    errors.append(
                        f"{step_label}: action 'press_key' 'wait_after_ms' must be a number"
                    )
                # `selector` is optional for press_key (omit to press on the
                # element that currently has focus). No further validation.

    # extract: dict of key -> spec
    extract = recipe.get("extract", {})
    if extract and not isinstance(extract, dict):
        errors.append(f"{source_label}: 'extract' must be an object")
    elif isinstance(extract, dict):
        for key, spec in extract.items():
            spec_label = f"{source_label}: extract['{key}']"
            if not isinstance(spec, dict):
                errors.append(f"{spec_label} must be an object")
                continue
            # Must have at least one of selector / regex
            if not spec.get("selector") and not spec.get("regex"):
                errors.append(f"{spec_label} requires either 'selector' or 'regex'")
            t = spec.get("type")
            if t is not None and t not in ALLOWED_EXTRACT_TYPES:
                errors.append(
                    f"{spec_label}: unknown type '{t}'. "
                    f"Allowed: {sorted(ALLOWED_EXTRACT_TYPES)}"
                )

    # host_whitelist_mode is optional but if present must be a known value
    hmode = recipe.get("host_whitelist_mode")
    if hmode is not None:
        if not isinstance(hmode, str) or hmode not in ALLOWED_HOST_WHITELIST_MODES:
            errors.append(
                f"{source_label}: 'host_whitelist_mode' must be one of "
                f"{sorted(ALLOWED_HOST_WHITELIST_MODES)} (got {hmode!r})"
            )

    # verification_required is optional but if present must be list[str]
    vr = recipe.get("verification_required", [])
    if vr and not isinstance(vr, list):
        errors.append(f"{source_label}: 'verification_required' must be a list of field-path strings")
    elif isinstance(vr, list):
        for i, k in enumerate(vr):
            if not isinstance(k, str) or not k.strip():
                errors.append(f"{source_label}: verification_required[{i}] must be a non-empty string")

    return errors


def validate_all_recipes(recipes_dir: Path) -> dict[str, list[str]]:
    """Validate every .json in `recipes_dir`. Returns `{filename: [errors]}`.

    Files with zero errors are still present in the mapping (mapped to an
    empty list) so callers can confirm they were inspected.
    """
    out: dict[str, list[str]] = {}
    if not recipes_dir.exists():
        return out
    for path in sorted(recipes_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            out[path.name] = [f"{path.name}: JSON parse error: {exc}"]
            continue
        out[path.name] = validate_recipe(data, source_label=path.name)
    return out


def load_recipe(county_id: str, recipes_dir: Path | None = None) -> dict[str, Any] | None:
    """Load and validate `<recipes_dir>/<county_id>.json`. Returns None if not present.

    Raises ValueError on validation errors so the caller fails fast.
    """
    if recipes_dir is None:
        recipes_dir = Path(__file__).resolve().parents[3] / "config" / "tax_recipes"
    path = recipes_dir / f"{county_id}.json"
    if not path.exists():
        return None
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Recipe {path} is not valid JSON: {exc}") from exc
    errors = validate_recipe(recipe, source_label=path.name)
    if errors:
        raise ValueError(f"Recipe {path} failed validation: " + "; ".join(errors))
    return recipe
