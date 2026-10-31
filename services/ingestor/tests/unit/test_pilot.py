import io
from types import SimpleNamespace

from ingestor import pilot
from ingestor.cli import main
from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.providers.stream import SourceError


def test_pilot_cli_uses_production_collection_closes_provider_and_never_opens_database(monkeypatch):
    closed = []
    provider = SimpleNamespace(close=lambda: closed.append(True))
    calls = []

    def collect(source, **kwargs):
        calls.append((source, kwargs["chain_id"]))
        kwargs["check"]()
        return SimpleNamespace(
            aggregation=SimpleNamespace(can_publish=True, products=("private product",)),
            successful_branches=(1, 2, 3),
            attempted_branches=(1, 2, 3),
        )

    monkeypatch.setattr(pilot, "collect_chain", collect)
    stream = io.StringIO()

    def forbidden():
        raise AssertionError("Database access forbidden")

    assert (
        main(
            ["pilot", "--chains", "rami-levy"],
            env={},
            transport=ConsoleTransport(stream),
            provider_factory=lambda *_: provider,
            connection_factory=forbidden,
        )
        == 0
    )
    assert calls == [(provider, "rami-levy")] and closed == [True]
    assert '"product_count": 1' in stream.getvalue()
    assert "private product" not in stream.getvalue()


def test_source_failure_continues_to_other_chains_and_cleans_up(monkeypatch):
    visited, closed = [], []

    def factory(chain, *_):
        visited.append(chain)
        return SimpleNamespace(close=lambda: closed.append(chain))

    def fail(*args, **kwargs):
        raise SourceError("HTTP_403")

    monkeypatch.setattr(pilot, "collect_chain", fail)
    assert (
        pilot.run_pilot(("rami-levy", "victory"), load_settings({}), create_logger(), factory) == 1
    )
    assert visited == closed == ["rami-levy", "victory"]


def test_expired_deadline_stops_before_provider_io():
    ticks = iter([0, 2701, 2701, 2701, 2701])

    def forbidden(*args):
        raise AssertionError("Provider must not be opened")

    assert (
        pilot.run_pilot(
            ("rami-levy",), load_settings({}), create_logger(), forbidden, clock=lambda: next(ticks)
        )
        == 1
    )


def test_deferred_chain_rejected_before_provider_io():
    assert pilot.run_pilot(("carrefour",), load_settings({}), create_logger(), None) == 2
