"""Authorized PostgreSQL repository operations."""

from __future__ import annotations

import base64
from datetime import datetime
import json
from uuid import UUID, uuid4

from sqlalchemy import select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import func

from contitext.auth import AuthenticationError, PrincipalIdentity, ProjectNotFoundError
from contitext.namespaces import ProjectResolver
from contitext.locking import acquire_project_transaction_lock
from contitext.models import ContextEvent, Principal, Project, ProjectACL, ScopeBinding, Workspace
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

    def __init__(self, session_factory: sessionmaker[Session], *, compatibility_workspace: str | None = None) -> None:
        self._session_factory = session_factory
        self.resolver = ProjectResolver(compatibility_workspace)

    def ready(self) -> bool:
        try:
            with self._session_factory() as session:
                version = session.execute(text(
                    "SELECT version_num FROM alembic_version"
                )).scalar_one()
                from contitext.migrations import HEAD_REVISION
                return version == HEAD_REVISION
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
                if (not isinstance(after, list) or len(after) != 3
                        or after[0] != str(principal.principal_id)
                        or not all(isinstance(v, str) and v for v in after[1:])):
                    raise ValueError
            except (ValueError, UnicodeError) as exc:
                raise ValueError("invalid project cursor") from exc
        with self._session_factory() as session:
            statement = self.resolver.authorized(principal.principal_id).order_by(
                Workspace.slug.collate("C"), Project.slug.collate("C"),
            ).limit(limit + 1)
            if after is not None:
                statement = statement.where(tuple_(Workspace.slug.collate("C"), Project.slug.collate("C")) > tuple_(after[1], after[2]))
            rows = session.execute(statement).all()
            projects = [AccessibleProject(
                project_id=self.resolver.reference(p, w), display_name=p.display_name, status=p.status, role=role,
            ) for p, w, role in rows[:limit]]
            next_cursor = None
            if len(rows) > limit:
                last, workspace, _ = rows[limit - 1]
                next_cursor = base64.urlsafe_b64encode(json.dumps(
                    [str(principal.principal_id), workspace.slug, last.slug]
                ).encode("utf-8")).decode("ascii").rstrip("=")
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
            workspace, slug = self.resolver.workspace_for_creation(session, principal.principal_id, request.project_id)
            created = session.execute(insert(Project).values(
                id=uuid4(), workspace_id=workspace.id, slug=slug, display_name=request.display_name, status="active",
            ).on_conflict_do_nothing(index_elements=[Project.workspace_id, Project.slug]).returning(Project)).scalar_one_or_none()
            if created is None:
                raise ProjectCreationConflictError("project ID is unavailable")
            session.add(ProjectACL(
                project_id=created.id, principal_id=principal.principal_id, role="owner",
            ))
            return AccessibleProject(
                project_id=self.resolver.reference(created, workspace), display_name=request.display_name,
                status="active", role="owner",
            )

    def bind_project(
        self,
        principal: PrincipalIdentity,
        request: BindProjectRequest,
    ) -> ProjectBinding:
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, request.project_id)
            statement = insert(ScopeBinding).values(
                principal_id=principal.principal_id, scope_id=request.scope_id,
                project_id=project.id, session_id=request.session_id,
            )
            if request.if_unbound:
                statement = statement.on_conflict_do_nothing(
                    index_elements=[ScopeBinding.principal_id, ScopeBinding.scope_id],
                ).returning(ScopeBinding)
                binding = session.execute(statement).scalar_one_or_none()
                if binding is None:
                    # A manual selection may have won the race. Never update it,
                    # including its session ID/timestamp, or fall through after revocation.
                    binding = session.execute(select(ScopeBinding).where(
                        ScopeBinding.principal_id == principal.principal_id,
                        ScopeBinding.scope_id == request.scope_id,
                    ).with_for_update()).scalar_one()
                    existing = self.resolver.resolve_uuid(session, principal.principal_id, binding.project_id)
                    return self._binding_result(binding, existing.reference)
                return self._binding_result(binding, project.reference)
            statement = statement.on_conflict_do_update(
                index_elements=[ScopeBinding.principal_id, ScopeBinding.scope_id],
                set_={"project_id": project.id, "session_id": request.session_id, "updated_at": func.now()},
            ).returning(ScopeBinding)
            binding = session.execute(statement).scalar_one()
            return self._binding_result(binding, project.reference)

    @staticmethod
    def _binding_result(binding, reference):
        return ProjectBinding(principal_id=binding.principal_id, project_id=reference,
                              scope_id=binding.scope_id, session_id=binding.session_id,
                              updated_at=binding.updated_at)

    def current_project(self, principal: PrincipalIdentity, scope_id: str) -> ProjectBinding:
        with self._session_factory.begin() as session:
            binding = session.get(ScopeBinding, (principal.principal_id, scope_id))
            if binding is None:
                raise BindingNotFoundError("scope is not bound")
            try:
                project = self.resolver.resolve_uuid(session, principal.principal_id, binding.project_id)
            except ProjectNotFoundError:
                raise BindingNotFoundError("scope is not bound") from None
            return self._binding_result(binding, project.reference)

    def record_context(
        self,
        principal: PrincipalIdentity,
        request: RecordContextRequest | StoreContextEventRequest,
    ) -> ContextEventResult:
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, request.project_id, "writer")
            # Serialize writes with rebinds of the same principal/conversation.
            # Session IDs may change when a conversation resumes; project identity may not.
            binding = session.execute(select(ScopeBinding).where(
                ScopeBinding.principal_id == principal.principal_id,
                ScopeBinding.scope_id == request.scope_id,
            ).with_for_update()).scalar_one_or_none()
            if binding is None or binding.project_id != project.id:
                raise BindingConflictError("bind this scope to the requested project before writing")
            if request.expected_binding_updated_at is not None and binding.updated_at != request.expected_binding_updated_at:
                raise BindingConflictError("conversation binding changed; checkpoint replay remains pending")
            acquire_project_transaction_lock(session, project.id)
            existing_key = session.scalar(select(ContextEvent.event_id).where(
                ContextEvent.project_id == project.id, ContextEvent.idempotency_key == request.idempotency_key,
            ))
            if existing_key is None:
                from contitext.assembly import validate_lifecycle
                validate_lifecycle(session, project.id, request)
            statement = (
                insert(ContextEvent)
                .values(
                    event_id=uuid4(),
                    project_id=project.id,
                    principal_id=principal.principal_id,
                    scope_id=request.scope_id,
                    session_id=request.session_id,
                    agent_id=request.agent_id,
                    source_kind=request.source_kind,
                    source_id=request.source_id,
                    event_kind=request.event_kind.value,
                    payload=request.payload,
                    event_metadata=request.event_metadata.model_dump(mode="json") if request.event_metadata is not None else None,
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
                        ContextEvent.project_id == project.id,
                        ContextEvent.idempotency_key == request.idempotency_key,
                    )
                ).scalar_one()
                expected = request.model_dump(mode="json", exclude={"idempotency_key", "expected_binding_updated_at"})
                expected["project_id"] = str(project.id)
                actual = {
                    "project_id": str(event.project_id),
                    "scope_id": event.scope_id,
                    "session_id": event.session_id,
                    "agent_id": event.agent_id,
                    "source_kind": event.source_kind,
                    "source_id": event.source_id,
                    "event_kind": event.event_kind,
                    "payload": event.payload,
                    "event_metadata": event.event_metadata,
                }
                if event.principal_id != principal.principal_id or actual != expected:
                    raise IdempotencyConflictError("idempotency key already used for a different request")
            return self._event_result(event, project.reference)

    @staticmethod
    def _event_result(event: ContextEvent, reference: str) -> ContextEventResult:
        return ContextEventResult.model_validate({**{column.name: getattr(event, column.name) for column in ContextEvent.__table__.columns}, "project_id": reference})

    def get_context(
        self,
        principal: PrincipalIdentity,
        project_id: str,
        *,
        question_limit: int = 20,
        decision_limit: int = 20,
    ) -> ProjectContext:
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, project_id)
            project_id = project.id

            def events(kind: str, limit: int, *, unresolved: bool = False) -> list[ContextEvent]:
                from contitext.assembly import event_selection
                return list(session.scalars(event_selection(project_id, kind, limit=limit)))

            status_events = events("checkpoint", 1)
            questions = events("question", question_limit, unresolved=True)
            decisions = events("decision", decision_limit)
            handoffs = events("handoff", 1)
            return ProjectContext(
                overview=ProjectOverview(
                    project_id=project.reference,
                    display_name=project.project.display_name,
                    status=project.project.status,
                ),
                status=self._event_result(status_events[0], project.reference) if status_events else None,
                unresolved_questions=[self._event_result(item, project.reference) for item in questions],
                recent_decisions=[self._event_result(item, project.reference) for item in decisions],
                latest_handoff=self._event_result(handoffs[0], project.reference) if handoffs else None,
            )

    def assemble_context(self, principal, project_id, options):
        from contitext.assembly import assemble
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, project_id)
            return assemble(session, project, options)

    @staticmethod
    def _encode_search_cursor(rank: float, created_at: datetime, event_id: UUID, identity: list[str]) -> str:
        raw = json.dumps(
            [identity, repr(rank), created_at.isoformat(), str(event_id)],
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_search_cursor(cursor: str, identity: list[str]) -> tuple[float, datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            actual_identity, rank, created_at, event_id = json.loads(
                base64.urlsafe_b64decode(padded.encode("ascii"))
            )
            if actual_identity != identity:
                raise ValueError
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
        cursor_predicate = ""
        parameters: dict[str, object] = {
            "principal_id": principal.principal_id,
            "project_id": project_id,
            "query": query,
            "limit": limit + 1,
        }
        statement = text(
            """
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
                WHERE true __CURSOR_PREDICATE__
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
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, project_id)
            parameters["project_id"] = project.id
            cursor_identity = [str(principal.principal_id), str(project.id), query]
            if cursor:
                cursor_values = self._decode_search_cursor(cursor, cursor_identity)
                cursor_predicate = "AND (rank, created_at, event_id) < (:cursor_rank, :cursor_created_at, :cursor_event_id)"
                parameters.update(cursor_rank=cursor_values[0], cursor_created_at=cursor_values[1], cursor_event_id=cursor_values[2])
            statement = text(str(statement).replace("__CURSOR_PREDICATE__", cursor_predicate))
            row = session.execute(statement, parameters).mappings().one()
        if not row["authorized"]:
            raise ProjectNotFoundError("project not found")
        raw_rows = list(row["rows"])
        has_more = len(raw_rows) > limit
        raw_rows = raw_rows[:limit]
        results: list[ContextSearchResult] = []
        for item in raw_rows:
            item["project_id"] = project.reference
            event = ContextEventResult.model_validate(
                {key: value for key, value in item.items() if key != "rank"}
            )
            results.append(ContextSearchResult(event=event, rank=float(item["rank"])))
        next_cursor = None
        if has_more and results:
            last = results[-1]
            next_cursor = self._encode_search_cursor(
                last.rank, last.event.created_at, last.event.event_id, cursor_identity
            )
        return ContextSearchPage(
            query=query,
            results=results,
            total_count=int(row["total_count"]),
            next_cursor=next_cursor,
        )
