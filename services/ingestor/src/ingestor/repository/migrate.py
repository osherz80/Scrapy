"""Explicit transactional migration administration; never loads environment files."""

import argparse
import hashlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import psycopg

from ..logging import create_logger

_MIGRATION_NAME = re.compile(r"^(\d{3,})_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    """Public diagnostic code without database credentials or SQL error text."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    forward: str = field(repr=False)
    rollback: str = field(repr=False)
    checksum: str
    rollback_checksum: str


def _read_sql(path: Path, root: Path) -> str:
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise MigrationError("MIGRATION_OUTSIDE_PROJECT")
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def load_migrations(project_root: Path) -> tuple[Migration, ...]:
    root = project_root.resolve()
    directory = root / "db/migrations"
    if any(
        not folder.resolve().is_relative_to(root) for folder in (directory, root / "db/rollback")
    ):
        raise MigrationError("MIGRATION_OUTSIDE_PROJECT")
    paths = list(directory.glob("*.sql"))
    if not paths:
        raise MigrationError("MISSING_MIGRATIONS")
    versions: set[int] = set()
    migrations = []
    for path in paths:
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError("INVALID_MIGRATION_NAME")
        version = match.group(1)
        if int(version) in versions:
            raise MigrationError("DUPLICATE_VERSION")
        versions.add(int(version))
        rollback_path = root / "db/rollback" / path.name
        if not rollback_path.is_file():
            raise MigrationError("MISSING_ROLLBACK")
        forward = _read_sql(path, root)
        rollback = _read_sql(rollback_path, root)
        migrations.append(
            Migration(
                version,
                path.name,
                forward,
                rollback,
                hashlib.sha256(forward.encode()).hexdigest(),
                hashlib.sha256(rollback.encode()).hexdigest(),
            )
        )
    return tuple(sorted(migrations, key=lambda migration: int(migration.version)))


def _lock(connection: psycopg.Connection) -> None:
    connection.execute("SET LOCAL lock_timeout = '5s'")
    connection.execute("SET LOCAL statement_timeout = '120s'")
    connection.execute("SELECT pg_advisory_xact_lock(1397900112, 1)")


def _history(connection: psycopg.Connection, migrations: tuple[Migration, ...]) -> tuple[str, ...]:
    if (
        connection.execute("SELECT to_regclass('supermarket.schema_migrations')").fetchone()[0]
        is None
    ):
        return ()
    rows = connection.execute(
        "SELECT version,name,checksum,rollback_checksum FROM supermarket.schema_migrations"
    ).fetchall()
    expected = {migration.version: migration for migration in migrations}
    if any(row[0] not in expected for row in rows):
        raise MigrationError("MIGRATION_HISTORY_DIVERGED")
    rows.sort(key=lambda row: int(row[0]))
    for version, name, checksum, rollback_checksum in rows:
        migration = expected[version]
        if (name, checksum, rollback_checksum) != (
            migration.name,
            migration.checksum,
            migration.rollback_checksum,
        ):
            raise MigrationError("MIGRATION_DRIFT")
    versions = tuple(row[0] for row in rows)
    if versions != tuple(migration.version for migration in migrations[: len(versions)]):
        raise MigrationError("MIGRATION_HISTORY_DIVERGED")
    return versions


def _check_connection(connection: psycopg.Connection) -> None:
    if not connection.autocommit:
        raise MigrationError("AUTOCOMMIT_CONNECTION_REQUIRED")


def migration_status(
    connection: psycopg.Connection, migrations: tuple[Migration, ...]
) -> tuple[str, ...]:
    _check_connection(connection)
    with connection.transaction():
        _lock(connection)
        return _history(connection, migrations)


def apply_migrations(
    connection: psycopg.Connection, migrations: tuple[Migration, ...]
) -> tuple[str, ...]:
    _check_connection(connection)
    with connection.transaction():
        _lock(connection)
        connection.execute("""CREATE SCHEMA IF NOT EXISTS supermarket;
            REVOKE ALL ON SCHEMA supermarket FROM PUBLIC;
            CREATE TABLE IF NOT EXISTS supermarket.schema_migrations(
                version text PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
                rollback_checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
            ); REVOKE ALL ON supermarket.schema_migrations FROM PUBLIC;""")
        applied = _history(connection, migrations)
        pending = migrations[len(applied) :]
        for migration in pending:
            connection.execute(migration.forward, prepare=False)
            connection.execute(
                """INSERT INTO supermarket.schema_migrations(
                version,name,checksum,rollback_checksum) VALUES (%s,%s,%s,%s)""",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    migration.rollback_checksum,
                ),
            )
        return tuple(migration.version for migration in pending)


def rollback_migration(
    connection: psycopg.Connection,
    migrations: tuple[Migration, ...],
    *,
    version: str,
) -> None:
    _check_connection(connection)
    with connection.transaction():
        _lock(connection)
        applied = _history(connection, migrations)
        if not applied or version != applied[-1]:
            raise MigrationError("ROLLBACK_MUST_TARGET_LATEST")
        migration = next(migration for migration in migrations if migration.version == version)
        connection.execute(migration.rollback, prepare=False)
        connection.execute("DELETE FROM supermarket.schema_migrations WHERE version=%s", (version,))


def _connection_options(url: str, env: Mapping[str, str], root: Path) -> dict[str, object]:
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
        raise MigrationError("INVALID_DATABASE_URL") from None
    if env.get("PGSERVICE"):
        raise MigrationError("PGSERVICE_NOT_SUPPORTED")
    options: dict[str, object] = {
        "autocommit": True,
        "connect_timeout": 10,
        "sslmode": "disable" if local_test else "verify-full",
        "passfile": str(root / "Temp/disabled-passfile"),
    }
    if not local_test:
        options["sslrootcert"] = "system"
    return options


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("Invalid migration command; use --help")


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    parser = _Parser(
        description="Explicit database administration; rollback removes application data"
    )
    parser.add_argument("operation", choices=("status", "apply", "rollback"))
    parser.add_argument("--version", help="Required latest version for destructive rollback")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    logger = create_logger(
        environment=env.get("LOG_ENV", "administration"),
        version=env.get("APP_VERSION") or env.get("GITHUB_SHA") or "unknown",
    )
    try:
        url = env.get("MIGRATION_DATABASE_URL")
        if not url:
            raise MigrationError("MIGRATION_DATABASE_URL_REQUIRED")
        if args.operation == "rollback":
            if not args.version or not re.fullmatch(r"\d{3,}", args.version):
                raise MigrationError("ROLLBACK_VERSION_REQUIRED")
        elif args.version:
            raise MigrationError("VERSION_ONLY_VALID_FOR_ROLLBACK")
        root = Path.cwd().resolve()
        options = _connection_options(url, env, root)
        migrations = load_migrations(root)
        with psycopg.connect(url, **options) as connection:
            if args.operation == "apply":
                versions = apply_migrations(connection, migrations)
            elif args.operation == "rollback":
                rollback_migration(connection, migrations, version=args.version)
                versions = (args.version,)
            else:
                versions = migration_status(connection, migrations)
        logger.info(
            "migration.completed",
            "Database administration completed",
            operation=args.operation,
            versions=versions,
        )
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, MigrationError) else "MIGRATION_FAILED"
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            code = "MIGRATION_FAILED"
        logger.error(
            "migration.failed", "Database administration failed", error_code=code, error=error
        )
        return 2
    finally:
        logger.flush()


if __name__ == "__main__":
    raise SystemExit(main())
