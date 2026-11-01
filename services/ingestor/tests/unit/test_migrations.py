from pathlib import Path

import pytest

from ingestor.repository.migrate import MigrationError, load_migrations, main

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "message,code,hint",
    [
        (
            "SSL error: certificate verify failed",
            "DATABASE_TLS_VERIFICATION_FAILED",
            "DATABASE_SSLROOTCERT",
        ),
        ("password authentication failed", "DATABASE_AUTHENTICATION_FAILED", "credentials"),
        ("could not translate host name", "DATABASE_DNS_FAILED", "hostname"),
        ("connection timeout expired", "DATABASE_CONNECTION_TIMEOUT", "network"),
        (
            "connection failed: Network is unreachable",
            "DATABASE_NETWORK_UNREACHABLE",
            "session pooler",
        ),
        ("connection failed: No route to host", "DATABASE_NETWORK_UNREACHABLE", "session pooler"),
    ],
)
def test_connection_failure_has_actionable_safe_diagnostic(
    monkeypatch, capsys, message, code, hint
):
    import json

    from ingestor.repository import migrate

    def connect(*args, **kwargs):
        raise migrate.psycopg.OperationalError(message + " private-credential")

    monkeypatch.setattr(migrate.psycopg, "connect", connect)
    assert main(["status"], env={"DATABASE_URL": "postgresql://admin:secret@db.test/db"}) == 2
    output = capsys.readouterr().err
    record = json.loads(output)
    assert record["fields"]["error_code"] == code
    assert hint in record["message"]
    assert "private-credential" not in output and "db.test" not in output


def test_repository_has_ordered_paired_forward_and_rollback_migrations():
    migrations = load_migrations(ROOT)
    assert [migration.version for migration in migrations] == ["001", "002", "003", "004"]
    assert len(migrations[0].checksum) == 64
    assert "CREATE TABLE supermarket.products" in migrations[0].forward
    assert "DROP TABLE supermarket.products" in migrations[0].rollback


def project(tmp_path, filename="001_test.sql", forward="SELECT 1;\n", rollback="SELECT 2;\n"):
    (tmp_path / "db/migrations").mkdir(parents=True)
    (tmp_path / "db/rollback").mkdir(parents=True)
    (tmp_path / "db/migrations" / filename).write_bytes(forward.encode())
    if rollback is not None:
        (tmp_path / "db/rollback" / filename).write_bytes(rollback.encode())
    return tmp_path


def test_checksums_are_independent_of_windows_line_endings(tmp_path):
    root = project(tmp_path)
    original = load_migrations(root)[0].checksum
    (root / "db/migrations/001_test.sql").write_bytes(b"SELECT 1;\r\n")
    assert load_migrations(root)[0].checksum == original


def test_missing_rollback_is_rejected_before_connecting(tmp_path):
    with pytest.raises(MigrationError, match="MISSING_ROLLBACK"):
        load_migrations(project(tmp_path, rollback=None))


def test_duplicate_numeric_versions_are_rejected(tmp_path):
    root = project(tmp_path)
    (root / "db/migrations/0001_other.sql").write_text("SELECT 1;", encoding="utf-8")
    (root / "db/rollback/0001_other.sql").write_text("SELECT 2;", encoding="utf-8")
    with pytest.raises(MigrationError, match="DUPLICATE_VERSION"):
        load_migrations(root)


def test_files_without_versioned_names_are_not_read(tmp_path):
    root = project(tmp_path)
    (root / "db/migrations/unversioned.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="INVALID_MIGRATION_NAME"):
        load_migrations(root)


def test_cli_missing_admin_url_is_safe_and_makes_no_connection(monkeypatch, capsys):
    import json

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: pytest.fail("must not connect"))
    assert main(["status"], env={}) == 2
    record = json.loads(capsys.readouterr().err)
    assert record["fields"]["error_code"] == "DATABASE_URL_REQUIRED"


def test_cli_does_not_echo_invalid_connection_secrets(capsys):
    assert main(["status"], env={"MIGRATION_DATABASE_URL": "synthetic-secret"}) == 2
    assert "synthetic-secret" not in capsys.readouterr().err


def test_admin_connection_defaults_to_verified_tls(monkeypatch, capsys):
    from ingestor.repository import migrate

    received = {}

    def connect(url, **kwargs):
        received.update(kwargs)
        raise RuntimeError("postgresql://admin:synthetic-secret@db.test/db")

    monkeypatch.setattr(migrate.psycopg, "connect", connect)
    assert (
        main(
            ["status"],
            env={"MIGRATION_DATABASE_URL": "postgresql://admin:synthetic-secret@db.test/db"},
        )
        == 2
    )
    assert received["sslmode"] == "verify-full" and received["sslrootcert"] == "system"
    assert "synthetic-secret" not in capsys.readouterr().err


def test_admin_cli_requires_version_for_rollback_without_connecting(monkeypatch, capsys):
    from ingestor.repository import migrate

    monkeypatch.setattr(
        migrate.psycopg, "connect", lambda *args, **kwargs: pytest.fail("must not connect")
    )
    url = "postgresql://admin:synthetic-secret@db.test/db"
    assert main(["rollback"], env={"MIGRATION_DATABASE_URL": url}) == 2
    assert "ROLLBACK_VERSION_REQUIRED" in capsys.readouterr().err


@pytest.mark.parametrize("override", [None, "", "postgresql://admin:override-secret@db.test/admin"])
def test_existing_database_url_is_used_unless_a_nonempty_override_is_supplied(
    monkeypatch, capsys, override
):
    from ingestor.repository import migrate

    database_url = "postgresql://admin:default-secret@db.test/db"
    env = {"DATABASE_URL": database_url}
    if override is not None:
        env["MIGRATION_DATABASE_URL"] = override
    received = []

    def connect(url, **kwargs):
        received.append(url)
        raise RuntimeError("synthetic connection failure")

    monkeypatch.setattr(migrate.psycopg, "connect", connect)
    assert main(["status"], env=env) == 2
    assert received == [override or database_url]
    output = capsys.readouterr().err
    assert "default-secret" not in output and "override-secret" not in output
