"""Exercise independent client configuration, authentication and recovery guidance."""
import argparse
import asyncio
import json
import shlex

from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from contitext.diagnostics import client_config
from test_cli import cli, BIN_DIR


def test_config_overlay_and_remote_compose_paths():
    options = argparse.Namespace(compose=None, config_file="/private/server.env", executable="/venv/bin/contitext", ssh=None, credential_file="/private/Agent B's token.env")
    value = client_config(options)["mcpServers"]["contitext"]
    assert value["args"] == ["--env-file", options.config_file, "--env-file", options.credential_file, "mcp"]
    options.compose = "/srv/context"
    options.config_file = None
    options.ssh = "operator@host"
    value = client_config(options)["mcpServers"]["contitext"]
    command = shlex.split(value["args"][-1])
    assert command[command.index("--env-from-file") + 1] == options.credential_file
    assert command[-3:] == ["app", "contitext", "mcp"]
    assert "env" not in value
    options.credential_file = "relative.env"
    with pytest.raises(ValueError, match="absolute"):
        client_config(options)


def test_two_credentials_handoff_live_revocation_and_diagnostics(migrated_database_url, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config = tmp_path / "server.env"
    assert cli("init", "--project", "research", "--output", str(config), cwd=tmp_path).returncode == 0

    def run(*args, token_file=None, ok=True):
        prefix = ["--env-file", str(config)]
        if token_file:
            prefix += ["--env-file", str(token_file)]
        result = cli(*prefix, *args, cwd=tmp_path)
        assert (result.returncode == 0) == ok, result.stderr
        return json.loads(result.stdout)

    run("admin", "seed", "--if-empty")
    run("credential", "import-config")
    with config.open("a") as stream:
        stream.write("CONTITEXT_AUTH_MODE=database\n")
    owner = run("principal", "list")["principals"][0]["id"]
    member = run("principal", "create", "Agent B")["id"]
    credential = tmp_path / "agent-b.env"
    issued = run("credential", "issue", member, "--name", "Agent B", "--output", str(credential))
    assert credential.stat().st_mode & 0o777 == 0o600
    assert not run("doctor", token_file=credential, ok=False)["ok"]
    run("workspace", "member", "grant", "personal", member)
    checks = run("doctor", token_file=credential, ok=False)["checks"]
    assert next(x for x in checks if x["check"] == "workspace_membership")["ok"]
    assert not next(x for x in checks if x["check"] == "project_access")["ok"]
    run("access", "grant", "personal/research", member, "--role", "writer")
    assert run("doctor", token_file=credential)["ok"]

    def params(token=None):
        options = argparse.Namespace(compose=None, config_file=str(config), executable=str(BIN_DIR / "contitext"), ssh=None, credential_file=str(token) if token else None)
        return StdioServerParameters(**client_config(options)["mcpServers"]["contitext"])

    async def exercise():
        async with stdio_client(params()) as (read, write):
            async with ClientSession(read, write) as a:
                await a.initialize()
                assert not (await a.call_tool("project_bind", {"project_id":"personal/research", "scope_id":"same-scope", "session_id":"a"})).isError
                result = await a.call_tool("context_handoff", {"project_id":"personal/research", "scope_id":"same-scope", "session_id":"a", "agent_id":owner, "source_kind":"test", "source_id":"a", "summary":"Ready for B", "next_action":"Continue implementation", "idempotency_key":"a-handoff"})
                assert not result.isError
        async with stdio_client(params(credential)) as (read, write):
            async with ClientSession(read, write) as b:
                await b.initialize()
                # An identical scope string cannot reuse another principal's binding.
                assert (await b.call_tool("project_current", {"scope_id":"same-scope"})).isError
                bound = await b.call_tool("project_bind", {"project_id":"personal/research", "scope_id":"same-scope", "session_id":"b"})
                assert bound.structuredContent["principal_id"] == member
                result = await b.call_tool("context_get", {"project_id":"personal/research"})
                assert result.structuredContent["latest_handoff"]["payload"]["next_action"] == "Continue implementation"
                vault = tmp_path / "reader"
                run("export", "--output", str(vault), token_file=credential)
                assert "research" in (vault / "README.md").read_text().lower()
                assert len(list(vault.glob("project-*.md"))) == 1
                run("workspace", "member", "revoke", "personal", member)
                assert (await b.call_tool("project_current", {"scope_id":"same-scope"})).isError
                assert (await b.call_tool("context_get", {"project_id":"personal/research"})).isError
                run("export", "--output", str(vault), token_file=credential)
                assert not list(vault.glob("project-*.md"))
                run("workspace", "member", "grant", "personal", member)
                run("access", "revoke", "personal/research", member)
                assert (await b.call_tool("context_get", {"project_id":"personal/research"})).isError
                run("access", "grant", "personal/research", member, "--role", "writer")
                assert not (await b.call_tool("context_get", {"project_id":"personal/research"})).isError
                run("credential", "revoke", issued["credential_id"])
                assert (await b.call_tool("project_list", {})).isError
                diagnostic = run("doctor", token_file=credential, ok=False)
                assert not next(x for x in diagnostic["checks"] if x["check"] == "mcp_identity")["ok"]
                assert dotenv_values(credential)["CONTITEXT_MCP_TOKEN"] not in json.dumps(diagnostic)
        assert run("doctor")["ok"]  # Other credential remains valid.
    asyncio.run(exercise())
