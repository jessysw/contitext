"""Exercise operator onboarding and the same boundaries external clients encounter."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
from uuid import UUID

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest
from sqlalchemy import create_engine, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, TokenStore
from contitext.db import create_session_factory
from contitext.diagnostics import client_config
from contitext.repository import BindingConflictError, Repository
from contitext.schemas import BindProjectRequest
from contitext.service import ContextService
from test_cli import cli, BIN_DIR
from test_events import make_event_request, seed_event_access


def test_onboarding_operator_commands_and_two_client_continuity(migrated_database_url, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config = tmp_path / "private.env"
    initial = cli("init", "--project", "research", "--name", "Researcher's ${HOME} \\ lab", "--output", str(config), cwd=tmp_path)
    assert initial.returncode == 0, initial.stderr
    owner = json.loads(initial.stdout)["principal_id"]
    assert config.stat().st_mode & 0o777 == 0o600
    values = dotenv_values(config, interpolate=False)
    token = values["CONTITEXT_MCP_TOKEN"]
    assert token not in initial.stdout + initial.stderr
    assert json.loads(values["CONTITEXT_SEED_JSON"])["projects"][0]["display_name"] == "Researcher's ${HOME} \\ lab"
    original = config.read_bytes()
    assert cli("init", "--output", str(config), cwd=tmp_path).returncode == 2
    assert config.read_bytes() == original

    def run(*args, ok=True):
        result = cli("--env-file", str(config), *args, cwd=tmp_path)
        assert (result.returncode == 0) == ok, result.stderr
        assert token not in result.stdout + result.stderr
        return json.loads(result.stdout) if ok else result

    run("admin", "seed", "--if-empty")
    assert run("doctor")["ok"]
    assert len(run("project", "list")["projects"]) == 1
    created = run("project", "create", "second", "--name", "Second", "--owner", owner)
    assert created["id"] == "second"
    run("project", "create", "second", "--name", "Duplicate", "--owner", owner, ok=False)
    run("project", "create", "../unsafe", "--name", "Unsafe", "--owner", owner, ok=False)
    assert len(run("project", "list")["projects"]) == 2
    assert run("project", "update", "second", "--status", "paused")["status"] == "paused"
    member = run("principal", "create", "Reader")["id"]
    run("workspace", "member", "grant", values["CONTITEXT_COMPATIBILITY_WORKSPACE"], member)
    run("access", "grant", "second", member, "--role", "reader")
    assert len(run("project", "show", "second")["access"]) == 2

    # Independent processes emulate agent disconnect/reconnect without an in-process cache.
    async def client(session_number):
        params = StdioServerParameters(command=str(BIN_DIR / "contitext"), args=["--env-file", str(config), "mcp"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if session_number == 1:
                    bound = await session.call_tool("project_bind", {"project_id": "research", "scope_id": "client-one:conversation", "session_id": "first"})
                    assert not bound.isError
                    result = await session.call_tool("context_handoff", {
                        "project_id": "research", "scope_id": "client-one:conversation", "session_id": "first",
                        "agent_id": owner, "source_kind": "test", "source_id": "first-session",
                        "summary": "Research completed", "next_action": "Review findings", "idempotency_key": "handoff-1",
                    })
                else:
                    unbound = await session.call_tool("project_current", {"scope_id": "client-two:conversation"})
                    assert unbound.isError
                    await session.call_tool("project_bind", {"project_id": "research", "scope_id": "client-two:conversation", "session_id": "second"})
                    result = await session.call_tool("context_get", {"project_id": "research"})
                    assert result.structuredContent["latest_handoff"]["payload"]["next_action"] == "Review findings"
                    old_binding = await session.call_tool("project_current", {"scope_id": "client-one:conversation"})
                    assert old_binding.structuredContent["project_id"] == "research"
                assert not result.isError
    asyncio.run(client(1))
    asyncio.run(client(2))

    # Revocation is effective on the next request, and bootstrap never restores it.
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine), compatibility_workspace=values["CONTITEXT_COMPATIBILITY_WORKSPACE"]))
    tokens = TokenStore.from_json(json.dumps({"reader-test-only": {"principal_id": member, "name": "Reader"}}))
    http = TestClient(create_app(service=service, token_store=tokens))
    headers = {"Authorization": "Bearer reader-test-only"}
    try:
        assert http.get("/v1/projects/second/context", headers=headers).status_code == 200
        assert http.get("/v1/projects/research/context", headers=headers).status_code == 404
        run("access", "revoke", "second", member)
        assert http.get("/v1/projects/second/context", headers=headers).status_code == 404
        run("access", "revoke", "research", owner)
        run("admin", "seed", "--if-empty")
        assert run("access", "list", "research")["access"] == []
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM context_events")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM scope_bindings")).scalar_one() == 2
    finally:
        engine.dispose()


def test_writes_and_handoffs_require_matching_binding(migrated_database_url):
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    repository = Repository(create_session_factory(engine))
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO project_acl VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='beta'), :id, 'writer')"), {"id": writer.principal_id})
        with pytest.raises(BindingConflictError):
            repository.record_context(writer, make_event_request(project_id="beta"))
        with pytest.raises(BindingConflictError):
            repository.record_context(writer, make_event_request().model_copy(update={"scope_id": "unbound"}))
        # A resumed conversation may have a fresh session ID without a project switch.
        request = make_event_request().model_copy(update={"session_id": "resumed"})
        original = repository.record_context(writer, request)
        assert original.session_id == "resumed"
        repository.bind_project(writer, BindProjectRequest(project_id="beta", scope_id="scope:exact", session_id="resumed"))
        with pytest.raises(BindingConflictError):
            repository.record_context(writer, request)
        store = TokenStore.from_json(json.dumps({"token": {"principal_id": str(writer.principal_id), "name": writer.name}}))
        client = TestClient(create_app(service=ContextService(repository), token_store=store))
        response = client.post("/v1/projects/alpha/handoffs", headers={"Authorization": "Bearer token"}, json={
            "scope_id": "scope:exact", "session_id": "resumed", "agent_id": "test", "source_kind": "test", "source_id": "handoff",
            "summary": "Wrong project", "next_action": "Do not save", "idempotency_key": "h",
        })
        assert response.status_code == 409
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM context_events")).scalar_one() == 1
    finally:
        engine.dispose()


def test_client_config_quotes_remote_paths_without_secrets():
    directory = "/srv/My context's $(unchanged)"
    options = argparse.Namespace(compose=directory, config_file=None, executable="contitext", ssh="operator@server")
    value = client_config(options)["mcpServers"]["contitext"]
    assert value["command"] == "ssh"
    remote = shlex.split(value["args"][-1])
    assert remote[remote.index("--project-directory") + 1] == directory
    assert remote[-2:] == ["contitext", "mcp"]
    assert "env" not in value
    options.ssh = "-oProxyCommand=bad"
    with pytest.raises(ValueError):
        client_config(options)


def test_doctor_does_not_print_credentials(monkeypatch, tmp_path, clean_environment):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://private-user:private-password@127.0.0.1:1/no-database?connect_timeout=1")
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", json.dumps({"private-token": {"principal_id": "55555555-5555-4555-8555-555555555555", "name": "Caller"}}))
    result = cli("doctor", cwd=tmp_path)
    assert result.returncode == 1
    assert not json.loads(result.stdout)["ok"]
    for secret in ("private-user", "private-password", "private-token"):
        assert secret not in result.stdout + result.stderr


def test_concurrent_rebind_is_observed_before_write(migrated_database_url):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    import threading
    from sqlalchemy import event
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    started = threading.Event()
    repository = Repository(create_session_factory(engine))

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if "FROM scope_bindings" in statement and "FOR UPDATE" in statement:
            started.set()
    event.listen(engine, "before_cursor_execute", before_execute)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO project_acl VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='beta'), :id, 'writer')"), {"id": writer.principal_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            with engine.begin() as rebinding:
                rebinding.execute(text("SELECT * FROM scope_bindings WHERE principal_id=:id AND scope_id='scope:exact' FOR UPDATE"), {"id": writer.principal_id})
                pending = pool.submit(repository.record_context, writer, make_event_request())
                assert started.wait(5)
                with pytest.raises(FutureTimeout):
                    pending.result(timeout=0.05)
                rebinding.execute(text("UPDATE scope_bindings SET project_id=(SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='beta') WHERE principal_id=:id AND scope_id='scope:exact'"), {"id": writer.principal_id})
            with pytest.raises(BindingConflictError):
                pending.result(timeout=5)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM context_events")).scalar_one() == 0
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
        engine.dispose()
