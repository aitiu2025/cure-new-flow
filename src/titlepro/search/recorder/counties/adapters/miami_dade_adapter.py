"""
Miami-Dade County (FL) Recorder Adapter — PROPRIETARY platform.

Backend: https://onlineservices.miamidadeclerk.gov/officialrecords/
Platform: custom (not in the Tyler/Landmark/OnceCare/DueProcess/Clericus families).

This adapter is in the **design phase**. Method bodies are stubbed and will
raise NotImplementedError until the live-portal probe captures the selectors.

Design inputs (read FIRST before filling in any method):
  - docs/FL/Miami_Dade_Indexing_Review.md (Tony Roveda, 2026-05-21) — single
    authoritative source for the platform's UX. Section "Adapter implications"
    enumerates the 8 concrete differences from the FL platform-family
    standards.
  - docs/implementation_references/CURE_Exam_Methodology_Guide.md — the
    cross-cutting abstractor methodology this adapter must operationalize.

Distinguishing platform behaviour (vs Tyler/Landmark/etc):
  1. Name search uses THREE discrete inputs — Last / First / Middle. Not
     the single "Last First" combined field used elsewhere. The adapter
     splits the input name string into the three fields.
  2. No platform-side Effective Date is exposed. Stamp the download
     timestamp as the effective date (matches Tyler/DueProcess pattern).
  3. Result image access is a TWO-CLICK flow: (a) row click opens the
     detail panel, (b) a separate hyperlink "Document Image" opens the
     image. Don't conflate the two.
  4. Doc Type appears in the result row — cheap pre-filter for deeds vs
     mortgages vs liens BEFORE pulling images.
  5. Result-set is sortable by date. Use date sort (desc) to put newest
     first (matches CURE chain-of-title "Newest to Oldest" rendering rule).
  6. Document images can lag indexing by ~3 days. Recent records may
     successfully read the index entry but fail image fetch. The download
     phase must distinguish "image-not-yet-available" (retryable, surface
     as pending) from a hard fetch failure. Config: `image_availability_lag_days`.
  7. No CAPTCHA called out by Tony — verify on first live run; if a
     passive challenge appears, fall through to a real-browser Playwright
     session (Clericus-style fallback).
  8. Parcel-ID search availability and Party-Type filter availability are
     UNKNOWN — flagged as open questions in the config and Tony follow-ups.

Commercial-access alternative (Tony's note, NOT yet decided):
  Tiered pricing: $1/exam, or 5000 exams for $500 ($0.10/exam) — bypasses
  any CAPTCHA. Worth a cost/effort comparison vs full custom scraper build.
"""

import time
from typing import Dict, List, Optional

from titlepro.search.recorder.base_recorder import (
    BaseRecorderSearch,
    DocumentRecord,
)


class MiamiDadeRecorderSearch(BaseRecorderSearch):
    """
    Custom adapter for the Miami-Dade Clerk Official Records portal.

    Skeleton-only — see module docstring for the live-probe requirements
    that must be satisfied before any method body is filled in.
    """

    DEFAULT_SELECTORS: Dict[str, str] = {
        "disclaimer_accept": "",
        "last_name_field": "",
        "first_name_field": "",
        "middle_name_field": "",
        "start_date_field": "",
        "end_date_field": "",
        "search_button": "",
        "result_rows": "",
        "result_row_doc_type_cell": "",
        "detail_open_selector": "",
        "image_open_selector": "",
        "no_results": "",
    }

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Miami-Dade")
        self._base_url = config.get("base_url", "")
        self._search_url = config.get("search_url", self._base_url)
        self._disclaimer_url = config.get("disclaimer_url", self._base_url)

        self.selectors = {**self.DEFAULT_SELECTORS}
        if "selectors" in config:
            self.selectors.update(config["selectors"])

        self.name_input_mode = config.get("name_input_mode", "split_lfm")
        self.effective_date_strategy = config.get(
            "effective_date_strategy", "download_timestamp"
        )
        self.image_availability_lag_days = int(
            config.get("image_availability_lag_days", 3)
        )
        self.captcha_required = bool(config.get("captcha_required", False))
        self.result_sort_field = config.get("result_sort_field", "date")
        self.result_sort_order = config.get("result_sort_order", "desc")
        self.doc_type_in_result_row = bool(
            config.get("doc_type_in_result_row", True)
        )

        self._disclaimer_accepted = False

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    def __enter__(self):
        self.setup_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        return False

    @staticmethod
    def split_name_lfm(name: str) -> Dict[str, str]:
        """Split a `LAST, FIRST [MIDDLE]` or `LAST FIRST MIDDLE` name string
        into discrete last / first / middle components for the three Miami-Dade
        name inputs. See `Miami_Dade_Indexing_Review.md` — Adapter implications #1.
        """
        if not name:
            return {"last": "", "first": "", "middle": ""}
        parts = [p.strip() for p in name.replace(",", " ").split() if p.strip()]
        if not parts:
            return {"last": "", "first": "", "middle": ""}
        last = parts[0]
        first = parts[1] if len(parts) > 1 else ""
        middle = " ".join(parts[2:]) if len(parts) > 2 else ""
        return {"last": last, "first": first, "middle": middle}

    def setup_driver(self):
        raise NotImplementedError(
            "Miami-Dade adapter: setup_driver not yet implemented. Requires "
            "live-portal probe to determine whether a stealth driver "
            "(undetected-chromedriver) is needed or vanilla Selenium suffices. "
            "See docs/FL/Miami_Dade_Indexing_Review.md (no CAPTCHA called "
            "out — confirm on first live run)."
        )

    def navigate_to_search(self):
        raise NotImplementedError(
            "Miami-Dade adapter: navigate_to_search not yet implemented. The "
            "disclaimer / landing-page flow has not been observed in this "
            "session. Capture it during the live probe and wire the "
            "`disclaimer_accept` selector + the path from landing -> name-search "
            "form."
        )

    def perform_search(
        self, name: str, party_type: str = "Grantor/Grantee"
    ) -> List[DocumentRecord]:
        raise NotImplementedError(
            "Miami-Dade adapter: perform_search not yet implemented. "
            "Distinct from other FL platforms — must fill THREE separate "
            "inputs (last_name_field, first_name_field, middle_name_field) "
            "via `split_name_lfm()`. Party-type filter availability is "
            "UNKNOWN (config.party_type_supported = 'unknown') — open "
            "question for Tony."
        )

    def extract_results(self) -> List[DocumentRecord]:
        raise NotImplementedError(
            "Miami-Dade adapter: extract_results not yet implemented. Doc "
            "Type appears in the result row (config.doc_type_in_result_row "
            "= true) — wire that into the standard DocumentRecord schema. "
            "Sort newest-first per CURE methodology."
        )

    def return_to_search(self):
        raise NotImplementedError(
            "Miami-Dade adapter: return_to_search not yet implemented."
        )

    def download_documents(self, case_dir: str, documents: List[DocumentRecord]):
        raise NotImplementedError(
            "Miami-Dade adapter: download_documents not yet implemented. "
            "Image access is a TWO-CLICK flow: (1) `detail_open_selector` "
            "(row click -> detail panel), (2) `image_open_selector` "
            "('Document Image' hyperlink). Documents recorded within the "
            "last image_availability_lag_days days may not yet have an "
            "image — return status='pending_image' rather than raising."
        )
