#!/usr/bin/env python3
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

# Credentials
with open('secrets.json') as f:
    secrets = json.load(f)

username = secrets.get('TITLEPRO_USERNAME', 'CURE2026')
password = secrets.get('TITLEPRO_PASSWORD', 'TitleExam2026!')

# Documents to download
docs = [
    {"number": "2016000243775", "year": "2016"},
    {"number": "2018000325101", "year": "2018"},
    {"number": "2020000219276", "year": "2020"},
]

try:
    driver = webdriver.Chrome()
    driver.get("https://www.titlepro247.com/DocumentRetrieval/")
    time.sleep(5)
    
    # Dismiss cookie banner if present
    try:
        close_cookie_button = driver.find_element(By.ID, "onetrust-pc-btn-handler")
        close_cookie_button.click()
        print("Closed cookie banner")
        time.sleep(2)
    except:
        print("No cookie banner or already closed")
    
    # Login
    username_field = driver.find_element(By.ID, "UserName")
    password_field = driver.find_element(By.ID, "Password")
    username_field.send_keys(username)
    password_field.send_keys(password)
    
    login_button = driver.find_element(By.ID, "login-submit")
    login_button.click()
    
    time.sleep(5)
    print(f"Logged in. Current URL: {driver.current_url}")
    
    for doc in docs:
        doc_num = doc["number"]
        year = doc["year"]
        print(f"\n=== Downloading Document {doc_num} ({year}) ===")
        
        try:
            # Click Documents tab
            docs_tab = driver.find_element(By.ID, "documents")
            docs_tab.click()
            time.sleep(2)
            
            # Fill in document number
            doc_field = driver.find_element(By.ID, "documentno")
            doc_field.clear()
            doc_field.send_keys(doc_num)
            
            # Fill in year
            year_field = driver.find_element(By.ID, "year")
            year_field.clear()
            year_field.send_keys(year)
            
            time.sleep(1)
            
            # Click Buy Now
            buy_button = driver.find_element(By.ID, "btn-buyNow")
            buy_button.click()
            
            time.sleep(5)
            print(f"Download initiated for {doc_num}")
            
            # Check for duplicate documents modal
            try:
                continue_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "modal-dup-documents_btn_Continue"))
                )
                continue_button.click()
                print(f"Clicked continue on duplicate modal")
                time.sleep(3)
            except:
                print(f"No duplicate modal for {doc_num}")
            
        except Exception as e:
            print(f"Error downloading {doc_num}: {e}")
    
    print("\n\n=== Download process complete ===")
    print("Check ~/Downloads for PDF files")
    time.sleep(5)
    
finally:
    driver.quit()

