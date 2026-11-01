import gzip
import io
from datetime import UTC, datetime
from decimal import Decimal
from random import Random

import pytest

from ingestor.collection import collect_chain
from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.providers.stream import SourceError
from ingestor.providers.types import Branch, BranchIdentity, BranchKind, FileKind, PublishedFile


class Ordered(Random):
    def shuffle(self, values):
        pass


class FixtureProvider:
    source_chain_id = "7290058140886"

    def __init__(self, count=4, fail_first=True, all_fail=False):
        self.count, self.fail_first, self.all_fail = count, fail_first, all_fail
        self.downloaded = []

    def list_branches(self):
        return tuple(
            Branch(BranchIdentity("rami-levy", "001", str(i)), BranchKind.PHYSICAL_GROCERY)
            for i in range(self.count)
        )

    def iter_files(self):
        for branch in self.list_branches():
            store = branch.identity.store_id
            yield PublishedFile(
                branch.identity,
                FileKind.PRICE_FULL,
                f"PriceFull{self.source_chain_id}-001-{store}-20261030-060000.gz",
                "https://source.test/file?signature=synthetic-secret",
                datetime(2026, 10, 30, 6, tzinfo=UTC),
            )

    def download(self, ref):
        store = ref.identity.store_id
        self.downloaded.append(store)
        if self.all_fail or (self.fail_first and store == "0"):
            raise SourceError("HTTP_403")
        payload = (
            f"<Root><ChainId>{self.source_chain_id}</ChainId><SubChainId>001</SubChainId>"
            f"<StoreId>{store}</StoreId><Items><Item><ItemCode>001234</ItemCode>"
            f"<ItemName>Example</ItemName><ItemPrice>{10 + int(store)}</ItemPrice>"
            f"<Quantity>60</Quantity><UnitQty>ml</UnitQty><bIsWeighted>0</bIsWeighted>"
            "</Item></Items></Root>"
        ).encode()
        return gzip.compress(payload)

    def close(self):
        pass


def test_complete_collection_path_replaces_failure_then_returns_averages_only():
    provider = FixtureProvider()
    stream = io.StringIO()
    logger = create_logger(transport=ConsoleTransport(stream)).child(run_id="fixture-run")
    result = collect_chain(
        provider, chain_id="rami-levy", settings=load_settings({}), logger=logger, rng=Ordered()
    )
    assert provider.downloaded == ["0", "1", "2", "3"]
    assert len(result.attempted_branches) == 4 and result.failed_attempt_count == 1
    product = result.aggregation.products[0]
    assert product.price == Decimal("12.0000") and product.sample_count == 3
    assert product.fields["quantity"] == "60" and result.aggregation.can_publish
    assert "synthetic-secret" not in stream.getvalue()
    assert "001234" not in stream.getvalue()


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_collection_reports_zero_or_partial_coverage_without_fabricating_observations(count):
    provider = FixtureProvider(count=count, fail_first=False)
    result = collect_chain(
        provider,
        chain_id="rami-levy",
        settings=load_settings({}),
        logger=create_logger(),
        rng=Ordered(),
    )
    assert result.aggregation.successful_branch_count == count
    assert result.aggregation.can_publish == (count > 0)
    if count:
        assert result.aggregation.products[0].sample_count == count


def test_complete_source_failure_never_returns_a_publishable_empty_catalog():
    result = collect_chain(
        FixtureProvider(all_fail=True),
        chain_id="rami-levy",
        settings=load_settings({}),
        logger=create_logger(),
        rng=Ordered(),
    )
    assert not result.aggregation.can_publish
    assert not result.aggregation.products
    assert result.failed_attempt_count == 4


def test_listing_failure_prevents_any_download_or_partial_roster_sampling():
    class BrokenListing(FixtureProvider):
        def iter_files(self):
            yield next(super().iter_files())
            raise SourceError("TIME_LIMIT")

    provider = BrokenListing()
    with pytest.raises(SourceError, match="TIME_LIMIT"):
        collect_chain(
            provider, chain_id="rami-levy", settings=load_settings({}), logger=create_logger()
        )
    assert provider.downloaded == []
