from pathlib import Path

import pytest

from ingestor.repository.connection import DatabaseConnectionError, make_connection_factory


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
