"""
Broward AcclaimWeb state-contamination bug reproducer.

Two production runs (SIMMONS, ANAND) showed a [N, 0, 0, 0, 0, 0] result-count
pattern: only run 1 returned docs, runs 2-6 all returned 0. This script
instruments three sequential searches against the live Broward portal,
capturing form state + cookies + HTML + screenshots before/after each
submit, so we can identify which adapter-side assumption breaks on run 2+.

Authorized read-only probe — no submits other than the three diagnostic
searches. Output goes under docs/FL/source/broward_state_bug_repro/.

Run:
    cd <repo>
    source venv/bin/activate
    python tools/diagnostics/broward_state_repro.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "docs" / "FL" / "source" / "broward_state_bug_repro"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_URL = "https://officialrecords.broward.org/AcclaimWeb/search/SearchTypeName"

# Three sequential probes: same name twice (state-reset baseline), then a
# different name.
PROBES = [
    {"label": "search1_SIMMONS_SHANTELL", "last": "SIMMONS", "first": "SHANTELL"},
    {"label": "search2_SIMMONS_SHANTELL_repeat", "last": "SIMMONS", "first": "SHANTELL"},
    {"label": "search3_SIMMONS_DESTON", "last": "SIMMONS", "first": "DESTON"},
]


def log(msg: str) -> None:
    print(f"[broward_repro] {msg}", flush=True)


def save_json(name: str, payload: Any) -> None:
    p = OUT_DIR / name
    with p.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    log(f"  wrote {p.name}")


def save_text(name: str, text: str) -> None:
    p = OUT_DIR / name
    p.write_text(text, encoding="utf-8", errors="replace")
    log(f"  wrote {p.name} ({len(text)} chars)")


def safe_value(driver, selector: str) -> Optional[str]:
    """Read .value of an input via JS (works even if Kendo masks the DOM)."""
    try:
        return driver.execute_script(
            "var el = document.querySelector(arguments[0]); "
            "return el ? (el.value !== undefined ? el.value : el.innerText) : null;",
            selector,
        )
    except Exception as exc:
        return f"<read-error: {exc}>"


def grab_state(driver, stage: str) -> Dict[str, Any]:
    """Capture every state input that could leak between searches."""
    try:
        url = driver.current_url
    except Exception:
        url = None
    try:
        title = driver.title
    except Exception:
        title = None

    state: Dict[str, Any] = {
        "stage": stage,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "current_url": url,
        "document_title": title,
    }

    # Form fields commonly used by Broward AcclaimWeb (PascalCase per MVC).
    selectors = {
        "SearchOnName": "#SearchOnName",
        "LastName": "#LastName",
        "FirstName": "#FirstName",
        "Name": "#Name",
        "PartyType": "#PartyType",
        "RecordDateFrom": "#RecordDateFrom",
        "RecordDateTo": "#RecordDateTo",
        "DateFiledFrom": "#DateFiledFrom",
        "DateFiledTo": "#DateFiledTo",
    }
    state["form_values"] = {
        key: safe_value(driver, sel) for key, sel in selectors.items()
    }

    # Anti-forgery token
    try:
        token = driver.execute_script(
            "var el = document.querySelector('input[name=\"__RequestVerificationToken\"]'); "
            "return el ? el.value : null;"
        )
    except Exception as exc:
        token = f"<error: {exc}>"
    state["request_verification_token"] = (
        (token[:40] + "...") if isinstance(token, str) and len(token) > 40 else token
    )
    state["request_verification_token_len"] = (
        len(token) if isinstance(token, str) else None
    )

    # Cookies
    try:
        cookies = driver.get_cookies()
        state["cookies"] = [
            {
                "name": c.get("name"),
                "domain": c.get("domain"),
                "path": c.get("path"),
                "value_preview": (c.get("value") or "")[:24] + "...",
                "value_len": len(c.get("value") or ""),
                "expiry": c.get("expiry"),
            }
            for c in cookies
        ]
        state["cookie_names"] = sorted(c.get("name") for c in cookies)
    except Exception as exc:
        state["cookies_error"] = str(exc)

    # Result row count (k-master-row / k-alt) — works for both pre and post.
    try:
        row_count = driver.execute_script(
            "return document.querySelectorAll('tr.k-master-row, tr.k-alt').length;"
        )
    except Exception:
        row_count = None
    state["kendo_row_count"] = row_count

    # Empty-results marker
    try:
        no_results_present = driver.execute_script(
            "var nodes = document.querySelectorAll('body *'); "
            "for (var i=0;i<nodes.length;i++){ "
            "  var t = (nodes[i].innerText||'').toLowerCase(); "
            "  if (t && t.length < 200 && (t.indexOf('no records') !== -1 || t.indexOf('no results') !== -1)) return true; "
            "} return false;"
        )
    except Exception:
        no_results_present = None
    state["no_results_marker_present"] = no_results_present

    return state


def snapshot(driver, stage: str) -> None:
    state = grab_state(driver, stage)
    save_json(f"{stage}_state.json", state)
    try:
        html = driver.page_source
    except Exception as exc:
        html = f"<page_source error: {exc}>"
    save_text(f"{stage}_page.html", html)
    try:
        png = OUT_DIR / f"{stage}_screenshot.png"
        driver.save_screenshot(str(png))
        log(f"  wrote {png.name}")
    except Exception as exc:
        log(f"  screenshot failed: {exc}")


def click_by_xpath(driver, xpath: str, timeout: int = 15) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        return True
    except Exception as exc:
        log(f"  click_by_xpath failed for {xpath!r}: {exc}")
        return False


def fill_field(driver, css_selector: str, value: str) -> bool:
    """Try to find/clear/send_keys with stale retry. Matches adapter behavior."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import (
        StaleElementReferenceException,
        TimeoutException,
        NoSuchElementException,
    )

    for attempt in range(3):
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            el.clear()
            el.send_keys(value)
            return True
        except (StaleElementReferenceException, NoSuchElementException):
            time.sleep(0.5)
            continue
        except TimeoutException:
            return False
    return False


