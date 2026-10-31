"""Transient validated catalog data; no raw XML or persistence behavior."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .providers.types import BranchIdentity


@dataclass(frozen=True, slots=True, repr=False)
class ProductObservation:
    item_code: str
    name: str
    price: Decimal
    is_weighted: bool
    manufacturer: str | None = None
    source_quantity: Decimal | None = None
    source_unit_qty: str | None = None
    source_quantity_text: str | None = None
    unit_of_measure: str | None = None
    qty_in_package: Decimal | None = None
    item_type: str | None = None
    item_price_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ParsedCatalog:
    branch: BranchIdentity
    source_chain_id: str
    source_updated_at: datetime
    products: tuple[ProductObservation, ...] = field(repr=False)
    invalid_row_count: int
    duplicate_row_count: int
    missing_package_count: int
    conflicting_codes: frozenset[str] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.products:
            raise ValueError("Parsed catalog must be nonempty")


@dataclass(frozen=True, slots=True, repr=False)
class AggregatedProduct:
    chain_id: str
    item_code: str
    name: str
    manufacturer: str | None
    price: Decimal
    sample_count: int
    is_weighted: bool
    package_quantity: Decimal | None
    package_unit: str | None
    source_quantity: Decimal | None
    source_unit_qty: str | None
    item_price_updated_at: datetime | None
    source_updated_at: datetime
    newest_source_updated_at: datetime
    normalized_name: str
    name_tokens: tuple[str, ...]
    currency: str = "ILS"


@dataclass(frozen=True, slots=True)
class AggregationResult:
    chain_id: str
    products: tuple[AggregatedProduct, ...] = field(repr=False)
    successful_branch_count: int
    conflict_count: int
    invalid_price_count: int
    invalid_row_count: int
    duplicate_row_count: int
    missing_package_count: int

    @property
    def can_publish(self) -> bool:
        return self.successful_branch_count > 0 and bool(self.products)

    @property
    def source_updated_at(self) -> datetime | None:
        return min((product.source_updated_at for product in self.products), default=None)
