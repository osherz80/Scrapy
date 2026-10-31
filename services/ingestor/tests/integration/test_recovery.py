from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from ingestor.repository.admission import admit_run, record_dispatch
from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.repository.ownership import claim_run, heartbeat
from ingestor.repository.publication import publish_collection
from ingestor.repository.recovery import finish_run, get_run_status, prune_runs, reconcile_expired
from ingestor.runs.admission import AdmissionError
from ingestor.runs.ownership import OwnershipError
from ingestor.runs.recovery import RecoveryError

from .conftest import ROOT
from .test_publication import collection, owner_for


@pytest.fixture
def recovery_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def expire(connection, run_id):
    connection.execute(
        "UPDATE supermarket.chain_leases SET heartbeat_at=clock_timestamp()-interval '2 hours',"
        "expires_at=clock_timestamp()-interval '1 hour' WHERE run_id=%s",
        (run_id,),
    )


@pytest.mark.parametrize("running", [False, True])
def test_status_reconciles_hard_kill_expiry_once_and_allows_readmission(recovery_db, running):
    run = admit_run(recovery_db, ("victory", "osher-ad"))
    if running:
        owner = claim_run(recovery_db, run.id, "12345")
    else:
        record_dispatch(recovery_db, run.id, "UNCERTAIN")
    expire(recovery_db, run.id)
    recovery_db.execute("SET ROLE supermarket_control")
    state = get_run_status(recovery_db, run.id)
    assert state.status == "FAILED"
    assert state.error_code == ("LEASE_EXPIRED" if running else "DISPATCH_EXPIRED")
    assert all(chain.status == "FAILED" for chain in state.chains)
    assert state.finished_at is not None
    assert state.github_run_id == ("12345" if running else None)
    assert get_run_status(recovery_db, run.id) == state
    assert reconcile_expired(recovery_db) == ()
    assert recovery_db.execute("SELECT count(*) FROM supermarket.chain_leases").fetchone() == (0,)
    admit_run(recovery_db, run.chains)
    if running:
        with pytest.raises(OwnershipError, match="LEASE_LOST"):
            heartbeat(recovery_db, owner)


def test_partial_publication_survives_remaining_worker_expiry(recovery_db):
    owner = owner_for(recovery_db, ("victory", "osher-ad"))
    publish_collection(recovery_db, owner, collection("keep"))
    before = recovery_db.execute("SELECT * FROM supermarket.products").fetchall()
    expire(recovery_db, owner.run_id)
    state = get_run_status(recovery_db, owner.run_id)
    assert state.status == "PARTIAL_FAILED"
    assert {chain.chain_id: chain.status for chain in state.chains} == {
        "victory": "SUCCEEDED",
        "osher-ad": "FAILED",
    }
    assert recovery_db.execute("SELECT * FROM supermarket.products").fetchall() == before
    assert recovery_db.execute(
        "SELECT current_run_id FROM supermarket.chains WHERE id='victory'"
    ).fetchone() == (owner.run_id,)


def test_unexpired_runs_are_untouched_and_missing_lease_is_recovered(recovery_db):
    owner = owner_for(recovery_db)
    assert reconcile_expired(recovery_db) == ()
    assert get_run_status(recovery_db, owner.run_id).status == "RUNNING"
    recovery_db.execute("DELETE FROM supermarket.chain_leases WHERE run_id=%s", (owner.run_id,))
    assert reconcile_expired(recovery_db) == (owner.run_id,)
    assert get_run_status(recovery_db, owner.run_id).error_code == "LEASE_MISSING"


def test_new_admission_reconciles_all_chains_of_overlapping_abandoned_run(recovery_db):
    old = owner_for(recovery_db, ("victory", "osher-ad"))
    expire(recovery_db, old.run_id)
    fresh = admit_run(recovery_db, ("victory",))
    assert get_run_status(recovery_db, old.run_id).status == "FAILED"
    assert recovery_db.execute(
        "SELECT chain_id,run_id FROM supermarket.chain_leases"
    ).fetchall() == [("victory", fresh.id)]
    admit_run(recovery_db, ("osher-ad",))


