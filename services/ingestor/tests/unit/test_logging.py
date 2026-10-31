import io
import json
import threading
from datetime import datetime

import pytest

from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport


class CaptureTransport:
    def __init__(self):
        self.records = []
        self.flushed = False

    def write(self, record):
        self.records.append(record)

    def flush(self):
        self.flushed = True


def test_console_outputs_json_with_utc_schema_and_filters_levels():
    stream = io.StringIO()
    logger = create_logger(environment="test", version="abc", transport=ConsoleTransport(stream))
    logger.debug("hidden", "hidden")
    logger.info("run.started", "Starting run", run_id="run-1", entry_point="refresh")
    logger.flush()
    record = json.loads(stream.getvalue())
    assert record["level"] == "info"
    assert record["event"] == "run.started"
    assert record["service"] == "ingestor"
    assert record["environment"] == "test"
    assert record["version"] == "abc"
    assert datetime.fromisoformat(record["timestamp"]).utcoffset().total_seconds() == 0
    assert record["fields"]["run_id"] == "run-1"


def test_capture_transport_and_child_context_are_isolated():
    transport = CaptureTransport()
    logger = create_logger(transport=transport, level="debug")
    child = logger.child(run_id="run-1", chain_id="shufersal")
    child.warn("branch.failed", "Branch failed", attempt_count=1)
    logger.error("run.failed", "Run failed")
    child.fatal("run.aborted", "Aborted")
    logger.flush()
    assert transport.records[0]["fields"]["chain_id"] == "shufersal"
    assert "run_id" not in transport.records[1]["fields"]
    assert [r["level"] for r in transport.records] == ["warn", "error", "fatal"]
    assert transport.flushed


def test_secrets_and_source_content_never_reach_injected_transport():
    transport = CaptureTransport()
    logger = create_logger(transport=transport)
    logger.child(database_url="postgresql://admin:db-secret@host/db").error(
        "provider.failed",
        "Download https://source.test/file?signature=source-secret failed token=message-secret",
        nested={"Authorization": "Bearer auth-secret", "password": "password-secret"},
        error=RuntimeError("unlabelled-secret <Items>raw-xml</Items>"),
        raw_xml="raw-xml",
        branch_price="10.90",
        api_key="api-key-secret",
        price="11.99",
    )
    output = json.dumps(transport.records)
    for secret in (
        "db-secret",
        "source-secret",
        "message-secret",
        "auth-secret",
        "password-secret",
        "unlabelled-secret",
        "raw-xml",
        "10.90",
        "api-key-secret",
        "11.99",
    ):
        assert secret not in output
    assert "RuntimeError" in output


def test_delivery_failure_does_not_escape_to_application():
    class BrokenTransport:
        def write(self, record):
            raise OSError("sensitive error")

        def flush(self):
            raise OSError("sensitive error")

    logger = create_logger(transport=BrokenTransport())
    logger.info("run.finished", "Finished")
    logger.flush()


def test_shutdown_flush_is_bounded_even_if_transport_blocks():
    release = threading.Event()

    class BlockingTransport(CaptureTransport):
        def flush(self):
            release.wait()

    logger = create_logger(transport=BlockingTransport())
    completed = threading.Event()
    thread = threading.Thread(
        target=lambda: (logger.flush(timeout=0.01), completed.set()), daemon=True
    )
    thread.start()
    try:
        assert completed.wait(timeout=1), "flush exceeded its shutdown budget"
    finally:
        release.set()
        thread.join(timeout=1)


def test_unknown_log_level_is_rejected():
    with pytest.raises(ValueError):
        create_logger(level="verbose")


def test_context_is_snapshotted_and_untrusted_objects_are_not_stringified():
    class Untrusted:
        def __str__(self):
            raise AssertionError("must not stringify source objects")

    transport = CaptureTransport()
    context = {"attempt_count": 1}
    child = create_logger(transport=transport).child(details=context)
    context["attempt_count"] = 99
    child.info("run.summary", "Summary", unknown=Untrusted())
    assert transport.records[0]["fields"]["details"]["attempt_count"] == 1
    assert transport.records[0]["fields"]["unknown"] == "[UNSUPPORTED]"


def test_records_bound_large_recursive_context_without_breaking_delivery():
    transport = CaptureTransport()
    context = {}
    context["self"] = context
    create_logger(transport=transport).info("run.summary", "x" * 10000, details=context)
    assert len(json.dumps(transport.records)) < 2000


@pytest.mark.parametrize("level", ["debug", "info", "warn", "error", "fatal"])
def test_level_threshold_includes_only_that_severity_and_above(level):
    transport = CaptureTransport()
    logger = create_logger(transport=transport, level=level)
    levels = ["debug", "info", "warn", "error", "fatal"]
    for severity in levels:
        getattr(logger, severity)("test.event", "Test event")
    assert [record["level"] for record in transport.records] == levels[levels.index(level) :]
