"""
Debug search script to capture screenshots and HTML of Orange County Recorder results.
"""

import time
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False


def run_debug_search(name: str = "Kwa Danny", start_date: str = "01/01/2000"):
    """Run a search and capture debug info."""

    from titlepro import DOWNLOAD_DIR
    output_dir = str(DOWNLOAD_DIR / "Kwa_Danny")
    os.makedirs(output_dir, exist_ok=True)

    # Setup Chrome
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    try:
        if USE_WEBDRIVER_MANAGER:
            driver_path = ChromeDriverManager().install()
            if not driver_path.endswith('chromedriver'):
                driver_dir = os.path.dirname(driver_path)
                driver_path = os.path.join(driver_dir, 'chromedriver')
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"WebDriver manager failed: {e}")
        driver = webdriver.Chrome(options=options)

    driver.implicitly_wait(5)
    wait = WebDriverWait(driver, 15)

    try:
        # Navigate to site
        print("Navigating to Orange County Recorder...")
        driver.get("https://cr.occlerkrecorder.gov/RecorderWorksInternet/")
        time.sleep(2)

        # Click Name tab
        name_tab = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Name')]")))
        name_tab.click()
        time.sleep(1)
        print("Clicked Name tab")

        # Set party type to Grantee (since we found 9 results as Grantee)
        dropdown = wait.until(EC.presence_of_element_located((By.ID, "MainContent_MainMenu1_SearchByName1_partytype")))
        select = Select(dropdown)
        select.select_by_visible_text("Grantee")
        time.sleep(0.5)
        print("Set party type: Grantee")

        # Enter name
        name_field = wait.until(EC.presence_of_element_located((By.ID, "MainContent_MainMenu1_SearchByName1_nameForSearch")))
        name_field.clear()
        name_field.send_keys(name)
        print(f"Entered name: {name}")

        # Set dates
        inputs = driver.find_elements(By.XPATH, "//input[@type='text']")
        date_inputs = []
        for inp in inputs:
            inp_id = (inp.get_attribute('id') or '').lower()
            inp_name = (inp.get_attribute('name') or '').lower()
            if 'date' in inp_id or 'date' in inp_name:
                date_inputs.append(inp)

        if len(date_inputs) >= 2:
            driver.execute_script("arguments[0].value = arguments[1];", date_inputs[0], start_date)
            end_date = datetime.now().strftime("%m/%d/%Y")
            driver.execute_script("arguments[0].value = arguments[1];", date_inputs[1], end_date)
            print(f"Set date range: {start_date} to {end_date}")

        # Click search
        search_button = wait.until(EC.element_to_be_clickable((By.ID, "MainContent_MainMenu1_SearchByName1_btnSearch")))
        search_button.click()
        print("Clicked search button")

        # Wait for results
        time.sleep(5)

        # Take screenshot of results
        screenshot_path = os.path.join(output_dir, "debug_search_results.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved: {screenshot_path}")

        # Save HTML
        html_path = os.path.join(output_dir, "debug_search_results.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"HTML saved: {html_path}")

        # Try to extract table structure info
        debug_script = """
        var debug = {
            tables: [],
            masterTable: null,
            allText: ''
        };

        // Find all tables and their structure
        var tables = document.querySelectorAll('table');
        for (var i = 0; i < tables.length; i++) {
            var t = tables[i];
            var tableInfo = {
                index: i,
                id: t.id || '',
                className: t.className || '',
                rowCount: t.querySelectorAll('tr').length,
                firstRowCells: []
            };

            // Get first data row cells
            var rows = t.querySelectorAll('tr');
            for (var r = 0; r < rows.length && r < 3; r++) {
                var cells = rows[r].querySelectorAll('td, th');
                var rowCells = [];
                for (var c = 0; c < cells.length; c++) {
                    rowCells.push({
                        tag: cells[c].tagName,
                        text: cells[c].innerText.substring(0, 50).trim(),
                        className: cells[c].className || ''
                    });
                }
                if (rowCells.length > 0) {
                    tableInfo.firstRowCells.push(rowCells);
                }
            }

            if (tableInfo.rowCount > 0) {
                debug.tables.push(tableInfo);
            }
        }

        // Check for RadGrid specifically
        var masterTable = document.querySelector('table.rgMasterTable');
        if (masterTable) {
            debug.masterTable = {
                found: true,
                id: masterTable.id,
                className: masterTable.className,
                rowCount: masterTable.querySelectorAll('tr').length,
                dataRowCount: masterTable.querySelectorAll('tr.rgRow, tr.rgAltRow').length
            };
        }

        // Get visible text sample
        debug.allText = document.body.innerText.substring(0, 2000);

        return debug;
        """

        debug_info = driver.execute_script(debug_script)

        # Save debug info
        import json
        debug_path = os.path.join(output_dir, "debug_table_structure.json")
        with open(debug_path, 'w') as f:
            json.dump(debug_info, f, indent=2)
        print(f"Debug info saved: {debug_path}")

        # Print summary
        print("\n=== DEBUG SUMMARY ===")
        print(f"Tables found: {len(debug_info.get('tables', []))}")
        if debug_info.get('masterTable'):
            print(f"Master table: {debug_info['masterTable']}")
        else:
            print("Master table (rgMasterTable): NOT FOUND")

        for t in debug_info.get('tables', [])[:5]:
            print(f"\nTable {t['index']}: class='{t['className']}', rows={t['rowCount']}")
            if t['firstRowCells']:
                for ridx, row in enumerate(t['firstRowCells'][:2]):
                    cells_text = [c['text'][:20] for c in row[:7]]
                    print(f"  Row {ridx}: {cells_text}")

        print("\n=== PAGE TEXT SAMPLE ===")
        print(debug_info.get('allText', '')[:1000])

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        # Still try to save screenshot on error
        try:
            driver.save_screenshot(os.path.join(output_dir, "debug_error.png"))
        except:
            pass
    finally:
        driver.quit()
        print("\nBrowser closed.")


if __name__ == "__main__":
    run_debug_search()
