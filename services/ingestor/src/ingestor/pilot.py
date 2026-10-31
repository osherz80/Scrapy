"""Production collection evidence without database access or catalog persistence."""

import re
import sys
from time import monotonic

from .chains import DEFERRED_CHAIN_IDS
from .collection import collect_chain
from .providers.stream import SourceError


def run_pilot(chains, settings, logger, provider_factory, *, clock=monotonic):
    if (
        not chains
        or len(set(chains)) != len(chains)
        or any(c not in settings.enabled_chains or c in DEFERRED_CHAIN_IDS for c in chains)
    ):
        logger.error("pilot.invalid", "Pilot requires distinct enabled, nondeferred chains")
        return 2
    started = clock()
    deadline = started + settings.run_timeout_minutes * 60
    successes = 0

    def check():
        if clock() >= deadline:
            raise SourceError("TIME_LIMIT")

    for chain in chains:
        source = None
        chain_started = clock()
        try:
            check()
            source = provider_factory(chain, settings, deadline)
            result = collect_chain(
                source, chain_id=chain, settings=settings, logger=logger, check=check
            )
            if not result.aggregation.can_publish:
                raise SourceError("NO_PUBLISHABLE_PRODUCTS")
            successes += 1
            logger.info(
                "pilot.chain_completed",
                "Production collection validated without publication",
                chain_id=chain,
                product_count=len(result.aggregation.products),
                successful_branch_count=len(result.successful_branches),
                attempt_count=len(result.attempted_branches),
                duration_ms=round((clock() - chain_started) * 1000),
            )
        except Exception as error:
            code = str(error) if isinstance(error, SourceError) else "PROVIDER_FAILURE"
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
                code = "PROVIDER_FAILURE"
            logger.error(
                "pilot.chain_failed",
                "Production collection validation failed",
                chain_id=chain,
                error_code=code,
                error=error,
            )
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception as error:
                    logger.warn("pilot.close_failed", "Provider cleanup failed", error=error)
        if clock() >= deadline:
            break
    metrics = {}
    # Linux GitHub runners report ru_maxrss in KiB. Other platforms omit it.
    if sys.platform == "linux":
        import resource

        metrics["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    logger.info(
        "pilot.finished",
        "Source-only production pilot finished",
        requested_chain_count=len(chains),
        successful_chain_count=successes,
        duration_ms=round((clock() - started) * 1000),
        **metrics,
    )
    return 0 if successes == len(chains) else 1
