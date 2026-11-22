"""Credential lifecycle against isolated PostgreSQL, HTTP, and real MCP processes."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError

from contitext.api import create_app
from contitext.auth import AuthenticationError
from contitext.cli import main
from contitext.config import ConfigurationError, Settings
from contitext.credentials import DatabaseTokenStore, digest, import_config, issue, revoke, rotate
from contitext.db import create_session_factory
from contitext.mcp_server import server_from_env
from contitext.models import Credential, CredentialAudit, Principal, Project, ProjectACL, WorkspaceMember
from contitext import reader
from test_migrations import alembic_config, reset_schema


@pytest.fixture
def credentials(migrated_database_url, monkeypatch):
    engine = create_engine(migrated_database_url)
    factory = create_session_factory(engine)
    owner, other = uuid4(), uuid4()
    project_id = uuid4()
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    with factory.begin() as session:
        session.add_all([Principal(id=owner, name="Owner"), Principal(id=other, name="Other"),
                         Project(id=project_id, workspace_id=workspace_id, slug="alpha", display_name="Alpha", status="active")])
        session.flush()
        session.add(ProjectACL(project_id=project_id, principal_id=owner, role="owner"))
        session.add(WorkspaceMember(workspace_id=workspace_id, principal_id=owner, role="member"))
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("CONTITEXT_AUTH_MODE", "database")
    monkeypatch.delenv("CONTITEXT_AUTH_TOKENS", raising=False)
    monkeypatch.delenv("CONTITEXT_MCP_TOKEN", raising=False)
    yield engine, factory, owner, other
    engine.dispose()


def test_independent_tokens_hash_only_revocation_expiry_and_audit(credentials):
    engine, factory, owner, other = credentials
    with factory.begin() as session:
        first, token = issue(session, owner, "First agent")
        first_id = first.id
        second, second_token = issue(session, owner, "Second agent")
        second_id = second.id
        _, other_token = issue(session, other, "Other person")
    resolver = DatabaseTokenStore(factory)
    assert resolver.resolve(token).principal_id == owner
    with factory() as session:
        row = session.get(Credential, first_id)
        assert row.token_hash == digest(token) and token not in repr(row)
        raw = session.execute(text("SELECT row_to_json(credentials)::text FROM credentials")).scalars().all()
        assert all(token not in data and second_token not in data for data in raw)
    with factory.begin() as session:
        assert revoke(session, first_id)[1]
        assert not revoke(session, first_id)[1]
    for bad in (token, "not-a-token", ""):
        with pytest.raises(AuthenticationError, match="invalid bearer"):
            resolver.resolve(bad)
    assert resolver.resolve(second_token).principal_id == owner
    assert resolver.resolve(other_token).principal_id == other
    with factory.begin() as session:
        session.get(Credential, second_id).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(AuthenticationError):
        resolver.resolve(second_token)
    with factory() as session:
        assert list(session.scalars(select(CredentialAudit.action).where(CredentialAudit.credential_id == first_id)
                                    .order_by(CredentialAudit.created_at))) == ["issued", "revoked"]
    assert token not in repr(resolver)


def test_cli_private_delivery_rotation_and_output_failure_are_atomic(credentials, tmp_path, capsys):
    engine, factory, owner, _ = credentials
    output = tmp_path / "agent.env"
    main(["credential", "issue", str(owner), "--name", "Agent", "--output", str(output), "--expires-in", "600"])
    result = json.loads(capsys.readouterr().out)
    credential_id = result["credential_id"]
    token = dotenv_values(output)["CONTITEXT_MCP_TOKEN"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert token not in json.dumps(result) and digest(token) not in json.dumps(result)
    assert result["expires_at"] is not None
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        main(["credential", "rotate", credential_id, "--output", str(output)])
    assert output.read_bytes() == original
    assert token not in capsys.readouterr().err
    assert DatabaseTokenStore(factory).resolve(token).principal_id == owner
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Credential)) == 1
        assert session.scalar(select(func.count()).select_from(CredentialAudit)) == 1
    replacement = tmp_path / "replacement.env"
    main(["credential", "rotate", credential_id, "--output", str(replacement)])
    renewed = json.loads(capsys.readouterr().out)
    new_token = dotenv_values(replacement)["CONTITEXT_MCP_TOKEN"]
    assert renewed["expires_at"] == result["expires_at"]
    with pytest.raises(AuthenticationError):
        DatabaseTokenStore(factory).resolve(token)
    assert DatabaseTokenStore(factory).resolve(new_token).principal_id == owner
    main(["credential", "list", "--principal", str(owner)])
    listing = capsys.readouterr().out
    assert token not in listing and new_token not in listing and digest(token) not in listing
    main(["credential", "audit", credential_id])
    audit_rows = json.loads(capsys.readouterr().out)["audit"]
    assert [row["action"] for row in audit_rows] == ["issued", "rotated"]
    assert audit_rows[-1]["related_credential_id"] == renewed["credential_id"]
    main(["credential", "revoke", renewed["credential_id"]])
    assert json.loads(capsys.readouterr().out)["changed"]
    with pytest.raises(AuthenticationError):
        DatabaseTokenStore(factory).resolve(new_token)


def test_import_is_idempotent_never_revives_or_reassigns(credentials, monkeypatch, capsys):
    _, factory, owner, other = credentials
    raw = json.dumps({"legacy-test-only": {"principal_id": str(owner), "name": "Owner"}})
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", raw)
    main(["credential", "import-config"])
    assert json.loads(capsys.readouterr().out) == {"imported": 1, "existing": 0}
    assert DatabaseTokenStore(factory).resolve("legacy-test-only").principal_id == owner
    with factory.begin() as session:
        item = session.scalar(select(Credential))
        item_id = item.id
        revoke(session, item_id)
    main(["credential", "import-config"])
    assert json.loads(capsys.readouterr().out) == {"imported": 0, "existing": 1}
    # Even though the old configuration still contains the secret, DB auth rejects it.
    resolver = Settings.from_env().credential_resolver(factory)
    with pytest.raises(AuthenticationError):
        resolver.resolve("legacy-test-only")
    conflicting = json.dumps({"legacy-test-only": {"principal_id": str(other), "name": "Other"}})
    with pytest.raises(ValueError, match="another principal"):
        with factory.begin() as session:
            import_config(session, conflicting)
    with factory() as session:
        assert session.get(Credential, item_id).principal_id == owner


def test_failed_secret_write_rolls_back_rotation_and_cleans_only_new_file(credentials, tmp_path, monkeypatch, capsys):
    _, factory, owner, _ = credentials
    with factory.begin() as session:
        item, token = issue(session, owner, "Agent")
        item_id = item.id
    def fail(_):
        raise OSError("test write failure")
    monkeypatch.setattr("contitext.credentials.os.fsync", fail)
    output = tmp_path / "failed.env"
    with pytest.raises(SystemExit):
        main(["credential", "rotate", str(item_id), "--output", str(output)])
    assert not output.exists()
    assert token not in capsys.readouterr().err
    assert DatabaseTokenStore(factory).resolve(token).principal_id == owner
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Credential)) == 1
        assert session.scalar(select(func.count()).select_from(CredentialAudit)) == 1


def test_doctor_and_default_owner_creation_accept_database_credentials(credentials, monkeypatch, capsys):
    _, factory, owner, _ = credentials
    with factory.begin() as session:
        item, token = issue(session, owner, "Agent")
        item_id = item.id
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", token)
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["ok"]
    main(["project", "create", "new-project", "--name", "New project"])
    assert json.loads(capsys.readouterr().out)["owner"] == str(owner)
    monkeypatch.setenv("CONTITEXT_AUTH_MODE", "config")
    main(["credential", "revoke", str(item_id)])
    result = json.loads(capsys.readouterr().out)
    assert "Config-mode services" in result["warning"] and result["changed"]


def test_import_failure_rolls_back_entire_batch(credentials):
    _, factory, owner, _ = credentials
    raw = json.dumps({"valid-test": {"principal_id": str(owner), "name": "Owner"},
                      "invalid-test": {"principal_id": str(uuid4()), "name": "Missing"}})
    with pytest.raises(ValueError, match="unprovisioned"):
        with factory.begin() as session:
            import_config(session, raw)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Credential)) == 0


def test_concurrent_rotation_has_only_one_winner(credentials):
    _, factory, owner, _ = credentials
    with factory.begin() as session:
        original, token = issue(session, owner, "Agent")
        original_id = original.id
    def attempt(_):
        try:
            with factory.begin() as session:
                _, replacement = rotate(session, original_id)
            return replacement
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(AuthenticationError):
        DatabaseTokenStore(factory).resolve(token)
    assert DatabaseTokenStore(factory).resolve(next(result for result in results if result)).principal_id == owner


def test_existing_http_and_mcp_processes_reject_revocation(credentials, monkeypatch):
    _, factory, owner, other = credentials
    with factory.begin() as session:
        item, token = issue(session, owner, "Agent")
        item_id = item.id
        _, denied_token = issue(session, other, "Other")
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", token)
    server = server_from_env()
    app = create_app()
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer " + token}
            assert client.get("/v1/projects", headers=headers).status_code == 200
            assert client.get("/v1/projects/alpha/context", headers={"Authorization": "Bearer " + denied_token}).status_code == 404
            asyncio.run(server.call_tool("project_bind", {"project_id": "alpha", "scope_id": "scope", "session_id": "session"}))
            with factory.begin() as session:
                revoke(session, item_id)
            assert client.get("/v1/projects", headers=headers).status_code == 401
            cases = {
                "project_list": {}, "project_create": {"project_id": "new", "display_name": "New"},
                "project_current": {"scope_id": "scope"}, "context_get": {"project_id": "alpha"},
                "context_search": {"project_id": "alpha", "query": "test"},
                "project_bind": {"project_id": "alpha", "scope_id": "scope", "session_id": "session"},
                "context_record": {"project_id": "alpha", "scope_id": "scope", "session_id": "session", "agent_id": "agent",
                                   "source_kind": "test", "source_id": "source", "event_kind": "note", "payload": {}, "idempotency_key": "one"},
                "context_handoff": {"project_id": "alpha", "scope_id": "scope", "session_id": "session", "agent_id": "agent",
                                    "source_kind": "test", "source_id": "source", "summary": "test", "next_action": "test", "idempotency_key": "two"},
            }
            for tool, args in cases.items():
                with pytest.raises(ToolError, match="invalid bearer"):
                    asyncio.run(server.call_tool(tool, args))
    finally:
        server._contitext_engine.dispose()
        app.state.engine.dispose()


def test_real_stdio_session_observes_external_revocation(credentials):
    _, factory, owner, _ = credentials
    with factory.begin() as session:
        item, token = issue(session, owner, "Agent")
        item_id = item.id
    async def scenario():
        env = dict(os.environ, CONTITEXT_MCP_TOKEN=token)
        params = StdioServerParameters(command=sys.executable, args=["-m", "contitext.cli", "mcp"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                first = await client.call_tool("project_list", {})
                assert not first.isError and first.structuredContent["projects"][0]["project_id"] == "alpha"
                with factory.begin() as session:
                    revoke(session, item_id)
                second = await client.call_tool("project_list", {})
                assert second.isError
                assert token not in str(second)
    asyncio.run(scenario())


def test_reader_reauthenticates_each_refresh(credentials, monkeypatch, tmp_path, capsys):
    _, factory, owner, _ = credentials
    with factory.begin() as session:
        item, token = issue(session, owner, "Reader")
        item_id = item.id
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", token)
    sleeps = []
    def sleep(_):
        if sleeps:
            raise KeyboardInterrupt
        sleeps.append(True)
        with factory.begin() as session:
            revoke(session, item_id)
    monkeypatch.setattr(reader.time, "sleep", sleep)
    output = tmp_path / "reader"
    assert reader.run(SimpleNamespace(output=output, watch=10, project=None)) == 0
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [result["status"] for result in results] == ["ok", "error"]
    assert "Refresh failed" in (output / "SYNC-STATUS.md").read_text()
    assert token not in json.dumps(results)


def test_authentication_modes_and_database_failure_fail_closed():
    with pytest.raises(ConfigurationError, match="CONTITEXT_AUTH_TOKENS"):
        Settings.from_env({"DATABASE_URL": "postgresql://u@localhost/db"})
    with pytest.raises(ConfigurationError, match="AUTH_MODE"):
        Settings.from_env({"DATABASE_URL": "postgresql://u@localhost/db", "CONTITEXT_AUTH_MODE": "both"})
    settings = Settings.from_env({"DATABASE_URL": "postgresql://u@localhost/db", "CONTITEXT_AUTH_MODE": "database",
                                  "CONTITEXT_AUTH_TOKENS": "invalid ignored legacy config"})
    assert settings.token_store is None
    def broken():
        raise OperationalError("private connection details", {}, Exception("secret"))
    with pytest.raises(AuthenticationError, match="unavailable") as error:
        settings.credential_resolver(broken).resolve("secret")
    assert "secret" not in str(error.value) and "private" not in str(error.value)


def test_existing_schema_data_survives_migration_and_populated_downgrade_is_blocked(test_database_url, postgres_available, monkeypatch):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()
    command.upgrade(config, "0001_foundation")
    engine = create_engine(test_database_url)
    principal_id, event_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id,display_name,status) VALUES ('legacy','Legacy','active')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'Owner')"), {"id": principal_id})
        connection.execute(text("INSERT INTO project_acl VALUES ('legacy',:id,'owner')"), {"id": principal_id})
        connection.execute(text("INSERT INTO scope_bindings (principal_id,scope_id,project_id,session_id) VALUES (:id,'scope','legacy','session')"), {"id": principal_id})
        connection.execute(text("""INSERT INTO context_events (event_id,project_id,principal_id,scope_id,session_id,agent_id,source_kind,source_id,event_kind,payload,idempotency_key)
            VALUES (:event,'legacy',:id,'scope','session','agent','test','source','note','{"text":"preserve me"}','key')"""), {"id": principal_id, "event": event_id})
        connection.execute(text("INSERT INTO projection_offsets (project_id,last_event_id) VALUES ('legacy',:event)"), {"event": event_id})
        tables = ["projects", "principals", "project_acl", "scope_bindings", "context_events", "projection_offsets"]
        before = {table: connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all() for table in tables}
    try:
        command.upgrade(config, "0002_credentials")
        with engine.connect() as connection:
            after = {table: connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all() for table in tables}
        assert before == after
        factory = create_session_factory(engine)
        with factory.begin() as session:
            _, token = issue(session, principal_id, "Imported installation")
        with pytest.raises(RuntimeError, match="credential history exists"):
            command.downgrade(config, "0001_foundation")
        assert DatabaseTokenStore(factory).resolve(token).principal_id == principal_id
    finally:
        engine.dispose()
