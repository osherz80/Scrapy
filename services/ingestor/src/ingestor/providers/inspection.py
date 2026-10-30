"""Secure feasibility inspection, not production reconciliation or publication."""

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError
from zoneinfo import ZoneInfo

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

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


def _source_time(value: datetime | None) -> datetime:
    if value is None:
        raise SourceError("MISSING_SOURCE_TIME")
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    zone = ZoneInfo("Asia/Jerusalem")
    candidates = {
        value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if value.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == value
    }
    if len(candidates) != 1:
        raise SourceError("AMBIGUOUS_SOURCE_TIME")
    return candidates.pop()


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
    published = _source_time(published_at)
    headers: dict[str, str] = {}
    stack: list[str] = []
    first: ProbeProduct | None = None
    valid = invalid = package_rows = 0
    items_container = None
    try:
        events = ElementTree.iterparse(
            io.BytesIO(xml),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for event, element in events:
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if event == "start":
                stack.append(tag)
                if tag == "items":
                    items_container = element
                continue
            if len(stack) == 2 and tag in ("chainid", "subchainid", "storeid"):
                headers[tag] = (element.text or "").strip()
            if tag == "item" and len(stack) >= 2 and stack[-2] == "items":
                fields = {
                    child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip()
                    for child in element
                }
                price = _positive(fields.get("itemprice"))
                code, name = fields.get("itemcode"), fields.get("itemname") or fields.get("itemnm")
                if price is not None and code and name:
                    quantity, unit = (
                        _positive(fields.get("quantity")),
                        fields.get("unitqty") or None,
                    )
                    package_rows += int(quantity is not None and unit is not None)
                    valid += 1
                    if first is None:
                        first = ProbeProduct(code, name, price, quantity, unit)
                else:
                    invalid += 1
                element.clear()
                if items_container is not None:
                    items_container.remove(element)
            stack.pop()
    except (ParseError, DefusedXmlException, ValueError):
        raise SourceError("INVALID_CATALOG") from None
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
