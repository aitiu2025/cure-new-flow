"""Property Appraiser result dataclasses.

Shape mirrors the existing `tax/result.py` (TaxLookupResult) so downstream
serializers + UI code can treat property-appraiser output the same way as
tax lookup output.

A `PropertyAppraiserResult` carries the canonical APN/folio, owner of record,
situs address, legal description, assessed values, and — most critically for
back-chain recovery — the **sale history** as a list of `SaleHistoryEntry`.

Tony Roveda Phase-1a directives, 2026-05-26:
  - APN from PA is the AUTHORITATIVE subject-property anchor
  - sale_history newest-first (index 0 = most recent / vesting deed)
  - pre-recorder-window deeds (older than the workflow's `start_date`)
    are recoverable here without extending the recorder search window
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Literal, Optional


# Status values returned by every PA adapter.
PropertyAppraiserStatus = Literal[
    "PA_SUCCESS",       # adapter returned a parcel + sale history
    "PA_NO_RESULTS",    # address/APN not found in PA database
    "PA_AMBIGUOUS",     # multiple candidates and we couldn't pick one
    "PA_FAILED",        # adapter hit an error (network, parse, etc.)
    "PA_NO_RUNNER",     # no PA adapter registered for this county
]


@dataclass
class SaleHistoryEntry:
    """One row of a PA's sale-history table. Newest-first ordering in the
    parent `PropertyAppraiserResult.sale_history` list.

    `deed_doc_number` and `deed_book_page` are mutually-exclusive: BCPA
    returns a single combined field (`bookAndPageOrCin1..5`) — adapters
    split into instrument # vs book/page based on the literal '/' delimiter.
    """
    sale_date: str = ""              # "MM/DD/YYYY"
    sale_price: int = 0              # 0 if non-sale conveyance or unknown
    deed_doc_number: str = ""        # recorder instrument # when PA cross-refs CIN
    deed_book_page: str = ""         # "OR BK 48462 PG 1410" or "48462 / 1410"
    deed_type: str = ""              # "WD" | "QCD" | "CT" | "SWD" | etc.
    grantor: str = ""                # often blank — BCPA doesn't return; recorder cross-ref fills
    grantee: str = ""                # ditto
    qualified: bool = False          # tax-roll "qualified sale" flag
    notes: str = ""                  # adapter-supplied free-text (e.g., verification status)


@dataclass
class PropertyAppraiserResult:
    """The full anchor record returned by Phase 1a.

    A successful lookup must populate at minimum: apn, owner_of_record,
    situs_address, legal_description, and (if available) sale_history.

    Adapters that can't populate a field MUST leave it at the default and
    add a note rather than fabricating a value.
    """
    apn: str = ""                              # canonical parcel ID (county-format)
    folio: str = ""                            # alternate parcel identifier
    pin: str = ""                              # alternate parcel identifier
    owner_of_record: str = ""                  # tax-roll vested owner (current)
    co_owners: List[str] = field(default_factory=list)
    situs_address: str = ""                    # appraiser's canonical subject address
    mailing_address: str = ""                  # owner mailing address (may differ from situs)
    legal_description: str = ""                # appraiser's short legal
    just_value: int = 0
    assessed_value: int = 0
    land_value: int = 0
    improvement_value: int = 0
    homestead_active: bool = False
    homestead_amount: int = 0
    year_built: int = 0
    living_area_sqft: int = 0
    sale_history: List[SaleHistoryEntry] = field(default_factory=list)
    source_url: str = ""                       # adapter's canonical landing URL for this parcel
    fetched_at: str = ""                       # ISO timestamp
    status: PropertyAppraiserStatus = "PA_FAILED"
    notes: str = ""

    # Reconciliation-friendly accessor — returns the deed_doc_number or
    # deed_book_page (whichever is populated) for use in cross-checking
    # against the recorder's documents_found.json.
    def deed_identifiers(self) -> List[str]:
        out: List[str] = []
        for s in self.sale_history:
            if s.deed_doc_number:
                out.append(s.deed_doc_number)
            elif s.deed_book_page:
                out.append(s.deed_book_page.replace(" ", ""))
        return out

    def to_dict(self) -> dict:
        return asdict(self)
