from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest

from ingestor.cli import main
from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.runs.worker import run_worker


def forbidden(*args):
    pytest.fail("operation occurred before worker preflight completed")


@pytest.mark.parametrize(
    "change",
    [
        {"run_timeout_minutes": 46},
        {"run_lease_seconds": 301},
        {"heartbeat_seconds": 300},
        {"heartbeat_seconds": 0},
    ],
)
def test_invalid_worker_timing_does_not_claim_or_open_connections(change):
    assert (
        run_worker(
            uuid4(),
            execution_id="12345:1",
            settings=replace(load_settings({}), **change),
            connection_factory=forbidden,
            provider_factory=forbidden,
            logger=create_logger(),
        )
        == 2
    )


def test_cancellation_before_claim_leaves_run_and_connections_untouched():
    cancelled = Event()
    cancelled.set()
    assert (
        run_worker(
            uuid4(),
            execution_id="12345:1",
            settings=load_settings({}),
            connection_factory=forbidden,
            provider_factory=forbidden,
            logger=create_logger(),
            cancelled=cancelled,
        )
        == 130
    )


@pytest.mark.parametrize(
    "github",
    [
        {},
        {"GITHUB_RUN_ID": "synthetic-secret"},
        {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "bad-secret"},
    ],
)
def test_injected_cli_requires_safe_execution_correlation_before_connection(github, capsys):
    assert (
        main(
            ["refresh", "--run-id", str(uuid4())],
            env={"DATABASE_URL": "postgresql://worker:synthetic-secret@db.test/db", **github},
            connection_factory=forbidden,
            provider_factory=forbidden,
        )
        == 2
    )
    assert "secret" not in capsys.readouterr().err


def test_provider_injection_cannot_bypass_required_execution_context():
    assert (
        main(
            ["refresh", "--run-id", str(uuid4())],
            env={"DATABASE_URL": "postgresql://worker:synthetic-secret@db.test/db"},
            provider_factory=forbidden,
        )
        == 2
    )


@pytest.mark.parametrize("bad_run", [True, False])
def test_invalid_worker_identity_is_rejected_before_binding_input_to_logs(bad_run, capsys):
    assert (
        run_worker(
            "synthetic-secret" if bad_run else uuid4(),
            execution_id="12345:1" if bad_run else "synthetic-secret",
            settings=load_settings({}),
            connection_factory=forbidden,
            provider_factory=forbidden,
            logger=create_logger(),
        )
        == 2
    )
    assert "synthetic-secret" not in capsys.readouterr().err
