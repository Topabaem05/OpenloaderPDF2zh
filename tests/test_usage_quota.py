from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openpdf2zh.services.usage_quota import QuotaExceededError, UsageQuotaService


class _Clock:
    def __init__(self, now_utc: datetime) -> None:
        self._now = now_utc
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, *, seconds: float = 0.0, wall_seconds: float | None = None) -> None:
        self._monotonic += seconds
        self._now += timedelta(seconds=seconds if wall_seconds is None else wall_seconds)


def _service(tmp_path: Path, clock: _Clock, *, daily_limit_seconds: int = 500) -> UsageQuotaService:
    return UsageQuotaService(
        str(tmp_path / "quota.sqlite3"),
        daily_limit_seconds=daily_limit_seconds,
        timezone_name="Asia/Seoul",
        now_fn=clock.now,
        monotonic_fn=clock.monotonic,
    )


def test_usage_quota_accumulates_same_ip_and_blocks_after_limit(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 4, 4, 0, 0, tzinfo=UTC))
    service = _service(tmp_path, clock)

    with service.acquire("1.1.1.1") as first:
        clock.advance(seconds=200)
        first.raise_if_expired()

    second = service.acquire("1.1.1.1")
    clock.advance(seconds=300)
    with pytest.raises(QuotaExceededError):
        second.raise_if_expired()

    snapshot = service.get_snapshot("1.1.1.1")
    assert int(round(snapshot.used_seconds)) == 500
    assert snapshot.remaining_seconds == 0.0

    with pytest.raises(QuotaExceededError):
        service.acquire("1.1.1.1")


def test_usage_quota_excludes_time_before_lease_and_separates_ips(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 4, 4, 0, 0, tzinfo=UTC))
    service = _service(tmp_path, clock)

    clock.advance(seconds=240, wall_seconds=240)
    assert service.get_snapshot("1.1.1.1").used_seconds == 0.0

    with service.acquire("1.1.1.1"):
        clock.advance(seconds=120)

    with service.acquire("2.2.2.2"):
        clock.advance(seconds=80)

    assert int(round(service.get_snapshot("1.1.1.1").used_seconds)) == 120
    assert int(round(service.get_snapshot("2.2.2.2").used_seconds)) == 80


def test_usage_quota_resets_on_kst_day_boundary(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 4, 4, 14, 50, tzinfo=UTC))  # 2026-04-04 23:50 KST
    service = _service(tmp_path, clock)

    with service.acquire("1.1.1.1"):
        clock.advance(seconds=60)

    assert int(round(service.get_snapshot("1.1.1.1").used_seconds)) == 60

    clock.advance(seconds=0, wall_seconds=15 * 60)
    next_day_snapshot = service.get_snapshot("1.1.1.1")
    assert next_day_snapshot.used_seconds == 0.0
    assert next_day_snapshot.remaining_seconds == 500.0


def test_usage_quota_rolls_active_lease_into_next_kst_day(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 4, 4, 14, 59, tzinfo=UTC))  # 2026-04-04 23:59 KST
    service = _service(tmp_path, clock)

    with service.acquire("1.1.1.1") as lease:
        clock.advance(seconds=120, wall_seconds=120)
        lease.raise_if_expired()

    with service._connect() as connection:
        previous_day = service._read_used_seconds(connection, "1.1.1.1", "2026-04-04")
        next_day = service._read_used_seconds(connection, "1.1.1.1", "2026-04-05")

    assert int(round(previous_day)) == 60
    assert int(round(next_day)) == 60
    assert int(round(service.get_snapshot("1.1.1.1").used_seconds)) == 60
