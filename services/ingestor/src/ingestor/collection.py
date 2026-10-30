"""Collect and reconcile one chain through injected, transport-independent boundaries."""

import re
from dataclasses import dataclass
from random import Random
from time import monotonic

from .aggregation import aggregate_catalogs
from .chains import DEFERRED_CHAIN_IDS
from .config import Settings
from .logging.types import Logger
from .models import AggregationResult, ParsedCatalog
from .parsing import parse_catalog
from .providers.selected import select_catalogs
from .providers.stream import SourceError, decompress
from .providers.types import BranchIdentity, CatalogCandidate, Provider
from .selection import collect_sample


@dataclass(frozen=True)
class ChainCollection:
    aggregation: AggregationResult
    attempted_branches: tuple[BranchIdentity, ...]
    successful_branches: tuple[BranchIdentity, ...]
    failed_attempt_count: int


def collect_chain(
    provider: Provider,
    *,
    chain_id: str,
    settings: Settings,
    logger: Logger,
    rng: Random | None = None,
) -> ChainCollection:
    """The caller owns provider lifetime. This function never writes to a database."""
    if chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    if chain_id not in settings.enabled_chains:
        raise SourceError("CHAIN_DISABLED")
    logger = logger.child(chain_id=chain_id)
    started = monotonic()
    logger.info("inventory.started", "Reading complete source inventory")
    try:
        source_id = provider.source_chain_id
        if not isinstance(source_id, str) or not re.fullmatch(r"\d{13}", source_id):
            raise SourceError("MISSING_IDENTITY")
        branches = provider.list_branches()
        candidates = select_catalogs(branches, provider.iter_files(), chain_id=chain_id)
    except Exception as error:
        code = str(error) if isinstance(error, SourceError) else "INVENTORY_FAILURE"
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            code = "INVENTORY_FAILURE"
        logger.error("inventory.failed", "Source inventory failed", error_code=code, error=error)
        raise SourceError(code) from None
    logger.info(
        "inventory.finished",
        "Complete inventory validated",
        branch_count=len(branches),
        candidate_count=len(candidates),
        duration_ms=round((monotonic() - started) * 1000),
    )

    def collect(candidate: CatalogCandidate) -> ParsedCatalog:
        ref = candidate.file
        if ref is None:
            raise SourceError("MISSING_SOURCE_TIME")
        payload = provider.download(ref)
        if len(payload) > settings.provider_max_decompressed_bytes:
            raise SourceError("SIZE_LIMIT")
        xml = decompress(payload, limit=settings.provider_max_decompressed_bytes)
        catalog = parse_catalog(
            xml,
            branch=candidate.branch.identity,
            expected_source_chain_id=source_id,
            published_at=ref.published_at,
            max_bytes=settings.provider_max_decompressed_bytes,
        )
        logger.child(branch_id=f"{ref.identity.subchain_id}/{ref.identity.store_id}").info(
            "catalog.parsed",
            "Full branch catalog validated",
            product_count=len(catalog.products),
            invalid_row_count=catalog.invalid_row_count,
            duplicate_row_count=catalog.duplicate_row_count,
            conflict_count=len(catalog.conflicting_codes),
            missing_source_pair_count=catalog.missing_package_count,
        )
        return catalog

    sample = collect_sample(candidates, collect, logger, rng=rng)
    aggregation = aggregate_catalogs(
        tuple(success.catalog for success in sample.successful),
        chain_id=chain_id,
        logger=logger,
    )
    return ChainCollection(
        aggregation,
        sample.attempted,
        tuple(success.identity for success in sample.successful),
        sample.failed_attempt_count,
    )
