from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional


_SAFE_KEY = re.compile(r"[^A-Za-z0-9_]+")


def _sanitize(value: Any) -> str:
    """Compact, filesystem-safe key segment."""
    text = "" if value is None else str(value)
    return _SAFE_KEY.sub("_", text).strip("_")


def make_session_key(
    safe_owner: str,
    county: str,
    phase: str,
    job_id: str,
    search_unit: str,
) -> str:
    """Build a case/job/search-unit scoped checkpoint key.

    Format: ``<safe_owner>:<county>:<phase>:<job_id>:<search_unit>``.
    Each segment is sanitized so the key is safe in logs, paths, and JSON.
    """
    parts = [_sanitize(safe_owner), _sanitize(county), _sanitize(phase), _sanitize(job_id), _sanitize(search_unit)]
    return ":".join(p or "_" for p in parts)


class HumanCheckpointRequired(RuntimeError):
    """Raised when automation must pause for a human action."""

    checkpoint_type = "human"

    def __init__(
        self,
        *,
        resume_token: str,
        county: str,
        step: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.resume_token = resume_token
        self.county = county
        self.step = step
        self.message = message
        self.details = details or {}
        # Search unit identifier (e.g. "AMAYA JANINE / Grantor-Grantee").
        # Adapters set this when CAPTCHA pauses mid-search so resume can pick
        # the same unit back up. Falls back to a generic value when omitted.
        self.search_unit = (details or {}).get("search_unit", "initial")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.checkpoint_type,
            "resume_token": self.resume_token,
            "county": self.county,
            "step": self.step,
            "message": self.message,
            "details": self.details,
        }


class CaptchaCheckpointRequired(HumanCheckpointRequired):
    """Raised when a county portal requires manually solved CAPTCHA."""

    checkpoint_type = "captcha"


class RetryableSubmitError(RuntimeError):
    """Raised when a search/submit returns a recoverable form error.

    Surfaced as ``needs_human`` by the pipeline so the user can correct the
    form (e.g. empty-name guard) and resume.
    """

    def __init__(self, message: str, *, county: str = "", step: str = ""):
        super().__init__(message)
        self.county = county
        self.step = step


@dataclass
class CheckpointSession:
    resume_token: str
    checkpoint_type: str
    county: str
    step: str
    message: str
    resource: Any = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(minutes=15))
    status: str = "waiting_for_human"
    session_key: str = ""
    renewable: bool = True

    def public_payload(self) -> dict[str, Any]:
        return {
            "type": self.checkpoint_type,
            "resume_token": self.resume_token,
            "county": self.county,
            "step": self.step,
            "message": self.message,
            "details": self.details,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
            "session_key": self.session_key,
            "renewable": self.renewable,
        }


