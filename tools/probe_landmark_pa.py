#!/usr/bin/env python3
"""Probe a Landmark-county Property Appraiser portal and capture fixtures.

This is step 1 of graduating a Landmark PA scaffold to a live adapter. It runs
HTTP-only (curl_cffi — Tony directive #1, no Selenium/Playwright) and saves the
raw material an engineer (or Claude) needs to write the parser:

  * the portal landing HTML
  * every <form> action + method + field names found
  * every <script src> and any link/endpoint whose text contains
    search / parcel / cama / api / detail
  * (optional) the result of an address or APN search, if you pass --search-url

Outputs go to docs/FL/source/landmark_pa_probe/<county_id>/ so the capture is
committed alongside the case material and can back fixture-driven unit tests.

Run it from an egress that can reach the portal (your workstation or the
pipeline host); some county portals block datacenter / non-US egress.

Examples
--------
    # 1) capture the landing page + discover the search form/endpoints
    python3 tools/probe_landmark_pa.py fl_escambia

    # 2) once you know the search URL, capture a real search + a parcel page
    python3 tools/probe_landmark_pa.py fl_escambia \
        --search-url "https://www.escpa.org/.../Search" \
        --address "120 Main St" \
        --detail-url "https://www.escpa.org/.../parcel?id=123"

The base_url comes from config/county_property_appraiser_urls.json so you never
hand-type it. Pass --base-url to override during discovery.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PA_CONFIG = REPO / "config" / "county_property_appraiser_urls.json"
OUT_ROOT = REPO / "docs" / "FL" / "source" / "landmark_pa_probe"

_IMPERSONATE = "chrome120"  # matches the working LeePA profile
_INTEREST = re.compile(r"(search|parcel|cama|api|detail|folio|strap)", re.I)


def _session():
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        sys.exit(
            "curl_cffi not installed. `pip install curl_cffi` "
            "(it is already a project dependency — use the repo venv)."
        )
    return cffi.Session(impersonate=_IMPERSONATE, timeout=30)


def _base_url(county_id: str, override: str | None) -> str:
    if override:
        return override
    cfg = json.loads(PA_CONFIG.read_text())
    entry = cfg.get("counties", {}).get(county_id)
    if not entry:
        sys.exit(f"{county_id} not in {PA_CONFIG.name}; pass --base-url to probe anyway.")
    return entry["base_url"]


def _discover(html: str) -> dict:
    forms = []
    for fm in re.finditer(r"<form\b[^>]*>", html, re.I):
        tag = fm.group(0)
        action = (re.search(r'action="([^"]*)"', tag) or [None, ""])[1]
        method = (re.search(r'method="([^"]*)"', tag) or [None, "GET"])[1]
        forms.append({"action": action, "method": method.upper()})
    fields = sorted(set(re.findall(r'<input\b[^>]*name="([^"]+)"', html, re.I)))
    scripts = sorted(set(re.findall(r'<script\b[^>]*src="([^"]+)"', html, re.I)))
    links = sorted(
        set(
            href
            for href in re.findall(r'href="([^"]+)"', html, re.I)
            if _INTEREST.search(href)
        )
    )
    return {"forms": forms, "input_fields": fields, "scripts": scripts,
            "interesting_links": links}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Probe a Landmark PA portal.")
    ap.add_argument("county_id", help="e.g. fl_escambia")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--search-url", default=None, help="capture a search if provided")
    ap.add_argument("--address", default=None)
    ap.add_argument("--apn", default=None)
    ap.add_argument("--detail-url", default=None, help="capture one parcel detail page")
    args = ap.parse_args(argv)

    base = _base_url(args.county_id, args.base_url)
    out = OUT_ROOT / args.county_id
    out.mkdir(parents=True, exist_ok=True)
    s = _session()
    summary = {"county_id": args.county_id, "base_url": base,
               "probed_at": datetime.now().isoformat(), "steps": []}

    # 1) landing page
    r = s.get(base)
    (out / "01_landing.html").write_text(r.text, encoding="utf-8", errors="replace")
    disc = _discover(r.text)
    summary["steps"].append({"step": "landing", "url": base,
                             "status": r.status_code, "discovered": disc})
    print(f"[landing] {base} -> HTTP {r.status_code} ({len(r.text):,} bytes)")
    for f in disc["forms"]:
        print(f"   form: {f['method']} {f['action']}")
    for ln in disc["interesting_links"][:15]:
        print(f"   link: {ln}")

    # 2) optional search
    if args.search_url and (args.address or args.apn):
        payload = {}
        if args.address:
            payload["address"] = args.address
        if args.apn:
            payload["apn"] = args.apn
        rs = s.post(args.search_url, data=payload)
        (out / "02_search.html").write_text(rs.text, encoding="utf-8", errors="replace")
        summary["steps"].append({"step": "search", "url": args.search_url,
                                 "payload": payload, "status": rs.status_code})
        print(f"[search]  {args.search_url} -> HTTP {rs.status_code} "
              f"({len(rs.text):,} bytes)  (NOTE: field names are guesses — "
              f"correct them from the landing form above)")

    # 3) optional detail page
    if args.detail_url:
        rd = s.get(args.detail_url)
        (out / "03_detail.html").write_text(rd.text, encoding="utf-8", errors="replace")
        summary["steps"].append({"step": "detail", "url": args.detail_url,
                                 "status": rd.status_code})
        print(f"[detail]  {args.detail_url} -> HTTP {rd.status_code} "
              f"({len(rd.text):,} bytes)")

    (out / "probe_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nSaved capture to {out}")
    print("Next: inspect 01_landing.html for the real search form/endpoint, then "
          "re-run with --search-url/--detail-url to capture fixtures, then "
          "implement the parser in property_appraiser/counties/"
          f"{args.county_id.replace('fl_','')}_pa.py against those saved files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
