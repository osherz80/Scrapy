import io
from threading import Event

import pytest

from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.runs.ownership import LeaseGuard, OwnershipError, TransientOwnershipError


def test_background_heartbeat_and_bounded_stop():
    called = Event()
    calls = []

    def renew():
        calls.append(True)
        if len(calls) >= 2:
            called.set()

    with LeaseGuard(renew, interval_seconds=0.01) as guard:
        assert called.wait(2)
        guard.check()
    assert not guard.running
    with pytest.raises(OwnershipError, match="GUARD_STOPPED"):
        guard.check()


def test_initial_heartbeat_failure_prevents_work_and_redacts_exception():
    stream = io.StringIO()

    def fail():
        raise RuntimeError("synthetic-secret-password")

    guard = LeaseGuard(fail, logger=create_logger(transport=ConsoleTransport(stream)))
    with pytest.raises(OwnershipError, match="HEARTBEAT_FAILED"):
        with guard:
            pytest.fail("work started without ownership")
    assert not guard.running
    assert "synthetic-secret" not in stream.getvalue()
    assert "lease.heartbeat_failed" in stream.getvalue()


def test_background_failure_is_sticky_and_prevents_further_work():
    attempted = Event()
    calls = []

    def renew():
        calls.append(True)
        if len(calls) > 1:
            attempted.set()
            raise OwnershipError("LEASE_LOST")

    with LeaseGuard(renew, interval_seconds=0.01) as guard:
        assert attempted.wait(2)
        assert guard.wait_until_lost(timeout=2)
        with pytest.raises(OwnershipError, match="HEARTBEAT_FAILED"):
            guard.check()


def test_transient_renewal_contention_is_retried_without_losing_ownership():
    renewed = Event()
    calls = []
    stream = io.StringIO()

    def renew():
        calls.append(True)
        if 1 < len(calls) < 4:
            raise TransientOwnershipError("HEARTBEAT_CONTENDED")
        if len(calls) == 4:
            renewed.set()

    with LeaseGuard(
        renew,
        logger=create_logger(transport=ConsoleTransport(stream)),
        interval_seconds=0.01,
        retry_seconds=0.01,
        lease_seconds=300,
    ) as guard:
        assert renewed.wait(2)
        guard.check()
    assert not guard.wait_until_lost(0)
    assert "lease.heartbeat_contended" in stream.getvalue()
    assert "lease.heartbeat_failed" not in stream.getvalue()


def test_transient_contention_past_the_lease_marks_ownership_lost():
    now = [0.0]

    def renew():
        raise TransientOwnershipError("HEARTBEAT_CONTENDED")

    def pause(seconds):
        now[0] += seconds

    guard = LeaseGuard(
        renew,
        interval_seconds=0.01,
        retry_seconds=1,
        lease_seconds=5,
        monotonic=lambda: now[0],
        pause=pause,
    )
    with pytest.raises(OwnershipError, match="HEARTBEAT_FAILED"):
        guard.start()
    with pytest.raises(OwnershipError, match="HEARTBEAT_FAILED"):
        guard.check()


def test_local_monotonic_deadline_stops_work_even_without_another_heartbeat():
    now = [0.0]
    with LeaseGuard(lambda: None, timeout_seconds=1, monotonic=lambda: now[0]) as guard:
        now[0] = 1.0
        with pytest.raises(OwnershipError, match="RUN_DEADLINE_EXCEEDED"):
            guard.check()


def test_guard_cannot_be_restarted():
    guard = LeaseGuard(lambda: None)
    with guard:
        with pytest.raises(OwnershipError, match="GUARD_ALREADY_STARTED"):
            guard.start()


@pytest.mark.parametrize("settings", [{"interval_seconds": 0}, {"timeout_seconds": -1}])
def test_invalid_guard_timing_fails_early(settings):
    with pytest.raises(OwnershipError, match="INVALID_OWNERSHIP_TIMING"):
        LeaseGuard(lambda: None, **settings)
