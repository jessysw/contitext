"""Project discovery and self-owned creation through the real service boundaries."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text

from contitext.api import create_app
from contitext.auth import AuthenticationError, PrincipalIdentity, TokenStore
from contitext.db import create_session_factory
from contitext.mcp_server import create_mcp_server
from contitext.repository import BindingNotFoundError, ProjectCreationConflictError, Repository
from contitext.schemas import BindProjectRequest, CreateProjectRequest
from contitext.service import ContextService, WriterFencedError
from test_cli import cli


def setup(url, **options):
    engine = create_engine(url)
    caller = PrincipalIdentity(uuid4(), 'Caller')
    other = PrincipalIdentity(uuid4(), 'Other')
    with engine.begin() as c:
        c.execute(text('INSERT INTO principals (id,name) VALUES (:a,:an),(:b,:bn)'),
                  dict(a=caller.principal_id, an=caller.name, b=other.principal_id, bn=other.name))
    return engine, caller, other, ContextService(Repository(create_session_factory(engine)), **options)


def test_discovery_is_authorized_paginated_and_does_not_bind(migrated_database_url):
    engine, caller, other, service = setup(migrated_database_url)
    try:
        assert service.list_projects(caller).projects == []
        for p in ['alpha', 'zulu', 'middle']:
            service.create_project(caller, CreateProjectRequest(project_id=p, display_name=p.title()))
        service.create_project(other, CreateProjectRequest(project_id='hidden', display_name='Private'))
        with engine.begin() as c:
            c.execute(text("UPDATE projects SET status='inactive' WHERE id='middle'"))
            c.execute(text("UPDATE project_acl SET role='reader' WHERE project_id='middle'"))
        first = service.list_projects(caller, limit=2)
        assert [p.project_id for p in first.projects] == ['alpha', 'middle']
        assert first.projects[1].status == 'inactive' and first.projects[1].role == 'reader'
        assert first.next_cursor
        second = service.list_projects(caller, limit=2, cursor=first.next_cursor)
        assert [p.project_id for p in second.projects] == ['zulu'] and second.next_cursor is None
        for cursor in ['%', 'bnVsbA', 'W10', 'IiI']:
            with pytest.raises(ValueError, match='cursor'):
                service.list_projects(caller, cursor=cursor)
        with pytest.raises(ValueError, match='limit'):
            service.list_projects(caller, limit=101)
        with pytest.raises(BindingNotFoundError):
            service.current_project(caller, 'new-conversation')
        with engine.begin() as c:
            c.execute(text("DELETE FROM project_acl WHERE project_id='alpha'"))
        assert [p.project_id for p in service.list_projects(caller).projects] == ['middle', 'zulu']
    finally:
        engine.dispose()


def test_creation_cannot_overwrite_or_rebind_and_duplicate_errors_do_not_enumerate(migrated_database_url):
    engine, caller, other, service = setup(migrated_database_url)
    try:
        service.create_project(caller, CreateProjectRequest(project_id='first', display_name='First'))
        service.bind_project(caller, BindProjectRequest(project_id='first', scope_id='scope', session_id='session'))
        result = service.create_project(caller, CreateProjectRequest(project_id='second', display_name='Second'))
        assert result.role == 'owner' and result.status == 'active'
        assert service.current_project(caller, 'scope').project_id == 'first'
        service.create_project(other, CreateProjectRequest(project_id='private', display_name='Secret name'))
        errors = []
        for project in ['second', 'private']:
            with pytest.raises(ProjectCreationConflictError) as error:
                service.create_project(caller, CreateProjectRequest(project_id=project, display_name='Replacement'))
            errors.append(str(error.value))
        assert errors[0] == errors[1] == 'project ID is unavailable'
        with engine.connect() as c:
            assert c.execute(text("SELECT display_name FROM projects WHERE id='second'")).scalar_one() == 'Second'
            assert c.execute(text("SELECT principal_id FROM project_acl WHERE project_id='second'")).scalar_one() == caller.principal_id
            assert c.execute(text('SELECT count(*) FROM context_events')).scalar_one() == 0
    finally:
        engine.dispose()


def test_create_is_atomic_when_owner_grant_fails(migrated_database_url):
    engine, caller, _, service = setup(migrated_database_url)
    def fail_grant(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO project_acl'):
            raise RuntimeError('simulated grant failure')
    event.listen(engine, 'before_cursor_execute', fail_grant)
    try:
        with pytest.raises(RuntimeError, match='grant failure'):
            service.create_project(caller, CreateProjectRequest(project_id='atomic', display_name='Atomic'))
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM projects WHERE id='atomic'")).scalar_one() == 0
    finally:
        event.remove(engine, 'before_cursor_execute', fail_grant)
        engine.dispose()


def test_concurrent_creation_has_exactly_one_owner(migrated_database_url):
    engine, caller, other, service = setup(migrated_database_url)
    def create(identity):
        try:
            service.create_project(identity, CreateProjectRequest(project_id='race', display_name=identity.name))
            return identity.principal_id
        except ProjectCreationConflictError:
            return None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = [v for v in pool.map(create, [caller, other]) if v]
        assert len(winners) == 1
        with engine.connect() as c:
            assert c.execute(text("SELECT principal_id FROM project_acl WHERE project_id='race'")).scalars().all() == winners
    finally:
        engine.dispose()


def test_creation_validates_identity_input_and_writer_fence(migrated_database_url, tmp_path):
    fence = tmp_path/'fence'
    engine, caller, _, service = setup(migrated_database_url, writer_fence_file=fence)
    request = CreateProjectRequest(project_id='new', display_name='New')
    try:
        with pytest.raises(AuthenticationError, match='not provisioned'):
            service.create_project(PrincipalIdentity(uuid4(), 'Unknown'), request)
        for project_id, name in [('../bad', 'Bad'), ('bad space', 'Bad'), ('safe', '   ')]:
            with pytest.raises(ValidationError):
                service.create_project(caller, CreateProjectRequest.model_construct(project_id=project_id, display_name=name))
        with pytest.raises(ValidationError):
            CreateProjectRequest(project_id='safe', display_name='Safe', owner=str(caller.principal_id))
        fence.touch()
        with pytest.raises(WriterFencedError):
            service.create_project(caller, request)
        assert service.list_projects(caller).projects == []
        with engine.connect() as c:
            assert c.execute(text('SELECT count(*) FROM projects')).scalar_one() == 0
    finally:
        engine.dispose()


def test_http_and_mcp_project_management_have_identical_identity_rules(migrated_database_url):
    engine, caller, other, service = setup(migrated_database_url)
    tokens = TokenStore.from_json(json.dumps({'caller': {'principal_id': str(caller.principal_id), 'name': caller.name}}))
    client = TestClient(create_app(service=service, token_store=tokens))
    headers = {'Authorization': 'Bearer caller'}
    server = create_mcp_server(service, caller)
    try:
        assert client.get('/v1/projects').status_code == 401
        assert client.post('/v1/projects', json={'project_id': 'x', 'display_name': 'X'}).status_code == 401
        created = client.post('/v1/projects', headers=headers, json={'project_id': 'first', 'display_name': 'First'})
        assert created.status_code == 201 and created.json()['role'] == 'owner'
        _, mcp_created = asyncio.run(server.call_tool('project_create', {'project_id': 'second', 'display_name': 'Second'}))
        assert mcp_created['role'] == 'owner'
        _, listed = asyncio.run(server.call_tool('project_list', {}))
        assert client.get('/v1/projects', headers=headers).json() == listed
        assert [p['project_id'] for p in listed['projects']] == ['first', 'second']
        assert client.post('/v1/projects', headers=headers, json={'project_id': 'third', 'display_name': 'Third', 'owner': str(other.principal_id)}).status_code == 422
        assert client.post('/v1/projects', headers=headers, json={'project_id': 'first', 'display_name': 'Overwrite'}).status_code == 409
        with pytest.raises(ToolError, match='unavailable'):
            asyncio.run(server.call_tool('project_create', {'project_id': 'second', 'display_name': 'Overwrite'}))
    finally:
        engine.dispose()


def test_cli_create_defaults_to_authenticated_identity(migrated_database_url, monkeypatch, tmp_path):
    engine, caller, other, service = setup(migrated_database_url)
    monkeypatch.setenv('DATABASE_URL', migrated_database_url)
    monkeypatch.setenv('CONTITEXT_AUTH_TOKENS', json.dumps({'test-token': {'principal_id': str(caller.principal_id), 'name': caller.name}}))
    monkeypatch.setenv('CONTITEXT_MCP_TOKEN', 'test-token')
    try:
        result = cli('project', 'create', 'automatic', '--name', 'Automatic owner', cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['owner'] == str(caller.principal_id)
        assert service.list_projects(caller).projects[0].project_id == 'automatic'
        monkeypatch.delenv('CONTITEXT_MCP_TOKEN')
        result = cli('project', 'create', 'missing-token', '--name', 'Must fail', cwd=tmp_path)
        assert result.returncode == 2 and 'Traceback' not in result.stderr
        assert service.list_projects(other).projects == []
        result = cli('project', 'create', 'explicit', '--name', 'Explicit owner', '--owner', str(other.principal_id), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert service.list_projects(other).projects[0].project_id == 'explicit'
    finally:
        engine.dispose()
