import json
import os
import subprocess
import sys

import pytest

from ingestor.cli import main
from ingestor.logging.transports import ConsoleTransport


def test_check_config_logs_safe_summary_and_flushes():
    import io

    stream = io.StringIO()
    code = main(["check-config"], env={}, transport=ConsoleTransport(stream))
    record = json.loads(stream.getvalue())
    assert code == 0
    assert record["event"] == "configuration.validated"
    assert record["fields"]["chain_count"] == 10


def test_required_database_error_is_sanitized(capsys):
    code = main(["check-config", "--require-database"], env={})
    record = json.loads(capsys.readouterr().err)
    assert code == 2
    assert record["event"] == "configuration.invalid"
    assert "DATABASE_URL" in record["message"]


@pytest.mark.parametrize(
    "args",
    [
        ["refresh", "--run-id", "secret-invalid-uuid"],
        ["scheduled", "--timezone", "secret-invalid-zone"],
        ["probe", "--chains", "secret-unknown-chain"],
        ["probe", "--max-branches", "0"],
        ["probe", "--max-branches", "4"],
    ],
)
def test_invalid_command_arguments_never_echo_values(args, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(args, env={})
    assert exit_info.value.code == 2
    assert "secret-" not in capsys.readouterr().err


def test_unwired_refresh_exits_explicitly_without_success_claim(capsys):
    code = main(
        ["refresh", "--run-id", "31318188-526e-4cad-aad2-c914228910fd"],
        env={"DATABASE_URL": "postgresql://worker:synthetic-secret@db.test/catalog"},
    )
    record = json.loads(capsys.readouterr().err)
    assert code == 3
    assert record["event"] == "command.unavailable"
    assert record["fields"]["entry_point"] == "refresh"
    assert "synthetic-secret" not in json.dumps(record)


def test_probe_rejects_disabled_chain(capsys):
    code = main(["probe", "--chains", "carrefour"], env={"ENABLED_CHAINS": "shufersal"})
    assert code == 2
    assert json.loads(capsys.readouterr().err)["event"] == "configuration.invalid"


def test_help_subprocess_needs_no_database_configuration():
    env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "ingestor.cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0
    assert "check-config" in result.stdout
    assert result.stderr == ""
