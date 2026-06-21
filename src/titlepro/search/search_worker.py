import time
from selenium.webdriver.common.by import By
from titlepro.search.captcha_solver import CaptchaSolver
# ... other necessary imports ...

# ... existing setup code ...
def handle_captcha(driver, captcha_type, api_key=None):
    solver = CaptchaSolver(driver, twocaptcha_api_key=api_key)
    if captcha_type == 'recaptcha_v2':
        try:
            # Attempt auto bypass
            site_key_elem = driver.find_element(By.CLASS_NAME, 'g-recaptcha')
            site_key = site_key_elem.get_attribute('data-sitekey')
            url = driver.current_url
            success = solver.auto_bypass_recaptcha(site_key, url)
            if success:
                print("reCAPTCHA solved automatically.")
                return True
            else:
                print("Auto reCAPTCHA solver failed, falling back to manual.")
        except Exception as e:
            print(f"reCAPTCHA auto detection failed: {e}")
        # Fallback to manual
        input('Please manually solve the reCAPTCHA in the browser, then press Enter to continue...')
        return False
    elif captcha_type == 'image':
        try:
            img_element = driver.find_element(By.XPATH, "//img[contains(@src, 'captcha') or contains(@id, 'captcha')]")
            input_element = driver.find_element(By.XPATH, "//input[@type='text' and (contains(@name, 'captcha') or contains(@id, 'captcha'))]")
            success = solver.auto_bypass_image_captcha(img_element, input_element)
            if success:
                print("Image CAPTCHA solved automatically.")
                return True
            else:
                print("Auto image CAPTCHA solver failed; trying manual input.")
                value = solver.fallback_manual_captcha(img_element)
                input_element.clear()
                input_element.send_keys(value)
                return False
        except Exception as e:
            print(f"Image CAPTCHA detection failed: {e}")
            input('Please manually solve the image CAPTCHA in the browser, then press Enter to continue...')
            return False
    else:
        print(f"Unknown CAPTCHA type: {captcha_type}")
        return False

# ... wherever CAPTCHAs may arise in scraping flows, insert:
# Example usage:
# handle_captcha(driver, 'recaptcha_v2', api_key='YOUR_2CAPTCHA_KEY')
# handle_captcha(driver, 'image', api_key='YOUR_2CAPTCHA_KEY')

# Existing search functions should call handle_captcha(driver, <type>, api_key) at the relevant step
