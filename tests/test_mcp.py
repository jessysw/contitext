from __future__ import annotations

from workspace_fixtures import seed_members


import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import create_engine, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, TokenStore
from contitext.db import create_session_factory
from contitext.mcp_server import create_mcp_server
from contitext.repository import Repository
from contitext.service import ContextService


TOOLS = ["project_bind", "project_current", "context_get", "context_search", "context_record", "context_handoff", "project_list", "project_create"]


def setup(database_url: str):
    engine = create_engine(database_url)
    principal = PrincipalIdentity(uuid4(), "MCP Owner")
    denied = PrincipalIdentity(uuid4(), "MCP Denied")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (slug, workspace_id,display_name,status) VALUES ('alpha', '00000000-0000-4000-8000-000000000001','Alpha','active'),('beta', '00000000-0000-4000-8000-000000000001','Beta','active')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'MCP Owner'),(:denied,'MCP Denied')"), {"id": principal.principal_id, "denied": denied.principal_id})
        seed_members(connection)
        connection.execute(text("INSERT INTO project_acl (project_id,principal_id,role) VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'),:id,'owner')"), {"id": principal.principal_id})
    service = ContextService(Repository(create_session_factory(engine)))
    return engine, principal, denied, service


def test_lists_eight_tools_with_stable_schemas(migrated_database_url: str) -> None:
    engine, principal, _, service = setup(migrated_database_url)
    try:
        tools = asyncio.run(create_mcp_server(service, principal).list_tools())
        assert [tool.name for tool in tools] == TOOLS
        schemas = {tool.name: tool.inputSchema for tool in tools}
        assert set(schemas["project_bind"]["required"]) == {"scope_id", "project_id", "session_id"}
        assert "principal" not in json.dumps(schemas)
        assert set(schemas["project_create"]["required"]) == {"project_id", "display_name"}
        assert "owner" not in schemas["project_create"]["properties"]
        assert set(schemas["context_record"]["required"]) == {
            "project_id", "scope_id", "session_id", "agent_id", "source_kind",
            "source_id", "event_kind", "payload", "idempotency_key",
        }
        assert schemas["context_record"]["$defs"]["RecordEventKind"]["enum"] == ["note", "decision", "question", "checkpoint"]
        assert set(schemas["context_handoff"]["required"]) == {
            "project_id", "scope_id", "session_id", "agent_id", "source_kind",
            "source_id", "summary", "next_action", "idempotency_key",
        }
    finally:
        engine.dispose()


def test_mcp_http_semantics_and_acl_are_identical(migrated_database_url: str) -> None:
    engine, principal, denied, service = setup(migrated_database_url)
    try:
        server = create_mcp_server(service, principal)
        args = {
            "project_id": "alpha", "scope_id": "scope", "session_id": "session",
            "agent_id": "agent", "source_kind": "hermes", "source_id": "source:1",
            "event_kind": "note", "payload": {"text": "parity phrase"},
            "idempotency_key": "parity-1",
        }
        with pytest.raises(ToolError, match="bind this scope"):
            asyncio.run(server.call_tool("context_record", args))
        asyncio.run(server.call_tool("project_bind", {"project_id": "alpha", "scope_id": "scope", "session_id": "session"}))
        _, mcp_result = asyncio.run(server.call_tool("context_record", args))
        store = TokenStore.from_json(json.dumps({"token": {"principal_id": str(principal.principal_id), "name": principal.name}}))
        client = TestClient(create_app(service=service, token_store=store))
        http = client.post("/v1/projects/alpha/events", headers={"Authorization": "Bearer token"}, json={key: value for key, value in args.items() if key != "project_id"})
        assert http.status_code == 201
        assert http.json() == mcp_result
        with pytest.raises(ToolError, match="idempotency key"):
            asyncio.run(server.call_tool("context_record", {**args, "payload": {"text": "different"}}))

        denied_server = create_mcp_server(service, denied)
        failures = []
        for project_id in ("alpha", "missing"):
            with pytest.raises(ToolError) as caught:
                asyncio.run(denied_server.call_tool("context_get", {"project_id": project_id}))
            failures.append(str(caught.value))
        assert failures[0] == failures[1]

        with pytest.raises(ToolError):
            asyncio.run(server.call_tool("context_record", {**args, "event_kind": "handoff"}))
    finally:
        engine.dispose()


