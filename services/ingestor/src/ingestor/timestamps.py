"""Convert verified publisher timestamps; never infer freshness from download time."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .providers.stream import SourceError


def source_timestamp(value: datetime | None) -> datetime:
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
