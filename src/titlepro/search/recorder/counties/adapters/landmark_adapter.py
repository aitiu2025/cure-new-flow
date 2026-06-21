"""
Landmark Web Official Records — HTTP-First Adapter.

Pure-Python (``curl_cffi`` + BeautifulSoup) adapter for the Landmark Web
recorder platform (the same Pioneer / Fidlar-derived stack used by ~16 FL
counties plus a handful in other states). First production target is
Palm Beach County (FL); the same code path is expected to unlock Lee,
Escambia, St. Johns, Clay, Hernando, Bay, Martin, Indian River, Citrus,
Flagler, Monroe, Walton, Wakulla, Levy, Okeechobee with a per-county JSON
config swap.

Platform fingerprints (verified live 2026-05-26 on Palm Beach + Lee):

* Landing page contains ``Landmark Web Official Records Search`` in <title>
  and a ``var site = encodeURI(...)`` bootstrap.
* Disclaimer is accepted via a HTTP POST to ``/Search/SetDisclaimer``
  with an empty body. Response body is empty but cookies are set.
* The search page is reached via
  ``/search/index?theme=.blue&section=searchCriteriaName``. Hitting it
  before SetDisclaimer returns a "Session Has Expired" stub.
* Whether reCAPTCHA is currently required is reported by a HTTP POST to
  ``/Search/ShowCaptcha`` (response body == "True" / "False"). Palm Beach
  returns ``True`` for every cold session; Lee likewise (2026-05-26).
* Name search is a HTTP POST to ``/Search/NameSearch`` with the criteria
  payload extracted from ``Scripts/search/index.js`` ``SetCriteria()`` —
  the ``g-recaptcha-response`` field is appended verbatim and the server
  returns 500 if it is missing OR if ``bookType`` is empty (must be ``"0"``
  for "All Books" — the default select value). The 500 is the same generic
  IIS error template either way (no "Invalid Captcha" hint).
* The NameSearch response itself contains only the DataTables WRAPPER
  (column headers, the ``oTable = $('#resultsTable').DataTable({...})``
  init block, and an inline ``_TOTAL_ records of N`` count). The actual
  document rows are fetched server-side via a SECOND POST to
  ``/Search/GetSearchResults`` with the DataTables draw/start/length
  payload. That second call returns JSON
  ``{draw, recordsTotal, recordsFiltered, data: [{...}]}``.
* Parcel-ID search is a HTTP POST to ``/Search/ParcelIdSearch`` with a
  smaller payload (``parcelId`` + dates + record count). Same captcha
  gate + same two-stage NameSearch / GetSearchResults flow.
* Per-row anchors trigger ``GetDetailSection(id, row, ...)`` which POSTs
  ``/Document/Index``.
* The reCAPTCHA sitekey is embedded in ``<div class="recaptchasection-Name
  recaptchasection" data-sitekey="...">`` on the search page.

This adapter mirrors the design of ``acclaimweb_http_adapter.py``:

* Subclasses ``BaseRecorderSearch`` so the registry plumbing is unchanged.
* All Selenium/Playwright ABC methods collapse to no-ops.
* Selectors and URLs come from the JSON config — no county-specific
  hard-coding. Adding a Wave-2 Landmark county is a config-only task.
* When CAPTCHA is required and either (a) no solver has been wired or
  (b) the configured solver has no ``CAPTCHA_API_KEY``, ``perform_search``
  sets ``self.last_failure = "needs_captcha"`` and returns ``[]`` so the
  upstream pipeline can branch to a manual checkpoint.

See ``docs/FL/FL_Platform_Examination_Guide.md`` Platform 1 for Tony
Roveda's examination notes that informed the design (Party Type=Both,
Last-First name format, parcel-ID fallback for common-name counties).
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests as _cffi_requests
from bs4 import BeautifulSoup

from titlepro.search.recorder.base_recorder import BaseRecorderSearch, DocumentRecord


# Default DataTables result-fetch endpoint. Landmark uses server-side
# DataTables mode: NameSearch returns the wrapper, GetSearchResults returns
# the row data as JSON.
_DEFAULT_GET_SEARCH_RESULTS_EP = "Search/GetSearchResults"

# Column indices for the GetSearchResults JSON payload, verified live against
# Palm Beach Landmark 2026-05-26. The JSON rows are dicts keyed by string
# column index. We map the indices we care about to DocumentRecord fields.
# NOTE: These are the Palm Beach / standard Landmark defaults. Some counties
# (e.g. Bay — older Landmark build) have a shorter row (26 cols vs 30+) and
# use different indices. Override via ``column_map`` in the county config.
_LANDMARK_COL_STATUS = "3"
_LANDMARK_COL_DIRECT_NAME = "4"
_LANDMARK_COL_REVERSE_NAME = "5"
_LANDMARK_COL_SEARCH_NAME = "6"
_LANDMARK_COL_RECORD_DATE = "7"
_LANDMARK_COL_LOCATION_HEADER = "8"
_LANDMARK_COL_DOC_TYPE = "9"
_LANDMARK_COL_BOOK_TYPE = "10"
_LANDMARK_COL_BOOK = "11"
_LANDMARK_COL_PAGE = "12"
_LANDMARK_COL_INSTRUMENT = "13"
_LANDMARK_COL_LEGAL = "15"
_LANDMARK_COL_PAGE_COUNT = "28"
_LANDMARK_COL_DOC_ID = "29"

# Default column map (Palm Beach layout). Overridable per county via
# ``column_map`` in the county JSON config.
_DEFAULT_COLUMN_MAP = {
    "direct_name":    _LANDMARK_COL_DIRECT_NAME,
    "reverse_name":   _LANDMARK_COL_REVERSE_NAME,
    "record_date":    _LANDMARK_COL_RECORD_DATE,
    "location_header": _LANDMARK_COL_LOCATION_HEADER,
    "doc_type":       _LANDMARK_COL_DOC_TYPE,
    "instrument":     _LANDMARK_COL_INSTRUMENT,
    "page_count":     _LANDMARK_COL_PAGE_COUNT,
    "doc_id":         _LANDMARK_COL_DOC_ID,
}

# Class-hint prefixes that the Landmark rowCallback strips off cell text.
# Always strip these before persisting values.
_LANDMARK_CELL_PREFIXES = (
    "nobreak_",
    "unclickable_",
    "hidden_",
    "legalfield_",
)


# Default Chrome impersonation profile. Palm Beach returns 200 on the first
# GET with chrome120; Lee sits behind Akamai and may need an alternative
# fingerprint (override via config["impersonate_profile"]).
DEFAULT_IMPERSONATE = "chrome120"

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}


class LandmarkAdapter(BaseRecorderSearch):
    """Pure-HTTP search adapter for the Landmark Web recorder platform."""

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        config: Dict,
        start_date: str = "01/01/2010",
        end_date: Optional[str] = None,
    ):
        super().__init__(start_date=start_date, end_date=end_date)
        self.config = config

        self._county_name = config.get("county_name", "Unknown")
        self._base_url = config.get("base_url", "").rstrip("/") + "/"
        # Landmark sometimes sits at a subpath (Lee: /LandMarkWeb/, Escambia:
        # /LandmarkWeb1.4.6.134/). The recorder_root MUST end in "/".
        recorder_root = config.get("recorder_root") or config.get("search_url") or self._base_url
        if not recorder_root.endswith("/"):
            recorder_root = recorder_root.rstrip("/") + "/"
        self._recorder_root = recorder_root

        # Per-county overridable endpoint suffixes (all relative to recorder_root)
        eps = config.get("landmark_endpoints", {})
        self._ep_disclaimer = eps.get("disclaimer", "Search/SetDisclaimer")
        self._ep_show_captcha = eps.get("show_captcha", "Search/ShowCaptcha")
        self._ep_name_search = eps.get("name_search", "Search/NameSearch")
        self._ep_parcel_search = eps.get("parcel_search", "Search/ParcelIdSearch")
        self._ep_book_page_search = eps.get("book_page_search", "Search/BookPageSearch")
        self._ep_detail = eps.get("detail", "Document/Index")
        self._ep_search_index = eps.get(
            "search_index",
            "search/index?theme=.blue&section=searchCriteriaName",
        )
        # Two-stage DataTables fetch — NameSearch primes the session, this
        # endpoint returns the actual row data as JSON.
        self._ep_get_search_results = eps.get(
            "get_search_results", _DEFAULT_GET_SEARCH_RESULTS_EP
        )

        # bookType select default. The visible <select id="bookType-name"> on
        # the search form defaults to value "0" (All Books). Sending an empty
        # string here triggers a server-side 500 even when the captcha token
        # is valid. Per-county overridable in case some Landmark tenants
        # default to a different code.
        self._default_book_type = str(config.get("default_book_type", "0"))

        # Party-type mapping. Landmark uses a numeric code in the request.
        # Tony Roveda: examiners should use 'Both' by default.
        self.party_type_map = config.get(
            "party_type_map",
            {
                "Both": "0",
                "All": "0",
                "Grantor/Grantee": "0",
                "Grantor": "1",          # Direct Name (the grantor side)
                "Grantee": "2",          # Reverse Name (the grantee side)
                "Direct Name": "1",
                "Reverse Name": "2",
            },
        )
        self.supported_party_types = config.get(
            "supported_party_types", ["Both", "Grantor", "Grantee"]
        )

        # matchType: 0=StartsWith 1=Contains 2=Equals. StartsWith is the
        # examiner default per Tony's guide.
        self._default_match_type = str(config.get("default_match_type", "0"))

        # Result cap selectable per request (200/700/3000/5000/10000)
        self._record_cap = str(config.get("record_cap", "200"))

        # Doc-number pattern. Palm Beach uses 8+ digit numbers (e.g. "20220123456").
        # Override via config when porting to another Landmark county.
        pat = config.get("doc_number_pattern") or r"^\d{4,}$"
        self._doc_number_re = re.compile(pat)

        # reCAPTCHA configuration
        self.captcha_required = bool(config.get("captcha_required", True))
        self._site_key_override: Optional[str] = config.get("recaptcha_site_key")
        self._site_key: Optional[str] = self._site_key_override
        self.allow_automated_captcha_solver = bool(
            config.get("allow_automated_captcha_solver", False)
        )
        self.captcha_solver = None
        # Track whether we've already verified ShowCaptcha for this session
        self._captcha_check_done = False

        # Sitekey acquisition strategy.
        #   "inline"       — sitekey is in the warmed search HTML (Palm Beach,
        #                    Martin). Default — matches the originally-validated
        #                    behavior.
        #   "async_scrape" — sitekey is rendered by JS after page load (Clay,
        #                    Hernando and the rest of the Wave-2 cohort). Adapter
        #                    falls back to a headless browser scrape when the
        #                    inline HTML doesn't carry data-sitekey.
        #   "none"         — county does not enforce reCAPTCHA (Bay). Skip
        #                    everything captcha-related.
        # Inferred from captcha_required when not explicitly set: True->inline
        # (back-compat), False->none.
        cfg_strategy = config.get("sitekey_strategy")
        if not cfg_strategy:
            cfg_strategy = "inline" if self.captcha_required else "none"
        self._sitekey_strategy = str(cfg_strategy).lower()
        # Normalize: strategy="none" implies captcha not required (Bay-style).
        # Keep the explicit config field authoritative when set; otherwise
        # downcast captcha_required so perform_search short-circuits cleanly.
        if self._sitekey_strategy == "none" and "captcha_required" not in config:
            self.captcha_required = False

        # Sidecar cache of scraped sitekeys (when sitekey_strategy=async_scrape
        # we don't want to fire up a headless browser on every search). Cache
        # is keyed by base_url so multiple counties don't collide. Defaults
        # to ~/.titlepro/landmark_sitekey_cache.json — overridable per-county.
        cache_cfg = config.get(
            "sitekey_cache_path", "~/.titlepro/landmark_sitekey_cache.json"
        )
        self._sitekey_cache_path = Path(os.path.expanduser(cache_cfg))
        # Cache TTL (days) — Google rarely rotates sitekeys but the cap is a
        # safety net.
        self._sitekey_cache_ttl_days = int(config.get("sitekey_cache_ttl_days", 30))

        # Cookie-jar reuse for Akamai-fronted Landmark tenants (Lee).
        # When set, warm_session must load these cookies from disk on EVERY
        # adapter call. The adapter never spawns a browser at run time — the
        # operator runs `tools/diagnostics/mint_lee_cookies.py` once.
        cookie_jar_cfg = config.get("cookie_jar_path")
        self._cookie_jar_path: Optional[Path] = (
            Path(os.path.expanduser(cookie_jar_cfg)) if cookie_jar_cfg else None
        )
        self._requires_warmed_cookies = bool(
            config.get("requires_warmed_cookies", False)
        )
        # Default Akamai cookie TTL (days). Akamai typically issues cookies
        # with a ~30-day lifetime.
        self._cookie_jar_ttl_days = int(config.get("cookie_jar_ttl_days", 30))

        # HTTP session with chrome impersonation (defeats Akamai on Lee and
        # other behind-CDN Landmark counties out of the box).
        impersonate_profile = config.get("impersonate_profile", DEFAULT_IMPERSONATE)
        self.session = _cffi_requests.Session(impersonate=impersonate_profile)
        self.session.headers.update(EXTRA_HEADERS)

        self._session_warmed: bool = False
        self.last_failure: Optional[str] = None

        # download_pdf state — Landmark serves document images as per-page PNGs
        # via `Document/GetDocumentImage/?documentId={internal_id}&index=0&pageNum={N}&type=normal`.
        # The internal_id is column 29 (`hidden_<id>`) of the search results,
        # NOT the indexed instrument number. We map instrument # -> internal id
        # while extracting rows so download_pdf can look up the right id later.
        self._doc_id_by_number: Dict[str, str] = {}

        # Page-image endpoint, configurable per Landmark tenant.
        self._ep_get_image = eps.get("get_document_image", "Document/GetDocumentImage/")

        # PDF-assembly tunables.
        self._pdf_max_pages = int(config.get("pdf_max_pages", 200))
        self._pdf_fetch_retries = int(config.get("pdf_fetch_retries", 3))
        self._pdf_retry_delay_seconds = float(config.get("pdf_retry_delay_seconds", 1.5))
        # If True the adapter writes a raw .png alongside the stitched .pdf for
        # easier debugging. Off by default — production cases don't need it.
        self._pdf_keep_page_images = bool(config.get("pdf_keep_page_images", False))

        # Per-county column map (overridable via config["column_map"]).
        # Merges caller's overrides into the class-level defaults so counties
        # that only differ on a few columns don't need to replicate the full map.
        col_overrides = config.get("column_map") or {}
        self._col = {**_DEFAULT_COLUMN_MAP, **{k: str(v) for k, v in col_overrides.items()}}

        # reCAPTCHA v3 support (Bay County uses v3 server-side even though
        # ShowCaptcha returns False for the v2 widget). When captcha_type is
        # "recaptcha_v3", the adapter uses solve_recaptcha_v3() instead of v2.
        self._captcha_type = str(config.get("captcha_type", "recaptcha_v2")).lower()
        self._recaptcha_v3_action = str(config.get("recaptcha_v3_action", "submit"))
        # v3 sitekey may differ from v2 sitekey
        v3_key = config.get("recaptcha_sitekey_v3") or config.get("recaptcha_site_key")
        self._site_key_v3: Optional[str] = v3_key or None

        # Pipeline mode: when True, _async_scrape_sitekey will NOT launch a
        # headless browser (Selenium). In pipeline mode the sitekey must come
        # from the cache or inline HTML — a missing sitekey sets last_failure
        # and returns [] rather than blocking the pipeline on a browser scrape.
        # Set via config["pipeline_mode"] = true, OR via the "no_browser" alias.
        self._pipeline_mode: bool = bool(
            config.get("pipeline_mode") or config.get("no_browser", False)
        )

        # ABC compliance
        self.driver = None

    # --------------------------------------------------- BaseRecorderSearch props

    @property
    def county_name(self) -> str:
        return self._county_name

    @property
    def base_url(self) -> str:
        return self._base_url

    # --------------------------------------- ABC no-ops (Selenium-only contract)

    def setup_driver(self):
        return None

    def navigate_to_search(self):
        return None

    def return_to_search(self):
        return None

    # ----------------------------------------------- solver hookup (registry-callable)

    def set_captcha_solver(self, solver) -> None:
        """Wire a 2Captcha/Anti-Captcha solver instance.

        Only honored when the county config opts in via
        ``allow_automated_captcha_solver: true`` (mirrors Tyler adapter).
        """
        if self.allow_automated_captcha_solver:
            self.captcha_solver = solver
            return
        print(
            f"Automated CAPTCHA solver ignored for {self.county_name} County. "
            "Set allow_automated_captcha_solver=true in county config to enable."
        )

    # ------------------------------------------------------ session warm-up

    def warm_session(self) -> bool:
        """Bootstrap the session: GET landing -> POST disclaimer -> GET search index.

        After this returns True, ``self.session`` carries ``ASP.NET_SessionId``
        + the load-balancer cookie required for subsequent search POSTs.
        On failure ``self.last_failure`` is set to the appropriate sentinel.

        Sitekey resolution honors ``self._sitekey_strategy``:
          * ``"none"`` — skip sitekey work entirely (Bay).
          * ``"inline"`` — scrape from landing + search HTML (Palm Beach, Martin).
          * ``"async_scrape"`` — fall back to a headless-browser scrape when the
             inline HTML doesn't carry data-sitekey (Clay, Hernando, etc.). The
             scraped sitekey is cached on disk so subsequent searches in the
             same session (and subsequent process runs) don't pay the browser
             cost.

        Akamai cookie reuse: when the county config sets
        ``requires_warmed_cookies: true`` AND ``cookie_jar_path``, this method
        loads cookies from disk before the landing GET. If the file is missing
        or stale, ``last_failure="needs_cookie_mint"`` is set and the method
        returns False with a clear error message pointing at
        ``tools/diagnostics/mint_lee_cookies.py``.
        """
        # Akamai cookie precondition (Lee). MUST run before any HTTP call so
        # the Akamai edge sees a returning client.
        if self._requires_warmed_cookies:
            if not self._load_persisted_cookies():
                # _load_persisted_cookies has already set last_failure +
                # printed a clear next-step pointer.
                return False

        try:
            landing = self.session.get(self._base_url, timeout=30)
        except Exception as exc:
            print(f"  [warm_session] landing GET failed: {exc}")
            self.last_failure = "needs_session_token"
            return False

        if landing.status_code != 200:
            print(f"  [warm_session] landing returned {landing.status_code}")
            if self._requires_warmed_cookies and landing.status_code in (401, 403):
                # Akamai rejected even our cached cookies — they're stale.
                self.last_failure = "needs_cookie_mint"
                print(
                    "  [warm_session] Akamai rejected cached cookies — "
                    "re-run tools/diagnostics/mint_lee_cookies.py"
                )
            else:
                self.last_failure = "needs_session_token"
            return False

        # Inline-sitekey scrape from landing (only if strategy permits captcha).
        if self._sitekey_strategy != "none" and not self._site_key:
            self._site_key = self._scrape_sitekey(landing.text)

        # POST the disclaimer accept. Empty body, XHR header so server treats
        # us as the JS modal click.
        try:
            disc = self.session.post(
                self._url(self._ep_disclaimer),
                data={},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._base_url,
                },
                timeout=30,
            )
        except Exception as exc:
            print(f"  [warm_session] disclaimer POST failed: {exc}")
            self.last_failure = "needs_session_token"
            return False

        if disc.status_code not in (200, 204):
            print(f"  [warm_session] disclaimer returned {disc.status_code}")
            self.last_failure = "needs_session_token"
            return False

        # Now GET the search index. Sets the session up for the name-search
        # POST and gives us the recaptcha sitekey we need for 2Captcha.
        # The search-index page is ~2.5 MB; over a slow cross-region link
        # (e.g. a non-US VPN egress reaching the US-only portal) the default
        # 30s can time out mid-transfer even though bytes ARE flowing. Use a
        # longer ceiling here — a true geo/TCP drop fails at connect, not
        # mid-body, so this only helps the slow-but-progressing case.
        try:
            search_page = self.session.get(
                self._url(self._ep_search_index),
                timeout=90,
                headers={
                    "Referer": self._base_url,
                    # Force compression — the search-index page is ~2.5 MB
                    # uncompressed and stalls mid-stream over a slow/unstable
                    # cross-region link; gzip cuts it to a few hundred KB.
                    "Accept-Encoding": "gzip, deflate, br",
                },
            )
        except Exception as exc:
            print(f"  [warm_session] search-index GET failed: {exc}")
            self.last_failure = "needs_session_token"
            return False

        if search_page.status_code != 200:
            # 403 is the Akamai/Cloudflare signal — fingerprint mismatch.
            if search_page.status_code == 403:
                if self._requires_warmed_cookies:
                    self.last_failure = "needs_cookie_mint"
                    print(
                        "  [warm_session] 403 on search index with cached cookies — "
                        "re-run tools/diagnostics/mint_lee_cookies.py"
                    )
                else:
                    self.last_failure = "needs_session_token"
            else:
                self.last_failure = f"http_{search_page.status_code}"
            print(
                f"  [warm_session] search index returned {search_page.status_code}"
            )
            return False

        # Stage A — inline-HTML scrape from the warmed search page.
        if self._sitekey_strategy != "none" and not self._site_key:
            self._site_key = self._scrape_sitekey(search_page.text)

        # Stage B — async-scrape fallback when configured AND inline came up
        # empty. This is the new Wave-2 path; without it, 14 of the 15 newly-
        # onboarded counties would submit a placeholder Palm Beach sitekey
        # that 2Captcha rejects.
        if (
            self._sitekey_strategy == "async_scrape"
            and not self._site_key
        ):
            cached = self._load_cached_sitekey()
            if cached:
                self._site_key = cached
                print(
                    f"  [warm_session] loaded cached sitekey for {self._county_name}: "
                    f"{cached[:10]}..."
                )
            else:
                scraped = self._async_scrape_sitekey()
                if scraped:
                    self._site_key = scraped
                    self._save_cached_sitekey(scraped)
                    print(
                        f"  [warm_session] async-scraped sitekey for "
                        f"{self._county_name}: {scraped[:10]}... (cached)"
                    )
                else:
                    print(
                        f"  [warm_session] async sitekey scrape returned nothing — "
                        f"captcha solve will be skipped (placeholder sitekey will "
                        f"likely be rejected by 2Captcha)"
                    )

        self._session_warmed = True
        return True

    @staticmethod
    def _scrape_sitekey(html: str) -> Optional[str]:
        """Extract the data-sitekey from the recaptcha section divs."""
        if not html:
            return None
        m = re.search(r'data-sitekey="([0-9A-Za-z_-]{30,})"', html)
        return m.group(1) if m else None

    # ------------------------------------------------ sitekey async-scrape (Wave-2)

    def _load_cached_sitekey(self) -> Optional[str]:
        """Load a previously-scraped sitekey for ``self._base_url`` from disk.

        Returns None if the cache file doesn't exist, the entry is missing,
        or the entry is older than ``self._sitekey_cache_ttl_days``.
        """
        try:
            if not self._sitekey_cache_path.exists():
                return None
            with self._sitekey_cache_path.open("r") as f:
                cache = json.load(f)
        except Exception:
            return None
        entry = cache.get(self._base_url)
        if not entry or not isinstance(entry, dict):
            return None
        cached_at_iso = entry.get("cached_at", "")
        try:
            cached_at = datetime.fromisoformat(cached_at_iso)
        except Exception:
            return None
        if datetime.now() - cached_at > timedelta(days=self._sitekey_cache_ttl_days):
            return None
        return entry.get("sitekey") or None

    def _save_cached_sitekey(self, sitekey: str) -> None:
        """Persist a freshly-scraped sitekey under ``self._base_url``."""
        try:
            self._sitekey_cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache: Dict[str, Dict[str, str]] = {}
            if self._sitekey_cache_path.exists():
                try:
                    with self._sitekey_cache_path.open("r") as f:
                        cache = json.load(f) or {}
                except Exception:
                    cache = {}
            cache[self._base_url] = {
                "sitekey": sitekey,
                "cached_at": datetime.now().isoformat(),
                "county": self._county_name,
            }
            with self._sitekey_cache_path.open("w") as f:
                json.dump(cache, f, indent=2)
        except Exception as exc:
            print(f"  [sitekey_cache] failed to persist: {exc}")

    def _async_scrape_sitekey(self) -> Optional[str]:
        """Open a headless browser, render the search page, return data-sitekey.

        Used by counties whose recaptcha widget is rendered async by JS after
        page load (Clay, Hernando, Citrus and the rest of the Wave-2 cohort —
        14 of 15). The fallback runs ONLY when:
          * ``sitekey_strategy == "async_scrape"``, AND
          * the inline-HTML scrape returned nothing, AND
          * no cached sitekey is available for ``self._base_url``.

        Result is cached on disk so subsequent searches don't pay the
        browser cost. Returns None on any failure (browser missing, page
        timed out, sitekey never rendered) — caller will print a warning
        and fall back to the (likely-stale) configured sitekey.

        **Pipeline-mode guard**: when ``self._pipeline_mode`` is True (set via
        config ``pipeline_mode`` or ``no_browser``), this method will NOT launch
        a headless Selenium browser. It sets ``last_failure="needs_sitekey_mint"``
        and returns None so the operator knows they must pre-populate the sitekey
        cache using the standalone mint tool before running the pipeline.
        """
        # Guard: pipeline/no_browser mode — do not start Selenium at runtime.
        if self._pipeline_mode:
            self.last_failure = "needs_sitekey_mint"
            print(
                f"  [landmark/{self._county_name}] pipeline_mode=True — "
                "skipping async Selenium sitekey scrape. "
                "Pre-populate the sitekey cache with tools/diagnostics/mint_landmark_sitekey.py "
                "or set sitekey_strategy=inline in the county config."
            )
            return None

        # Selenium is the only browser-driver in requirements.txt; we lazy-
        # import so non-async-scrape counties don't pay the import cost.
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            print(
                "  [async_scrape] Selenium not installed — cannot async-scrape "
                "sitekey. Install selenium or pre-populate sitekey_cache_path."
            )
            return None

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--window-size=1280,800")
        # Mirror our curl_cffi UA so the server emits the same widget variant.
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        driver = None
        try:
            driver = webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(45)
            driver.get(self._base_url)
            # Most Landmark deploys land directly on a disclaimer modal — we
            # don't click it; the modal markup still contains the sitekey on
            # the underlying search form once JS runs.
            try:
                driver.get(self._url(self._ep_search_index))
            except Exception:
                pass
            # Wait up to 15s for the recaptcha widget to render.
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-sitekey]")
                    )
                )
            except Exception:
                pass
            html = ""
            try:
                html = driver.page_source
            except Exception:
                pass
            if not html:
                return None
            return self._scrape_sitekey(html)
        except Exception as exc:
            print(f"  [async_scrape] browser scrape failed: {exc}")
            return None
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    # ----------------------------------------------- persisted-cookie loader (Lee)

    def _load_persisted_cookies(self) -> bool:
        """Load Akamai cookies from ``self._cookie_jar_path`` into the session.

        Returns True on success, False on any failure with ``last_failure``
        set to ``"needs_cookie_mint"`` and a clear next-step printed.

        The jar payload mirrors the Broward acclaim format::

            {
              "minted_at":  "<iso8601>",
              "expires_at": "<iso8601>",  # optional — when missing we fall
                                          # back to cookie_jar_ttl_days
              "domain":     "<host>",     # informational only
              "cookies": [
                {"name": "...", "value": "...", "domain": "...", "path": "/"}
              ]
            }
        """
        if not self._cookie_jar_path:
            self.last_failure = "needs_cookie_mint"
            print(
                f"  [warm_session] {self._county_name} requires warmed cookies "
                "but cookie_jar_path is not configured. Add it to the county "
                "JSON config."
            )
            return False

        if not self._cookie_jar_path.exists():
            self.last_failure = "needs_cookie_mint"
            print(
                f"  [warm_session] cookie jar missing at {self._cookie_jar_path}.\n"
                f"  Run once interactively:\n"
                f"      python3 tools/diagnostics/mint_lee_cookies.py\n"
                f"  Then re-run this search."
            )
            return False

        try:
            with self._cookie_jar_path.open("r") as f:
                payload = json.load(f)
        except Exception as exc:
            self.last_failure = "needs_cookie_mint"
            print(
                f"  [warm_session] cookie jar at {self._cookie_jar_path} is "
                f"unreadable ({exc}). Re-mint via "
                "tools/diagnostics/mint_lee_cookies.py."
            )
            return False

        # Expiry check — prefer explicit expires_at; fall back to TTL since minted_at.
        exp_str = payload.get("expires_at")
        minted_str = payload.get("minted_at")
        expired = False
        try:
            if exp_str:
                expired = datetime.fromisoformat(exp_str) < datetime.now()
            elif minted_str:
                expired = (
                    datetime.fromisoformat(minted_str)
                    + timedelta(days=self._cookie_jar_ttl_days)
                    < datetime.now()
                )
        except Exception:
            expired = False  # If we can't parse, fall through and let the
                              # server reject — better than blocking unnecessarily.
        if expired:
            self.last_failure = "needs_cookie_mint"
            print(
                f"  [warm_session] cookie jar at {self._cookie_jar_path} has "
                "expired. Re-run tools/diagnostics/mint_lee_cookies.py."
            )
            return False

        cookies = payload.get("cookies") or []
        if not cookies:
            self.last_failure = "needs_cookie_mint"
            print(
                f"  [warm_session] cookie jar at {self._cookie_jar_path} is "
                "empty. Re-run tools/diagnostics/mint_lee_cookies.py."
            )
            return False

        loaded = 0
        for c in cookies:
            try:
                self.session.cookies.set(
                    c.get("name"),
                    c.get("value"),
                    domain=c.get("domain"),
                    path=c.get("path", "/"),
                )
                loaded += 1
            except Exception:
                continue
        print(
            f"  [warm_session] loaded {loaded} Akamai cookies from "
            f"{self._cookie_jar_path}"
        )
        return loaded > 0

    def _url(self, suffix: str) -> str:
        """Resolve an endpoint suffix against the recorder_root."""
        if suffix.startswith("http://") or suffix.startswith("https://"):
            return suffix
        return self._recorder_root + suffix.lstrip("/")

    def _resolve_captcha_token(self) -> Optional[str]:
        """Return a fresh ``g-recaptcha-response`` token, or None.

        Falls back to None when:
          - The site reports ShowCaptcha=False (no captcha needed)
          - No solver is wired AND no API key is configured
          - The solver throws (network, balance, etc.)

        Caller (``perform_search``) interprets None to mean "manual
        checkpoint required" and sets ``last_failure = "needs_captcha"``.
        """
        # Counties with sitekey_strategy="none" and captcha_type="recaptcha_v3"
        # still need a token — they use v3 server-side even though ShowCaptcha
        # returns False (Bay County). Skip the short-circuit for v3.
        if self._sitekey_strategy == "none" and self._captcha_type != "recaptcha_v3":
            return ""

        # Ask the server whether captcha is currently required. ShowCaptcha
        # is a cheap GET-equivalent — flagged in Landmark JS as ``$.post``
        # but it accepts empty bodies.
        # SKIP for v3 counties (Bay): ShowCaptcha only governs the v2 widget;
        # it returns "False" even when v3 is enforced server-side on NameSearch.
        if not self._captcha_check_done and self._captcha_type != "recaptcha_v3":
            try:
                resp = self.session.post(
                    self._url(self._ep_show_captcha),
                    data={},
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": self._url(self._ep_search_index),
                    },
                    timeout=15,
                )
                self._captcha_check_done = True
                if resp.status_code == 200 and resp.text.strip().lower() == "false":
                    # Server has cleared us — no token needed.
                    return ""
            except Exception:
                pass

        if not self.captcha_solver:
            return None

        page_url = self._url(self._ep_search_index)

        # reCAPTCHA v3 path (Bay County and similar). Use the v3 sitekey and
        # solve_recaptcha_v3() so 2Captcha workers get the right task type.
        if self._captcha_type == "recaptcha_v3":
            site_key = self._site_key_v3 or self._site_key
            if not site_key:
                print("  [landmark] reCAPTCHA v3 site_key not configured; cannot solve")
                return None
            try:
                token = self.captcha_solver.solve_recaptcha_v3(
                    site_key, page_url, action=self._recaptcha_v3_action
                )
            except Exception as exc:
                print(f"  [landmark] captcha v3 solver raised: {exc}")
                return None
            return token

        if not self._site_key:
            print("  [landmark] reCAPTCHA site_key not discovered; cannot solve")
            return None

        try:
            token = self.captcha_solver.solve_recaptcha_v2(self._site_key, page_url)
        except Exception as exc:
            print(f"  [landmark] captcha solver raised: {exc}")
            return None
        return token

    # ----------------------------------------------------------------- search

    def perform_search(
        self,
        name: str,
        party_type: str = "Both",
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Pure-HTTP name search against Landmark's ``/Search/NameSearch``.

        Returns ``[]`` (with ``self.last_failure`` set) on:
          * Session that won't warm (network / Akamai / disclaimer rejection)
          * CAPTCHA required but no solver wired (``needs_captcha``)
          * Server 500 response (typically empty captcha token rejected)
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [perform_search] session not warmed; last_failure={self.last_failure}"
                )
                return []

        mapped_party = self.party_type_map.get(party_type, "0")

        token = ""
        if self.captcha_required:
            token = self._resolve_captcha_token() or ""
            if not token:
                self.last_failure = "needs_captcha"
                print(
                    f"  [perform_search] reCAPTCHA token unavailable for {self.county_name}; "
                    "set CAPTCHA_API_KEY + allow_automated_captcha_solver:true to auto-solve."
                )
                return []

        payload = {
            "searchLikeType": self._default_match_type,
            "type": mapped_party,
            "name": name,
            "doctype": doc_type or "",
            # bookType default MUST be "0" (All Books) — the select's first
            # option value. Empty string triggers a 500 in the controller's
            # model binder. Configurable via `default_book_type` if some
            # other Landmark tenant defaults to a different code.
            "bookType": self._default_book_type,
            "beginDate": date_from or self.start_date,
            "endDate": date_to or self.end_date,
            "recordCount": self._record_cap,
            "exclude": "false",
            "ReturnIndexGroups": "false",
            "townName": "",
            "selectedNamesIds": "",
            "includeNickNames": "false",
            "selectedNames": "",
            "mobileHomesOnly": "false",
            "g-recaptcha-response": token,
        }

        try:
            resp = self.session.post(
                self._url(self._ep_name_search),
                data=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                    "Origin": self._base_url.rstrip("/"),
                },
                timeout=60,
            )
        except Exception as exc:
            print(f"  [perform_search] POST raised: {exc}")
            self.last_failure = "network_error"
            return []

        if resp.status_code == 500:
            # The 500 generic IIS error template comes back for ANY model-
            # binding failure inside the NameSearch controller. The two most
            # common causes are: (a) bookType="" (fixed above), (b) missing
            # or rejected g-recaptcha-response. Surface as needs_captcha so
            # the pipeline can branch to manual.
            self.last_failure = "needs_captcha"
            print("  [perform_search] HTTP 500 from NameSearch (likely captcha or bad bookType)")
            return []
        if resp.status_code != 200:
            self.last_failure = f"http_{resp.status_code}"
            print(f"  [perform_search] HTTP {resp.status_code} from NameSearch")
            return []
        if "Invalid Captcha" in resp.text:
            self.last_failure = "invalid_captcha"
            print("  [perform_search] Server rejected captcha token")
            return []

        # NameSearch returned 200 with the DataTables wrapper. The actual
        # row data lives in a follow-up POST to GetSearchResults — Landmark
        # uses DataTables in server-side mode.
        record_count = self._scrape_total_count(resp.text)
        if record_count == 0:
            return []
        return self._fetch_data_rows(
            record_count_hint=record_count or int(self._record_cap)
        )

    # ----------------------------------------------------- parcel search (fallback)

    def perform_parcel_search(
        self,
        parcel_id: str,
        doc_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Parcel-ID search — Tony Roveda's recommended fallback when name
        search hits the result cap on common surnames. Mirrors
        ``SetCriteria/ParcelIdSearch`` in ``Scripts/search/index.js``.
        """
        if not self._session_warmed and not self.warm_session():
            return []

        token = ""
        if self.captcha_required:
            token = self._resolve_captcha_token() or ""
            if not token:
                self.last_failure = "needs_captcha"
                return []

        payload = {
            "searchLikeType": self._default_match_type,
            "parcelId": parcel_id,
            "doctype": doc_type or "",
            "bookType": self._default_book_type,
            "beginDate": date_from or self.start_date,
            "endDate": date_to or self.end_date,
            "exclude": "false",
            "ReturnIndexGroups": "false",
            "recordCount": self._record_cap,
            "townName": "",
            "mobileHomesOnly": "false",
            "g-recaptcha-response": token,
        }

        try:
            resp = self.session.post(
                self._url(self._ep_parcel_search),
                data=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                    "Origin": self._base_url.rstrip("/"),
                },
                timeout=60,
            )
        except Exception as exc:
            print(f"  [perform_parcel_search] POST raised: {exc}")
            self.last_failure = "network_error"
            return []

        if resp.status_code != 200:
            self.last_failure = f"http_{resp.status_code}"
            return []
        record_count = self._scrape_total_count(resp.text)
        if record_count == 0:
            return []
        return self._fetch_data_rows(
            record_count_hint=record_count or int(self._record_cap)
        )

    # ----------------------------------------------------- book/page search

    def perform_book_page_search(
        self,
        book: str,
        page: str,
        book_type: Optional[str] = None,
        record_count: Optional[str] = None,
    ) -> List[DocumentRecord]:
        """Direct Book / Page retrieval against Landmark ``/Search/BookPageSearch``.

        Mirrors the JS ``SetCriteria`` payload (verified live 2026-05-26 on
        Palm Beach Landmark)::

            { bookType, book, page, exclude, ReturnIndexGroups, recordCount,
              mobileHomesOnly, g-recaptcha-response }

        This is the canonical way to recover pre-recorder-search-window deeds
        (i.e. anything older than the ``start_date`` configured for the
        recorder search). Vesting deeds from the 1990s are typically only
        reachable via Book / Page direct retrieval — Landmark / Acclaim /
        Tyler all index documents back to inception, but the date-range filter
        on name search blocks out the older ones. Book / Page search has NO
        date-range filter (the book is already a temporal identifier).

        Returns ``[]`` (with ``self.last_failure`` set) on:
          * Session that won't warm
          * CAPTCHA required but no solver wired (``needs_captcha``)
          * Server 500 (typically captcha rejection)
        """
        if not self._session_warmed:
            if not self.warm_session():
                print(
                    f"  [book_page_search] session not warmed; last_failure={self.last_failure}"
                )
                return []

        token = ""
        if self.captcha_required:
            token = self._resolve_captcha_token() or ""
            if not token:
                self.last_failure = "needs_captcha"
                print(
                    f"  [book_page_search] reCAPTCHA token unavailable for "
                    f"{self.county_name}; set CAPTCHA_API_KEY + "
                    "allow_automated_captcha_solver:true to auto-solve."
                )
                return []

        payload = {
            "bookType": str(book_type) if book_type is not None else self._default_book_type,
            "book": str(book),
            "page": str(page),
            "exclude": "false",
            "ReturnIndexGroups": "false",
            "recordCount": str(record_count or self._record_cap),
            "mobileHomesOnly": "false",
            "g-recaptcha-response": token,
        }

        try:
            resp = self.session.post(
                self._url(self._ep_book_page_search),
                data=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                    "Origin": self._base_url.rstrip("/"),
                },
                timeout=60,
            )
        except Exception as exc:
            print(f"  [book_page_search] POST raised: {exc}")
            self.last_failure = "network_error"
            return []

        if resp.status_code == 500:
            self.last_failure = "needs_captcha"
            print(
                "  [book_page_search] HTTP 500 (likely captcha rejection or bad "
                f"payload) — body snippet: {resp.text[:300]!r}"
            )
            return []
        if resp.status_code != 200:
            self.last_failure = f"http_{resp.status_code}"
            print(f"  [book_page_search] HTTP {resp.status_code}")
            return []
        if "Invalid Captcha" in resp.text:
            self.last_failure = "invalid_captcha"
            print("  [book_page_search] Server rejected captcha token")
            return []

        record_count_actual = self._scrape_total_count(resp.text)
        if record_count_actual == 0:
            return []
        return self._fetch_data_rows(
            record_count_hint=record_count_actual or int(self._record_cap)
        )

    # --------------------------------------- DataTables two-stage fetch helpers

    @staticmethod
    def _scrape_total_count(name_search_html: str) -> int:
        """Pull the total record count from the inline ``records of N`` text.

        Landmark embeds the count in the DataTables language config of the
        NameSearch response::

            "info": "<b ...>Returned " + '_TOTAL_ records of 6</b>",

        Returns 0 when the text matches ``Returned 0 records`` / ``infoEmpty``
        / no-results-banner cases, ``-1`` when the count could not be parsed
        (caller should default to ``record_cap`` so we still try the
        DataTables fetch).
        """
        if not name_search_html:
            return 0
        # Explicit "no results" wording from DataTables config
        if "infoEmpty" in name_search_html and "records of 0</b>" in name_search_html:
            return 0
        m = re.search(r"records of\s*(\d+)\s*</b>", name_search_html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return -1
        # Some Landmark tenants omit the count entirely on zero-result pages
        # but emit a clearly empty body
        if "No records found" in name_search_html or "zeroRecords" in name_search_html and len(name_search_html) < 5000:
            return 0
        return -1

    def _fetch_data_rows(self, record_count_hint: int = 200) -> List[DocumentRecord]:
        """POST to ``/Search/GetSearchResults`` and parse the JSON rows.

        Landmark uses DataTables in server-side mode — the actual document
        data comes from this follow-up call, NOT from the NameSearch
        response body. The DataTables payload is the standard:
        ``draw, start, length, search[value], search[regex], time``.
        """
        # Capped at record_cap to avoid pulling more than the user asked for.
        try:
            cap = int(self._record_cap)
        except (TypeError, ValueError):
            cap = 200
        length = max(1, min(record_count_hint or cap, cap))

        dt_payload = {
            "draw": "1",
            "start": "0",
            "length": str(length),
            "search[value]": "",
            "search[regex]": "false",
            "time": str(int(time.time() * 1000)),
        }
        try:
            resp = self.session.post(
                self._url(self._ep_get_search_results),
                data=dt_payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                    "Origin": self._base_url.rstrip("/"),
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=60,
            )
        except Exception as exc:
            print(f"  [_fetch_data_rows] POST raised: {exc}")
            self.last_failure = "network_error"
            return []

        if resp.status_code != 200:
            self.last_failure = f"http_{resp.status_code}"
            print(f"  [_fetch_data_rows] HTTP {resp.status_code} from GetSearchResults")
            return []

        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            # Some servers return JSON in resp.text only — fall back to manual parse.
            try:
                payload = json.loads(resp.text)
            except Exception:
                print(f"  [_fetch_data_rows] non-JSON response: {exc}")
                self.last_failure = "bad_response"
                return []

        rows = payload.get("data") or []
        out: List[DocumentRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rec = self._row_to_document_record(row)
            # Populate the doc_id cache so download_pdf can resolve
            # instrument # -> Landmark internal documentId.
            # Use per-county doc_id column (default "29", Bay uses "25").
            internal_id = self._clean_cell(row.get(self._col["doc_id"], ""))
            if not internal_id:
                # Fallback: extract from DT_RowId = "doc_<id>_<row>"
                row_id = str(row.get("DT_RowId", ""))
                if row_id.startswith("doc_"):
                    internal_id = row_id[len("doc_"):].split("_")[0]
            if rec.document_number and internal_id:
                self._doc_id_by_number[rec.document_number] = internal_id
            out.append(rec)
        return out

    @staticmethod
    def _clean_cell(value) -> str:
        """Strip Landmark's class-hint prefixes from a cell value.

        Cells in the DataTables JSON arrive with optional prefixes like
        ``nobreak_``, ``unclickable_``, ``hidden_``, ``legalfield_`` that the
        Landmark rowCallback uses to decide CSS classes. These are not part
        of the actual data.
        """
        if value is None:
            return ""
        if not isinstance(value, str):
            return str(value)
        v = value
        for pfx in _LANDMARK_CELL_PREFIXES:
            if v.startswith(pfx):
                v = v[len(pfx):]
                break
        return v.strip()

    def _row_to_document_record(self, row: Dict) -> DocumentRecord:
        """Convert a single GetSearchResults JSON row into a DocumentRecord.

        Column indices default to Palm Beach Landmark 2026-05-26 layout but
        are overridable per county via ``self._col`` (populated from the JSON
        config's ``column_map`` key). This fixes older Landmark builds like Bay
        County that have a 26-column row instead of Palm Beach's 30-column row.

        Doc number resolution order:
          1. Instrument column (config-driven, default col 13) — the indexed
             human-readable number (e.g. ``20190401915``) used in reports.
          2. DT_RowId attribute (``doc_<internalId>_<row>``) — the Landmark
             internal numeric ID, usable as instrument # when col 13 is absent.
          3. doc_id column (config-driven, default col 29) as last resort.

        For Bay County (26-col layout): instrument = col 12, doc_id = col 25.
        Configure via ``"column_map": {"instrument": "12", "doc_id": "25", ...}``.
        """
        def get(idx: str) -> str:
            return self._clean_cell(row.get(idx, ""))

        col = self._col  # per-county column map

        # Instrument number (human-readable, e.g. "20190401915")
        doc_num = get(col["instrument"])
        # Fallback: DT_RowId carries internal id (numeric); use when col is empty
        # or when col lands on legal description (older Landmark: col 13 = legal)
        if not doc_num or (doc_num and len(doc_num) > 30 and " " in doc_num):
            row_id = str(row.get("DT_RowId", ""))
            if row_id.startswith("doc_"):
                doc_num = row_id[len("doc_"):].split("_")[0]
        if not doc_num:
            doc_num = get(col["doc_id"])

        # Names — Landmark embeds <div class='nameSeperator'></div> between
        # multiple parties; strip the HTML to leave human-readable strings.
        def strip_html(s: str) -> str:
            if not s:
                return s
            # Replace separator div with semicolon for easy grep
            s = re.sub(
                r"<div\s+class=['\"]nameSeperator['\"][^>]*>\s*</div>",
                "; ",
                s,
            )
            # Drop any remaining HTML tags
            s = re.sub(r"<[^>]+>", "", s)
            return re.sub(r"\s+", " ", s).strip()

        direct_name = strip_html(get(col["direct_name"]))
        reverse_name = strip_html(get(col["reverse_name"]))

        # doc_type: try the configured column first; if it looks like a book-type
        # code ("OR", "MTG-OR", single-letter) fall back to location_header which
        # carries the human-readable type in older builds (DEED, MORTGAGE, LIEN).
        doc_type = get(col["doc_type"])
        if not doc_type or doc_type in ("OR", "O", "R"):
            loc_hdr = get(col["location_header"])
            if loc_hdr and loc_hdr not in ("OR", "O", "R"):
                doc_type = loc_hdr

        return DocumentRecord(
            document_number=doc_num,
            grantors=direct_name,
            grantees=reverse_name,
            grantor_grantees=(
                f"{direct_name}; {reverse_name}"
                if direct_name and reverse_name
                else (direct_name or reverse_name)
            ),
            document_type=doc_type,
            recording_date=get(col["record_date"]),
            pages=get(col["page_count"]),
        )

    @staticmethod
    def _extract_pcn_from_legal(legal: str) -> str:
        """Pull a PCN/APN out of the Landmark legal-description blob.

        Landmark formats parcel control numbers as ``PCN: 00-41-47-22-04-000-1090``
        in the legal column. When present this is a more reliable APN than
        scraping it from pull_detail. Returns empty string when not found.
        """
        if not legal:
            return ""
        m = re.search(r"PCN[:\s]+([0-9\-]{15,30})", legal)
        return m.group(1) if m else ""

    # ----------------------------------------------------------- download_pdf

    # `var imageCount = N;` is the Landmark convention for the page count of
    # the displayed (recorded-image) tab. `var transImageCount = N;` is the
    # transferred-image / redacted tab. Some Landmark tenants only emit
    # `imageCount`; defensively scan for both.
    _IMAGE_COUNT_RE = re.compile(r"var\s+imageCount\s*=\s*(\d+)\s*;", re.IGNORECASE)
    _TRANS_IMAGE_COUNT_RE = re.compile(r"var\s+transImageCount\s*=\s*(\d+)\s*;", re.IGNORECASE)

    @classmethod
    def _scrape_page_count(cls, detail_html: str) -> int:
        """Return the page count for a Landmark detail HTML response.

        Returns 0 when neither imageCount nor transImageCount is found
        (caller treats this as "single page fallback" — fetch pageNum=0
        and stop on first non-200 / non-image response).
        """
        if not detail_html:
            return 0
        m = cls._IMAGE_COUNT_RE.search(detail_html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
        m = cls._TRANS_IMAGE_COUNT_RE.search(detail_html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
        return 0

    def _fetch_page_image(self, internal_id: str, page_num: int) -> Optional[bytes]:
        """GET one page image from /Document/GetDocumentImage/.

        Landmark serves each page as a separate PNG (verified live Palm Beach
        2026-05-26 — see /tmp/pb_probe_image_out.txt). pageNum is 1-indexed
        though pageNum=0 also returns the first page. We use 1-indexed loops
        for clarity.

        Returns the raw image bytes on success; None on any failure (caller
        decides whether to retry or accept partial pages).
        """
        url = self._url(self._ep_get_image)
        params = {
            "documentId": internal_id,
            "index": "0",
            "pageNum": str(page_num),
            "type": "normal",
            # `time` is a cache-buster used by the JS — mirror it to be safe.
            "time": str(int(time.time() * 1000)),
            "rotate": "0",
        }
        # Build full URL with query string (curl_cffi handles dict params).
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=60,
                headers={
                    "Referer": self._url("Document/Index"),
                    "Accept": "image/png,image/*,*/*;q=0.8",
                },
            )
        except Exception as exc:
            print(f"  [download_pdf] page {page_num} GET raised: {exc}")
            return None
        if resp.status_code != 200:
            return None
        content = resp.content or b""
        # Sanity check: PNG / JPEG / TIFF magic bytes. Anything else (e.g.
        # the IIS error HTML when pageNum is past EOF) returns None.
        if content[:8] == b"\x89PNG\r\n\x1a\n":
            return content
        if content[:3] == b"\xff\xd8\xff":      # JPEG
            return content
        if content[:4] in (b"II*\x00", b"MM\x00*"):  # TIFF
            return content
        return None

    @staticmethod
    def _stitch_images_to_pdf(image_bytes_list: List[bytes], dest_path: Path) -> int:
        """Convert a list of page-image bytes into a single PDF using Pillow.

        Returns the size of the written PDF in bytes. Raises if PIL refuses
        every page (caller surfaces as an error result).
        """
        try:
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(f"PIL/Pillow is required for Landmark PDF stitching: {exc}")

        pages = []
        for raw in image_bytes_list:
            try:
                img = Image.open(io.BytesIO(raw))
                # Convert to RGB — PNG can be RGBA / P / L, PDF wants RGB
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                pages.append(img)
            except Exception as exc:
                print(f"  [download_pdf] stitch warning: dropped page (decode failed: {exc})")
                continue

        if not pages:
            raise RuntimeError("no valid page images to stitch")

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        first, rest = pages[0], pages[1:]
        first.save(
            str(dest_path),
            format="PDF",
            save_all=True,
            append_images=rest,
            resolution=200.0,
        )
        return dest_path.stat().st_size

    def download_pdf(self, doc_num: str, dest_path: Path) -> Dict[str, Any]:
        """Download a Landmark document as a stitched-PDF.

        Mirrors the Tyler / AcclaimWeb ``download_pdf`` contract — returns:

        Success: ``{"status": "success", "size": int, "pages": int,
                    "src_via": "landmark_page_images_to_pdf",
                    "internal_id": str}``
        Failure: ``{"status": "error", "error": str, "phase": str,
                    "internal_id"?: str, "pages_attempted"?: int}``

        Flow (verified live 2026-05-26 against Palm Beach for instrument
        20190401915 / internal_id 23030131):

        1. Warm session (no-op if already warmed).
        2. Resolve the Landmark internal documentId from the cached
           ``_doc_id_by_number`` map. If absent, the caller must run
           perform_search first OR seed the cache via `seed_doc_id`.
        3. POST /Document/Index with {id=internal_id, row=0} to (a) get the
           page count from ``var imageCount = N;`` and (b) prime any
           per-document session state Landmark requires before serving
           images.
        4. GET each page from /Document/GetDocumentImage/?documentId=...
           &pageNum=N&type=normal — Landmark serves PNG bytes per page.
           Retry up to ``pdf_fetch_retries`` times with exponential-ish
           backoff if a page comes back as HTML (typical "page past EOF"
           response).
        5. Stitch the PNGs into a single multi-page PDF via Pillow.
           Save to ``dest_path``.

        NOTE: Landmark does NOT expose a single "give me the PDF" endpoint —
        every Palm Beach probe in /tmp/pb_probe_image_out.txt for
        ``Document/GetDocumentPdf``, ``Document/Pdf``, ``Document/Print``,
        and ``PrintAllDocsInMyList`` returned either 404 or HTML. The
        page-image-stitch path is the only HTTP-only way to ship a PDF.
        """
        if not self._session_warmed:
            if not self.warm_session():
                return {
                    "status": "error",
                    "doc": doc_num,
                    "phase": "warm_session",
                    "error": self.last_failure or "session warm-up failed",
                }

        internal_id = self._doc_id_by_number.get(doc_num) or self._doc_id_by_number.get(str(doc_num))
        if not internal_id:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "id_resolution",
                "error": (
                    f"no Landmark internal id cached for instrument {doc_num!r} — "
                    f"run perform_search first or seed via seed_doc_id()."
                ),
            }

        # Step 3 — prime detail to get page count + per-doc nav state.
        detail_payload = {
            "id": internal_id,
            "row": "0",
            "time": "",
            "navigationType": "",
        }
        try:
            dr = self.session.post(
                self._url(self._ep_detail),
                data=detail_payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                    "Origin": self._base_url.rstrip("/"),
                },
                timeout=45,
            )
        except Exception as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "detail_prime",
                "error": f"network: {exc}",
                "internal_id": internal_id,
            }
        if dr.status_code != 200:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "detail_prime",
                "error": f"HTTP {dr.status_code}",
                "internal_id": internal_id,
            }

        page_count = self._scrape_page_count(dr.text)
        if page_count <= 0:
            # Defensive: attempt a single page and stop. Some 1-page Landmark
            # docs may not emit imageCount.
            page_count = 1
        if page_count > self._pdf_max_pages:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "page_count_validation",
                "error": (
                    f"page_count={page_count} exceeds pdf_max_pages={self._pdf_max_pages} — "
                    f"refusing to download (likely a misidentified doc or runaway)."
                ),
                "internal_id": internal_id,
            }

        # Step 4 — fetch each page with retry.
        # Pages are 1-indexed for the user-visible Landmark JS, but the
        # endpoint also accepts pageNum=0 (returns page 1). We use the
        # 1..N range for clarity.
        image_blobs: List[bytes] = []
        for page in range(1, page_count + 1):
            blob: Optional[bytes] = None
            for attempt in range(1, self._pdf_fetch_retries + 1):
                blob = self._fetch_page_image(internal_id, page)
                if blob:
                    break
                if attempt < self._pdf_fetch_retries:
                    time.sleep(self._pdf_retry_delay_seconds)
            if not blob:
                return {
                    "status": "error",
                    "doc": doc_num,
                    "phase": "fetch_page",
                    "error": (
                        f"page {page}/{page_count} returned no image bytes after "
                        f"{self._pdf_fetch_retries} retries"
                    ),
                    "internal_id": internal_id,
                    "pages_attempted": len(image_blobs),
                }
            image_blobs.append(blob)
            # Optionally keep raw PNGs next to the PDF for debugging.
            if self._pdf_keep_page_images:
                try:
                    page_path = Path(dest_path).with_suffix("").with_suffix(f".page{page:02d}.png")
                    page_path.parent.mkdir(parents=True, exist_ok=True)
                    page_path.write_bytes(blob)
                except Exception:
                    pass

        # Step 5 — stitch and save.
        try:
            size = self._stitch_images_to_pdf(image_blobs, Path(dest_path))
        except Exception as exc:
            return {
                "status": "error",
                "doc": doc_num,
                "phase": "stitch",
                "error": f"PDF stitch failed: {exc}",
                "internal_id": internal_id,
                "pages_attempted": len(image_blobs),
            }

        return {
            "status": "success",
            "size": size,
            "pages": len(image_blobs),
            "src_via": "landmark_page_images_to_pdf",
            "internal_id": internal_id,
            "doc": doc_num,
        }

    def seed_doc_id(self, doc_num: str, internal_id: str) -> None:
        """Populate ``_doc_id_by_number`` for a known doc.

        Used by the pipeline when search has been cached / replayed from a
        prior run — avoids having to re-run the captcha-gated search just to
        re-discover internal ids.
        """
        if doc_num and internal_id:
            self._doc_id_by_number[str(doc_num)] = str(internal_id)

    # ----------------------------------------------------------- extract_results

    def extract_results(self, html: str) -> List[DocumentRecord]:
        """Parse a Landmark name-search response into DocumentRecord rows.

        Landmark renders results as a plain ``<table id="resultsTable">``
        with one ``<tr>`` per document (no Kendo classes). Each row has an
        anchor with ``onclick="GetDetailSection('<docId>', ...)"`` that we
        also harvest into the DocumentRecord for downstream detail pulls.

        Returns ``[]`` for the "no records found" landing AND for malformed
        HTML. The pipeline distinguishes these via ``self.last_failure``.
        """
        documents: List[DocumentRecord] = []
        if not html:
            return documents

        soup = BeautifulSoup(html, "lxml")

        # Detect explicit "no results" banner — Landmark shows
        # "No records found" or "0 records" in a styled banner near the top.
        text_blob = soup.get_text(" ", strip=True).lower()
        if (
            "no records found" in text_blob
            and "results" in text_blob
            and len(text_blob) < 4000
        ):
            return documents

        # Strategy 1: rows in #resultsTable / #resultsGridDiv
        rows = soup.select("#resultsTable tr, #resultsGridDiv tr, table.results tr")

        # Strategy 2: any tr that carries an id starting with "doc_" (Landmark
        # convention — `id="doc_{documentId}"`).
        if not rows:
            rows = soup.select('tr[id^="doc_"]')

        # Strategy 3: fall back to every table row and let the doc-number
        # regex filter the junk.
        if not rows:
            rows = soup.find_all("tr")

        seen = set()
        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue

            doc_num, doc_idx = self._extract_doc_number(row, cells)
            if not doc_num or doc_num in seen:
                continue
            seen.add(doc_num)

            rec_date, doc_type, grantors, grantees, pages = self._classify_columns(
                cells, doc_idx
            )

            documents.append(
                DocumentRecord(
                    document_number=doc_num,
                    grantors=grantors,
                    grantees=grantees,
                    grantor_grantees=(
                        f"{grantors}; {grantees}"
                        if grantors and grantees
                        else (grantors or grantees)
                    ),
                    document_type=doc_type,
                    recording_date=rec_date,
                    pages=pages,
                )
            )

        return documents

    def _extract_doc_number(self, row, cells: List[str]) -> Tuple[str, int]:
        """Locate the document number in a Landmark result row.

        Priority order:
          1. ``<tr id="doc_{N}">`` attribute (most reliable on Landmark)
          2. Any ``<a onclick="GetDetailSection('{N}',...)">`` anchor
          3. First cell whose plain text matches ``self._doc_number_re``
        """
        row_id = row.get("id", "")
        if row_id.startswith("doc_"):
            candidate = row_id[len("doc_"):].split("_")[0]
            if candidate and self._doc_number_re.match(candidate):
                # Locate the cell index that holds the visible doc number.
                for i, txt in enumerate(cells):
                    if candidate in txt:
                        return candidate, i
                return candidate, 0

        for i, td in enumerate(row.find_all("td")):
            for a in td.find_all("a"):
                onclick = a.get("onclick", "") or ""
                m = re.search(r"GetDetailSection\(\s*['\"]([^'\"]+)['\"]", onclick)
                if m:
                    candidate = m.group(1).split("_")[0]
                    if candidate:
                        return candidate, i
                txt = a.get_text(strip=True)
                if txt and self._doc_number_re.match(txt):
                    return txt, i

        for i, txt in enumerate(cells):
            if txt and self._doc_number_re.match(txt):
                return txt, i

        return "", -1

    # Landmark doc-type codes are short uppercase tokens — most are 1-6 chars
    # with NO embedded space (e.g. "D", "MTG", "ASG", "AFF TX" is the rare
    # exception). Party names ALWAYS contain at least one space ("HABER DANA").
    _DOCTYPE_LIKE_RE = re.compile(r"^[A-Z][A-Z0-9 /&-]{0,15}$")

    @classmethod
    def _classify_columns(
        cls, cells: List[str], doc_idx: int
    ) -> Tuple[str, str, str, str, str]:
        """Heuristic column scan — same shape as our other adapters.

        Returns (rec_date, doc_type, grantors, grantees, pages).

        Heuristic priority:
          1. Date matches MM/DD/YYYY -> recording_date.
          2. 1-4 digit pure number with reasonable page count (<=999) -> pages.
          3. Short uppercase token w/o lowercase letters AND <= 6 chars and
             NO space inside -> doc_type (Landmark's vocabulary). The
             important guard is the lack of a space: "HABER DANA" has one,
             "MTG" does not, "AFF TX" does have one but that's rare and
             gets correctly routed to grantors only when the doc_type slot
             is already filled.
          4. Anything else with length >= 2 -> grantors then grantees.
        """
        rec_date = doc_type = grantors = grantees = pages = ""
        for i, txt in enumerate(cells):
            if i == doc_idx or not txt:
                continue
            if not rec_date and re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", txt):
                rec_date = txt
                continue
            if not pages and re.match(r"^\d{1,4}$", txt) and int(txt) <= 9999:
                pages = txt
                continue
            looks_like_doctype = (
                not doc_type
                and len(txt) <= 8
                and " " not in txt
                and txt == txt.upper()
                and cls._DOCTYPE_LIKE_RE.match(txt) is not None
                and "," not in txt
                and ";" not in txt
            )
            if looks_like_doctype:
                doc_type = txt
                continue
            if len(txt) >= 2:
                if not grantors:
                    grantors = txt
                elif not grantees:
                    grantees = txt
        return rec_date, doc_type, grantors, grantees, pages

    # -------------------------------------------------------------- pull_detail

    def pull_detail(self, doc_num: str, row_number: int = 0) -> Dict:
        """Fetch the document-detail HTML fragment for ``doc_num``.

        Landmark exposes this as a POST to ``/Document/Index`` with
        ``{id, row, time, navigationType}`` — the body that the
        ``GetDetailSection()`` JS function would send. Returns a parsed
        dict mirroring the AcclaimWeb adapter contract so the pipeline's
        cross-reference checker doesn't need a Landmark special case.
        """
        if not self._session_warmed and not self.warm_session():
            return {"document_number": doc_num, "error": "session_not_warmed"}

        payload = {
            "id": doc_num,
            "row": row_number,
            "time": "",
            "navigationType": "",
        }
        try:
            resp = self.session.post(
                self._url(self._ep_detail),
                data=payload,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(self._ep_search_index),
                },
                timeout=45,
            )
        except Exception as exc:
            return {"document_number": doc_num, "error": f"network: {exc}"}

        if resp.status_code != 200:
            return {"document_number": doc_num, "error": f"HTTP {resp.status_code}"}

        return self._parse_detail_html(resp.text, doc_num)

    @staticmethod
    def _parse_detail_html(html: str, doc_num: str) -> Dict:
        """Parse a Landmark ``/Document/Index`` response into structured fields."""
        soup = BeautifulSoup(html, "lxml")

        def find_field(label_substring: str) -> str:
            label_re = re.compile(label_substring, re.IGNORECASE)
            for cell in soup.find_all(["td", "th", "dt", "div", "span", "label"]):
                txt = cell.string or cell.get_text(" ", strip=True)
                if txt and label_re.search(txt):
                    nxt = cell.find_next_sibling(["td", "dd", "div", "span"])
                    if nxt:
                        v = nxt.get_text(" ", strip=True)
                        if v:
                            return v
            return ""

        indexed_apn = (
            find_field(r"Parcel.?ID")
            or find_field(r"\bAPN\b")
            or find_field(r"Property.?ID")
        )
        recording_date = find_field(r"Record(ed|ing) Date") or find_field(r"Date Recorded")
        doc_type = find_field(r"Doc.?Type") or find_field(r"Document Type")
        book_page = find_field(r"Book.?\/.?Page") or find_field(r"Book\s*Page")

        parties: List[Dict[str, str]] = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if any("party" in h or "role" in h or "name" in h for h in headers):
                for trow in table.find_all("tr")[1:]:
                    tds = [td.get_text(strip=True) for td in trow.find_all("td")]
                    if len(tds) >= 2:
                        parties.append({"role": tds[0], "name": tds[1]})

        return {
            "document_number": doc_num,
            "recording_date": recording_date,
            "doc_type": doc_type,
            "indexed_apn": indexed_apn,
            "book_page": book_page,
            "parties": parties,
            "raw_html_snippet": html[:2000],
        }
