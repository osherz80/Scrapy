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
from ingestor.runs.ownership import OwnershipError

from .conftest import ROOT


@pytest.fixture
def owned_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def test_claim_sets_execution_and_new_token_with_five_minute_leases(owned_db):
    run = admit_run(owned_db, ("victory", "osher-ad"))
    pending_token = owned_db.execute(
        "SELECT owner_token FROM public.chain_leases LIMIT 1"
    ).fetchone()[0]
    owner = claim_run(owned_db, run.id, "12345:1")
    assert owner.run_id == run.id and owner.chains == run.chains
    assert owner.token != pending_token and str(owner.token) not in repr(owner)
    assert owned_db.execute(
        "SELECT status,github_run_id,started_at IS NOT NULL FROM public.refresh_runs"
    ).fetchone() == ("RUNNING", "12345:1", True)
    assert owned_db.execute(
        "SELECT count(*) FROM public.chain_leases WHERE owner_token=%s "
        "AND expires_at-heartbeat_at=interval '300 seconds'",
        (owner.token,),
    ).fetchone() == (2,)
    assert claim_run(owned_db, run.id, "12345:2") is None
    assert not record_dispatch(owned_db, run.id, "REJECTED")


def test_duplicate_delivery_race_only_claims_once(owned_db):
    run = admit_run(owned_db, ("victory",))
    barrier = Barrier(2)

    def claim(attempt):
        with psycopg.connect(owned_db.info.dsn, autocommit=True) as connection:
            connection.execute("SET ROLE supermarket_ingestor")
            barrier.wait(timeout=10)
            return claim_run(connection, run.id, f"12345:{attempt}")

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(claim, (1, 2)))
    assert sum(owner is not None for owner in claims) == 1


def test_heartbeat_renews_all_owned_leases_and_rejects_wrong_token(owned_db):
    run = admit_run(owned_db, ("victory", "osher-ad"))
    owned_db.execute("SET ROLE supermarket_ingestor")
    owner = claim_run(owned_db, run.id, "12345")
    assert heartbeat(owned_db, owner) == 2
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        heartbeat(owned_db, replace(owner, token=uuid4()))
    assert heartbeat(owned_db, owner) == 2


def test_claim_resolves_dispatch_uncertainty(owned_db):
    run = admit_run(owned_db, ("victory",))
    record_dispatch(owned_db, run.id, "UNCERTAIN")
    assert claim_run(owned_db, run.id, "12345") is not None
    assert owned_db.execute("SELECT dispatch_state FROM public.refresh_runs").fetchone() == (
        "ACKNOWLEDGED",
    )


