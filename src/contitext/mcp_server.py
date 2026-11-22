"""Official-SDK stdio MCP adapter over the shared application service."""

from __future__ import annotations

import os
from typing import Annotated, Any, Callable

from pydantic import Field

from mcp.server.fastmcp import FastMCP

from contitext.auth import AuthenticationError, PrincipalIdentity
from contitext.config import Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.repository import Repository
from contitext.schemas import (
    BindProjectRequest,
    AccessibleProject,
    CreateProjectRequest,
    ProjectListPage,
    ContextEventResult,
    ContextSearchPage,
    HandoffRequest,
    ProjectBinding,
    ProjectContext,
    RecordEventKind,
    RecordContextRequest,
)
from contitext.service import ContextService


def create_mcp_server(service: ContextService, principal: PrincipalIdentity | Callable[[], PrincipalIdentity]) -> FastMCP:
    server = FastMCP("contitext", log_level="WARNING")

    def identity() -> PrincipalIdentity:
        return principal() if callable(principal) else principal

    @server.tool(name="project_bind", structured_output=True)
    def project_bind(scope_id: str, project_id: str, session_id: str) -> ProjectBinding:
        return service.bind_project(identity(), BindProjectRequest(
            project_id=project_id, scope_id=scope_id, session_id=session_id,
        ))

    @server.tool(name="project_current", structured_output=True)
    def project_current(scope_id: str) -> ProjectBinding:
        return service.current_project(identity(), scope_id)

    @server.tool(name="context_get", structured_output=True)
    def context_get(project_id: str) -> ProjectContext:
        return service.get_context(identity(), project_id)

    @server.tool(name="context_search", structured_output=True)
    def context_search(
        project_id: str,
        query: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ContextSearchPage:
        return service.search_context(
            identity(), project_id, query, limit=limit, cursor=cursor
        )

    @server.tool(name="context_record", structured_output=True)
    def context_record(
        project_id: str,
        scope_id: str,
        session_id: str,
        agent_id: str,
        source_kind: str,
        source_id: str,
        event_kind: RecordEventKind,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ContextEventResult:
        return service.record_context(identity(), RecordContextRequest(
            project_id=project_id,
            scope_id=scope_id,
            session_id=session_id,
            agent_id=agent_id,
            source_kind=source_kind,
            source_id=source_id,
            event_kind=event_kind,
            payload=payload,
            idempotency_key=idempotency_key,
        ))

    @server.tool(name="context_handoff", structured_output=True)
    def context_handoff(
        project_id: str,
        scope_id: str,
        session_id: str,
        agent_id: str,
        source_kind: str,
        source_id: str,
        summary: str,
        next_action: str,
        idempotency_key: str,
        completed: list[str] | None = None,
        current: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> ContextEventResult:
        return service.create_handoff(identity(), HandoffRequest(
            project_id=project_id,
            scope_id=scope_id,
            session_id=session_id,
            agent_id=agent_id,
            source_kind=source_kind,
            source_id=source_id,
            summary=summary,
            next_action=next_action,
            completed=completed or [],
            current=current or [],
            blockers=blockers or [],
            idempotency_key=idempotency_key,
        ))

    @server.tool(name="project_list", structured_output=True)
    def project_list(
        limit: Annotated[int, Field(ge=1, le=100)] = 100,
        cursor: str | None = None,
    ) -> ProjectListPage:
        """List projects accessible to the authenticated caller without selecting one."""
        return service.list_projects(identity(), limit=limit, cursor=cursor)

    @server.tool(name="project_create", structured_output=True)
    def project_create(project_id: str, display_name: str) -> AccessibleProject:
        """Create a project owned by the authenticated caller; does not bind a conversation."""
        return service.create_project(identity(), CreateProjectRequest(
            project_id=project_id, display_name=display_name,
        ))

    return server


def server_from_env() -> FastMCP:
    settings = Settings.from_env()
    token = os.environ.get("CONTITEXT_MCP_TOKEN", "")
    if not token:
        raise AuthenticationError("CONTITEXT_MCP_TOKEN is required")
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    resolver = settings.credential_resolver(factory)
    try:
        resolver.resolve(token)
    except BaseException:
        engine.dispose()
        raise
    service = ContextService(Repository(factory))
    server = create_mcp_server(service, lambda: resolver.resolve(token))
    # Keep the engine alive for the stdio server lifetime without exposing it as a tool.
    server._contitext_engine = engine
    return server


def main() -> None:
    server_from_env().run(transport="stdio")


if __name__ == "__main__":
    main()
