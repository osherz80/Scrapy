"""Secure feasibility inspection, not production reconciliation or publication."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ..timestamps import source_timestamp
from ..xml_catalog import iter_price_items
from .stream import SourceError


@dataclass(frozen=True, repr=False)
class ProbeProduct:
    item_code: str
    name: str
    price: Decimal
    source_quantity: Decimal | None
    source_unit_qty: str | None


@dataclass(frozen=True)
class CatalogSummary:
    chain_id: str
    subchain_id: str
    store_id: str
    published_at: datetime
    valid_rows: int
    invalid_rows: int
    package_rows: int
    first_product: ProbeProduct = field(repr=False)


def _positive(value: str | None) -> Decimal | None:
    try:
        result = Decimal(value or "")
        return result if result.is_finite() and result > 0 else None
    except InvalidOperation:
        return None


def inspect_catalog(
    xml: bytes,
    *,
    published_at: datetime | None,
    expected_chain: str | None = None,
) -> CatalogSummary:
    published = source_timestamp(published_at)
    headers: dict[str, str] = {}
    first: ProbeProduct | None = None
    valid = invalid = package_rows = 0
    for fields in iter_price_items(xml, headers):
        price = _positive(fields.get("itemprice"))
        code, name = fields.get("itemcode"), fields.get("itemname") or fields.get("itemnm")
        if price is not None and code and name and "__ambiguous_row__" not in fields:
            quantity, unit = _positive(fields.get("quantity")), fields.get("unitqty") or None
            package_rows += int(quantity is not None and unit is not None)
            valid += 1
            if first is None:
                first = ProbeProduct(code, name, price, quantity, unit)
        else:
            invalid += 1
    if not all(headers.get(key) for key in ("chainid", "subchainid", "storeid")):
        raise SourceError("MISSING_IDENTITY")
    if expected_chain is not None and headers["chainid"] != expected_chain:
        raise SourceError("IDENTITY_MISMATCH")
    if first is None:
        raise SourceError("EMPTY_CATALOG")
    return CatalogSummary(
        headers["chainid"],
        headers["subchainid"],
        headers["storeid"],
        published,
        valid,
        invalid,
        package_rows,
        first,
    )
