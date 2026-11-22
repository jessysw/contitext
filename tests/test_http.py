from __future__ import annotations

from workspace_fixtures import seed_members


import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, TokenStore
from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.service import ContextService


def setup(database_url: str):
    engine = create_engine(database_url)
    principal = PrincipalIdentity(uuid4(), "HTTP Writer")
    denied = PrincipalIdentity(uuid4(), "Denied")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO projects (slug, workspace_id,display_name,status) VALUES ('alpha', '00000000-0000-4000-8000-000000000001','Alpha','active'),('beta', '00000000-0000-4000-8000-000000000001','Beta','active')"))
        connection.execute(text("INSERT INTO principals (id,name) VALUES (:id,'HTTP Writer'),(:denied,'Denied')"), {"id": principal.principal_id, "denied": denied.principal_id})
        seed_members(connection)
        connection.execute(text("INSERT INTO project_acl (project_id,principal_id,role) VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'),:id,'owner')"), {"id": principal.principal_id})
    token_store = TokenStore.from_json(json.dumps({
        "valid-token": {"principal_id": str(principal.principal_id), "name": principal.name},
        "denied-token": {"principal_id": str(denied.principal_id), "name": denied.name},
    }))
    service = ContextService(Repository(create_session_factory(engine)))
    return engine, TestClient(create_app(service=service, token_store=token_store))


def auth(token="valid-token"):
    return {"Authorization": f"Bearer {token}"}


def event_body(key="event-1"):
    return {
        "scope_id": "scope", "session_id": "session", "agent_id": "agent",
        "source_kind": "hermes", "source_id": "source:1", "event_kind": "note",
        "payload": {"text": "searchable phrase"}, "idempotency_key": key,
    }


def handoff_body(key="handoff-1"):
    return {
        "scope_id": "scope", "session_id": "session", "agent_id": "agent",
        "source_kind": "hermes", "source_id": "source:h", "summary": "summary",
        "next_action": "searchable next", "idempotency_key": key,
    }


def test_all_http_routes_and_idempotency(migrated_database_url: str) -> None:
    engine, client = setup(migrated_database_url)
    try:
        assert client.get("/health/live").json() == {"status": "live"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        bound = client.put("/v1/scopes/scope/binding", headers=auth(), json={"project_id": "alpha", "session_id": "session"})
        assert bound.status_code == 200 and bound.json()["project_id"] == "alpha"
        assert client.get("/v1/scopes/scope/binding", headers=auth()).json()["project_id"] == "alpha"
        first = client.post("/v1/projects/alpha/events", headers=auth(), json=event_body())
        retry = client.post("/v1/projects/alpha/events", headers=auth(), json=event_body())
        assert first.status_code == 201 and retry.json()["event_id"] == first.json()["event_id"]
        conflict = client.post("/v1/projects/alpha/events", headers=auth(), json={**event_body(), "payload": {"text": "changed"}})
        assert conflict.status_code == 409
        handoff = client.post("/v1/projects/alpha/handoffs", headers=auth(), json=handoff_body())
        assert handoff.status_code == 201 and handoff.json()["event_kind"] == "handoff"
        changed_handoff = client.post("/v1/projects/alpha/handoffs", headers=auth(), json={**handoff_body(), "summary": "different"})
        assert changed_handoff.status_code == 409
        context = client.get("/v1/projects/alpha/context", headers=auth()).json()
        assert context["latest_handoff"]["event_id"] == handoff.json()["event_id"]
        search = client.get("/v1/projects/alpha/search", headers=auth(), params={"q": "searchable"}).json()
        assert search["total_count"] == 2
        assert client.post("/v1/projects/alpha/projection", headers=auth()).status_code == 503
    finally:
        engine.dispose()


def test_auth_acl_validation_request_ids_and_safe_logs(migrated_database_url: str, caplog) -> None:
    engine, client = setup(migrated_database_url)
    try:
        assert client.get("/v1/projects/alpha/context").status_code == 401
        assert client.get("/v1/projects/alpha/context", headers=auth("bad")).status_code == 401
        denied = client.get("/v1/projects/alpha/context", headers=auth("denied-token"))
        missing = client.get("/v1/projects/missing/context", headers=auth("denied-token"))
        assert (denied.status_code, denied.json()) == (missing.status_code, missing.json()) == (404, {"detail": "project not found"})
        malformed = client.post("/v1/projects/alpha/events", headers=auth(), json={**event_body(), "source_id": ""})
        assert malformed.status_code == 422
        generic_handoff = client.post(
            "/v1/projects/alpha/events",
            headers=auth(),
            json={**event_body("generic-handoff"), "event_kind": "handoff"},
        )
        assert generic_handoff.status_code == 422
        with caplog.at_level(logging.INFO, logger="contitext.http"):
            response = client.get("/health/live", headers={"x-request-id": "request-123", "Authorization": "Bearer secret-never-log"})
        assert response.headers["x-request-id"] == "request-123"
        logs = caplog.text
        assert "secret-never-log" not in logs and "searchable phrase" not in logs
    finally:
        engine.dispose()


def test_readiness_fails_closed_without_database_and_openapi_is_exact(migrated_database_url: str) -> None:
    engine, client = setup(migrated_database_url)
    try:
        engine.dispose()
        # Break new connections after disposal.
        service = client.app.state.service
        service._repository._session_factory.configure(bind=create_engine("postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid", connect_args={"connect_timeout": 1}))
        assert client.get("/health/ready").status_code == 503
        paths = set(client.get("/openapi.json").json()["paths"])
        assert paths == {
            "/v1/scopes/{scope_id}/binding", "/v1/projects/{project_id}/context",
            "/v1/projects/{project_id}/search", "/v1/projects/{project_id}/events",
            "/v1/projects/{project_id}/handoffs", "/v1/projects/{project_id}/projection",
            "/health/live", "/health/ready", "/v1/projects",
        }
    finally:
        engine.dispose()
