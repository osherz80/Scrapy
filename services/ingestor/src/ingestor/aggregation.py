"""Current-catalog reconciliation using at most three distinct branch observations."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from .chains import DEFERRED_CHAIN_IDS
from .logging.types import Logger
from .models import AggregatedProduct, AggregationResult, ParsedCatalog, ProductObservation
from .normalization import normalize_name, tokenize
from .packaging import compatible_packages, normalize_package
from .providers.stream import SourceError

_QUANTUM = Decimal("0.0001")
_MAX_PRICE = Decimal("9999999999.9999")
_MAX_NUMERIC_DIGITS = 1000


def average_price(prices: Sequence[Decimal]) -> Decimal:
    if not 1 <= len(prices) <= 3:
        raise SourceError("INVALID_SAMPLE_COUNT")
    if any(not price.is_finite() or price <= 0 for price in prices):
        raise SourceError("INVALID_PRICE")
    # Bound hostile exponent/coefficient work; fail the product rather than
    # approximate its contribution or allocate an arbitrarily large context.
    if any(
        len(price.as_tuple().digits) > _MAX_NUMERIC_DIGITS
        or abs(price.as_tuple().exponent) > _MAX_NUMERIC_DIGITS
        for price in prices
    ):
        raise SourceError("NUMERIC_LIMIT")
    scale = max(0, max(-price.as_tuple().exponent for price in prices))
    precision = max(40, max(price.adjusted() for price in prices) + scale + 12)
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_UP)):
        # With <=3 finite decimal operands, these guard digits also keep a
        # repeating quotient from crossing a four-place half-way boundary.
        result = (sum(prices, Decimal(0)) / len(prices)).quantize(
            _QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    if result <= 0 or result > _MAX_PRICE:
        raise SourceError("INVALID_AGGREGATE_PRICE")
    return result


def aggregate_catalogs(
    catalogs: Sequence[ParsedCatalog],
    *,
    chain_id: str,
    logger: Logger | None = None,
) -> AggregationResult:
    if chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    if len(catalogs) > 3:
        raise SourceError("BRANCH_LIMIT")
    if len({catalog.branch for catalog in catalogs}) != len(catalogs):
        raise SourceError("DUPLICATE_BRANCH")
    if any(catalog.branch.chain_id != chain_id for catalog in catalogs):
        raise SourceError("MIXED_CHAINS")
    if len({catalog.source_chain_id for catalog in catalogs}) > 1:
        raise SourceError("MIXED_SOURCE_CHAINS")
    if any(catalog.source_updated_at.utcoffset() is None for catalog in catalogs):
        raise SourceError("INVALID_SOURCE_TIME")
    observations: dict[str, list[tuple[ParsedCatalog, ProductObservation]]] = {}
    conflicts = set().union(*(catalog.conflicting_codes for catalog in catalogs))
    for catalog in catalogs:
        codes: set[str] = set()
        for row in catalog.products:
            if row.item_code in codes:
                raise SourceError("DUPLICATE_OBSERVATION")
            codes.add(row.item_code)
            if row.item_code not in conflicts:
                observations.setdefault(row.item_code, []).append((catalog, row))
    products = []
    invalid_prices = missing_packages = 0
    for code, contributing in sorted(observations.items()):
        # Catalog publication is observation time; the item's price-change time
        # does not describe when its current name/manufacturer was observed.
        contributing.sort(key=lambda pair: pair[0].branch)
        contributing.sort(key=lambda pair: pair[0].source_updated_at, reverse=True)
        _, metadata = contributing[0]
        packages = [normalize_package(row) for _, row in contributing]
        if any(not compatible_packages(packages[0], package) for package in packages[1:]):
            conflicts.add(code)
            continue
        try:
            price = average_price([row.price for _, row in contributing])
        except SourceError:
            invalid_prices += 1
            continue
        package = packages[0]
        missing_packages += int(package.quantity is None)
        products.append(
            AggregatedProduct(
                chain_id=chain_id,
                item_code=code,
                name=metadata.name,
                manufacturer=metadata.manufacturer,
                price=price,
                sample_count=len(contributing),
                is_weighted=metadata.is_weighted,
                package_quantity=package.quantity,
                package_unit=package.unit,
                source_quantity=package.source_quantity,
                source_unit_qty=package.source_unit_qty,
                item_price_updated_at=metadata.item_price_updated_at,
                source_updated_at=min(catalog.source_updated_at for catalog, _ in contributing),
                newest_source_updated_at=max(
                    catalog.source_updated_at for catalog, _ in contributing
                ),
                normalized_name=normalize_name(metadata.name),
                name_tokens=tokenize(metadata.name),
            )
        )
    result = AggregationResult(
        chain_id,
        tuple(products),
        len(catalogs),
        len(conflicts),
        invalid_prices,
        sum(catalog.invalid_row_count for catalog in catalogs),
        sum(catalog.duplicate_row_count for catalog in catalogs),
        missing_packages,
    )
    if logger is not None:
        logger.child(chain_id=chain_id).info(
            "aggregation.finished",
            "Chain reconciliation completed",
            product_count=len(products),
            successful_branch_count=len(catalogs),
            conflict_count=result.conflict_count,
            invalid_price_count=invalid_prices,
            missing_package_count=missing_packages,
            can_publish=result.can_publish,
        )
    return result
