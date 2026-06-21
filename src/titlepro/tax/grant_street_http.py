"""Grant Street Group `county-taxes.net` HTTP adapter.

Pure-HTTP tax lookup for counties whose tax portal is hosted by Grant Street
Group's GovHub product (the same vendor that runs CA Alameda / Sacramento /
Contra Costa / San Diego portals). Initial target: **Broward County, FL**.

Why HTTP not Playwright
-----------------------
The Broward `county-taxes.net` SPA is a Vue/InstantSearch front-end backed by
publicly exposed JSON/HTML endpoints. Probing on 2026-05-23 showed:
- Typeahead search is an Algolia query against index `fl-broward.property_tax`
  (API key + app id are baked into the public JS bundle).
- Parcel detail HTML is served at
  `https://county-taxes.net/iframe-taxsys/broward.county-taxes.com/govhub/property-tax/{b64}/load-bill-history`
- Per-year bill detail HTML (with ad-valorem assessed values, taxing-authority
  table, and non-ad-valorem assessments) is served at
  `https://county-taxes.net/iframe-taxsys/broward.county-taxes.com/govhub/property-tax/{b64}/bills/{bill_uuid}`

No Cloudflare challenge, no anti-bot. `curl_cffi` with chrome120 impersonation
returns 200 on every call. This matches Tony Roveda's Phase 1 directive (no
Selenium / Playwright in the data path).

Public entry point
------------------
``lookup_grant_street_tax(apn: str, county_id: str, case_dir: Path) -> TaxLookupResult``

Per-county configuration is sourced from ``config/county_tax_urls.json``
(``grant_street`` block) so new GovHub counties can be added without code
changes — they just need a different Algolia ``index_name`` and a different
``portal_subdomain``.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi

from titlepro.tax.result import TaxLookupResult, apn_matches, host_in_whitelist


# ---------------------------------------------------------------------------
# Config defaults (per-county overridable via county_tax_urls.json)
# ---------------------------------------------------------------------------

DEFAULT_IMPERSONATE = "chrome120"

# These three were captured by sniffing the public JS bundle on
# https://county-taxes.net/broward/property-tax on 2026-05-23. They are
# embedded in the public JS bundle, not user-specific credentials.
DEFAULT_ALGOLIA_APP_ID = "0LWZO52LS2"
DEFAULT_ALGOLIA_API_KEY = "c0745578b56854a1b90ed57b63fbf0ba"

# Default per-county settings (Broward shape). Other GovHub counties
# differ only in `algolia_index`, `portal_path`, and `portal_subdomain`.
COUNTY_DEFAULTS: dict[str, dict[str, str]] = {
    "broward": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-broward.property_tax",
        # The iframe-taxsys URL is:
        #   /iframe-taxsys/{portal_subdomain}/govhub/{iframe_path}/{b64}/...
        # And the public (browser-bar) URL is:
        #   /{public_path}/{b64}/...
        "portal_subdomain": "broward.county-taxes.com",
        "iframe_path": "property-tax",            # under /govhub/ -- NO county prefix
        "public_path": "broward/property-tax",    # browser-bar URL prefix
        "iframe_origin": "https://county-taxes.net",
        # Public-facing referer (sent on every fetch).
        "referer": "https://county-taxes.net/broward/property-tax",
        # Used by source_url whitelist check downstream.
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Hillsborough FL — same Grant Street GovHub backbone as Broward.
    # Verified 2026-05-26 against FROMER folio 1151460000 (parcel
    # f5249e84-e509-11eb-af6c-00505681b2cf). Same Algolia app_id + api_key
    # (they're public client credentials baked into the JS bundle).
    "hillsborough": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-hillsborough.property_tax",
        "portal_subdomain": "hillsborough.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "hillsborough/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/hillsborough/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Volusia FL — same Grant Street GovHub backbone. Live-probed 2026-06-10
    # against GUILD parcel 533705070110 (uuid d51ba963-e508-11eb-9998-
    # 00505681f6c9): Algolia hit + load-bill-history both 200. NOTE: Volusia's
    # public (browser-bar) path is the vanity slug `vctaxcollector` — NOT
    # `volusia` — and volusia.county-taxes.com 302s to
    # county-taxes.net/vctaxcollector. The bare county-taxes.com host is
    # Cloudflare-challenged for non-browser TLS; county-taxes.net (where all
    # adapter calls go) is not.
    "volusia": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-volusia.property_tax",
        "portal_subdomain": "volusia.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "vctaxcollector/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/vctaxcollector/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Pasco — probed 2026-06-10 (0610 RILEY case): pasco.county-taxes.com/public
    # redirects to county-taxes.net/fl-pasco, 200 with safari17_2_ios, no
    # challenge. Algolia index name is by vendor convention — validate on the
    # first Wave-2 lookup.
    "pasco": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-pasco.property_tax",
        "portal_subdomain": "pasco.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "pasco/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/pasco/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Brevard — probed 2026-06-10 (0610 LEWIS case): GovHub confirmed, no
    # anti-bot. Index by vendor convention — validate on first Wave-2 lookup.
    "brevard": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-brevard.property_tax",
        "portal_subdomain": "brevard.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "brevard/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/brevard/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Duval — probed 2026-06-10 (0610 SKINNER case). Two quirks: public path is
    # the state-prefixed slug 'fl-duval', and chrome120 gets Cloudflare-
    # challenged (403) — safari17_2_ios required (honored via the per-county
    # 'impersonate' override in lookup_grant_street_tax).
    "duval": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-duval.property_tax",
        "portal_subdomain": "duval.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-duval/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-duval/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
    # Miami-Dade — probed 2026-06-18 (0618 NUNEZ/PROPHETE/HAMMONS batch):
    # miamidade.county-taxes.com/public 200-redirects to county-taxes.net/
    # fl-miamidade (state-prefixed public slug, like Duval). safari17_2_ios, no
    # challenge. Folio is the 13-digit Property Appraiser folio (display
    # NN-NNNN-NNN-NNNN). Index by vendor convention — validate on first lookup.
    "miami_dade": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-miamidade.property_tax",
        "portal_subdomain": "miamidade.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-miamidade/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-miamidade/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
    # Lee — live-validated 2026-06-10 (0610 OSTIGUY case): TAX_SUCCESS for the
    # subject parcel via in-process monkeypatch of this exact dict.
    "lee": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-lee.property_tax",
        "portal_subdomain": "lee.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-lee/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-lee/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Sarasota — probed 2026-06-10 (0610 BRUNO case): GovHub confirmed.
    # Index by convention — validate on first Wave-2 lookup.
    "sarasota": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-sarasota.property_tax",
        "portal_subdomain": "sarasota.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "sarasota/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/sarasota/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Seminole — probed 2026-06-10 (0610 PORTILLA case): GovHub v9; public path
    # uses the LIVE-observed state-prefixed slug 'fl-seminole'. Confirm Algolia
    # index + slug end-to-end before flipping the county stub.
    "seminole": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-seminole.property_tax",
        "portal_subdomain": "seminole.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-seminole/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-seminole/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Lake County FL — confirmed 2026-06-19 via Algolia probe: index fl-lake.property_tax
    # exists, 1511 records, same app_id/key as other FL GovHub counties.
    # APN format: 03-23-26-0109-000-003D0 (dash-separated). Public path TBD (likely
    # 'lake/property-tax' or 'fl-lake/property-tax' — validate on first live lookup).
    "lake": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-lake.property_tax",
        "portal_subdomain": "lake.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "lake/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/lake/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Sumter County FL — confirmed 2026-06-19 via Algolia probe: index fl-sumter.property_tax
    # exists, 755 records, same app_id/key as other FL GovHub counties.
    # APN format: D33G061 (The Villages parcel ID). Public path TBD.
    "sumter": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-sumter.property_tax",
        "portal_subdomain": "sumter.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "sumter/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/sumter/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Aliases with fl_ prefix matching recorder county_id keys (used by workflow_config).
    # These duplicate the above but keyed as fl_lake / fl_sumter for direct dispatch.
    "fl_lake": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-lake.property_tax",
        "portal_subdomain": "lake.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "lake/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/lake/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    "fl_sumter": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-sumter.property_tax",
        "portal_subdomain": "sumter.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "sumter/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/sumter/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Santa Rosa FL — Algolia index confirmed 2026-06-19 (WHITE parcel
    # efe55559-e509-11eb-a109-005056b98e38, external_id 231S28000300A000170).
    # Public path is fl-santarosa (state-prefixed, confirmed from parcelview
    # link "county-taxes.net/fl-santarosa/property-tax"). Cloudflare on
    # county-taxes.net iframe-taxsys from datacenter egress (403); bill-history
    # endpoint requires residential cf_clearance. Algolia search itself
    # works (no CF on dsn.algolia.net). Until residential egress is available,
    # the adapter returns TAX_FAILED and the report falls back to the PA-derived
    # tax estimate from parcelview.srcpa.gov (APN, millage 0.0113897, 2025).
    "santa_rosa": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-santarosa.property_tax",
        "portal_subdomain": "santarosa.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-santarosa/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-santarosa/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
    # fl_santa_rosa alias (recorder county_id -> tax key dispatch)
    "fl_santa_rosa": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-santarosa.property_tax",
        "portal_subdomain": "santarosa.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-santarosa/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-santarosa/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
    # Citrus County FL — county-taxes.net/citrus (no fl- prefix, per live probe
    # 2026-06-19; county_tax_urls.json base_url confirms the 'citrus' slug).
    # APN format: 18E17S320020 (PA strap without leading zeros). Algolia index
    # by vendor convention fl-citrus.property_tax — validate on first live lookup.
    "citrus": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-citrus.property_tax",
        "portal_subdomain": "citrus.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "citrus/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/citrus/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # fl_citrus alias (recorder county_id -> tax key dispatch)
    "fl_citrus": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-citrus.property_tax",
        "portal_subdomain": "citrus.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "citrus/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/citrus/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Escambia FL — Algolia index fl-escambia.property_tax confirmed 2026-06-19
    # (HILLIS parcel uuid f670343d-e509-11eb-a109-005056b98e38, account 110850125,
    # external_id 11-0850-125; query KEY = folio = '110850125', not the PA APN
    # '221N302302001001'). The iframe-taxsys bill-history endpoint returns CF-403
    # from datacenter IPs (same wall as Santa Rosa); residential cf_clearance
    # needed to complete the live-bill pull. Algolia search itself works from
    # datacenter (no CF on dsn.algolia.net). Public path = fl-escambia per
    # county-taxes.net redirect target.
    "escambia": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-escambia.property_tax",
        "portal_subdomain": "escambia.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-escambia/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-escambia/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
        # Escambia's Algolia search key is the FOLIO (account number, e.g.
        # '110850125'), NOT the PA APN ('221N302302001001'). The pipeline passes
        # apn from workflow_config; callers must map APN -> folio before querying,
        # or pass the folio directly. Until this mapping is built, the adapter
        # will surface TAX_FAILED with a diagnostic so the bill-pull can be
        # completed manually from county-taxes.net/fl-escambia/property-tax.
        "apn_key": "folio",  # indicates the Algolia query key is the folio, not the APN
    },
    # fl_escambia alias (recorder county_id -> tax key dispatch)
    "fl_escambia": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-escambia.property_tax",
        "portal_subdomain": "escambia.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-escambia/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-escambia/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
        "apn_key": "folio",
    },
    # Bay County FL — county-taxes.net/fl-bay/property-tax (state-prefixed slug,
    # confirmed from county_tax_urls.json probe). APN format: 40001-100-048
    # (hyphen-separated, matching the PA Tax Parcel ID). Algolia index by vendor
    # convention fl-bay.property_tax — validated on first live lookup 2026-06-19.
    # No Cloudflare on county-taxes.net from datacenter egress (confirmed 2026-06-19).
    "bay": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-bay.property_tax",
        "portal_subdomain": "bay.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-bay/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-bay/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # fl_bay alias (recorder county_id -> tax key dispatch)
    "fl_bay": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-bay.property_tax",
        "portal_subdomain": "bay.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-bay/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-bay/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Clay County FL — county-taxes.net/fl-clay/property-tax (state-prefixed slug,
    # confirmed from county_tax_urls.json: base_url='https://county-taxes.net/fl-clay/property-tax').
    # APN format: NN-NN-NN-NNNNNN-NNN-NN (dash-separated, 17-char e.g. 18-04-25-007953-056-43).
    # Algolia index by vendor convention fl-clay.property_tax — validate on first live lookup.
    # No Cloudflare on county-taxes.net from datacenter egress (same host as Bay, Brevard).
    "clay": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-clay.property_tax",
        "portal_subdomain": "clay.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-clay/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-clay/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # fl_clay alias (recorder county_id -> tax key dispatch)
    "fl_clay": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-clay.property_tax",
        "portal_subdomain": "clay.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-clay/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-clay/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Flagler County FL — Algolia index fl-flagler.property_tax confirmed live
    # 2026-06-19 (FEDERICO parcel 03133151202AF051090, uuid
    # f3c4d9fe-e509-11eb-9467-005056818710, owner FEDERICO GIACOMO).
    # Public path = fl-flagler per county_tax_urls.json base_url
    # https://county-taxes.net/fl-flagler/property-tax.
    # APN format: 03-13-31-5120-2AF05-1090 (dashes); Algolia search key =
    # APN with dashes stripped = '03133151202AF051090'. No Cloudflare on
    # county-taxes.net from datacenter egress (same host as Bay, Clay, Brevard).
    "flagler": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-flagler.property_tax",
        "portal_subdomain": "flagler.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-flagler/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-flagler/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # fl_flagler alias (recorder county_id -> tax key dispatch)
    "fl_flagler": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-flagler.property_tax",
        "portal_subdomain": "flagler.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-flagler/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-flagler/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Indian River County FL — live-probed 2026-06-19 (POGANY/VANDERMOLEN 0618 batch).
    # Algolia index = fl-indianriver.property_tax (no hyphen between 'indian' and 'river'
    # — standard fl-{slug} convention; 'fl-indian-river' and 'fl-indian_river' both 404).
    # Public (browser-bar) path = 'indianriver/property-tax' (no 'fl-' prefix — confirmed
    # from county_tax_urls.json base_url). APN search key: the PA APN is 32402900015000000010.0
    # (dots); the Algolia external_id for that parcel is '32-40-29-00015-0000-00010-0'.
    # Algolia hit confirmed: 1 result for POGANY, uuid f425aedd-e509-11eb-9467-005056818710.
    # No Cloudflare on county-taxes.net from datacenter egress (chrome120 200).
    "indian_river": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-indianriver.property_tax",
        "portal_subdomain": "indianriver.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "indianriver/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/indianriver/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # fl_indian_river alias (recorder county_id -> tax key dispatch)
    "fl_indian_river": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-indianriver.property_tax",
        "portal_subdomain": "indianriver.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "indianriver/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/indianriver/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
    },
    # Walton FL — county_tax_urls.json base_url is
    # county-taxes.net/fl-walton/property-tax (state-prefixed public slug, like
    # Duval / Lee / Miami-Dade). Wired 2026-06-19 (0618 JETT + SHAHID batch).
    # Folio/key = the Property Appraiser strap (e.g. 30-2S-21-42820-00B-0105).
    # Algolia index by vendor convention fl-walton.property_tax — validate on the
    # first live lookup. safari17_2_ios mirrors the other state-prefixed-slug
    # counties (chrome120 is CF-challenged on some Grant Street GovHub hosts).
    "walton": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-walton.property_tax",
        "portal_subdomain": "walton.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-walton/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-walton/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
    # fl_walton alias (recorder county_id -> tax key dispatch)
    "fl_walton": {
        "algolia_app_id": DEFAULT_ALGOLIA_APP_ID,
        "algolia_api_key": DEFAULT_ALGOLIA_API_KEY,
        "algolia_index": "fl-walton.property_tax",
        "portal_subdomain": "walton.county-taxes.com",
        "iframe_path": "property-tax",
        "public_path": "fl-walton/property-tax",
        "iframe_origin": "https://county-taxes.net",
        "referer": "https://county-taxes.net/fl-walton/property-tax",
        "authoritative_hosts": ["county-taxes.net"],
        "impersonate": "safari17_2_ios",
    },
}


def _log(msg: str) -> None:
    print(f"[grant-street-tax] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Currency / number helpers
# ---------------------------------------------------------------------------


_CURRENCY_RE = re.compile(r"\$?-?[\d,]+(?:\.\d+)?")


def _parse_money(text: Any) -> float:
    """``'$1,492.75'`` -> ``1492.75`` (returns 0.0 on miss)."""
    if text is None:
        return 0.0
    s = str(text)
    m = _CURRENCY_RE.search(s)
    if not m:
        return 0.0
    cleaned = m.group(0).replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _clean_apn(apn: str) -> str:
    """Strip non-alphanumerics. ``49-42-25-04-0800`` -> ``4942250040800``."""
    return re.sub(r"[^A-Za-z0-9]", "", apn or "")


def _normalize_county(c: str) -> str:
    c = (c or "").lower().strip()
    # `fl_broward` (recorder county_id) maps to `broward` (tax county_id)
    if c.startswith("fl_"):
        c = c[3:]
    for suffix in (" county, fl", " county, ca", ", fl", ", ca", " county", " ca", " fl"):
        if c.endswith(suffix):
            c = c[: -len(suffix)]
    return c.strip().replace(" ", "_")


# ---------------------------------------------------------------------------
# Step 1: Algolia search -> parcel UUID + display id + owner/situs preview
# ---------------------------------------------------------------------------


def _search_algolia(session: Any, county_cfg: dict, apn: str) -> dict | None:
    """Query Algolia for the parcel matching ``apn``.

    Returns the first hit's ``custom_parameters`` (and ``hit`` object merged)
    with at least these keys when successful:
        - ``parcel_uuid``     (e.g. ``0168ad90-e50a-11eb-ba38-005056819334``)
        - ``parcel_b64``      (base64-encoded ``broward:real_estate:parents:<uuid>``)
        - ``external_id``     (display APN, e.g. ``494225-04-0800``)
        - ``public_url``      (e.g. ``/public/real_estate/parcels/.../bills``)
        - ``entities``        (list with owner + situs strings)
    Returns ``None`` if no hits.
    """
    endpoint = f"https://{county_cfg['algolia_app_id'].lower()}-dsn.algolia.net/1/indexes/*/queries"
    params = {
        "x-algolia-agent": "Algolia for JavaScript (4.23.3); Browser (lite); instantsearch.js (4.66.1); Vue (3.3.4); Vue InstantSearch (4.15.0); JS Helper (3.17.0)",
        "x-algolia-api-key": county_cfg["algolia_api_key"],
        "x-algolia-application-id": county_cfg["algolia_app_id"],
    }
    body = {
        "requests": [{
            "indexName": county_cfg["algolia_index"],
            "params": (
                "clickAnalytics=true&facets=%5B%5D"
                "&highlightPostTag=__%2Fais-highlight__"
                "&highlightPreTag=__ais-highlight__"
                "&hitsPerPage=15"
                f"&query={apn}"
                "&tagFilters="
            ),
        }]
    }
    r = session.post(endpoint, params=params, json=body, timeout=20)
    if r.status_code != 200:
        _log(f"algolia search returned {r.status_code}: {r.text[:200]!r}")
        return None
    try:
        data = r.json()
    except Exception as exc:
        _log(f"algolia response not JSON: {exc}")
        return None
    results = (data.get("results") or [{}])[0]
    hits = results.get("hits") or []
    if not hits:
        return None

    # Pick the first hit whose external_id, child_groups, or external_id_tokens
    # matches our cleaned APN. (Names sometimes appear before APN hits.)
    target = _clean_apn(apn)

    def _hit_apns(hit: dict) -> list[str]:
        apns: list[str] = []
        # Top-level external_id (Hillsborough uses this for the prefixed
        # parcel identifier, e.g. "A1151460000")
        if hit.get("external_id"):
            apns.append(hit["external_id"])
        params = hit.get("custom_parameters") or {}
        ext = params.get("external_id")
        if ext:
            apns.append(ext)
        # `alternate_keys` carries the unprefixed display APN on some counties
        # (Hillsborough: ``{"external_id": "1151460000"}``)
        for ak in (params.get("alternate_keys") or []):
            if isinstance(ak, dict) and ak.get("external_id"):
                apns.append(ak["external_id"])
        # The actual APN often lives inside child_groups[].children[]
        for cg in (hit.get("child_groups") or []):
            for child in (cg.get("children") or []):
                cp = child.get("custom_parameters") or {}
                if child.get("external_id"):
                    apns.append(child["external_id"])
                if cp.get("external_id"):
                    apns.append(cp["external_id"])
                for tok in child.get("external_id_tokens") or []:
                    apns.append(tok)
        return apns

    chosen: dict | None = None
    for hit in hits:
        candidates = [_clean_apn(a) for a in _hit_apns(hit)]
        if any(c == target for c in candidates):
            chosen = hit
            break

    if chosen is None:
        # Fall back to first hit (display order matches relevance from Algolia)
        chosen = hits[0]

    custom = dict(chosen.get("custom_parameters") or {})

    # Extract parcel UUID from objectID or public_url.
    object_id = chosen.get("objectID") or ""
    parcel_uuid = ""
    m = re.search(r"parents:([0-9a-f-]{30,})", object_id)
    if m:
        parcel_uuid = m.group(1)
    if not parcel_uuid:
        # Try the URL pattern  ?parcel=<uuid>
        public_url = custom.get("public_url", "")
        m = re.search(r"parcel=([0-9a-f-]{30,})", public_url)
        if m:
            parcel_uuid = m.group(1)

    if not parcel_uuid:
        _log(f"algolia hit lacks parcel UUID: objectID={object_id!r} custom={custom!r}")
        return None

    # Build the base64 parcel ID expected by the iframe URL.
    raw_id = f"broward:real_estate:parents:{parcel_uuid}"
    # Some other GovHub counties may use the same scheme with a different
    # county prefix — derive from algolia_index.
    county_prefix = county_cfg["algolia_index"].split(".")[0].replace("fl-", "").replace("-", "_")
    if county_prefix and county_prefix != "broward":
        raw_id = f"{county_prefix}:real_estate:parents:{parcel_uuid}"
    import base64 as _b64
    parcel_b64 = _b64.b64encode(raw_id.encode("ascii")).decode("ascii")

    # Find the display APN — prefer the child external_id over the parent.
    # Hillsborough exposes the canonical (unprefixed) APN under
    # `custom_parameters.alternate_keys[0].external_id`; Broward uses
    # `custom_parameters.external_id`. Indian River (and others) expose the
    # display APN as the top-level hit `external_id` (e.g. "32-40-29-00015-0000-00010-0"),
    # while `custom_parameters.alternate_keys` contains a short account key (e.g. "57491").
    # Priority: (1) child_groups child external_id matching cleaned APN,
    #           (2) `custom_parameters.external_id`,
    #           (3) top-level `chosen.external_id` (display APN on many GovHub counties),
    #           (4) `custom_parameters.alternate_keys` (fallback — may be account#, not APN).
    display_apn = custom.get("external_id") or ""
    # Check top-level chosen.external_id early — on Indian River this IS the display APN
    if not display_apn:
        display_apn = chosen.get("external_id") or ""
    # Scan child_groups for a child whose cleaned external_id matches the input APN
    for cg in (chosen.get("child_groups") or []):
        for child in (cg.get("children") or []):
            ext = child.get("external_id") or (child.get("custom_parameters") or {}).get("external_id")
            if ext and _clean_apn(ext) == target:
                display_apn = ext
                break
    if not display_apn:
        for ak in (custom.get("alternate_keys") or []):
            if isinstance(ak, dict) and ak.get("external_id"):
                display_apn = ak["external_id"]
                break

    entities = custom.get("entities") or []
    return {
        "parcel_uuid": parcel_uuid,
        "parcel_b64": parcel_b64,
        "external_id": display_apn,
        "public_url": custom.get("public_url", ""),
        "roll_year": custom.get("roll_year", ""),
        "entities": entities,
        "_raw_hit": chosen,
    }


# ---------------------------------------------------------------------------
# Step 2: Pull bill-history fragment, locate the most-recent Annual bill UUID
# ---------------------------------------------------------------------------


def _bill_history_url(county_cfg: dict, parcel_b64: str) -> str:
    return (
        f"{county_cfg['iframe_origin']}/iframe-taxsys/{county_cfg['portal_subdomain']}"
        f"/govhub/{county_cfg['iframe_path']}/{parcel_b64}/load-bill-history"
    )


def _parent_iframe_url(county_cfg: dict, parcel_b64: str) -> str:
    return (
        f"{county_cfg['iframe_origin']}/iframe-taxsys/{county_cfg['portal_subdomain']}"
        f"/govhub/{county_cfg['iframe_path']}/{parcel_b64}"
    )


def _parse_all_annual_bills(html: str) -> list[dict[str, Any]]:
    """Parse the load-bill-history HTML for ALL ``Annual bill`` rows.

    Returns a list of dicts (one per year) sorted newest-first, each with:
        - ``year``         (int)
        - ``bill_url``     (full URL on county-taxes.net)
        - ``status_text``  (e.g. 'Paid $48,027.63')
        - ``amount_due``   (float)
        - ``row_cells``    (list[str] of the surrounding <tr> cells)
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, Any]] = []
    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        if not href:
            continue
        m_year = re.search(r"\b(20\d{2})\s+Annual bill\b", text, re.I)
        if not m_year:
            continue
        year = int(m_year.group(1))

        tr = a.find_parent("tr")
        cells: list[str] = []
        if tr:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        status_text = ""
        for c in cells:
            if "Paid" in c or "UNPAID" in c.upper() or "DELINQUENT" in c.upper():
                status_text = c
                break

        amount_due = 0.0
        for c in cells:
            if c.startswith("$"):
                amount_due = _parse_money(c)
                break

        candidates.append({
            "year": year,
            "bill_url": href,
            "status_text": status_text,
            "amount_due": amount_due,
            "row_cells": cells,
        })

    candidates.sort(key=lambda c: c["year"], reverse=True)
    return candidates


