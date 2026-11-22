"""Verify UUID referential integrity and fail-closed schema changes."""
import json
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from contitext.auth import PrincipalIdentity
from contitext.db import create_session_factory
from contitext.repository import Repository
from test_migrations import alembic_config, reset_schema


def test_old_project_identifiers_map_without_rewriting_history(test_database_url, postgres_available, monkeypatch):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()
    command.upgrade(config, "0002_credentials")
    engine = create_engine(test_database_url)
    principal, event = uuid4(), uuid4()
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO projects (id,display_name,status) VALUES ('old-project','Old name','active')"))
            c.execute(text("INSERT INTO principals (id,name) VALUES (:id,'Old principal')"), {"id": principal})
            c.execute(text("INSERT INTO project_acl VALUES ('old-project',:id,'owner')"), {"id": principal})
            c.execute(text("INSERT INTO scope_bindings (principal_id,scope_id,project_id,session_id) VALUES (:id,'old-scope','old-project','old-session')"), {"id": principal})
            c.execute(text("""INSERT INTO context_events (event_id,project_id,principal_id,scope_id,session_id,agent_id,source_kind,source_id,event_kind,payload,idempotency_key)
                VALUES (:event,'old-project',:id,'old-scope','old-session','old-agent','test','old-source','checkpoint','{"summary":"Old content"}','old-key')"""), {"event": event, "id": principal})
            c.execute(text("INSERT INTO projection_offsets (project_id,last_event_id) VALUES ('old-project',:event)"), {"event": event})
            before = c.execute(text("SELECT row_to_json(e) FROM context_events e")).scalar_one()
            binding_before = c.execute(text("SELECT row_to_json(b) FROM scope_bindings b")).scalar_one()
        command.upgrade(config, "head")
        with engine.connect() as c:
            project_id = c.execute(text("SELECT id FROM projects WHERE slug='old-project'")).scalar_one()
            assert isinstance(project_id, UUID)
            after = c.execute(text("SELECT row_to_json(e) FROM context_events e")).scalar_one()
            binding_after = c.execute(text("SELECT row_to_json(b) FROM scope_bindings b")).scalar_one()
            assert after == {**before, "project_id": str(project_id), "event_metadata": None}
            assert binding_after == {**binding_before, "project_id": str(project_id)}
            for table in ("project_acl", "projection_offsets"):
                assert c.execute(text(f"SELECT project_id FROM {table}")).scalar_one() == project_id
            assert c.execute(text("SELECT role FROM workspace_members WHERE principal_id=:id"), {"id": principal}).scalar_one() == "member"
        repository = Repository(create_session_factory(engine), compatibility_workspace="legacy")
        identity = PrincipalIdentity(principal, "Old principal")
        assert repository.current_project(identity, "old-scope").project_id == "old-project"
        assert repository.get_context(identity, "old-project").status.event_id == event
        assert repository.get_context(identity, "legacy/old-project").status.event_id == event
        with pytest.raises(RuntimeError, match="workspace data exists"):
            command.downgrade(config, "0002_credentials")
        assert repository.ready()
    finally:
        engine.dispose()


@pytest.mark.parametrize("old_id", ["not/a/slug", "x" * 129])
def test_incompatible_legacy_name_rolls_back_entire_workspace_migration(test_database_url, postgres_available, monkeypatch, old_id):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()
    command.upgrade(config, "0002_credentials")
    engine = create_engine(test_database_url)
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO projects (id,display_name,status) VALUES (:id,'Preserve me','active')"), {"id": old_id})
        with pytest.raises(IntegrityError):
            command.upgrade(config, "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0002_credentials"
            assert c.execute(text("SELECT id FROM projects")).scalar_one() == old_id
            assert c.execute(text("SELECT to_regclass('workspaces')")).scalar_one() is None
    finally:
        engine.dispose()
