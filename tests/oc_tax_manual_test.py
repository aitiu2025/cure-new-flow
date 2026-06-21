#!/usr/bin/env python3
"""
Manual test: Opens OC Tax site in visible browser.
Solve the captcha manually, then the script extracts all result page data.
Usage: python3 tests/oc_tax_manual_test.py
"""
import json
import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    page.goto("https://taxbill.octreasurer.gov/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(3000)

    # Type address
    combobox = page.locator('[role="combobox"]')
    combobox.click()
    combobox.fill("1234 N Main")
    page.wait_for_timeout(3000)

    # Select first result
    options = page.locator('[role="option"]')
    if options.count() > 0:
        print(f"Selecting: {options.first.inner_text()}")
        options.first.click()
        page.wait_for_timeout(1000)

    # Click Find
    page.locator("button.find-btn.btn.btn-primary").first.click()
    page.wait_for_timeout(2000)

    print("\n" + "=" * 60)
    print("PLEASE SOLVE THE CAPTCHA IN THE BROWSER WINDOW")
    print("Waiting up to 60 seconds...")
    print("=" * 60)

    # Wait for captcha to be solved (URL changes or modal disappears)
    start = time.time()
    while time.time() - start < 60:
        body = page.inner_text("body")
        if "VERIFY THAT YOU ARE HUMAN" not in body:
            break
        time.sleep(2)

    if "VERIFY THAT YOU ARE HUMAN" in page.inner_text("body"):
        print("Captcha was not solved in time.")
        browser.close()
        exit(1)

    print("\nCaptcha solved! Waiting for results...")
    page.wait_for_timeout(5000)

    current_url = page.url
    print(f"Result URL: {current_url}")

    body_text = page.inner_text("body")
    print(f"\n=== RESULT PAGE TEXT (first 6000 chars) ===")
    print(body_text[:6000])

    # Extract tables
    tables = page.evaluate("""() => {
        const tables = document.querySelectorAll('table');
        return Array.from(tables).map((t, idx) => ({
            index: idx,
            cls: (t.className || '').substring(0, 60),
            rows: Array.from(t.rows).map(r =>
                Array.from(r.cells).map(c => c.textContent.trim().substring(0, 120))
            ),
        }));
    }""")
    print("\n=== TABLES ===")
    for t in tables:
        print(f"\nTable {t['index']} (class={t['cls']}):")
        for row in t["rows"]:
            print(f"  {' | '.join(row)}")

    # Extract dt/dd pairs
    details = page.evaluate("""() => {
        const dts = document.querySelectorAll('dt');
        return Array.from(dts).map(dt => ({
            label: dt.textContent.trim().substring(0, 60),
            value: dt.nextElementSibling ? dt.nextElementSibling.textContent.trim().substring(0, 100) : '',
        }));
    }""")
    print("\n=== DETAIL PAIRS ===")
    for d in details:
        print(f"  {d['label']}: {d['value']}")

    # Sections
    sections = page.evaluate("""() => {
        const els = document.querySelectorAll('h2, h3, h4, .card-header, .card-title, [class*="title"], [class*="header"]');
        return Array.from(els).slice(0, 30).map(e => ({
            tag: e.tagName,
            cls: (e.className || '').substring(0, 60),
            text: e.textContent.trim().substring(0, 150),
        }));
    }""")
    print("\n=== SECTION HEADERS ===")
    for s in sections:
        print(f"  [{s['tag']} .{s['cls']}] {s['text']}")

    # All card-body content
    cards = page.evaluate("""() => {
        const els = document.querySelectorAll('.card-body, .panel-body, [class*="detail"]');
        return Array.from(els).slice(0, 10).map(e => ({
            cls: (e.className || '').substring(0, 60),
            text: e.textContent.trim().substring(0, 400),
        }));
    }""")
    print("\n=== CARD BODY CONTENT ===")
    for c in cards:
        print(f"  [{c['cls']}] {c['text'][:300]}")

    page.screenshot(path="tests/screenshots/oc_tax_result_manual.png", full_page=True)
    print("\nScreenshot saved to tests/screenshots/oc_tax_result_manual.png")

    input("\nPress Enter to close browser...")
    browser.close()
