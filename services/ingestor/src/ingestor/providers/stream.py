"""Bounded source handling. Raw payloads never leave process memory."""

import gzip
import io
import zipfile
import zlib


class SourceError(Exception):
    """Stable public failure code, independent of source bodies and credentials."""


def decompress(payload: bytes, *, limit: int) -> bytes:
    if limit <= 0:
        raise ValueError("limit must be positive")
    try:
        if payload.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as source:
                result = source.read(limit + 1)
        elif payload.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(members) != 1:
                    raise SourceError("AMBIGUOUS_ARCHIVE")
                if members[0].file_size > limit:
                    raise SourceError("SIZE_LIMIT")
                with archive.open(members[0]) as source:
                    result = source.read(limit + 1)
        else:
            result = payload
    except (OSError, EOFError, zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError):
        raise SourceError("CORRUPT_ARCHIVE") from None
    if len(result) > limit:
        raise SourceError("SIZE_LIMIT")
    return result
