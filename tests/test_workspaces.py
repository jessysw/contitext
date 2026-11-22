"""Namespace isolation through the real service, HTTP, MCP, CLI and reader."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import create_engine, event, select, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, ProjectNotFoundError, TokenStore
from contitext.db import create_session_factory
from contitext.mcp_server import create_mcp_server
from contitext.models import ContextEvent, Principal, Project, ProjectACL, ScopeBinding, WorkspaceMember
from contitext.projector import Projector
from contitext.reader import project_filename, snapshot
from contitext.repository import BindingConflictError, BindingNotFoundError, Repository
from contitext.schemas import BindProjectRequest, CreateProjectRequest, HandoffRequest, RecordContextRequest
from contitext.service import ContextService
from contitext.workspaces import change_membership, create_workspace, WorkspaceNotFoundError
from test_cli import cli


@pytest.fixture
def spaces(migrated_database_url):
    engine = create_engine(migrated_database_url)
    factory = create_session_factory(engine)
    owner, visitor, outsider = [PrincipalIdentity(uuid4(), name) for name in ("Owner", "Visitor", "Outsider")]
    with factory.begin() as session:
        session.add_all([Principal(id=p.principal_id, name=p.name) for p in (owner, visitor, outsider)])
        session.flush()
        one = create_workspace(session, "one", "Workspace One", owner.principal_id)
        two = create_workspace(session, "two", "Workspace Two", owner.principal_id)
        change_membership(session, "one", owner.principal_id, visitor.principal_id, "member")
    service = ContextService(Repository(factory, compatibility_workspace=""))
    for ref in ("one/research", "two/research"):
        service.create_project(owner, CreateProjectRequest(project_id=ref, display_name="Research"))
    with factory.begin() as session:
        project = session.scalar(select(Project).where(Project.workspace_id == one.id))
        session.add(ProjectACL(project_id=project.id, principal_id=visitor.principal_id, role="owner"))
    yield engine, factory, owner, visitor, outsider, service, one.id, two.id
    engine.dispose()


def bind(service, principal, ref, scope="scope"):
    return service.bind_project(principal, BindProjectRequest(project_id=ref, scope_id=scope, session_id="session"))


def record(service, principal, ref, key="same-key", scope="scope"):
    return service.record_context(principal, RecordContextRequest(
        project_id=ref, scope_id=scope, session_id="session", agent_id="metadata-only",
        source_kind="test", source_id="test-source", event_kind="checkpoint",
        payload={"summary": f"searchable {ref}"}, idempotency_key=key,
    ))


def test_same_slug_uses_distinct_uuid_binding_event_idempotency_and_search(spaces):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    first_page = service.list_projects(owner, limit=1)
    assert [p.project_id for p in first_page.projects] == ["one/research"]
    assert [p.project_id for p in service.list_projects(owner, cursor=first_page.next_cursor).projects] == ["two/research"]
    with pytest.raises(ValueError, match="cursor"):
        service.list_projects(visitor, cursor=first_page.next_cursor)
    ids = []
    for ref in ("one/research", "two/research"):
        with pytest.raises(BindingNotFoundError):
            service.current_project(owner, ref)
        bind(service, owner, ref, ref)
        ids.append(record(service, owner, ref, scope=ref).event_id)
        record(service, owner, ref, "another-key", scope=ref)
    assert ids[0] != ids[1]
    with pytest.raises(BindingConflictError):
        record(service, owner, "two/research", scope="one/research")
    with factory() as session:
        projects = list(session.scalars(select(Project)))
        assert len(projects) == 2 and all(isinstance(p.id, UUID) for p in projects)
        assert len({p.id for p in projects}) == 2
        assert session.get(ScopeBinding, (owner.principal_id, "one/research")).project_id in {p.id for p in projects}
    page = service.search_context(owner, "one/research", "searchable", limit=1)
    assert page.total_count == 2 and page.results[0].event.project_id == "one/research"
    for ref, principal, query in [("two/research", owner, "searchable"), ("one/research", visitor, "searchable"), ("one/research", owner, "other")]:
        with pytest.raises(ValueError, match="cursor"):
            service.search_context(principal, ref, query, cursor=page.next_cursor)


def test_compatibility_is_explicit_and_never_rebinds(spaces, monkeypatch):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    with pytest.raises(ValueError, match="workspace/project"):
        service.get_context(owner, "research")
    compatible = ContextService(Repository(factory, compatibility_workspace="one"))
    bind(compatible, owner, "research")
    a = record(compatible, owner, "research")
    b = compatible.record_context(owner, RecordContextRequest(
        project_id="one/research", scope_id="scope", session_id="session", agent_id="metadata-only",
        source_kind="test", source_id="test-source", event_kind="checkpoint",
        payload={"summary": "searchable research"}, idempotency_key="same-key",
    ))
    assert a.event_id == b.event_id
    changed = ContextService(Repository(factory, compatibility_workspace="two"))
    assert changed.current_project(owner, "scope").project_id == "one/research"
    with pytest.raises(BindingConflictError):
        record(changed, owner, "research")
    monkeypatch.delenv("CONTITEXT_COMPATIBILITY_WORKSPACE", raising=False)
    with pytest.raises(ValueError, match="workspace/project"):
        Repository(factory).get_context(owner, "research")
    assert service.current_project(owner, "scope").project_id == "one/research"


def test_membership_and_project_acl_are_both_required_without_enumeration(spaces):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    with factory.begin() as session:
        # Even workspace owners have no implicit access to projects owned by others.
        change_membership(session, "one", owner.principal_id, outsider.principal_id, "owner")
        p = session.scalar(select(Project).where(Project.workspace_id == two))
        session.add(ProjectACL(project_id=p.id, principal_id=visitor.principal_id, role="owner"))
    assert service.list_projects(outsider).projects == []
    assert [p.project_id for p in service.list_projects(visitor).projects] == ["one/research"]
    for who, ref in [(outsider, "one/research"), (visitor, "two/research"), (visitor, "missing/research"), (visitor, "one/missing")]:
        with pytest.raises(ProjectNotFoundError, match="^project not found$"):
            service.get_context(who, ref)
        with pytest.raises(ProjectNotFoundError, match="^project not found$"):
            bind(service, who, ref)
    with pytest.raises(ProjectNotFoundError):
        service.create_project(visitor, CreateProjectRequest(project_id="two/new", display_name="No membership"))
    service.create_project(visitor, CreateProjectRequest(project_id="one/new", display_name="Caller owned"))
    with pytest.raises(BindingNotFoundError):
        service.current_project(visitor, "never-selected")


@pytest.mark.parametrize("revocation", ["membership", "acl"])
def test_revocation_denies_existing_mcp_http_binding_search_writes_and_export(spaces, tmp_path, revocation):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    bind(service, visitor, "one/research")
    record(service, visitor, "one/research")
    tokens = TokenStore.from_json(json.dumps({"test-token": {"principal_id": str(visitor.principal_id), "name": visitor.name}}))
    client = TestClient(create_app(service=service, token_store=tokens))
    headers = {"Authorization": "Bearer test-token"}
    mcp = create_mcp_server(service, visitor)
    assert client.get("/v1/projects/one/research/context", headers=headers).status_code == 200
    assert snapshot(engine, visitor, ["one/research"])[0]["events"]
    with factory.begin() as session:
        if revocation == "membership":
            change_membership(session, "one", owner.principal_id, visitor.principal_id, None)
        else:
            session.execute(text("DELETE FROM project_acl WHERE principal_id=:id"), {"id": visitor.principal_id})
    for path in ("/v1/projects/one/research/context", "/v1/projects/one/research/search?q=searchable", "/v1/scopes/scope/binding"):
        assert client.get(path, headers=headers).status_code == 404
    assert client.get("/v1/projects", headers=headers).json()["projects"] == []
    calls = [
        ("project_current", {"scope_id": "scope"}),
        ("project_bind", {"scope_id": "scope", "session_id": "s", "project_id": "one/research"}),
        ("context_get", {"project_id": "one/research"}),
        ("context_search", {"project_id": "one/research", "query": "searchable"}),
        ("context_record", dict(project_id="one/research", scope_id="scope", session_id="s", agent_id=str(owner.principal_id), source_kind="test", source_id="x", event_kind="note", payload={}, idempotency_key="new")),
        ("context_handoff", dict(project_id="one/research", scope_id="scope", session_id="s", agent_id=str(owner.principal_id), source_kind="test", source_id="x", summary="x", next_action="x", idempotency_key="new")),
    ]
    for tool, args in calls:
        with pytest.raises(ToolError):
            asyncio.run(mcp.call_tool(tool, args))
    if revocation == "membership":
        with pytest.raises(ToolError):
            asyncio.run(mcp.call_tool("project_create", {"project_id": "one/new", "display_name": "New"}))
    assert asyncio.run(mcp.call_tool("project_list", {}))[1]["projects"] == []
    assert snapshot(engine, visitor) == []
    with pytest.raises(ProjectNotFoundError):
        snapshot(engine, visitor, ["one/research"])
    with pytest.raises(ProjectNotFoundError):
        Projector(factory, tmp_path).project(visitor, "one/research")
    with factory() as session:
        assert len(list(session.scalars(select(ContextEvent)))) == 1


def test_namespace_projection_and_reader_do_not_collide(spaces, tmp_path):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    projector = Projector(factory, tmp_path, compatibility_workspace="")
    for ref in ("one/research", "two/research"):
        bind(service, owner, ref)
        record(service, owner, ref)
        root = tmp_path / ref
        (root / "HANDOFFS").mkdir(parents=True)
        (root / "STATUS.md").write_text("# Status\n")
        assert projector.project(owner, ref).project_id == ref
        content = (root / "STATUS.md").read_text()
        assert f"searchable {ref}" in content
        assert f"searchable {'two' if ref.startswith('one') else 'one'}/research" not in content
    pages = snapshot(engine, owner)
    assert [p["id"] for p in pages] == ["one/research", "two/research"]
    assert project_filename(pages[0]["id"]) != project_filename(pages[1]["id"])


def test_workspace_cli_membership_requires_owner_and_preserves_last_owner(spaces, tmp_path, monkeypatch):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    monkeypatch.setenv("DATABASE_URL", str(engine.url.render_as_string(hide_password=False)))
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", json.dumps({"owner-token": {"principal_id": str(owner.principal_id), "name": owner.name}, "visitor-token": {"principal_id": str(visitor.principal_id), "name": visitor.name}}))
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", "visitor-token")
    denied = cli("workspace", "member", "grant", "one", str(outsider.principal_id), cwd=tmp_path)
    assert denied.returncode == 2 and "workspace not found" in denied.stderr
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", "owner-token")
    created = cli("workspace", "create", "three", "--name", "Workspace Three", cwd=tmp_path)
    assert created.returncode == 0, created.stderr
    with pytest.raises(BindingNotFoundError):
        service.current_project(owner, "not-selected")
    granted = cli("workspace", "member", "grant", "one", str(outsider.principal_id), cwd=tmp_path)
    assert granted.returncode == 0, granted.stderr
    assert service.list_projects(outsider).projects == []
    for action in ("revoke", "grant"):
        result = cli("workspace", "member", action, "one", str(owner.principal_id), cwd=tmp_path)
        assert result.returncode == 2 and "last workspace owner" in result.stderr
    access = cli("access", "grant", "two/research", str(outsider.principal_id), "--role", "reader", cwd=tmp_path)
    assert access.returncode == 2 and "membership" in access.stderr


def test_concurrent_owner_removals_leave_one_owner(spaces):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    with factory.begin() as session:
        change_membership(session, "one", owner.principal_id, visitor.principal_id, "owner")
    def remove(target):
        try:
            with factory.begin() as session:
                return change_membership(session, "one", None, target, None, operator=True)
        except ValueError as exc:
            assert "last workspace owner" in str(exc)
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(remove, [owner.principal_id, visitor.principal_id])) == 1
    with factory() as session:
        assert len(list(session.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == one, WorkspaceMember.role == "owner")))) == 1


@pytest.mark.parametrize("revocation", ["membership", "project_acl"])
def test_revocation_waits_for_authorized_write_then_denies_next_call(spaces, monkeypatch, revocation):
    engine, factory, owner, visitor, outsider, service, one, two = spaces
    monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
    bind(service, visitor, "one/research")
    reached, release, revoking = Event(), Event(), Event()
    def hold(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO context_events"):
            reached.set()
            assert release.wait(10)
    event.listen(engine, "before_cursor_execute", hold)
    def revoke():
        revoking.set()
        if revocation == "membership":
            with factory.begin() as session:
                change_membership(session, "one", owner.principal_id, visitor.principal_id, None)
        else:
            from types import SimpleNamespace
            from contitext.admin import manage
            manage(SimpleNamespace(command="access", action="revoke", project_id="one/research", principal_id=visitor.principal_id))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(record, service, visitor, "one/research")
            assert reached.wait(5)
            revocation = pool.submit(revoke)
            assert revoking.wait(5)
            try:
                from concurrent.futures import TimeoutError
                with pytest.raises(TimeoutError):
                    revocation.result(timeout=0.2)
            finally:
                release.set()
            writing.result(timeout=10)
            revocation.result(timeout=10)
        with pytest.raises(ProjectNotFoundError):
            record(service, visitor, "one/research", "after-revocation")
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", hold)