@pytest.mark.parametrize("server_args", [
    ["-m", "contitext.cli", "mcp"], ["-m", "contitext.mcp_server"],
    None,  # Installed console command and package arguments from the Registry.
])
def test_real_stdio_initialize_list_and_calls(migrated_database_url: str, server_args: list[str] | None) -> None:
    engine, principal, _, _ = setup(migrated_database_url)
    engine.dispose()
    auth_json = json.dumps({"stdio-token": {"principal_id": str(principal.principal_id), "name": principal.name}})
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": migrated_database_url,
        "CONTITEXT_AUTH_TOKENS": auth_json,
        "CONTITEXT_MCP_TOKEN": "stdio-token",
    })

    async def smoke():
        command = sys.executable
        args = server_args
        if args is None:
            manifest = json.loads((Path(__file__).resolve().parents[1] / "server.json").read_text())
            package = manifest["packages"][0]
            command = str(Path(sys.executable).with_name(package["identifier"]))
            args = [argument["value"] for argument in package["packageArguments"]]
        params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert [tool.name for tool in listed.tools] == TOOLS
                projects = await session.call_tool("project_list", {})
                assert [p["project_id"] for p in projects.structuredContent["projects"]] == ["alpha"]
                created = await session.call_tool("project_create", {"project_id": "new-project", "display_name": "New Project"})
                assert not created.isError and created.structuredContent["role"] == "owner"
                unbound = await session.call_tool("project_current", {"scope_id": "stdio"})
                assert unbound.isError
                bound = await session.call_tool("project_bind", {"scope_id": "stdio", "project_id": "alpha", "session_id": "stdio-session"})
                assert not bound.isError and bound.structuredContent["project_id"] == "alpha"
                current = await session.call_tool("project_current", {"scope_id": "stdio"})
                assert current.structuredContent["project_id"] == "alpha"
                recorded = await session.call_tool("context_record", {
                    "project_id": "alpha", "scope_id": "stdio", "session_id": "stdio-session",
                    "agent_id": "agent", "source_kind": "codex", "source_id": "stdio:1",
                    "event_kind": "note", "payload": {"text": "stdio searchable"},
                    "idempotency_key": "stdio-record",
                })
                assert not recorded.isError
                context = await session.call_tool("context_get", {"project_id": "alpha"})
                assert not context.isError
                search = await session.call_tool("context_search", {"project_id": "alpha", "query": "stdio"})
                assert search.structuredContent["total_count"] == 1
                handoff = await session.call_tool("context_handoff", {
                    "project_id": "alpha", "scope_id": "stdio", "session_id": "stdio-session",
                    "agent_id": "agent", "source_kind": "codex", "source_id": "stdio:h",
                    "summary": "stdio handoff", "next_action": "finish smoke",
                    "idempotency_key": "stdio-handoff",
                })
                assert not handoff.isError and handoff.structuredContent["event_kind"] == "handoff"

    asyncio.run(smoke())


@pytest.mark.parametrize("smoke_args", [
    ["-m", "contitext.cli", "mcp-smoke"], ["-m", "contitext.mcp_smoke"],
])
def test_deployable_mcp_smoke_module_uses_official_stdio_client(migrated_database_url: str, smoke_args: list[str]) -> None:
    engine, principal, _, _ = setup(migrated_database_url)
    engine.dispose()
    token = "module-smoke-token"
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": migrated_database_url,
        "CONTITEXT_AUTH_TOKENS": json.dumps({
            token: {"principal_id": str(principal.principal_id), "name": principal.name},
        }),
        "CONTITEXT_MCP_TOKEN": token,
        "CONTITEXT_SMOKE_PROJECT_ID": "alpha",
    })
    completed = subprocess.run(
        [sys.executable, *smoke_args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "contitext mcp smoke: ok"
    assert token not in completed.stdout + completed.stderr
