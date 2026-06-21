import time
import base64
import requests
from selenium.webdriver.common.by import By

class CaptchaSolver:
    def __init__(self, driver, twocaptcha_api_key=None):
        self.driver = driver
        self.twocaptcha_api_key = twocaptcha_api_key  # For 2Captcha or similar services

    # --- reCAPTCHA v2 Solver ---
    def solve_recaptcha_v2(self, site_key, url):
        if not self.twocaptcha_api_key:
            return None
        # Submit captcha
        s = requests.Session()
        captcha_id = s.post(
            'http://2captcha.com/in.php',
            data={
                'key': self.twocaptcha_api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': url,
                'json': 1
            }
        ).json()
        if captcha_id['status'] != 1:
            return None
        captcha_id = captcha_id['request']
        # Poll for solved
        for _ in range(20):
            time.sleep(5)
            resp = s.get(
                'http://2captcha.com/res.php',
                params={
                    'key': self.twocaptcha_api_key,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
            ).json()
            if resp['status'] == 1:
                return resp['request']
        return None

    def inject_recaptcha_response(self, g_response):
        # Set value in g-recaptcha-response textarea
        script = (
            "document.getElementById('g-recaptcha-response').style.display = 'block';"
            "document.getElementById('g-recaptcha-response').value = '%s';"
            "document.getElementById('g-recaptcha-response').dispatchEvent(new Event('change'));"
        ) % g_response
        self.driver.execute_script(script)

    def auto_bypass_recaptcha(self, site_key, page_url):
        g_response = self.solve_recaptcha_v2(site_key, page_url)
        if g_response:
            self.inject_recaptcha_response(g_response)
            # Optionally click verify/submit
            return True
        return False

    # --- Image-based CAPTCHA Solver ---
    def solve_image_captcha(self, img_element):
        if not self.twocaptcha_api_key:
            return None
        # Get base64 image src from Selenium element
        img_b64 = self._get_base64_from_element(img_element)
        if not img_b64:
            return None
        s = requests.Session()
        resp = s.post(
            'http://2captcha.com/in.php',
            files={'file': base64.b64decode(img_b64)},
            data={'key': self.twocaptcha_api_key, 'json': 1}
        ).json()
        if resp['status'] != 1:
            return None
        captcha_id = resp['request']
        # Poll for solved
        for _ in range(20):
            time.sleep(5)
            resp2 = s.get(
                'http://2captcha.com/res.php',
                params={'key': self.twocaptcha_api_key, 'action': 'get', 'id': captcha_id, 'json': 1}
            ).json()
            if resp2['status'] == 1:
                return resp2['request']
        return None

    def _get_base64_from_element(self, img_element):
        # Try data URI first
        src = img_element.get_attribute('src')
        if src and src.startswith('data:image'):
            # e.g. data:image/png;base64,...
            parts = src.split(',')
            if len(parts) == 2:
                return parts[1]
        # Else: take screenshot of element
        img_b64 = self.driver.execute_script(
            "var canvas = document.createElement('canvas');"
            "var ctx = canvas.getContext('2d');"
            "var img = arguments[0];"
            "canvas.width = img.width; canvas.height = img.height;"
            "ctx.drawImage(img, 0, 0, img.width, img.height);"
            "return canvas.toDataURL('image/png').substring(22);",
            img_element,
        )
        return img_b64

    def auto_bypass_image_captcha(self, img_element, input_element):
        solution = self.solve_image_captcha(img_element)
        if solution:
            input_element.clear()
            input_element.send_keys(solution)
            return True
        return False

    # --- Manual Fallback ---
    def fallback_manual_captcha(self, img_element=None):
        print("\n---- MANUAL CAPTCHA ENTRY REQUIRED ----")
        if img_element:
            # Attempt to open image in browser
            src = img_element.get_attribute('src')
            print(f"Open this image in your browser: {src}")
        value = input('Enter CAPTCHA value as shown above: ')
        return value
