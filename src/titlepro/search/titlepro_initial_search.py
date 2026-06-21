import os
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

INPUT_PATH = os.path.join(os.path.dirname(__file__), 'input_names.json')
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'initial_search_results.json')
TITLEPRO_URL = 'https://www.titlepro247.com/'  # Adjust if different
LOGIN_URL = f'{TITLEPRO_URL}Account/Login'   # Adjust if different

# Credentials must be set as env vars (for security): TITLEPRO_USER, TITLEPRO_PASS
TP_USER = os.environ.get('TITLEPRO_USER')
TP_PASS = os.environ.get('TITLEPRO_PASS')

if not TP_USER or not TP_PASS:
    raise ValueError('Please set TITLEPRO_USER and TITLEPRO_PASS environment variables.')

def read_names_from_json(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
    # Expecting {"GRANTOR": [...], "GRANTEE": [...], "ALL": [...]} as lists
    names = set()
    if 'ALL' in data:
        for n in data['ALL']:
            names.add(n)
    for k in ('GRANTOR', 'GRANTEE'):
        ns = data.get(k, [])
        for n in ns:
            names.add(n)
    return list(names)

def login_titlepro(driver):
    driver.get(LOGIN_URL)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, 'Username')))
    driver.find_element(By.ID, 'Username').send_keys(TP_USER)
    driver.find_element(By.ID, 'Password').send_keys(TP_PASS)
    time.sleep(0.5)
    driver.find_element(By.XPATH, "//button[contains(., 'Login') or contains(., 'Sign In')]").click()
    # Wait for login to complete
    WebDriverWait(driver, 25).until_not(
        EC.presence_of_element_located((By.ID, 'Username'))
    )
    # Or wait for some dashboard element
    time.sleep(2)

def search_name(driver, name):
    '''Do an initial name search for a given name. Returns a list of relevant document numbers.'''
    # Navigate to search page (adjust selector to the search UI)
    search_url = f'{TITLEPRO_URL}TitleSearch'  # Adjust if needed
    driver.get(search_url)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.NAME, 'partyName')))

    name_box = driver.find_element(By.NAME, 'partyName')
    name_box.clear()
    name_box.send_keys(name)
    # Click search button
    driver.find_element(By.XPATH, "//button[contains(., 'Search') or @type='submit']").click()

    # Wait for results
    WebDriverWait(driver, 20).until(
        EC.or_(EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'No results') or contains(text(),'no results') or contains(@class,'empty-result') or contains(@class,'no-result') or contains(text(),'No matching records') or contains(text(),'not found') or contains(text(),'No records')]") ),
              EC.presence_of_element_located((By.XPATH, "//table|//tbody|//tr|//div[contains(@class,'results')]") )
        )
    )
    time.sleep(1)
    # Get document numbers from table/div
    doc_numbers = set()
    # Attempt to get table rows
    try:
        rows = driver.find_elements(By.XPATH, "//table//tr")
        for row in rows[1:]:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if not cells: continue
            # Often document number is first or second column, check for digits
            for c in cells[:3]:
                txt = c.text.strip()
                if len(txt) > 2 and txt.replace('-', '').replace('/', '').isdigit():
                    doc_numbers.add(txt)
                break
    except Exception:
        pass
    # Fallback: look for document numbers in possible result divs
    if not doc_numbers:
        items = driver.find_elements(By.XPATH, "//*[contains(@class,'doc-number') or contains(text(),'Doc #') or contains(@class,'result-row')]")
        for it in items:
            t = it.text.strip()
            if 'Doc' in t and any(x.isdigit() for x in t):
                for part in t.split():
                    if part.replace('-', '').replace('/', '').isdigit() and len(part) > 2:
                        doc_numbers.add(part)
    return list(doc_numbers)

def main():
    # Use Chrome browser via Selenium (can be changed to Firefox, etc)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=options)
    try:
        login_titlepro(driver)
        names = read_names_from_json(INPUT_PATH)
        results = {}
        for nm in names:
            try:
                docs = search_name(driver, nm)
                results[nm] = docs
                print(f"Searched {nm}: {docs}")
            except Exception as e:
                results[nm] = []
                print(f"Error searching {nm}: {e}")
        with open(OUTPUT_PATH, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Done. Saved results to {OUTPUT_PATH}")
    finally:
        driver.quit()

if __name__ == '__main__':
    main()
