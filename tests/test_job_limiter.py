from __future__ import annotations

from threading import Event, Thread

from openpdf2zh.utils.job_limiter import JobLimiter, QueueBusyError


def test_job_limiter_raises_busy_when_queue_is_full() -> None:
    limiter = JobLimiter(max_concurrency=1, max_waiting=1)
    release_active = Event()
    waiting_started = Event()

    def active_job() -> None:
        with limiter.acquire():
            waiting_started.set()
            release_active.wait(timeout=2)

    active_thread = Thread(target=active_job)
    active_thread.start()
    waiting_started.wait(timeout=2)

    queue_entered = Event()

    def waiting_job() -> None:
        queue_entered.set()
        with limiter.acquire():
            return None

    waiting_thread = Thread(target=waiting_job)
    waiting_thread.start()
    queue_entered.wait(timeout=2)

    try:
        with limiter.acquire():
            raise AssertionError("QueueBusyError should have been raised")
    except QueueBusyError as exc:
        assert "The server is busy processing document translations right now." in str(
            exc
        )

    release_active.set()
    active_thread.join(timeout=2)
    waiting_thread.join(timeout=2)


def test_job_limiter_releases_slots_after_completion() -> None:
    limiter = JobLimiter(max_concurrency=1, max_waiting=1)

    with limiter.acquire():
        assert limiter.snapshot() == (1, 0)

    assert limiter.snapshot() == (0, 0)
