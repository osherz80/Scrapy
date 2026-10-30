from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql


def seed_run(db):
    run_id = uuid4()
    db.execute(
        "INSERT INTO supermarket.refresh_runs(id, origin, requested_chains) "
        "VALUES (%s, 'MANUAL', %s)",
        (run_id, ["rami-levy"]),
    )
    db.execute(
        "INSERT INTO supermarket.refresh_run_chains(run_id, chain_id) VALUES (%s, 'rami-levy')",
        (run_id,),
    )
    return run_id


def insert_product(db, run_id, *, code="001234", price="10.9000", sample_count=1):
    db.execute(
        """INSERT INTO supermarket.products(
        chain_id, item_code, name, price, is_weighted, sample_count, source_updated_at,
        newest_source_updated_at, run_id, normalized_name, name_tokens
    ) VALUES ('rami-levy', %s, 'Example', %s, false, %s, now(), now(), %s, 'example', %s)""",
        (code, price, sample_count, run_id, ["example"]),
    )


def test_six_domain_tables_and_ten_chains_are_seeded_with_two_deferred(db):
    tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='supermarket'").fetchall()
    assert {row[0] for row in tables} == {
        "chains",
        "products",
        "refresh_runs",
        "refresh_run_chains",
        "chain_leases",
        "schedule_claims",
    }
    chains = db.execute("SELECT id, enabled FROM supermarket.chains").fetchall()
    assert len(chains) == 10
    assert {name for name, enabled in chains if not enabled} == {"carrefour", "shufersal"}


def test_exact_codes_preserve_leading_zeros_and_required_indexes_exist(db):
    run_id = seed_run(db)
    insert_product(db, run_id, code="001")
    insert_product(db, run_id, code="1")
    assert db.execute(
        "SELECT item_code FROM supermarket.products ORDER BY item_code"
    ).fetchall() == [("001",), ("1",)]
    indexes = dict(
        db.execute(
            "SELECT indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='supermarket' AND tablename='products'"
        ).fetchall()
    )
    assert "USING gin" in indexes["products_name_tokens_idx"]
    assert "(item_code)" in indexes["products_item_code_idx"]


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "10000000000"])
def test_nonpositive_nonfinite_or_out_of_range_prices_are_rejected_by_postgres(db, price):
    run_id = seed_run(db)
    with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.NumericValueOutOfRange)):
        with db.transaction():
            insert_product(db, run_id, price=price)


@pytest.mark.parametrize("count", [0, 4])
def test_database_enforces_one_to_three_observations(db, count):
    run_id = seed_run(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            insert_product(db, run_id, sample_count=count)


def test_current_products_prevent_pruning_their_publication_run(db):
    run_id = seed_run(db)
    insert_product(db, run_id)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            db.execute("DELETE FROM supermarket.refresh_runs WHERE id=%s", (run_id,))
    assert db.execute("SELECT count(*) FROM supermarket.products").fetchone()[0] == 1


@pytest.mark.parametrize(
    "role", ["supermarket_search", "supermarket_control", "supermarket_ingestor"]
)
def test_runtime_roles_cannot_create_schema_objects_or_escalate(db, role):
    db.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
    assert db.execute("SELECT current_user").fetchone()[0] == role
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("CREATE TABLE supermarket.unauthorized(id integer)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction():
            db.execute("CREATE ROLE unauthorized LOGIN SUPERUSER")


def test_search_role_can_only_read_catalogs(db):
    insert_product(db, seed_run(db))
    db.execute("SET LOCAL ROLE supermarket_search")
    assert db.execute("SELECT count(*) FROM supermarket.products").fetchone()[0] == 1
    for statement in ("DELETE FROM supermarket.products", "SELECT * FROM supermarket.refresh_runs"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute(statement)


def test_control_role_cannot_read_or_write_catalog_prices(db):
    seed_run(db)
    db.execute("SET LOCAL ROLE supermarket_control")
    assert db.execute("SELECT count(*) FROM supermarket.refresh_runs").fetchone()[0] == 1
    for statement in ("SELECT * FROM supermarket.products", "DELETE FROM supermarket.products"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute(statement)


def test_public_has_no_schema_usage(db):
    privileges = db.execute("""SELECT privilege_type FROM pg_namespace,
        LATERAL aclexplode(nspacl) WHERE nspname='supermarket' AND grantee=0""").fetchall()
    assert privileges == []


def test_writer_can_publish_rows_but_cannot_change_enabled_chains_or_truncate(db):
    run_id = seed_run(db)
    db.execute("SET LOCAL ROLE supermarket_ingestor")
    insert_product(db, run_id)
    db.execute("UPDATE supermarket.chains SET product_count=1 WHERE id='rami-levy'")
    for statement in (
        "UPDATE supermarket.chains SET enabled=true",
        "TRUNCATE supermarket.products",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction():
                db.execute(statement)


@pytest.mark.parametrize("chains", [[], ["unknown"], ["rami-levy", "rami-levy"], [None]])
def test_control_admission_rejects_invalid_chain_sets_at_the_database_boundary(db, chains):
    db.execute("SET LOCAL ROLE supermarket_control")
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute(
                """INSERT INTO supermarket.refresh_runs(id,origin,requested_chains)
                VALUES (%s,'MANUAL',%s)""",
                (uuid4(), chains),
            )


def test_package_columns_cannot_mix_unknown_and_known_conversion_pairs(db):
    run_id = seed_run(db)
    insert_product(db, run_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute("UPDATE supermarket.products SET source_quantity=60, source_unit_qty='ml'")


def test_supabase_style_anonymous_default_grants_are_removed(unmigrated_db):
    root = Path(__file__).resolve().parents[4]
    db = unmigrated_db
    for role in ("anon", "authenticated"):
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            db.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
    db.execute(
        "CREATE SCHEMA supermarket; GRANT USAGE ON SCHEMA supermarket TO anon, authenticated"
    )
    db.execute("""ALTER DEFAULT PRIVILEGES IN SCHEMA supermarket
        GRANT ALL ON TABLES TO anon, authenticated""")
    db.execute((root / "db/migrations/001_ingestion.sql").read_text(encoding="utf-8"))
    for role in ("anon", "authenticated"):
        assert not db.execute(
            "SELECT has_schema_privilege(%s,'supermarket','USAGE')", (role,)
        ).fetchone()[0]
        assert not db.execute(
            "SELECT has_table_privilege(%s,'supermarket.products','SELECT')", (role,)
        ).fetchone()[0]
