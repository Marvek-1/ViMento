"""Lifecycle regression tests for ``_FairLock`` (agent/src/swarm/worker.py).

A standalone stress test already proved FIFO ordering under continuous
contention (no starvation streaks). That proved the happy path. These tests
cover the lifecycle edge cases where lock bugs actually hide: a queued waiter
timing out, a critical section raising, and a timed-out waiter leaving no
orphan ticket behind for a later arrival to collide with.
"""

from __future__ import annotations

import threading
import time

from src.swarm.worker import _FairLock


def test_timed_out_waiter_is_removed_from_queue() -> None:
    """A waiter whose acquire() times out must not remain queued afterward.

    Holds the lock so a second thread queues and then times out. Once the
    holder releases, nothing should be granted to the already-timed-out
    waiter — the queue must be empty, not carrying a stale ticket.
    """
    lock = _FairLock()
    assert lock.acquire(timeout=1)  # main thread holds it

    result: dict[str, bool] = {}

    def waiter() -> None:
        result["acquired"] = lock.acquire(timeout=0.2)

    t = threading.Thread(target=waiter)
    t.start()
    t.join(timeout=2)

    assert result["acquired"] is False, "waiter should have timed out while queued"
    assert len(lock._waiters) == 0, "timed-out waiter must not remain in the queue"

    lock.release()


def test_new_waiter_after_timeout_is_not_blocked_by_orphan_ticket() -> None:
    """A fresh acquire() after a prior waiter's timeout must not stall.

    Regression for a queue-cleanup bug where a timed-out waiter's Event
    could be left in the deque, causing ``release()`` to hand ownership to
    a ticket nobody is waiting on anymore instead of the real next waiter.
    """
    lock = _FairLock()
    assert lock.acquire(timeout=1)  # main thread holds it

    # First waiter times out and gives up before we release.
    first_result: dict[str, bool] = {}

    def first_waiter() -> None:
        first_result["acquired"] = lock.acquire(timeout=0.2)

    t1 = threading.Thread(target=first_waiter)
    t1.start()
    t1.join(timeout=2)
    assert first_result["acquired"] is False

    # A second, later waiter queues after the first one gave up.
    second_result: dict[str, bool] = {}

    def second_waiter() -> None:
        second_result["acquired"] = lock.acquire(timeout=2)

    t2 = threading.Thread(target=second_waiter)
    t2.start()
    time.sleep(0.1)  # ensure it's queued before we release
    lock.release()
    t2.join(timeout=3)

    assert second_result["acquired"] is True, (
        "second waiter must be granted the lock — an orphan ticket from the "
        "timed-out first waiter must not swallow the release"
    )


def test_release_after_exception_in_critical_section_unblocks_next_waiter() -> None:
    """A critical-section exception must not leave the lock permanently held.

    Mirrors the real call site's ``try/finally`` around ``llm.stream_chat``:
    the caller is responsible for calling ``release()`` in a ``finally``
    block regardless of how the critical section exits. This test proves
    that once that contract is honored, a waiter queued behind the failing
    holder is still granted ownership — no deadlock from the exception path.
    """
    lock = _FairLock()
    assert lock.acquire(timeout=1)

    waiter_result: dict[str, bool] = {}

    def waiter() -> None:
        waiter_result["acquired"] = lock.acquire(timeout=2)
        if waiter_result["acquired"]:
            lock.release()

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)  # ensure the waiter is queued before we raise + release

    try:
        raise RuntimeError("simulated failure inside the locked section")
    except RuntimeError:
        pass
    finally:
        lock.release()

    t.join(timeout=3)
    assert waiter_result["acquired"] is True, (
        "waiter must acquire the lock after the holder's critical section "
        "raised, as long as release() ran in the holder's finally block"
    )
