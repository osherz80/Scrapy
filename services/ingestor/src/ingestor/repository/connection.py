"""Direct process-configured PostgreSQL connections; no environment-file loading."""

from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import psycopg


class DatabaseConnectionError(Exception):
    """Static connection validation code, never driver text or credentials."""


def connection_options(url: str, env: Mapping[str, str], root: Path) -> dict[str, object]:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("postgres", "postgresql")
            or not parsed.hostname
            or not parsed.username
        ):
            raise ValueError
        if not parsed.path.strip("/") or parsed.fragment:
            raise ValueError
        _ = parsed.port
        query = dict(parse_qsl(parsed.query))
        if any(
            key in query
            for key in (
                "service",
                "host",
                "hostaddr",
                "port",
                "user",
                "password",
                "dbname",
                "passfile",
                "sslcert",
                "sslkey",
                "sslrootcert",
                "sslcrl",
                "sslcrldir",
            )
        ):
            raise ValueError
        local_test = parsed.hostname in ("127.0.0.1", "localhost", "::1") and parsed.path.lstrip(
            "/"
        ).startswith("ingestor_test")
        if not local_test and not parsed.password:
            raise ValueError
    except ValueError:
        raise DatabaseConnectionError("INVALID_DATABASE_URL") from None
    if env.get("PGSERVICE"):
        raise DatabaseConnectionError("PGSERVICE_NOT_SUPPORTED")
    options: dict[str, object] = {
        "autocommit": True,
        "connect_timeout": 10,
        "sslmode": "disable" if local_test else "verify-full",
        "passfile": str(root / "Temp/disabled-passfile"),
    }
    if not local_test:
        options["sslrootcert"] = "system"
        if certificate := env.get("DATABASE_SSLROOTCERT"):
            try:
                root = root.resolve()
                path = (root / certificate).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError
            except (OSError, ValueError):
                raise DatabaseConnectionError("DATABASE_CA_FILE_INVALID") from None
            options["sslrootcert"] = str(path)
    return options


def connection_failure_diagnostic(error: Exception) -> tuple[str, str]:
    """Classify driver failures into fixed public text; never return driver details."""
    if isinstance(error, DatabaseConnectionError):
        return str(error), "Check DATABASE_SSLROOTCERT points to a CA file inside the project."
    if isinstance(error, psycopg.OperationalError):
        message = str(error).lower()
        if any(
            term in message
            for term in (
                "network is unreachable",
                "no route to host",
                "network unreachable",
                "cannot assign requested address",
            )
        ):
            return (
                "DATABASE_NETWORK_UNREACHABLE",
                "Runner cannot reach the database network. An IPv6-only Supabase direct "
                "endpoint needs IPv6 connectivity; use the session pooler on port 5432 "
                "for an IPv4-only runner.",
            )
        if any(term in message for term in ("certificate verify failed", "root certificate")):
            return (
                "DATABASE_TLS_VERIFICATION_FAILED",
                "Database TLS verification failed. Set DATABASE_SSLROOTCERT to the downloaded "
                "database CA certificate path inside the project; "
                "server verification remains enabled.",
            )
        if "password authentication failed" in message:
            return (
                "DATABASE_AUTHENTICATION_FAILED",
                "Database rejected the credentials in DATABASE_URL.",
            )
        if any(term in message for term in ("could not translate host", "getaddrinfo")):
            return (
                "DATABASE_DNS_FAILED",
                "Database hostname could not be resolved; check DATABASE_URL and DNS.",
            )
        if any(term in message for term in ("timeout", "timed out")):
            return (
                "DATABASE_CONNECTION_TIMEOUT",
                "Database connection timed out; check network access and database availability.",
            )
        return (
            "DATABASE_CONNECTION_FAILED",
            "Database connection failed; check network access and database connection settings.",
        )
    return "MIGRATION_FAILED", "Database administration failed"


def make_connection_factory(
    url: str, *, env: Mapping[str, str], root: Path | None = None
) -> Callable[[], psycopg.Connection]:
    """Create independent direct sessions, including a dedicated heartbeat session."""
    options = connection_options(url, env, Path.cwd().resolve() if root is None else root)
    options.update(
        options=(
            "-c statement_timeout=15000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=15000"
        ),
        keepalives=1,
        keepalives_idle=10,
        keepalives_interval=5,
        keepalives_count=3,
        tcp_user_timeout=15000,
    )

    def connect() -> psycopg.Connection:
        return psycopg.connect(url, **options)

    return connect
