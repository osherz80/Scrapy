"""Recover abandoned workers without changing committed catalog data."""

from datetime import timedelta
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from ..runs.ownership import OwnershipError, RunOwnership
from ..runs.recovery import ChainStatus, RecoveryError, RunStatus, final_status


def _require_idle(connection):
    if not connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise RecoveryError("AUTOCOMMIT_CONNECTION_REQUIRED")


def _timeouts(connection):
    connection.execute("SET LOCAL lock_timeout = '5s'")
    connection.execute("SET LOCAL statement_timeout = '15s'")


def _states(connection, run_id):
    return connection.execute(
        "SELECT chain_id,status FROM supermarket.refresh_run_chains "
        "WHERE run_id=%s ORDER BY chain_id",
        (run_id,),
    ).fetchall()


def _finalize(connection, run_id, now, error_code=None):
    status = final_status(tuple(row[1] for row in _states(connection, run_id)))
    connection.execute(
        "UPDATE supermarket.refresh_runs SET status=%s,finished_at=%s,error_code=%s WHERE id=%s",
        (status, now, None if status == "SUCCEEDED" else error_code or "CHAIN_FAILURE", run_id),
    )
    connection.execute("DELETE FROM supermarket.chain_leases WHERE run_id=%s", (run_id,))
    return status


def _fail_unfinished(connection, run_id, now, error_code):
    connection.execute(
        "UPDATE supermarket.refresh_run_chains SET status='FAILED',finished_at=%s,"
        "error_code=%s,error_message=NULL WHERE run_id=%s AND status IN ('PENDING','RUNNING')",
        (now, error_code, run_id),
    )


def _reconcile_one(connection, run_id):
    # All worker/dispatch/recovery mutation locks the run first. Recovery never
    # takes admission advisory locks, avoiding a cycle when two disjoint requests
    # recover different chains that belonged to the same abandoned run.
    run = connection.execute(
        "SELECT status,created_at,started_at FROM supermarket.refresh_runs WHERE id=%s FOR UPDATE",
        (run_id,),
    ).fetchone()
    if run is None or run[0] not in ("PENDING", "RUNNING"):
        return False
    active = tuple(
        row[0] for row in _states(connection, run_id) if row[1] in ("PENDING", "RUNNING")
    )
    leases = connection.execute(
        "SELECT chain_id,owner_token,expires_at FROM supermarket.chain_leases "
        "WHERE run_id=%s ORDER BY chain_id FOR UPDATE",
        (run_id,),
    ).fetchall()
    now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    if not active:
        _finalize(connection, run_id, now)
        return True
    leases = [lease for lease in leases if lease[0] in active]
    reason = None
    if run[0] == "PENDING" and run[1] + timedelta(minutes=30) <= now:
        reason = "DISPATCH_EXPIRED"
    elif run[0] == "RUNNING" and run[2] + timedelta(minutes=45) <= now:
        reason = "RUN_DEADLINE_EXCEEDED"
    elif tuple(lease[0] for lease in leases) != active:
        reason = "LEASE_MISSING"
    elif any(lease[2] <= now for lease in leases):
        reason = "DISPATCH_EXPIRED" if run[0] == "PENDING" else "LEASE_EXPIRED"
    elif len({lease[1] for lease in leases}) != 1:
        reason = "LEASE_INCONSISTENT"
    if reason is None:
        return False
    _fail_unfinished(connection, run_id, now, reason)
    _finalize(connection, run_id, now, reason)
    return True


def reconcile_for_admission(
    connection: psycopg.Connection, chains: tuple[str, ...]
) -> tuple[UUID, ...]:
    """Internal composition point: caller already owns the admission transaction."""
    rows = connection.execute(
        "SELECT id FROM supermarket.refresh_runs WHERE status IN ('PENDING','RUNNING') "
        "AND requested_chains && %s ORDER BY id",
        (list(chains),),
    ).fetchall()
    return tuple(row[0] for row in rows if _reconcile_one(connection, row[0]))


