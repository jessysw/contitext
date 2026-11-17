from __future__ import annotations

import pytest

from contitext.config import ConfigurationError, Settings


def test_production_configuration_fails_closed() -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env({})


def test_sqlite_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        Settings.from_env(
            {"DATABASE_URL": "sqlite:///local.db", "CONTITEXT_AUTH_TOKENS": "{}"}
        )


def test_test_configuration_requires_dedicated_database() -> None:
    with pytest.raises(ConfigurationError, match="dedicated test database"):
        Settings.from_env(
            {"CONTITEXT_TEST_DATABASE_URL": "postgresql+psycopg://u:p@db/context"},
            testing=True,
        )
