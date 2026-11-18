"""Authorized PostgreSQL repository operations."""

from __future__ import annotations

import base64
from datetime import datetime
import json
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import func

from contitext.auth import AuthenticationError, PrincipalIdentity, ProjectNotFoundError, require_project_access
from contitext.locking import acquire_project_transaction_lock
from contitext.models import ContextEvent, Principal, Project, ProjectACL, ScopeBinding
from contitext.schemas import (
    BindProjectRequest,
    AccessibleProject,
    CreateProjectRequest,
    ProjectListPage,
    ContextSearchPage,
    ContextSearchResult,
    ContextEventResult,
    ProjectContext,
    ProjectBinding,
    ProjectOverview,
    RecordContextRequest,
    StoreContextEventRequest,
)


class BindingNotFoundError(RuntimeError):
    """Raised when a principal has no authorized binding for a scope."""


class IdempotencyConflictError(RuntimeError):
    """An existing event key cannot be reused for another request or principal."""


class BindingConflictError(RuntimeError):
    """A write must target the caller's explicitly bound project."""


class ProjectCreationConflictError(RuntimeError):
    """A project ID is unavailable; never disclose an existing project's metadata."""


class Repository:
    """Only exposes project-filtered, authorization-aware operations."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ready(self) -> bool:
        try:
            with self._session_factory() as session:
                version = session.execute(text(
                    "SELECT version_num FROM alembic_version"
                )).scalar_one()
                return version == "0001_foundation"
        except Exception:
            return False

    def list_projects(
        self, principal: PrincipalIdentity, *, limit: int = 100, cursor: str | None = None,
    ) -> ProjectListPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = None
        if cursor is not None:
            try:
                after = json.loads(base64.b64decode(
                    cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True,
                ).decode("utf-8"))
                if not isinstance(after, str) or not after:
                    raise ValueError
            except (ValueError, UnicodeError) as exc:
                raise ValueError("invalid project cursor") from exc
        with self._session_factory() as session:
            statement = select(Project, ProjectACL.role).join(ProjectACL).where(
                ProjectACL.principal_id == principal.principal_id,
            ).order_by(Project.id.collate("C")).limit(limit + 1)
            if after is not None:
                statement = statement.where(Project.id.collate("C") > after)
            rows = session.execute(statement).all()
            projects = [AccessibleProject(
                project_id=p.id, display_name=p.display_name, status=p.status, role=role,
            ) for p, role in rows[:limit]]
            next_cursor = None
            if len(rows) > limit:
                next_cursor = base64.urlsafe_b64encode(
                    json.dumps(projects[-1].project_id).encode("utf-8")
                ).decode("ascii").rstrip("=")
            return ProjectListPage(projects=projects, next_cursor=next_cursor)

    def create_project(
        self, principal: PrincipalIdentity, request: CreateProjectRequest,
    ) -> AccessibleProject:
        with self._session_factory.begin() as session:
            # Hold the identity against concurrent deletion until its owner grant commits.
            identity = session.execute(select(Principal.id).where(
                Principal.id == principal.principal_id,
            ).with_for_update(read=True, key_share=True)).scalar_one_or_none()
            if identity is None:
                raise AuthenticationError("authenticated principal is not provisioned")
            created = session.execute(insert(Project).values(
                id=request.project_id, display_name=request.display_name, status="active",
            ).on_conflict_do_nothing(index_elements=[Project.id]).returning(Project.id)).scalar_one_or_none()
            if created is None:
                raise ProjectCreationConflictError("project ID is unavailable")
            session.add(ProjectACL(
                project_id=request.project_id, principal_id=principal.principal_id, role="owner",
            ))
            return AccessibleProject(
                project_id=request.project_id, display_name=request.display_name,
                status="active", role="owner",
            )

    def bind_project(
        self,
        principal: PrincipalIdentity,
        request: BindProjectRequest,
    ) -> ProjectBinding:
        with self._session_factory.begin() as session:
            require_project_access(session, principal.principal_id, request.project_id, "reader")
            statement = (
                insert(ScopeBinding)
                .values(
                    principal_id=principal.principal_id,
                    scope_id=request.scope_id,
                    project_id=request.project_id,
                    session_id=request.session_id,
                )
                .on_conflict_do_update(
                    index_elements=[ScopeBinding.principal_id, ScopeBinding.scope_id],
                    set_={
                        "project_id": request.project_id,
                        "session_id": request.session_id,
                        "updated_at": func.now(),
                    },
                )
                .returning(ScopeBinding)
            )
            binding = session.execute(statement).scalar_one()
            return ProjectBinding.model_validate(binding, from_attributes=True)

    def current_project(
        self,
        principal: PrincipalIdentity,
        scope_id: str,
    ) -> ProjectBinding:
        with self._session_factory() as session:
            binding = session.execute(
                select(ScopeBinding)
                .join(
                    ProjectACL,
                    (ProjectACL.project_id == ScopeBinding.project_id)
                    & (ProjectACL.principal_id == ScopeBinding.principal_id),
                )
                .where(
                    ScopeBinding.principal_id == principal.principal_id,
                    ScopeBinding.scope_id == scope_id,
                )
            ).scalar_one_or_none()
            if binding is None:
                raise BindingNotFoundError("scope is not bound")
            return ProjectBinding.model_validate(binding, from_attributes=True)

    def record_context(
        self,
        principal: PrincipalIdentity,
        request: RecordContextRequest | StoreContextEventRequest,
    ) -> ContextEventResult:
        with self._session_factory.begin() as session:
            require_project_access(session, principal.principal_id, request.project_id, "writer")
            # Serialize writes with rebinds of the same principal/conversation.
            # Session IDs may change when a conversation resumes; project identity may not.
            binding = session.execute(select(ScopeBinding).where(
                ScopeBinding.principal_id == principal.principal_id,
                ScopeBinding.scope_id == request.scope_id,
            ).with_for_update()).scalar_one_or_none()
            if binding is None or binding.project_id != request.project_id:
                raise BindingConflictError("bind this scope to the requested project before writing")
            acquire_project_transaction_lock(session, request.project_id)
            statement = (
                insert(ContextEvent)
                .values(
                    event_id=uuid4(),
                    project_id=request.project_id,
                    principal_id=principal.principal_id,
                    scope_id=request.scope_id,
                    session_id=request.session_id,
                    agent_id=request.agent_id,
                    source_kind=request.source_kind,
                    source_id=request.source_id,
                    event_kind=request.event_kind.value,
                    payload=request.payload,
                    idempotency_key=request.idempotency_key,
                    created_at=func.clock_timestamp(),
                )
                .on_conflict_do_nothing(
                    index_elements=[ContextEvent.project_id, ContextEvent.idempotency_key]
                )
                .returning(ContextEvent)
            )
            event = session.execute(statement).scalar_one_or_none()
            if event is None:
                event = session.execute(
                    select(ContextEvent).where(
                        ContextEvent.project_id == request.project_id,
                        ContextEvent.idempotency_key == request.idempotency_key,
                    )
                ).scalar_one()
                expected = request.model_dump(mode="json", exclude={"idempotency_key"})
                actual = {
                    "project_id": event.project_id,
                    "scope_id": event.scope_id,
                    "session_id": event.session_id,
                    "agent_id": event.agent_id,
                    "source_kind": event.source_kind,
                    "source_id": event.source_id,
                    "event_kind": event.event_kind,
                    "payload": event.payload,
                }
                if event.principal_id != principal.principal_id or actual != expected:
                    raise IdempotencyConflictError("idempotency key already used for a different request")
            return ContextEventResult.model_validate(event, from_attributes=True)

    @staticmethod
    def _event_result(event: ContextEvent) -> ContextEventResult:
        return ContextEventResult.model_validate(event, from_attributes=True)

    def get_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
        *,
        question_limit: int = 20,
        decision_limit: int = 20,
    ) -> ProjectContext:
        with self._session_factory() as session:
            require_project_access(session, principal.principal_id, project_id, "reader")
            project_row = session.execute(
                text(
                    """
                    SELECT p.id, p.display_name, p.status
                    FROM projects p
                    JOIN project_acl acl
                      ON acl.project_id = p.id AND acl.principal_id = :principal_id
                    WHERE p.id = :project_id
                    """
                ),
                {"principal_id": principal.principal_id, "project_id": project_id},
            ).mappings().one()

            def events(kind: str, limit: int, *, unresolved: bool = False) -> list[ContextEvent]:
                statement = select(ContextEvent).join(
                    ProjectACL,
                    (ProjectACL.project_id == ContextEvent.project_id)
                    & (ProjectACL.principal_id == principal.principal_id),
                ).where(
                    ContextEvent.project_id == project_id,
                    ContextEvent.event_kind == kind,
                )
                if unresolved:
                    statement = statement.where(
                        ContextEvent.payload["resolved"].as_boolean().is_not(True)
                    )
                statement = statement.order_by(
                    ContextEvent.created_at.desc(), ContextEvent.event_id.desc()
                ).limit(limit)
                return list(session.execute(statement).scalars())

            status_events = events("checkpoint", 1)
            questions = events("question", question_limit, unresolved=True)
            decisions = events("decision", decision_limit)
            handoffs = events("handoff", 1)
            return ProjectContext(
                overview=ProjectOverview(
                    project_id=project_row["id"],
                    display_name=project_row["display_name"],
                    status=project_row["status"],
                ),
                status=self._event_result(status_events[0]) if status_events else None,
                unresolved_questions=[self._event_result(item) for item in questions],
                recent_decisions=[self._event_result(item) for item in decisions],
                latest_handoff=self._event_result(handoffs[0]) if handoffs else None,
            )

    @staticmethod
    def _encode_search_cursor(rank: float, created_at: datetime, event_id: UUID) -> str:
        raw = json.dumps(
            [repr(rank), created_at.isoformat(), str(event_id)],
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_search_cursor(cursor: str) -> tuple[float, datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            rank, created_at, event_id = json.loads(
                base64.urlsafe_b64decode(padded.encode("ascii"))
            )
            return float(rank), datetime.fromisoformat(created_at), UUID(event_id)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid search cursor") from exc

    def search_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ContextSearchPage:
        query = query.strip()
        if not query:
            raise ValueError("search query must not be empty")
        if limit < 1 or limit > 100:
            raise ValueError("search limit must be between 1 and 100")
        cursor_values = self._decode_search_cursor(cursor) if cursor else None
        cursor_predicate = ""
        parameters: dict[str, object] = {
            "principal_id": principal.principal_id,
            "project_id": project_id,
            "query": query,
            "limit": limit + 1,
        }
        if cursor_values:
            cursor_predicate = """
              AND (rank, created_at, event_id) <
                  (:cursor_rank, :cursor_created_at, :cursor_event_id)
            """
            parameters.update(
                cursor_rank=cursor_values[0],
                cursor_created_at=cursor_values[1],
                cursor_event_id=cursor_values[2],
            )
        statement = text(
            f"""
            WITH authorized_project AS (
                SELECT p.id
                FROM projects p
                JOIN project_acl acl
                  ON acl.project_id = p.id
                 AND acl.principal_id = :principal_id
                WHERE p.id = :project_id
            ), authorized_matches AS (
                SELECT e.*,
                       ts_rank(
                           to_tsvector('simple', lower(coalesce(e.payload::text, ''))),
                           plainto_tsquery('simple', lower(:query))
                       )::double precision AS rank
                FROM authorized_project p
                JOIN context_events e ON e.project_id = p.id
                WHERE e.project_id = :project_id
                  AND to_tsvector('simple', lower(coalesce(e.payload::text, '')))
                      @@ plainto_tsquery('simple', lower(:query))
            ), page AS (
                SELECT * FROM authorized_matches
                WHERE true {cursor_predicate}
                ORDER BY rank DESC, created_at DESC, event_id DESC
                LIMIT :limit
            )
            SELECT
                COALESCE((SELECT jsonb_agg(to_jsonb(page) ORDER BY rank DESC, created_at DESC, event_id DESC)
                          FROM page), '[]'::jsonb) AS rows,
                (SELECT count(*) FROM authorized_matches) AS total_count,
                EXISTS(SELECT 1 FROM authorized_project) AS authorized
            """
        )
        with self._session_factory() as session:
            row = session.execute(statement, parameters).mappings().one()
        if not row["authorized"]:
            raise ProjectNotFoundError("project not found")
        raw_rows = list(row["rows"])
        has_more = len(raw_rows) > limit
        raw_rows = raw_rows[:limit]
        results: list[ContextSearchResult] = []
        for item in raw_rows:
            event = ContextEventResult.model_validate(
                {key: value for key, value in item.items() if key != "rank"}
            )
            results.append(ContextSearchResult(event=event, rank=float(item["rank"])))
        next_cursor = None
        if has_more and results:
            last = results[-1]
            next_cursor = self._encode_search_cursor(
                last.rank, last.event.created_at, last.event.event_id
            )
        return ContextSearchPage(
            query=query,
            results=results,
            total_count=int(row["total_count"]),
            next_cursor=next_cursor,
        )
