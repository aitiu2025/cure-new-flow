"""Abstract base for county Property Appraiser adapters.

Mirrors the `BaseRecorderSearch` shape used by recorder adapters so the
factory + tests + pipeline can treat PA adapters uniformly. The three
abstract entry points are address, APN, and owner-name lookups.

Implementations MUST be HTTP-only (Tony directive #1 — no Selenium/Playwright)
and MUST return a `PropertyAppraiserResult` with a valid status code even
on failure (no raising allowed — fail soft, populate `status` + `notes`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from .result import PropertyAppraiserResult


class AbstractPropertyAppraiser(ABC):
    """Common interface every county PA adapter implements."""

    # Subclasses fill these from their JSON config.
    county_id: str = ""
    county_name: str = ""
    source_label: str = ""    # e.g., "Broward County Property Appraiser"

    @abstractmethod
    def lookup_by_address(self, address: str) -> PropertyAppraiserResult:
        """Resolve subject address → PropertyAppraiserResult.

        Adapters should perform whatever normalization the portal requires
        (autocomplete pass, suffix stripping, etc.) BEFORE the main search,
        and surface ambiguity via status=PA_AMBIGUOUS + notes.
        """

    @abstractmethod
    def lookup_by_apn(self, apn: str) -> PropertyAppraiserResult:
        """Resolve APN/folio → PropertyAppraiserResult.

        The APN format passed in may have hyphens, dots, or spaces — the
        adapter must normalize to the portal's expected format.
        """

    @abstractmethod
    def lookup_by_owner_name(self, owner_name: str) -> List[PropertyAppraiserResult]:
        """Best-effort owner-name search. Mainly for diagnostics — the
        canonical path is by address. Returns a (possibly empty) list.
        """
