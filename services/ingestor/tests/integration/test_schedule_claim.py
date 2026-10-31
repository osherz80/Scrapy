from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import psycopg
import pytest

from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.repository.admission import admit_run
from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.repository.recovery import get_run_status
from ingestor.repository.schedule import claim_daily_run
from ingestor.runs.schedule import run_scheduled

from .conftest import ROOT
from .test_worker import FixtureProvider


@pytest.fixture
def schedule_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def test_daily_claim_reserves_all_configured_active_chains_and_is_idempotent(schedule_db):
    chains = load_settings({}).enabled_chains
    result = claim_daily_run(schedule_db, date(2026, 7, 15), chains)
    assert result.outcome == "ADMITTED"
    assert claim_daily_run(schedule_db, date(2026, 7, 15), chains).outcome == "ALREADY_CLAIMED"
    assert schedule_db.execute(
        "SELECT count(*) FROM public.chain_leases WHERE run_id=%s", (result.run_id,)
    ).fetchone() == (8,)
    assert schedule_db.execute(
        "SELECT origin,dispatch_state FROM public.refresh_runs"
    ).fetchone() == ("SCHEDULED", "NOT_REQUIRED")


def test_concurrent_daily_invocations_claim_once_using_control_role(schedule_db):
    barrier = Barrier(2)

    def claim(_):
        with psycopg.connect(schedule_db.info.dsn, autocommit=True) as connection:
            connection.execute("SET ROLE supermarket_control")
            barrier.wait(timeout=10)
            return claim_daily_run(connection, date(2026, 7, 15), ("victory",))

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(claim, range(2)))
    assert sorted(result.outcome for result in results) == ["ADMITTED", "ALREADY_CLAIMED"]
    assert len({result.run_id for result in results}) == 1
    assert schedule_db.execute("SELECT count(*) FROM public.refresh_runs").fetchone() == (1,)


def test_manual_overlap_records_scheduled_conflict_without_partial_reservation(schedule_db):
    manual = admit_run(schedule_db, ("victory",))
    result = claim_daily_run(schedule_db, date(2026, 7, 15), ("victory", "osher-ad"))
    assert result.outcome == "SCHEDULE_CONFLICT"
    assert schedule_db.execute("SELECT chain_id,run_id FROM public.chain_leases").fetchall() == [
        ("victory", manual.id)
    ]
    state = get_run_status(schedule_db, result.run_id)
    assert state.status == "FAILED" and state.error_code == "SCHEDULE_CONFLICT"
    assert len(state.chains) == 2 and all(chain.status == "FAILED" for chain in state.chains)
    assert (
        claim_daily_run(schedule_db, date(2026, 7, 15), ("victory", "osher-ad")).outcome
        == "ALREADY_CLAIMED"
    )


def test_failed_claim_insert_rolls_back_run_and_all_leases(schedule_db):
    schedule_db.execute("REVOKE INSERT ON public.schedule_claims FROM supermarket_control")
    schedule_db.execute("SET ROLE supermarket_control")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        claim_daily_run(schedule_db, date(2026, 7, 15), ("victory",))
    assert schedule_db.execute("SELECT count(*) FROM public.refresh_runs").fetchone() == (0,)
    assert schedule_db.execute("SELECT count(*) FROM public.chain_leases").fetchone() == (0,)


def test_scheduled_composition_admits_then_executes_fixture_worker_once(schedule_db):
    calls = []

    def connect():
        connection = psycopg.connect(schedule_db.info.dsn, autocommit=True)
        connection.execute("SET ROLE supermarket_ingestor")
        return connection

    def source(chain, *args):
        calls.append(chain)
        return FixtureProvider(chain)

    kwargs = dict(
        settings=load_settings({"ENABLED_CHAINS": "victory"}),
        execution_id="12345:1",
        connection_factory=connect,
        provider_factory=source,
        logger=create_logger(),
        now=datetime(2026, 7, 15, 3, 1, tzinfo=UTC),
    )
    assert run_scheduled(**kwargs) == 0
    assert run_scheduled(**kwargs) == 0
    assert calls == ["victory"]
    assert schedule_db.execute("SELECT status FROM public.refresh_runs").fetchone() == (
        "SUCCEEDED",
    )
