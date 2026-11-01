from datetime import UTC, datetime

import pytest

from ingestor.providers.types import BranchIdentity
from ingestor.xml_items import aggregate_xml_catalogs, parse_xml_catalog

ITEM = """<Item>
<PriceUpdateTime>2024-03-14T12:55:50.000</PriceUpdateTime>
<ItemCode>7290119371129</ItemCode>
<LastSaleDateTime>2026-10-31T15:06:12.000</LastSaleDateTime>
<ItemType>1</ItemType><ItemName>חטיף חלבון פרו שוקול</ItemName>
<ManufactureName>MIESZKO S.A - MS. JO</ManufactureName>
<ManufactureCountry>לא ידוע</ManufactureCountry>
<ManufactureItemDescription>חטיף חלבון פרו שוקולד לבן עוגיות 60 גר</ManufactureItemDescription>
<UnitQty>גרם</UnitQty><Quantity>60.00</Quantity>
<UnitOfMeasure>100 גרם</UnitOfMeasure><bIsWeighted>0</bIsWeighted>
<QtyInPackage>12</QtyInPackage><ItemPrice>12.90</ItemPrice>
<UnitOfMeasurePrice>21.50</UnitOfMeasurePrice>
<AllowDiscount>1</AllowDiscount><ItemStatus/>
</Item>"""


def catalog(item=ITEM, store="001", published=None):
    xml = (
        f"<Root><ChainId>7290000000000</ChainId><SubChainId>001</SubChainId>"
        f"<StoreId>{store}</StoreId><Items>{item}</Items></Root>"
    ).encode()
    return parse_xml_catalog(
        xml,
        branch=BranchIdentity("keshet-teamim", "001", store),
        expected_source_chain_id="7290000000000",
        published_at=published or datetime(2026, 10, 31, 22, 10, tzinfo=UTC),
    )


def test_supplied_keshet_item_is_preserved_without_normalization():
    result = aggregate_xml_catalogs([catalog()], chain_id="keshet-teamim")
    row = result.products[0]
    assert row.item_code == "7290119371129"
    assert row.fields["quantity"] == "60.00"
    assert row.fields["unit_qty"] == "גרם"
    assert row.fields["qty_in_package"] == "12"
    assert row.fields["unit_of_measure"] == "100 גרם"
    assert row.fields["unit_of_measure_price"] == "21.50"
    assert row.fields["manufacture_item_description"] == "חטיף חלבון פרו שוקולד לבן עוגיות 60 גר"
    assert row.fields["price_update_time"] == "2024-03-14T12:55:50.000"
    assert row.fields["item_status"] == ""
    assert row.fields["item_price"] == "12.90"


def test_price_is_averaged_but_all_other_fields_come_from_one_branch():
    first = catalog(store="002")
    second = catalog(ITEM.replace("12.90", "14.90").replace("60.00", "90.00"), store="001")
    result = aggregate_xml_catalogs([first, second], chain_id="keshet-teamim")
    row = result.products[0]
    assert row.fields["item_price"] == "13.9000"
    assert row.fields["quantity"] == "90.00"
    assert row.fields["unit_of_measure_price"] == "21.50"
    assert row.sample_count == 2


def test_unknown_fields_whitespace_empty_values_and_bad_prices_are_not_dropped():
    item = ITEM.replace("12.90", "not-a-number").replace(
        "<ItemStatus/>", "<ItemStatus/><NewRetailerField>  untouched  </NewRetailerField>"
    )
    row = aggregate_xml_catalogs([catalog(item)], chain_id="keshet-teamim").products[0]
    assert row.fields["item_price"] == "not-a-number"
    assert row.fields["new_retailer_field"] == "  untouched  "
    assert row.fields["item_status"] == ""


def test_missing_optional_values_do_not_remove_the_item():
    row = aggregate_xml_catalogs(
        [catalog("<Item><ItemCode>0001</ItemCode></Item>")], chain_id="keshet-teamim"
    ).products[0]
    assert row.fields == {"item_code": "0001"}


@pytest.mark.parametrize("suffix", ["<broken>", "</extra>"])
def test_malformed_tail_cannot_publish_partial_items(suffix):
    from ingestor.providers.stream import SourceError

    with pytest.raises(SourceError, match="INVALID_CATALOG"):
        catalog(ITEM + suffix)


def test_newest_branch_metadata_is_preserved_as_one_coherent_item():
    old = catalog(store="001")
    new = catalog(
        ITEM.replace("60.00", "999.00"), store="002", published=datetime(2026, 11, 1, tzinfo=UTC)
    )
    row = aggregate_xml_catalogs([old, new], chain_id="keshet-teamim").products[0]
    assert row.selected_branch.store_id == "002"
    assert row.fields["quantity"] == "999.00"


def test_alternate_xml_names_use_only_the_canonical_columns():
    item = (
        ITEM.replace("ManufactureName", "ManufacturerName")
        .replace("bIsWeighted", "blsWeighted")
        .replace("PriceUpdateTime", "PriceUpdateDate")
    )
    row = aggregate_xml_catalogs([catalog(item)], chain_id="keshet-teamim").products[0]
    assert row.fields["manufacture_name"] == "MIESZKO S.A - MS. JO"
    assert row.fields["b_is_weighted"] == "0"
    assert row.fields["price_update_time"] == "2024-03-14T12:55:50.000"
    assert {"manufacturer_name", "bls_weighted", "price_update_date"}.isdisjoint(row.fields)


def test_explicit_canonical_value_wins_over_an_alternate_field():
    item = ITEM.replace("<ItemStatus/>", "<ItemStatus/><ManufacturerName>Other</ManufacturerName>")
    row = aggregate_xml_catalogs([catalog(item)], chain_id="keshet-teamim").products[0]
    assert row.fields["manufacture_name"] == "MIESZKO S.A - MS. JO"
