"""TaxAgent Gap E — verify the legacy "County 'X' not supported. Supported:
[...]" error text never reaches the user-facing surface.

Three layers protected:

1. `titlepro.tax.multi_county_tax.lookup_tax` (the legacy entry point) must
   delegate to the v2 dispatcher and must NEVER return an `error` field
   containing "not supported" or "Supported:".
2. `titlepro.tax.fetch_tax` for a county without a recipe / scraper must
   return `TAX_NO_RUNNER` with a clean `notes` string (no "Supported:" list).
3. `RecorderAutomationPipeline._build_raw_user_prompt`, when given a tax
   sidecar AND tax JSON that contain legacy "Supported: [...]" / "not
   supported" fragments, must scrub those before serializing the prompt.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1) Legacy lookup_tax must not leak "not supported" text
# ---------------------------------------------------------------------------


def test_lookup_tax_contra_costa_no_legacy_supported_text():
    """`lookup_tax("contra_costa", APN)` historically returned an error like
    `"County 'contra_costa' not supported for tax lookup. Supported:
    ['orange', ...]"`. After delegating to the v2 dispatcher, the returned
    dict's `error` field must NOT contain that fragment.
    """
    from titlepro.tax.multi_county_tax import lookup_tax

    result = lookup_tax("011-291-028-6", "contra_costa")
    assert isinstance(result, dict)
    # Be permissive about the runner shape (success may be True or False
    # depending on browser availability), but the error field must be clean.
    err = (result.get("error") or "").lower()
    notes = (result.get("notes") or "").lower()
    assert "not supported" not in err, f"legacy error fragment leaked: {err}"
    assert "supported:" not in err, f"legacy 'Supported:' list leaked: {err}"
    assert "not supported" not in notes, f"legacy fragment leaked into notes: {notes}"
    assert "supported:" not in notes, f"legacy 'Supported:' list leaked into notes: {notes}"


def test_lookup_tax_unknown_county_returns_neutral_message():
    """An unknown county must return a neutral message, not a 'Supported: ['
    list. This is the primary regression guard."""
    from titlepro.tax.multi_county_tax import lookup_tax

    result = lookup_tax("123-456-78", "totally_unknown_county_xyz")
    assert isinstance(result, dict)
    err = (result.get("error") or "")
    notes = (result.get("notes") or "")
    # Either field is allowed to be empty; neither may carry the legacy list.
    assert "Supported:" not in err
    assert "Supported:" not in notes
    assert "not supported" not in err.lower()
    assert "not supported" not in notes.lower()


# ---------------------------------------------------------------------------
# 2) fetch_tax dispatcher returns TAX_NO_RUNNER cleanly
# ---------------------------------------------------------------------------


def test_fetch_tax_alameda_returns_clean_no_runner(tmp_path):
    """A platform='direct' county with no recipe must return TAX_NO_RUNNER
    with a neutral `notes` string.

    Note (2026-05-13): alameda was flipped to playwright_form when its recipe
    landed. Test now exercises kern (still 'direct') to keep the original
    intent of the assertion intact.
    """
    from titlepro.tax import fetch_tax

    result = fetch_tax(
        county_id="kern",
        apn="1234-001-001",
        owner_name="TEST OWNER",
        property_address="",
        case_dir=tmp_path,
    )
    assert result.status == "TAX_NO_RUNNER"
    notes = (result.notes or "")
    error = (result.error or "")
    assert "Supported:" not in notes
    assert "Supported:" not in error
    assert "not supported" not in notes.lower()
    assert "not supported" not in error.lower()
    # And the message should explicitly identify itself as a "no runner" notice.
    assert "no tax-lookup runner" in notes.lower() or "no automated" in notes.lower() \
        or "runner" in notes.lower(), notes


# ---------------------------------------------------------------------------
# 3) _build_raw_user_prompt must sanitize legacy error text
# ---------------------------------------------------------------------------


def test_build_raw_user_prompt_strips_legacy_supported_list(tmp_path, monkeypatch):
    """When the tax sidecar contains a legacy 'Supported: [...]' fragment,
    `_build_raw_user_prompt` must remove it before injecting into the prompt.
    """
    from titlepro.automation import pipeline as pipeline_module
    from titlepro.automation.pipeline import RecorderAutomationPipeline, WorkflowConfig

    monkeypatch.setattr(pipeline_module, "DOWNLOAD_DIR", tmp_path)

    cfg = WorkflowConfig.from_dict({
        "owner_name": "WALTERS_TEST",
        "county": "contra_costa",
        "search_requests": [{"name": "WALTERS"}],
        "fetch_tax": True,
        "apn": "011-291-028-6",
    })
    pipeline = RecorderAutomationPipeline(cfg)

    # Plant a tax_lookup_status.json with legacy error fragment.
    legacy_notes = (
        "County 'contra_costa' not supported for tax lookup. "
        "Supported: ['orange', 'amador', 'plumas']. "
        "APN searched: 011-291-028-6."
    )
    sidecar = {
        "status": "failed",
        "tax_status": "TAX_FAILED",
        "reason": "legacy run",
        "notes": legacy_notes,
        "error": legacy_notes,
        "county": "contra_costa",
        "apn": "011-291-028-6",
    }
    pipeline.tax_lookup_status_path().write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )

    # Plant the legacy-format tax_<owner>.json too.
    tax_path = pipeline.case_dir / f"tax_{cfg.safe_owner}.json"
    tax_payload = {
        "lookup_metadata": {
            "county": "contra_costa",
            "platform": "unknown",
            "lookup_timestamp": "2026-05-14T23:26:47",
            "apn_searched": "011-291-028-6",
            "success": False,
            "error": legacy_notes,
        },
        "tax_information": {
            "tax_year": "",
            "apn": "011-291-028-6",
            "annual_tax_estimated": "",
            "verification_url": "",
            "data_source": "",
        },
    }
    tax_path.write_text(json.dumps(tax_payload), encoding="utf-8")

    # Need a documents_found.json so _build_raw_user_prompt can run.
    (pipeline.case_dir / "documents_found.json").write_text("[]", encoding="utf-8")
    (pipeline.case_dir / "downloaded_files.json").write_text("{}", encoding="utf-8")

    prompt = pipeline._build_raw_user_prompt()

    assert "Supported: [" not in prompt, (
        "legacy 'Supported: [...]' fragment leaked into RAW user prompt:\n"
        f"{prompt[:500]}"
    )
    assert "not supported for tax lookup" not in prompt.lower(), (
        "legacy 'not supported for tax lookup' fragment leaked into RAW user prompt"
    )


def test_scrub_legacy_text_helper_strips_supported_list():
    """Unit test for the module-level scrubber helper."""
    from titlepro.automation.pipeline import _scrub_legacy_text

    src = (
        "County 'contra_costa' not supported for tax lookup. "
        "Supported: ['orange', 'amador']. APN searched: 011-291-028-6."
    )
    out = _scrub_legacy_text(src)
    assert "Supported:" not in out
    assert "not supported" not in out.lower()


def test_canonical_tax_payload_drops_legacy_error():
    """`_canonical_tax_payload_for_prompt` must NOT carry the legacy `error`
    string from `lookup_metadata` into its output."""
    from titlepro.automation.pipeline import _canonical_tax_payload_for_prompt

    tax_data = {
        "lookup_metadata": {
            "county": "contra_costa",
            "success": False,
            "error": (
                "County 'contra_costa' not supported for tax lookup. "
                "Supported: ['orange']"
            ),
            "verification_url": "https://taxcolp.cccttc.us/lookup/",
            "apn_searched": "011-291-028-6",
        },
        "tax_information": {
            "tax_year": "2025-2026",
            "apn": "011-291-028-6",
            "annual_tax_estimated": "",
            "property_address": "1724 WESLEY AVE, EL CERRITO, CA",
        },
    }
    canonical = _canonical_tax_payload_for_prompt(tax_data)
    serialized = json.dumps(canonical)
    assert "Supported:" not in serialized
    assert "not supported" not in serialized.lower()
    # Canonical fields preserved
    assert canonical.get("apn") == "011-291-028-6"
    assert canonical.get("tax_year") == "2025-2026"
