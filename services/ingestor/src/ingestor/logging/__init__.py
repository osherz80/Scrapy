"""Logger facade and factory; application code depends on the Logger protocol."""

import math
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import islice
from threading import Thread

from .transports import ConsoleTransport
from .types import Logger, LogLevel, Transport

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40, "fatal": 50}
_SENSITIVE = re.compile(
    r"password|passwd|secret|token|authorization|cookie|database|connection|dsn|"
    r"raw|xml|payload|branch.?price|product_dump|observations|^items$|^products$|"
    r"api[_-]?key|^price$|^item_?price$|^catalog$",
    re.IGNORECASE,
)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_CREDENTIAL = re.compile(
    r"\b(?:password|passwd|token|secret|api[_-]?key|authorization)\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)|\bbearer\s+\S+",
    re.IGNORECASE,
)


def _text(value: str) -> str:
    if "<" in value and ">" in value:
        return "[REDACTED SOURCE CONTENT]"
    return _CREDENTIAL.sub("[REDACTED]", _URL.sub("[REDACTED URL]", value))[:500]


def _safe(value: object, depth: int = 0) -> object:
    if depth >= 4:
        return "[TRUNCATED]"
    if isinstance(value, BaseException):
        # Exception text/tracebacks can contain unlabelled credentials and raw XML.
        return {"type": type(value).__name__, "message": "[REDACTED]"}
    if isinstance(value, str):
        return _text(value)
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else "[NONFINITE]"
    if type(value) is dict:
        return {
            _text(key): "[REDACTED]" if _SENSITIVE.search(key) else _safe(item, depth + 1)
            for key, item in islice(value.items(), 16)
            if isinstance(key, str)
        }
    if type(value) in (tuple, list):
        return [_safe(item, depth + 1) for item in value[:16]]
    return "[UNSUPPORTED]"


def _fields(fields: dict[str, object]) -> dict[str, object]:
    return {
        _text(key): "[REDACTED]" if _SENSITIVE.search(key) else _safe(value)
        for key, value in islice(fields.items(), 32)
    }


@dataclass(frozen=True)
class _Logger:
    _transport: Transport
    _level: int
    _environment: str
    _version: str
    _context: dict[str, object] = field(default_factory=dict)

    def child(self, **context: object) -> Logger:
        return replace(self, _context=_fields({**self._context, **context}))

    def _emit(self, level: LogLevel, event: str, message: str, fields: dict[str, object]) -> None:
        if _LEVELS[level] < self._level:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": _text(event),
            "message": _text(message),
            "service": "ingestor",
            "environment": _text(self._environment),
            "version": _text(self._version),
            "fields": _fields({**self._context, **fields}),
        }
        try:
            self._transport.write(record)
        except Exception:
            # A broken sink cannot change database publication/ownership outcomes.
            pass

    def debug(self, event: str, message: str, **fields: object) -> None:
        self._emit("debug", event, message, fields)

    def info(self, event: str, message: str, **fields: object) -> None:
        self._emit("info", event, message, fields)

    def warn(self, event: str, message: str, **fields: object) -> None:
        self._emit("warn", event, message, fields)

    def error(self, event: str, message: str, **fields: object) -> None:
        self._emit("error", event, message, fields)

    def fatal(self, event: str, message: str, **fields: object) -> None:
        self._emit("fatal", event, message, fields)

    def flush(self, timeout: float = 1.0) -> None:
        def deliver() -> None:
            try:
                self._transport.flush()
            except Exception:
                pass

        thread = Thread(target=deliver, daemon=True, name="ingestor-log-flush")
        thread.start()
        thread.join(timeout=max(0.0, min(timeout, 5.0)))


def create_logger(
    *,
    level: str = "info",
    environment: str = "development",
    version: str = "unknown",
    transport: Transport | None = None,
) -> Logger:
    """Select delivery once at startup; no environment files or SDKs are loaded."""
    if level not in _LEVELS:
        raise ValueError("Invalid log level")
    return _Logger(
        ConsoleTransport() if transport is None else transport, _LEVELS[level], environment, version
    )