def accept_disclaimer(driver) -> None:
    """Click the I-Agree / Accept link if disclaimer page is shown."""
    from selenium.webdriver.common.by import By

    xpaths = [
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'accept')]",
        "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'agree')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'accept')]",
        "//input[@type='submit' and (contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') or contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'agree'))]",
    ]
    for xp in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xp)
            if els:
                try:
                    els[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", els[0])
                log(f"  clicked disclaimer via {xp[:60]}...")
                time.sleep(3)
                return
        except Exception:
            continue
    log("  no disclaimer button found (probably already accepted)")


def submit_and_wait(driver, stage_label: str) -> None:
    """Click the Search button and wait for results/no-results to render."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    candidates = [
        "//button[@id='btnSearch']",
        "//button[contains(@class,'btnSearch')]",
        "//input[@type='submit' and (contains(@value,'Search') or contains(@id,'Search'))]",
        "//button[contains(text(),'Search')]",
        "//a[contains(@class,'btnSearch')]",
    ]
    clicked = False
    for xp in candidates:
        try:
            els = driver.find_elements(By.XPATH, xp)
            if els:
                try:
                    els[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", els[0])
                clicked = True
                log(f"  submitted via {xp[:60]}...")
                break
        except Exception:
            continue
    if not clicked:
        log("  WARN: could not find submit button")

    # Wait for either result rows or no-results banner
    try:
        WebDriverWait(driver, 20).until(
            lambda d: (
                d.execute_script(
                    "return document.querySelectorAll('tr.k-master-row, tr.k-alt').length > 0 "
                    "|| (function(){ var ns=document.querySelectorAll('body *'); for (var i=0;i<ns.length;i++){ "
                    "var t=(ns[i].innerText||'').toLowerCase(); if (t && t.length<200 && (t.indexOf('no records')!==-1 || t.indexOf('no results')!==-1)) return true;} return false;})();"
                )
            )
        )
    except Exception:
        log("  WARN: results-or-no-results wait timed out")
    time.sleep(2.0)  # let Kendo finish dataBound


def return_to_search(driver) -> None:
    """Mirror the adapter's return_to_search behaviour (back link)."""
    from selenium.webdriver.common.by import By

    xpaths = [
        "//a[contains(text(),'New Search')]",
        "//a[contains(text(),'Back')]",
        "//a[contains(@href,'SearchTypeName')]",
    ]
    for xp in xpaths:
        try:
            els = driver.find_elements(By.XPATH, xp)
            if els:
                try:
                    els[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", els[0])
                log(f"  clicked back via {xp[:50]}...")
                time.sleep(3)
                return
        except Exception:
            continue
    log("  no back-to-search link found; re-navigating to search URL")
    driver.get(SEARCH_URL)
    time.sleep(3)


def main() -> int:
    try:
        import undetected_chromedriver as uc
    except ImportError:
        log("FATAL: undetected_chromedriver not installed")
        return 2

    profile_dir = os.path.expanduser("~/.titlepro/chrome_profile_acclaim")
    os.makedirs(profile_dir, exist_ok=True)

    uc_options = uc.ChromeOptions()
    uc_options.add_argument("--window-size=1600,1100")
    uc_options.add_argument("--disable-blink-features=AutomationControlled")
    uc_options.add_argument(f"--user-data-dir={profile_dir}")

    log("Launching undetected-chromedriver (pinned to Chrome 148)...")
    driver = None
    try:
        driver = uc.Chrome(options=uc_options, version_main=148, use_subprocess=True)
    except Exception as exc:
        log(f"uc.Chrome failed once: {exc}; retrying without profile")
        try:
            driver = uc.Chrome(
                options=uc.ChromeOptions(), version_main=148, use_subprocess=True
            )
        except Exception as exc2:
            log(f"FATAL: uc.Chrome could not start: {exc2}")
            return 3

    driver.implicitly_wait(3)

    try:
        log(f"GET {SEARCH_URL}")
        driver.get(SEARCH_URL)
        time.sleep(4)

        accept_disclaimer(driver)
        time.sleep(2)

        # If we got bounced to disclaimer or home, navigate directly to name search.
        if "SearchTypeName" not in (driver.current_url or ""):
            log(f"  not on name-search yet (url={driver.current_url}); re-navigating")
            driver.get(SEARCH_URL)
            time.sleep(4)

        for i, probe in enumerate(PROBES, start=1):
            stage_pre = f"{i*2-1:02d}_pre_{probe['label']}"
            stage_post = f"{i*2:02d}_post_{probe['label']}"
            log(f"--- probe {i}: {probe['label']} ---")

            # 1) capture current state BEFORE doing anything (this is what
            # leaks between runs in the adapter — we want to see the raw state
            # at this moment).
            snapshot(driver, stage_pre + "_initial")

            # 2) Try filling the LastName field. Broward AcclaimWeb sometimes
            # exposes a single SearchOnName input — try that first, fall back
            # to LastName/FirstName.
            filled_combined = fill_field(driver, "#SearchOnName", f"{probe['last']}, {probe['first']}")
            if not filled_combined:
                fill_field(driver, "#LastName", probe["last"])
                fill_field(driver, "#FirstName", probe["first"])

            time.sleep(0.5)

            # 3) capture state with fields filled (this is what the form actually
            # sends — and shows whether prior values leaked through).
            snapshot(driver, stage_pre + "_filled")

            # 4) Submit
            submit_and_wait(driver, probe["label"])

            # 5) Capture post-submit state (rows, url, cookies rotated?)
            snapshot(driver, stage_post)

            # 6) Mimic adapter: go back to search form before next iteration
            if i < len(PROBES):
                return_to_search(driver)
                time.sleep(2)

        log("All probes complete.")
        return 0

    except Exception as exc:
        log(f"EXCEPTION: {exc}")
        traceback.print_exc()
        save_text("FATAL_traceback.txt", traceback.format_exc())
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
