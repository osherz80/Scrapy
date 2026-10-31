from pathlib import Path

import pytest

from ingestor.repository.connection import DatabaseConnectionError, make_connection_factory


@pytest.mark.parametrize("template", ["", ":[YOUR-PASSWORD]", ":old-password"])
def test_raw_password_goes_directly_to_driver_without_uri_encoding(template, monkeypatch):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from ingestor.repository import connection

    raw = "a@b:#%/ ?[]\\\"'\nעברית"
    received = []
    monkeypatch.setattr(connection.psycopg, "connect", lambda url, **kw: received.append((url, kw)))
    factory = make_connection_factory(
        f"postgresql://postgres.project{template}@pool.test:5432/postgres",
        env={"DATABASE_PASSWORD": raw},
    )
    factory()
    dsn, options = received[0]
    assert options["password"] == raw
    assert conninfo_to_dict(dsn)["user"] == "postgres.project"
    assert "password" not in conninfo_to_dict(dsn)
    assert conninfo_to_dict(make_conninfo(dsn, password=options["password"]))["password"] == raw
    assert raw not in dsn and raw not in repr(factory)
    assert options["sslmode"] == "verify-full"


def test_settings_accept_supabase_template_with_separate_password():
    from ingestor.config import load_settings

    settings = load_settings(
        {
            "DATABASE_URL": "postgresql://postgres.project:[YOUR-PASSWORD]@pool.test:5432/postgres",
            "DATABASE_PASSWORD": "literal@#%password",
        },
        require_database=True,
    )
    assert settings.database_url and "literal@#%password" not in repr(settings)


def test_project_ca_certificate_is_used_without_weakening_verification(tmp_path, monkeypatch):
    from ingestor.repository import connection

    certificate = tmp_path / "certs/supabase-ca.crt"
    certificate.parent.mkdir()
    certificate.write_text("synthetic public CA", encoding="utf-8")
    received = {}
    monkeypatch.setattr(connection.psycopg, "connect", lambda url, **kw: received.update(kw))
    factory = make_connection_factory(
        "postgresql://worker:secret@db.test/catalog",
        env={"DATABASE_SSLROOTCERT": "certs/supabase-ca.crt"},
        root=tmp_path,
    )
    factory()
    assert received["sslmode"] == "verify-full"
    assert received["sslrootcert"] == str(certificate.resolve())


@pytest.mark.parametrize("certificate", ["missing.crt", "../outside.crt", "certs"])
def test_unusable_ca_path_fails_with_static_diagnostic(tmp_path, certificate):
    (tmp_path / "certs").mkdir()
    with pytest.raises(DatabaseConnectionError, match="DATABASE_CA_FILE_INVALID"):
        make_connection_factory(
            "postgresql://worker:secret@db.test/catalog",
            env={"DATABASE_SSLROOTCERT": certificate},
            root=tmp_path,
        )


def test_worker_connection_uses_existing_url_and_forces_tls_and_timeouts(monkeypatch):
    from ingestor.repository import connection

    calls = []
    sentinel = object()

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return sentinel

    monkeypatch.setattr(connection.psycopg, "connect", connect)
    url = "postgresql://worker:synthetic-secret@db.test/catalog?sslmode=disable"
    factory = make_connection_factory(url, env={})
    assert factory() is sentinel
    actual, options = calls[0]
    assert actual == url and options["autocommit"]
    assert options["sslmode"] == "verify-full" and options["sslrootcert"] == "system"
    assert options["connect_timeout"] == 10 and "statement_timeout=15000" in options["options"]
    assert Path(options["passfile"]).is_relative_to(Path.cwd())
    assert options["keepalives"] == 1 and options["tcp_user_timeout"] == 15000
    assert "synthetic-secret" not in repr(factory)


@pytest.mark.parametrize(
    "url,env",
    [
        ("invalid-synthetic-secret", {}),
        ("postgresql://worker:synthetic-secret@db.test/catalog?service=file", {}),
        ("postgresql://worker:synthetic-secret@db.test/catalog", {"PGSERVICE": "secret-service"}),
        ("postgresql://worker@127.0.0.1/ingestor_test?host=db.test", {}),
        ("postgresql://worker@127.0.0.1/ingestor_test?dbname=production", {}),
    ],
)
def test_connection_validation_never_opens_files_or_echoes_values(url, env):
    with pytest.raises(DatabaseConnectionError) as error:
        make_connection_factory(url, env=env)
    assert "synthetic-secret" not in str(error.value) and "secret-service" not in str(error.value)
