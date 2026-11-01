"""Single-attempt HTTP with explicit host, byte, time and request budgets."""

from collections.abc import Mapping
from time import monotonic
from typing import Self

import httpx

from ..logging.types import Logger
from .stream import SourceError


class BoundedClient:
    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        timeout_seconds: float,
        max_bytes: int,
        max_requests: int = 40,
        deadline: float | None = None,
        allow_azure: bool = False,
        transport: httpx.BaseTransport | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.allow_azure = allow_azure
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_requests = max_requests
        self.deadline = monotonic() + 120 if deadline is None else deadline
        self.request_count = 0
        self._logger = logger
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "neuton-ingestor/0.1", "Accept-Encoding": "identity"},
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, params: Mapping[str, object] | None = None) -> httpx.Response:
        return self._request("GET", url, params=params)

    def post(self, url: str, data: Mapping[str, object] | None = None) -> httpx.Response:
        return self._request("POST", url, data=data)

    def _validate_url(self, url: httpx.URL) -> None:
        host = url.host.lower()
        allowed = host in self.allowed_hosts or (
            self.allow_azure and host.endswith(".blob.core.windows.net")
        )
        if not allowed or url.scheme != "https" or url.port not in (None, 443) or url.userinfo:
            raise SourceError("UNAPPROVED_SOURCE_URL")

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        started = monotonic()
        request, status = None, None
        try:
            request = self._client.build_request(method, url, **kwargs)
            request_deadline = min(self.deadline, monotonic() + self.timeout_seconds)
            for _ in range(6):
                self._validate_url(request.url)
                remaining = request_deadline - monotonic()
                if remaining <= 0:
                    raise SourceError("TIME_LIMIT")
                if self.request_count >= self.max_requests:
                    raise SourceError("REQUEST_LIMIT")
                request.extensions["timeout"] = httpx.Timeout(remaining).as_dict()
                self.request_count += 1
                response = self._client.send(request, stream=True)
                status = response.status_code
                try:
                    if response.is_redirect and response.next_request is not None:
                        next_request = response.next_request
                        if request.method != "GET" and request.url.host != next_request.url.host:
                            raise SourceError("UNSAFE_REDIRECT")
                        request = next_request
                        continue
                    if response.status_code >= 400:
                        raise SourceError(f"HTTP_{response.status_code}")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise SourceError("HTTP_ENCODING_UNSUPPORTED")
                    payload = bytearray()
                    chunks = (
                        [response.content] if response.is_stream_consumed else response.iter_raw()
                    )
                    for chunk in chunks:
                        if monotonic() >= request_deadline:
                            raise SourceError("TIME_LIMIT")
                        if len(payload) + len(chunk) > self.max_bytes:
                            raise SourceError("SIZE_LIMIT")
                        payload.extend(chunk)
                    return httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=bytes(payload),
                        request=response.request,
                    )
                finally:
                    response.close()
            raise SourceError("REDIRECT_LIMIT")
        except SourceError as error:
            self._log_failure(request, status, started, error)
            raise
        except httpx.TimeoutException:
            error = SourceError("TIME_LIMIT")
            self._log_failure(request, status, started, error)
            raise error from None
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            error = SourceError("HTTP_FAILURE")
            self._log_failure(request, status, started, error)
            raise error from None

    def _log_failure(
        self,
        request: httpx.Request | None,
        status: int | None,
        started: float,
        error: SourceError,
    ) -> None:
        """Emit host/path diagnostics only when a request fails; never the query."""
        if self._logger is None:
            return
        self._logger.error(
            "http.request_failed",
            "Source request failed",
            method=request.method if request is not None else None,
            host=request.url.host if request is not None else None,
            path=request.url.path if request is not None else None,
            status=status,
            elapsed_ms=round((monotonic() - started) * 1000),
            request_count=self.request_count,
            error_code=str(error),
        )