class CheckpointSessionStore:
    """In-process, thread-safe store for live browser-backed checkpoints.

    Drives the CAPTCHA-pause / human-resume workflow. The store owns the live
    Selenium driver (or equivalent) for the duration of the pause and is
    responsible for closing it on cancel / expire / shutdown so we never leak
    browser processes.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[str, CheckpointSession] = {}

    def create(
        self,
        *,
        checkpoint_type: str,
        county: str = "",
        step: str = "",
        message: str = "",
        resource: Any = None,
        details: Optional[dict[str, Any]] = None,
        timeout_seconds: int = 900,
        session_key: str = "",
        renewable: bool = True,
    ) -> CheckpointSession:
        now = datetime.now()
        token = f"{checkpoint_type}_{_sanitize(county.lower() or 'session')}_{uuid.uuid4().hex[:12]}"
        session = CheckpointSession(
            resume_token=token,
            checkpoint_type=checkpoint_type,
            county=county,
            step=step,
            message=message,
            resource=resource,
            details=dict(details or {}),
            created_at=now,
            expires_at=now + timedelta(seconds=max(int(timeout_seconds), 1)),
            session_key=session_key or "",
            renewable=bool(renewable),
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def get(self, resume_token: str) -> Optional[CheckpointSession]:
        with self._lock:
            session = self._sessions.get(resume_token)
            if not session:
                return None
            if datetime.now() > session.expires_at:
                session.status = "expired"
                self._close_resource(session.resource)
                self._sessions.pop(resume_token, None)
                return None
            return session

    def require(self, resume_token: str) -> CheckpointSession:
        session = self.get(resume_token)
        if not session:
            raise KeyError(f"Checkpoint session not found or expired: {resume_token}")
        return session

    def update_details(self, resume_token: str, details: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(resume_token)
            if session:
                session.details.update(details)

    def complete(self, resume_token: str, *, close_resource: bool = True) -> None:
        """Mark the session completed (successful resume)."""
        with self._lock:
            session = self._sessions.pop(resume_token, None)
        if session:
            session.status = "completed"
            if close_resource:
                self._close_resource(session.resource)

    # Alias matching the proposal's naming.
    def resume(self, resume_token: str) -> CheckpointSession:
        """Mark a session as resumed (in-progress) and return it.

        Unlike ``complete()`` this does NOT close the driver — the caller is
        about to re-enter the paused phase with the live browser. Closure
        happens later via ``complete()`` (on success) or ``fail()``/``cancel()``
        (on terminal failure).
        """
        session = self.require(resume_token)
        with self._lock:
            session.status = "resumed"
        return session

    def renew(self, resume_token: str, additional_seconds: Optional[int] = None) -> CheckpointSession:
        """Extend the expiry of an active checkpoint.

        ``additional_seconds`` defaults to the original timeout window inferred
        from ``created_at`` and ``expires_at``. Raises KeyError if the session
        is unknown or already expired.
        """
        session = self.require(resume_token)
        if not session.renewable:
            raise RuntimeError(f"Checkpoint {resume_token} is not renewable")
        if additional_seconds is None:
            window = (session.expires_at - session.created_at).total_seconds()
            additional_seconds = int(window) if window > 0 else 900
        with self._lock:
            session.expires_at = datetime.now() + timedelta(seconds=max(int(additional_seconds), 1))
        return session

    def fail(self, resume_token: str, *, close_resource: bool = True) -> None:
        with self._lock:
            session = self._sessions.pop(resume_token, None)
        if session:
            session.status = "failed"
            if close_resource:
                self._close_resource(session.resource)

    def cancel(self, resume_token: str) -> Optional[CheckpointSession]:
        """User-initiated cancel — closes the live browser and removes session."""
        with self._lock:
            session = self._sessions.pop(resume_token, None)
        if session:
            session.status = "cancelled"
            self._close_resource(session.resource)
        return session

    def purge_expired(self) -> int:
        """Remove and close any expired sessions. Returns count purged."""
        now = datetime.now()
        purged: list[CheckpointSession] = []
        with self._lock:
            for token in list(self._sessions.keys()):
                session = self._sessions[token]
                if now > session.expires_at:
                    session.status = "expired"
                    purged.append(self._sessions.pop(token))
        for session in purged:
            self._close_resource(session.resource)
        return len(purged)

    def list_active(self) -> list[dict[str, Any]]:
        """Public snapshot of every active checkpoint (auto-purges expired)."""
        self.purge_expired()
        with self._lock:
            return [session.public_payload() for session in self._sessions.values()]

    def public_payload(self, resume_token: str) -> Optional[dict[str, Any]]:
        session = self.get(resume_token)
        return session.public_payload() if session else None

    @staticmethod
    def _close_resource(resource: Any) -> None:
        """Best-effort browser cleanup.

        Selenium drivers expose ``.quit()`` (which closes ALL windows and the
        webdriver process); Playwright contexts expose ``.close()``. Both can
        raise during teardown — never let cleanup propagate.
        """
        if resource is None:
            return
        # Selenium uses .quit() to fully tear down the browser process.
        for method_name in ("quit", "close"):
            method = getattr(resource, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                # quit() supersedes close() — don't double-call.
                if method_name == "quit":
                    return


# Module-level singleton — the entire process shares one checkpoint store.
checkpoint_sessions = CheckpointSessionStore()
# Compat alias: the proposal refers to ``CheckpointRegistry``; keep both
# names available so external imports don't break either way.
CheckpointRegistry = CheckpointSessionStore
