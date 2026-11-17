from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "alembic_version",
    "projects",
    "principals",
    "project_acl",
    "scope_bindings",
    "context_events",
    "projection_offsets",
}


def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "src" / "contitext" / "migrations"))
    return config


def reset_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def test_upgrade_downgrade_reupgrade_and_schema(
    test_database_url: str, postgres_available: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()

    command.upgrade(config, "head")
    engine = create_engine(test_database_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == EXPECTED_TABLES
        assert {column["name"] for column in inspector.get_columns("context_events")} == {
            "event_id", "project_id", "principal_id", "scope_id", "session_id",
            "agent_id", "source_kind", "source_id", "event_kind", "payload",
            "idempotency_key", "created_at",
        }
        assert {
            index["name"] for index in inspector.get_indexes("context_events")
        } >= {
            "ix_context_events_project_created_event",
            "ix_context_events_project_kind_created",
            "ix_context_events_payload_search",
            "ix_context_events_project_source",
        }
        checks = {item["name"] for item in inspector.get_check_constraints("context_events")}
        assert "ck_context_events_kind" in checks
        acl_checks = {item["name"] for item in inspector.get_check_constraints("project_acl")}
        assert "ck_project_acl_role" in acl_checks
        created_at = next(
            column for column in inspector.get_columns("context_events")
            if column["name"] == "created_at"
        )
        assert "clock_timestamp" in str(created_at["default"])
        with engine.connect() as connection:
            index_definition = connection.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_context_events_payload_search'")
            ).scalar_one()
        assert "USING gin" in index_definition
        assert "to_tsvector" in index_definition
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(test_database_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(test_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_database_constraints_reject_invalid_values_and_duplicates(
    test_database_url: str, postgres_available: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    command.upgrade(alembic_config(), "head")
    engine = create_engine(test_database_url)
    principal_id = uuid4()
    event_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO projects (id, display_name, status) VALUES ('alpha', 'Alpha', 'active')")
            )
            connection.execute(
                text("INSERT INTO principals (id, name) VALUES (:id, 'Alice')"), {"id": principal_id}
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO project_acl (project_id, principal_id, role) VALUES ('alpha', :id, 'admin')"),
                    {"id": principal_id},
                )

        event_parameters = {
            "event_id": event_id,
            "project_id": "alpha",
            "principal_id": principal_id,
            "scope_id": "scope:1",
            "session_id": "session:1",
            "agent_id": "hermes",
            "source_kind": "hermes",
            "source_id": "hermes:session:1",
            "event_kind": "invalid",
            "payload": '{"text":"hello"}',
            "idempotency_key": "same-key",
        }
        insert_event = text(
            """INSERT INTO context_events
            (event_id, project_id, principal_id, scope_id, session_id, agent_id,
             source_kind, source_id, event_kind, payload, idempotency_key)
            VALUES (:event_id, :project_id, :principal_id, :scope_id, :session_id,
                    :agent_id, :source_kind, :source_id, :event_kind,
                    CAST(:payload AS jsonb), :idempotency_key)"""
        )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(insert_event, event_parameters)

        event_parameters["event_kind"] = "note"
        with engine.begin() as connection:
            connection.execute(insert_event, event_parameters)
        duplicate = dict(event_parameters, event_id=uuid4())
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(insert_event, duplicate)
    finally:
        engine.dispose()
