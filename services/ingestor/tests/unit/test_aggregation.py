from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ingestor.aggregation import aggregate_catalogs
from ingestor.models import ParsedCatalog, ProductObservation
from ingestor.providers.stream import SourceError
from ingestor.providers.types import BranchIdentity

NOW = datetime(2026, 10, 30, 6, tzinfo=UTC)


def row(code="001234", price="10", quantity="60", unit="ml", **kwargs):
    return ProductObservation(
        code,
        "Example",
        Decimal(price),
        False,
        source_quantity=Decimal(quantity) if quantity else None,
        source_unit_qty=unit,
        source_quantity_text=quantity,
        **kwargs,
    )


def catalog(store, *rows, published=NOW, conflicts=frozenset()):
    return ParsedCatalog(
        BranchIdentity("rami-levy", "001", store),
        "7290058140886",
        published,
        tuple(rows),
        0,
        0,
        0,
        conflicts,
    )


def test_averages_only_observed_branches_and_preserves_leading_zero_codes():
    result = aggregate_catalogs(
        (
            catalog("001", row(price="10"), row(code="only", price="8")),
            catalog("002", row(price="11")),
        ),
        chain_id="rami-levy",
    )
    products = {product.item_code: product for product in result.products}
    assert products["001234"].price == Decimal("10.5000")
    assert products["001234"].sample_count == 2
    assert products["only"].price == Decimal("8.0000")
    assert products["only"].sample_count == 1
    assert result.can_publish


def test_newest_catalog_metadata_keeps_source_pair_and_true_source_dates():
    old = catalog("001", row(quantity="1000", unit="ml"), published=NOW - timedelta(days=2))
    newer_row = replace(
        row(quantity="1", unit="ליטר"),
        name="Newer name",
        manufacturer="Maker",
        item_price_updated_at=NOW - timedelta(days=100),
    )
    new = catalog("002", newer_row)
    product = aggregate_catalogs((new, old), chain_id="rami-levy").products[0]
    assert product.name == "Newer name" and product.manufacturer == "Maker"
    assert (product.package_quantity, product.package_unit) == (Decimal(1000), "ml")
    assert (product.source_quantity, product.source_unit_qty) == (Decimal(1), "ליטר")
    assert product.source_updated_at == NOW - timedelta(days=2)
    assert product.newest_source_updated_at == NOW
    assert product.item_price_updated_at == NOW - timedelta(days=100)


def test_metadata_ties_use_branch_identity_order_independent_of_input_order():
    a, b = catalog("001", row()), catalog("002", replace(row(), name="Other name"))
    assert (
        aggregate_catalogs((b, a), chain_id="rami-levy").products
        == aggregate_catalogs((a, b), chain_id="rami-levy").products
    )
    assert aggregate_catalogs((b, a), chain_id="rami-levy").products[0].name == "Example"


def test_packaging_conflicts_and_intra_branch_conflicts_exclude_sku_for_entire_run():
    a = catalog("001", row(), row(code="blocked"), row(code="safe"))
    b = catalog("002", row(quantity="61"), row(code="safe"), conflicts=frozenset({"blocked"}))
    result = aggregate_catalogs((a, b), chain_id="rami-levy")
    assert [product.item_code for product in result.products] == ["safe"]
    assert result.conflict_count == 2


def test_unknown_package_is_searchable_once_but_empty_signatures_are_not_averaged():
    missing = row(quantity=None, unit=None)
    single = aggregate_catalogs((catalog("001", missing),), chain_id="rami-levy")
    assert single.products[0].package_quantity is None
    assert single.products[0].source_quantity is None
    multiple = aggregate_catalogs(
        (catalog("001", missing), catalog("002", missing)), chain_id="rami-levy"
    )
    assert not multiple.can_publish and multiple.conflict_count == 1


def test_zero_success_or_all_conflicts_cannot_be_published():
    result = aggregate_catalogs((), chain_id="rami-levy")
    assert not result.can_publish and result.successful_branch_count == 0


def test_duplicate_branch_cannot_inflate_samples():
    a = catalog("001", row())
    with pytest.raises(SourceError, match="DUPLICATE_BRANCH"):
        aggregate_catalogs((a, a), chain_id="rami-levy")


def test_invalid_aggregate_price_is_counted_without_poisoning_other_products():
    result = aggregate_catalogs(
        (catalog("001", row(price="0.000001"), row(code="safe")),), chain_id="rami-levy"
    )
    assert [product.item_code for product in result.products] == ["safe"]
    assert result.invalid_price_count == 1


def test_three_branch_mean_and_compatible_unknown_units():
    inputs = tuple(catalog(str(i), row(price=str(i), unit="box", quantity="1")) for i in (1, 2, 3))
    product = aggregate_catalogs(inputs, chain_id="rami-levy").products[0]
    assert product.sample_count == 3 and product.price == Decimal("2.0000")
    assert product.source_quantity is None and product.package_quantity is None


def test_duplicate_observations_inside_a_branch_are_rejected_even_if_parser_was_bypassed():
    with pytest.raises(SourceError, match="DUPLICATE_OBSERVATION"):
        aggregate_catalogs((catalog("001", row(), row()),), chain_id="rami-levy")


def test_branch_ceiling_and_mixed_chain_catalogs_are_rejected():
    with pytest.raises(SourceError, match="BRANCH_LIMIT"):
        aggregate_catalogs(tuple(catalog(str(i), row()) for i in range(4)), chain_id="rami-levy")
    other = replace(catalog("001", row()), branch=BranchIdentity("victory", "001", "001"))
    with pytest.raises(SourceError, match="MIXED_CHAINS"):
        aggregate_catalogs((other,), chain_id="rami-levy")


def test_sku_strings_are_not_canonicalized_or_fuzzily_merged():
    result = aggregate_catalogs(
        (catalog("001", row(code="001"), row(code="1")),), chain_id="rami-levy"
    )
    assert [product.item_code for product in result.products] == ["001", "1"]


def test_aggregation_summary_does_not_include_source_prices_or_product_dumps():
    import io
    import json

    from ingestor.logging import create_logger
    from ingestor.logging.transports import ConsoleTransport

    stream = io.StringIO()
    logger = create_logger(transport=ConsoleTransport(stream)).child(run_id="fixture-run")
    aggregate_catalogs(
        (catalog("001", row(code="private-sku", price="17.31")),),
        chain_id="rami-levy",
        logger=logger,
    )
    event = json.loads(stream.getvalue())
    assert event["fields"]["product_count"] == 1
    assert event["fields"]["run_id"] == "fixture-run"
    assert "private-sku" not in stream.getvalue() and "17.31" not in stream.getvalue()
