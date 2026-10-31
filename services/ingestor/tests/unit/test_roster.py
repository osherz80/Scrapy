from datetime import UTC, datetime

import pytest

from ingestor.providers.roster import parse_filename, parse_roster
from ingestor.providers.stream import SourceError
from ingestor.providers.types import BranchKind


def roster(stores, sub="001"):
    return (
        f"<Root><ChainId>7290058140886</ChainId><SubChains><SubChain>"
        f"<SubChainId>{sub}</SubChainId><Stores>{stores}</Stores>"
        "</SubChain></SubChains></Root>"
    ).encode()


def store(code="001", kind="1", extra=""):
    return f"<Store><StoreId>{code}</StoreId><StoreType>{kind}</StoreType>{extra}</Store>"


def parse(xml, **kwargs):
    return parse_roster(xml, chain_id="rami-levy", source_chain_id="7290058140886", **kwargs)


def test_numeric_types_include_physical_and_combined_but_exclude_online_unknown():
    branches = parse(
        roster("".join(store(str(i), kind) for i, kind in enumerate(("1", "2", "3", "", "9"))))
    )
    assert [branch.kind for branch in branches] == [
        BranchKind.PHYSICAL_GROCERY,
        BranchKind.ONLINE_ONLY,
        BranchKind.PHYSICAL_GROCERY,
        BranchKind.UNKNOWN,
        BranchKind.UNKNOWN,
    ]
    assert branches[0].identity.subchain_id == "001"


def test_documented_subchain_alias_is_explicit_and_cannot_merge_two_branches():
    assert parse(roster(store()), subchain_aliases={"1": "000"})[0].identity.subchain_id == "000"
    xml = (
        "<Root><ChainId>7290058140886</ChainId><Stores>"
        + store(extra="<SubChainId>1</SubChainId>")
        + store(extra="<SubChainId>0</SubChainId>")
        + "</Stores></Root>"
    ).encode()
    with pytest.raises(SourceError, match="INVALID_ROSTER"):
        parse(xml, subchain_aliases={"1": "000"})


@pytest.mark.parametrize(
    "xml",
    [
        roster(store() + store("1")),
        roster(store(extra="<StoreType>2</StoreType>")),
        roster(store(extra="<SubChainId>002</SubChainId>")),
        roster(store()).replace(b"7290058140886", b"7290000000000"),
        roster(store()).replace(b"</Root>", b"<bad>"),
        b'<!DOCTYPE Root [<!ENTITY x "secret">]><Root>&x;</Root>',
        b"<Root><ChainId>7290058140886</ChainId><Stores>" + store().encode() + b"</Stores></Root>",
        roster(""),
    ],
)
def test_ambiguous_unsafe_incomplete_rosters_fail_as_a_whole(xml):
    with pytest.raises(SourceError):
        parse(xml)


def test_flat_case_insensitive_namespaced_utf16_roster():
    xml = (
        '<Root xmlns="urn:test"><CHAINID>7290058140886</CHAINID><STORES><STORE>'
        "<STOREID>001</STOREID><SUBCHAINID>002</SUBCHAINID><STORETYPE>1</STORETYPE>"
        "</STORE></STORES></Root>"
    ).encode("utf-16")
    assert parse(xml)[0].identity.subchain_id == "002"


@pytest.mark.parametrize(
    "suffix,sub,store_id,expected",
    [
        ("001-007-20261031-063000", "001", "007", datetime(2026, 10, 31, 4, 30, tzinfo=UTC)),
        ("007-202610310630", None, "007", datetime(2026, 10, 31, 4, 30, tzinfo=UTC)),
        ("001-007-20261331-063000", "001", "007", None),
    ],
)
def test_price_filename_identity_and_true_israel_publication_time(suffix, sub, store_id, expected):
    ref = parse_filename(f"PriceFull7290058140886-{suffix}.gz")
    assert (ref.subchain_id, ref.store_id, ref.published_at) == (sub, store_id, expected)


def test_fourteen_digit_store_filename_and_duplicated_time():
    ref = parse_filename("Stores7290696200003-000-20261031060100-060100.gz")
    assert ref.published_at == datetime(2026, 10, 31, 4, 1, tzinfo=UTC)
    assert parse_filename("Price7290058140886-001-007-20261031-060000.gz") is None
    assert parse_filename("PriceFull7290058140886-../file.gz") is None


def test_catalog_accepts_branch_padding_only_and_keeps_exact_product_code():
    from ingestor.parsing import parse_catalog
    from ingestor.providers.types import BranchIdentity

    xml = (
        b"<Root><ChainId>7290058140886</ChainId><SubChainId>1</SubChainId>"
        b"<StoreId>7</StoreId><Items><Item><ItemCode>000123</ItemCode><ItemName>Example</ItemName>"
        b"<ItemPrice>1</ItemPrice><bIsWeighted>0</bIsWeighted></Item></Items></Root>"
    )
    parsed = parse_catalog(
        xml,
        branch=BranchIdentity("rami-levy", "001", "007"),
        expected_source_chain_id="7290058140886",
        published_at=datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert parsed.products[0].item_code == "000123"
    with pytest.raises(SourceError, match="IDENTITY_MISMATCH"):
        parse_catalog(
            xml.replace(b"<SubChainId>1", b"<SubChainId>0"),
            branch=parsed.branch,
            expected_source_chain_id="7290058140886",
            published_at=parsed.source_updated_at,
        )
