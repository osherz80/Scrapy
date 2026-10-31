from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from ingestor.repository.admission import admit_run, record_dispatch
from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.runs.admission import AdmissionError

from .conftest import ROOT


@pytest.fixture
def admitted_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def test_admission_reserves_exact_sorted_set_for_thirty_minutes(admitted_db):
    run = admit_run(admitted_db, ("victory", "rami-levy"))
    assert run.chains == ("rami-levy", "victory")
    assert admitted_db.execute(
        "SELECT status,origin,requested_chains,dispatch_state FROM supermarket.refresh_runs"
    ).fetchone() == ("PENDING", "MANUAL", list(run.chains), "PENDING")
    assert admitted_db.execute(
        "SELECT count(*),bool_and(expires_at-heartbeat_at=interval '30 minutes') "
        "FROM supermarket.chain_leases WHERE run_id=%s",
        (run.id,),
    ).fetchone() == (2, True)
    assert admitted_db.execute(
        "SELECT count(*) FROM supermarket.refresh_run_chains WHERE run_id=%s AND status='PENDING'",
        (run.id,),
    ).fetchone() == (2,)


@pytest.mark.parametrize("chains", [(), ("victory", "victory"), ("unknown",), ("carrefour",)])
def test_invalid_or_disabled_chains_create_nothing(admitted_db, chains):
    with pytest.raises(AdmissionError):
        admit_run(admitted_db, chains)
    assert admitted_db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone() == (0,)


def test_conflict_rolls_back_whole_request_including_free_chain(admitted_db):
    first = admit_run(admitted_db, ("victory",))
    with pytest.raises(AdmissionError, match="CHAIN_RESERVED"):
        admit_run(admitted_db, ("rami-levy", "victory"))
    assert admitted_db.execute(
        "SELECT run_id,chain_id FROM supermarket.chain_leases"
    ).fetchall() == [(first.id, "victory")]
    assert admitted_db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone() == (1,)


@pytest.mark.parametrize("overlap", [True, False])
def test_simultaneous_requests_conflict_only_for_overlapping_sets(admitted_db, overlap):
    barrier = Barrier(2)

    def request(chains):
        with psycopg.connect(admitted_db.info.dsn, autocommit=True) as connection:
            connection.execute("SET ROLE supermarket_control")
            barrier.wait(timeout=10)
            try:
                return admit_run(connection, chains)
            except AdmissionError as error:
                return str(error)

    sets = [("victory", "rami-levy"), ("rami-levy", "victory") if overlap else ("osher-ad",)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(request, sets))
    assert sum(result == "CHAIN_RESERVED" for result in results) == int(overlap)
    assert admitted_db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone() == (
        1 if overlap else 2,
    )


def test_uncertain_dispatch_retains_original_reservation_and_can_be_acknowledged(admitted_db):
    run = admit_run(admitted_db, ("victory",))
    lease = admitted_db.execute("SELECT * FROM supermarket.chain_leases").fetchone()
    assert record_dispatch(admitted_db, run.id, "UNCERTAIN")
    assert admitted_db.execute("SELECT * FROM supermarket.chain_leases").fetchone() == lease
    assert record_dispatch(admitted_db, run.id, "ACKNOWLEDGED")
    assert not record_dispatch(admitted_db, run.id, "UNCERTAIN")
    assert admitted_db.execute(
        "SELECT status,dispatch_state FROM supermarket.refresh_runs"
    ).fetchone() == ("PENDING", "ACKNOWLEDGED")


def test_definitive_rejection_fails_run_and_releases_only_its_leases(admitted_db):
    run = admit_run(admitted_db, ("victory", "rami-levy"))
    other = admit_run(admitted_db, ("osher-ad",))
    record_dispatch(admitted_db, run.id, "UNCERTAIN")
    assert record_dispatch(admitted_db, run.id, "REJECTED")
    assert not record_dispatch(admitted_db, run.id, "REJECTED")
    assert admitted_db.execute(
        "SELECT status,dispatch_state,error_code,finished_at IS NOT NULL "
        "FROM supermarket.refresh_runs WHERE id=%s",
        (run.id,),
    ).fetchone() == ("FAILED", "REJECTED", "DISPATCH_REJECTED", True)
    assert admitted_db.execute(
        "SELECT count(*) FROM supermarket.refresh_run_chains WHERE run_id=%s "
        "AND status='FAILED' AND finished_at IS NOT NULL",
        (run.id,),
    ).fetchone() == (2,)
    assert admitted_db.execute("SELECT run_id FROM supermarket.chain_leases").fetchall() == [
        (other.id,)
    ]
    admit_run(admitted_db, run.chains)


def test_late_dispatch_failure_cannot_fail_a_claimed_worker(admitted_db):
    run = admit_run(admitted_db, ("victory",))
    admitted_db.execute(
        "UPDATE supermarket.refresh_runs SET status='RUNNING',started_at=clock_timestamp() "
        "WHERE id=%s",
        (run.id,),
    )
    assert not record_dispatch(admitted_db, run.id, "REJECTED")
    assert admitted_db.execute("SELECT count(*) FROM supermarket.chain_leases").fetchone() == (1,)


def test_scheduled_dispatch_is_not_required_and_unknown_run_is_safe(admitted_db):
    run = admit_run(admitted_db, ("victory",), origin="SCHEDULED")
    assert not record_dispatch(admitted_db, run.id, "REJECTED")
    assert not record_dispatch(admitted_db, uuid4(), "UNCERTAIN")
    with pytest.raises(AdmissionError, match="INVALID_DISPATCH_STATE"):
        record_dispatch(admitted_db, run.id, "unsafe text")


def test_nested_transaction_is_rejected_before_mutation(admitted_db):
    with admitted_db.transaction():
        with pytest.raises(AdmissionError, match="AUTOCOMMIT_CONNECTION_REQUIRED"):
            admit_run(admitted_db, ("victory",))
    assert admitted_db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone() == (0,)


def test_failure_after_run_insert_rolls_back_and_connection_is_reusable(admitted_db):
    admitted_db.execute("REVOKE INSERT ON supermarket.chain_leases FROM supermarket_control")
    admitted_db.execute("SET ROLE supermarket_control")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admit_run(admitted_db, ("victory",))
    assert admitted_db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone() == (0,)
    assert admitted_db.execute(
        "SELECT count(*) FROM supermarket.refresh_run_chains"
    ).fetchone() == (0,)
    admitted_db.execute("RESET ROLE")
    admit_run(admitted_db, ("victory",))


def test_database_disabled_chain_is_rejected(admitted_db):
    admitted_db.execute("UPDATE supermarket.chains SET enabled=false WHERE id='victory'")
    with pytest.raises(AdmissionError, match="CHAIN_DISABLED"):
        admit_run(admitted_db, ("victory",))


def test_expired_lease_is_reconciled_before_readmission(admitted_db):
    first = admit_run(admitted_db, ("victory",))
    admitted_db.execute(
        "UPDATE supermarket.chain_leases SET heartbeat_at=clock_timestamp()-interval '2 hours',"
        "expires_at=clock_timestamp()-interval '1 hour' WHERE run_id=%s",
        (first.id,),
    )
    replacement = admit_run(admitted_db, ("victory",))
    assert admitted_db.execute(
        "SELECT status,error_code FROM supermarket.refresh_runs WHERE id=%s", (first.id,)
    ).fetchone() == ("FAILED", "DISPATCH_EXPIRED")
    assert admitted_db.execute("SELECT run_id FROM supermarket.chain_leases").fetchall() == [
        (replacement.id,)
    ]
