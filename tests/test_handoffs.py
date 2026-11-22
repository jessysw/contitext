from __future__ import annotations

from workspace_fixtures import seed_members


from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from contitext.auth import PrincipalIdentity
from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.schemas import BindProjectRequest, HandoffRequest
from contitext.service import ContextService


def request(key: str = "handoff-1", **changes) -> HandoffRequest:
    values = dict(
        project_id="alpha", scope_id="scope:exact", session_id="session:exact",
        agent_id="agent:exact", source_kind="hermes", source_id="source:exact",
        summary="transfer summary", next_action="continue implementation",
        completed=["task one"], current=["task two"], blockers=["none"],
        idempotency_key=key,
    )
    values.update(changes)
    return HandoffRequest(**values)


def setup(database_url: str):
    engine = create_engine(database_url)
    principal = PrincipalIdentity(uuid4(), "Writer")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (slug, workspace_id,display_name,status) VALUES ('alpha', '00000000-0000-4000-8000-000000000001','Alpha','active')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'Writer')"), {"id": principal.principal_id})
        seed_members(connection)
        connection.execute(text("INSERT INTO project_acl (project_id,principal_id,role) VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'),:id,'writer')"), {"id": principal.principal_id})
    service = ContextService(Repository(create_session_factory(engine)))
    service.bind_project(principal, BindProjectRequest(project_id="alpha", scope_id="scope:exact", session_id="session:exact"))
    return engine, principal, service


def test_handoff_requires_summary_next_action_and_exact_provenance() -> None:
    base = request().model_dump()
    for field in ("summary", "next_action", "agent_id", "source_kind", "source_id", "scope_id", "session_id"):
        invalid = dict(base)
        invalid.pop(field)
        with pytest.raises(ValidationError):
            HandoffRequest.model_validate(invalid)


def test_handoff_is_append_only_searchable_hydrated_and_idempotent(migrated_database_url: str) -> None:
    engine, principal, service = setup(migrated_database_url)
    try:
        first = service.create_handoff(principal, request())
        retry = service.create_handoff(principal, request())
        assert retry.event_id == first.event_id
        assert first.event_kind.value == "handoff"
        assert first.payload == {
            "summary": "transfer summary", "next_action": "continue implementation",
            "completed": ["task one"], "current": ["task two"], "blockers": ["none"],
        }
        assert first.agent_id == "agent:exact" and first.source_id == "source:exact"
        assert service.get_context(principal, "alpha").latest_handoff.event_id == first.event_id
        found = service.search_context(principal, "alpha", "implementation")
        assert [item.event.event_id for item in found.results] == [first.event_id]
    finally:
        engine.dispose()


def test_concurrent_handoffs_preserve_every_unique_request(migrated_database_url: str) -> None:
    engine, principal, service = setup(migrated_database_url)
    try:
        count = 40
        with ThreadPoolExecutor(max_workers=12) as pool:
            events = list(pool.map(lambda index: service.create_handoff(principal, request(
                key=f"handoff-{index}", summary=f"summary {index}", next_action=f"next {index}",
            )), range(count)))
        assert len({event.event_id for event in events}) == count
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM context_events WHERE project_id=(SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha') AND event_kind='handoff'" )).scalar_one() == count
        latest = service.get_context(principal, "alpha").latest_handoff
        expected = max(events, key=lambda item: (item.created_at, item.event_id))
        assert latest.event_id == expected.event_id
    finally:
        engine.dispose()
