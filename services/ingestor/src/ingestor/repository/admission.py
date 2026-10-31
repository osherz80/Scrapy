"""Atomic reservations and dispatch outcomes; never sends a workflow request."""

from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.pq import TransactionStatus

from ..chains import CHAINS
from ..runs.admission import AdmissionError, AdmittedRun, validate_request
from .recovery import reconcile_for_admission

# All ten identities participate so deferred-source changes cannot shift indexes.
_CHAIN_IDS = tuple(sorted(chain.id for chain in CHAINS))


def _require_idle(connection: psycopg.Connection) -> None:
    if not connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise AdmissionError("AUTOCOMMIT_CONNECTION_REQUIRED")


def _timeouts(connection: psycopg.Connection) -> None:
    connection.execute("SET LOCAL lock_timeout = '5s'")
    connection.execute("SET LOCAL statement_timeout = '15s'")


def admit_run(
    connection: psycopg.Connection,
    chains: tuple[str, ...],
    *,
    origin: str = "MANUAL",
) -> AdmittedRun:
    """Commit all reservations or none; caller owns a dedicated idle connection.

    Active runs for disjoint chain sets coexist. Abandoned runs overlapping this
    request are reconciled in the same transaction before new reservation.
    """
    chains = validate_request(chains, origin)
    _require_idle(connection)
    run_id, pending_token = uuid4(), uuid4()
    with connection.transaction():
        _timeouts(connection)
        for chain in chains:
            # Exact stable registry index avoids hash collisions and needs no
            # UPDATE permission on chains for the control role. Reserve this
            # advisory-lock namespace for admission; never hold session locks.
            connection.execute(
                "SELECT pg_advisory_xact_lock(1397900113, %s)",
                (_CHAIN_IDS.index(chain),),
            )
        enabled = connection.execute(
            "SELECT id FROM supermarket.chains WHERE id=ANY(%s) AND enabled ORDER BY id",
            (list(chains),),
        ).fetchall()
        if tuple(row[0] for row in enabled) != chains:
            raise AdmissionError("CHAIN_DISABLED")
        reconcile_for_admission(connection, chains)
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        connection.execute(
            "INSERT INTO supermarket.refresh_runs"
            "(id,origin,requested_chains,created_at,dispatch_state) VALUES (%s,%s,%s,%s,%s)",
            (
                run_id,
                origin,
                list(chains),
                now,
                "PENDING" if origin == "MANUAL" else "NOT_REQUIRED",
            ),
        )
        for chain in chains:
            connection.execute(
                "INSERT INTO supermarket.refresh_run_chains(run_id,chain_id) VALUES (%s,%s)",
                (run_id, chain),
            )
            reserved = connection.execute(
                "INSERT INTO supermarket.chain_leases"
                "(chain_id,run_id,owner_token,heartbeat_at,expires_at) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (chain_id) DO NOTHING RETURNING chain_id",
                (chain, run_id, pending_token, now, now + timedelta(minutes=30)),
            ).fetchone()
            if reserved is None:
                raise AdmissionError("CHAIN_RESERVED")
    return AdmittedRun(run_id, chains)


def record_dispatch(connection: psycopg.Connection, run_id: UUID, outcome: str) -> bool:
    """Persist a definite/uncertain delivery result, without undoing worker claim.

    Returns false for missing, claimed, terminal, scheduled, duplicate or stale
    notifications. Acknowledgement cannot subsequently become uncertainty or
    rejection. A later definite result may resolve an uncertain dispatch.
    """
    if outcome not in ("ACKNOWLEDGED", "UNCERTAIN", "REJECTED"):
        raise AdmissionError("INVALID_DISPATCH_STATE")
    _require_idle(connection)
    with connection.transaction():
        _timeouts(connection)
        row = connection.execute(
            "SELECT status,dispatch_state FROM supermarket.refresh_runs WHERE id=%s FOR UPDATE",
            (run_id,),
        ).fetchone()
        if row is None or row[0] != "PENDING" or row[1] not in ("PENDING", "UNCERTAIN"):
            return False
        if row[1] == outcome:
            return False
        if outcome != "REJECTED":
            connection.execute(
                "UPDATE supermarket.refresh_runs SET dispatch_state=%s WHERE id=%s",
                (outcome, run_id),
            )
        else:
            now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            connection.execute(
                "UPDATE supermarket.refresh_run_chains SET status='FAILED',finished_at=%s,"
                "error_code='DISPATCH_REJECTED' WHERE run_id=%s AND status='PENDING'",
                (now, run_id),
            )
            connection.execute("DELETE FROM supermarket.chain_leases WHERE run_id=%s", (run_id,))
            connection.execute(
                "UPDATE supermarket.refresh_runs SET status='FAILED',dispatch_state='REJECTED',"
                "finished_at=%s,error_code='DISPATCH_REJECTED' WHERE id=%s",
                (now, run_id),
            )
    return True
