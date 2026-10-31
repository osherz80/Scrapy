import gzip
from dataclasses import replace
from datetime import UTC, datetime
from random import Random
from threading import Event

import psycopg
import pytest

from ingestor.cli import main
from ingestor.config import load_settings
from ingestor.logging import create_logger
from ingestor.providers.stream import SourceError
from ingestor.providers.types import Branch, BranchIdentity, BranchKind, FileKind, PublishedFile
from ingestor.repository.admission import admit_run
from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.repository.recovery import get_run_status
from ingestor.runs.worker import run_worker

from .conftest import ROOT


class Capture:
    def __init__(self):
        self.records = []
        self.heartbeat_failed = Event()

    def write(self, record):
        self.records.append(record)
        if record["event"] == "lease.heartbeat_failed":
            self.heartbeat_failed.set()

    def flush(self):
        pass


class FixtureProvider:
    source_chain_id = "7290000000000"

    def __init__(self, chain, *, action=None, listing_error=False, close_error=False):
        self.chain, self.action = chain, action
        self.listing_error, self.close_error = listing_error, close_error
        self.downloaded, self.closed = [], False

    def list_branches(self):
        if self.listing_error:
            raise SourceError("LISTING_FAILED")
        return tuple(
            Branch(BranchIdentity(self.chain, "001", str(i)), BranchKind.PHYSICAL_GROCERY)
            for i in range(3)
        )

    def iter_files(self):
        for branch in self.list_branches():
            yield PublishedFile(
                branch.identity,
                FileKind.PRICE_FULL,
                f"PriceFull{self.source_chain_id}-001-{branch.identity.store_id}.gz",
                "https://source.test/catalog?signature=synthetic-secret",
                datetime(2026, 10, 30, 6, tzinfo=UTC),
            )

    def download(self, ref):
        self.downloaded.append(ref.identity)
        if self.action:
            self.action()
        return gzip.compress(
            (
                f"<Root><ChainId>{self.source_chain_id}</ChainId><SubChainId>001</SubChainId>"
                f"<StoreId>{ref.identity.store_id}</StoreId><Items><Item><ItemCode>007</ItemCode>"
                "<ItemName>Private fixture product</ItemName>"
                f"<ItemPrice>{10 + int(ref.identity.store_id)}</ItemPrice>"
                "<Quantity>60</Quantity><UnitQty>ml</UnitQty><bIsWeighted>0</bIsWeighted>"
                "</Item></Items></Root>"
            ).encode()
        )

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("synthetic-private-close-error")


