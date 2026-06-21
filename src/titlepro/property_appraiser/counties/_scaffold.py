"""Shared scaffold base for not-yet-implemented county Property Appraiser adapters.

Phase 1b (FL next batch — Landmark wave). Each Landmark county already has a
live recorder adapter + per-county recorder config + a registered tax recipe;
the ONLY missing Broward-Standard layer is the Property Appraiser anchor. This
module gives every such county a real home + registry wiring so the only
remaining work per county is the live portal probe + parse implementation
(mirrors how the Miami-Dade recorder adapter was scaffolded before its probe).

A scaffolded county:
  * is registered in ``config/county_property_appraiser_urls.json`` with
    ``platform: "landmark_pa_scaffold"`` and ``status: "scaffold"``;
  * resolves through ``fetch_property_appraiser`` to a concrete adapter object
    (so the pipeline "sees" the county);
  * returns a soft-failure ``PropertyAppraiserResult`` (``status="PA_NO_RUNNER"``,
    notes naming the county + "scaffold / not implemented") from the three
    lookup entry points, so it can never silently ship an empty anchor AND never
    crashes a caller that treats a registered county as callable. The public
    ``fetch_property_appraiser`` factory contract is that adapters never raise.
  * still exposes a DEV-ONLY ``preflight()`` that DOES raise
    ``NotImplementedError`` with the per-county probe checklist — for use in
    scaffold structural tests / manual dev signalling, NOT on the factory path.

To graduate a county to live:
  1. Run the live probe (capture address-search request/response, parcel-detail
     shape, owner/legal/value/sale-history fields). Save to
     ``/tmp/<county>_pa_probe.md``.
  2. Implement ``lookup_by_address`` / ``lookup_by_apn`` in the county module
     (``<county>_pa.py``), returning a populated ``PropertyAppraiserResult``.
  3. Flip the county's config ``platform`` to its own (e.g. ``escambia_pa_http``)
     and add a dedicated branch in ``property_appraiser/__init__.py``.
  4. Add real unit tests (≥10, against canned probe fixtures) and drop the
     scaffold assertions for that county.

HTTP-only when implemented (Tony directive #1 — no Selenium/Playwright).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ..base import AbstractPropertyAppraiser
from ..result import PropertyAppraiserResult


class LandmarkPAScaffold(AbstractPropertyAppraiser):
    """Concrete-but-unimplemented PA adapter. Identity comes from config.

    Subclasses (one per county) set ``SOURCE_LABEL`` and carry the county's
    probe checklist in their module docstring; behaviour stays here until the
    county is implemented.
    """

    SOURCE_LABEL: str = "County Property Appraiser"
    # Platform name the county will use once it graduates to a live adapter.
    LIVE_PLATFORM: str = ""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.county_id = self.config.get("county_id", "")
        self.county_name = self.config.get("county_name", "")
        self.source_label = self.config.get("description") or self.SOURCE_LABEL
        self.base_url = self.config.get("base_url", "")
        self.endpoints = self.config.get("endpoints", {})

    # --- identity helpers -------------------------------------------------
    @property
    def is_scaffold(self) -> bool:
        return True

    def _not_implemented_message(self, kind: str) -> str:
        return (
            f"{self.__class__.__name__} ({self.county_id}) is a Property Appraiser "
            f"SCAFFOLD — live probe pending. base_url={self.base_url!r}. "
            f"{kind} lookup not yet implemented; run the portal probe, then "
            f"implement in the county module and flip config platform to "
            f"{self.LIVE_PLATFORM or '<county>_pa_http'}. "
            f"See _scaffold.py module docstring for the graduation checklist."
        )

    def _soft_failure(self, kind: str) -> PropertyAppraiserResult:
        """Soft-failure result the factory path returns instead of raising.

        Uses ``PA_NO_RUNNER`` — the same status other adapters report when a
        county has no live runner — so downstream reconciliation treats a
        scaffolded county exactly like an unregistered one (anchor absent,
        loudly noted) rather than crashing.
        """
        return PropertyAppraiserResult(
            status="PA_NO_RUNNER",
            notes=self._not_implemented_message(kind),
            source_url=self.base_url,
            fetched_at=datetime.now().isoformat(),
        )

    def preflight(self, kind: str = "lookup") -> None:
        """DEV-ONLY hard signal. Raises ``NotImplementedError`` so a developer
        wiring a new county against a scaffold gets a loud, actionable error.
        This is NOT invoked on the ``fetch_property_appraiser`` factory path —
        that path must never raise (see module docstring)."""
        raise NotImplementedError(self._not_implemented_message(kind))

    # --- abstract entry points (soft-fail until implemented) --------------
    # These return a PA_NO_RUNNER result rather than raising, honoring the
    # public factory's no-raise contract (P2b, 2026-06-16).
    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        return self._soft_failure("address")

    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        return self._soft_failure("APN")

    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        return [self._soft_failure("owner-name")]
