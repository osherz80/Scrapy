from decimal import Decimal, Inexact, localcontext

import pytest

from ingestor.aggregation import average_price
from ingestor.providers.stream import SourceError


@pytest.mark.parametrize(
    "prices,expected",
    [
        (["10.90"], "10.9000"),
        (["10", "11"], "10.5000"),
        (["1", "2", "2"], "1.6667"),
        (["1.00004", "1.00006"], "1.0001"),
        (["1.000049999999999999999999999999999999"], "1.0000"),
        (["9999999999.99994"], "9999999999.9999"),
    ],
)
def test_decimal_mean_rounds_once_half_up(prices, expected):
    with localcontext() as context:
        context.prec = 6  # Application behavior must not depend on a caller's context.
        result = average_price([Decimal(value) for value in prices])
    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -4


@pytest.mark.parametrize("prices", [[], ["0"], ["NaN"], ["Infinity"], ["-1"], ["1"] * 4])
def test_invalid_observations_and_sample_sizes_are_rejected(prices):
    with pytest.raises(SourceError):
        average_price([Decimal(value) for value in prices])


@pytest.mark.parametrize("price", ["0.000001", "10000000000", "1e-999999999"])
def test_unpublishable_or_excessive_numeric_values_are_not_clamped_or_approximated(price):
    with pytest.raises(SourceError):
        average_price([Decimal(price)])


def test_callers_decimal_traps_cannot_break_valid_mean_calculation():
    with localcontext() as context:
        context.traps[Inexact] = True
        assert average_price([Decimal(1), Decimal(2), Decimal(2)]) == Decimal("1.6667")
