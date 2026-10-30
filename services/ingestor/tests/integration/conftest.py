"""Real database tests require an explicitly designated disposable test database."""

import os
from pathlib import Path

import psycopg
import pytest

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
def db(db_url):
    with psycopg.connect(db_url, connect_timeout=5) as connection:
        if not connection.info.dbname.startswith("ingestor_test"):
            pytest.fail("Integration database name must start with ingestor_test")
        try:
            connection.execute(
                (ROOT / "db/migrations/001_ingestion.sql").read_text(encoding="utf-8")
            )
            yield connection
        finally:
            connection.rollback()