@pytest.fixture
def harness(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    connections = []

    def connect():
        connection = psycopg.connect(migration_db.info.dsn, autocommit=True)
        connection.execute("SET ROLE supermarket_ingestor")
        connections.append(connection)
        return connection

    return migration_db, connect, connections


def execute(harness, run_id, factory, **kwargs):
    _, connect, connections = harness
    capture = kwargs.pop("capture", Capture())
    result = run_worker(
        run_id,
        execution_id="12345:1",
        settings=kwargs.pop("settings", load_settings({})),
        connection_factory=connect,
        provider_factory=factory,
        logger=create_logger(transport=capture),
        rng=Random(1),
        **kwargs,
    )
    assert all(connection.closed for connection in connections)
    return result, capture


def test_worker_reads_only_authorized_chains_and_runs_full_pipeline(harness):
    db, _, connections = harness
    run = admit_run(db, ("victory", "osher-ad"))
    sources = []

    def factory(chain, settings, deadline):
        assert chain in run.chains and deadline > 0
        assert db.execute(
            "SELECT status,started_at IS NOT NULL FROM public.refresh_run_chains "
            "WHERE run_id=%s AND chain_id=%s",
            (run.id, chain),
        ).fetchone() == ("RUNNING", True)
        source = FixtureProvider(chain)
        sources.append(source)
        return source

    code, capture = execute(harness, run.id, factory)
    assert code == 0 and len(connections) == 2
    assert all(source.closed and len(source.downloaded) == 3 for source in sources)
    state = get_run_status(db, run.id)
    assert state.status == "SUCCEEDED" and state.github_run_id == "12345:1"
    assert db.execute(
        "SELECT chain_id,item_code,price,sample_count FROM public.products ORDER BY chain_id"
    ).fetchall() == [(chain, "007", 11, 3) for chain in run.chains]
    assert db.execute("SELECT count(*) FROM public.chain_leases").fetchone() == (0,)
    assert "Private fixture product" not in str(capture.records)
    assert "synthetic-secret" not in str(capture.records)
    assert any(record["event"] == "run.finished" for record in capture.records)


def test_cli_refresh_without_id_admits_and_publishes_using_worker_role(harness):
    db, connect, connections = harness
    assert (
        main(
            ["refresh"],
            env={
                "DATABASE_URL": "postgresql://synthetic:secret@db.test/db",
                "GITHUB_RUN_ID": "23456",
                "ENABLED_CHAINS": "victory",
            },
            connection_factory=connect,
            provider_factory=lambda chain, *_: FixtureProvider(chain),
            transport=Capture(),
        )
        == 0
    )
    assert db.execute("SELECT status FROM public.refresh_runs").fetchall() == [("SUCCEEDED",)]
    assert db.execute("SELECT chain_id,price,sample_count FROM public.products").fetchall() == [
        ("victory", 11, 3)
    ]
    assert all(connection.closed for connection in connections)


def test_cli_manual_conflict_preserves_existing_run_and_never_opens_provider(harness):
    db, connect, _ = harness
    admit_run(db, ("victory",))

    def forbidden(*_):
        pytest.fail("Conflict must prevent provider access")

    assert (
        main(
            ["refresh"],
            env={
                "DATABASE_URL": "postgresql://synthetic:secret@db.test/db",
                "GITHUB_RUN_ID": "23456",
                "ENABLED_CHAINS": "victory",
            },
            connection_factory=connect,
            provider_factory=forbidden,
            transport=Capture(),
        )
        == 1
    )
    assert db.execute("SELECT count(*) FROM public.refresh_runs").fetchone() == (1,)


def test_source_failure_does_not_prevent_other_chain_from_publishing(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory", "osher-ad"))
    code, _ = execute(
        harness, run.id, lambda chain, *_: FixtureProvider(chain, listing_error=chain == "osher-ad")
    )
    state = get_run_status(db, run.id)
    assert code == 1 and state.status == "PARTIAL_FAILED"
    assert {chain.chain_id: chain.error_code for chain in state.chains} == {
        "osher-ad": "LISTING_FAILED",
        "victory": None,
    }
    assert db.execute("SELECT chain_id FROM public.products").fetchall() == [("victory",)]


def test_duplicate_delivery_does_not_construct_source_or_renewal_connection(harness):
    db, _, connections = harness
    run = admit_run(db, ("victory",))
    assert execute(harness, run.id, lambda chain, *_: FixtureProvider(chain))[0] == 0
    before = len(connections)

    def forbidden(*args):
        pytest.fail("duplicate delivery reached source")

    assert execute(harness, run.id, forbidden)[0] == 0
    assert len(connections) == before + 1


def test_cancellation_preserves_published_chain_and_aborts_remaining_work(harness):
    db, _, _ = harness
    run = admit_run(db, ("osher-ad", "victory"))
    cancelled = Event()
    sources = []

    def factory(chain, *_):
        source = FixtureProvider(chain, action=cancelled.set if chain == "victory" else None)
        sources.append(source)
        return source

    code, _ = execute(harness, run.id, factory, cancelled=cancelled)
    assert code == 130 and get_run_status(db, run.id).status == "PARTIAL_FAILED"
    assert db.execute("SELECT chain_id FROM public.products").fetchall() == [("osher-ad",)]
    assert all(source.closed for source in sources)
    assert len(sources[1].downloaded) == 1


def test_heartbeat_database_failure_stops_before_publication(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory",))
    capture = Capture()
    source = FixtureProvider("victory", action=lambda: capture.heartbeat_failed.wait(4))

    def factory(*args):
        db.execute(
            "CREATE FUNCTION public.break_heartbeat() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'synthetic-private-database-error'; END $$"
        )
        db.execute(
            "CREATE TRIGGER break_heartbeat BEFORE UPDATE ON public.chain_leases "
            "FOR EACH ROW EXECUTE FUNCTION public.break_heartbeat()"
        )
        return source

    code, _ = execute(
        harness,
        run.id,
        factory,
        capture=capture,
        settings=replace(load_settings({}), heartbeat_seconds=1),
    )
    assert code == 1 and capture.heartbeat_failed.is_set()
    assert len(source.downloaded) == 1 and source.closed
    assert db.execute("SELECT count(*) FROM public.products").fetchone() == (0,)
    assert get_run_status(db, run.id).status == "FAILED"
    assert "synthetic-private" not in str(capture.records)


def test_deadline_is_checked_after_inflight_source_returns(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory",))
    now = [0.0]
    source = FixtureProvider("victory", action=lambda: now.__setitem__(0, 2800.0))
    code, capture = execute(harness, run.id, lambda *_: source, clock=lambda: now[0])
    assert code == 1 and len(source.downloaded) == 1 and source.closed
    assert get_run_status(db, run.id).status == "FAILED"
    assert "RUN_DEADLINE_EXCEEDED" in str(capture.records)


def test_cleanup_error_is_visible_and_does_not_discard_valid_catalog(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory",))
    code, capture = execute(
        harness, run.id, lambda chain, *_: FixtureProvider(chain, close_error=True)
    )
    assert code == 0 and get_run_status(db, run.id).status == "SUCCEEDED"
    assert any(record["event"] == "provider.close_failed" for record in capture.records)
    assert "synthetic-private" not in str(capture.records)


def test_injected_cli_executes_authorized_run_without_loading_environment_files(harness):
    db, connect, connections = harness
    run = admit_run(db, ("victory",))
    code = main(
        ["refresh", "--run-id", str(run.id)],
        env={
            "DATABASE_URL": "postgresql://unused:synthetic-secret@db.test/db",
            "GITHUB_RUN_ID": "12345",
        },
        provider_factory=lambda chain, *_: FixtureProvider(chain),
        connection_factory=connect,
        transport=Capture(),
    )
    assert code == 0 and get_run_status(db, run.id).status == "SUCCEEDED"
    assert all(connection.closed for connection in connections)


def test_unavailable_authorized_chain_fails_before_source_construction(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory",))

    def forbidden(*args):
        pytest.fail("disabled chain reached source")

    code, _ = execute(
        harness, run.id, forbidden, settings=load_settings({"ENABLED_CHAINS": "osher-ad"})
    )
    assert code == 1 and get_run_status(db, run.id).status == "FAILED"


def test_keyboard_interrupt_closes_source_and_finalizes_owned_run(harness):
    db, _, _ = harness
    run = admit_run(db, ("victory",))

    def interrupt():
        raise KeyboardInterrupt

    source = FixtureProvider("victory", action=interrupt)
    code, _ = execute(harness, run.id, lambda *_: source)
    assert code == 130 and source.closed
    assert get_run_status(db, run.id).status == "FAILED"


def test_publication_failure_aborts_run_but_preserves_previously_published_chain(harness):
    db, _, _ = harness
    run = admit_run(db, ("osher-ad", "victory"))
    db.execute(
        "CREATE FUNCTION public.fail_victory() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NEW.chain_id='victory' THEN RAISE EXCEPTION 'private-write-error'; "
        "END IF; RETURN NEW; END $$"
    )
    db.execute(
        "CREATE TRIGGER fail_victory BEFORE INSERT ON public.products "
        "FOR EACH ROW EXECUTE FUNCTION public.fail_victory()"
    )
    code, capture = execute(harness, run.id, lambda chain, *_: FixtureProvider(chain))
    assert code == 1 and get_run_status(db, run.id).status == "PARTIAL_FAILED"
    assert db.execute("SELECT chain_id FROM public.products").fetchall() == [("osher-ad",)]
    assert "private-write-error" not in str(capture.records)


def test_cli_handles_sigterm_cooperatively_and_restores_previous_handler(harness):
    import signal

    db, connect, _ = harness
    run = admit_run(db, ("victory",))
    before = signal.getsignal(signal.SIGTERM)

    def terminate():
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    code = main(
        ["refresh", "--run-id", str(run.id)],
        env={
            "DATABASE_URL": "postgresql://unused:synthetic-secret@db.test/db",
            "GITHUB_RUN_ID": "12345",
        },
        provider_factory=lambda chain, *_: FixtureProvider(chain, action=terminate),
        connection_factory=connect,
        transport=Capture(),
    )
    assert code == 130 and signal.getsignal(signal.SIGTERM) == before
    assert get_run_status(db, run.id).status == "FAILED"


def test_default_cli_connection_factory_uses_database_url_for_real_worker(harness, monkeypatch):
    from ingestor import cli

    db, _, _ = harness
    run = admit_run(db, ("victory",))
    monkeypatch.setattr(cli, "PublishedProvider", lambda chain, *_: FixtureProvider(chain))
    url = f"postgresql://{db.info.user}@127.0.0.1:{db.info.port}/{db.info.dbname}"
    assert (
        main(
            ["refresh", "--run-id", str(run.id)],
            env={"DATABASE_URL": url, "GITHUB_RUN_ID": "12345"},
            transport=Capture(),
        )
        == 0
    )
    assert get_run_status(db, run.id).status == "SUCCEEDED"