def reconcile_expired(connection: psycopg.Connection) -> tuple[UUID, ...]:
    _require_idle(connection)
    with connection.transaction():
        _timeouts(connection)
        rows = connection.execute(
            "SELECT id FROM supermarket.refresh_runs "
            "WHERE status IN ('PENDING','RUNNING') ORDER BY id"
        ).fetchall()
        changed = tuple(row[0] for row in rows if _reconcile_one(connection, row[0]))
    return changed


def get_run_status(connection: psycopg.Connection, run_id: UUID) -> RunStatus | None:
    """Reconcile before returning durable operational state; control-role safe."""
    _require_idle(connection)
    with connection.transaction():
        _timeouts(connection)
        _reconcile_one(connection, run_id)
        row = connection.execute(
            "SELECT id,status,dispatch_state,requested_chains,created_at,started_at,finished_at,"
            "error_code,github_run_id FROM supermarket.refresh_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        chains = connection.execute(
            "SELECT chain_id,status,attempt_count,successful_branch_count,product_count,"
            "invalid_row_count,"
            "conflict_count,source_updated_at,error_code FROM supermarket.refresh_run_chains "
            "WHERE run_id=%s ORDER BY chain_id",
            (run_id,),
        ).fetchall()
        result = RunStatus(
            row[0],
            row[1],
            row[2],
            tuple(row[3]),
            *row[4:8],
            row[8],
            tuple(ChainStatus(*chain) for chain in chains),
        )
    return result


def finish_run(connection: psycopg.Connection, owner: RunOwnership, *, abort: bool = False) -> str:
    """Finalize committed outcomes, or fail only unfinished chains during teardown.

    Abort may release an expired lease only while its token still belongs to this
    worker. Missing/reassigned leases require independent recovery instead.
    """
    _require_idle(connection)
    with connection.transaction():
        _timeouts(connection)
        run = connection.execute(
            "SELECT status,requested_chains FROM supermarket.refresh_runs WHERE id=%s FOR UPDATE",
            (owner.run_id,),
        ).fetchone()
        if run is None:
            raise RecoveryError("RUN_NOT_FOUND")
        if run[0] not in ("PENDING", "RUNNING"):
            return run[0]
        if run[0] != "RUNNING" or tuple(sorted(run[1])) != owner.chains:
            raise OwnershipError("LEASE_LOST")
        active = tuple(
            row[0] for row in _states(connection, owner.run_id) if row[1] in ("PENDING", "RUNNING")
        )
        if active and not abort:
            raise RecoveryError("UNFINISHED_CHAINS")
        if active:
            leases = connection.execute(
                "SELECT chain_id,owner_token FROM supermarket.chain_leases "
                "WHERE run_id=%s AND chain_id=ANY(%s) ORDER BY chain_id FOR UPDATE",
                (owner.run_id, list(active)),
            ).fetchall()
            if tuple(lease[0] for lease in leases) != active or any(
                lease[1] != owner.token for lease in leases
            ):
                raise OwnershipError("LEASE_LOST")
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        if active:
            _fail_unfinished(connection, owner.run_id, now, "WORKER_ABORTED")
        status = _finalize(connection, owner.run_id, now, "WORKER_ABORTED" if active else None)
    return status


def prune_runs(connection: psycopg.Connection) -> tuple[UUID, ...]:
    """Prune at most 100 unreferenced terminal runs older than 30 days per call."""
    _require_idle(connection)
    with connection.transaction():
        _timeouts(connection)
        rows = connection.execute(
            "SELECT r.id FROM supermarket.refresh_runs r "
            "WHERE r.status IN ('SUCCEEDED','PARTIAL_FAILED','FAILED') "
            "AND r.finished_at < clock_timestamp()-interval '30 days' "
            "AND NOT EXISTS(SELECT 1 FROM supermarket.chain_leases l WHERE l.run_id=r.id) "
            "AND NOT EXISTS(SELECT 1 FROM supermarket.chains c WHERE c.current_run_id=r.id) "
            "AND NOT EXISTS(SELECT 1 FROM supermarket.products p WHERE p.run_id=r.id) "
            "ORDER BY r.id LIMIT 100 FOR UPDATE OF r SKIP LOCKED"
        ).fetchall()
        ids = tuple(row[0] for row in rows)
        if ids:
            connection.execute(
                "DELETE FROM supermarket.refresh_runs WHERE id=ANY(%s)", (list(ids),)
            )
    return ids
