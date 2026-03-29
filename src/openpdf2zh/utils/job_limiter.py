from __future__ import annotations

from contextlib import contextmanager
from threading import Condition
from typing import Iterator


class QueueBusyError(RuntimeError):
    pass


class JobLimiter:
    def __init__(self, max_concurrency: int, max_waiting: int) -> None:
        self.max_concurrency = max(max_concurrency, 1)
        self.max_waiting = max(max_waiting, 1)
        self._active = 0
        self._waiting = 0
        self._condition = Condition()

    @contextmanager
    def acquire(self) -> Iterator[None]:
        with self._condition:
            if self._active >= self.max_concurrency:
                if self._waiting >= self.max_waiting:
                    raise QueueBusyError(self.busy_message())
                self._waiting += 1
                try:
                    while self._active >= self.max_concurrency:
                        self._condition.wait()
                finally:
                    self._waiting -= 1
            self._active += 1

        try:
            yield
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify()

    def snapshot(self) -> tuple[int, int]:
        with self._condition:
            return self._active, self._waiting

    def busy_message(self) -> str:
        total_capacity = self.max_concurrency + self.max_waiting
        return (
            "The server is busy processing document translations right now. "
            f"It can handle {self.max_concurrency} active jobs with up to {self.max_waiting} waiting "
            f"requests ({total_capacity} total in-flight). Please try again in a moment."
        )
