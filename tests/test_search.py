from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from contitext.auth import PrincipalIdentity, ProjectNotFoundError
from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.schemas import HandoffRequest, RecordContextRequest, RecordEventKind
from contitext.service import ContextService


def build_service(database_url: str):
    engine = create_engine(database_url)
    principal = PrincipalIdentity(uuid4(), "Search User")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id, display_name, status) VALUES ('alpha','Alpha','active'),('beta','Beta','paused')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'Search User')"), {"id": principal.principal_id})
        connection.execute(text("INSERT INTO project_acl (project_id,principal_id,role) VALUES ('alpha',:id,'writer'),('beta',:id,'writer')"), {"id": principal.principal_id})
    return engine, principal, ContextService(Repository(create_session_factory(engine)))


def record(service, principal, project, kind, text_value, key, **extra):
    return service.record_context(principal, RecordContextRequest(
        project_id=project, scope_id="scope", session_id="session", agent_id="agent",
        source_kind="test", source_id=f"source:{key}", event_kind=kind,
        payload={"text": text_value, **extra}, idempotency_key=key,
    ))


def test_hydration_is_bounded_and_in_fixed_startup_order(migrated_database_url: str) -> None:
    engine, principal, service = build_service(migrated_database_url)
    try:
        record(service, principal, "alpha", RecordEventKind.checkpoint, "current status", "s")
        record(service, principal, "alpha", RecordEventKind.question, "open", "q1")
        record(service, principal, "alpha", RecordEventKind.question, "closed", "q2", resolved=True)
        record(service, principal, "alpha", RecordEventKind.decision, "decision", "d")
        service.create_handoff(principal, HandoffRequest(
            project_id="alpha", scope_id="scope", session_id="session", agent_id="agent",
            source_kind="test", source_id="source:h", summary="handoff",
            next_action="continue", idempotency_key="h",
        ))
        context = service.get_context(principal, "alpha")
        assert list(context.model_dump()) == ["overview", "status", "unresolved_questions", "recent_decisions", "latest_handoff"]
        assert context.overview.model_dump() == {"project_id": "alpha", "display_name": "Alpha", "status": "active"}
        assert context.status.payload["text"] == "current status"
        assert [item.payload["text"] for item in context.unresolved_questions] == ["open"]
        assert [item.payload["text"] for item in context.recent_decisions] == ["decision"]
        assert context.latest_handoff is not None
        assert context.latest_handoff.payload["summary"] == "handoff"
    finally:
        engine.dispose()


def test_search_ranking_pagination_and_project_isolation(migrated_database_url: str) -> None:
    engine, principal, service = build_service(migrated_database_url)
    try:
        record(service, principal, "alpha", RecordEventKind.note, "needle needle needle", "a1")
        record(service, principal, "alpha", RecordEventKind.note, "needle once", "a2")
        record(service, principal, "beta", RecordEventKind.note, "needle beta secret", "b1")
        first = service.search_context(principal, "alpha", "needle", limit=1)
        assert first.total_count == 2
        assert len(first.results) == 1 and first.next_cursor
        assert first.results[0].event.project_id == "alpha"
        second = service.search_context(principal, "alpha", "needle", limit=1, cursor=first.next_cursor)
        assert second.total_count == 2
        assert len(second.results) == 1
        assert second.results[0].event.event_id != first.results[0].event.event_id
        assert second.next_cursor is None
        assert service.search_context(principal, "alpha", "absent").model_dump() == {
            "query": "absent", "results": [], "total_count": 0, "next_cursor": None,
        }
    finally:
        engine.dispose()


def test_search_unknown_and_unauthorized_are_indistinguishable(migrated_database_url: str) -> None:
    engine, principal, service = build_service(migrated_database_url)
    denied = PrincipalIdentity(uuid4(), "Denied")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'Denied')"), {"id": denied.principal_id})
    try:
        failures = []
        for project in ("alpha", "missing"):
            with pytest.raises(ProjectNotFoundError) as caught:
                service.get_context(denied, project)
            failures.append((type(caught.value), str(caught.value)))
        assert failures[0] == failures[1]
        search_failures = []
        for project in ("alpha", "missing"):
            with pytest.raises(ProjectNotFoundError) as caught:
                service.search_context(denied, project, "needle")
            search_failures.append((type(caught.value), str(caught.value)))
        assert search_failures[0] == search_failures[1]
    finally:
        engine.dispose()


def test_search_cursor_validation(migrated_database_url: str) -> None:
    engine, principal, service = build_service(migrated_database_url)
    try:
        with pytest.raises(ValueError, match="invalid search cursor"):
            service.search_context(principal, "alpha", "needle", cursor="not-a-cursor")
    finally:
        engine.dispose()