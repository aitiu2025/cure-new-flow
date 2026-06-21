"""Unit tests for the in-process CheckpointSessionStore registry."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from titlepro.automation.checkpoints import (
    CaptchaCheckpointRequired,
    CheckpointSessionStore,
    HumanCheckpointRequired,
    RetryableSubmitError,
    checkpoint_sessions,
    make_session_key,
)


class FakeDriver:
    """Mimics the slice of Selenium WebDriver our registry uses for cleanup."""

    def __init__(self):
        self.quit_called = 0
        self.close_called = 0

    def quit(self):
        self.quit_called += 1

    def close(self):
        self.close_called += 1


class FakeDriverWithRaisingQuit(FakeDriver):
    def quit(self):
        super().quit()
        raise RuntimeError("driver explosion during teardown")


class TestMakeSessionKey:
    def test_sanitizes_each_segment(self):
        key = make_session_key(
            safe_owner="Fresno AMAYA, Janine",
            county="Fresno County",
            phase="search",
            job_id="workflow abc-123",
            search_unit="AMAYA JANINE / Grantor-Grantee",
        )
        assert key == "Fresno_AMAYA_Janine:Fresno_County:search:workflow_abc_123:AMAYA_JANINE_Grantor_Grantee"

    def test_empty_segments_become_placeholder(self):
        key = make_session_key(safe_owner="", county="", phase="", job_id="", search_unit="")
        # Each empty segment renders as "_" so the key shape stays predictable.
        assert key == "_:_:_:_:_"


class TestCheckpointRegistry:
    def setup_method(self):
        self.store = CheckpointSessionStore()

    def test_create_returns_token_and_stores_session(self):
        driver = FakeDriver()
        session = self.store.create(
            checkpoint_type="captcha",
            county="Fresno",
            step="recorder_search_submit",
            message="solve CAPTCHA",
            resource=driver,
            timeout_seconds=120,
            session_key="key1",
        )
        assert session.resume_token
        assert session.checkpoint_type == "captcha"
        assert session.session_key == "key1"
        assert session.status == "waiting_for_human"
        assert session.renewable is True
        again = self.store.require(session.resume_token)
        assert again.resume_token == session.resume_token

    def test_require_missing_raises_keyerror(self):
        with pytest.raises(KeyError):
            self.store.require("does-not-exist")

    def test_resume_marks_session_resumed(self):
        s = self.store.create(checkpoint_type="captcha", message="m", resource=FakeDriver())
        resumed = self.store.resume(s.resume_token)
        assert resumed.status == "resumed"
        # Resource still alive (registry hasn't closed it).
        assert s.resource.quit_called == 0

    def test_renew_extends_expiry(self):
        s = self.store.create(checkpoint_type="captcha", message="m", timeout_seconds=10, resource=FakeDriver())
        original_expiry = s.expires_at
        self.store.renew(s.resume_token, additional_seconds=300)
        refreshed = self.store.require(s.resume_token)
        assert refreshed.expires_at > original_expiry
        # New expiry should land ~300s from now.
        assert (refreshed.expires_at - datetime.now()).total_seconds() > 250

    def test_renew_rejects_non_renewable(self):
        s = self.store.create(
            checkpoint_type="captcha",
            message="m",
            resource=FakeDriver(),
            renewable=False,
        )
        with pytest.raises(RuntimeError, match="not renewable"):
            self.store.renew(s.resume_token, additional_seconds=60)

    def test_cancel_closes_driver_and_removes_session(self):
        driver = FakeDriver()
        s = self.store.create(checkpoint_type="captcha", message="m", resource=driver)
        cancelled = self.store.cancel(s.resume_token)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert driver.quit_called == 1
        # Already cancelled — second call is a no-op.
        again = self.store.cancel(s.resume_token)
        assert again is None

    def test_cancel_unknown_token_is_noop(self):
        assert self.store.cancel("nope") is None

    def test_expired_session_is_purged_on_get(self):
        driver = FakeDriver()
        s = self.store.create(checkpoint_type="captcha", message="m", resource=driver, timeout_seconds=60)
        # Force the expiry into the past.
        s.expires_at = datetime.now() - timedelta(seconds=1)
        # get() should detect the expiry, close the driver, and remove it.
        assert self.store.get(s.resume_token) is None
        assert driver.quit_called == 1

    def test_purge_expired_returns_count_and_closes(self):
        d1 = FakeDriver()
        d2 = FakeDriver()
        s1 = self.store.create(checkpoint_type="captcha", message="m", resource=d1, timeout_seconds=60)
        s2 = self.store.create(checkpoint_type="captcha", message="m", resource=d2, timeout_seconds=60)
        s1.expires_at = datetime.now() - timedelta(seconds=1)
        purged = self.store.purge_expired()
        assert purged == 1
        assert d1.quit_called == 1
        assert d2.quit_called == 0
        # s2 still present
        assert self.store.get(s2.resume_token) is not None

    def test_cleanup_swallows_driver_exceptions(self):
        bad = FakeDriverWithRaisingQuit()
        s = self.store.create(checkpoint_type="captcha", message="m", resource=bad)
        # Should NOT raise even though quit() throws.
        self.store.cancel(s.resume_token)
        assert bad.quit_called == 1

    def test_complete_and_fail_close_driver(self):
        d = FakeDriver()
        s = self.store.create(checkpoint_type="captcha", message="m", resource=d)
        self.store.complete(s.resume_token, close_resource=True)
        assert d.quit_called == 1
        # After complete the token must be gone.
        with pytest.raises(KeyError):
            self.store.require(s.resume_token)

    def test_list_active_excludes_expired(self):
        d_alive = FakeDriver()
        d_dead = FakeDriver()
        alive = self.store.create(checkpoint_type="captcha", message="alive", resource=d_alive, timeout_seconds=60)
        dead = self.store.create(checkpoint_type="captcha", message="dead", resource=d_dead, timeout_seconds=60)
        dead.expires_at = datetime.now() - timedelta(seconds=1)
        active = self.store.list_active()
        tokens = {entry["resume_token"] for entry in active}
        assert alive.resume_token in tokens
        assert dead.resume_token not in tokens

    def test_concurrent_create_and_cancel_thread_safe(self):
        """Smoke test for thread-safety: create + cancel hammered in parallel."""
        store = CheckpointSessionStore()

        def worker(i):
            driver = FakeDriver()
            s = store.create(
                checkpoint_type="captcha",
                message=f"m{i}",
                resource=driver,
                timeout_seconds=30,
            )
            store.cancel(s.resume_token)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, range(64)))
        # Everything cancelled, registry empty.
        assert store.list_active() == []


class TestCheckpointExceptions:
    def test_captcha_inherits_from_human(self):
        exc = CaptchaCheckpointRequired(
            resume_token="tok",
            county="Fresno",
            step="recorder_search_submit",
            message="solve",
            details={"search_unit": "AMAYA JANINE / Both"},
        )
        assert isinstance(exc, HumanCheckpointRequired)
        assert exc.checkpoint_type == "captcha"
        assert exc.search_unit == "AMAYA JANINE / Both"

    def test_retryable_carries_county_and_step(self):
        with pytest.raises(RetryableSubmitError) as ctx:
            raise RetryableSubmitError("oops", county="Fresno", step="recorder_search_submit")
        assert ctx.value.county == "Fresno"
        assert ctx.value.step == "recorder_search_submit"


def test_module_level_singleton_is_registry_instance():
    # Sanity check: the module exports a shared registry the rest of the
    # codebase imports.
    assert isinstance(checkpoint_sessions, CheckpointSessionStore)
