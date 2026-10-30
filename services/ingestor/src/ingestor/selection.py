"""Randomized three-slot sampling over a complete, validated branch inventory."""

import re
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Sequence
from dataclasses import dataclass, field
from random import Random, SystemRandom
from time import monotonic

from .chains import DEFERRED_CHAIN_IDS
from .logging.types import Logger
from .providers.stream import SourceError
from .providers.types import BranchIdentity, BranchKind, CatalogCandidate


@dataclass(frozen=True)
class BranchSample[T]:
    identity: BranchIdentity
    catalog: T = field(repr=False)


@dataclass(frozen=True)
class SampleResult[T]:
    attempted: tuple[BranchIdentity, ...]
    successful: tuple[BranchSample[T], ...]
    failed_attempt_count: int


def collect_sample[T](
    candidates: Sequence[CatalogCandidate],
    collect: Callable[[CatalogCandidate], T],
    logger: Logger,
    *,
    rng: Random | None = None,
) -> SampleResult[T]:
    """collect must fully parse/validate a nonempty catalog before returning it.

    Never pass streaming rows as a completed catalog. Collection exceptions fail
    the entire attempt, so partial branch data cannot enter successful results.
    """
    queue = list(candidates)
    identities = [candidate.branch.identity for candidate in queue]
    if len(set(identities)) != len(identities):
        raise SourceError("DUPLICATE_BRANCH")
    if len({identity.chain_id for identity in identities}) > 1:
        raise SourceError("MIXED_CHAINS")
    if any(identity.chain_id in DEFERRED_CHAIN_IDS for identity in identities):
        raise SourceError("SOURCE_DEFERRED")
    if any(candidate.branch.kind != BranchKind.PHYSICAL_GROCERY for candidate in queue):
        raise SourceError("INELIGIBLE_BRANCH")
    if identities:
        logger = logger.child(chain_id=identities[0].chain_id)
    (SystemRandom() if rng is None else rng).shuffle(queue)
    remaining = iter(queue)
    attempted = []
    successful = []
    failures = 0
    for slot in range(3):
        for replacement in range(3):
            candidate = next(remaining, None)
            if candidate is None:
                break
            identity = candidate.branch.identity
            attempted.append(identity)
            branch_logger = logger.child(branch_id=f"{identity.subchain_id}/{identity.store_id}")
            started = monotonic()
            branch_logger.info(
                "branch.attempt.started",
                "Collecting sampled branch",
                slot=slot + 1,
                replacement=replacement,
                attempt_count=len(attempted),
            )
            try:
                if candidate.metadata_error_code:
                    raise SourceError(candidate.metadata_error_code)
                catalog = collect(candidate)
                if catalog is None or isinstance(catalog, (Iterator, AsyncIterator)):
                    raise SourceError("INCOMPLETE_CATALOG")
                if isinstance(catalog, Collection) and not catalog:
                    raise SourceError("EMPTY_CATALOG")
                successful.append(BranchSample(identity, catalog))
                branch_logger.info(
                    "branch.attempt.succeeded",
                    "Branch fully validated",
                    duration_ms=round((monotonic() - started) * 1000),
                )
                break
            except Exception as error:
                failures += 1
                code = str(error) if isinstance(error, SourceError) else "BRANCH_FAILED"
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
                    code = "BRANCH_FAILED"
                branch_logger.warn(
                    "branch.attempt.failed",
                    "Branch attempt failed",
                    error_code=code,
                    error=error,
                    duration_ms=round((monotonic() - started) * 1000),
                )
    logger.info(
        "selection.finished",
        "Branch sampling completed",
        attempt_count=len(attempted),
        successful_branch_count=len(successful),
        failed_attempt_count=failures,
    )
    return SampleResult(tuple(attempted), tuple(successful), failures)
