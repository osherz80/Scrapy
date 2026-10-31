import gzip
import io
import zipfile

import pytest

from ingestor.providers.stream import SourceError, decompress


def zipped(data: bytes, names=("PriceFull.xml",)) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, data)
    return stream.getvalue()


@pytest.mark.parametrize("encode", [lambda data: data, gzip.compress, zipped])
def test_payloads_are_decoded_entirely_in_memory_with_exact_limit(encode):
    data = b"<Root>content</Root>"
    assert decompress(encode(data), limit=len(data)) == data


@pytest.mark.parametrize("encode", [lambda data: data, gzip.compress, zipped])
def test_decompressed_byte_limit_never_returns_partial_catalog(encode):
    with pytest.raises(SourceError, match="SIZE_LIMIT"):
        decompress(encode(b"a" * 1000), limit=100)


@pytest.mark.parametrize("payload", [b"\x1f\x8bcorrupt", gzip.compress(b"data")[:-5], b"PKcorrupt"])
def test_corrupt_or_truncated_archives_fail(payload):
    with pytest.raises(SourceError, match="CORRUPT_ARCHIVE"):
        decompress(payload, limit=1000)


def test_ambiguous_zip_members_are_not_silently_selected():
    with pytest.raises(SourceError, match="AMBIGUOUS_ARCHIVE"):
        decompress(zipped(b"data", names=("first.xml", "second.xml")), limit=1000)


def test_no_archive_file_is_extracted_to_disk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("raw files must never be written")

    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden)
    assert decompress(zipped(b"<Root/>"), limit=1000) == b"<Root/>"
