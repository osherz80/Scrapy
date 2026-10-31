from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ingestor.providers.inspection import inspect_catalog
from ingestor.providers.stream import SourceError


def catalog(items: str, header: str = "") -> bytes:
    return (
        "<Root><ChainId>7290027600007</ChainId><SubChainId>001</SubChainId>"
        f"<StoreId>001</StoreId>{header}<Items>{items}</Items></Root>"
    ).encode()


ITEM = (
    "<Item><ItemCode>001234</ItemCode><ItemName>Test product</ItemName>"
    "<ItemPrice>10.90</ItemPrice><UnitQty>מיליליטר</UnitQty><Quantity>60</Quantity>"
    "<QtyInPackage>0</QtyInPackage><ItemStatus/></Item>"
)
PUBLISHED = datetime(2026, 10, 30, 6)


def test_secure_inspection_preserves_identity_decimal_and_source_pair():
    result = inspect_catalog(catalog(ITEM), published_at=PUBLISHED)
    assert (result.chain_id, result.subchain_id, result.store_id) == ("7290027600007", "001", "001")
    assert result.published_at == datetime(2026, 10, 30, 4, tzinfo=UTC)
    assert result.valid_rows == 1
    assert result.invalid_rows == 0
    assert result.first_product.item_code == "001234"
    assert result.first_product.price == Decimal("10.90")
    assert result.first_product.source_quantity == Decimal("60")
    assert result.first_product.source_unit_qty == "מיליליטר"
    assert "001234" not in repr(result)


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "bad"])
def test_catalog_with_no_valid_price_identity_fails(price):
    with pytest.raises(SourceError, match="EMPTY_CATALOG"):
        inspect_catalog(catalog(ITEM.replace("10.90", price)), published_at=PUBLISHED)


def test_invalid_rows_are_counted_without_losing_other_valid_rows():
    result = inspect_catalog(catalog(ITEM + ITEM.replace("10.90", "0")), published_at=PUBLISHED)
    assert (result.valid_rows, result.invalid_rows) == (1, 1)


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE Root [<!ENTITY x "secret">]><Root><Items>&x;</Items></Root>',
        b"<Root><Items><Item>",
        b"<Root/>",
    ],
)
def test_unsafe_malformed_or_empty_catalogs_fail(payload):
    with pytest.raises(SourceError):
        inspect_catalog(payload, published_at=PUBLISHED)


def test_truncated_tail_invalidates_previously_parsed_rows():
    with pytest.raises(SourceError, match="INVALID_CATALOG"):
        inspect_catalog(catalog(ITEM)[:-5], published_at=PUBLISHED)


def test_missing_or_conflicting_source_identity_is_not_accepted():
    with pytest.raises(SourceError, match="IDENTITY_MISMATCH"):
        inspect_catalog(catalog(ITEM), published_at=PUBLISHED, expected_chain="other")
    with pytest.raises(SourceError, match="MISSING_IDENTITY"):
        inspect_catalog(
            catalog(ITEM).replace(b"<StoreId>001</StoreId>", b""), published_at=PUBLISHED
        )


def test_missing_catalog_time_is_not_replaced_by_ingestion_or_item_time():
    with pytest.raises(SourceError, match="MISSING_SOURCE_TIME"):
        inspect_catalog(catalog(ITEM), published_at=None)


def test_ambiguous_local_source_time_is_not_guessed():
    with pytest.raises(SourceError, match="AMBIGUOUS_SOURCE_TIME"):
        inspect_catalog(catalog(ITEM), published_at=datetime(2026, 10, 25, 1, 30))
