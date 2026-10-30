import io
import json
from dataclasses import replace
from datetime import UTC, datetime
from random import Random

import pytest

from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.providers.stream import SourceError
from ingestor.providers.types import (
    Branch,
    BranchIdentity,
    BranchKind,
    CatalogCandidate,
    FileKind,
    PublishedFile,
)
from ingestor.selection import collect_sample


def candidates(count):
    result = []
    for number in range(count):
        identity = BranchIdentity("rami-levy", "001", str(number))
        branch = Branch(identity, BranchKind.PHYSICAL_GROCERY)
        ref = PublishedFile(
            identity,
            FileKind.PRICE_FULL,
            "PriceFull.xml",
            "https://source.test/file",
            datetime(2026, 10, 30, tzinfo=UTC),
        )
        result.append(CatalogCandidate(branch, ref))
    return tuple(result)


def test_three_successes_use_three_distinct_branches_and_seeded_sampling():
    seen = []

    def collect(candidate):
        seen.append(candidate.branch.identity)
        return "validated catalog"

    result = collect_sample(candidates(20), collect, create_logger(), rng=Random(4))
    assert len(result.successful) == 3
    assert len(set(seen)) == 3
    assert len(result.attempted) == 3
    repeated = collect_sample(
        candidates(20), lambda _: "validated catalog", create_logger(), rng=Random(4)
    )
    assert result.attempted == repeated.attempted


def test_all_failures_stop_at_nine_attempts_without_repeating_branches():
    seen = []

    def collect(candidate):
        seen.append(candidate.branch.identity)
        raise RuntimeError("synthetic-secret")

    stream = io.StringIO()
    result = collect_sample(
        candidates(20), collect, create_logger(transport=ConsoleTransport(stream)), rng=Random(1)
    )
    assert len(seen) == len(set(seen)) == 9
    assert result.successful == ()
    assert result.failed_attempt_count == 9
    assert "synthetic-secret" not in stream.getvalue()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert all(record["fields"]["chain_id"] == "rami-levy" for record in records)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_small_roster_exhaustion_keeps_available_successes(count):
    result = collect_sample(
        candidates(count), lambda _: "validated catalog", create_logger(), rng=Random(3)
    )
    assert len(result.successful) == count
    assert len(result.attempted) == count


def test_each_slot_allows_only_initial_attempt_plus_two_replacements():
    class Ordered(Random):
        def shuffle(self, values):
            pass

    def collect(candidate):
        number = int(candidate.branch.identity.store_id)
        if number in (0, 1, 2):
            raise SourceError("INVALID_CATALOG")
        return number

    result = collect_sample(candidates(10), collect, create_logger(), rng=Ordered())
    # The first slot fails after 3 attempts; the remaining slots succeed once each.
    assert [sample.catalog for sample in result.successful] == [3, 4]
    assert len(result.attempted) == 5


def test_partial_or_lazy_catalog_does_not_enter_successful_results():
    def collect(candidate):
        def lazy_rows():
            yield "partial row"
            raise SourceError("INVALID_CATALOG")

        return lazy_rows()

    result = collect_sample(candidates(1), collect, create_logger(), rng=Random(1))
    assert not result.successful
    assert result.failed_attempt_count == 1


def test_duplicate_candidate_identity_is_rejected_before_collection():
    candidate = candidates(1)[0]
    with pytest.raises(SourceError, match="DUPLICATE_BRANCH"):
        collect_sample(
            (candidate, candidate), lambda _: pytest.fail("must not collect"), create_logger()
        )


def test_missing_metadata_is_a_failed_attempt_without_invoking_collection():
    candidate = CatalogCandidate(candidates(1)[0].branch, None, "MISSING_SOURCE_TIME")
    result = collect_sample(
        (candidate,), lambda _: pytest.fail("must not collect"), create_logger()
    )
    assert result.failed_attempt_count == 1
    assert not result.successful


def test_empty_catalog_is_not_a_success():
    result = collect_sample(candidates(1), lambda _: [], create_logger())
    assert not result.successful


def test_deferred_chain_cannot_be_collected_through_the_sampling_boundary():
    original = candidates(1)[0]
    identity = replace(original.branch.identity, chain_id="carrefour")
    candidate = CatalogCandidate(
        replace(original.branch, identity=identity), replace(original.file, identity=identity)
    )
    with pytest.raises(SourceError, match="SOURCE_DEFERRED"):
        collect_sample((candidate,), lambda _: pytest.fail("must not collect"), create_logger())
