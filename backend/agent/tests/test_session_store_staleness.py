"""Regression tests for ``SessionStore.is_attempt_stale``.

Regular chat-session attempts have no heartbeat trail (unlike swarm runs'
``events.jsonl``), so silence-based staleness detection isn't available for
them. Instead, ``SessionStore`` stamps its own boot time once at construction
and treats any ``running`` attempt created *before* that boot time as
provably orphaned - its owning process is gone, and no restart can revive it.

This closes a real gap found in production use: a killed/restarted backend
left session attempts permanently stuck at ``status: "running"`` on disk,
indistinguishable from a genuinely active turn, with the swarm engine's
equivalent ``is_run_stale`` reconciliation having no counterpart here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.session.models import Attempt, AttemptStatus
from src.session.store import SessionStore


def _make_attempt(session_id: str, status: AttemptStatus, created_at: str) -> Attempt:
    return Attempt(
        session_id=session_id,
        status=status,
        prompt="test prompt",
        created_at=created_at,
    )


def test_running_attempt_from_before_server_boot_is_stale(tmp_path: Path) -> None:
    """A 'running' attempt created before this process started must be flagged stale."""
    store = SessionStore(base_dir=tmp_path)
    old_timestamp = (store._server_epoch - timedelta(hours=1)).isoformat()
    attempt = _make_attempt("s1", AttemptStatus.RUNNING, old_timestamp)

    assert store.is_attempt_stale(attempt) is True


def test_running_attempt_from_after_server_boot_is_not_stale(tmp_path: Path) -> None:
    """A 'running' attempt created under THIS live process is never a false positive,
    no matter how long it's been running - mirrors a real 101-minute successful run
    observed in production that must not be misclassified as abandoned."""
    store = SessionStore(base_dir=tmp_path)
    recent_timestamp = (store._server_epoch + timedelta(seconds=1)).isoformat()
    attempt = _make_attempt("s1", AttemptStatus.RUNNING, recent_timestamp)

    assert store.is_attempt_stale(attempt) is False


def test_completed_attempt_is_never_stale_regardless_of_age(tmp_path: Path) -> None:
    """Staleness only applies to 'running' - a finished attempt from before this
    server booted is just history, not an orphan."""
    store = SessionStore(base_dir=tmp_path)
    old_timestamp = (store._server_epoch - timedelta(days=1)).isoformat()
    attempt = _make_attempt("s1", AttemptStatus.COMPLETED, old_timestamp)

    assert store.is_attempt_stale(attempt) is False


def test_failed_attempt_is_never_stale(tmp_path: Path) -> None:
    """Same as completed - a failed attempt is a terminal state, not an orphan."""
    store = SessionStore(base_dir=tmp_path)
    old_timestamp = (store._server_epoch - timedelta(days=1)).isoformat()
    attempt = _make_attempt("s1", AttemptStatus.FAILED, old_timestamp)

    assert store.is_attempt_stale(attempt) is False


def test_malformed_created_at_is_not_stale_not_crash(tmp_path: Path) -> None:
    """A corrupt/unparseable created_at must degrade to 'not stale' rather than
    raising - staleness is an advisory display flag, never allowed to break the
    surrounding session read."""
    store = SessionStore(base_dir=tmp_path)
    attempt = _make_attempt("s1", AttemptStatus.RUNNING, "not-a-real-timestamp")

    assert store.is_attempt_stale(attempt) is False


def test_server_epoch_marker_is_persisted(tmp_path: Path) -> None:
    """The boot marker file exists and is readable for operator debugging."""
    store = SessionStore(base_dir=tmp_path)
    marker = tmp_path / ".server_epoch"

    assert marker.exists()
    persisted = datetime.fromisoformat(marker.read_text(encoding="utf-8"))
    assert persisted == store._server_epoch


def test_new_server_instance_gets_a_later_epoch(tmp_path: Path) -> None:
    """A fresh SessionStore construction (simulating a process restart) advances
    the epoch, so an attempt that was 'live' under the old instance becomes
    stale once the new instance takes over - the actual production scenario."""
    store1 = SessionStore(base_dir=tmp_path)
    attempt = _make_attempt("s1", AttemptStatus.RUNNING, datetime.now().isoformat())
    assert store1.is_attempt_stale(attempt) is False

    # Simulate the backend process dying and restarting.
    store2 = SessionStore(base_dir=tmp_path)
    assert store2._server_epoch > store1._server_epoch
    assert store2.is_attempt_stale(attempt) is True
