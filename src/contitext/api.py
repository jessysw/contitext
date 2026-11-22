"""Thin FastAPI adapter for the Contitext application service."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from contitext import __version__
from contitext.auth import AuthenticationError, PrincipalIdentity, ProjectNotFoundError, TokenStore
from contitext.credentials import DatabaseTokenStore
from contitext.config import Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.repository import BindingConflictError, BindingNotFoundError, IdempotencyConflictError, ProjectCreationConflictError, Repository
from contitext.projector import Projector
from contitext.schemas import (
    BindProjectRequest,
    CreateProjectRequest,
    HandoffRequest,
    RecordEventKind,
    RecordContextRequest,
)
from contitext.service import ContextService, WriterFencedError, ProjectionUnavailableError

logger = logging.getLogger("contitext.http")
bearer = HTTPBearer(auto_error=False)


class BindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class RecordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    event_kind: RecordEventKind
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1)


class HandoffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    completed: list[str] = Field(default_factory=list)
    current: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)


def create_app(
    *,
    service: ContextService | None = None,
    token_store: TokenStore | DatabaseTokenStore | None = None,
    projection: Callable[[PrincipalIdentity, str], Any] | None = None,
) -> FastAPI:
    owned_engine = None
    if service is None or token_store is None:
        settings = Settings.from_env()
        if service is None or settings.auth_mode == "database":
            owned_engine = create_database_engine(settings.database_url)
            factory = create_session_factory(owned_engine)
        if service is None:
            configured_projector = None
            if projection is None:
                import os
                projects_root = os.environ.get("CONTITEXT_PROJECTS_ROOT")
                if projects_root:
                    configured_projector = Projector(factory, projects_root, legacy_marker_prefixes=tuple(
                        prefix.strip() for prefix in os.environ.get("CONTITEXT_LEGACY_MARKER_PREFIXES", "").split(",") if prefix.strip()
                    ))
            service = ContextService(Repository(factory), configured_projector)
        if token_store is None:
            token_store = settings.credential_resolver(factory if owned_engine is not None else None)
    if token_store is None:
        raise AuthenticationError("local bearer token resolver is required")

    app = FastAPI(
        title="Contitext",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = service
    app.state.token_store = token_store
    app.state.projection = projection
    app.state.engine = owned_engine

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            },
        )
        return response

    def principal(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> PrincipalIdentity:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer credential")
        try:
            return token_store.resolve(credentials.credentials)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    @app.exception_handler(ProjectNotFoundError)
    async def project_not_found(_: Request, __: ProjectNotFoundError):
        return _json_error(404, "project not found")

    @app.exception_handler(AuthenticationError)
    async def unprovisioned_identity(_: Request, __: AuthenticationError):
        return _json_error(401, "authenticated principal is not provisioned")

    @app.exception_handler(BindingNotFoundError)
    async def binding_not_found(_: Request, __: BindingNotFoundError):
        return _json_error(404, "scope is not bound")

    @app.exception_handler(ValueError)
    async def invalid_value(_: Request, exc: ValueError):
        return _json_error(422, str(exc))

    @app.exception_handler(BindingConflictError)
    @app.exception_handler(ProjectCreationConflictError)
    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(_: Request, exc: IdempotencyConflictError):
        return _json_error(409, str(exc))

    @app.exception_handler(ProjectionUnavailableError)
    async def projection_unavailable(_: Request, exc: ProjectionUnavailableError):
        return _json_error(503, str(exc))

    @app.exception_handler(WriterFencedError)
    async def writers_fenced(_: Request, exc: WriterFencedError):
        return _json_error(503, str(exc))

    @app.get("/v1/projects")
    def list_projects(
        limit: int = Query(default=100, ge=1, le=100),
        cursor: str | None = None,
        identity: PrincipalIdentity = Depends(principal),
    ):
        return service.list_projects(identity, limit=limit, cursor=cursor)

    @app.post("/v1/projects", status_code=201)
    def create_project(body: CreateProjectRequest, identity: PrincipalIdentity = Depends(principal)):
        return service.create_project(identity, body)

    @app.put("/v1/scopes/{scope_id}/binding")
    def bind(scope_id: str, body: BindBody, identity: PrincipalIdentity = Depends(principal)):
        return service.bind_project(identity, BindProjectRequest(
            project_id=body.project_id, scope_id=scope_id, session_id=body.session_id,
        ))

    @app.get("/v1/scopes/{scope_id}/binding")
    def current(scope_id: str, identity: PrincipalIdentity = Depends(principal)):
        return service.current_project(identity, scope_id)

    @app.get("/v1/projects/{project_id:path}/context")
    def context(project_id: str, identity: PrincipalIdentity = Depends(principal)):
        return service.get_context(identity, project_id)

    @app.get("/v1/projects/{project_id:path}/search")
    def search(
        project_id: str,
        q: str = Query(min_length=1),
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = None,
        identity: PrincipalIdentity = Depends(principal),
    ):
        return service.search_context(identity, project_id, q, limit=limit, cursor=cursor)

    @app.post("/v1/projects/{project_id:path}/events", status_code=201)
    def record(project_id: str, body: RecordBody, identity: PrincipalIdentity = Depends(principal)):
        return service.record_context(identity, RecordContextRequest(
            project_id=project_id, **body.model_dump(),
        ))

    @app.post("/v1/projects/{project_id:path}/handoffs", status_code=201)
    def handoff(project_id: str, body: HandoffBody, identity: PrincipalIdentity = Depends(principal)):
        return service.create_handoff(identity, HandoffRequest(
            project_id=project_id, **body.model_dump(),
        ))

    @app.post("/v1/projects/{project_id:path}/projection")
    def project(project_id: str, identity: PrincipalIdentity = Depends(principal)):
        if projection is not None:
            return projection(identity, project_id)
        return service.project_context(identity, project_id)

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready(response: Response):
        if not service.ready():
            response.status_code = 503
            return {"status": "not ready"}
        return {"status": "ready"}

    return app


def _json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})


def app_from_env() -> FastAPI:
    return create_app()
