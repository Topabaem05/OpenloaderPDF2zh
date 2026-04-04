from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from zoneinfo import ZoneInfo


class QuotaExceededError(RuntimeError):
    pass


@dataclass(slots=True)
class QuotaSnapshot:
    used_seconds: float
    reserved_seconds: float
    limit_seconds: int
    reset_at: datetime

    @property
    def remaining_seconds(self) -> float:
        return max(self.limit_seconds - self.used_seconds - self.reserved_seconds, 0.0)


@dataclass(slots=True)
class QuotaLease:
    service: "UsageQuotaService"
    lease_id: str
    client_ip: str
    day_key: str
    limit_seconds: int
    reserved_seconds: float
    started_at_utc: datetime
    started_monotonic: float
    reset_at: datetime
    initial_used_seconds: float
    closed: bool = False

    def elapsed_seconds(self) -> float:
        return max(self.service.monotonic_fn() - self.started_monotonic, 0.0)

    def deadline_monotonic(self) -> float:
        return self.started_monotonic + self.reserved_seconds

    def raise_if_expired(self) -> None:
        if self.closed:
            return
        self.service._rollover_if_needed(self)
        if self.closed:
            raise QuotaExceededError(self.service.build_limit_error(self.client_ip))
        if self.elapsed_seconds() + 1e-6 < self.reserved_seconds:
            return
        self.service.finalize(self)
        raise QuotaExceededError(self.service.build_limit_error(self.client_ip))

    def close(self) -> None:
        self.service.finalize(self)

    def __enter__(self) -> "QuotaLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class UsageQuotaService:
    def __init__(
        self,
        storage_path: str,
        *,
        daily_limit_seconds: int,
        timezone_name: str,
        now_fn=None,
        monotonic_fn=None,
    ) -> None:
        self.storage_path = Path(storage_path).expanduser().resolve()
        self.daily_limit_seconds = max(int(daily_limit_seconds), 1)
        self.timezone = ZoneInfo(timezone_name)
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        self.monotonic_fn = monotonic_fn or time.monotonic
        self._initialize()

    def acquire(self, client_ip: str) -> QuotaLease:
        normalized_ip = client_ip.strip()
        if not normalized_ip:
            raise RuntimeError("Client IP could not be resolved for runtime quota.")

        snapshot = self.get_snapshot(normalized_ip)
        if snapshot.remaining_seconds <= 0:
            raise QuotaExceededError(self.build_limit_error(normalized_ip))

        lease = QuotaLease(
            service=self,
            lease_id=str(uuid4()),
            client_ip=normalized_ip,
            day_key=self._day_key(),
            limit_seconds=self.daily_limit_seconds,
            reserved_seconds=snapshot.remaining_seconds,
            started_at_utc=self.now_fn(),
            started_monotonic=self.monotonic_fn(),
            reset_at=snapshot.reset_at,
            initial_used_seconds=snapshot.used_seconds,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            refreshed = self._read_snapshot(connection, normalized_ip, lease.day_key)
            if refreshed.remaining_seconds <= 0:
                connection.rollback()
                raise QuotaExceededError(self.build_limit_error(normalized_ip))
            lease.reserved_seconds = refreshed.remaining_seconds
            connection.execute(
                """
                INSERT INTO active_leases (
                    lease_id,
                    client_ip,
                    day_key,
                    reserved_seconds,
                    started_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lease.lease_id,
                    lease.client_ip,
                    lease.day_key,
                    lease.reserved_seconds,
                    self.now_fn().isoformat(),
                ),
            )
            connection.commit()
        return lease

    def finalize(self, lease: QuotaLease) -> None:
        if lease.closed:
            return
        self._rollover_if_needed(lease)
        if lease.closed:
            return
        consumed_seconds = min(lease.elapsed_seconds(), lease.reserved_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM active_leases WHERE lease_id = ?",
                (lease.lease_id,),
            )
            self._commit_usage(
                connection,
                lease.client_ip,
                lease.day_key,
                max(consumed_seconds, 0.0),
            )
            connection.commit()
        lease.closed = True

    def get_snapshot(self, client_ip: str) -> QuotaSnapshot:
        day_key = self._day_key()
        with self._connect() as connection:
            return self._read_snapshot(connection, client_ip.strip(), day_key)

    def build_limit_error(self, client_ip: str) -> str:
        snapshot = self.get_snapshot(client_ip)
        used_seconds = min(snapshot.limit_seconds, int(round(snapshot.used_seconds)))
        reset_label = snapshot.reset_at.astimezone(self.timezone).strftime(
            "%Y-%m-%d %H:%M %Z"
        )
        return (
            "Daily runtime limit exceeded for this IP. "
            f"Today used: {used_seconds}s / {snapshot.limit_seconds}s. "
            "Remaining: 0s. "
            f"Resets at: {reset_label}."
        )

    def _rollover_if_needed(self, lease: QuotaLease) -> None:
        if lease.closed:
            return

        now_utc = self.now_fn()
        monotonic_now = self.monotonic_fn()
        while self._day_key_at(now_utc) != lease.day_key:
            boundary_utc = lease.reset_at.astimezone(UTC)
            elapsed_seconds = max(monotonic_now - lease.started_monotonic, 0.0)
            segment_seconds = max(
                min(
                    elapsed_seconds,
                    (boundary_utc - lease.started_at_utc.astimezone(UTC)).total_seconds(),
                ),
                0.0,
            )
            remaining_elapsed = max(elapsed_seconds - segment_seconds, 0.0)
            next_day_key = self._day_key_at(now_utc)
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM active_leases WHERE lease_id = ?",
                    (lease.lease_id,),
                )
                self._commit_usage(
                    connection,
                    lease.client_ip,
                    lease.day_key,
                    segment_seconds,
                )
                refreshed = self._read_snapshot(
                    connection,
                    lease.client_ip,
                    next_day_key,
                )
                if refreshed.remaining_seconds <= 0:
                    connection.commit()
                    lease.closed = True
                    return
                connection.execute(
                    """
                    INSERT INTO active_leases (
                        lease_id,
                        client_ip,
                        day_key,
                        reserved_seconds,
                        started_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        lease.lease_id,
                        lease.client_ip,
                        next_day_key,
                        refreshed.remaining_seconds,
                        boundary_utc.isoformat(),
                    ),
                )
                connection.commit()
            lease.day_key = next_day_key
            lease.reserved_seconds = refreshed.remaining_seconds
            lease.started_at_utc = boundary_utc
            lease.started_monotonic = monotonic_now - remaining_elapsed
            lease.reset_at = refreshed.reset_at
            lease.initial_used_seconds = refreshed.used_seconds

    def _commit_usage(
        self,
        connection: sqlite3.Connection,
        client_ip: str,
        day_key: str,
        consumed_seconds: float,
    ) -> None:
        existing_used = self._read_used_seconds(connection, client_ip, day_key)
        next_used = min(
            self.daily_limit_seconds,
            existing_used + max(consumed_seconds, 0.0),
        )
        connection.execute(
            """
            INSERT INTO daily_usage (
                client_ip,
                day_key,
                used_seconds,
                updated_at_utc
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(client_ip, day_key) DO UPDATE SET
                used_seconds = excluded.used_seconds,
                updated_at_utc = excluded.updated_at_utc
            """,
            (
                client_ip,
                day_key,
                next_used,
                self.now_fn().isoformat(),
            ),
        )

    def _read_snapshot(
        self,
        connection: sqlite3.Connection,
        client_ip: str,
        day_key: str,
    ) -> QuotaSnapshot:
        used_seconds = self._read_used_seconds(connection, client_ip, day_key)
        reserved_row = connection.execute(
            """
            SELECT COALESCE(SUM(reserved_seconds), 0.0)
            FROM active_leases
            WHERE client_ip = ? AND day_key = ?
            """,
            (client_ip, day_key),
        ).fetchone()
        reserved_seconds = float(reserved_row[0] or 0.0)
        return QuotaSnapshot(
            used_seconds=used_seconds,
            reserved_seconds=reserved_seconds,
            limit_seconds=self.daily_limit_seconds,
            reset_at=self._next_reset_at(),
        )

    def _read_used_seconds(
        self,
        connection: sqlite3.Connection,
        client_ip: str,
        day_key: str,
    ) -> float:
        row = connection.execute(
            """
            SELECT used_seconds
            FROM daily_usage
            WHERE client_ip = ? AND day_key = ?
            """,
            (client_ip, day_key),
        ).fetchone()
        if row is None:
            return 0.0
        return float(row[0] or 0.0)

    def _initialize(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_usage (
                    client_ip TEXT NOT NULL,
                    day_key TEXT NOT NULL,
                    used_seconds REAL NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (client_ip, day_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_leases (
                    lease_id TEXT PRIMARY KEY,
                    client_ip TEXT NOT NULL,
                    day_key TEXT NOT NULL,
                    reserved_seconds REAL NOT NULL,
                    started_at_utc TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.storage_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _day_key(self) -> str:
        return self._day_key_at(self.now_fn())

    def _day_key_at(self, value: datetime) -> str:
        return value.astimezone(self.timezone).date().isoformat()

    def _next_reset_at(self) -> datetime:
        localized_now = self.now_fn().astimezone(self.timezone)
        midnight = datetime.combine(
            localized_now.date() + timedelta(days=1),
            datetime.min.time(),
            self.timezone,
        )
        return midnight
