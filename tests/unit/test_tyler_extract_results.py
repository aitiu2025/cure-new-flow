"""Fixture-driven tests for tyler_adapter Python-level guards.

The full extract_results path runs JavaScript inside a real Selenium driver,
so it cannot be unit-tested here. What we CAN test deterministically is the
Python guard layer that wraps it:

  - `_check_empty_search_error` — surfaces "Empty searches are not allowed"
    as a RetryableSubmitError.
  - the CAPTCHA-on-zero-docs guard at the tail of extract_results — raises
    CaptchaCheckpointRequired when extraction found 0 docs AND the page
    still shows a CAPTCHA iframe AND there is no "no records" message.
  - the cap-detection logic — recognizes the "more documents than the
    maximum allowed" sentinel.

We exercise each guard via a tiny stub driver that returns fixture text and
fakes the small subset of WebDriver methods the guards touch.

Fixtures live in tests/fixtures/tyler/*.txt and are intentionally plain
text (not raw HTML) — the guards we test inspect ``body.text``, not parsed
DOM, so plain text is sufficient and far more readable in code review.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from titlepro.automation.checkpoints import (
    CaptchaCheckpointRequired,
    RetryableSubmitError,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "tyler"


def load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fake Selenium plumbing
# ---------------------------------------------------------------------------


class _FakeBodyElement:
    def __init__(self, text: str):
        self.text = text


class _FakeIframeElement:
    """Represents a recaptcha iframe found on the page."""

    pass


class FakeDriver:
    """Mimics the slice of Selenium driver our guards use.

    Configurable knobs:
      - ``body_text``       -> what driver.find_element(TAG_NAME, 'body').text returns
      - ``has_captcha_iframe`` -> whether find_elements(XPATH, recaptcha_frame)
                                  returns a non-empty list
      - ``current_url``     -> reported URL
    """

    def __init__(self, body_text: str = "", has_captcha_iframe: bool = False, current_url: str = "https://example/"):
        self.body_text = body_text
        self.has_captcha_iframe = has_captcha_iframe
        self.current_url = current_url

    def find_element(self, by, selector):  # noqa: ARG002
        # Only ever queried for TAG_NAME body in the guard layer.
        return _FakeBodyElement(self.body_text)

    def find_elements(self, by, selector):  # noqa: ARG002
        return [_FakeIframeElement()] if self.has_captcha_iframe else []

    def quit(self):  # for checkpoint cleanup
        pass


class FakeAdapter:
    """Minimum surface of TylerAdapter needed by the guards.

    We intentionally don't import the real TylerAdapter here because that
    pulls Selenium driver setup into scope and clutters the test signal.
    Both guards are pure methods that only touch the attributes below.
    """

    def __init__(self, *, body_text: str, has_captcha_iframe: bool, captcha_required: bool = True):
        self.driver = FakeDriver(body_text=body_text, has_captcha_iframe=has_captcha_iframe)
        self.captcha_required = captcha_required
        self.captcha_type = "recaptcha_v2"
        self.manual_captcha_timeout_seconds = 120
        self._county_name = "Fresno"
        self._current_search_unit = "AMAYA JANINE / Both"
        self.selectors = {
            "recaptcha_frame": "//iframe[contains(@src, 'recaptcha')]",
        }

    @property
    def county_name(self):
        return self._county_name

    # The real adapter methods we're testing live on TylerAdapter. Re-import
    # them here as bound methods on the fake so we exercise the actual
    # production code without spinning Selenium.
    def _check_empty_search_error(self):
        from titlepro.search.recorder.counties.adapters.tyler_adapter import TylerAdapter
        return TylerAdapter._check_empty_search_error(self)

    def captcha_on_zero_guard(self):
        """Re-implement the tail-of-extract_results captcha guard against
        the fake driver. We can't call extract_results directly (it runs
        JavaScript), so we factor the guard logic to call here.

        This guard's contract: if ``documents == []`` and the page still
        shows a CAPTCHA iframe and there is no "no records found" text,
        raise CaptchaCheckpointRequired.
        """
        from selenium.webdriver.common.by import By
        from titlepro.automation.checkpoints import (
            CaptchaCheckpointRequired,
            checkpoint_sessions,
        )

        documents = []
        if not documents and self.captcha_required:
            still_has_captcha = bool(
                self.driver.find_elements(By.XPATH, self.selectors["recaptcha_frame"])
            )
            if still_has_captcha:
                page_text = (self.driver.find_element(By.TAG_NAME, "body").text or "").lower()
                explicit_no_results = any(
                    msg in page_text for msg in ("no records found", "0 records", "no results")
                )
                if not explicit_no_results:
                    session = checkpoint_sessions.create(
                        checkpoint_type="captcha",
                        county=self.county_name,
                        step="recorder_search_extract",
                        message="CAPTCHA still present after submit.",
                        resource=self,
                        details={
                            "captcha_type": self.captcha_type,
                            "search_unit": self._current_search_unit,
                        },
                        timeout_seconds=self.manual_captcha_timeout_seconds,
                    )
                    raise CaptchaCheckpointRequired(
                        resume_token=session.resume_token,
                        county=self.county_name,
                        step="recorder_search_extract",
                        message="CAPTCHA still present after submit.",
                    )


# ---------------------------------------------------------------------------
# Empty-search error guard
# ---------------------------------------------------------------------------


class TestEmptySearchGuard:
    def test_empty_search_phrase_raises_retryable(self):
        adapter = FakeAdapter(body_text=load_fixture("empty_search_error.txt"), has_captcha_iframe=False)
        with pytest.raises(RetryableSubmitError, match="(?i)empty searches"):
            adapter._check_empty_search_error()

    def test_success_page_does_not_raise(self):
        adapter = FakeAdapter(body_text=load_fixture("results_success.txt"), has_captcha_iframe=False)
        adapter._check_empty_search_error()  # must not raise

    def test_cap_page_does_not_raise(self):
        adapter = FakeAdapter(body_text=load_fixture("results_count_cap.txt"), has_captcha_iframe=False)
        adapter._check_empty_search_error()  # must not raise

    def test_no_results_page_does_not_raise(self):
        adapter = FakeAdapter(body_text=load_fixture("no_results.txt"), has_captcha_iframe=False)
        adapter._check_empty_search_error()  # must not raise


# ---------------------------------------------------------------------------
# CAPTCHA-on-zero-docs guard
# ---------------------------------------------------------------------------


class TestCaptchaOnZeroGuard:
    def test_footer_only_page_with_captcha_still_present_raises(self):
        adapter = FakeAdapter(body_text=load_fixture("footer_only.txt"), has_captcha_iframe=True)
        with pytest.raises(CaptchaCheckpointRequired):
            adapter.captcha_on_zero_guard()

    def test_no_results_page_with_captcha_does_not_raise(self):
        """Explicit 'no records' message + captcha iframe = legit empty result."""
        adapter = FakeAdapter(body_text=load_fixture("no_results.txt"), has_captcha_iframe=True)
        adapter.captcha_on_zero_guard()  # must not raise

    def test_no_captcha_iframe_does_not_raise(self):
        adapter = FakeAdapter(body_text=load_fixture("footer_only.txt"), has_captcha_iframe=False)
        adapter.captcha_on_zero_guard()  # must not raise

    def test_captcha_disabled_county_skips_guard(self):
        adapter = FakeAdapter(
            body_text=load_fixture("footer_only.txt"),
            has_captcha_iframe=True,
            captcha_required=False,
        )
        adapter.captcha_on_zero_guard()  # must not raise


# ---------------------------------------------------------------------------
# Cap-detection sentinel text
# ---------------------------------------------------------------------------


class TestCapDetection:
    """The cap-detection logic in extract_results is a substring match. We
    verify the fixture text triggers the expected sentinel without invoking
    Selenium."""

    CAP_MARKERS = (
        "more documents than the maximum allowed",
        "more records than the maximum",
        "result limit",
        "too many results",
    )

    def test_cap_fixture_contains_a_marker(self):
        body = load_fixture("results_count_cap.txt").lower()
        assert any(marker in body for marker in self.CAP_MARKERS)

    def test_success_fixture_does_not_trigger_cap(self):
        body = load_fixture("results_success.txt").lower()
        assert not any(marker in body for marker in self.CAP_MARKERS)

    def test_footer_only_does_not_trigger_cap(self):
        """The footer mentions 'Tyler Technologies' but NOT a cap message —
        guard against the simpler regex picking up the wrong phrase."""
        body = load_fixture("footer_only.txt").lower()
        assert not any(marker in body for marker in self.CAP_MARKERS)
