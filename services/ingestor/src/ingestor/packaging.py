"""Package dimensions from published quantity/unit fields, never product names."""

from dataclasses import dataclass, field
from decimal import Decimal, DecimalException

from .models import ProductObservation

_UNITS: dict[str, tuple[str, int]] = {
    **dict.fromkeys(("ml", "מיליליטר", "מיליליטרים", 'מ"ל', "מ״ל"), ("ml", 0)),
    **dict.fromkeys(("l", "liter", "litre", "ליטר", "ליטרים"), ("ml", 3)),
    **dict.fromkeys(("g", "gram", "grams", "גרם", "גר'"), ("g", 0)),
    **dict.fromkeys(("kg", "קילוגרם", "קילוגרמים", 'ק"ג', "ק״ג", "קג"), ("g", 3)),
    **dict.fromkeys(("unit", "units", "piece", "pcs", "יחידה", "יחידות", "יח'"), ("unit", 0)),
}


@dataclass(frozen=True)
class NormalizedPackage:
    quantity: Decimal | None
    unit: str | None
    source_quantity: Decimal | None
    source_unit_qty: str | None
    is_weighted: bool
    _source_signature: tuple[Decimal | None, str | None] = field(repr=False)


def normalize_package(row: ProductObservation) -> NormalizedPackage:
    raw_unit = " ".join((row.source_unit_qty or "").split()).casefold() or None
    quantity = row.source_quantity
    if quantity is not None and (not quantity.is_finite() or quantity <= 0):
        quantity = None
    signature = (quantity, raw_unit)
    known = _UNITS.get(raw_unit) if raw_unit else None
    if quantity is not None and known is not None:
        unit, power = known
        parts = quantity.as_tuple()
        try:
            # Exact powers of 1000 without decimal-context rounding of dimensions.
            normalized = Decimal((parts.sign, parts.digits, parts.exponent + power))
        except DecimalException:
            normalized = None
        if normalized is not None:
            return NormalizedPackage(
                normalized, unit, quantity, row.source_unit_qty, row.is_weighted, signature
            )
    return NormalizedPackage(None, None, None, None, row.is_weighted, signature)


def compatible_packages(a: NormalizedPackage, b: NormalizedPackage) -> bool:
    if a.is_weighted != b.is_weighted:
        return False
    if a.quantity is not None and b.quantity is not None:
        return (a.quantity, a.unit) == (b.quantity, b.unit)
    if a.quantity is not None or b.quantity is not None:
        return False
    # Unknown units may agree only through a complete published quantity/unit
    # signature. Empty signatures do not establish that two packages are alike.
    if any(value is None for value in a._source_signature + b._source_signature):
        return False
    return a._source_signature == b._source_signature