def test_claim_and_dispatch_rejection_race_has_one_consistent_outcome(owned_db):
    run = admit_run(owned_db, ("victory",))
    barrier = Barrier(2)

    def act(claim):
        with psycopg.connect(owned_db.info.dsn, autocommit=True) as connection:
            barrier.wait(timeout=10)
            return (
                claim_run(connection, run.id, "12345")
                if claim
                else record_dispatch(connection, run.id, "REJECTED")
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        owner, rejected = list(workers.map(act, (True, False)))
    assert (owner is None) == rejected
    assert owned_db.execute("SELECT status FROM public.refresh_runs").fetchone() == (
        "FAILED" if rejected else "RUNNING",
    )
    assert owned_db.execute("SELECT count(*) FROM public.chain_leases").fetchone() == (
        0 if rejected else 1,
    )


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_expired_lease_cannot_be_claimed(owned_db, missing):
    run = admit_run(owned_db, ("victory",))
    _invalidate_lease(owned_db, run.id, missing)
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        claim_run(owned_db, run.id, "12345")
    assert owned_db.execute("SELECT status FROM public.refresh_runs").fetchone() == ("PENDING",)


@pytest.mark.parametrize("missing", [True, False])
def test_one_lost_lease_prevents_partial_renewal(owned_db, missing):
    run = admit_run(owned_db, ("victory", "osher-ad"))
    owner = claim_run(owned_db, run.id, "12345")
    _invalidate_lease(owned_db, run.id, missing)
    before = owned_db.execute(
        "SELECT heartbeat_at FROM public.chain_leases WHERE chain_id='osher-ad'"
    ).fetchone()
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        heartbeat(owned_db, owner)
    assert (
        owned_db.execute(
            "SELECT heartbeat_at FROM public.chain_leases WHERE chain_id='osher-ad'"
        ).fetchone()
        == before
    )


def _invalidate_lease(connection, run_id, missing):
    if missing:
        connection.execute(
            "DELETE FROM public.chain_leases WHERE run_id=%s AND chain_id='victory'", (run_id,)
        )
    else:
        connection.execute(
            "UPDATE public.chain_leases SET heartbeat_at=clock_timestamp()-interval '2 hours',"
            "expires_at=clock_timestamp()-interval '1 hour' WHERE run_id=%s AND chain_id='victory'",
            (run_id,),
        )


def test_deadline_caps_lease_and_prevents_renewal_after_job_limit(owned_db):
    run = admit_run(owned_db, ("victory",))
    owner = claim_run(owned_db, run.id, "12345", timeout_seconds=60)
    assert owned_db.execute(
        "SELECT expires_at-heartbeat_at FROM public.chain_leases"
    ).fetchone() == (timedelta(seconds=60),)
    owned_db.execute(
        "UPDATE public.refresh_runs SET created_at=created_at-interval '1 hour',"
        "started_at=started_at-interval '1 hour' WHERE id=%s",
        (run.id,),
    )
    with pytest.raises(OwnershipError, match="RUN_DEADLINE_EXCEEDED"):
        heartbeat(owned_db, owner, timeout_seconds=60)


def test_heartbeat_ignores_completed_chains_without_recreating_reservations(owned_db):
    run = admit_run(owned_db, ("victory", "osher-ad"))
    owner = claim_run(owned_db, run.id, "12345")
    owned_db.execute(
        "UPDATE public.refresh_run_chains SET status='FAILED',finished_at=clock_timestamp() "
        "WHERE run_id=%s AND chain_id='victory'",
        (run.id,),
    )
    owned_db.execute("DELETE FROM public.chain_leases WHERE chain_id='victory'")
    assert heartbeat(owned_db, owner) == 1
    assert owned_db.execute("SELECT count(*) FROM public.chain_leases").fetchone() == (1,)


def test_unknown_or_rejected_run_is_not_claimed_and_input_is_sanitized(owned_db):
    assert claim_run(owned_db, uuid4(), "12345") is None
    run = admit_run(owned_db, ("victory",))
    record_dispatch(owned_db, run.id, "REJECTED")
    assert claim_run(owned_db, run.id, "12345") is None
    with pytest.raises(OwnershipError, match="^INVALID_EXECUTION_ID$"):
        claim_run(owned_db, run.id, "secret text")


def test_old_owner_cannot_renew_a_chain_after_expiry_and_readmission(owned_db):
    old_run = admit_run(owned_db, ("victory",))
    old_owner = claim_run(owned_db, old_run.id, "12345")
    _invalidate_lease(owned_db, old_run.id, missing=False)
    # Simulate the lease release boundary of the upcoming recovery layer. Even
    # before old run finalization, its token must not touch the new reservation.
    owned_db.execute("DELETE FROM public.chain_leases WHERE run_id=%s", (old_run.id,))
    new_run = admit_run(owned_db, ("victory",))
    new_owner = claim_run(owned_db, new_run.id, "67890")
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        heartbeat(owned_db, old_owner)
    assert heartbeat(owned_db, new_owner) == 1
    assert owned_db.execute("SELECT owner_token FROM public.chain_leases").fetchone() == (
        new_owner.token,
    )
