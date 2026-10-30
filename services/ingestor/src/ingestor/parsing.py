"""Convert an entire secure PriceFull document into validated transient rows."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .chains import DEFERRED_CHAIN_IDS
from .models import ParsedCatalog, ProductObservation
from .providers.stream import SourceError
from .providers.types import BranchIdentity
from .timestamps import source_timestamp
from .xml_catalog import iter_price_items


def _decimal(value: str | None, *, allow_zero: bool = False) -> Decimal | None:
    try:
        result = Decimal(value or "")
        if result.is_finite() and (result >= 0 if allow_zero else result > 0):
            return result
    except InvalidOperation:
        pass
    return None


def _pick(fields: Mapping[str, str], *names: str) -> str | None:
    return next((fields[name] for name in names if fields.get(name)), None)


def _item_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return source_timestamp(datetime.fromisoformat(value))
    except (ValueError, SourceError):
        return None


def _observation(fields: Mapping[str, str]) -> ProductObservation | None:
    price = _decimal(fields.get("itemprice"))
    code, name = fields.get("itemcode"), _pick(fields, "itemname", "itemnm")
    weighted = _pick(fields, "bisweighted", "isweighted", "blsweighted")
    if not code or not name or price is None or weighted not in ("0", "1"):
        return None
    if "__ambiguous_row__" in fields:
        return None
    return ProductObservation(
        item_code=code,
        name=name,
        price=price,
        is_weighted=weighted == "1",
        manufacturer=_pick(fields, "manufacturename", "manufacturername"),
        source_quantity=_decimal(fields.get("quantity")),
        source_unit_qty=_pick(fields, "unitqty"),
        source_quantity_text=_pick(fields, "quantity"),
        unit_of_measure=_pick(fields, "unitofmeasure"),
        qty_in_package=_decimal(fields.get("qtyinpackage"), allow_zero=True),
        item_type=_pick(fields, "itemtype"),
        item_price_updated_at=_item_time(_pick(fields, "priceupdatetime", "priceupdatedate")),
    )


def parse_catalog(
    xml: bytes,
    *,
    branch: BranchIdentity,
    expected_source_chain_id: str,
    published_at: datetime | None,
    max_bytes: int = 100_000_000,
) -> ParsedCatalog:
    if branch.chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    published = source_timestamp(published_at)
    headers: dict[str, str] = {}
    products: dict[str, ProductObservation] = {}
    conflicts: set[str] = set()
    invalid = duplicates = 0
    # No products are returned until the iterator has validated the document tail.
    for fields in iter_price_items(xml, headers, max_bytes=max_bytes):
        row = _observation(fields)
        if row is None:
            invalid += 1
            continue
        if row.item_code in conflicts:
            duplicates += 1
            continue
        previous = products.get(row.item_code)
        if previous is not None:
            duplicates += 1
            if previous != row:
                conflicts.add(row.item_code)
                del products[row.item_code]
            continue
        products[row.item_code] = row
    if not all(headers.get(key) for key in ("chainid", "subchainid", "storeid")):
        raise SourceError("MISSING_IDENTITY")
    if (headers["chainid"], headers["subchainid"], headers["storeid"]) != (
        expected_source_chain_id,
        branch.subchain_id,
        branch.store_id,
    ):
        raise SourceError("IDENTITY_MISMATCH")
    if not products:
        raise SourceError("EMPTY_CATALOG")
    rows = tuple(products.values())
    return ParsedCatalog(
        branch=branch,
        source_chain_id=expected_source_chain_id,
        source_updated_at=published,
        products=rows,
        invalid_row_count=invalid,
        duplicate_row_count=duplicates,
        missing_package_count=sum(
            row.source_quantity is None or row.source_unit_qty is None for row in rows
        ),
        conflicting_codes=frozenset(conflicts),
    )
