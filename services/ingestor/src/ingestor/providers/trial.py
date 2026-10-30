"""Opt-in local feasibility probe. This command never publishes a catalog."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from ..config import Settings
from ..logging.types import Logger
from .http import BoundedClient
from .inspection import inspect_catalog
from .stream import SourceError, decompress

_PORTALS = {
    "shufersal": "prices.shufersal.co.il",
    "carrefour": "prices.carrefour.co.il",
    "hatzi-hinam": "shop.hazi-hinam.co.il",
    "victory": "laibcatalog.co.il",
    "mahsanei-hashuk": "laibcatalog.co.il",
    **dict.fromkeys(
        ("rami-levy", "yochananof", "osher-ad", "tiv-taam", "keshet-teamim"),
        "url.publishedprices.co.il",
    ),
}


@dataclass(frozen=True)
class ProbeFile:
    store_id: str | None
    url: str = field(repr=False)
    published_at: datetime | None


class CandidateSource:
    def __init__(self, chain: str, settings: Settings, deadline: float):
        try:
            import israeli_prices as candidate
        except ImportError:
            raise SourceError("PROBE_DEPENDENCY_MISSING") from None
        if candidate.__version__ != "0.2.0":
            raise SourceError("PROBE_VERSION_MISMATCH")
        self.chain = chain
        self._full_type = candidate.FileType.PRICE_FULL
        self._client = BoundedClient(
            allowed_hosts=frozenset({_PORTALS[chain]}),
            allow_azure=chain in ("shufersal", "hatzi-hinam"),
            timeout_seconds=settings.provider_timeout_seconds,
            max_bytes=settings.provider_max_decompressed_bytes,
            deadline=min(deadline, monotonic() + 120),
        )
        try:
            self._adapter = candidate.get_adapter(chain, client=self._client)
            self.expected_chain_id = self._adapter.info.chain_id
            if not self.expected_chain_id or not re.fullmatch(r"\d{13}", self.expected_chain_id):
                raise SourceError("MISSING_IDENTITY")
        except Exception:
            self.close()
            raise

    def files(self):
        for ref in self._adapter.iter_files(file_type=self._full_type):
            if ref.chain != self.chain or ref.file_type != self._full_type:
                continue
            if not re.match(r"^PriceFull\d{13}-", ref.name, re.IGNORECASE):
                continue
            yield ProbeFile(ref.store_id, ref.url, ref.published_at)

    def download(self, ref: ProbeFile) -> bytes:
        # Bypass adapter.download: its reauthentication path can retry a branch.
        return self._client.get(ref.url).content

    def close(self) -> None:
        self._client.close()


def error_code(error: Exception) -> str:
    if isinstance(error, SourceError) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", str(error)):
        return str(error)
    return "PROVIDER_FAILURE"


def run_probe(
    chains: tuple[str, ...],
    settings: Settings,
    logger: Logger,
    *,
    max_branches: int,
) -> int:
    if not 1 <= max_branches <= 3:
        raise ValueError("max_branches must be 1..3")
    started = monotonic()
    deadline = started + settings.run_timeout_minutes * 60
    logger = logger.child(run_id=str(uuid4()), entry_point="probe", provider="israeli-prices")
    logger.info("probe.started", "Starting bounded feasibility probe", chain_count=len(chains))
    successful_chains = 0
    for chain in chains:
        chain_logger = logger.child(chain_id=chain)
        source = None
        attempts = successes = failures = 0
        observed_branches: set[tuple[str, str, str]] = set()
        try:
            source = CandidateSource(chain, settings, deadline)
            chain_logger.info("probe.listing.started", "Listing candidate full catalogs")
            files = iter(source.files())
            while attempts < max_branches:
                ref = next(files, None)
                if ref is None:
                    break
                attempts += 1
                attempt_start = monotonic()
                try:
                    payload = source.download(ref)
                    xml = decompress(payload, limit=settings.provider_max_decompressed_bytes)
                    summary = inspect_catalog(
                        xml,
                        published_at=ref.published_at,
                        expected_chain=source.expected_chain_id,
                    )
                    branch = (summary.chain_id, summary.subchain_id, summary.store_id)
                    if ref.store_id is None or ref.store_id.lstrip("0") != summary.store_id.lstrip(
                        "0"
                    ):
                        raise SourceError("IDENTITY_MISMATCH")
                    if branch in observed_branches:
                        raise SourceError("DUPLICATE_BRANCH")
                    observed_branches.add(branch)
                    successes += 1
                    chain_logger.info(
                        "probe.branch.succeeded",
                        "Full catalog validated in memory",
                        branch_id="/".join(branch),
                        valid_row_count=summary.valid_rows,
                        invalid_row_count=summary.invalid_rows,
                        package_pair_count=summary.package_rows,
                        source_updated_at=summary.published_at.isoformat(),
                        source_age_hours=round(
                            (datetime.now(UTC) - summary.published_at).total_seconds() / 3600, 2
                        ),
                        duration_ms=round((monotonic() - attempt_start) * 1000),
                        eligibility_verified=False,
                        compressed_byte_count=len(payload),
                        decompressed_byte_count=len(xml),
                    )
                    del payload, xml, summary
                except Exception as error:
                    failures += 1
                    chain_logger.warn(
                        "probe.branch.failed",
                        "Candidate branch failed validation",
                        attempt_count=attempts,
                        error_code=error_code(error),
                        error=error,
                    )
                finally:
                    payload = xml = summary = None
            if attempts == 0:
                raise SourceError("NO_PRICEFULL")
        except Exception as error:
            failures += 1
            chain_logger.error(
                "probe.chain.failed",
                "Candidate source failed",
                error_code=error_code(error),
                error=error,
            )
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception as error:
                    failures += 1
                    chain_logger.error(
                        "probe.chain.failed",
                        "Candidate source cleanup failed",
                        error_code=error_code(error),
                        error=error,
                    )
        passed = successes > 0 and failures == 0
        successful_chains += int(passed)
        chain_logger.info(
            "probe.chain.finished",
            "Chain feasibility probe completed",
            attempt_count=attempts,
            successful_branch_count=successes,
            failed_attempt_count=failures,
            status="SUCCEEDED" if passed else "FAILED",
        )
    failed_chains = len(chains) - successful_chains
    logger.info(
        "probe.finished",
        "Feasibility probe completed",
        successful_chain_count=successful_chains,
        failed_chain_count=failed_chains,
        duration_ms=round((monotonic() - started) * 1000),
    )
    return 1 if failed_chains else 0