def test_completed_run_is_finalized_even_when_worker_dies_after_publication(recovery_db):
    owner = owner_for(recovery_db)
    publish_collection(recovery_db, owner, collection("keep"))
    assert reconcile_expired(recovery_db) == (owner.run_id,)
    assert get_run_status(recovery_db, owner.run_id).status == "SUCCEEDED"
    assert get_run_status(recovery_db, uuid4()) is None


def test_teardown_fails_only_unfinished_chains_and_rejects_wrong_owner(recovery_db):
    owner = owner_for(recovery_db, ("victory", "osher-ad"))
    publish_collection(recovery_db, owner, collection("keep"))
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        finish_run(recovery_db, replace(owner, token=uuid4()), abort=True)
    with pytest.raises(RecoveryError, match="UNFINISHED_CHAINS"):
        finish_run(recovery_db, owner)
    assert finish_run(recovery_db, owner, abort=True) == "PARTIAL_FAILED"
    assert finish_run(recovery_db, owner, abort=True) == "PARTIAL_FAILED"
    assert get_run_status(recovery_db, owner.run_id).error_code == "WORKER_ABORTED"
    assert recovery_db.execute("SELECT item_code FROM supermarket.products").fetchall() == [
        ("keep",)
    ]
    assert recovery_db.execute("SELECT count(*) FROM supermarket.chain_leases").fetchone() == (0,)


def test_completed_success_and_failure_have_honest_run_outcomes(recovery_db):
    owner = owner_for(recovery_db)
    publish_collection(recovery_db, owner, collection("keep"))
    assert finish_run(recovery_db, owner) == "SUCCEEDED"
    failed = owner_for(recovery_db)
    publish_collection(recovery_db, failed, collection(successes=0))
    assert finish_run(recovery_db, failed) == "FAILED"


def test_job_deadline_recovers_even_if_lease_is_still_in_future(recovery_db):
    owner = owner_for(recovery_db)
    recovery_db.execute(
        "UPDATE supermarket.refresh_runs SET created_at=created_at-interval '1 hour',"
        "started_at=started_at-interval '1 hour' WHERE id=%s",
        (owner.run_id,),
    )
    assert get_run_status(recovery_db, owner.run_id).error_code == "RUN_DEADLINE_EXCEEDED"


def test_two_new_admissions_race_to_recover_one_old_run_without_deadlock(recovery_db):
    old = owner_for(recovery_db, ("victory", "osher-ad"))
    expire(recovery_db, old.run_id)
    barrier = Barrier(2)

    def request(chain):
        with psycopg.connect(recovery_db.info.dsn, autocommit=True) as connection:
            connection.execute("SET ROLE supermarket_control")
            barrier.wait(timeout=5)
            return admit_run(connection, (chain,))

    with ThreadPoolExecutor(max_workers=2) as workers:
        fresh = list(workers.map(request, ("victory", "osher-ad")))
    assert len({run.id for run in fresh}) == 2
    assert get_run_status(recovery_db, old.run_id).status == "FAILED"


def age_run(connection, run_id, days):
    connection.execute(
        "UPDATE supermarket.refresh_runs SET created_at=created_at-%s,"
        "started_at=started_at-%s,finished_at=finished_at-%s WHERE id=%s",
        (timedelta(days=days),) * 3 + (run_id,),
    )


