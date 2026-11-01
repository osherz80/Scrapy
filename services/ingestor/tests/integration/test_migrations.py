import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from ingestor.repository.migrate import (
    MigrationError,
    apply_migrations,
    load_migrations,
    main,
    migration_status,
    rollback_migration,
)

ROOT = Path(__file__).resolve().parents[4]


def test_status_does_not_bootstrap_or_mutate_an_empty_database(migration_db):
    assert migration_status(migration_db, load_migrations(ROOT)) == ()
    assert migration_db.execute("SELECT to_regnamespace('supermarket')").fetchone()[0] is None


def test_apply_is_idempotent_and_records_forward_and_rollback_checksums(migration_db):
    migrations = load_migrations(ROOT)
    assert apply_migrations(migration_db, migrations) == ("001", "002", "003")
    assert apply_migrations(migration_db, migrations) == ()
    assert migration_status(migration_db, migrations) == ("001", "002", "003")
    record = migration_db.execute(
        "SELECT checksum,rollback_checksum FROM public.schema_migrations WHERE version='001'"
    ).fetchone()
    assert record == (migrations[0].checksum, migrations[0].rollback_checksum)


def test_changed_applied_sql_is_rejected_before_further_work(migration_db):
    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations)
    drifted = (replace(migrations[0], checksum="f" * 64), *migrations[1:])
    with pytest.raises(MigrationError, match="MIGRATION_DRIFT"):
        apply_migrations(migration_db, drifted)
    assert migration_db.execute("SELECT count(*) FROM public.chains").fetchone()[0] == 10


def test_explicit_rollback_removes_domain_tables_and_can_be_reapplied(migration_db):
    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations)
    rollback_migration(migration_db, migrations, version="003")
    rollback_migration(migration_db, migrations, version="002")
    rollback_migration(migration_db, migrations, version="001")
    assert migration_status(migration_db, migrations) == ()
    assert migration_db.execute("SELECT to_regclass('supermarket.products')").fetchone()[0] is None
    assert migration_db.execute(
        "SELECT rolcanlogin FROM pg_roles WHERE rolname='supermarket_ingestor'"
    ).fetchone() == (False,)
    assert apply_migrations(migration_db, migrations) == ("001", "002", "003")


def test_failed_sql_rolls_back_ddl_and_ledger_for_the_entire_batch(migration_db):
    migrations = load_migrations(ROOT)
    invalid_sql = "CREATE TABLE public.marker(id integer); SELECT definitely_missing_column;"
    broken = replace(
        migrations[0],
        version="004",
        name="004_broken.sql",
        forward=invalid_sql,
        checksum=hashlib.sha256(invalid_sql.encode()).hexdigest(),
    )
    with pytest.raises(psycopg.errors.UndefinedColumn):
        apply_migrations(migration_db, migrations + (broken,))
    assert migration_db.execute("SELECT to_regnamespace('supermarket')").fetchone()[0] is None


def test_concurrent_runners_apply_each_version_once(migration_db):
    migrations = load_migrations(ROOT)

    def apply_once(_):
        with psycopg.connect(migration_db.info.dsn, autocommit=True) as connection:
            return apply_migrations(connection, migrations)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(apply_once, range(2)))
    assert sorted(results) == [(), ("001", "002", "003")]
    assert migration_status(migration_db, migrations) == ("001", "002", "003")


def test_rollback_only_targets_the_latest_applied_version(migration_db):
    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations)
    with pytest.raises(MigrationError, match="ROLLBACK_MUST_TARGET_LATEST"):
        rollback_migration(migration_db, migrations, version="000")
    assert migration_status(migration_db, migrations) == ("001", "002", "003")


def test_cli_status_apply_and_rollback_use_only_explicit_admin_environment(migration_db):
    url = (
        f"postgresql://{migration_db.info.user}@127.0.0.1:"
        f"{migration_db.info.port}/{migration_db.info.dbname}"
    )
    env = {"DATABASE_URL": url}
    assert main(["status"], env=env) == 0
    assert main(["apply"], env=env) == 0
    assert main(["rollback", "--version", "003"], env=env) == 0
    assert main(["rollback", "--version", "002"], env=env) == 0
    assert main(["rollback", "--version", "001"], env=env) == 0
    assert migration_status(migration_db, load_migrations(ROOT)) == ()


def test_runtime_roles_cannot_modify_or_inspect_migration_history(migration_db):
    apply_migrations(migration_db, load_migrations(ROOT))
    for role in ("supermarket_search", "supermarket_control", "supermarket_ingestor"):
        with migration_db.transaction():
            migration_db.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with migration_db.transaction():
                    migration_db.execute(
                        "SELECT * FROM public.schema_migrations WHERE version='001'"
                    )


def test_upgrade_moves_existing_data_and_removes_legacy_schema(migration_db):
    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations[:1])
    migration_db.execute(
        "UPDATE supermarket.chains SET display_name='Preserved' WHERE id='rami-levy'"
    )
    assert apply_migrations(migration_db, migrations) == ("002", "003")
    assert migration_db.execute("SELECT to_regnamespace('supermarket')").fetchone()[0] is None
    assert (
        migration_db.execute(
            "SELECT display_name FROM public.chains WHERE id='rami-levy'"
        ).fetchone()[0]
        == "Preserved"
    )
    assert migration_status(migration_db, migrations) == ("001", "002", "003")


def test_xml_migration_preserves_known_existing_values_and_removes_old_columns(migration_db):
    from ingestor.repository.admission import admit_run

    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations[:2])
    run = admit_run(migration_db, ("victory",))
    migration_db.execute(
        "INSERT INTO public.products(chain_id,item_code,name,price,is_weighted,sample_count,"
        "source_updated_at,newest_source_updated_at,run_id,normalized_name,name_tokens,"
        "source_quantity,source_unit_qty,package_quantity,package_unit) "
        "VALUES ('victory','001','Existing',12.90,false,1,now(),now(),%s,'existing',"
        "ARRAY['existing'],60,'גרם',60,'g')",
        (run.id,),
    )
    assert apply_migrations(migration_db, migrations) == ("003",)
    assert migration_db.execute(
        "SELECT item_code,item_name,item_price,quantity,unit_qty FROM public.products"
    ).fetchone() == ("001", "Existing", "12.9000", "60", "גרם")
    columns = {
        r[0]
        for r in migration_db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='products'"
        ).fetchall()
    }
    assert not columns.intersection(
        {"compatibility_metadata", "source_updated_at", "newest_source_updated_at", "name", "price"}
    )
    rollback_migration(migration_db, migrations, version="003")
    assert migration_db.execute(
        "SELECT item_code,name,price::text FROM public.products"
    ).fetchone() == (
        "001",
        "Existing",
        "12.9000",
    )


def test_legacy_rollback_refuses_unrepresentable_raw_values_without_losing_rows(migration_db):
    from ingestor.repository.admission import admit_run

    migrations = load_migrations(ROOT)
    apply_migrations(migration_db, migrations)
    run = admit_run(migration_db, ("victory",))
    migration_db.execute(
        "INSERT INTO public.products(chain_id,item_code,item_price,sample_count,run_id) "
        "VALUES ('victory','001','not numeric',1,%s)",
        (run.id,),
    )
    with pytest.raises(psycopg.Error):
        rollback_migration(migration_db, migrations, version="003")
    assert migration_db.execute("SELECT item_price FROM public.products").fetchone() == (
        "not numeric",
    )
    assert migration_status(migration_db, migrations) == ("001", "002", "003")
