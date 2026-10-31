import io
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from ingestor.aggregation import aggregate_catalogs
from ingestor.collection import ChainCollection
from ingestor.logging import create_logger
from ingestor.logging.transports import ConsoleTransport
from ingestor.models import ParsedCatalog, ProductObservation
from ingestor.providers.types import BranchIdentity
from ingestor.repository.admission import admit_run
from ingestor.repository.migrate import apply_migrations, load_migrations
from ingestor.repository.ownership import claim_run, heartbeat
from ingestor.repository.publication import PublicationError, publish_collection
from ingestor.runs.ownership import OwnershipError

from .conftest import ROOT

SOURCE_TIME = datetime(2026, 10, 29, 6, tzinfo=UTC)


def collection(*codes, chain_id="victory", source_time=SOURCE_TIME, successes=1):
    branches = tuple(BranchIdentity(chain_id, "001", str(i)) for i in range(successes))
    catalogs = tuple(
        ParsedCatalog(
            branch,
            "7290000000000",
            source_time,
            tuple(
                ProductObservation(
                    code,
                    "Example",
                    Decimal("12.3456"),
                    False,
                    source_quantity=Decimal(60),
                    source_unit_qty="ml",
                )
                for code in codes
            ),
            2,
            0,
            0,
            frozenset(),
        )
        for branch in branches
    )
    result = aggregate_catalogs(catalogs, chain_id=chain_id)
    return ChainCollection(result, branches, branches, 0)


