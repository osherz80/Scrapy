"""Ownership evidence and a fail-closed background heartbeat."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, Thread
from time import monotonic, sleep
from uuid import UUID

from ..logging.types import Logger


class OwnershipError(Exception):
    """Static coordination diagnostic, safe to expose without driver details."""


class TransientOwnershipError(OwnershipError):
    """Renewal was blocked by contention; ownership may still be valid."""


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

    A renewal that raises :class:`TransientOwnershipError` is retried instead of
    being treated as ownership loss. Retention stops only once the renewed lease
    could have expired; publication fencing still rejects an expired lease.
    """

    def __init__(
        self,
        renew: Callable[[], object],
        *,
        logger: Logger | None = None,
        interval_seconds: float = 30,
        timeout_seconds: float = 2700,
        lease_seconds: float = 300,
        retry_seconds: float = 5,
        monotonic: Callable[[], float] = monotonic,
        pause: Callable[[float], None] = sleep,
    ) -> None:
        if (
            any(
                not math.isfinite(value) or value <= 0
                for value in (interval_seconds, timeout_seconds, lease_seconds, retry_seconds)
            )
            or timeout_seconds > 2700
            or lease_seconds > 300
        ):
            raise OwnershipError("INVALID_OWNERSHIP_TIMING")
        self._renew, self._logger = renew, logger
        self._interval, self._timeout = interval_seconds, timeout_seconds
        self._lease, self._retry = lease_seconds, retry_seconds
        self._clock, self._pause = monotonic, pause
        self._stop, self._lost = Event(), Event()
        self._thread: Thread | None = None
        self._deadline = 0.0
        self._renewed_at = 0.0
        self._contended = False
        self._started = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._started:
            raise OwnershipError("GUARD_ALREADY_STARTED")
        self._started = True
        self._deadline = self._clock() + self._timeout
        self._renewed_at = self._clock()
        while True:
            try:
                self.check()
                self._renew()
                self._renewed_at = self._clock()
                break
            except TransientOwnershipError as error:
                remaining = self._lease - (self._clock() - self._renewed_at)
                if remaining <= 0:
                    self._lost.set()
                    self._log_failure(error)
                    raise OwnershipError("HEARTBEAT_FAILED") from None
                self._log_contended(error, remaining)
                self._pause(min(self._retry, remaining))
            except Exception as error:
                self._lost.set()
                self._log_failure(error)
                raise OwnershipError("HEARTBEAT_FAILED") from None
        self.check()
        self._thread = Thread(target=self._run, name="ingestor-heartbeat", daemon=True)
        self._thread.start()

    def _pulse(self) -> bool:
        """Renew once; return false only when ownership can no longer be valid."""
        try:
            self.check()
            self._renew()
            self._renewed_at = self._clock()
            if not self._stop.is_set():
                self.check()
            self._contended = False
            return True
        except TransientOwnershipError as error:
            if self._stop.is_set():
                return True
            remaining = self._lease - (self._clock() - self._renewed_at)
            if remaining > 0:
                self._contended = True
                self._log_contended(error, remaining)
                return True
            self._lost.set()
            self._contended = False
            self._log_failure(error)
            return False
        except Exception as error:
            if self._stop.is_set():
                return True
            self._lost.set()
            self._contended = False
            self._log_failure(error)
            return False

    def _run(self) -> None:
        while not self._stop.wait(self._retry if self._contended else self._interval):
            if not self._pulse():
                return

    def _log_contended(self, error: Exception, remaining: float) -> None:
        if self._logger:
            self._logger.warn(
                "lease.heartbeat_contended",
                "Ownership renewal deferred by database contention",
                exception_type=type(error).__name__,
                remaining_seconds=round(remaining, 3),
            )

    def _log_failure(self, error: Exception) -> None:
        if self._logger:
            self._logger.error(
                "lease.heartbeat_failed",
                "Worker ownership could not be renewed",
                exception_type=type(error).__name__,
            )

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
