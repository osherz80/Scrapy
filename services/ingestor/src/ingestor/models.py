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
