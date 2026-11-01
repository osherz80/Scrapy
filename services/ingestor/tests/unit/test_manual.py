from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.runs import manual
from ingestor.runs.admission import AdmissionError


def test_manual_admits_all_enabled_chains_then_uses_regular_worker(monkeypatch):
    run_id = uuid4()
    connection = object()
    settings = load_settings({})
    calls = []

    def admit(actual, chains):
        assert actual is connection and chains == settings.enabled_chains
        calls.append("admit")
        return SimpleNamespace(id=run_id)

    def worker(actual, **kwargs):
        assert actual == run_id
        calls.append("worker")
        return 0

    monkeypatch.setattr(manual, "admit_run", admit)
    monkeypatch.setattr(manual, "run_worker", worker)
    assert (
        manual.run_manual(
            settings=settings,
            logger=create_logger(),
            connection_factory=lambda: nullcontext(connection),
        )
        == 0
    )
    assert calls == ["admit", "worker"]


def test_existing_api_run_does_not_create_another_admission(monkeypatch):
    run_id = uuid4()
    monkeypatch.setattr(manual, "run_worker", lambda actual, **_: 0 if actual == run_id else 1)
    assert manual.run_manual(run_id, logger=create_logger()) == 0


def test_admission_conflict_does_not_start_worker(monkeypatch, capsys):
    def conflict(*_):
        raise AdmissionError("CHAIN_BUSY")

    monkeypatch.setattr(manual, "admit_run", conflict)
    assert (
        manual.run_manual(
            settings=load_settings({}),
            logger=create_logger(),
            connection_factory=lambda: nullcontext(object()),
        )
        == 1
    )
    assert "CHAIN_BUSY" in capsys.readouterr().err
