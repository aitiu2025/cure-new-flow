# TitlePro247 Document Retrieval Selenium Automation Guide

## 1. Overview

This document provides a comprehensive implementation guide for creating a Selenium-based automation script to retrieve and download documents from the TitlePro247 website. The script will be designed to be robust, configurable, and easy to use from the command line.

### Key Features:
- **Secure Credential Management:** Uses environment variables to handle login credentials securely, avoiding hardcoded values.
- **Command-Line Interface:** Accepts the Document Number and Year as command-line arguments for flexible and automated execution.
- **Robust Navigation & Interaction:** Implements explicit waits and dynamic element handling to ensure reliability even with variations in page load times.
- **Automated Download:** Handles the entire workflow from login to document download, saving the file to a specified local directory.

## 2. Prerequisites

Before implementing the script, ensure the following prerequisites are met:

- **Python 3.x:** The script will be written in Python.
- **Selenium Library:** The core library for browser automation. Install using `pip install selenium`.
- **WebDriver:** A specific browser driver is required for Selenium to control a web browser. We recommend using `webdriver-manager` to automatically handle the driver installation and management. Install with `pip install webdriver-manager`.
- **Web Browser:** A compatible web browser such as Google Chrome or Mozilla Firefox.

## 3. Configuration

To maintain security and avoid exposing sensitive information, the script will use environment variables to store login credentials.

### Environment Variables:
- `TITLEPRO_USERNAME`: Your TitlePro247 username.
- `TITLEPRO_PASSWORD`: Your TitlePro247 password.

These variables must be set in the environment where the script is executed. For example, in a Linux/macOS shell:

```bash
export TITLEPRO_USERNAME="your_username"
export TITLEPRO_PASSWORD="your_password"
```

## 4. Automation Strategy

The automation script will follow a logical sequence of steps that mimic the manual user workflow. This ensures a predictable and reliable process.

### High-Level Workflow:

1.  **Initialization:**
    -   Initialize the Selenium WebDriver.
    -   Read the Document Number and Year from command-line arguments.
    -   Read the `TITLEPRO_USERNAME` and `TITLEPRO_PASSWORD` from environment variables.

2.  **Login:**
    -   Navigate to the TitlePro247 login page (`https://www.titlepro247.com/`).
    -   Enter the username and password into the respective fields.
    -   Click the "LOGIN" button.

3.  **Navigate to Document Search:**
    -   After successful login, navigate to the Document Retrieval page by clicking the "Documents" link in the main navigation menu.

4.  **Perform Document Search:**
    -   On the Document Retrieval page, locate the input fields for "Year" and "Document #".
    -   Enter the values provided via command-line arguments.
    -   Click the "GET NOW" button to initiate the search.

5.  **Handle Pop-up and View Order:**
    -   After clicking "GET NOW," a pop-up dialog may appear indicating a recently ordered document.
    -   The script will click the "CONTINUE WITH ORDER" button to proceed.
    -   Next, it will click the "View Order" link to open the document viewer.

6.  **Download Document:**
    -   Once the document is open in the viewer, the script will trigger the download.
    -   The downloaded file will be saved to a pre-configured local directory.

7.  **Termination:**
    -   Close the WebDriver session gracefully.

## 5. Implementation Details

This section provides detailed guidance and code structure for implementing the automation script.

### Core Components:

- **Argument Parsing:** Use Python's `argparse` library to handle command-line arguments for the Document Number and Year.
- **WebDriver Management:** Use `webdriver-manager` to simplify the setup and management of the browser driver.
- **Explicit Waits:** Employ `WebDriverWait` to pause the script until specific conditions are met (e.g., an element is clickable or visible). This is crucial for handling dynamic web pages and avoiding race conditions.

### Code Structure (Python):

```python
import os
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- Main Automation Logic ---
def automate_titlepro_download(doc_num, year):
    # 1. Initialize WebDriver
    driver = webdriver.Chrome(ChromeDriverManager().install())
    wait = WebDriverWait(driver, 20) # 20-second timeout

    try:
        # 2. Login
        driver.get("https://www.titlepro247.com/")
        username = os.environ.get("TITLEPRO_USERNAME")
        password = os.environ.get("TITLEPRO_PASSWORD")

        wait.until(EC.presence_of_element_located((By.ID, "UserName"))).send_keys(username)
        driver.find_element(By.ID, "Password").send_keys(password)
        driver.find_element(By.ID, "login-submit").click()

        # 3. Navigate to Document Search
        wait.until(EC.element_to_be_clickable((By.ID, "documents"))).click()

        # 4. Perform Document Search
        wait.until(EC.presence_of_element_located((By.ID, "year"))).send_keys(year)
        driver.find_element(By.ID, "documentno").send_keys(doc_num)
        driver.find_element(By.ID, "btn-buyNow").click()

        # 5. Handle Pop-up and View Order
        # Wait for the "Continue with Order" button and click it
        wait.until(EC.element_to_be_clickable((By.ID, "modal-dup-documents_btn_Continue"))).click()

        # The page reloads, so we need to re-locate the "View Order" link
        # This part might require careful handling of dynamic elements
        # It is recommended to click on the history tab and then find the order
        wait.until(EC.element_to_be_clickable((By.ID, "my-orders"))).click()
        
        # Find the specific order and click "View Document"
        # This is a simplified example; a more robust solution would be to find the row with the order number
        view_doc_link = wait.until(EC.element_to_be_clickable((By.XPATH, f"//td[contains(text(), '{doc_num}')]/following-sibling::td/a[contains(text(), 'View Document')]")))
        view_doc_link.click()

        # 6. Download Document
        # The download should be initiated by the click above. 
        # You may need to configure Chrome options to set a default download directory.

        print(f"Successfully initiated download for Document # {doc_num}")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        # 7. Termination
        driver.quit()

# --- Script Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate document download from TitlePro247.")
    parser.add_argument("doc_num", help="The Document Number to search for.")
    parser.add_argument("year", help="The Year (YYYY) to search for.")
    args = parser.parse_args()

    automate_titlepro_download(args.doc_num, args.year)

```

## 6. Error Handling

A robust automation script must anticipate and handle potential errors gracefully.

- **Invalid Credentials:** The script should check for an "Invalid login attempt" message after submitting the login form.
- **Document Not Found:** If the document search yields no results, the script should report this and exit cleanly.
- **Element Not Found:** Use explicit waits (`WebDriverWait`) to prevent `NoSuchElementException`. If an element is still not found after the timeout, the script should log the error and terminate.
- **UI Changes:** The script relies on element IDs and structure. If the website's UI changes, the script may break. Regular maintenance and testing are recommended.

## 7. Usage Instructions

1.  **Set Environment Variables:**
    ```bash
    export TITLEPRO_USERNAME="your_username"
    export TITLEPRO_PASSWORD="your_password"
    ```

2.  **Run the Script:**
    Execute the script from the command line, providing the Document Number and Year as arguments.
    ```bash
    python titlepro_downloader.py 2025000053475 2025
    ```

## 8. Disclaimer

This automation script is provided as a proof of concept and is intended for personal use. The script's functionality is highly dependent on the structure and design of the TitlePro247 website. Any changes to the website may cause the script to fail. The user of this script is responsible for ensuring compliance with the TitlePro247 terms of service.
