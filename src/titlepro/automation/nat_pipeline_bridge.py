"""
NAT → CURE Pipeline Bridge
Translates a NAT API request dict into a WorkflowConfig for RecorderAutomationPipeline.
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional
from titlepro.automation.pipeline import WorkflowConfig, SearchRequest, AIConfig


def _load_secrets() -> dict:
    """Read config/secrets.json; return empty dict on any error."""
    try:
        secrets_path = Path(__file__).parent.parent.parent.parent / "config" / "secrets.json"
        return json.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _engine_to_provider(engine: str) -> str:
    """Map an AI_ENGINE string to the provider key used by build_agent_runner()."""
    e = engine.strip().lower()
    if e == "google":  return "google"
    if e == "groq":    return "groq"
    if e == "claude":  return "api"
    return "api"  # default


def _engine_to_model(engine: str, s: dict) -> str:
    """Return the model name for the given engine, reading from secrets dict."""
    e = engine.strip().lower()
    if e == "google":  return s.get("GOOGLE_MODEL") or "gemini-2.0-flash"
    if e == "groq":    return s.get("GROQ_MODEL")   or "llama-3.3-70b-versatile"
    return s.get("CLAUDE_MODEL") or "claude-sonnet-4-6"


def _load_secrets_provider() -> str:
    """Global provider — used when no per-phase override is set."""
    s = _load_secrets()
    engine = s.get("AI_ENGINE", "").strip().lower()
    if engine in ("google", "groq", "claude"):
        return _engine_to_provider(engine)
    # Backwards-compat: check CLAUDE_MODE
    return "api" if s.get("CLAUDE_MODE", "").strip().lower() == "api" else "claude"


def _load_secrets_model() -> str:
    """Global model — used when no per-phase override is set."""
    s = _load_secrets()
    engine = s.get("AI_ENGINE", "").strip().lower()
    return _engine_to_model(engine, s)


def _load_phase_provider(phase_key: str) -> Optional[str]:
    """
    Load a per-phase provider from secrets.json.

    phase_key is one of: AI_ENGINE_RAW, AI_ENGINE_TITLE, AI_ENGINE_ONE.
    Returns None when the key is absent or empty (caller uses global provider).
    """
    s = _load_secrets()
    engine = s.get(phase_key, "").strip().lower()
    if not engine:
        return None
    return _engine_to_provider(engine)


def _load_phase_model_for_key(phase_engine_key: str) -> Optional[str]:
    """
    Return the model for a per-phase engine key (e.g. AI_ENGINE_RAW).
    Returns None when the key is absent or empty (caller uses global model).
    """
    s = _load_secrets()
    engine = s.get(phase_engine_key, "").strip().lower()
    if not engine:
        return None
    return _engine_to_model(engine, s)


# ── County slug normalization ──────────────────────────────────────────────────

# Counties that use a non-standard slug in the registry
_COUNTY_SLUG_OVERRIDES: dict[str, str] = {
    "palm beach":       "fl_palm_beach",
    "miami-dade":       "fl_miami_dade",
    "miami dade":       "fl_miami_dade",
    "st. johns":        "fl_st_johns",
    "st johns":         "fl_st_johns",
    "st. lucie":        "fl_st_lucie",
    "st lucie":         "fl_st_lucie",
    "indian river":     "fl_indian_river",
    "santa rosa":       "fl_santa_rosa",
    "okaloosa":         "fl_okaloosa",
}


def _normalize_county_slug(county_raw: str, state: str = "FL") -> str:
    """
    Turn NAT's county string into the pipeline registry slug.
    e.g. "polk" + "FL" → "fl_polk"
         "Palm Beach" + "FL" → "fl_palm_beach"
    """
    cleaned = county_raw.strip().lower()
    # Remove trailing " county" if present
    cleaned = re.sub(r"\s+county$", "", cleaned)

    # Check override table first
    if cleaned in _COUNTY_SLUG_OVERRIDES:
        return _COUNTY_SLUG_OVERRIDES[cleaned]

    # Generic: {state_lower}_{county_snake_case}
    slug = cleaned.replace(" ", "_").replace("-", "_")
    return f"{state.strip().lower()}_{slug}"


# ── Owner name formatting ──────────────────────────────────────────────────────

def _deduplicate_name(name: str) -> str:
    """
    Remove accidentally doubled names that NAT sometimes sends.
    "ALANA FROMER ALANA FROMER" → "ALANA FROMER"
    "BUNKER WILLIAM JOSEPH BUNKER WILLIAM JOSEPH" → "BUNKER WILLIAM JOSEPH"
    Leaves normal names untouched.
    """
    words = name.split()
    n = len(words)
    # Try all even-split lengths from half down to 1
    for half in range(n // 2, 0, -1):
        if n == half * 2 and words[:half] == words[half:]:
            return ' '.join(words[:half])
    return name


def _to_fl_last_first(name_raw: str) -> str:
    """
    Convert an owner name to FL recorder "LAST, FIRST" format.

    Handles:
      "BUNKER WILLIAM JOSEPH" → "BUNKER, WILLIAM JOSEPH"
      "HABER DANA M"          → "HABER, DANA M"
      "HABER, DANA M"         → "HABER, DANA M"  (already formatted — pass through)
      "ALANA FROMER ALANA FROMER" → deduplicated first → "ALANA, FROMER"
    """
    name = _deduplicate_name(name_raw.strip().upper())
    # Already in LAST, FIRST format
    if "," in name:
        return name

    parts = name.split()
    if len(parts) == 1:
        return name
    if len(parts) >= 2:
        # Assume first token is the last name (FL recorder standard)
        return f"{parts[0]}, {' '.join(parts[1:])}"
    return name


# ── Build WorkflowConfig ───────────────────────────────────────────────────────

def build_nat_workflow_config(
    request_data: dict,
    nat_file_number: str,
) -> WorkflowConfig:
    """
    Translate a NAT API request payload into a WorkflowConfig for the pipeline.

    Expected request_data keys:
        nat_file_number  str  (also passed as arg)
        owner_name       str  e.g. "BUNKER WILLIAM JOSEPH"
        county           str  e.g. "polk"
        state            str  e.g. "FL"  (defaults to FL)
        address          str  e.g. "123 Main St, Tampa FL 33601"
        apn              str  optional parcel number
        spouse_name      str  optional second owner name

    Returns a fully-configured WorkflowConfig ready to pass to
    RecorderAutomationPipeline(config).
    """
    state = request_data.get("state", "FL").strip().upper()
    county_raw = request_data.get("county", "")
    county_slug = _normalize_county_slug(county_raw, state)

    owner_raw = request_data.get("owner_name", "").strip().upper()
    owner_fl = _to_fl_last_first(owner_raw)

    address = request_data.get("address", "").strip()
    apn: Optional[str] = request_data.get("apn") or None

    # Build search request list — primary owner always included
    search_requests: list[SearchRequest] = [
        SearchRequest(
            name=owner_fl,
            party_types=["Grantor", "Grantee", "Grantor/Grantee"],
        )
    ]

    # Add spouse if provided
    spouse_raw = request_data.get("spouse_name", "").strip().upper()
    if spouse_raw:
        spouse_fl = _to_fl_last_first(spouse_raw)
        if spouse_fl and spouse_fl != owner_fl:
            search_requests.append(
                SearchRequest(
                    name=spouse_fl,
                    party_types=["Grantor", "Grantee", "Grantor/Grantee"],
                )
            )

    return WorkflowConfig(
        owner_name=owner_fl,
        county=county_slug,
        state=state,
        property_address=address,
        apn=apn,
        output_folder_name=f"NAT_{nat_file_number}",
        search_requests=search_requests,
        generate_title_notes=True,
        generate_raw_pdf=True,
        generate_title_pdf=True,
        generate_one_report=True,
        fetch_tax=True,
        # If no APN in NAT request and none extractable from deeds, skip tax
        # gracefully (write status="skipped") rather than hard-failing the job.
        allow_tax_skip_on_missing_apn=True,
        resume=True,
        # Tolerate individual download failures: the pipeline promotes any
        # undownloadable doc to "examined_and_excluded" in the report rather
        # than aborting the entire job. The RAW/Title AI phases still produce
        # a complete report for all successfully downloaded documents.
        strict_downloads=False,
        # Model + provider for all AI phases — read from config/secrets.json.
        # AI_ENGINE global: 'claude' | 'google' | 'groq'
        # AI_ENGINE_RAW / AI_ENGINE_TITLE / AI_ENGINE_ONE override per phase.
        # When a per-phase key is empty the global AI_ENGINE applies.
        #
        # IMPORTANT: do NOT set the global `model` field here.  The
        # `_resolve_phase_model()` logic gives global model absolute priority
        # over per-phase models, so setting it to the Groq model would make
        # the Claude-overridden RAW phase call Claude with a Groq model name.
        # Instead, resolve each phase's model here in the bridge where we have
        # access to secrets, and store them as per-phase model fields.
        ai=AIConfig(
            provider=_load_secrets_provider(),
            raw_provider=_load_phase_provider("AI_ENGINE_RAW"),
            title_provider=_load_phase_provider("AI_ENGINE_TITLE"),
            one_provider=_load_phase_provider("AI_ENGINE_ONE"),
            # Per-phase model: use the phase-engine's model, or fall back to
            # the global engine's model when no per-phase override is set.
            raw_model=_load_phase_model_for_key("AI_ENGINE_RAW") or _load_secrets_model(),
            title_model=_load_phase_model_for_key("AI_ENGINE_TITLE") or _load_secrets_model(),
            one_model=_load_phase_model_for_key("AI_ENGINE_ONE") or _load_secrets_model(),
        ),
    )
