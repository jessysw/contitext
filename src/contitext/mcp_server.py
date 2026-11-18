"""Official-SDK stdio MCP adapter over the shared application service."""

from __future__ import annotations

import os
from typing import Annotated, Any

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


def create_mcp_server(service: ContextService, principal: PrincipalIdentity) -> FastMCP:
    server = FastMCP("contitext", log_level="WARNING")

    @server.tool(name="project_bind", structured_output=True)
    def project_bind(scope_id: str, project_id: str, session_id: str) -> ProjectBinding:
        return service.bind_project(principal, BindProjectRequest(
            project_id=project_id, scope_id=scope_id, session_id=session_id,
        ))

    @server.tool(name="project_current", structured_output=True)
    def project_current(scope_id: str) -> ProjectBinding:
        return service.current_project(principal, scope_id)

    @server.tool(name="context_get", structured_output=True)
    def context_get(project_id: str) -> ProjectContext:
        return service.get_context(principal, project_id)

    @server.tool(name="context_search", structured_output=True)
    def context_search(
        project_id: str,
        query: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ContextSearchPage:
        return service.search_context(
            principal, project_id, query, limit=limit, cursor=cursor
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
        return service.record_context(principal, RecordContextRequest(
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
        return service.create_handoff(principal, HandoffRequest(
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
        return service.list_projects(principal, limit=limit, cursor=cursor)

    @server.tool(name="project_create", structured_output=True)
    def project_create(project_id: str, display_name: str) -> AccessibleProject:
        """Create a project owned by the authenticated caller; does not bind a conversation."""
        return service.create_project(principal, CreateProjectRequest(
            project_id=project_id, display_name=display_name,
        ))

    return server


def server_from_env() -> FastMCP:
    settings = Settings.from_env()
    token = os.environ.get("CONTITEXT_MCP_TOKEN", "")
    if not token or settings.token_store is None:
        raise AuthenticationError("CONTITEXT_MCP_TOKEN is required")
    principal = settings.token_store.resolve(token)
    engine = create_database_engine(settings.database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    server = create_mcp_server(service, principal)
    # Keep the engine alive for the stdio server lifetime without exposing it as a tool.
    server._contitext_engine = engine
    return server


def main() -> None:
    server_from_env().run(transport="stdio")


if __name__ == "__main__":
    main()
