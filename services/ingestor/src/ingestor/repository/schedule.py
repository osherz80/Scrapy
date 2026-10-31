"""Atomic local-date claim and all-or-none scheduled chain reservation."""

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import psycopg

from ..runs.admission import AdmissionError, validate_request
from .admission import _admit_in_transaction, _require_idle, _timeouts


@dataclass(frozen=True, slots=True)
class DailyAdmission:
    run_id: UUID
    outcome: str


def claim_daily_run(
    connection: psycopg.Connection,
    local_date: date,
    chains: tuple[str, ...],
    *,
    execution_id: str | None = None,
) -> DailyAdmission:
    chains = validate_request(chains, "SCHEDULED")
    _require_idle(connection)
    if type(local_date) is not date:
        raise AdmissionError("INVALID_SCHEDULE_DATE")
    if execution_id is not None and not re.fullmatch(r"[0-9]{1,30}(?::[0-9]{1,10})?", execution_id):
        raise AdmissionError("INVALID_EXECUTION_ID")
    with connection.transaction():
        _timeouts(connection)
        connection.execute("SELECT pg_advisory_xact_lock(1397900115,%s)", (local_date.toordinal(),))
        existing = connection.execute(
            "SELECT run_id FROM public.schedule_claims WHERE local_date=%s", (local_date,)
        ).fetchone()
        if existing:
            return DailyAdmission(existing[0], "ALREADY_CLAIMED")
        try:
            with connection.transaction():
                admitted = _admit_in_transaction(connection, chains, "SCHEDULED")
            run_id, outcome = admitted.id, "ADMITTED"
        except AdmissionError as error:
            if str(error) != "CHAIN_RESERVED":
                raise
            run_id, outcome = uuid4(), "SCHEDULE_CONFLICT"
            now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            connection.execute(
                "INSERT INTO public.refresh_runs(id,origin,status,requested_chains,created_at,"
                "finished_at,dispatch_state,error_code) VALUES (%s,'SCHEDULED','FAILED',%s,%s,%s,"
                "'NOT_REQUIRED','SCHEDULE_CONFLICT')",
                (run_id, list(chains), now, now),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO public.refresh_run_chains"
                    "(run_id,chain_id,status,finished_at,error_code) "
                    "VALUES (%s,%s,'FAILED',%s,'SCHEDULE_CONFLICT')",
                    ((run_id, chain, now) for chain in chains),
                )
        if execution_id is not None:
            connection.execute(
                "UPDATE public.refresh_runs SET github_run_id=%s WHERE id=%s",
                (execution_id, run_id),
            )
        connection.execute(
            "INSERT INTO public.schedule_claims(local_date,run_id) VALUES (%s,%s)",
            (local_date, run_id),
        )
    return DailyAdmission(run_id, outcome)
