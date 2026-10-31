"""Israel-local schedule gate; database date claims remain authoritative."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import Event
from zoneinfo import ZoneInfo

from ..config import Settings
from ..logging.types import Logger
from ..repository.schedule import claim_daily_run
from .admission import AdmissionError
from .worker import ConnectionFactory, ProviderFactory, run_worker


class ScheduleError(Exception):
    """Static schedule diagnostic without caller-supplied values."""


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    local_date: date
    permitted: bool
    reason: str
    delay_seconds: int


def schedule_decision(now: datetime) -> ScheduleDecision:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ScheduleError("INVALID_SCHEDULE_TIME")
    local = now.astimezone(ZoneInfo("Asia/Jerusalem"))
    target = local.replace(hour=6, minute=0, second=0, microsecond=0)
    delay = int((local - target).total_seconds())
    if local.hour < 6:
        reason = "BEFORE_WINDOW"
    elif local.hour > 6:
        reason = "MISSED_WINDOW"
    else:
        reason = "READY" if delay == 0 else "DELAYED"
    return ScheduleDecision(local.date(), local.hour == 6, reason, max(0, delay))


def run_scheduled(
    *,
    settings: Settings,
    execution_id: str,
    connection_factory: ConnectionFactory,
    provider_factory: ProviderFactory,
    logger: Logger,
    now: datetime | None = None,
    cancelled: Event | None = None,
) -> int:
    if not isinstance(execution_id, str) or not re.fullmatch(
        r"[0-9]{1,30}(?::[0-9]{1,10})?", execution_id
    ):
        logger.error("schedule.invalid", "Execution correlation is invalid")
        return 2
    if cancelled is not None and cancelled.is_set():
        logger.warn("schedule.cancelled", "Schedule cancelled before admission")
        return 130
    logger = logger.child(github_run_id=execution_id)
    try:
        decision = schedule_decision(datetime.now(UTC) if now is None else now)
        logger = logger.child(
            local_date=decision.local_date.isoformat(),
            timezone="Asia/Jerusalem",
            delay_seconds=decision.delay_seconds,
        )
        if not decision.permitted:
            logger.warn(
                "schedule.skipped", "Invocation outside the scheduled hour", reason=decision.reason
            )
            return 1 if decision.reason == "MISSED_WINDOW" else 0
        if decision.reason == "DELAYED":
            logger.warn("schedule.delayed", "Scheduled refresh starting after its target time")
        with connection_factory() as connection:
            result = claim_daily_run(
                connection, decision.local_date, settings.enabled_chains, execution_id=execution_id
            )
        if result.outcome == "ALREADY_CLAIMED":
            logger.info(
                "schedule.skipped",
                "Local date already claimed",
                run_id=str(result.run_id),
                reason=result.outcome,
            )
            return 0
        if result.outcome == "SCHEDULE_CONFLICT":
            logger.warn(
                "schedule.conflict",
                "Scheduled chains overlap an existing reservation",
                run_id=str(result.run_id),
            )
            return 1
        logger.info(
            "schedule.admitted",
            "Daily refresh reserved",
            run_id=str(result.run_id),
            chain_count=len(settings.enabled_chains),
        )
        return run_worker(
            result.run_id,
            execution_id=execution_id,
            settings=settings,
            connection_factory=connection_factory,
            provider_factory=provider_factory,
            logger=logger,
            cancelled=cancelled,
        )
    except (Exception, KeyboardInterrupt) as error:
        code = (
            str(error) if isinstance(error, (AdmissionError, ScheduleError)) else "SCHEDULE_FAILED"
        )
        logger.error("schedule.failed", "Scheduled admission failed", error_code=code, error=error)
        return (
            130
            if isinstance(error, KeyboardInterrupt)
            or (cancelled is not None and cancelled.is_set())
            else 1
        )
