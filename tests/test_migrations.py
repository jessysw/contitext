from __future__ import annotations

from workspace_fixtures import seed_members


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
    "credentials",
    "credential_audit",
    "workspaces",
    "workspace_members",
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
            "idempotency_key", "created_at", "event_metadata",
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
                text("INSERT INTO projects (slug, workspace_id, display_name, status) VALUES ('alpha', '00000000-0000-4000-8000-000000000001', 'Alpha', 'active')")
            )
            project_uuid = connection.execute(text("SELECT id FROM projects WHERE slug='alpha'")).scalar_one()
            connection.execute(
                text("INSERT INTO principals (id, name) VALUES (:id, 'Alice')"), {"id": principal_id}
            )
            seed_members(connection)

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO project_acl (project_id, principal_id, role) VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'), :id, 'admin')"),
                    {"id": principal_id},
                )

        event_parameters = {
            "event_id": event_id,
            "project_id": project_uuid,
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


def test_080_upgrade_preserves_data_and_refuses_lossy_downgrade(test_database_url, postgres_available, monkeypatch, tmp_path):
    from contitext.upgrade import inspect_upgrade, compare_snapshot, write_snapshot
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()
    command.upgrade(config, "0001_foundation")
    from test_upgrade import seed_legacy
    seed_legacy(test_database_url)
    command.upgrade(config, "0003_workspaces")
    snapshot = tmp_path / "before.json"
    before = inspect_upgrade(test_database_url)
    assert before["ok"]
    write_snapshot(before, snapshot)
    command.upgrade(config, "head")
    after = inspect_upgrade(test_database_url)
    compare_snapshot(after, snapshot)
    assert after["ok"] and after["comparison"]["matches"]
    engine = create_engine(test_database_url)
    with engine.begin() as c:
        c.execute(text("UPDATE context_events SET event_metadata = CAST(:meta AS jsonb)"), {"meta": '{"candidate":true}'})
    with pytest.raises(RuntimeError, match="context metadata exists"):
        command.downgrade(config, "0003_workspaces")
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0004_context_metadata"
    engine.dispose()
