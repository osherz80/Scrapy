from dataclasses import replace
from decimal import Decimal

import pytest

from ingestor.models import ProductObservation
from ingestor.packaging import compatible_packages, normalize_package


def observation(quantity="60", unit="מיליליטר", **overrides):
    return ProductObservation(
        item_code="001",
        name="Product name is not a dimension source",
        price=Decimal("10.90"),
        is_weighted=False,
        source_quantity=Decimal(quantity) if quantity else None,
        source_unit_qty=unit,
        source_quantity_text=quantity,
        **overrides,
    )


@pytest.mark.parametrize(
    "quantity,unit,base_quantity,base_unit",
    [
        ("60", "מיליליטר", "60", "ml"),
        ("1", "ליטר", "1000", "ml"),
        ("0.5", "קילוגרם", "500", "g"),
        ("1000", "גרם", "1000", "g"),
        ("2", "יחידות", "2", "unit"),
        ("1", "L", "1000", "ml"),
    ],
)
def test_known_package_dimensions_normalize_without_changing_source_pair(
    quantity, unit, base_quantity, base_unit
):
    package = normalize_package(observation(quantity, unit))
    assert package.quantity == Decimal(base_quantity)
    assert package.unit == base_unit
    assert (package.source_quantity, package.source_unit_qty) == (Decimal(quantity), unit)


def test_equivalent_packages_compare_but_mass_and_volume_never_do():
    litre = normalize_package(observation("1", "ליטר"))
    ml = normalize_package(observation("1000", "מיליליטר"))
    kg = normalize_package(observation("1", "קילוגרם"))
    assert compatible_packages(litre, ml)
    assert not compatible_packages(litre, kg)


def test_unknown_unit_has_no_invented_conversion_pair_but_keeps_comparison_signature():
    box = normalize_package(observation("1", "box"))
    assert box.quantity is None and box.unit is None
    assert box.source_quantity is None and box.source_unit_qty is None
    assert compatible_packages(box, normalize_package(observation("1", "box")))
    assert not compatible_packages(box, normalize_package(observation("2", "box")))


def test_missing_size_cannot_be_guessed_from_product_name_or_comparison_basis():
    row = observation(None, None, unit_of_measure="100 מיליליטר")
    row = replace(row, name='רוטב טבסקו 60 מ"ל')
    package = normalize_package(row)
    assert package.quantity is None and package.unit is None
    assert not compatible_packages(package, package)


def test_weighted_and_sold_by_unit_observations_are_incompatible():
    row = observation()
    assert not compatible_packages(
        normalize_package(row), normalize_package(replace(row, is_weighted=True))
    )


def test_qty_in_package_zero_or_unverified_counts_are_not_invented_package_dimensions():
    a = normalize_package(observation(qty_in_package=Decimal(0)))
    b = normalize_package(observation(qty_in_package=Decimal(12)))
    assert a.quantity == b.quantity == 60
    assert compatible_packages(a, b)


def test_sixty_ml_is_not_the_hundred_ml_comparison_basis():
    package = normalize_package(observation(unit_of_measure="100 מיליליטר"))
    assert package.quantity == 60 and package.unit == "ml"
