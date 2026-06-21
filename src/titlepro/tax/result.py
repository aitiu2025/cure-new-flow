"""Canonical TaxLookupResult dataclass.

Every tax-lookup runner (MBC scraper, OC Treasurer scraper, generic
Playwright recipe runner, etc.) returns this exact shape. The pipeline
never touches raw scraper dicts.

See `docs/proposals/tax_plumbing_v2_codex_revised.md` (Layer 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# Status vocabulary. Synchronized with the proposal v2 spec and consumed
# by `RecorderAutomationPipeline.tax_lookup`, the UI badge logic, and
# tests/unit/test_tax_*.py.
TaxStatus = Literal[
    "TAX_SUCCESS",
    "TAX_PARTIAL",
    "TAX_NO_RESULTS",
    "TAX_NO_RUNNER",
    "TAX_FAILED",
    "NEEDS_HUMAN",
]

TAX_STATUSES: frozenset[str] = frozenset(
    (
        "TAX_SUCCESS",
        "TAX_PARTIAL",
        "TAX_NO_RESULTS",
        "TAX_NO_RUNNER",
        "TAX_FAILED",
        "NEEDS_HUMAN",
    )
)


@dataclass
class TaxLookupResult:
    """Canonical tax-lookup result returned by every scraper/runner.

    Fields:
        apn:                 APN echoed back from the authoritative source.
        tax_year:            Tax year string (e.g. "2025-26").
        property_address:    Subject property address (passthrough).
        tra:                 Tax Rate Area code if reported.
        assessed_value:      Dict of `{land, improvements, net_taxable, ...}`.
        installments:        List of `{period, amount, status, due_date}` dicts.
        annual_total:        Annual tax total (float).
        delinquent:          Boolean delinquent flag.
        special_assessments: List of special-assessment line items.
        source_url:          URL of the page the data was actually scraped from.
                             MUST match the recipe's `authoritative_source_hosts`
                             whitelist for `status="TAX_SUCCESS"`.
        source_artifact:     Local path to a captured HTML/PDF artifact.
        captured_at:         When the lookup ran.
        status:              One of TAX_STATUSES.
        verified_fields:     Field paths confirmed populated from the
                             authoritative source. Estimated/_estimated keys
                             MUST NOT appear here.
        missing_fields:      Field paths that should have been populated but
                             were not.
        notes:               Human-readable notes.
        error:               Error message when `status="TAX_FAILED"`.
    """

    apn: str
    tax_year: str
    property_address: str
    tra: str = ""
    assessed_value: dict = field(default_factory=dict)
    installments: list[dict] = field(default_factory=list)
    annual_total: float = 0.0
    delinquent: bool = False
    special_assessments: list = field(default_factory=list)
    source_url: str = ""
    source_artifact: str = ""
    captured_at: datetime = field(default_factory=datetime.now)
    status: str = "TAX_FAILED"  # use TaxStatus literal at type-checking time
    verified_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    notes: str = ""
    error: str = ""

    # -----------------------------------------------------------------
    # Prior-year (N-1) dual-year echo
    # -----------------------------------------------------------------
    # Many county tax-collector portals expose a "Prior Year" link or
    # historical-year section on the parcel detail page. When the
    # adapter can capture that data, it populates these fields so the
    # downstream report can render a dual-year layout. When the prior
    # year is unavailable, every field stays None (NOT empty-string,
    # NOT 0) and the pipeline falls back to single-year rendering.
    #
    # Added 2026-06-03 per the dual-year tax echo plumbing. Additive
    # only -- existing callers that ignore these fields are unaffected.
    prior_year_tax_year: int | None = None
    prior_year_annual_amount: float | None = None
    prior_year_just_value: float | None = None
    prior_year_net_taxable: float | None = None
    prior_year_installment_status: str | None = None  # "PAID/CURRENT", "DELINQUENT", "INSTALLMENT_PLAN", "NOT_AVAILABLE"
    prior_year_paid_date: str | None = None           # ISO date
    prior_year_source_url: str | None = None
    prior_year_captured_at: str | None = None         # ISO timestamp (mirrors captured_at style)

    def __post_init__(self) -> None:
        if self.status not in TAX_STATUSES:
            raise ValueError(
                f"Unknown TaxStatus '{self.status}'. Valid: {sorted(TAX_STATUSES)}"
            )

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (datetime -> isoformat)."""
        from dataclasses import asdict

        data = asdict(self)
        # Datetime -> ISO string. dataclasses.asdict doesn't auto-convert.
        captured = data.get("captured_at")
        if isinstance(captured, datetime):
            data["captured_at"] = captured.isoformat()
        return data


