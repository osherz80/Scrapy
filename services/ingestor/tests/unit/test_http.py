import io
import json

import httpx
import pytest

from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.providers.http import BoundedClient
from ingestor.providers.stream import SourceError


def client(handler, **kwargs):
    return BoundedClient(
        allowed_hosts=frozenset({"source.test"}),
        timeout_seconds=60,
        max_bytes=10,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_client_does_not_retry_failure_or_echo_source_url():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, content=b"secret body")

    with client(handler) as source:
        with pytest.raises(SourceError, match="HTTP_503") as error:
            source.get("https://source.test/file?token=synthetic-secret")
        assert len(calls) == 1
        assert "synthetic-secret" not in str(error.value)


def test_http_failure_logs_host_path_status_and_elapsed_without_query():
    stream = io.StringIO()

    def handler(_):
        return httpx.Response(403, content=b"blocked")

    with client(handler, logger=create_logger(transport=ConsoleTransport(stream))) as source:
        with pytest.raises(SourceError, match="HTTP_403"):
            source.get("https://source.test/Prices?t=3&p=1&token=synthetic-secret")
    record = json.loads(stream.getvalue())
    fields = record["fields"]
    assert record["event"] == "http.request_failed"
    assert fields["method"] == "GET"
    assert fields["host"] == "source.test"
    assert fields["path"] == "/Prices"
    assert fields["status"] == 403
    assert type(fields["elapsed_ms"]) is int
    assert fields["error_code"] == "HTTP_403"
    assert "synthetic-secret" not in stream.getvalue()
    assert "?" not in stream.getvalue()


def test_successful_request_emits_no_request_log():
    stream = io.StringIO()

    with client(
        lambda _: httpx.Response(200, content=b"ok"),
        logger=create_logger(transport=ConsoleTransport(stream)),
    ) as source:
        assert source.get("https://source.test/file").content == b"ok"
    assert stream.getvalue() == ""


def test_byte_budget_rejects_whole_response():
    with client(lambda _: httpx.Response(200, content=b"a" * 11)) as source:
        with pytest.raises(SourceError, match="SIZE_LIMIT"):
            source.get("https://source.test/file")


def test_http_content_encoding_is_not_decompressed_without_a_limit():
    with client(lambda _: httpx.Response(200, headers={"content-encoding": "gzip"})) as source:
        with pytest.raises(SourceError, match="HTTP_ENCODING_UNSUPPORTED"):
            source.get("https://source.test/file")


def test_unapproved_redirect_is_blocked_before_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/admin"})

    with client(handler) as source:
        with pytest.raises(SourceError, match="UNAPPROVED_SOURCE_URL"):
            source.get("https://source.test/file")
        assert len(calls) == 1


def test_request_budget_covers_adapter_internal_calls_and_redirects():
    with client(lambda _: httpx.Response(200, content=b"ok"), max_requests=1) as source:
        assert source.get("https://source.test/file").content == b"ok"
        with pytest.raises(SourceError, match="REQUEST_LIMIT"):
            source.get("https://source.test/file")


def test_cookie_session_is_kept_and_no_proxy_environment_is_used(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://unapproved.test")

    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        if request.url.path == "/login":
            return httpx.Response(
                200, headers={"set-cookie": "session=test; Path=/"}, content=b"ok"
            )
        assert request.headers["cookie"] == "session=test"
        return httpx.Response(200, content=b"ok")

    with client(handler) as source:
        source.post("https://source.test/login", data={"user": "public"})
        assert source.get("https://source.test/file").content == b"ok"


def test_expired_deadline_makes_no_network_request():
    with client(lambda _: pytest.fail("network must not be used"), deadline=0) as source:
        with pytest.raises(SourceError, match="TIME_LIMIT"):
            source.get("https://source.test/file")


def test_stream_stops_before_reading_the_rest_of_an_oversized_body():
    class Body(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b"a" * 6
            yield b"b" * 6
            pytest.fail("must not consume the rest of a rejected response")

        def close(self):
            self.closed = True

    body = Body()
    with client(lambda _: httpx.Response(200, stream=body)) as source:
        with pytest.raises(SourceError, match="SIZE_LIMIT"):
            source.get("https://source.test/file")
    assert body.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://source.test/file",
        "https://user:password@source.test/file",
        "https://source.test:444/file",
        "https://evil.test/file",
    ],
)
def test_unsafe_url_is_blocked_before_network_access(url):
    with client(lambda _: pytest.fail("network must not be used")) as source:
        with pytest.raises(SourceError, match="UNAPPROVED_SOURCE_URL"):
            source.get(url)
