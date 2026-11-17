from __future__ import annotations

from datetime import timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from contitext.auth import PrincipalIdentity, ProjectNotFoundError
from contitext.db import create_session_factory
from contitext.repository import IdempotencyConflictError, Repository
from contitext.schemas import EventKind, RecordContextRequest, RecordEventKind
from contitext.service import ContextService, WriterFencedError


@pytest.fixture(params=[
    ("hermes", "hermes:session/01"),
    ("openclaw", "openclaw:thread#alpha"),
    ("codex", "codex:task/feature-A"),
    ("claude-code", "claude-code:conversation:ß-42"),
])
def source_identity(request: pytest.FixtureRequest) -> tuple[str, str]:
    return request.param


def seed_event_access(database_url: str) -> tuple[PrincipalIdentity, PrincipalIdentity]:
    writer = PrincipalIdentity(uuid4(), "Writer")
    reader = PrincipalIdentity(uuid4(), "Reader")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""INSERT INTO projects (id, display_name, status)
                VALUES ('alpha', 'Alpha', 'active'), ('beta', 'Beta', 'active')"""))
            connection.execute(
                text("INSERT INTO principals (id, name) VALUES (:writer, 'Writer'), (:reader, 'Reader')"),
                {"writer": writer.principal_id, "reader": reader.principal_id},
            )
            connection.execute(text("""INSERT INTO project_acl (project_id, principal_id, role)
                VALUES ('alpha', :writer, 'writer'), ('alpha', :reader, 'reader'),
                       ('beta', :reader, 'owner')"""),
                {"writer": writer.principal_id, "reader": reader.principal_id},
            )
    finally:
        engine.dispose()
    return writer, reader


def make_event_request(
    *,
    project_id: str = "alpha",
    source_kind: str = "hermes",
    source_id: str = "hermes:session/01",
    idempotency_key: str = "event-key-1",
) -> RecordContextRequest:
    return RecordContextRequest(
        project_id=project_id,
        scope_id="scope:exact",
        session_id="session:exact",
        agent_id="agent:exact",
        source_kind=source_kind,
        source_id=source_id,
        event_kind=RecordEventKind.note,
        payload={"text": "preserve exact provenance"},
        idempotency_key=idempotency_key,
    )


def test_required_provenance_fields_are_rejected_when_missing() -> None:
    base = make_event_request().model_dump()
    for field in ("agent_id", "source_kind", "source_id", "scope_id", "session_id"):
        invalid = dict(base)
        invalid.pop(field)
        with pytest.raises(ValidationError):
            RecordContextRequest.model_validate(invalid)


def test_generic_service_record_rejects_handoff_kind(migrated_database_url: str) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    invalid = RecordContextRequest.model_construct(
        **make_event_request().model_dump(exclude={"event_kind"}),
        event_kind=EventKind.handoff,
    )
    try:
        with pytest.raises(ValidationError):
            service.record_context(writer, invalid)
    finally:
        engine.dispose()


def test_service_writer_fence_blocks_until_removed(
    migrated_database_url: str, tmp_path
) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    fence = tmp_path / "writers-fenced"
    fence.write_text("maintenance\n")
    service = ContextService(
        Repository(create_session_factory(engine)), writer_fence_file=fence
    )
    try:
        with pytest.raises(WriterFencedError, match="writers are fenced"):
            service.record_context(writer, make_event_request())
        fence.unlink()
        recorded = service.record_context(writer, make_event_request())
        assert recorded.idempotency_key == "event-key-1"
    finally:
        engine.dispose()


def test_record_context_preserves_exact_source_ids_and_server_metadata(
    migrated_database_url: str,
    source_identity: tuple[str, str],
) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    source_kind, source_id = source_identity
    try:
        event = service.record_context(
            writer,
            make_event_request(source_kind=source_kind, source_id=source_id),
        )
        assert event.source_kind == source_kind
        assert event.source_id == source_id
        assert event.scope_id == "scope:exact"
        assert event.session_id == "session:exact"
        assert event.agent_id == "agent:exact"
        assert event.created_at.tzinfo is not None
        utc_offset = event.created_at.astimezone(timezone.utc).utcoffset()
        assert utc_offset is not None
        assert utc_offset.total_seconds() == 0
    finally:
        engine.dispose()


def test_idempotent_retry_returns_original_event_without_duplicate(
    migrated_database_url: str,
) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    try:
        first = service.record_context(writer, make_event_request())
        second = service.record_context(writer, make_event_request())
        assert second.event_id == first.event_id
        assert second.payload == first.payload
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT count(*) FROM context_events WHERE project_id='alpha' AND idempotency_key='event-key-1'")
            ).scalar_one()
        assert count == 1
    finally:
        engine.dispose()


def test_idempotency_rejects_changed_payload_and_provenance(migrated_database_url: str) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    try:
        original = service.record_context(writer, make_event_request())
        for field, value in (("payload", {"text": "changed"}), ("source_id", "another-source"),
                             ("scope_id", "another-scope"), ("session_id", "another-session")):
            changed = make_event_request().model_copy(update={field: value})
            with pytest.raises(IdempotencyConflictError):
                service.record_context(writer, changed)
        assert service.record_context(writer, make_event_request()).event_id == original.event_id
    finally:
        engine.dispose()


def test_writer_acl_and_project_filter_are_enforced(migrated_database_url: str) -> None:
    writer, reader = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    repository = Repository(create_session_factory(engine))
    service = ContextService(repository)
    try:
        with pytest.raises(ProjectNotFoundError, match="project not found"):
            service.record_context(reader, make_event_request(project_id="alpha"))
        with pytest.raises(ProjectNotFoundError, match="project not found"):
            repository.record_context(writer, make_event_request(project_id="beta"))
    finally:
        engine.dispose()


def test_idempotency_key_cannot_be_reused_by_another_principal(migrated_database_url: str) -> None:
    writer, reader = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    try:
        service.record_context(writer, make_event_request())
        with engine.begin() as connection:
            connection.execute(text("UPDATE project_acl SET role='writer' WHERE project_id='alpha' AND principal_id=:id"), {"id": reader.principal_id})
        with pytest.raises(IdempotencyConflictError):
            service.record_context(reader, make_event_request())
    finally:
        engine.dispose()


def test_repository_and_service_expose_no_event_update_or_delete_api(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    repository = Repository(create_session_factory(engine))
    service = ContextService(repository)
    try:
        for target in (repository, service):
            assert not hasattr(target, "update_context")
            assert not hasattr(target, "delete_context")
            assert not hasattr(target, "update_event")
            assert not hasattr(target, "delete_event")
    finally:
        engine.dispose()
