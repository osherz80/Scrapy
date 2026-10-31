"""Single-delivery claims and atomic fenced heartbeat transactions."""

import re
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.pq import TransactionStatus

from ..runs.ownership import OwnershipError, RunOwnership
from .admission import _timeouts


def _validate(connection, lease_seconds, timeout_seconds):
    if any(
        type(value) is not int or not 1 <= value <= maximum
        for value, maximum in ((lease_seconds, 300), (timeout_seconds, 2700))
    ):
        raise OwnershipError("INVALID_OWNERSHIP_TIMING")
    if not connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise OwnershipError("AUTOCOMMIT_CONNECTION_REQUIRED")


def claim_run(
    connection: psycopg.Connection,
    run_id: UUID,
    execution_id: str,
    *,
    lease_seconds: int = 300,
    timeout_seconds: int = 2700,
) -> RunOwnership | None:
    if not isinstance(execution_id, str) or not re.fullmatch(
        r"[0-9]{1,30}(?::[0-9]{1,10})?", execution_id
    ):
        raise OwnershipError("INVALID_EXECUTION_ID")
    _validate(connection, lease_seconds, timeout_seconds)
    with connection.transaction():
        _timeouts(connection)
        row = connection.execute(
            "SELECT status,requested_chains FROM public.refresh_runs WHERE id=%s FOR UPDATE",
            (run_id,),
        ).fetchone()
        if row is None or row[0] != "PENDING":
            return None
        chains = tuple(sorted(row[1]))
        leases = connection.execute(
            "SELECT chain_id,expires_at FROM public.chain_leases "
            "WHERE run_id=%s ORDER BY chain_id FOR UPDATE",
            (run_id,),
        ).fetchall()
        # Read the clock after acquiring locks: a lease can expire during a wait.
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        pending = connection.execute(
            "SELECT chain_id FROM public.refresh_run_chains "
            "WHERE run_id=%s AND status='PENDING' ORDER BY chain_id",
            (run_id,),
        ).fetchall()
        if (
            tuple(lease[0] for lease in leases) != chains
            or tuple(chain[0] for chain in pending) != chains
            or any(lease[1] <= now for lease in leases)
        ):
            raise OwnershipError("LEASE_LOST")
        token = uuid4()
        deadline = now + timedelta(seconds=timeout_seconds)
        connection.execute(
            "UPDATE public.refresh_runs SET status='RUNNING',started_at=%s,github_run_id=%s,"
            "dispatch_state=CASE WHEN dispatch_state='NOT_REQUIRED' THEN 'NOT_REQUIRED' "
            "ELSE 'ACKNOWLEDGED' END "
            "WHERE id=%s",
            (now, execution_id, run_id),
        )
        connection.execute(
            "UPDATE public.chain_leases SET owner_token=%s,heartbeat_at=%s,expires_at=%s "
            "WHERE run_id=%s",
            (token, now, min(deadline, now + timedelta(seconds=lease_seconds)), run_id),
        )
    return RunOwnership(run_id, chains, token, deadline)


def heartbeat(
    connection: psycopg.Connection,
    owner: RunOwnership,
    *,
    lease_seconds: int = 300,
    timeout_seconds: int = 2700,
) -> int:
    """Renew every unfinished chain together, or raise without renewing any."""
    _validate(connection, lease_seconds, timeout_seconds)
    with connection.transaction():
        _timeouts(connection)
        row = connection.execute(
            "SELECT status,requested_chains,started_at FROM public.refresh_runs "
            "WHERE id=%s FOR UPDATE",
            (owner.run_id,),
        ).fetchone()
        if row is None or row[0] != "RUNNING" or tuple(sorted(row[1])) != owner.chains:
            raise OwnershipError("LEASE_LOST")
        active = tuple(
            row[0]
            for row in connection.execute(
                "SELECT chain_id FROM public.refresh_run_chains "
                "WHERE run_id=%s AND status IN ('PENDING','RUNNING') ORDER BY chain_id",
                (owner.run_id,),
            ).fetchall()
        )
        leases = connection.execute(
            "SELECT chain_id,owner_token,expires_at FROM public.chain_leases "
            "WHERE run_id=%s AND chain_id=ANY(%s) ORDER BY chain_id FOR UPDATE",
            (owner.run_id, list(active)),
        ).fetchall()
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        deadline = min(owner.deadline, row[2] + timedelta(seconds=timeout_seconds))
        if deadline <= now:
            raise OwnershipError("RUN_DEADLINE_EXCEEDED")
        if tuple(lease[0] for lease in leases) != active or any(
            lease[1] != owner.token or lease[2] <= now for lease in leases
        ):
            raise OwnershipError("LEASE_LOST")
        connection.execute(
            "UPDATE public.chain_leases SET heartbeat_at=%s,expires_at=%s "
            "WHERE run_id=%s AND chain_id=ANY(%s)",
            (
                now,
                min(deadline, now + timedelta(seconds=lease_seconds)),
                owner.run_id,
                list(active),
            ),
        )
    return len(active)
