"""
reCAPTCHA Solver using 2Captcha or Anti-Captcha services.

Supports:
- reCAPTCHA v2 (checkbox and invisible)
- reCAPTCHA v3
- Image CAPTCHA (basic)
"""

import os
import time
import requests
from typing import Optional
from .solver_base import CaptchaSolverBase


class RecaptchaSolver(CaptchaSolverBase):
    """
    CAPTCHA solver using 2Captcha or Anti-Captcha API.

    Environment Variables:
        CAPTCHA_API_KEY: API key for the solving service
        CAPTCHA_SERVICE: "2captcha" (default) or "anticaptcha"
    """

    # API endpoints
    ENDPOINTS = {
        "2captcha": {
            "submit": "https://2captcha.com/in.php",
            "result": "https://2captcha.com/res.php",
            "balance": "https://2captcha.com/res.php",
        },
        "anticaptcha": {
            "submit": "https://api.anti-captcha.com/createTask",
            "result": "https://api.anti-captcha.com/getTaskResult",
            "balance": "https://api.anti-captcha.com/getBalance",
        }
    }

    def __init__(self, api_key: str = None, service: str = None, timeout: int = 120):
        """
        Initialize the reCAPTCHA solver.

        Args:
            api_key: API key (defaults to CAPTCHA_API_KEY env var)
            service: Service name - "2captcha" or "anticaptcha" (defaults to CAPTCHA_SERVICE env var)
            timeout: Maximum time to wait for solution (seconds)
        """
        api_key = api_key or os.environ.get("CAPTCHA_API_KEY", "")
        super().__init__(api_key, timeout)

        self.service = service or os.environ.get("CAPTCHA_SERVICE", "2captcha")
        if self.service not in self.ENDPOINTS:
            raise ValueError(f"Unknown service: {self.service}. Use '2captcha' or 'anticaptcha'")

        self.endpoints = self.ENDPOINTS[self.service]
        self.last_task_id = None

    def _is_configured(self) -> bool:
        """Check if solver is properly configured."""
        return bool(self.api_key)

    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve a reCAPTCHA v2 challenge.

        Args:
            site_key: The reCAPTCHA site key (data-sitekey attribute)
            page_url: The URL of the page with the CAPTCHA

        Returns:
            The g-recaptcha-response token, or None if solving failed
        """
        if not self._is_configured():
            print("  CAPTCHA solver not configured (missing API key)")
            return None

        print(f"  Submitting reCAPTCHA v2 to {self.service}...")

        try:
            if self.service == "2captcha":
                return self._solve_2captcha_v2(site_key, page_url)
            else:
                return self._solve_anticaptcha_v2(site_key, page_url)
        except Exception as e:
            print(f"  CAPTCHA solving error: {e}")
            return None

    def _solve_2captcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve using 2Captcha API."""
        # Submit task
        submit_data = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1
        }

        response = requests.post(self.endpoints["submit"], data=submit_data)
        result = response.json()

        if result.get("status") != 1:
            print(f"  2Captcha submit error: {result.get('error_text', result)}")
            return None

        task_id = result.get("request")
        self.last_task_id = task_id
        print(f"  Task submitted: {task_id}")

        # Poll for result
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            time.sleep(5)

            result_data = {
                "key": self.api_key,
                "action": "get",
                "id": task_id,
                "json": 1
            }

            response = requests.get(self.endpoints["result"], params=result_data)
            result = response.json()

            if result.get("status") == 1:
                token = result.get("request")
                print(f"  CAPTCHA solved successfully")
                return token
            elif result.get("request") == "CAPCHA_NOT_READY":
                print("  Waiting for solution...")
                continue
            else:
                print(f"  2Captcha result error: {result}")
                return None

        print("  CAPTCHA solving timed out")
        return None

    def _solve_anticaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve using Anti-Captcha API."""
        # Submit task
        submit_data = {
            "clientKey": self.api_key,
            "task": {
                "type": "RecaptchaV2TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key
            }
        }

        response = requests.post(self.endpoints["submit"], json=submit_data)
        result = response.json()

        if result.get("errorId") != 0:
            print(f"  Anti-Captcha submit error: {result.get('errorDescription', result)}")
            return None

        task_id = result.get("taskId")
        self.last_task_id = task_id
        print(f"  Task submitted: {task_id}")

        # Poll for result
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            time.sleep(5)

            result_data = {
                "clientKey": self.api_key,
                "taskId": task_id
            }

            response = requests.post(self.endpoints["result"], json=result_data)
            result = response.json()

            if result.get("status") == "ready":
                token = result.get("solution", {}).get("gRecaptchaResponse")
                print(f"  CAPTCHA solved successfully")
                return token
            elif result.get("status") == "processing":
                print("  Waiting for solution...")
                continue
            else:
                print(f"  Anti-Captcha result error: {result}")
                return None

        print("  CAPTCHA solving timed out")
        return None

    def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str = "verify") -> Optional[str]:
        """
        Solve a reCAPTCHA v3 challenge.

        Args:
            site_key: The reCAPTCHA site key
            page_url: The URL of the page with the CAPTCHA
            action: The action parameter for v3

        Returns:
            The token, or None if solving failed
        """
        if not self._is_configured():
            print("  CAPTCHA solver not configured (missing API key)")
            return None

        print(f"  Submitting reCAPTCHA v3 to {self.service}...")

        try:
            if self.service == "2captcha":
                # Submit task
                submit_data = {
                    "key": self.api_key,
                    "method": "userrecaptcha",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "version": "v3",
                    "action": action,
                    "min_score": 0.3,
                    "json": 1
                }

                response = requests.post(self.endpoints["submit"], data=submit_data)
                result = response.json()

                if result.get("status") != 1:
                    print(f"  2Captcha submit error: {result}")
                    return None

                task_id = result.get("request")
                self.last_task_id = task_id

                # Poll for result
                start_time = time.time()
                while time.time() - start_time < self.timeout:
                    time.sleep(5)

                    result_data = {
                        "key": self.api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1
                    }

                    response = requests.get(self.endpoints["result"], params=result_data)
                    result = response.json()

                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") == "CAPCHA_NOT_READY":
                        continue
                    else:
                        return None

            else:
                # Anti-Captcha v3
                submit_data = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "RecaptchaV3TaskProxyless",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                        "pageAction": action,
                        "minScore": 0.3
                    }
                }

                response = requests.post(self.endpoints["submit"], json=submit_data)
                result = response.json()

                if result.get("errorId") != 0:
                    return None

                task_id = result.get("taskId")
                self.last_task_id = task_id

                start_time = time.time()
                while time.time() - start_time < self.timeout:
                    time.sleep(5)

                    result_data = {
                        "clientKey": self.api_key,
                        "taskId": task_id
                    }

                    response = requests.post(self.endpoints["result"], json=result_data)
                    result = response.json()

                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("gRecaptchaResponse")
                    elif result.get("status") == "processing":
                        continue
                    else:
                        return None

        except Exception as e:
            print(f"  reCAPTCHA v3 solving error: {e}")
            return None

        return None

    def solve_image_captcha(self, image_base64: str) -> Optional[str]:
        """
        Solve an image-based CAPTCHA.

        Args:
            image_base64: Base64-encoded image data

        Returns:
            The text solution, or None if solving failed
        """
        if not self._is_configured():
            return None

        try:
            if self.service == "2captcha":
                submit_data = {
                    "key": self.api_key,
                    "method": "base64",
                    "body": image_base64,
                    "json": 1
                }

                response = requests.post(self.endpoints["submit"], data=submit_data)
                result = response.json()

                if result.get("status") != 1:
                    return None

                task_id = result.get("request")
                self.last_task_id = task_id

                start_time = time.time()
                while time.time() - start_time < self.timeout:
                    time.sleep(5)

                    result_data = {
                        "key": self.api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1
                    }

                    response = requests.get(self.endpoints["result"], params=result_data)
                    result = response.json()

                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") == "CAPCHA_NOT_READY":
                        continue
                    else:
                        return None

            else:
                # Anti-Captcha image
                submit_data = {
                    "clientKey": self.api_key,
                    "task": {
                        "type": "ImageToTextTask",
                        "body": image_base64
                    }
                }

                response = requests.post(self.endpoints["submit"], json=submit_data)
                result = response.json()

                if result.get("errorId") != 0:
                    return None

                task_id = result.get("taskId")
                self.last_task_id = task_id

                start_time = time.time()
                while time.time() - start_time < self.timeout:
                    time.sleep(5)

                    result_data = {
                        "clientKey": self.api_key,
                        "taskId": task_id
                    }

                    response = requests.post(self.endpoints["result"], json=result_data)
                    result = response.json()

                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("text")
                    elif result.get("status") == "processing":
                        continue
                    else:
                        return None

        except Exception as e:
            print(f"  Image CAPTCHA solving error: {e}")
            return None

        return None

    def get_balance(self) -> float:
        """Get the current account balance."""
        if not self._is_configured():
            return 0.0

        try:
            if self.service == "2captcha":
                params = {
                    "key": self.api_key,
                    "action": "getbalance",
                    "json": 1
                }
                response = requests.get(self.endpoints["balance"], params=params)
                result = response.json()
                return float(result.get("request", 0))

            else:
                data = {"clientKey": self.api_key}
                response = requests.post(self.endpoints["balance"], json=data)
                result = response.json()
                return float(result.get("balance", 0))

        except Exception as e:
            print(f"  Error getting balance: {e}")
            return 0.0

    def report_incorrect(self, task_id: str = None) -> bool:
        """Report an incorrect solution for refund."""
        task_id = task_id or self.last_task_id
        if not task_id or not self._is_configured():
            return False

        try:
            if self.service == "2captcha":
                params = {
                    "key": self.api_key,
                    "action": "reportbad",
                    "id": task_id,
                    "json": 1
                }
                response = requests.get(self.endpoints["result"], params=params)
                result = response.json()
                return result.get("status") == 1

            else:
                data = {
                    "clientKey": self.api_key,
                    "taskId": int(task_id)
                }
                response = requests.post(
                    "https://api.anti-captcha.com/reportIncorrectRecaptcha",
                    json=data
                )
                result = response.json()
                return result.get("errorId") == 0

        except Exception as e:
            print(f"  Error reporting incorrect: {e}")
            return False


def get_captcha_solver(api_key: str = None, service: str = None) -> Optional[RecaptchaSolver]:
    """
    Get a configured CAPTCHA solver instance.

    Args:
        api_key: API key (defaults to CAPTCHA_API_KEY env var)
        service: Service name (defaults to CAPTCHA_SERVICE env var)

    Returns:
        RecaptchaSolver instance if configured, None otherwise
    """
    api_key = api_key or os.environ.get("CAPTCHA_API_KEY")

    if not api_key:
        return None

    return RecaptchaSolver(api_key=api_key, service=service)