def _find_latest_annual_bill(html: str) -> dict[str, Any] | None:
    """Parse the load-bill-history HTML and return the most-recent Annual bill.

    Returns a dict with at least:
        - ``year``         (int, e.g. 2025)
        - ``bill_url``     (full URL on county-taxes.net)
        - ``status_text``  (e.g. 'Paid $48,027.63')
        - ``amount_due``   (float, e.g. 0.00)
    """
    candidates = _parse_all_annual_bills(html)
    if not candidates:
        return None
    return candidates[0]


# ---------------------------------------------------------------------------
# Step 3: Parse the per-year bill detail HTML
# ---------------------------------------------------------------------------


def _convert_bill_url_to_iframe(bill_url: str, county_cfg: dict) -> str:
    """``https://county-taxes.net/broward/property-tax/{b64}/bills/{uuid}``
    -> ``https://county-taxes.net/iframe-taxsys/broward.county-taxes.com/govhub/property-tax/{b64}/bills/{uuid}``

    The bill-history fragment's anchors use the **public** path
    (``county-taxes.net/{public_path}/{b64}/bills/{uuid}``); we rewrite it to
    the iframe-taxsys equivalent (which uses ``{iframe_path}`` without the
    county prefix and is served by the same backend at higher quality HTML).
    """
    public_prefix = f"{county_cfg['iframe_origin']}/{county_cfg['public_path']}/"
    iframe_prefix = (
        f"{county_cfg['iframe_origin']}/iframe-taxsys/{county_cfg['portal_subdomain']}"
        f"/govhub/{county_cfg['iframe_path']}/"
    )
    if bill_url.startswith(public_prefix):
        return iframe_prefix + bill_url[len(public_prefix):]
    if bill_url.startswith("/"):
        # Relative URL: prepend iframe-taxsys. Strip the {public_path} prefix.
        tail = bill_url.lstrip("/")
        # public_path is e.g. "broward/property-tax" — strip its full prefix.
        pub_segments = county_cfg["public_path"].split("/")
        for _ in pub_segments:
            if "/" in tail:
                tail = tail.split("/", 1)[1]
        return iframe_prefix + tail
    return bill_url  # last-resort: send as-is


