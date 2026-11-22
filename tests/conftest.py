"""Shared PostgreSQL fixtures for Contitext tests."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from contitext.config import ConfigurationError, Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    try:
        return Settings.from_env(testing=True).database_url
    except ConfigurationError as exc:
        pytest.fail(str(exc), pytrace=False)
        raise AssertionError("unreachable") from exc


@pytest.fixture(scope="session")
def postgres_available(test_database_url: str) -> None:
    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("show server_version_num")).scalar_one()
            if int(version) < 160000:
                pytest.fail("Contitext tests require PostgreSQL 16 or newer", pytrace=False)
    except OperationalError as exc:
        pytest.fail(f"dedicated Contitext test PostgreSQL is unavailable: {exc}", pytrace=False)
    finally:
        engine.dispose()


@pytest.fixture
def migrated_database_url(
    test_database_url: str,
    postgres_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setenv("CONTITEXT_COMPATIBILITY_WORKSPACE", "legacy")
    engine = create_engine(test_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()

    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "src" / "contitext" / "migrations"))
    command.upgrade(config, "head")
    return test_database_url


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DATABASE_URL", "CONTITEXT_TEST_DATABASE_URL", "CONTITEXT_AUTH_TOKENS"):
        monkeypatch.delenv(key, raising=False)