@pytest.fixture
def publication_db(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    return migration_db


def owner_for(connection, chains=("victory",)):
    run = admit_run(connection, chains)
    return claim_run(connection, run.id, "12345:1")


def snapshot(connection):
    return tuple(
        connection.execute(query).fetchall()
        for query in (
            "SELECT * FROM public.products ORDER BY chain_id,item_code",
            "SELECT * FROM public.chains ORDER BY id",
            "SELECT * FROM public.refresh_run_chains ORDER BY run_id,chain_id",
            "SELECT * FROM public.chain_leases ORDER BY chain_id",
        )
    )


def test_one_branch_publication_commits_catalog_metadata_and_outcome(publication_db):
    owner = owner_for(publication_db)
    publication_db.execute("SET ROLE supermarket_ingestor")
    assert publish_collection(publication_db, owner, collection("001234", "other"))
    assert publication_db.execute(
        "SELECT item_code,price,sample_count,package_quantity,package_unit,source_quantity,"
        "source_unit_qty,source_updated_at,newest_source_updated_at,run_id "
        "FROM public.products "
        "ORDER BY item_code"
    ).fetchall() == [
        (
            code,
            Decimal("12.3456"),
            1,
            Decimal(60),
            "ml",
            Decimal(60),
            "ml",
            SOURCE_TIME,
            SOURCE_TIME,
            owner.run_id,
        )
        for code in ("001234", "other")
    ]
    assert publication_db.execute(
        "SELECT current_run_id,product_count,source_updated_at,catalog_updated_at>SOURCE_TIME "
        "FROM public.chains CROSS JOIN (SELECT %s::timestamptz AS SOURCE_TIME) t "
        "WHERE id='victory'",
        (SOURCE_TIME,),
    ).fetchone() == (owner.run_id, 2, SOURCE_TIME, True)
    assert publication_db.execute(
        "SELECT status,attempt_count,successful_branch_count,product_count,invalid_row_count,"
        "started_at IS NOT NULL,finished_at IS NOT NULL FROM public.refresh_run_chains"
    ).fetchone() == ("SUCCEEDED", 1, 1, 2, 2, True, True)
    assert publication_db.execute("SELECT count(*) FROM public.chain_leases").fetchone() == (0,)


def test_success_removes_absent_products_and_preserves_other_chain(publication_db):
    owner = owner_for(publication_db, ("victory", "osher-ad"))
    publish_collection(publication_db, owner, collection("keep", "remove"))
    publish_collection(publication_db, owner, collection("untouched", chain_id="osher-ad"))
    next_owner = owner_for(publication_db)
    publish_collection(publication_db, next_owner, collection("keep", "new"))
    assert publication_db.execute(
        "SELECT chain_id,item_code FROM public.products ORDER BY chain_id,item_code"
    ).fetchall() == [("osher-ad", "untouched"), ("victory", "keep"), ("victory", "new")]


@pytest.mark.parametrize("no_branches", [True, False])
def test_unpublishable_result_preserves_catalog_and_records_failed_chain(
    publication_db, no_branches
):
    old_owner = owner_for(publication_db)
    publish_collection(publication_db, old_owner, collection("keep"))
    old = snapshot(publication_db)[:2]
    owner = owner_for(publication_db)
    result = collection(successes=0) if no_branches else collection("discarded")
    if no_branches:
        result = replace(
            result,
            attempted_branches=tuple(BranchIdentity("victory", "001", str(i)) for i in range(9)),
            failed_attempt_count=9,
        )
    else:
        result = replace(
            result, aggregation=replace(result.aggregation, products=(), conflict_count=1)
        )
    assert not publish_collection(publication_db, owner, result)
    assert snapshot(publication_db)[:2] == old
    assert publication_db.execute(
        "SELECT status,error_code,product_count FROM public.refresh_run_chains WHERE run_id=%s",
        (owner.run_id,),
    ).fetchone() == (
        "FAILED",
        "NO_SUCCESSFUL_BRANCHES" if no_branches else "NO_PUBLISHABLE_PRODUCTS",
        0,
    )
    assert heartbeat(publication_db, owner) == 0


@pytest.mark.parametrize("fault", ["insert", "metadata", "expire_during_insert"])
def test_mid_transaction_failures_roll_back_catalog_outcome_and_lease(publication_db, fault):
    old_owner = owner_for(publication_db)
    publish_collection(publication_db, old_owner, collection("old"))
    owner = owner_for(publication_db)
    before = snapshot(publication_db)
    if fault == "expire_during_insert":
        body = (
            "UPDATE public.chain_leases SET heartbeat_at=clock_timestamp()-interval '2 hours',"
            " expires_at=clock_timestamp()-interval '1 hour' "
            "WHERE chain_id=NEW.chain_id; RETURN NEW;"
        )
    else:
        body = "RAISE EXCEPTION 'synthetic-private-database-detail';"
    table, event = ("chains", "UPDATE") if fault == "metadata" else ("products", "INSERT")
    publication_db.execute(
        f"CREATE FUNCTION public.inject_failure() RETURNS trigger "
        f"LANGUAGE plpgsql AS $$ BEGIN {body} END $$"
    )
    publication_db.execute(
        f"CREATE TRIGGER inject_failure BEFORE {event} ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.inject_failure()"
    )
    stream = io.StringIO()
    with pytest.raises(OwnershipError if fault == "expire_during_insert" else psycopg.Error):
        publish_collection(
            publication_db,
            owner,
            collection("new"),
            logger=create_logger(transport=ConsoleTransport(stream)),
        )
    assert snapshot(publication_db) == before
    assert "synthetic-private" not in stream.getvalue()
    assert "publication.failed" in stream.getvalue()


@pytest.mark.parametrize("fault", ["expired", "wrong_token", "deadline", "unauthorized"])
def test_stale_or_unauthorized_owner_cannot_modify_catalog(publication_db, fault):
    owner = owner_for(publication_db)
    if fault == "expired":
        publication_db.execute(
            "UPDATE public.chain_leases SET heartbeat_at=clock_timestamp()-"
            "interval '2 hours',expires_at=clock_timestamp()-interval '1 hour'"
        )
    elif fault == "wrong_token":
        owner = replace(owner, token=uuid4())
    elif fault == "deadline":
        owner = replace(owner, deadline=datetime.now(UTC) - timedelta(seconds=1))
    before = snapshot(publication_db)
    with pytest.raises((OwnershipError, PublicationError)):
        publish_collection(
            publication_db,
            owner,
            collection("new", chain_id="osher-ad" if fault == "unauthorized" else "victory"),
        )
    assert snapshot(publication_db) == before


def test_duplicate_publication_is_rejected_without_overwriting_success(publication_db):
    owner = owner_for(publication_db)
    publish_collection(publication_db, owner, collection("original"))
    before = snapshot(publication_db)
    with pytest.raises(PublicationError, match="CHAIN_ALREADY_FINISHED"):
        publish_collection(publication_db, owner, collection("replacement"))
    assert snapshot(publication_db) == before


def test_old_source_watermark_is_not_replaced_with_ingestion_time(publication_db):
    owner = owner_for(publication_db)
    earlier = SOURCE_TIME - timedelta(days=20)
    publish_collection(
        publication_db, owner, collection("old-source", source_time=earlier, successes=3)
    )
    assert publication_db.execute(
        "SELECT source_updated_at,catalog_updated_at>%s FROM public.chains WHERE id='victory'",
        (earlier,),
    ).fetchone() == (earlier, True)
    assert publication_db.execute("SELECT sample_count FROM public.products").fetchone() == (3,)


@pytest.mark.parametrize(
    "fault", ["duplicate", "mixed_chain", "bad_time", "extra_precision", "bad_attempts"]
)
def test_invalid_collection_fails_without_mutation(publication_db, fault):
    owner = owner_for(publication_db)
    result = collection("new")
    product = result.aggregation.products[0]
    if fault == "bad_attempts":
        result = replace(result, attempted_branches=())
    else:
        products = {
            "duplicate": (product, product),
            "mixed_chain": (replace(product, chain_id="osher-ad"),),
            "bad_time": (replace(product, source_updated_at=SOURCE_TIME.replace(tzinfo=None)),),
            "extra_precision": (replace(product, price=Decimal("1.00001")),),
        }[fault]
        result = replace(result, aggregation=replace(result.aggregation, products=products))
    before = snapshot(publication_db)
    with pytest.raises(PublicationError, match="INVALID_PUBLICATION"):
        publish_collection(publication_db, owner, result)
    assert snapshot(publication_db) == before


@pytest.mark.parametrize("new_published", [False, True])
def test_expired_owner_cannot_overwrite_new_run(publication_db, new_published):
    old_owner = owner_for(publication_db)
    # Simulate a missing reservation; admission must reconcile the old run
    # before reserving the same chain for its replacement.
    publication_db.execute("DELETE FROM public.chain_leases WHERE run_id=%s", (old_owner.run_id,))
    new_owner = owner_for(publication_db)
    if new_published:
        publish_collection(publication_db, new_owner, collection("newer"))
    before = snapshot(publication_db)
    with pytest.raises(OwnershipError, match="LEASE_LOST"):
        publish_collection(publication_db, old_owner, collection("stale-overwrite"))
    assert snapshot(publication_db) == before


def test_attempt_summary_and_logs_are_bounded_metadata_only(publication_db):
    owner = owner_for(publication_db)
    result = collection("private-product-code")
    failed = BranchIdentity("victory", "002", "0")
    result = replace(
        result, attempted_branches=(failed, *result.attempted_branches), failed_attempt_count=1
    )
    stream = io.StringIO()
    publish_collection(
        publication_db, owner, result, logger=create_logger(transport=ConsoleTransport(stream))
    )
    assert publication_db.execute(
        "SELECT attempt_count,sampled_branch_ids FROM public.refresh_run_chains"
    ).fetchone() == (
        2,
        [
            {"subchain_id": "002", "store_id": "0", "successful": False},
            {"subchain_id": "001", "store_id": "0", "successful": True},
        ],
    )
    assert "private-product-code" not in stream.getvalue()
    assert SOURCE_TIME.isoformat() in stream.getvalue()
    assert "source_age_hours" in stream.getvalue()
