from datetime import UTC, datetime, timedelta, timezone

import pytest

from ingestor.providers.stream import SourceError
from ingestor.timestamps import source_timestamp


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        (datetime(2026, 1, 2, 6), datetime(2026, 1, 2, 4, tzinfo=UTC)),
        (datetime(2026, 7, 2, 6), datetime(2026, 7, 2, 3, tzinfo=UTC)),
    ],
)
def test_source_dates_use_israel_winter_and_summer_offsets(local, utc):
    assert source_timestamp(local) == utc


@pytest.mark.parametrize("value", [datetime(2026, 10, 25, 1, 30), datetime(2026, 3, 27, 2, 30)])
def test_ambiguous_and_nonexistent_local_dates_are_not_guessed(value):
    with pytest.raises(SourceError, match="AMBIGUOUS_SOURCE_TIME"):
        source_timestamp(value)


def test_explicit_offset_disambiguates_a_source_date():
    value = datetime(2026, 10, 25, 1, 30, tzinfo=timezone(timedelta(hours=3)))
    assert source_timestamp(value) == datetime(2026, 10, 24, 22, 30, tzinfo=UTC)


def test_missing_date_is_not_replaced_with_current_time():
    with pytest.raises(SourceError, match="MISSING_SOURCE_TIME"):
        source_timestamp(None)