def _parse_bill_detail(html: str) -> dict[str, Any]:
    """Parse the per-year bill detail HTML.

    The page layout (Broward 2025) is:

    - <h1>Real Estate Account #494225-04-0800</h1>
    - <h2>2025 ‍ Annual bill</h2>
    - Table 'bills' (1 row): Alternate Key, Escrow code, Millage code, Amount due, Print
    - Section "Ad Valorem Taxes":
        Header: Taxing authority | Millage | Assessed | Exemption | Taxable | Tax
        Rows by authority (BROWARD COUNTY GOVERNMENT, BROWARD CO SCHOOL BOARD,
        FORT LAUDERDALE, etc.) + a Subtotal row + a Total row.
    - Section "Non-Ad Valorem Assessments":
        Header: Levying authority | Rate | Amount
        Rows + "Total Non-Ad Valorem Assessments"
    - "Parcel details" section: owner/mailing/situs paragraphs.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {}

    # H1: "Real Estate Account #494225-04-0800"
    h1 = soup.find("h1")
    if h1:
        m = re.search(r"#\s*([0-9A-Za-z-]+)", h1.get_text(" ", strip=True))
        if m:
            out["display_apn"] = m.group(1)

    # H2 has the year
    for h in soup.find_all("h2"):
        m = re.search(r"\b(20\d{2})\b\s*.*Annual\s+bill", h.get_text(" ", strip=True), re.I)
        if m:
            out["tax_year"] = m.group(1)
            break

    # Ad-Valorem table — find the table whose header contains
    # "Taxing authority" + "Assessed" + "Taxable" + "Tax".
    ad_valorem_table = None
    for t in soup.find_all("table"):
        header_cells = [
            c.get_text(" ", strip=True).lower()
            for c in t.find_all("th")
        ] or [
            c.get_text(" ", strip=True).lower()
            for c in (t.find("tr").find_all("td") if t.find("tr") else [])
        ]
        joined = " | ".join(header_cells)
        if "taxing authority" in joined and "assessed" in joined and "taxable" in joined:
            ad_valorem_table = t
            break

    if ad_valorem_table is not None:
        # Compute assessed (max of the per-authority Assessed values, since most
        # authorities all report the same `$2,711,580` total just-value figure;
        # School Board reports a different basis with no Save Our Homes cap).
        assessed_values: list[float] = []
        taxable_values: list[float] = []
        exemption_values: list[float] = []
        tax_row_total = 0.0
        for tr in ad_valorem_table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 6:
                continue
            # Skip header
            if "taxing" in cells[0].lower() or cells[0].lower().startswith("taxing"):
                continue
            # Skip section breakers (only the authority name, rest empty)
            if not any(c for c in cells[1:]):
                continue
            # Skip totals/subtotals — handled below via "Total" check.
            label = cells[0]
            millage = cells[1]
            assessed = _parse_money(cells[2])
            exemption = _parse_money(cells[3])
            taxable = _parse_money(cells[4])
            tax = _parse_money(cells[5])
            if label.lower().startswith("total") or label.lower().startswith("subtotal"):
                if "ad valorem" in label.lower() or label.lower() == "total":
                    tax_row_total = tax or tax_row_total
                continue
            if assessed > 0:
                assessed_values.append(assessed)
            if taxable > 0:
                taxable_values.append(taxable)
            if exemption > 0:
                exemption_values.append(exemption)

        if assessed_values:
            out["assessed_just_value"] = max(assessed_values)
        if taxable_values:
            out["assessed_taxable_value"] = min(taxable_values)
        if exemption_values:
            out["assessed_exemptions"] = min(exemption_values)
        if tax_row_total:
            out["ad_valorem_total"] = tax_row_total

    # Non-ad-valorem totals
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        header = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if "levying authority" in " | ".join(header) and "amount" in " | ".join(header):
            non_ad_val_total = 0.0
            for tr in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not cells:
                    continue
                label = cells[0].lower()
                if "total" in label:
                    non_ad_val_total = _parse_money(cells[-1])
            if non_ad_val_total:
                out["non_ad_valorem_total"] = non_ad_val_total

    # Bills table at the top — extract amount_due + status from the row
    for t in soup.find_all("table"):
        cls = " ".join(t.get("class") or [])
        if "bills" in cls:
            rows = t.find_all("tr")
            if len(rows) >= 2:
                cells = [c.get_text(" ", strip=True) for c in rows[1].find_all(["td", "th"])]
                # E.g. ['2025 Annual bill', '338251', '—', '0312', '$0.00', 'paid Print (PDF) Downloading...']
                if len(cells) >= 5:
                    out["alternate_key"] = cells[1]
                    out["escrow_code"] = cells[2]
                    out["millage_code"] = cells[3]
                    out["amount_due"] = _parse_money(cells[4])
                    # The 'status' cell is the last one
                    status_blob = " ".join(cells[5:]).strip()
                    out["bill_status_blob"] = status_blob
            break

    # Parcel details: owner & situs
    # The "Parcel details" section is typically a definition list or labeled
    # divs. We grep the rendered text and use regex.
    text = soup.get_text("\n", strip=True)
    out["raw_text"] = text  # NEVER serialized externally; only used for fallback

    # Owner: usually a line of the form "Owner Name" then the actual name.
    m = re.search(r"Owner\s*\n+([^\n]{3,200})", text, re.I)
    if m:
        out["owner"] = m.group(1).strip()
    # Situs: "Situs address" or "Address"
    m = re.search(r"Situs\s+address\s*\n+([^\n]{3,200})", text, re.I)
    if m:
        out["situs_address"] = m.group(1).strip()
    else:
        m = re.search(r"Property\s+address\s*\n+([^\n]{3,200})", text, re.I)
        if m:
            out["situs_address"] = m.group(1).strip()

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lookup_grant_street_tax(
    apn: str,
    county_id: str,
    case_dir: Path,
    *,
    safe_owner: str = "tax",
    property_address: str = "",
    county_overrides: dict | None = None,
) -> TaxLookupResult:
    """End-to-end tax lookup for a Grant Street GovHub county (Broward etc.).

    Saves the bill-detail HTML to ``case_dir/tax_<safe_owner>_capture.html`` so
    it can be linked as ``source_artifact`` (mirrors what the playwright_runner
    does).
    """
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    county_key = _normalize_county(county_id)
    cfg = dict(COUNTY_DEFAULTS.get(county_key) or {})
    if not cfg:
        return TaxLookupResult(
            apn=apn,
            tax_year="",
            property_address=property_address,
            status="TAX_NO_RUNNER",
            notes=(
                f"grant_street_http has no default config for county {county_id!r} "
                f"(normalized={county_key!r}). Add an entry to COUNTY_DEFAULTS."
            ),
        )
    if county_overrides:
        cfg.update(county_overrides)

    # Per-county impersonation override (e.g. Duval Cloudflare-403s chrome120;
    # safari17_2_ios required). Backward-compatible for Broward/Hillsborough.
    session = cffi.Session(impersonate=cfg.get("impersonate", DEFAULT_IMPERSONATE))
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": cfg["referer"],
    })

    captured_at = datetime.now()

    # Step 1: Algolia
    # Some PA adapters (qPublic/Schneider) return APNs with a trailing `.0`
    # suffix (e.g. "32402900015000000010.0"). That suffix is NOT part of the
    # tax-system APN and prevents Algolia from matching the token list. Strip
    # the trailing `.0` literal before querying — this is safe because Algolia
    # uses prefix/token matching and the shorter form resolves correctly.
    algolia_apn = apn[:-2] if apn and apn.endswith(".0") else apn
    try:
        hit = _search_algolia(session, cfg, algolia_apn)
    except Exception as exc:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED", error=f"algolia search raised: {exc}",
            captured_at=captured_at,
        )
    if hit is None:
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_NO_RESULTS",
            notes=f"Algolia returned no hits for APN {apn!r} in {cfg['algolia_index']}",
            captured_at=captured_at,
        )

    # APN echo
    if hit.get("external_id") and not apn_matches(apn, hit["external_id"]):
        return TaxLookupResult(
            apn=apn, tax_year="", property_address=property_address,
            status="TAX_FAILED",
            error=f"APN echo mismatch: input={apn!r} algolia={hit['external_id']!r}",
            captured_at=captured_at,
        )

    parcel_b64 = hit["parcel_b64"]
    display_apn = hit.get("external_id", apn)

    # Step 2: bill history -> latest year + bill URL
    bh_url = _bill_history_url(cfg, parcel_b64)
    try:
        bh_resp = session.get(bh_url, timeout=30)
    except Exception as exc:
        return TaxLookupResult(
            apn=display_apn, tax_year="", property_address=property_address,
            status="TAX_FAILED", error=f"bill-history fetch raised: {exc}",
            source_url=bh_url, captured_at=captured_at,
        )
    if bh_resp.status_code != 200 or not bh_resp.text:
        return TaxLookupResult(
            apn=display_apn, tax_year="", property_address=property_address,
            status="TAX_FAILED",
            error=f"bill-history returned {bh_resp.status_code}",
            source_url=bh_url, captured_at=captured_at,
        )

    latest_bill = _find_latest_annual_bill(bh_resp.text)
    if not latest_bill:
        return TaxLookupResult(
            apn=display_apn, tax_year="", property_address=property_address,
            status="TAX_NO_RESULTS",
            notes="bill-history fragment loaded but contained no 'Annual bill' rows",
            source_url=bh_url, captured_at=captured_at,
        )

    # Step 3: bill detail HTML -> parse
    detail_url = _convert_bill_url_to_iframe(latest_bill["bill_url"], cfg)
    try:
        detail_resp = session.get(detail_url, timeout=30)
    except Exception as exc:
        return TaxLookupResult(
            apn=display_apn, tax_year=str(latest_bill["year"]),
            property_address=property_address,
            status="TAX_FAILED",
            error=f"bill detail fetch raised: {exc}",
            source_url=detail_url, captured_at=captured_at,
        )
    if detail_resp.status_code != 200 or not detail_resp.text:
        return TaxLookupResult(
            apn=display_apn, tax_year=str(latest_bill["year"]),
            property_address=property_address,
            status="TAX_FAILED",
            error=f"bill detail returned {detail_resp.status_code}",
            source_url=detail_url, captured_at=captured_at,
        )

    capture_path = case_dir / f"tax_{safe_owner}_capture.html"
    capture_path.write_text(detail_resp.text, encoding="utf-8")

    parsed = _parse_bill_detail(detail_resp.text)

    # Host whitelist
    if not host_in_whitelist(detail_url, cfg.get("authoritative_hosts") or [], mode="strict"):
        return TaxLookupResult(
            apn=display_apn,
            tax_year=parsed.get("tax_year") or str(latest_bill["year"]),
            property_address=property_address,
            status="TAX_FAILED",
            error=f"detail URL host not whitelisted: {detail_url!r}",
            source_url=detail_url,
            source_artifact=str(capture_path),
            captured_at=captured_at,
        )

    # Build installment list — Broward Florida portal shows a SINGLE annual
    # bill (no 1st/2nd installment split for paid bills). Emit a single
    # 'annual' installment with the bill amount + paid status. Some portals
    # also expose a discount schedule; we don't extract those.
    annual_amount = (
        parsed.get("amount_due", 0.0)
        + _parse_money(latest_bill["status_text"].split("Paid", 1)[-1])
        if latest_bill["status_text"].lower().startswith("paid")
        else parsed.get("amount_due", 0.0) or _parse_money(latest_bill["status_text"])
    )
    if not annual_amount:
        # Fallback: try to derive from ad_valorem_total + non_ad_valorem_total
        annual_amount = (parsed.get("ad_valorem_total") or 0.0) + (parsed.get("non_ad_valorem_total") or 0.0)

    paid_status = "PAID" if "paid" in (latest_bill["status_text"] or "").lower() else (
        "UNPAID" if "unpaid" in (latest_bill["status_text"] or "").lower() else ""
    )

    installments = [{
        "label": "annual",
        "amount": annual_amount,
        "status": paid_status,
        "due_date": "",  # FL annual due 03/31; portal doesn't display past-paid due dates
        "status_text": latest_bill["status_text"],
    }]

    # Owner / situs: fall back from Algolia hit if detail-page parse missed.
    owner = parsed.get("owner") or ""
    situs = parsed.get("situs_address") or ""
    if (not owner or not situs) and hit.get("entities"):
        # entities is a list of { external_id, key, label } per the public bundle.
        # Often the first entity's `label` is "OWNER_NAME, SITUS_ADDR".
        for e in hit["entities"]:
            lab = e.get("label") or ""
            if not owner and "," in lab:
                owner = lab.split(",", 1)[0].strip()
            if not situs and "," in lab:
                situs = ", ".join(p.strip() for p in lab.split(",")[1:])

    assessed_value = {}
    if parsed.get("assessed_just_value"):
        assessed_value["just_value"] = parsed["assessed_just_value"]
    if parsed.get("assessed_taxable_value"):
        assessed_value["net_taxable"] = parsed["assessed_taxable_value"]
    if parsed.get("assessed_exemptions"):
        assessed_value["exemptions"] = parsed["assessed_exemptions"]

    # Determine status
    verified: list[str] = []
    missing: list[str] = []
    for key in ("apn", "tax_year", "annual_total", "installments[0].amount"):
        if key == "apn" and display_apn:
            verified.append(key)
        elif key == "tax_year" and (parsed.get("tax_year") or latest_bill["year"]):
            verified.append(key)
        elif key == "annual_total" and annual_amount > 0:
            verified.append(key)
        elif key == "installments[0].amount" and annual_amount > 0:
            verified.append(key)
        else:
            missing.append(key)

    status = "TAX_SUCCESS" if not missing else ("TAX_PARTIAL" if verified else "TAX_FAILED")
    notes = "All required fields verified." if status == "TAX_SUCCESS" else (
        f"Partial: {len(verified)} verified, {len(missing)} missing"
        if status == "TAX_PARTIAL" else ""
    )

    result = TaxLookupResult(
        apn=display_apn,
        tax_year=str(parsed.get("tax_year") or latest_bill["year"]),
        property_address=situs or property_address,
        tra=parsed.get("millage_code") or "",
        assessed_value=assessed_value,
        installments=installments,
        annual_total=annual_amount,
        delinquent=("delinquent" in (latest_bill["status_text"] or "").lower()),
        special_assessments=[],
        source_url=detail_url,
        source_artifact=str(capture_path),
        captured_at=captured_at,
        status=status,
        verified_fields=verified,
        missing_fields=missing,
        notes=notes,
    )

    # Stash the bill-history URL as a secondary artifact pointer in `notes`
    # to keep the JSON compact (don't overload the dataclass).
    history_pointer = f" (history: {bh_url})"
    result.notes = (result.notes + history_pointer).strip()

    # Tag owner inside notes too (some downstream consumers read it).
    if owner:
        result.notes = (result.notes + f"; owner_on_record={owner}").strip()

    # ------------------------------------------------------------------
    # Best-effort prior-year (N-1) echo
    # ------------------------------------------------------------------
    # The bill-history fragment lists every recorded annual bill. If a
    # row exists for a year prior to ``latest_bill["year"]``, fetch its
    # detail HTML and populate the prior_year_* fields on the result.
    # Any failure here is swallowed -- prior-year is supplemental.
    try:
        _populate_prior_year(
            result=result,
            bh_html=bh_resp.text,
            current_year=latest_bill["year"],
            cfg=cfg,
            session=session,
        )
    except Exception as exc:
        _log(f"prior-year scrape skipped: {exc!r}")

    return result


def _populate_prior_year(
    *,
    result: TaxLookupResult,
    bh_html: str,
    current_year: int,
    cfg: dict,
    session: Any,
) -> None:
    """Best-effort prior-year (N-1) extraction.

    Looks at the bill-history fragment for a row immediately preceding
    ``current_year``, fetches its detail HTML, and mutates ``result`` in
    place to fill the ``prior_year_*`` fields. No-op if the prior-year
    row or its detail page can't be parsed.
    """
    all_bills = _parse_all_annual_bills(bh_html)
    prior = next((b for b in all_bills if b["year"] < current_year), None)
    if not prior:
        return

    prior_url = _convert_bill_url_to_iframe(prior["bill_url"], cfg)
    try:
        prior_resp = session.get(prior_url, timeout=30)
    except Exception as exc:
        _log(f"prior-year detail fetch raised: {exc!r}")
        return
    if prior_resp.status_code != 200 or not prior_resp.text:
        _log(f"prior-year detail returned status={prior_resp.status_code}")
        return

    parsed_prior = _parse_bill_detail(prior_resp.text)

    # Derive prior-year annual amount the same way the current-year path
    # does -- prefer amount_due + paid amount, fall back to ad_valorem +
    # non_ad_valorem totals.
    prior_status_text = prior.get("status_text") or ""
    if prior_status_text.lower().startswith("paid"):
        prior_annual = (
            parsed_prior.get("amount_due", 0.0)
            + _parse_money(prior_status_text.split("Paid", 1)[-1])
        )
    else:
        prior_annual = (
            parsed_prior.get("amount_due", 0.0)
            or _parse_money(prior_status_text)
        )
    if not prior_annual:
        prior_annual = (
            (parsed_prior.get("ad_valorem_total") or 0.0)
            + (parsed_prior.get("non_ad_valorem_total") or 0.0)
        )

    # Installment status — Grant Street portals show "Paid", "UNPAID",
    # "DELINQUENT" (or nothing). Map to the canonical vocabulary.
    status_l = prior_status_text.lower()
    if "delinquent" in status_l:
        inst_status = "DELINQUENT"
    elif "unpaid" in status_l:
        inst_status = "DELINQUENT"  # treat unpaid past-year as delinquent
    elif "paid" in status_l:
        inst_status = "PAID/CURRENT"
    elif "installment" in status_l or "plan" in status_l:
        inst_status = "INSTALLMENT_PLAN"
    else:
        inst_status = "NOT_AVAILABLE"

    result.prior_year_tax_year = int(prior["year"])
    result.prior_year_annual_amount = float(prior_annual) if prior_annual else None
    result.prior_year_just_value = (
        float(parsed_prior["assessed_just_value"])
        if parsed_prior.get("assessed_just_value") else None
    )
    result.prior_year_net_taxable = (
        float(parsed_prior["assessed_taxable_value"])
        if parsed_prior.get("assessed_taxable_value") else None
    )
    result.prior_year_installment_status = inst_status
    result.prior_year_paid_date = None  # Grant Street portal doesn't echo paid-date
    result.prior_year_source_url = prior_url
    result.prior_year_captured_at = datetime.now().isoformat()


__all__ = ["lookup_grant_street_tax", "COUNTY_DEFAULTS"]
