from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, ProjectNotFoundError, TokenStore
from contitext.db import create_session_factory
from contitext.projector import Projector, ProjectionSafetyError
from contitext.repository import Repository
from contitext.schemas import HandoffRequest, RecordContextRequest, RecordEventKind
from contitext.service import ContextService


def setup(database_url: str, tmp_path: Path):
    engine = create_engine(database_url)
    owner = PrincipalIdentity(uuid4(), "Owner")
    writer = PrincipalIdentity(uuid4(), "Writer")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (id,display_name,status) VALUES ('alpha','Alpha','active')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:owner,'Owner'),(:writer,'Writer')"), {"owner": owner.principal_id, "writer": writer.principal_id})
        connection.execute(text("INSERT INTO project_acl (project_id,principal_id,role) VALUES ('alpha',:owner,'owner'),('alpha',:writer,'writer')"), {"owner": owner.principal_id, "writer": writer.principal_id})
    project = tmp_path / "projects" / "alpha"
    (project / "HANDOFFS").mkdir(parents=True)
    curated = {}
    for name in ("NOTES.md", "DECISIONS.md", "OPEN-QUESTIONS.md", "STATUS.md"):
        curated[name] = f"# Curated {name}\n\nKeep this text exactly.\n"
        (project / name).write_text(curated[name])
    factory = create_session_factory(engine)
    service = ContextService(Repository(factory), Projector(factory, tmp_path / "projects"))
    return engine, owner, writer, service, project, curated


def record(service, principal, kind, key, text_value):
    return service.record_context(principal, RecordContextRequest(
        project_id="alpha", scope_id=f"scope:{key}", session_id=f"session:{key}",
        agent_id=f"agent:{key}", source_kind="test", source_id=f"source:{key}",
        event_kind=kind, payload={"text": text_value}, idempotency_key=key,
    ))


def test_fresh_repeated_partial_restart_and_curated_preservation(migrated_database_url: str, tmp_path: Path) -> None:
    engine, owner, _, service, project, curated = setup(migrated_database_url, tmp_path)
    try:
        events = [
            record(service, owner, RecordEventKind.note, "n", "note text"),
            record(service, owner, RecordEventKind.decision, "d", "decision text"),
            record(service, owner, RecordEventKind.question, "q", "question text"),
            record(service, owner, RecordEventKind.checkpoint, "c", "checkpoint text"),
        ]
        handoff = service.create_handoff(owner, HandoffRequest(
            project_id="alpha", scope_id="scope:h", session_id="session:h", agent_id="agent:h",
            source_kind="test", source_id="source:h", summary="handoff summary",
            next_action="next action", idempotency_key="h",
        ))
        first = service.project_context(owner, "alpha")
        assert first.projected_event_ids == [event.event_id for event in sorted(events + [handoff], key=lambda item: (item.created_at, item.event_id))]
        assert set(first.files_changed) == {"NOTES.md", "DECISIONS.md", "OPEN-QUESTIONS.md", "STATUS.md", f"HANDOFFS/{handoff.event_id}.md"}
        for name, prefix in curated.items():
            content = (project / name).read_text()
            assert content.startswith(prefix)
        snapshots = {path.relative_to(project): path.read_bytes() for path in project.rglob("*.md")}
        second = service.project_context(owner, "alpha")
        assert second.projected_event_ids == [] and second.files_changed == []
        assert snapshots == {path.relative_to(project): path.read_bytes() for path in project.rglob("*.md")}

        # Simulate an offset lag after files were atomically committed; markers prevent duplication.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM projection_offsets WHERE project_id='alpha'"))
        restarted = ContextService(Repository(create_session_factory(engine)), Projector(create_session_factory(engine), tmp_path / "projects"))
        recovered = restarted.project_context(owner, "alpha")
        assert len(recovered.projected_event_ids) == 5 and recovered.files_changed == []
        assert snapshots == {path.relative_to(project): path.read_bytes() for path in project.rglob("*.md")}
    finally:
        engine.dispose()


def test_concurrent_projection_is_exact_once_and_stably_ordered(migrated_database_url: str, tmp_path: Path) -> None:
    engine, owner, _, service, project, _ = setup(migrated_database_url, tmp_path)
    try:
        events = [record(service, owner, RecordEventKind.note, f"n-{index}", f"note {index}") for index in range(20)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: service.project_context(owner, "alpha"), range(2)))
        assert sum(len(result.projected_event_ids) for result in results) == 20
        text_value = (project / "NOTES.md").read_text()
        ordered = sorted(events, key=lambda item: (item.created_at, item.event_id))
        positions = [text_value.index(str(item.event_id)) for item in ordered]
        assert positions == sorted(positions)
        assert all(text_value.count(f"contitext:event:{item.event_id}:begin") == 1 for item in events)
    finally:
        engine.dispose()


