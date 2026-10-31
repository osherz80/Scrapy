import io
from datetime import UTC, datetime
from random import Random

from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.packaging import compatible_packages, normalize_package
from ingestor.parsing import parse_catalog
from ingestor.providers.types import (
    Branch,
    BranchIdentity,
    BranchKind,
    CatalogCandidate,
    FileKind,
    PublishedFile,
)
from ingestor.selection import collect_sample


def test_invalid_branch_tail_is_replaced_before_any_observation_can_contribute():
    class Ordered(Random):
        def shuffle(self, values):
            pass

    candidates = []
    for store in ("001", "002", "003", "004"):
        identity = BranchIdentity("rami-levy", "001", store)
        ref = PublishedFile(
            identity,
            FileKind.PRICE_FULL,
            "PriceFull.xml",
            "https://source.test/file",
            datetime(2026, 10, 30, 6, tzinfo=UTC),
        )
        candidates.append(CatalogCandidate(Branch(identity, BranchKind.PHYSICAL_GROCERY), ref))

    def collect(candidate):
        store = candidate.branch.identity.store_id
        code = "partial-only" if store == "001" else "001234"
        quantity, unit = ("1", "ליטר") if store == "002" else ("1000", "מיליליטר")
        xml = (
            f"<Root><ChainId>7290058140886</ChainId><SubChainId>001</SubChainId>"
            f"<StoreId>{store}</StoreId><Items><Item><ItemCode>{code}</ItemCode>"
            f"<ItemName>Example</ItemName><ItemPrice>10.90</ItemPrice>"
            f"<bIsWeighted>0</bIsWeighted><Quantity>{quantity}</Quantity>"
            f"<UnitQty>{unit}</UnitQty></Item></Items></Root>"
        ).encode()
        if store == "001":
            xml = xml[:-5]
        return parse_catalog(
            xml,
            branch=candidate.branch.identity,
            expected_source_chain_id="7290058140886",
            published_at=candidate.file.published_at,
        )

    stream = io.StringIO()
    logger = create_logger(transport=ConsoleTransport(stream)).child(run_id="fixture-run")
    sample = collect_sample(candidates, collect, logger, rng=Ordered())
    assert len(sample.attempted) == 4
    assert sample.failed_attempt_count == 1
    assert len(sample.successful) == 3
    rows = [success.catalog.products[0] for success in sample.successful]
    assert all(row.item_code == "001234" for row in rows)
    packages = [normalize_package(row) for row in rows]
    assert all(compatible_packages(packages[0], package) for package in packages)
    assert packages[0].source_quantity == 1
    assert packages[1].source_quantity == 1000
    assert "partial-only" not in stream.getvalue()
    assert "10.90" not in stream.getvalue()
    assert "fixture-run" in stream.getvalue()
