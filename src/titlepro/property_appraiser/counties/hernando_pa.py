"""Hernando County (FL) Property Appraiser — SCAFFOLD (live probe pending).

Part of the Landmark next-batch wave. Recorder adapter + per-county recorder
config + tax recipe are already in place for Hernando; this is the missing
Property Appraiser anchor (Broward-Standard item #1).

Best-known portal (VERIFY ON PROBE): https://www.hernandopa-fl.us/

Probe checklist before implementing:
  1. Address search: capture the request (GET tokens? POST fields?) + the
     results grid shape (parcel id / folio / owner / situs columns).
  2. Parcel detail: capture owner_of_record, situs_address, legal_description,
     just/assessed value, homestead flag, year_built.
  3. Sale history: capture the sales grid (date, price, deed type, book/page or
     instrument #) — newest-first; this feeds the ANAND-class back-chain.
  4. Confirm HTTP-only access (no Cloudflare/Akamai/CAPTCHA); pick an
     impersonate profile if needed. NO Selenium/Playwright (Tony directive #1).

Then implement lookup_by_address / lookup_by_apn here, flip the config platform
to ``hernando_pa_http``, add a dedicated factory branch + real unit tests.
"""

from __future__ import annotations

from ._scaffold import LandmarkPAScaffold


class HernandoPA(LandmarkPAScaffold):
    SOURCE_LABEL = "Hernando County Property Appraiser"
    LIVE_PLATFORM = "hernando_pa_http"