# ----------------------------------------------------------------------
# Helpers used by runners and tests
# ----------------------------------------------------------------------


def normalize_apn(apn: str) -> str:
    """Strip format hyphens/spaces and lowercase for comparison.

    Two APNs match when their normalized forms are equal. This is the
    canonical comparison used by `playwright_runner._check_apn_echo` and
    `dispatcher._wrap_legacy_dict`.
    """
    if not apn:
        return ""
    return "".join(ch for ch in str(apn) if ch.isalnum()).lower()


def apn_matches(input_apn: str, scraped_apn: str) -> bool:
    """Case-insensitive, hyphen-stripped APN equality with check-digit tolerance.

    Two APNs match when ANY of the following hold (after normalizing both
    via `normalize_apn` — strip hyphens/spaces, lowercase):

      (a) Exact normalized equality.
      (b) One is a strict prefix of the other AND the difference is <= 2
          trailing characters. This handles the Contra Costa case where
          the recorder stores "502-153-010-9" (10 digits) but a partial
          recipe might submit/echo "502-153-010" (9 digits) — the trailing
          "-9" is the published check digit.
      (c) One is a strict suffix of the other AND the difference is exactly
          1 trailing digit (covers symmetric check-digit suffix forms).

    This relaxation closes the audit defect where the Contra Costa recipe
    deliberately truncated the check digit to bypass the strict equality
    that rejected the canonical 10-digit APN. See
    docs/audits/legal_description_ordering_audit_2026-05-18.md.
    """
    a = normalize_apn(input_apn)
    b = normalize_apn(scraped_apn)
    if not a or not b:
        return False
    if a == b:
        return True
    # Determine which is longer; treat the shorter as the candidate prefix.
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    diff = len(long_) - len(short)
    if diff == 0:
        return False
    # (b) prefix match within 2 trailing chars
    if long_.startswith(short) and diff <= 2:
        # Verify the trailing chars are digits — alphanumerics drift between
        # parcels should not be silently equated.
        if long_[len(short):].isdigit():
            return True
    # (c) Single-character SUFFIX match — unusual but seen when a portal
    # echoes a leading 0 the user dropped.
    if diff == 1 and long_.endswith(short) and long_[0].isdigit():
        return True
    return False


def host_in_whitelist(
    source_url: str,
    whitelist: list[str],
    mode: str = "strict",
) -> bool:
    """Return True iff source_url's host matches one of `whitelist`.

    Modes (Codex finding: tighten default to opt-in suffix matching):

    - ``"strict"`` (default) — case-insensitive *exact* host equality. A
      whitelist entry of ``fcacttcptr.fresnocountyca.gov`` matches only
      URLs whose host is exactly that string. Subdomain takeovers like
      ``attacker.fcacttcptr.fresnocountyca.gov`` are rejected.
    - ``"suffix"`` — host matches if it equals or is a sub-domain of any
      whitelist entry (e.g. whitelist ``mptsweb.com`` matches
      ``common1.mptsweb.com``, ``common2.mptsweb.com``, etc.). Opt-in for
      portals whose authoritative source legitimately rotates sub-domains.

    Empty whitelist or empty URL always returns False.
    """
    if not source_url or not whitelist:
        return False
    try:
        from urllib.parse import urlparse

        host = (urlparse(source_url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    use_suffix = (str(mode or "strict").lower() == "suffix")
    for allowed in whitelist:
        allowed_l = (allowed or "").lower().strip()
        if not allowed_l:
            continue
        if host == allowed_l:
            return True
        if use_suffix and host.endswith("." + allowed_l):
            return True
    return False


def is_estimated_key(key: str) -> bool:
    """A field key is 'estimated' when it ends with `_estimated`."""
    return bool(key) and str(key).endswith("_estimated")
