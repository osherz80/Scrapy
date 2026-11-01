"""Source-text item storage. Only the cross-branch ItemPrice is calculated."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext

from .chains import DEFERRED_CHAIN_IDS
from .logging.types import Logger
from .providers.stream import SourceError
from .providers.types import BranchIdentity, identifier_key
from .timestamps import source_timestamp
from .xml_catalog import iter_price_items

XML_COLUMNS = (
    "price_update_time",
    "item_code",
    "last_sale_date_time",
    "item_type",
    "item_name",
    "manufacture_name",
    "manufacture_country",
    "manufacture_item_description",
    "unit_qty",
    "quantity",
    "unit_of_measure",
    "b_is_weighted",
    "qty_in_package",
    "item_price",
    "unit_of_measure_price",
    "allow_discount",
    "item_status",
    "is_weighted",
)


@dataclass(frozen=True, slots=True)
class XmlCatalog:
    branch: BranchIdentity
    source_chain_id: str
    source_updated_at: datetime
    products: tuple[dict[str, str], ...] = field(repr=False)
    invalid_row_count: int = 0
    duplicate_row_count: int = 0
    missing_package_count: int = 0
    conflicting_codes: frozenset[str] = field(default_factory=frozenset, repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class XmlProduct:
    chain_id: str
    item_code: str
    fields: dict[str, str]
    sample_count: int
    selected_branch: BranchIdentity

    @property
    def price(self) -> Decimal | None:
        try:
            return Decimal(self.fields.get("item_price", ""))
        except DecimalException:
            return None


@dataclass(frozen=True, slots=True)
class XmlAggregation:
    chain_id: str
    products: tuple[XmlProduct, ...] = field(repr=False)
    successful_branch_count: int
    source_updated_at: datetime | None
    conflict_count: int = 0
    invalid_price_count: int = 0
    invalid_row_count: int = 0
    duplicate_row_count: int = 0
    missing_package_count: int = 0

    @property
    def can_publish(self) -> bool:
        return bool(self.products) and self.successful_branch_count > 0


def parse_xml_catalog(
    xml: bytes,
    *,
    branch: BranchIdentity,
    expected_source_chain_id: str,
    published_at: datetime | None,
    max_bytes: int = 100_000_000,
) -> XmlCatalog:
    if branch.chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    headers = {}
    items = tuple(iter_price_items(xml, headers, max_bytes=max_bytes, preserve_source=True))
    for fields in items:
        for alternate, canonical in (
            ("manufacturer_name", "manufacture_name"),
            ("bls_weighted", "b_is_weighted"),
            ("price_update_date", "price_update_time"),
        ):
            if alternate in fields:
                fields.setdefault(canonical, fields.pop(alternate))
    if not all(headers.get(k) for k in ("chainid", "subchainid", "storeid")):
        raise SourceError("MISSING_IDENTITY")
    if (
        headers["chainid"],
        identifier_key(headers["subchainid"]),
        identifier_key(headers["storeid"]),
    ) != (
        expected_source_chain_id,
        identifier_key(branch.subchain_id),
        identifier_key(branch.store_id),
    ):
        raise SourceError("IDENTITY_MISMATCH")
    if not items:
        raise SourceError("EMPTY_CATALOG")
    # No row is silently discarded. Missing barcode/duplicate XML fields are
    # structural errors: fail the document rather than invent an identity/value.
    if any(not row.get("item_code") or "__ambiguous_row__" in row for row in items):
        raise SourceError("INVALID_ITEM_IDENTITY")
    return XmlCatalog(
        branch,
        expected_source_chain_id,
        source_timestamp(published_at),
        items,
        duplicate_row_count=len(items) - len({row["item_code"] for row in items}),
        missing_package_count=sum("quantity" not in r or "unit_qty" not in r for r in items),
    )


def _mean_text(rows: Sequence[dict[str, str]]) -> str | None:
    if len(rows) == 1:
        return rows[0].get("item_price")
    try:
        prices = [Decimal(row.get("item_price", "")) for row in rows]
        if any(
            not p.is_finite()
            or len(p.as_tuple().digits) > 1000
            or abs(p.as_tuple().exponent) > 1000
            for p in prices
        ):
            return rows[0].get("item_price")
        with localcontext() as context:
            context.prec = max(
                40,
                max(p.adjusted() for p in prices)
                + max(0, max(-p.as_tuple().exponent for p in prices))
                + 12,
            )
            return format(
                (sum(prices) / len(prices)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f"
            )
    except DecimalException:
        # Preserve the selected XML value when averaging isn't meaningful.
        return rows[0].get("item_price")


def aggregate_xml_catalogs(
    catalogs: Sequence[XmlCatalog], *, chain_id: str, logger: Logger | None = None
) -> XmlAggregation:
    if chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    if len(catalogs) > 3 or len({c.branch for c in catalogs}) != len(catalogs):
        raise SourceError("INVALID_SAMPLE_COUNT")
    if any(c.branch.chain_id != chain_id for c in catalogs):
        raise SourceError("MIXED_CHAINS")
    if len({c.source_chain_id for c in catalogs}) > 1:
        raise SourceError("MIXED_SOURCE_CHAINS")
    if any(c.source_updated_at.utcoffset() is None for c in catalogs):
        raise SourceError("INVALID_SOURCE_TIME")
    ordered = sorted(catalogs, key=lambda c: c.branch)
    ordered.sort(key=lambda c: c.source_updated_at, reverse=True)
    grouped: dict[str, list[tuple[BranchIdentity, dict[str, str]]]] = {}
    for catalog in ordered:
        seen = set()
        for fields in catalog.products:
            code = fields["item_code"]
            if code in seen:
                continue  # One contribution per branch; first XML occurrence wins.
            seen.add(code)
            grouped.setdefault(code, []).append((catalog.branch, fields))
    products = []
    for code, contributions in sorted(grouped.items()):
        fields = dict(contributions[0][1])
        mean = _mean_text([r for _, r in contributions])
        if mean is not None:
            fields["item_price"] = mean
        products.append(XmlProduct(chain_id, code, fields, len(contributions), contributions[0][0]))
    result = XmlAggregation(
        chain_id,
        tuple(products),
        len(catalogs),
        min((c.source_updated_at for c in catalogs), default=None),
        duplicate_row_count=sum(c.duplicate_row_count for c in catalogs),
        missing_package_count=sum(c.missing_package_count for c in catalogs),
    )
    if logger:
        logger.child(chain_id=chain_id).info(
            "aggregation.finished",
            "XML items collected; only ItemPrice averaged",
            product_count=len(products),
            successful_branch_count=len(catalogs),
            duplicate_row_count=result.duplicate_row_count,
            can_publish=result.can_publish,
        )
    return result
