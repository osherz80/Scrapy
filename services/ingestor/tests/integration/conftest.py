"""Real database tests require an explicitly designated disposable test database."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def db_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail(
            "TEST_DATABASE_URL is required for integration tests; use a disposable database"
        )
    return value


@pytest.fixture
def unmigrated_db(db_url):
    with psycopg.connect(db_url, connect_timeout=5) as connection:
        if not connection.info.dbname.startswith("ingestor_test"):
            pytest.fail("Integration database name must start with ingestor_test")
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.fixture
def db(unmigrated_db):
    unmigrated_db.execute((ROOT / "db/migrations/001_ingestion.sql").read_text(encoding="utf-8"))
    unmigrated_db.execute(
        (ROOT / "db/migrations/002_public_schema.sql").read_text(encoding="utf-8")
    )
    unmigrated_db.execute(
        (ROOT / "db/migrations/003_xml_item_fields.sql").read_text(encoding="utf-8")
    )
    return unmigrated_db


@pytest.fixture
def migration_db(db_url):
    parameters = conninfo_to_dict(db_url)
    if not parameters.get("dbname", "").startswith("ingestor_test"):
        pytest.fail("Migration tests require a disposable ingestor_test database")
    parameters["connect_timeout"] = "5"
    database_name = "ingestor_test_" + uuid4().hex
    with psycopg.connect(**parameters, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            parameters["dbname"] = database_name
            with psycopg.connect(**parameters, autocommit=True) as connection:
                yield connection
        finally:
            # Only remove the uniquely named database this fixture created.
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )
