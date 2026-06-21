"""
Base class for CAPTCHA solvers.

Provides abstract interface for different CAPTCHA solving services.
"""

from abc import ABC, abstractmethod
from typing import Optional


class CaptchaSolverBase(ABC):
    """
    Abstract base class for CAPTCHA solving services.

    Implementations should handle:
    - API authentication
    - Request submission
    - Solution polling
    - Error handling
    """

    def __init__(self, api_key: str, timeout: int = 120):
        """
        Initialize the CAPTCHA solver.

        Args:
            api_key: API key for the solving service
            timeout: Maximum time to wait for solution (seconds)
        """
        self.api_key = api_key
        self.timeout = timeout

    @abstractmethod
    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Solve a reCAPTCHA v2 challenge.

        Args:
            site_key: The reCAPTCHA site key (data-sitekey attribute)
            page_url: The URL of the page with the CAPTCHA

        Returns:
            The g-recaptcha-response token, or None if solving failed
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def solve_image_captcha(self, image_base64: str) -> Optional[str]:
        """
        Solve an image-based CAPTCHA.

        Args:
            image_base64: Base64-encoded image data

        Returns:
            The text solution, or None if solving failed
        """
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """
        Get the current account balance.

        Returns:
            Account balance in USD
        """
        pass

    @abstractmethod
    def report_incorrect(self, task_id: str) -> bool:
        """
        Report an incorrect solution for refund.

        Args:
            task_id: The task ID of the incorrect solution

        Returns:
            True if report was successful
        """
        pass
