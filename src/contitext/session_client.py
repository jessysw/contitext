"""MCP client operations for explicitly configured local automation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from contitext.resolution import ResolutionError, load_connection, load_mappings, select_mapping


class UnboundScope(ResolutionError):
    pass


async def call(client, name: str, args: dict) -> dict:
    result = await client.call_tool(name, args)
    if result.isError:
        if name == 'project_current' and any(
            getattr(item, 'text', '') == 'scope is not bound'
            or getattr(item, 'text', '') == 'Error executing tool project_current: scope is not bound'
            for item in result.content
        ):
            raise UnboundScope('scope is not bound')
        raise ResolutionError('Contitext request failed; check server version, access and configuration')
    if not isinstance(result.structuredContent, dict):
        raise ResolutionError('Contitext returned an unsupported response')
    return result.structuredContent


@asynccontextmanager
async def connect(connection: dict):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    # Remote stderr can include connection details. Never relay it into a hook or JSON report.
    import os
    with open(os.devnull, 'w') as errors:
        async with stdio_client(StdioServerParameters(**connection), errlog=errors) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client


async def resolve_with_client(client, mappings: dict, cwd: Path, scope_id: str, session_id: str, *, bind: bool) -> dict:
    if not scope_id.strip() or not session_id.strip() or max(len(scope_id), len(session_id)) > 512:
        raise ResolutionError('stable nonempty scope and session identifiers are required')
    try:
        current = await call(client, 'project_current', {'scope_id': scope_id})
    except UnboundScope:
        current = None
    if current is not None:
        # Runtime bindings outrank even ambiguous repository mappings.
        return {'status': 'bound', 'source': 'binding', 'project_id': current['project_id'], 'binding': current}
    selection = select_mapping(mappings() if callable(mappings) else mappings, cwd)
    result = {'status': selection.status, 'source': selection.source, 'project_id': selection.project}
    if selection.status != 'matched':
        return result
    if not bind:
        # Authorization is checked even in preview mode. Never return a guessed hidden project.
        await call(client, 'context_get', {'project_id': selection.project})
        return result
    tools = await client.list_tools()
    binding_tool = next((t for t in tools.tools if t.name == 'project_bind'), None)
    if binding_tool is None or 'if_unbound' not in binding_tool.inputSchema.get('properties', {}):
        raise ResolutionError('server lacks atomic automatic binding; upgrade the server or use explicit selection')
    binding = await call(client, 'project_bind', {'scope_id': scope_id, 'session_id': session_id,
                                               'project_id': selection.project, 'if_unbound': True})
    # The server can return a concurrent manual selection. Its result is authoritative.
    return {'status': 'bound', 'source': selection.source, 'project_id': binding['project_id'], 'binding': binding}


async def resolve_command(args) -> dict:
    connection = load_connection(args.connection)
    mappings = lambda: load_mappings(args.mappings, connection)
    try:
        async with asyncio.timeout(args.timeout):
            async with connect(connection) as client:
                return await resolve_with_client(client, mappings, args.cwd, args.scope_id, args.session_id, bind=args.bind)
    except ResolutionError:
        raise
    except Exception:
        raise ResolutionError('project resolution unavailable; connection failed or timed out') from None
