"""
County Registry System for CURE Multi-County Support.

This module provides:
- COUNTY_REGISTRY: Master dictionary of all supported counties
- get_recorder(): Factory function to instantiate the correct adapter
- get_supported_counties(): List of available county IDs
- get_county_info(): Get metadata about a specific county
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..base_recorder import BaseRecorderSearch

# Base path for config files
CONFIG_DIR = Path(__file__).parent / "config"


# Master registry of all supported California counties
# Each entry maps county_id to its configuration
COUNTY_REGISTRY: Dict[str, Dict] = {
    # =====================
    # RecorderWorks Platform (5 counties) - No CAPTCHA
    # =====================
    "amador": {
        "platform": "recorderworks",
        "config": "amador.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Amador County",
    },
    "contra_costa": {
        "platform": "recorderworks",
        "config": "contra_costa.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Contra Costa County",
    },
    "imperial": {
        "platform": "recorderworks",
        "config": "imperial.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Imperial County",
    },
    "merced": {
        "platform": "recorderworks",
        "config": "merced.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Merced County",
    },
    "orange": {
        "platform": "recorderworks",
        "config": "orange.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Orange County",
    },
    "stanislaus": {
        "platform": "recorderworks",
        "config": "stanislaus.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Stanislaus County",
    },

    # =====================
    # Tyler Technologies Platform (18 counties)
    # =====================
    # No CAPTCHA (5 counties)
    "calaveras": {
        "platform": "tyler",
        "config": "calaveras.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Calaveras County",
    },
    "monterey": {
        "platform": "tyler",
        "config": "monterey.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Monterey County",
    },
    "san_luis_obispo": {
        "platform": "tyler",
        "config": "san_luis_obispo.json",
        "state": "CA",
        "captcha": False,
        "display_name": "San Luis Obispo County",
    },
    "santa_cruz": {
        "platform": "tyler",
        "config": "santa_cruz.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Santa Cruz County",
    },
    "trinity": {
        "platform": "tyler",
        "config": "trinity.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Trinity County",
    },
    "riverside": {
        "platform": "tyler",
        "config": "riverside.json",
        "state": "CA",
        "captcha": False,
        "display_name": "Riverside County",
    },

    # With CAPTCHA (13 counties)
    "del_norte": {
        "platform": "tyler",
        "config": "del_norte.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Del Norte County",
    },
    "fresno": {
        "platform": "tyler",
        "config": "fresno.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Fresno County",
    },
    "humboldt": {
        "platform": "tyler",
        "config": "humboldt.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Humboldt County",
    },
    "inyo": {
        "platform": "tyler",
        "config": "inyo.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Inyo County",
    },
    "kings": {
        "platform": "tyler",
        "config": "kings.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Kings County",
    },
    "lake": {
        "platform": "tyler",
        "config": "lake.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Lake County",
    },
    "madera": {
        "platform": "tyler",
        "config": "madera.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Madera County",
    },
    "san_benito": {
        "platform": "tyler",
        "config": "san_benito.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "San Benito County",
    },
    "san_bernardino": {
        "platform": "tyler",
        "config": "san_bernardino.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "San Bernardino County",
    },
    "san_joaquin": {
        "platform": "tyler",
        "config": "san_joaquin.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "San Joaquin County",
    },
    "sierra": {
        "platform": "tyler",
        "config": "sierra.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Sierra County",
    },
    "tulare": {
        "platform": "tyler",
        "config": "tulare.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Tulare County",
    },
    "tuolumne": {
        "platform": "tyler",
        "config": "tuolumne.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "image",
        "display_name": "Tuolumne County",
    },
    "yolo": {
        "platform": "tyler",
        "config": "yolo.json",
        "state": "CA",
        "captcha": True,
        "captcha_type": "image",
        "display_name": "Yolo County",
    },

    # =====================
    # AcclaimWeb Platform (1 county) - No CAPTCHA
    # =====================
    "san_diego": {
        "platform": "acclaimweb",
        "config": "san_diego.json",
        "state": "CA",
        "captcha": False,
        "display_name": "San Diego County",
    },

    # =====================
    # FLORIDA — Top 5 by population (2026-05-21, Tony Roveda first test-subject batch)
    # =====================
    # Tyler HTTP (1 county, active) — pure-HTTP adapter (no Selenium/Playwright).
    # Verified live 2026-05-21 against Orange FL Self-Service. 2Captcha solves
    # the reCAPTCHA on /ssweb/user/disclaimer; the disclaimer-accept POST sets
    # a session flag that unlocks all downstream /ssweb/search/* routes.
    # The 14 reCAPTCHA-enabled CA Tyler counties (fresno, sbd, etc.) keep the
    # legacy Selenium adapter until separately validated against this path.
    "fl_orange": {
        "platform": "tyler_http",
        "config": "orange.json",
        "state": "FL",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Orange County (FL)",
    },
    # AcclaimWeb (1 county, active) — drop-in for acclaimweb_adapter.py
    # Toggle to acclaimweb_http after HTTP adapter is validated against live Broward
    "fl_broward": {
        "platform": "acclaimweb",
        "config": "broward.json",
        "state": "FL",
        "captcha": False,
        "display_name": "Broward County (FL)",
    },
    # Landmark (16 FL counties; Palm Beach is the first active one — 2026-05-26)
    # Wave-2 additions (Lee, Escambia, St. Johns, Clay, Hernando, Bay, Martin,
    # Indian River, Citrus, Flagler, Monroe, Walton, Wakulla, Levy, Okeechobee)
    # plug in via per-county JSON config — see config/fl/landmark_template.json
    # and registry the same way as fl_palm_beach.
    "fl_palm_beach": {
        "platform": "landmark",
        "config": "palm_beach.json",
        "state": "FL",
        "captcha": True,
        "captcha_type": "recaptcha_v2",
        "display_name": "Palm Beach County (FL)",
    },
    # Proprietary (2 counties)
    # Miami-Dade: SKELETON — config promoted to in_progress, adapter shell wired,
    # method bodies pending live-portal probe. See docs/FL/Miami_Dade_Indexing_Review.md.
    "fl_miami_dade": {
        "platform": "miami_dade",
        "config": "miami_dade.json",
        "state": "FL",
        "captcha": False,
        "display_name": "Miami-Dade County (FL)",
        "stub": True,
    },
    # Hillsborough FL — Pure-HTTP adapter (no Selenium/Playwright). Hillsborough
    # Clerk's portal is bare Microsoft-IIS with zero anti-bot; a single JSON
    # POST to /Public/ORIUtilities/DocumentSearch/api/Search returns the full
    # ResultList. PDF download via /OverlayWatermark/api/Watermark/{id} with
    # Referer header. Combined name search (party_type post-filtered).
    # Verified 2026-05-26 against live portal for FROMER + DEL MONTE subjects.
    "fl_hillsborough": {
        "platform": "hillsborough_http",
        "config": "hillsborough.json",
        "state": "FL",
        "captcha": False,
        "display_name": "Hillsborough County (FL)",
    },
    # Manatee FL — Proprietary records.manateeclerk.com ASP.NET MVC.
    # Two-stage HTTP flow (GET → __RequestVerificationToken → POST). No CAPTCHA.
    # Local cache at manatee_cache.db (2.68M rows, 2007-2025) for offline searches.
    # Reference client: US_Counties_Data/FL/AIProjects/Manatee_Title_Abstractor_Tools/query_manatee_clerk.py
    # Test subject verified 2026-05-23: FERNANDEZ + ROZANES @ 4837 SABAL HARBOUR DR BRADENTON.
    "fl_manatee": {
        "platform": "manatee_http",
        "config": "manatee.json",
        "state": "FL",
        "captcha": False,
        "display_name": "Manatee County (FL)",
    },

    # =====================
    # FLORIDA — Wave-2 Landmark counties (15 added 2026-05-29)
    # All share platform="landmark" — config-only swap from Palm Beach
    # Most require runtime sitekey scrape (async JS render); only Martin has inline
    # Bay is captcha-OFF (live-confirmed); Clay needs safari17_2_ios for Cloudflare
    # =====================
    "fl_clay": {"platform": "landmark", "config": "clay.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Clay County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter (Landmark ShowCaptcha not server-enforced); PA qpublic residential-gated"},
    "fl_hernando": {"platform": "landmark", "config": "hernando.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Hernando County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter; PA = SPA-scaffold (deferred)"},
    "fl_martin": {"platform": "landmark", "config": "martin.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v2", "display_name": "Martin County (FL)", "stub": True},
    "fl_citrus": {"platform": "landmark", "config": "citrus.json", "state": "FL", "captcha": False, "display_name": "Citrus County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-19. Akamai CDN but no CF-challenge. captcha_required=false (ShowCaptcha returns True but server does NOT enforce it — NameSearch accepts empty g-recaptcha-response and returns real rows). Surname-only search required (LASTNAME only, no comma-first format). 20-col row layout in citrus.json. chrome120 impersonation sufficient."},
    "fl_monroe": {"platform": "landmark", "config": "monroe.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Monroe County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter; PA qpublic residential-gated"},
    "fl_lee": {"platform": "landmark", "config": "lee.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v2", "display_name": "Lee County (FL)", "stub": True, "_notes": "Akamai-fronted; safari17_2_ios + warmed session required"},
    "fl_escambia": {"platform": "landmark", "config": "escambia.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Escambia County (FL)", "stub": False, "_live": "2026-06-19 LIVE-VALIDATED recorder from datacenter (HILLIS report shipped)", "_notes": "Cloudflare-fronted; safari17_2_ios required; versioned subpath /LandmarkWeb1.4.6.134"},
    "fl_bay": {"platform": "landmark", "config": "bay.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v3", "display_name": "Bay County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-18 (ROMAS: 9 deed rows). reCAPTCHA v3 server-side (NameSearch needs v3 token; ShowCaptcha governs only the v2 widget). 26-col layout (instrument#=col12, doc_id=col25) via column_map in bay.json. landmark_adapter.py hardened for reCAPTCHA v3 + per-county column_map."},
    "fl_indian_river": {"platform": "landmark", "config": "indian_river.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Indian River County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter; PA qpublic residential-gated"},
    "fl_flagler": {"platform": "landmark", "config": "flagler.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Flagler County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter; PA qpublic residential-gated"},
    "fl_st_johns": {"platform": "landmark", "config": "st_johns.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v2", "display_name": "St. Johns County (FL)", "stub": True, "_notes": "/Landmark/ subpath (no Web suffix)"},
    "fl_walton": {"platform": "landmark", "config": "walton.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Walton County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter (beacon qpublic PA residential-gated)"},
    "fl_wakulla": {"platform": "landmark", "config": "wakulla.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v2", "display_name": "Wakulla County (FL)", "stub": True, "_http_only": True, "_notes": "HTTP-only (NOT HTTPS); lowercase /Landmarkweb/"},
    "fl_levy": {"platform": "landmark", "config": "levy.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v2", "display_name": "Levy County (FL)", "stub": True, "_notes": "lowercase /landmarkweb subpath"},
    "fl_okeechobee": {"platform": "landmark", "config": "okeechobee.json", "state": "FL", "captcha": False, "captcha_type": "none", "display_name": "Okeechobee County (FL)", "stub": False, "_live": "2026-06-19 recorder live from datacenter; PA = SPA-scaffold (deferred)", "_notes": "/LandmarkWebLive (variant); may expose different endpoints"},
    # =====================
    # 0610 batch (Peter-comparison counties)
    # =====================
    "fl_pasco": {"platform": "pasco_asp_http", "config": "pasco.json", "state": "FL", "captcha": False, "display_name": "Pasco County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10 (RILEY e2e: counts [27,26,1,12,7,7], 28 instruments). Doc-image download needs BotDetect captcha solve (ticketed). In-house classic-ASP on bare IIS at app.pascoclerk.com; no anti-bot. Result-page HTML shapes fixture-locked, live-verify on first Wave-2 run."},
    "fl_duval": {"platform": "acclaimweb_http", "config": "duval.json", "state": "FL", "captcha": False, "display_name": "Duval County (FL)", "stub": True, "_notes": "'OnCore'-branded host runs Aptitude Acclaim public search at ROOT path (no /AcclaimWeb prefix) — config-only swap from Broward. Geo-blocks non-US egress at TCP level."},
    "fl_brevard": {"platform": "acclaimweb_http", "config": "brevard.json", "state": "FL", "captcha": False, "display_name": "Brevard County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10/11 (LEWIS e2e: 7 runs [1,0,20,6,74,8,9], 28 PDFs, three_step_json flow landed in acclaimweb_http_adapter with comma-format normalization fix). Harris AcclaimWeb at vaclmweb1.brevardclerk.us. NO Cloudflare / NO anti-forgery token (probed live 2026-06-10). DELTA vs Broward: 3-step search chain (SearchTypeName -> SearchTypePreName -> GridResults JSON) — needs search_flow='three_step_json' branch in the adapter; config carries numeric DocTypes=80 / BookTypes=3 / IsParsedName=False / record_type=3. Disclaimer + Atala PDF download verified live (instr 1996067410 -> 103KB PDF)."},
    "fl_sarasota": {"platform": "sarasota_clerknet_http", "config": "sarasota.json", "state": "FL", "captcha": False, "display_name": "Sarasota County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10 (BRUNO e2e: 10 names, 15 instruments, 14/15 PDFs pulled). Custom in-house ClerkNet ASP.NET WebForms + Telerik at secure.sarasotaclerk.com/OfficialRecords.aspx. No Cloudflare, no CAPTCHA, no disclaimer. Result-grid columns + doc-image href pattern unverified until first live POST."},
    "fl_polk": {"platform": "publicsoft_or", "config": "polk.json", "state": "FL", "captcha": False, "display_name": "Polk County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10 (BUNKER e2e: search+APN+pdf pulls all worked first-try). Field-map tickets open. PublicSoft/Kofile BrowserView OR (apps.polkcountyclerk.net/browserviewor/). RSA-encrypted (JSEncrypt PKCS1v1.5) field submission; no reCAPTCHA/disclaimer. Host geo-fenced — live e2e needs US egress."},
    "fl_volusia": {"platform": "volusia_or_m", "config": "volusia.json", "state": "FL", "captcha": False, "display_name": "Volusia County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10 (GUILD e2e: counts [11,4,24,14,5], disclaimer+PDF download+pagination all working). PROPRIETARY ASP.NET WebForms at app02.clerk.org/or_m/ — adapter volusia_or_m_adapter.py. clerk.org geo-blocks non-US egress. Direct retrieval: Default.aspx?s=orapr&i={instrument}."},
    "fl_seminole": {"platform": "duprocess_http", "config": "seminole.json", "state": "FL", "captcha": False, "display_name": "Seminole County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-10 (PORTILLA e2e: counts [16,17,4], 15/15 PDFs, X-Api-Token gate + criteria fixes landed). DuProcess Web Inquiry (recording.seminoleclerk.org/DuProcessWebInquiry/). Pure-HTTP JSON API; no Cloudflare/reCAPTCHA/disclaimer; anonymous search. Adapter: duprocess_http_adapter.py."},
    # =====================
    # Clericus / myfloridacounty.com platform (0618 — 4 counties, one shared adapter)
    # =====================
    "fl_nassau": {"platform": "clericus_http", "config": "nassau.json", "state": "FL", "captcha": True, "captcha_type": "turnstile", "display_name": "Nassau County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-18 (KELLY: 25 rows p1, pagination no re-turnstile, PDF 117KB). myfloridacounty.com/orisearch/45. Turnstile sitekey 0x4AAAAAAA64PTBePmuGbrkR. Tax: Grant Street."},
    "fl_sumter": {"platform": "clericus_http", "config": "sumter.json", "state": "FL", "captcha": True, "captcha_type": "turnstile", "display_name": "Sumter County (FL)", "stub": False, "_notes": "myfloridacounty.com/orisearch/60. Turnstile sitekey 0x4AAAAAAA64PTBePmuGbrkR. Tax: Grant Street. Config-only swap from Nassau."},
    "fl_de_soto": {"platform": "clericus_http", "config": "de_soto.json", "state": "FL", "captcha": True, "captcha_type": "turnstile", "display_name": "DeSoto County (FL)", "stub": False, "_notes": "myfloridacounty.com/orisearch/14. Turnstile sitekey 0x4AAAAAAA64PTBePmuGbrkR. Tax: VisualGov. Config-only swap from Nassau."},
    "fl_franklin": {"platform": "clericus_http", "config": "franklin.json", "state": "FL", "captcha": True, "captcha_type": "turnstile", "display_name": "Franklin County (FL)", "stub": False, "_notes": "myfloridacounty.com/orisearch/19. Turnstile sitekey 0x4AAAAAAA64PTBePmuGbrkR. Tax: VisualGov. Config-only swap from Nassau."},
    "fl_lake": {"platform": "onecare_http", "config": "lake.json", "state": "FL", "captcha": False, "display_name": "Lake County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-18 (officialrecords.lakecountyclerk.org; no CF). OneCare=AcclaimWeb/Harris Telerik-2012; three-step search (SearchTypeName treeview -> SearchTypePreName -> GridResults JSON w/ X-Requested-With:XMLHttpRequest). Deed DocType=26, OR BookType=1, PDF=/Image/DocumentPdfAllPages/{TransactionItemId}."},
    "fl_pinellas": {"platform": "onecare_http", "config": "pinellas.json", "state": "FL", "captcha": False, "display_name": "Pinellas County (FL)", "stub": True, "_notes": "CF-403 from datacenter (same CF block as Broward). Same OneCare adapter as Lake; needs residential IP + cf_clearance. DocType/BookType assumed from Lake -> verify live from residential."},
    "fl_charlotte": {"platform": "charlotte_kendo_http", "config": "charlotte.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v3", "display_name": "Charlotte County (FL)", "stub": True, "_notes": "Adapter code-correct (ctor + /Home/Verify step fixed). recording.charlotteclerk.com, ASP.NET Core MVC + Kendo. RESIDENTIAL-GATED: reCAPTCHA v3 scores 0 from datacenter -> /Home/Verify rejects. Live-validate from residential."},
    "fl_marion": {"platform": "marion_newvision_http", "config": "marion.json", "state": "FL", "captcha": True, "captcha_type": "recaptcha_v3", "display_name": "Marion County (FL)", "stub": True, "_notes": "Adapter code-correct (token field RecaptchaResponseV3, action Search_partySearchForm). NewVision BrowserView (publicsoft_or family), no CF, encryptData=0. RESIDENTIAL-GATED: reCAPTCHA v3 scores 0 from datacenter. Live-validate from residential."},
    "fl_santa_rosa": {"platform": "acclaimweb_telerik_http", "config": "santa_rosa.json", "state": "FL", "captcha": False, "display_name": "Santa Rosa County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-18 (WHITE TIMOTHY: 10 docs). acclaim.srccol.com/AcclaimWeb — OLD AcclaimWeb/Telerik RadGrid 2012, no CF/Akamai. Disclaimer st-param needs full /AcclaimWeb path; exact-name single-leaf select (multi-leaf -> 500). Tax: Grant Street."},
    "fl_leon": {"platform": "leon_lforms_http", "config": "leon.json", "state": "FL", "captcha": False, "display_name": "Leon County (FL)", "stub": False, "_notes": "LIVE-VALIDATED 2026-06-18 (JONES TELLIE: 8 docs). lforms.leonclerk.com/official_records/ classic-ASP; reCAPTCHA v2 client-side-only (server doesn't validate). No CF. Tax: Grant Street."},
}


def get_supported_counties() -> List[str]:
    """
    Get list of all supported county IDs.

    Returns:
        List of county IDs (lowercase, underscore-separated)
    """
    return list(COUNTY_REGISTRY.keys())


def get_county_info(county_id: str) -> Optional[Dict]:
    """
    Get metadata about a specific county.

    Args:
        county_id: County identifier (e.g., "orange", "fresno")

    Returns:
        Dictionary with county metadata, or None if not found
    """
    county_id = county_id.lower().replace(" ", "_").replace("-", "_")
    return COUNTY_REGISTRY.get(county_id)


def load_county_config(county_id: str) -> Dict:
    """
    Load the full JSON configuration for a county.

    Looks under `config/<state>/<config>` where <state> comes from the registry
    entry (lowercase, e.g. "ca", "fl"); defaults to "ca" if the entry omits it.

    Args:
        county_id: County identifier

    Returns:
        Full configuration dictionary from JSON file

    Raises:
        ValueError: If county not found
        FileNotFoundError: If config file missing
    """
    info = get_county_info(county_id)
    if not info:
        raise ValueError(f"Unknown county: {county_id}. Supported: {get_supported_counties()}")

    state = (info.get("state") or "ca").lower()
    config_path = CONFIG_DIR / state / info["config"]
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r') as f:
        return json.load(f)


def get_recorder(county_id: str, start_date: str = "01/01/2010", end_date: str = None) -> "BaseRecorderSearch":
    """
    Factory function to get the appropriate recorder adapter for a county.

    Args:
        county_id: County identifier (e.g., "orange", "fresno")
        start_date: Search start date in MM/DD/YYYY format
        end_date: Search end date in MM/DD/YYYY format (defaults to today)

    Returns:
        Configured recorder adapter instance

    Raises:
        ValueError: If county not supported
        ImportError: If adapter not available
    """
    county_id = county_id.lower().replace(" ", "_").replace("-", "_")

    info = get_county_info(county_id)
    if not info:
        raise ValueError(f"Unsupported county: {county_id}. Supported counties: {get_supported_counties()}")

    platform = info["platform"]
    config = load_county_config(county_id)

    if platform == "recorderworks":
        from .adapters.recorderworks_adapter import RecorderWorksAdapter
        return RecorderWorksAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "tyler":
        from .adapters.tyler_adapter import TylerAdapter
        adapter = TylerAdapter(config, start_date=start_date, end_date=end_date)

        # Auto-wire 2Captcha solver for CAPTCHA counties when CAPTCHA_API_KEY is set
        # AND the county's config opts in via allow_automated_captcha_solver: true
        if config.get("captcha_required") and config.get("allow_automated_captcha_solver"):
            try:
                from ..captcha.recaptcha_solver import get_captcha_solver
                solver = get_captcha_solver()
                if solver:
                    adapter.set_captcha_solver(solver)
                    print(f"  CAPTCHA solver configured for {adapter.county_name} County")
            except Exception as e:
                print(f"  CAPTCHA solver not available: {e} (will fall back to manual checkpoint)")

        return adapter

    elif platform == "acclaimweb":
        from .adapters.acclaimweb_adapter import AcclaimWebRecorderSearch
        return AcclaimWebRecorderSearch(config, start_date=start_date, end_date=end_date)

    elif platform == "acclaimweb_http":
        # Pure-HTTP AcclaimWeb adapter (Phase 1 CURE restructure). Cookies are
        # minted once via undetected-chromedriver and persisted to a jar; the
        # adapter itself never spins up a browser.
        from .adapters.acclaimweb_http_adapter import AcclaimWebHTTPAdapter
        return AcclaimWebHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "manatee_http":
        # Pure-HTTP adapter for Manatee FL Clerk (records.manateeclerk.com).
        # No Cloudflare, no CAPTCHA — two-stage anti-forgery token flow only.
        from .adapters.manatee_http_adapter import ManateeHTTPAdapter
        return ManateeHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "miami_dade":
        # Custom proprietary adapter — skeleton in place, method bodies
        # pending live-portal probe. Instantiating succeeds (so config-wiring
        # tests pass) but any search/download call raises NotImplementedError
        # with a pointer to the indexing review.
        from .adapters.miami_dade_adapter import MiamiDadeRecorderSearch
        return MiamiDadeRecorderSearch(config, start_date=start_date, end_date=end_date)

    elif platform == "tyler_http":
        # Pure-HTTP Tyler adapter (Phase 1 CURE restructure). Verified live
        # 2026-05-21 against Orange FL Self-Service. Auto-wires the 2Captcha
        # solver when the county's config opts in via
        # ``allow_automated_captcha_solver: true``.
        from .adapters.tyler_http_adapter import TylerHTTPAdapter
        adapter = TylerHTTPAdapter(config, start_date=start_date, end_date=end_date)
        if config.get("captcha_required") and config.get("allow_automated_captcha_solver"):
            try:
                from ..captcha.recaptcha_solver import get_captcha_solver
                solver = get_captcha_solver()
                if solver:
                    adapter.set_captcha_solver(solver)
                    print(f"  CAPTCHA solver configured for {adapter.county_name} County")
            except Exception as e:
                print(f"  CAPTCHA solver not available: {e} (will use inline 2Captcha API)")
        return adapter

    elif platform == "hillsborough_http":
        # Pure-HTTP adapter for the Hillsborough Clerk's REST API. No browser,
        # no anti-bot bypass needed — portal is bare IIS. Subclass of
        # BaseRecorderSearch with browser methods collapsed to no-ops.
        from .adapters.hillsborough_http_adapter import HillsboroughHTTPAdapter
        return HillsboroughHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "landmark":
        # Landmark Web Official Records — Palm Beach FL is the first active
        # county; ~16 other FL counties unlock with config-only swaps. Pure
        # HTTP (curl_cffi + BeautifulSoup), reCAPTCHA-protected by default.
        from .adapters.landmark_adapter import LandmarkAdapter
        adapter = LandmarkAdapter(config, start_date=start_date, end_date=end_date)

        # Auto-wire 2Captcha when CAPTCHA_API_KEY is set AND the county opts
        # in via allow_automated_captcha_solver: true (same pattern as Tyler).
        if config.get("captcha_required") and config.get("allow_automated_captcha_solver"):
            try:
                from ..captcha.recaptcha_solver import get_captcha_solver
                solver = get_captcha_solver()
                if solver:
                    adapter.set_captcha_solver(solver)
                    print(f"  CAPTCHA solver configured for {adapter.county_name} County")
            except Exception as e:
                print(f"  CAPTCHA solver not available: {e} (will fall back to manual checkpoint)")

        return adapter

    elif platform == "pasco_asp_http":
        # Pasco County in-house classic-ASP official-records app on bare IIS
        # (app.pascoclerk.com). Search/detail are anti-bot-free, but the
        # document-IMAGE flow is gated by a Lanap BotDetect 6-char text
        # captcha. Auto-wire the 2Captcha key from CAPTCHA_API_KEY so
        # download_pdf() can solve it (falls back to a structured error
        # naming the gate when no key is set — never a silent skip).
        import os as _os
        from .adapters.pasco_http_adapter import PascoHTTPAdapter
        if not config.get("captcha_api_key"):
            _key = _os.environ.get("CAPTCHA_API_KEY")
            if _key:
                config = {**config, "captcha_api_key": _key}
        return PascoHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "sarasota_clerknet_http":
        # Sarasota FL — custom ClerkNet WebForms portal. Pure-HTTP (Tony #1).
        from .adapters.sarasota_clerknet_http_adapter import SarasotaClerkNetHTTPAdapter
        return SarasotaClerkNetHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "publicsoft_or":
        # PublicSoft/Kofile BrowserView Official Records (Polk FL is first). Pure
        # HTTP (curl_cffi + cryptography). RSA-PKCS1v1.5 (JSEncrypt-compatible)
        # field encryption; no reCAPTCHA. See adapters/publicsoft_or_adapter.py.
        from .adapters.publicsoft_or_adapter import PublicSoftORAdapter
        return PublicSoftORAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "volusia_or_m":
        # Volusia FL — proprietary ASP.NET WebForms at app02.clerk.org/or_m/.
        # Pure HTTP (curl_cffi); VIEWSTATE harvest + postback per search.
        from .adapters.volusia_or_m_adapter import VolusiaOrMAdapter
        return VolusiaOrMAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "duprocess_http":
        # Pure-HTTP DuProcess Web Inquiry adapter (Seminole FL et al.). JSON GET
        # API; no Cloudflare/reCAPTCHA/disclaimer; anonymous search (user_id='').
        from .adapters.duprocess_http_adapter import DuProcessHTTPAdapter
        return DuProcessHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "clericus_http":
        # Pure-HTTP Clericus/myfloridacounty.com adapter (FL — 23 counties).
        # JSP server with Cloudflare Turnstile on every search POST. Solved via
        # 2captcha (CAPTCHA_API_KEY env var). Pagination (page 2+) needs no re-solve.
        # County differentiated by clericus_county_id in config. PDF download via
        # /orisearch/s/image?q1=<q1>&q2=<q2_hash>. No parcel-ID search.
        # LIVE-VALIDATED 2026-06-18: Nassau (county_id=45, KELLY deed search).
        from .adapters.clericus_http_adapter import ClericusHTTPAdapter
        return ClericusHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "onecare_http":
        # Pure-HTTP OneCare adapter (AcclaimWeb/Harris Telerik-2012; FL — Lake,
        # Pinellas, etc.). Three-step search: SearchTypeName treeview ->
        # SearchTypePreName -> GridResults JSON (requires X-Requested-With:
        # XMLHttpRequest). Lake live-validated 2026-06-18 (no CF); Pinellas
        # CF-blocked (needs residential). County differentiated by config.
        from .adapters.onecare_http_adapter import OneCareHTTPAdapter
        return OneCareHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "charlotte_kendo_http":
        # Pure-HTTP Charlotte FL recorder (recording.charlotteclerk.com).
        # ASP.NET Core MVC + Kendo UI; reCAPTCHA v3 (GET /Home/Verify?token=
        # then POST /Render/GetDocumentView JSON). CF passes via curl_cffi.
        # Code-correct; reCAPTCHA v3 scores 0 from datacenter -> needs residential.
        from .adapters.charlotte_kendo_http_adapter import CharlotteKendoHTTPAdapter
        return CharlotteKendoHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "marion_newvision_http":
        # Pure-HTTP Marion FL recorder (nvweb.marioncountyclerk.org/BrowserView/).
        # NewVision BrowserView (publicsoft_or family); encryptData=0; reCAPTCHA v3
        # field RecaptchaResponseV3, action Search_partySearchForm. Code-correct;
        # reCAPTCHA v3 scores 0 from datacenter -> needs residential.
        from .adapters.marion_newvision_http_adapter import MarionNewVisionHTTPAdapter
        return MarionNewVisionHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "acclaimweb_telerik_http":
        # Pure-HTTP OLD AcclaimWeb / ASP.NET MVC + Telerik RadGrid (FL — Santa
        # Rosa et al.). No Cloudflare/Akamai; disclaimer handshake; exact-name
        # single-leaf select then ExportCsv. Live-validated 2026-06-18 (Santa Rosa).
        from .adapters.acclaimweb_telerik_http_adapter import AcclaimWebTelerikHTTPAdapter
        return AcclaimWebTelerikHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform == "leon_lforms_http":
        # Pure-HTTP Leon FL recorder (lforms.leonclerk.com/official_records/).
        # Classic ASP; reCAPTCHA v2 enforced client-side only (no server check).
        # Live-validated 2026-06-18 (JONES TELLIE).
        from .adapters.leon_lforms_http_adapter import LeonLformsHTTPAdapter
        return LeonLformsHTTPAdapter(config, start_date=start_date, end_date=end_date)

    elif platform in ("onecare", "duprocess", "clericus", "proprietary"):
        raise NotImplementedError(
            f"Adapter for platform '{platform}' (county {county_id}) is not yet built. "
            f"See docs/FL/FL_Platform_Examination_Guide.md + docs/FL/FL_Implementation_Plan.md "
            f"for the build wave order. Stub config exists at config/{info.get('state','??').lower()}/{info.get('config','?')}."
        )

    else:
        raise ValueError(f"Unknown platform '{platform}' for county {county_id}")


def get_counties_by_platform(platform: str) -> List[str]:
    """
    Get all counties using a specific platform.

    Args:
        platform: Platform name ("recorderworks" or "tyler")

    Returns:
        List of county IDs using that platform
    """
    return [
        county_id
        for county_id, info in COUNTY_REGISTRY.items()
        if info["platform"] == platform
    ]


def get_counties_without_captcha() -> List[str]:
    """
    Get all counties that don't require CAPTCHA.

    Returns:
        List of county IDs without CAPTCHA requirement
    """
    return [
        county_id
        for county_id, info in COUNTY_REGISTRY.items()
        if not info.get("captcha", False)
    ]


def get_counties_with_captcha() -> List[str]:
    """
    Get all counties that require CAPTCHA.

    Returns:
        List of county IDs with CAPTCHA requirement
    """
    return [
        county_id
        for county_id, info in COUNTY_REGISTRY.items()
        if info.get("captcha", False)
    ]


# Convenience function to list all counties with details
def list_counties() -> List[Dict]:
    """
    Get detailed list of all supported counties.

    Returns:
        List of dictionaries with county details
    """
    counties = []
    for county_id, info in COUNTY_REGISTRY.items():
        counties.append({
            "id": county_id,
            "name": info["display_name"],
            "platform": info["platform"],
            "captcha_required": info.get("captcha", False),
            "captcha_type": info.get("captcha_type"),
        })
    return sorted(counties, key=lambda x: x["name"])
