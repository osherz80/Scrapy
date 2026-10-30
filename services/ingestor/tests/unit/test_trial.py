import io
import json
from datetime import datetime

from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.providers import trial
from ingestor.providers.stream import SourceError

CATALOG = (
    b"<Root><ChainId>123</ChainId><SubChainId>001</SubChainId><StoreId>001</StoreId>"
    b"<Items><Item><ItemCode>0001</ItemCode><ItemName>Example</ItemName>"
    b"<ItemPrice>10.90</ItemPrice><Quantity>60</Quantity><UnitQty>ml</UnitQty>"
    b"</Item></Items></Root>"
)


class FakeSource:
    expected_chain_id = "123"
    closed = False
    downloaded = 0

    def __init__(self, *args, **kwargs):
        pass

    def files(self):
        yield trial.ProbeFile(
            "001", "https://source.test/file?token=synthetic-secret", datetime(2026, 10, 30, 6)
        )

    def download(self, ref):
        self.downloaded += 1
        return CATALOG

    def close(self):
        self.closed = True


def test_probe_inspects_one_full_catalog_without_logging_product_or_source_data(monkeypatch):
    source = FakeSource()
    monkeypatch.setattr(trial, "CandidateSource", lambda *args, **kwargs: source)
    stream = io.StringIO()
    logger = create_logger(transport=ConsoleTransport(stream))
    assert trial.run_probe(("shufersal",), load_settings({}), logger, max_branches=1) == 0
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    branch = next(r for r in records if r["event"] == "probe.branch.succeeded")
    assert branch["fields"]["valid_row_count"] == 1
    assert branch["fields"]["run_id"]
    assert branch["fields"]["chain_id"] == "shufersal"
    assert source.closed and source.downloaded == 1
    for forbidden in ("synthetic-secret", "0001", "Example", "10.90", "<Root>"):
        assert forbidden not in stream.getvalue()


def test_induced_provider_failure_is_sanitized_correlated_and_does_not_stop_other_chains(
    monkeypatch,
):
    class Broken(FakeSource):
        def download(self, ref):
            raise RuntimeError(
                "postgresql://worker:synthetic-secret@db.test/db <Items>secret</Items>"
            )

    sources = {"shufersal": Broken(), "carrefour": FakeSource()}
    monkeypatch.setattr(trial, "CandidateSource", lambda chain, *args: sources[chain])
    stream = io.StringIO()
    logger = create_logger(transport=ConsoleTransport(stream))
    assert trial.run_probe(tuple(sources), load_settings({}), logger, max_branches=1) == 1
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    failure = next(r for r in records if r["event"] == "probe.branch.failed")
    assert failure["fields"]["run_id"]
    assert failure["fields"]["error_code"] == "PROVIDER_FAILURE"
    assert any(r["event"] == "probe.branch.succeeded" for r in records)
    assert all(source.closed for source in sources.values())
    assert "synthetic-secret" not in stream.getvalue()
    assert "<Items>" not in stream.getvalue()


def test_probe_does_not_relabel_empty_listing_as_success(monkeypatch):
    class Empty(FakeSource):
        def files(self):
            return iter(())

    monkeypatch.setattr(trial, "CandidateSource", Empty)
    stream = io.StringIO()
    result = trial.run_probe(
        ("shufersal",),
        load_settings({}),
        create_logger(transport=ConsoleTransport(stream)),
        max_branches=1,
    )
    assert result == 1
    assert "NO_PRICEFULL" in stream.getvalue()


def test_probe_public_error_codes_never_include_source_exception_messages():
    assert trial.error_code(SourceError("HTTP_403")) == "HTTP_403"
    assert trial.error_code(SourceError("source-secret-message")) == "PROVIDER_FAILURE"


def test_failed_branch_is_attempted_once_and_cleanup_failure_does_not_abort_run(monkeypatch):
    class Broken(FakeSource):
        def download(self, ref):
            self.downloaded += 1
            raise SourceError("HTTP_403")

        def close(self):
            self.closed = True
            raise OSError("synthetic-secret")

    source = Broken()
    monkeypatch.setattr(trial, "CandidateSource", lambda *args: source)
    stream = io.StringIO()
    result = trial.run_probe(
        ("shufersal",),
        load_settings({}),
        create_logger(transport=ConsoleTransport(stream)),
        max_branches=1,
    )
    assert result == 1
    assert source.downloaded == 1 and source.closed
    assert "synthetic-secret" not in stream.getvalue()
    assert '"event": "probe.finished"' in stream.getvalue()


def test_conflicting_filename_store_identity_fails_without_relabelling_the_catalog(monkeypatch):
    class Conflicting(FakeSource):
        def files(self):
            yield trial.ProbeFile("416", "https://source.test/file", datetime(2026, 10, 30, 6))

    monkeypatch.setattr(trial, "CandidateSource", Conflicting)
    stream = io.StringIO()
    assert (
        trial.run_probe(
            ("carrefour",),
            load_settings({}),
            create_logger(transport=ConsoleTransport(stream)),
            max_branches=1,
        )
        == 1
    )
    assert "IDENTITY_MISMATCH" in stream.getvalue()
    assert "probe.branch.succeeded" not in stream.getvalue()


def test_duplicate_catalog_identity_never_counts_as_two_branches(monkeypatch):
    class Duplicate(FakeSource):
        def files(self):
            yield from super().files()
            yield from super().files()

    monkeypatch.setattr(trial, "CandidateSource", Duplicate)
    stream = io.StringIO()
    assert (
        trial.run_probe(
            ("shufersal",),
            load_settings({}),
            create_logger(transport=ConsoleTransport(stream)),
            max_branches=2,
        )
        == 1
    )
    assert "DUPLICATE_BRANCH" in stream.getvalue()
    assert stream.getvalue().count('"event": "probe.branch.succeeded"') == 1
