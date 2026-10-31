import io

import pytest

from ingestor.environment import EnvironmentFileError, load_environment
from ingestor.logging.transports import ConsoleTransport


def test_local_file_loads_without_interpolation_or_process_mutation(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FILE_ONLY", raising=False)
    (tmp_path / ".env").write_text(
        '\ufeffDATABASE_URL="postgresql://worker:fake-${literal}@db.test/db"\n'
        "FILE_ONLY='quoted value'\n",
        encoding="utf-8",
    )
    env = load_environment(root=tmp_path)
    assert env["DATABASE_URL"] == "postgresql://worker:fake-${literal}@db.test/db"
    assert env["FILE_ONLY"] == "quoted value"
    import os

    assert "DATABASE_URL" not in os.environ and "FILE_ONLY" not in os.environ
    assert capsys.readouterr().out == "" and capsys.readouterr().err == ""


def test_process_environment_overrides_file_and_missing_file_is_optional(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://process:fake-secret@db.test/db")
    assert load_environment(root=tmp_path)["DATABASE_URL"].startswith("postgresql://process:")
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://file:fake-secret@db.test/db\n", encoding="utf-8"
    )
    assert load_environment(root=tmp_path)["DATABASE_URL"].startswith("postgresql://process:")


def test_explicit_mapping_bypasses_all_secret_file_access(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xffinvalid secret file")
    assert load_environment({}, root=tmp_path) == {}
    assert load_environment({"DATABASE_URL": "provided"}, root=tmp_path) == {
        "DATABASE_URL": "provided"
    }


@pytest.mark.parametrize("body", [b'DATABASE_URL="fake-private-secret\n', b"\xffprivate-secret"])
def test_bad_file_is_rejected_atomically_without_contents_in_diagnostics(tmp_path, body, capsys):
    (tmp_path / ".env").write_bytes(body)
    with pytest.raises(EnvironmentFileError, match="ENV_FILE_INVALID") as error:
        load_environment(root=tmp_path)
    assert "private-secret" not in str(error.value)
    captured = capsys.readouterr()
    assert "private-secret" not in captured.out + captured.err


def test_scraper_cli_resolves_default_environment_once(tmp_path, monkeypatch):
    from ingestor import cli, environment

    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://worker:fake-private-secret@db.test/db\n", encoding="utf-8"
    )
    calls = []

    def load(env=None):
        calls.append(True)
        return environment.load_environment(env, root=tmp_path)

    monkeypatch.setattr(cli, "load_environment", load)
    stream = io.StringIO()
    assert cli.main(["check-config", "--require-database"], transport=ConsoleTransport(stream)) == 0
    assert calls == [True] and "fake-private-secret" not in stream.getvalue()


def test_migration_cli_loads_file_without_echoing_url(tmp_path, monkeypatch, capsys):
    from ingestor import environment
    from ingestor.repository import migrate

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://worker:fake-private-secret@db.test/db\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        migrate,
        "load_environment",
        lambda env=None: environment.load_environment(env, root=tmp_path),
    )
    called = []

    def connect(url, **kwargs):
        called.append(True)
        assert "fake-private-secret" in url
        raise RuntimeError("fake-private-secret")

    monkeypatch.setattr(migrate.psycopg, "connect", connect)
    assert migrate.main(["status"]) == 2 and called == [True]
    assert "fake-private-secret" not in capsys.readouterr().err
