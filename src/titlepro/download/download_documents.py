#!/usr/bin/env python3
import os
import hashlib
import time
import json
import logging
from typing import List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# CONFIGURATION (edit as appropriate)
from titlepro import DOWNLOAD_DIR

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'titlepro247_config.json')
OUTPUT_DIR = str(DOWNLOAD_DIR)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return json.load(f)

def ensure_output_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def hash_file(file_path: str) -> str:
    with open(file_path, 'rb') as f:
        hasher = hashlib.md5()
        while chunk := f.read(4096):
            hasher.update(chunk)
    return hasher.hexdigest()


def deduplicate_files(dir_path: str):
    """
    Remove files with identical content (by hash) but different names, keeping only the first encountered.
    """
    seen_hashes = {}
    for filename in os.listdir(dir_path):
        full_path = os.path.join(dir_path, filename)
        if not os.path.isfile(full_path):
            continue
        file_hash = hash_file(full_path)
        if file_hash in seen_hashes:
            logging.info(f"Duplicate found: {filename} == {seen_hashes[file_hash]}, removing {filename}")
            os.remove(full_path)
        else:
            seen_hashes[file_hash] = filename
    logging.info("Deduplication complete.")


def get_downloaded_files(dir_path: str) -> List[str]:
    return [os.path.join(dir_path, f) for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]


def wait_for_downloads(dir_path: str, before_files: List[str], num_new:int, timeout=60):
    """
    Wait until number of new files appear that were not in before_files.
    """
    start = time.time()
    while time.time() - start < timeout:
        after_files = set(get_downloaded_files(dir_path))
        new_files = after_files - set(before_files)
        # Check not any .crdownload etc
        if len(new_files) >= num_new and all(not f.endswith('.crdownload') for f in new_files):
            logging.info(f"All downloads complete, new files: {new_files}")
            return list(new_files)
        time.sleep(1)
    raise TimeoutError("Timeout while waiting for documents to download!")


def titlepro247_login(driver, config):
    driver.get("https://www.titlepro247.com/")
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "txtUserName"))
    )
    driver.find_element(By.ID, "txtUserName").send_keys(config['username'])
    driver.find_element(By.ID, "txtPassword").send_keys(config['password'])
    driver.find_element(By.ID, "txtPassword").send_keys(Keys.RETURN)
    WebDriverWait(driver, 30).until_not(
        EC.presence_of_element_located((By.ID, "txtUserName"))
    )
    logging.info("Logged in to TitlePro247.")


def search_and_download(driver, config, output_dir):
    """
    For each property/subject in config['search_subjects'], perform search and download all relevant documents.
    """
    subjects = config['search_subjects']
    for idx, subj in enumerate(subjects):
        logging.info(f"Processing subject {idx+1}/{len(subjects)}: {subj}")
        # Implement property search (by address/APN/owner, as provided)
        driver.get("https://www.titlepro247.com/search")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "searchTxt"))
        )
        search_text = subj.get("address") or subj.get("apn") or subj.get("owner")
        driver.find_element(By.ID, "searchTxt").clear()
        driver.find_element(By.ID, "searchTxt").send_keys(search_text)
        driver.find_element(By.ID, "searchTxt").send_keys(Keys.RETURN)

        # Wait for search results
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div#searchResultTable tbody tr"))
        )
        # Select first search result (or customize selection as needed)
        rows = driver.find_elements(By.CSS_SELECTOR, "div#searchResultTable tbody tr")
        if not rows:
            logging.warning(f"No search results for {search_text}")
            continue
        rows[0].click()
        time.sleep(2)  # Wait for modal navigation/load

        # Access and download found documents
        doc_links = driver.find_elements(By.CSS_SELECTOR, "button.viewImage, a.documentDownload")
        logging.info(f"Found {len(doc_links)} documents to download.")
        before_download = get_downloaded_files(output_dir)
        for l in doc_links:
            l.click()
            time.sleep(1.5)
        # Wait for downloads
        try:
            wait_for_downloads(output_dir, before_download, len(doc_links), timeout=60)
        except TimeoutError:
            logging.error(f"Timeout downloading docs for {search_text}")
        time.sleep(2)
    logging.info("All subjects processed.")


def main():
    ensure_output_dir(OUTPUT_DIR)
    config = load_config(CONFIG_PATH)

    chrome_options = ChromeOptions()
    prefs = {
        "download.default_directory": OUTPUT_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--no-sandbox')
    
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        titlepro247_login(driver, config)
        search_and_download(driver, config, OUTPUT_DIR)
    finally:
        driver.quit()

    deduplicate_files(OUTPUT_DIR)
    logging.info(f"All documents downloaded and deduplicated in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
