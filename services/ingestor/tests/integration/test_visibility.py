from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import psycopg
import pytest

from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.repository.publication import publish_collection

from .conftest import ROOT
from .test_publication import collection, owner_for


@pytest.fixture
def publication_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def test_readers_see_complete_catalog_and_one_snapshot_across_commit(publication_db):
    old_owner = owner_for(publication_db)
    publish_collection(publication_db, old_owner, collection("old-a", "old-b"))
    owner = owner_for(publication_db)
    publication_db.execute(
        "CREATE FUNCTION public.pause_insert() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN PERFORM pg_advisory_xact_lock(1397900114,1); RETURN NEW; END $$"
    )
    publication_db.execute(
        "CREATE TRIGGER pause_insert BEFORE INSERT ON public.products "
        "FOR EACH ROW EXECUTE FUNCTION public.pause_insert()"
    )
    publication_db.execute("SELECT pg_advisory_lock(1397900114,1)")
    writer_pid = Queue()

    def publish():
        with psycopg.connect(publication_db.info.dsn, autocommit=True) as writer:
            writer.execute("SET ROLE supermarket_ingestor")
            writer_pid.put(writer.info.backend_pid)
            return publish_collection(writer, owner, collection("new-a", "new-b", "new-c"))

    query = (
        "SELECT p.item_code,c.product_count,c.current_run_id,p.run_id "
        "FROM public.products p JOIN public.chains c ON c.id=p.chain_id "
        "WHERE c.id='victory' ORDER BY p.item_code"
    )
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(publish)
        try:
            pid = writer_pid.get(timeout=5)
            deadline = monotonic() + 5
            while not publication_db.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s "
                "AND locktype='advisory' AND NOT granted)",
                (pid,),
            ).fetchone()[0]:
                assert monotonic() < deadline, "Writer did not reach paused replacement"
                sleep(0.01)
            with psycopg.connect(publication_db.info.dsn, autocommit=True) as reader:
                reader.execute("SET ROLE supermarket_search")
                reader.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                old = [(code, 2, old_owner.run_id, old_owner.run_id) for code in ("old-a", "old-b")]
                assert reader.execute(query).fetchall() == old
                # The writer has deleted old rows and is waiting on insertion.
                # A separate normal reader still sees the full committed catalog.
                assert publication_db.execute(query).fetchall() == old
                publication_db.execute("SELECT pg_advisory_unlock(1397900114,1)")
                assert future.result(timeout=5)
                assert reader.execute(query).fetchall() == old
                reader.execute("COMMIT")
                assert reader.execute(query).fetchall() == [
                    (code, 3, owner.run_id, owner.run_id) for code in ("new-a", "new-b", "new-c")
                ]
        finally:
            publication_db.execute("SELECT pg_advisory_unlock(1397900114,1)")
