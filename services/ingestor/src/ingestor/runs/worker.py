"""Authorized refresh orchestration with injected provider and DB boundaries."""

import re
from collections.abc import Callable
from random import Random
from threading import Event
from time import monotonic
from uuid import UUID

import psycopg

from ..chains import DEFERRED_CHAIN_IDS
from ..collection import ChainCollection, collect_chain
from ..config import Settings
from ..logging.types import Logger
from ..models import AggregationResult
from ..providers.stream import SourceError
from ..providers.types import Provider
from ..repository.ownership import claim_run, heartbeat
from ..repository.publication import publish_collection, start_chain
from ..repository.recovery import failed_chains, finish_run, prune_runs
from .ownership import LeaseGuard, OwnershipError

type ConnectionFactory = Callable[[], psycopg.Connection]
type ProviderFactory = Callable[[str, Settings, float, Logger], Provider]


def _failure_summary(failures):
    return [{"chain_id": chain_id, "error_code": error_code} for chain_id, error_code in failures]


class _CheckedProvider:
    def __init__(self, provider: Provider, check: Callable[[], None]):
        self._provider, self._check = provider, check

    @property
    def source_chain_id(self):
        self._check()
        return self._provider.source_chain_id

    def list_branches(self):
        self._check()
        result = self._provider.list_branches()
        self._check()
        return result

    def iter_files(self):
        self._check()
        for ref in self._provider.iter_files():
            self._check()
            yield ref
        self._check()

    def download(self, ref):
        self._check()
        result = self._provider.download(ref)
        self._check()
        return result

    def close(self):
        self._provider.close()


def _source_code(error):
    if isinstance(error, SourceError) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", str(error)):
        return str(error)
    return "PROVIDER_FAILURE"


