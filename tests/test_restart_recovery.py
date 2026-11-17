from __future__ import annotations

from sqlalchemy import create_engine

from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.schemas import BindProjectRequest
from contitext.service import ContextService
from test_bindings import seed_access


def test_binding_survives_engine_recreation(migrated_database_url: str) -> None:
    principal, _ = seed_access(migrated_database_url)
    first_engine = create_engine(migrated_database_url)
    first_service = ContextService(Repository(create_session_factory(first_engine)))
    first_service.bind_project(
        principal,
        BindProjectRequest(project_id="alpha", scope_id="restart:1", session_id="session:restart"),
    )
    first_engine.dispose()

    second_engine = create_engine(migrated_database_url)
    try:
        second_service = ContextService(Repository(create_session_factory(second_engine)))
        recovered = second_service.current_project(principal, "restart:1")
        assert recovered.project_id == "alpha"
        assert recovered.session_id == "session:restart"
    finally:
        second_engine.dispose()