def test_delayed_writer_cannot_fall_behind_projection_high_water(
    migrated_database_url: str, tmp_path: Path
) -> None:
    engine, owner, _, service, project, _ = setup(migrated_database_url, tmp_path)
    writer_engine = create_engine(migrated_database_url)
    writer_service = ContextService(Repository(create_session_factory(writer_engine)))
    writer_at_lock = threading.Event()
    release_writer = threading.Event()

    def block_writer_lock(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and not writer_at_lock.is_set():
            writer_at_lock.set()
            assert release_writer.wait(5), "writer lock barrier timed out"

    sqlalchemy_event.listen(writer_engine, "before_cursor_execute", block_writer_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                record, writer_service, owner, RecordEventKind.note,
                "delayed", "committed after the first projection",
            )
            assert writer_at_lock.wait(5), "writer never reached project lock"

            before_commit = service.project_context(owner, "alpha")
            assert before_commit.projected_event_ids == []
            release_writer.set()
            delayed = pending.result(timeout=5)

        projected = service.project_context(owner, "alpha")
        repeated = service.project_context(owner, "alpha")
        assert projected.projected_event_ids == [delayed.event_id]
        assert repeated.projected_event_ids == []
        content = (project / "NOTES.md").read_text()
        assert content.count(f"contitext:event:{delayed.event_id}:begin") == 1
    finally:
        release_writer.set()
        sqlalchemy_event.remove(writer_engine, "before_cursor_execute", block_writer_lock)
        writer_engine.dispose()
        engine.dispose()


def test_project_directory_swap_cannot_redirect_projection(
    migrated_database_url: str, tmp_path: Path
) -> None:
    engine, owner, _, service, project, _ = setup(migrated_database_url, tmp_path)
    try:
        note = record(service, owner, RecordEventKind.note, "swap-project", "safe target")
        parked = project.with_name("alpha-opened")
        outside = tmp_path / "outside-project"
        outside.mkdir()
        outside_notes = outside / "NOTES.md"
        outside_notes.write_text("OUTSIDE MUST NOT CHANGE\n")

        def swap(label: str) -> None:
            if label == "project" and not parked.exists():
                project.rename(parked)
                project.symlink_to(outside, target_is_directory=True)

        factory = create_session_factory(engine)
        guarded = ContextService(
            Repository(factory),
            Projector(factory, tmp_path / "projects", filesystem_hook=swap),
        )
        result = guarded.project_context(owner, "alpha")
        assert result.projected_event_ids == [note.event_id]
        assert str(note.event_id) in (parked / "NOTES.md").read_text()
        assert outside_notes.read_text() == "OUTSIDE MUST NOT CHANGE\n"
    finally:
        engine.dispose()


def test_handoffs_directory_swap_cannot_redirect_projection(
    migrated_database_url: str, tmp_path: Path
) -> None:
    engine, owner, _, service, project, _ = setup(migrated_database_url, tmp_path)
    try:
        handoff = service.create_handoff(owner, HandoffRequest(
            project_id="alpha", scope_id="scope:swap", session_id="session:swap",
            agent_id="agent:swap", source_kind="test", source_id="source:swap",
            summary="safe handoff", next_action="continue", idempotency_key="swap-handoff",
        ))
        handoffs = project / "HANDOFFS"
        parked = project / "HANDOFFS-opened"
        outside = tmp_path / "outside-handoffs"
        outside.mkdir()

        def swap(label: str) -> None:
            if label == "handoffs" and not parked.exists():
                handoffs.rename(parked)
                handoffs.symlink_to(outside, target_is_directory=True)

        factory = create_session_factory(engine)
        guarded = ContextService(
            Repository(factory),
            Projector(factory, tmp_path / "projects", filesystem_hook=swap),
        )
        result = guarded.project_context(owner, "alpha")
        assert result.projected_event_ids == [handoff.event_id]
        assert (parked / f"{handoff.event_id}.md").is_file()
        assert list(outside.iterdir()) == []
    finally:
        engine.dispose()


def test_projection_requires_owner_and_rejects_symlinks(migrated_database_url: str, tmp_path: Path) -> None:
    engine, owner, writer, service, project, _ = setup(migrated_database_url, tmp_path)
    try:
        record(service, owner, RecordEventKind.note, "n", "note")
        with pytest.raises(ProjectNotFoundError, match="project not found"):
            service.project_context(writer, "alpha")
        external = tmp_path / "external.md"
        external.write_text("DO NOT CHANGE\n")
        notes = project / "NOTES.md"
        notes.unlink()
        notes.symlink_to(external)
        with pytest.raises(ProjectionSafetyError, match="symlink"):
            service.project_context(owner, "alpha")
        assert external.read_text() == "DO NOT CHANGE\n"
    finally:
        engine.dispose()


def test_http_projection_uses_same_owner_acl_and_service(migrated_database_url: str, tmp_path: Path) -> None:
    engine, owner, writer, service, project, _ = setup(migrated_database_url, tmp_path)
    try:
        event = record(service, owner, RecordEventKind.note, "http-note", "project through HTTP")
        store = TokenStore.from_json(json.dumps({
            "owner-token": {"principal_id": str(owner.principal_id), "name": owner.name},
            "writer-token": {"principal_id": str(writer.principal_id), "name": writer.name},
        }))
        client = TestClient(create_app(service=service, token_store=store))
        denied = client.post("/v1/projects/alpha/projection", headers={"Authorization": "Bearer writer-token"})
        assert denied.status_code == 404 and denied.json() == {"detail": "project not found"}
        projected = client.post("/v1/projects/alpha/projection", headers={"Authorization": "Bearer owner-token"})
        assert projected.status_code == 200
        assert projected.json()["projected_event_ids"] == [str(event.event_id)]
        assert str(event.event_id) in (project / "NOTES.md").read_text()
    finally:
        engine.dispose()