def run_worker(
    run_id: UUID,
    *,
    execution_id: str,
    settings: Settings,
    connection_factory: ConnectionFactory,
    provider_factory: ProviderFactory,
    logger: Logger,
    cancelled: Event | None = None,
    rng: Random | None = None,
    clock: Callable[[], float] = monotonic,
) -> int:
    """Return 0 success/duplicate, 1 failed/partial, 2 invalid timing, 130 cancelled.

    Connections are owned here; the renewal connection is dedicated to the guard.
    Providers must enforce the supplied monotonic deadline and bounded I/O. Checks
    are cooperative; workflow timeout/hard-kill recovery remain separate gates.
    """
    if (
        not isinstance(run_id, UUID)
        or not isinstance(execution_id, str)
        or not re.fullmatch(r"[0-9]{1,30}(?::[0-9]{1,10})?", execution_id)
    ):
        logger.error("run.invalid", "Worker identity is invalid")
        return 2
    logger = logger.child(run_id=str(run_id), github_run_id=execution_id)
    cancelled = Event() if cancelled is None else cancelled
    started, owner = clock(), None
    chain_failures = ()
    if not (
        0 < settings.heartbeat_seconds < settings.run_lease_seconds <= 300
        and 0 < settings.run_timeout_minutes <= 45
    ):
        logger.error("run.invalid", "Worker timing exceeds the configured contract")
        return 2
    if cancelled.is_set():
        logger.warn("run.cancelled", "Worker cancelled before claim")
        return 130
    try:
        with connection_factory() as connection:
            owner = claim_run(
                connection,
                run_id,
                execution_id,
                lease_seconds=settings.run_lease_seconds,
                timeout_seconds=settings.run_timeout_minutes * 60,
            )
            if owner is None:
                logger.info("run.skipped", "Run was not pending; no collection performed")
                return 0
            if any(
                chain not in settings.enabled_chains or chain in DEFERRED_CHAIN_IDS
                for chain in owner.chains
            ):
                raise OwnershipError("AUTHORIZED_CHAIN_UNAVAILABLE")
            now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            remaining = (owner.deadline - now).total_seconds()
            if remaining <= 0:
                raise OwnershipError("RUN_DEADLINE_EXCEEDED")
            deadline = clock() + remaining
            logger.info("run.started", "Authorized refresh claimed", chain_count=len(owner.chains))
            with connection_factory() as renewal:

                def renew():
                    return heartbeat(
                        renewal,
                        owner,
                        lease_seconds=settings.run_lease_seconds,
                        timeout_seconds=settings.run_timeout_minutes * 60,
                    )

                with LeaseGuard(
                    renew,
                    logger=logger,
                    interval_seconds=settings.heartbeat_seconds,
                    timeout_seconds=remaining,
                    lease_seconds=settings.run_lease_seconds,
                    retry_seconds=min(5, settings.heartbeat_seconds),
                    monotonic=clock,
                ) as guard:

                    def check():
                        if cancelled.is_set():
                            raise OwnershipError("WORKER_CANCELLED")
                        guard.check()

                    for chain in owner.chains:
                        check()
                        start_chain(connection, owner, chain)
                        chain_logger = logger.child(chain_id=chain)
                        chain_started, source, result, failure = clock(), None, None, None
                        try:
                            check()
                            source = provider_factory(chain, settings, deadline, chain_logger)
                            result = collect_chain(
                                _CheckedProvider(source, check),
                                chain_id=chain,
                                settings=settings,
                                logger=chain_logger,
                                rng=rng,
                                check=check,
                            )
                        except OwnershipError:
                            raise
                        except Exception as error:
                            failure = _source_code(error)
                            chain_logger.error(
                                "chain.collection_failed",
                                "Chain collection failed",
                                error_code=failure,
                                error=error,
                            )
                        finally:
                            if source is not None:
                                try:
                                    source.close()
                                except Exception as error:
                                    chain_logger.warn(
                                        "provider.close_failed",
                                        "Provider cleanup failed",
                                        error=error,
                                    )
                        check()
                        if result is None:
                            result = ChainCollection(
                                AggregationResult(chain, (), 0, 0, 0, 0, 0, 0), (), (), 0
                            )
                        published = publish_collection(
                            connection,
                            owner,
                            result,
                            logger=chain_logger,
                            failure_code=failure,
                            lease_seconds=settings.run_lease_seconds,
                        )
                        chain_logger.info(
                            "chain.finished",
                            "Chain refresh completed",
                            published=published,
                            attempt_count=len(result.attempted_branches),
                            successful_branch_count=len(result.successful_branches),
                            product_count=len(result.aggregation.products),
                            duration_ms=round((clock() - chain_started) * 1000),
                        )
                    check()
                    status = finish_run(connection, owner)
                    chain_failures = failed_chains(connection, owner.run_id)
            try:
                pruned = prune_runs(connection)
                logger.info(
                    "retention.finished",
                    "Operational retention checked",
                    pruned_run_count=len(pruned),
                )
            except Exception as error:
                logger.warn("retention.failed", "Retention maintenance failed", error=error)
        logger.info(
            "run.finished",
            "Refresh completed",
            status=status,
            failed_chain_count=len(chain_failures),
            failed_chains=_failure_summary(chain_failures),
            duration_ms=round((clock() - started) * 1000),
        )
        return 0 if status == "SUCCEEDED" else 1
    except (Exception, KeyboardInterrupt) as error:
        is_cancelled = isinstance(error, KeyboardInterrupt) or cancelled.is_set()
        code = "WORKER_CANCELLED" if is_cancelled else "WORKER_FAILED"
        if isinstance(error, OwnershipError) and str(error) in (
            "LEASE_LOST",
            "HEARTBEAT_FAILED",
            "RUN_DEADLINE_EXCEEDED",
            "AUTHORIZED_CHAIN_UNAVAILABLE",
        ):
            code = str(error)
        logger.error(
            "run.failed",
            "Refresh stopped",
            error_code=code,
            error=error,
            duration_ms=round((clock() - started) * 1000),
        )
        if owner is not None:
            try:
                with connection_factory() as cleanup:
                    status = finish_run(cleanup, owner, abort=True)
                    chain_failures = failed_chains(cleanup, owner.run_id)
                logger.info(
                    "run.teardown_finished",
                    "Unfinished chains finalized",
                    status=status,
                    failed_chain_count=len(chain_failures),
                    failed_chains=_failure_summary(chain_failures),
                )
            except Exception as cleanup_error:
                logger.error(
                    "run.teardown_failed", "Expiry reconciliation is required", error=cleanup_error
                )
        return 130 if is_cancelled else 1