def test_retention_prunes_old_unreferenced_terminal_runs_only(recovery_db):
    referenced = owner_for(recovery_db)
    publish_collection(recovery_db, referenced, collection("current"))
    finish_run(recovery_db, referenced)
    old = owner_for(recovery_db, ("osher-ad",))
    finish_run(recovery_db, old, abort=True)
    recovery_db.execute(
        "INSERT INTO supermarket.schedule_claims(local_date,run_id) VALUES (current_date-40,%s)",
        (old.run_id,),
    )
    recent = owner_for(recovery_db, ("osher-ad",))
    finish_run(recovery_db, recent, abort=True)
    active = owner_for(recovery_db, ("osher-ad",))
    for run in (referenced, old, active):
        age_run(recovery_db, run.run_id, 31)
    # Pruning is an ingestor task; the control role has no product-read privilege.
    recovery_db.execute("SET ROLE supermarket_ingestor")
    assert prune_runs(recovery_db) == (old.run_id,)
    assert prune_runs(recovery_db) == ()
    assert recovery_db.execute(
        "SELECT id FROM supermarket.refresh_runs ORDER BY id"
    ).fetchall() == sorted([(run.run_id,) for run in (referenced, recent, active)])
    assert recovery_db.execute("SELECT count(*) FROM supermarket.schedule_claims").fetchone() == (
        0,
    )
    assert recovery_db.execute("SELECT item_code FROM supermarket.products").fetchall() == [
        ("current",)
    ]


def test_retention_keeps_old_terminal_record_with_active_lease_reference(recovery_db):
    owner = owner_for(recovery_db)
    # Defensive retention: preserve even inconsistent terminal records if a
    # reservation still references them; pruning must never erase a live lease.
    recovery_db.execute(
        "UPDATE supermarket.refresh_runs SET status='FAILED',finished_at=clock_timestamp()"
    )
    age_run(recovery_db, owner.run_id, 31)
    assert prune_runs(recovery_db) == ()


def test_conflicting_admission_rolls_back_recovery_together_with_new_reservation(recovery_db):
    old = owner_for(recovery_db)
    expire(recovery_db, old.run_id)
    live = owner_for(recovery_db, ("osher-ad",))
    with pytest.raises(AdmissionError, match="CHAIN_RESERVED"):
        admit_run(recovery_db, ("victory", "osher-ad"))
    # Read without the reconciling status function to inspect rollback itself.
    assert recovery_db.execute(
        "SELECT status FROM supermarket.refresh_runs WHERE id=%s", (old.run_id,)
    ).fetchone() == ("RUNNING",)
    assert set(recovery_db.execute("SELECT run_id FROM supermarket.chain_leases").fetchall()) == {
        (old.run_id,),
        (live.run_id,),
    }
    assert reconcile_expired(recovery_db) == (old.run_id,)


def test_teardown_can_release_its_own_expired_lease_but_not_a_missing_one(recovery_db):
    owner = owner_for(recovery_db)
    expire(recovery_db, owner.run_id)
    assert finish_run(recovery_db, owner, abort=True) == "FAILED"
    missing = owner_for(recovery_db)
    recovery_db.execute("DELETE FROM supermarket.chain_leases WHERE run_id=%s", (missing.run_id,))
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        finish_run(recovery_db, missing, abort=True)
    assert get_run_status(recovery_db, missing.run_id).status == "FAILED"


def test_retention_is_bounded_to_one_hundred_old_runs_per_transaction(recovery_db):
    ids = tuple(uuid4() for _ in range(101))
    with recovery_db.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO supermarket.refresh_runs"
            "(id,origin,status,requested_chains,created_at,finished_at) "
            "VALUES (%s,'MANUAL','FAILED',ARRAY['victory'],clock_timestamp()-interval '40 days',"
            "clock_timestamp()-interval '31 days')",
            ((run_id,) for run_id in ids),
        )
        cursor.executemany(
            "INSERT INTO supermarket.refresh_run_chains(run_id,chain_id,status,finished_at) "
            "VALUES (%s,'victory','FAILED',clock_timestamp()-interval '31 days')",
            ((run_id,) for run_id in ids),
        )
    first = prune_runs(recovery_db)
    second = prune_runs(recovery_db)
    assert len(first) == 100 and len(second) == 1
    assert set(first + second) == set(ids)
    assert recovery_db.execute(
        "SELECT count(*) FROM supermarket.refresh_run_chains"
    ).fetchone() == (0,)
