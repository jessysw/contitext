from __future__ import annotations

from workspace_fixtures import seed_members


from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text

from contitext.auth import PrincipalIdentity, ProjectNotFoundError
from contitext.db import create_session_factory
from contitext.repository import BindingNotFoundError, Repository
from contitext.schemas import BindProjectRequest
from contitext.service import ContextService


def seed_access(database_url: str) -> tuple[PrincipalIdentity, PrincipalIdentity]:
    engine = create_engine(database_url)
    first = PrincipalIdentity(uuid4(), "First")
    second = PrincipalIdentity(uuid4(), "Second")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO projects (slug, workspace_id, display_name, status)\n                VALUES ('alpha', '00000000-0000-4000-8000-000000000001', 'Alpha', 'active'), ('beta', '00000000-0000-4000-8000-000000000001', 'Beta', 'active')")
            )
            connection.execute(
                text("INSERT INTO principals (id, name) VALUES (:first, 'First'), (:second, 'Second')"),
                {"first": first.principal_id, "second": second.principal_id},
            )
            seed_members(connection)
            connection.execute(
                text("INSERT INTO project_acl (project_id, principal_id, role)\n                VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'), :first, 'reader'), ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='beta'), :first, 'writer'),\n                       ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='beta'), :second, 'reader')"),
                {"first": first.principal_id, "second": second.principal_id},
            )
    finally:
        engine.dispose()
    return first, second


def make_service(database_url: str) -> tuple[ContextService, Engine]:
    engine = create_engine(database_url, pool_pre_ping=True)
    service = ContextService(Repository(create_session_factory(engine)))
    return service, engine


def request(project: str, scope: str, session: str = "session:1") -> BindProjectRequest:
    return BindProjectRequest(project_id=project, scope_id=scope, session_id=session)


def test_bind_rebind_current_unbound_and_unauthorized(migrated_database_url: str) -> None:
    first, _ = seed_access(migrated_database_url)
    service, engine = make_service(migrated_database_url)
    try:
        bound = service.bind_project(first, request("alpha", "scope:1"))
        assert bound.project_id == "alpha"
        assert service.current_project(first, "scope:1").project_id == "alpha"

        rebound = service.bind_project(first, request("beta", "scope:1", "session:2"))
        assert rebound.project_id == "beta"
        assert rebound.session_id == "session:2"
        assert service.current_project(first, "scope:1").project_id == "beta"

        with pytest.raises(BindingNotFoundError, match="scope is not bound"):
            service.current_project(first, "unbound")
        with pytest.raises(ProjectNotFoundError, match="project not found"):
            service.bind_project(first, request("missing", "scope:2"))
    finally:
        engine.dispose()


def test_two_principals_can_use_the_same_scope_without_collision(
    migrated_database_url: str,
) -> None:
    first, second = seed_access(migrated_database_url)
    service, engine = make_service(migrated_database_url)
    try:
        service.bind_project(first, request("alpha", "shared"))
        service.bind_project(second, request("beta", "shared"))
        assert service.current_project(first, "shared").project_id == "alpha"
        assert service.current_project(second, "shared").project_id == "beta"
    finally:
        engine.dispose()


def test_repository_direct_call_cannot_bypass_acl(migrated_database_url: str) -> None:
    first, second = seed_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    repository = Repository(create_session_factory(engine))
    try:
        with pytest.raises(ProjectNotFoundError):
            repository.bind_project(second, request("alpha", "blocked"))
        repository.bind_project(first, request("alpha", "allowed"))
    finally:
        engine.dispose()


def test_concurrent_binds_to_distinct_scopes_preserve_all(
    migrated_database_url: str,
) -> None:
    first, _ = seed_access(migrated_database_url)
    service, engine = make_service(migrated_database_url)
    scopes = [f"parallel:{number}" for number in range(40)]
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(
                executor.map(
                    lambda scope: service.bind_project(first, request("alpha", scope)),
                    scopes,
                )
            )
        assert {item.scope_id for item in results} == set(scopes)
        assert {
            service.current_project(first, scope).scope_id for scope in scopes
        } == set(scopes)
    finally:
        engine.dispose()
