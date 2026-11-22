"""Transport-independent Contitext application service."""

from __future__ import annotations

import os
from pathlib import Path

from contitext.auth import PrincipalIdentity
from typing import Any

from contitext.repository import Repository
from contitext.schemas import (
    BindProjectRequest,
    AccessibleProject,
    CreateProjectRequest,
    ProjectListPage,
    ContextSearchPage,
    ContextEventResult,
    EventKind,
    HandoffRequest,
    ProjectContext,
    EventMetadata,
    AssemblyOptions,
    AssembledContext,
    ProjectBinding,
    ProjectionResult,
    RecordContextRequest,
    StoreContextEventRequest,
)


class ProjectionUnavailableError(RuntimeError):
    pass


class WriterFencedError(RuntimeError):
    pass


class ContextService:
    def __init__(
        self,
        repository: Repository,
        projector: Any | None = None,
        writer_fence_file: str | Path | None = None,
    ) -> None:
        self._repository = repository
        self._projector = projector
        configured_fence = writer_fence_file or os.environ.get(
            "CONTITEXT_WRITER_FENCE_FILE"
        )
        self._writer_fence_file = Path(configured_fence) if configured_fence else None

    def _require_writers_unfenced(self) -> None:
        if self._writer_fence_file is not None and self._writer_fence_file.exists():
            raise WriterFencedError("context-service writers are fenced for database maintenance")

    def ready(self) -> bool:
        return self._repository.ready()

    def list_projects(
        self, principal: PrincipalIdentity, *, limit: int = 100, cursor: str | None = None,
    ) -> ProjectListPage:
        return self._repository.list_projects(principal, limit=limit, cursor=cursor)

    def create_project(
        self, principal: PrincipalIdentity, request: CreateProjectRequest,
    ) -> AccessibleProject:
        self._require_writers_unfenced()
        validated = CreateProjectRequest.model_validate(request, from_attributes=True)
        return self._repository.create_project(principal, validated)

    def bind_project(
        self,
        principal: PrincipalIdentity,
        request: BindProjectRequest,
    ) -> ProjectBinding:
        self._require_writers_unfenced()
        return self._repository.bind_project(principal, request)

    def current_project(
        self,
        principal: PrincipalIdentity,
        scope_id: str,
    ) -> ProjectBinding:
        return self._repository.current_project(principal, scope_id)

    def record_context(
        self,
        principal: PrincipalIdentity,
        request: RecordContextRequest,
    ) -> ContextEventResult:
        self._require_writers_unfenced()
        validated = RecordContextRequest.model_validate(request, from_attributes=True)
        return self._repository.record_context(principal, validated)

    def get_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
        *, task_id: str | None = None, token_budget: int | None = None,
    ) -> ProjectContext | AssembledContext:
        if task_id is not None or token_budget is not None:
            options = AssemblyOptions(task_id=task_id, token_budget=4000 if token_budget is None else token_budget)
            return self._repository.assemble_context(principal, project_id, options)
        return self._repository.get_context(principal, project_id)

    def search_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ContextSearchPage:
        return self._repository.search_context(
            principal, project_id, query, limit=limit, cursor=cursor
        )

    def create_handoff(
        self,
        principal: PrincipalIdentity,
        request: HandoffRequest,
    ) -> ContextEventResult:
        self._require_writers_unfenced()
        return self._repository.record_context(
            principal,
            StoreContextEventRequest(
                project_id=request.project_id,
                scope_id=request.scope_id,
                session_id=request.session_id,
                agent_id=request.agent_id,
                source_kind=request.source_kind,
                source_id=request.source_id,
                event_kind=EventKind.handoff,
                event_metadata=request.event_metadata,
                payload={
                    "summary": request.summary,
                    "next_action": request.next_action,
                    "completed": request.completed,
                    "current": request.current,
                    "blockers": request.blockers,
                },
                idempotency_key=request.idempotency_key,
            ),
        )

    def project_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
    ) -> ProjectionResult:
        self._require_writers_unfenced()
        if self._projector is None:
            raise ProjectionUnavailableError("projection is not configured")
        return self._projector.project(principal, project_id)
