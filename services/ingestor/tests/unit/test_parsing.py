from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ingestor.parsing import parse_catalog
from ingestor.providers.stream import SourceError
from ingestor.providers.types import BranchIdentity

BRANCH = BranchIdentity("rami-levy", "001", "007")
SOURCE = "7290058140886"
PUBLISHED = datetime(2026, 10, 30, 6)


def item(code="001234", price="10.90", weighted="0", extra=""):
    return (
        f"<Item><ItemCode>{code}</ItemCode><ItemName>Example 60 ml</ItemName>"
        f"<ItemPrice>{price}</ItemPrice><bIsWeighted>{weighted}</bIsWeighted>{extra}</Item>"
    )


def xml(items, *, store="007", subchain="001", extra_header=""):
    return (
        f"<Root><ChainId>{SOURCE}</ChainId><SubChainId>{subchain}</SubChainId>"
        f"<StoreId>{store}</StoreId>{extra_header}<Items>{items}</Items></Root>"
    ).encode()


def parse(payload):
    return parse_catalog(
        payload, branch=BRANCH, expected_source_chain_id=SOURCE, published_at=PUBLISHED
    )


def test_decimal_identity_optional_fields_and_distinct_source_times():
    result = parse(
        xml(
            item(
                extra="<Quantity>60</Quantity><UnitQty>מיליליטר</UnitQty>"
                "<PriceUpdateTime>2026-05-10 10:30:00</PriceUpdateTime>"
                "<LastSaleDateTime>2026-10-30 12:00:00</LastSaleDateTime>"
                "<UnitOfMeasure>100 מיליליטר</UnitOfMeasure>"
                "<QtyInPackage>0</QtyInPackage><ItemStatus/>"
            )
        )
    )
    row = result.products[0]
    assert row.item_code == "001234"
    assert row.price == Decimal("10.90")
    assert row.source_quantity == Decimal(60)
    assert row.source_unit_qty == "מיליליטר"
    assert row.qty_in_package == Decimal(0)
    assert row.manufacturer is None
    assert row.is_weighted is False
    assert row.item_price_updated_at == datetime(2026, 5, 10, 7, 30, tzinfo=UTC)
    assert result.source_updated_at == datetime(2026, 10, 30, 4, tzinfo=UTC)
    assert "10.90" not in repr(result)


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "invalid"])
def test_invalid_rows_are_skipped_without_losing_valid_rows(price):
    result = parse(xml(item(code="bad", price=price) + item()))
    assert result.invalid_row_count == 1
    assert [row.item_code for row in result.products] == ["001234"]


@pytest.mark.parametrize("weighted", ["", "true", "2"])
def test_unknown_weighting_is_not_guessed_as_sold_by_unit(weighted):
    with pytest.raises(SourceError, match="EMPTY_CATALOG"):
        parse(xml(item(weighted=weighted)))


def test_missing_dimensions_stay_unknown_without_name_guessing():
    result = parse(xml(item()))
    row = result.products[0]
    assert row.source_quantity is None and row.source_unit_qty is None
    assert result.missing_package_count == 1


def test_identical_duplicates_count_only_once():
    result = parse(xml(item() + item()))
    assert len(result.products) == 1
    assert result.duplicate_row_count == 1
    assert not result.conflicting_codes


def test_conflicting_duplicate_sku_is_excluded_and_carried_to_reconciliation():
    result = parse(xml(item() + item(price="20.90") + item(code="safe")))
    assert [row.item_code for row in result.products] == ["safe"]
    assert result.conflicting_codes == frozenset({"001234"})


@pytest.mark.parametrize(
    "payload", [xml(item())[:-5], b'<!DOCTYPE Root [<!ENTITY x "secret">]><Root>&x;</Root>']
)
def test_malformed_tail_or_entities_never_return_partial_products(payload):
    with pytest.raises(SourceError, match="INVALID_CATALOG"):
        parse(payload)


@pytest.mark.parametrize("store,subchain", [("008", "001"), ("007", "002")])
def test_composite_source_identity_must_match_the_selected_branch(store, subchain):
    with pytest.raises(SourceError, match="IDENTITY_MISMATCH"):
        parse(xml(item(), store=store, subchain=subchain))


def test_catalog_time_must_come_from_verified_publication_metadata():
    with pytest.raises(SourceError, match="MISSING_SOURCE_TIME"):
        parse_catalog(
            xml(item()), branch=BRANCH, expected_source_chain_id=SOURCE, published_at=None
        )


def test_direct_parser_call_also_enforces_decompressed_size_limit():
    with pytest.raises(SourceError, match="SIZE_LIMIT"):
        parse_catalog(
            xml(item()),
            branch=BRANCH,
            expected_source_chain_id=SOURCE,
            published_at=PUBLISHED,
            max_bytes=10,
        )


def test_namespaced_utf16_catalog_and_verified_field_aliases():
    text = xml(item(weighted="1", extra="<ManufacturerName>Maker</ManufacturerName>")).decode()
    text = (
        text.replace("<Root>", '<Root xmlns="urn:prices">')
        .replace("ItemName", "ItemNm")
        .replace("bIsWeighted", "BlsWeighted")
    )
    row = parse(text.encode("utf-16")).products[0]
    assert row.is_weighted is True
    assert row.manufacturer == "Maker"


def test_conflicting_header_is_not_overwritten_silently():
    with pytest.raises(SourceError, match="AMBIGUOUS_HEADER"):
        parse(xml(item(), extra_header="<StoreId>other</StoreId>"))


def test_duplicate_row_fields_are_invalid_instead_of_last_value_winning():
    result = parse(xml(item(code="unsafe", extra="<ItemPrice>999</ItemPrice>") + item()))
    assert result.invalid_row_count == 1
    assert [row.item_code for row in result.products] == ["001234"]


def test_bad_item_date_is_nullable_and_does_not_reset_catalog_freshness():
    result = parse(xml(item(extra="<PriceUpdateTime>invalid</PriceUpdateTime>")))
    assert result.products[0].item_price_updated_at is None
    assert result.source_updated_at == datetime(2026, 10, 30, 4, tzinfo=UTC)


def test_spec_tabasco_fields_keep_two_skus_and_the_actual_sixty_ml_pair():
    # Synthetic regression reconstructed from the spec, not a retained portal file.
    fields = (
        "<Quantity>60</Quantity><UnitQty>מיליליטר</UnitQty>"
        "<UnitOfMeasure>100 מיליליטר</UnitOfMeasure><QtyInPackage>0</QtyInPackage>"
    )
    result = parse(
        xml(item(code="11210000094", extra=fields) + item(code="11210007253", extra=fields))
    )
    assert len(result.products) == 2
    assert {row.item_code for row in result.products} == {"11210000094", "11210007253"}
    assert all(
        row.source_quantity == 60 and row.source_unit_qty == "מיליליטר" for row in result.products
    )
    assert all(row.unit_of_measure == "100 מיליליטר" for row in result.products)
