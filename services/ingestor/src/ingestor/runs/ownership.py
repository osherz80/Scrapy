"""Ownership evidence and a fail-closed background heartbeat."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, Thread
from time import monotonic
from uuid import UUID

from ..logging.types import Logger


class OwnershipError(Exception):
    """Static coordination diagnostic, safe to expose without driver details."""


@dataclass(frozen=True, slots=True)
class RunOwnership:
    run_id: UUID
    chains: tuple[str, ...]
    token: UUID = field(repr=False)
    deadline: datetime


class LeaseGuard:
    """Check before external work and publication; SQL fencing remains mandatory.

    The renewal callback must use a dedicated connection with bounded database
    timeouts. Shutdown waits at most five seconds; Python cannot forcibly cancel
    blocked provider/database calls. Worker wiring must close/cancel those calls.
    """

    def __init__(
        self,
        renew: Callable[[], object],
        *,
        logger: Logger | None = None,
        interval_seconds: float = 30,
        timeout_seconds: float = 2700,
        monotonic: Callable[[], float] = monotonic,
    ) -> None:
        if (
            any(
                not math.isfinite(value) or value <= 0
                for value in (interval_seconds, timeout_seconds)
            )
            or timeout_seconds > 2700
        ):
            raise OwnershipError("INVALID_OWNERSHIP_TIMING")
        self._renew, self._logger = renew, logger
        self._interval, self._timeout = interval_seconds, timeout_seconds
        self._clock = monotonic
        self._stop, self._lost = Event(), Event()
        self._thread: Thread | None = None
        self._deadline = 0.0
        self._started = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._started:
            raise OwnershipError("GUARD_ALREADY_STARTED")
        self._started = True
        self._deadline = self._clock() + self._timeout
        self._pulse()
        self.check()
        self._thread = Thread(target=self._run, name="ingestor-heartbeat", daemon=True)
        self._thread.start()

    def _pulse(self) -> None:
        try:
            self.check()
            self._renew()
            if not self._stop.is_set():
                self.check()
        except Exception as error:
            if self._stop.is_set():
                return
            self._lost.set()
            if self._logger:
                self._logger.error(
                    "lease.heartbeat_failed",
                    "Worker ownership could not be renewed",
                    exception_type=type(error).__name__,
                )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._pulse()
            if self._lost.is_set():
                return

    def check(self) -> None:
        if self._lost.is_set():
            raise OwnershipError("HEARTBEAT_FAILED")
        if not self._started or self._stop.is_set():
            raise OwnershipError("GUARD_STOPPED")
        if self._clock() >= self._deadline:
            self._lost.set()
            raise OwnershipError("RUN_DEADLINE_EXCEEDED")

    def wait_until_lost(self, timeout: float) -> bool:
        return self._lost.wait(timeout)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()
