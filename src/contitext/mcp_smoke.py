"""Official-SDK smoke check that creates synthetic records and a project in a test deployment."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any
from uuid import uuid4

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

TOOLS = [
    "project_bind",
    "project_current",
    "context_get",
    "context_search",
    "context_record",
    "context_handoff",
    "project_list",
    "project_create",
]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _structured(result: Any, operation: str) -> dict[str, Any]:
    if result.isError or not isinstance(result.structuredContent, dict):
        raise RuntimeError(f"MCP {operation} failed")
    return result.structuredContent


async def run_smoke() -> None:
    project_id = _required_env("CONTITEXT_SMOKE_PROJECT_ID")
    from contitext.namespaces import ProjectResolver
    resolver = ProjectResolver()
    workspace_slug, project_slug = resolver.split(project_id)
    canonical_reference = project_slug if workspace_slug == resolver.compatibility_workspace else project_id
    _required_env("CONTITEXT_MCP_TOKEN")
    run_id = uuid4().hex
    scope_id = f"contitext-mcp-smoke-{run_id}"
    session_id = f"contitext-mcp-smoke-{run_id}"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "contitext.mcp_server"],
        env=os.environ.copy(),
    )

    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = [tool.name for tool in listed.tools]
            if names != TOOLS:
                raise RuntimeError(f"unexpected MCP tool set: {names!r}")

            # The smoke command is explicitly for synthetic data in a test deployment.
            _structured(await session.call_tool("project_list", {}), "project_list")
            created = _structured(await session.call_tool("project_create", {
                "project_id": f"{workspace_slug}/smoke-{run_id}", "display_name": "Synthetic smoke project",
            }), "project_create")
            if created.get("role") != "owner":
                raise RuntimeError("project_create did not grant the caller ownership")

            bound = _structured(await session.call_tool("project_bind", {
                "scope_id": scope_id,
                "project_id": project_id,
                "session_id": session_id,
            }), "project_bind")
            if bound.get("project_id") != canonical_reference:
                raise RuntimeError("MCP project_bind returned the wrong project")

            current = _structured(await session.call_tool("project_current", {
                "scope_id": scope_id,
            }), "project_current")
            if current.get("project_id") != canonical_reference:
                raise RuntimeError("MCP project_current returned the wrong project")

            _structured(await session.call_tool("context_get", {
                "project_id": project_id,
            }), "context_get")

            recorded = _structured(await session.call_tool("context_record", {
                "project_id": project_id,
                "scope_id": scope_id,
                "session_id": session_id,
                "agent_id": "contitext-mcp-smoke",
                "source_kind": "hermes",
                "source_id": f"contitext-mcp-smoke:{run_id}",
                "event_kind": "note",
                "payload": {"text": f"contitext mcp smoke {run_id}"},
                "idempotency_key": f"contitext-mcp-smoke-record-{run_id}",
            }), "context_record")

            searched = _structured(await session.call_tool("context_search", {
                "project_id": project_id,
                "query": run_id,
            }), "context_search")
            results = searched.get("results", [])
            if (
                searched.get("total_count") != 1
                or len(results) != 1
                or results[0].get("event", {}).get("event_id") != recorded.get("event_id")
            ):
                raise RuntimeError("MCP context_search did not find the durable record")

            handoff = _structured(await session.call_tool("context_handoff", {
                "project_id": project_id,
                "scope_id": scope_id,
                "session_id": session_id,
                "agent_id": "contitext-mcp-smoke",
                "source_kind": "hermes",
                "source_id": f"contitext-mcp-smoke-handoff:{run_id}",
                "summary": f"contitext mcp smoke handoff {run_id}",
                "next_action": "complete deployed MCP smoke",
                "completed": ["bind", "current", "get", "record", "search"],
                "current": ["handoff"],
                "blockers": [],
                "idempotency_key": f"contitext-mcp-smoke-handoff-{run_id}",
            }), "context_handoff")
            if handoff.get("event_kind") != "handoff":
                raise RuntimeError("MCP context_handoff did not create a handoff")

            hydrated = _structured(await session.call_tool("context_get", {
                "project_id": project_id,
            }), "context_get")
            if hydrated.get("overview", {}).get("project_id") != canonical_reference:
                raise RuntimeError("MCP context_get returned the wrong project")

            durable = _structured(await session.call_tool("context_search", {
                "project_id": project_id,
                "query": run_id,
            }), "context_search")
            durable_ids = {
                item.get("event", {}).get("event_id")
                for item in durable.get("results", [])
            }
            if {recorded.get("event_id"), handoff.get("event_id")} - durable_ids:
                raise RuntimeError("MCP durable operations were not readable after write")


def main() -> None:
    asyncio.run(run_smoke())
    print("contitext mcp smoke: ok")


if __name__ == "__main__":
    main()
