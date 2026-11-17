from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import create_engine, text

from contitext.api import create_app
from contitext.auth import PrincipalIdentity, TokenStore
from contitext.db import create_session_factory
from contitext.mcp_server import create_mcp_server
from contitext.projector import Projector
from contitext.repository import Repository
from contitext.service import ContextService


SOURCE_IDS = {
    "hermes": "hermes:session:acceptance",
    "openclaw": "openclaw:thread:acceptance",
    "codex": "codex:turn:acceptance",
    "claude-code": "claude-code:session:acceptance",
}


def _snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        data = path.read_bytes()
        result[str(path.relative_to(root))] = (
            hashlib.sha256(data).hexdigest(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
    return result


def _mcp_call(server, name: str, arguments: dict):
    _, structured = asyncio.run(server.call_tool(name, arguments))
    return structured


def _event(index: int) -> dict:
    source_kind, source_id = list(SOURCE_IDS.items())[index % len(SOURCE_IDS)]
    return {
        "project_id": "alpha",
        "scope_id": "acceptance-scope",
        "session_id": "acceptance-session",
        "agent_id": f"agent-{index % 8}",
        "source_kind": source_kind,
        "source_id": source_id,
        "event_kind": "decision" if index % 3 == 0 else "note",
        "payload": {"text": f"acceptance unique record {index}", "ordinal": index},
        "idempotency_key": f"acceptance-record-{index}",
    }


def _handoff(index: int) -> dict:
    source_kind, source_id = list(SOURCE_IDS.items())[index % len(SOURCE_IDS)]
    return {
        "project_id": "alpha",
        "scope_id": "acceptance-scope",
        "session_id": "acceptance-session",
        "agent_id": f"handoff-agent-{index % 4}",
        "source_kind": source_kind,
        "source_id": source_id,
        "summary": f"acceptance handoff {index}",
        "next_action": f"continue acceptance {index}",
        "completed": [f"record-{index}"],
        "current": ["acceptance"],
        "blockers": [],
        "idempotency_key": f"acceptance-handoff-{index}",
    }


def test_integrated_http_mcp_concurrency_restart_isolation_and_projection(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    owner = PrincipalIdentity(UUID("11111111-1111-4111-8111-111111111111"), "Acceptance Owner")
    outsider = PrincipalIdentity(UUID("22222222-2222-4222-8222-222222222222"), "Acceptance Outsider")
    engine = create_engine(migrated_database_url, pool_size=20, max_overflow=40)
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO projects (id, display_name, status) VALUES
              ('alpha', 'Alpha Acceptance', 'active'),
              ('beta', 'Beta Isolated', 'active')
        """))
        connection.execute(
            text("INSERT INTO principals (id, name) VALUES (:owner, :owner_name), (:outsider, :outsider_name)"),
            {
                "owner": owner.principal_id,
                "owner_name": owner.name,
                "outsider": outsider.principal_id,
                "outsider_name": outsider.name,
            },
        )
        connection.execute(
            text("""
                INSERT INTO project_acl (project_id, principal_id, role) VALUES
                  ('alpha', :owner, 'owner'),
                  ('beta', :outsider, 'owner')
            """),
            {"owner": owner.principal_id, "outsider": outsider.principal_id},
        )

    projects_root = tmp_path / "projects root [acceptance]"
    alpha_root = projects_root / "alpha"
    (alpha_root / "HANDOFFS").mkdir(parents=True)
    for name in ("NOTES.md", "DECISIONS.md", "OPEN-QUESTIONS.md", "STATUS.md"):
        (alpha_root / name).write_text(f"# {name}\n", encoding="utf-8")

    def build_stack():
        local_engine = create_engine(migrated_database_url, pool_size=20, max_overflow=40)
        factory = create_session_factory(local_engine)
        service = ContextService(Repository(factory), Projector(factory, projects_root))
        tokens = TokenStore.from_json(json.dumps({
            "owner-token": {"principal_id": str(owner.principal_id), "name": owner.name},
            "outsider-token": {"principal_id": str(outsider.principal_id), "name": outsider.name},
        }))
        return local_engine, service, TestClient(create_app(service=service, token_store=tokens)), create_mcp_server(service, owner)

    app_engine, service, http, mcp = build_stack()
    owner_headers = {"Authorization": "Bearer owner-token"}
    outsider_headers = {"Authorization": "Bearer outsider-token"}
    try:
        http_binding = http.put(
            "/v1/scopes/acceptance-scope/binding",
            headers=owner_headers,
            json={"project_id": "alpha", "session_id": "acceptance-session"},
        )
        assert http_binding.status_code == 200
        assert _mcp_call(mcp, "project_current", {"scope_id": "acceptance-scope"}) == http_binding.json()
        mcp_binding = _mcp_call(mcp, "project_bind", {
            "scope_id": "acceptance-scope",
            "project_id": "alpha",
            "session_id": "acceptance-session",
        })
        assert mcp_binding == http.get(
            "/v1/scopes/acceptance-scope/binding", headers=owner_headers
        ).json()

        def submit_record(index: int):
            body = _event(index)
            if index % 2:
                return "mcp", _mcp_call(mcp, "context_record", body)
            response = http.post(
                "/v1/projects/alpha/events",
                headers=owner_headers,
                json={key: value for key, value in body.items() if key != "project_id"},
            )
            assert response.status_code == 201
            return "http", response.json()

        def submit_handoff(index: int):
            body = _handoff(index)
            if index % 2:
                return "mcp", _mcp_call(mcp, "context_handoff", body)
            response = http.post(
                "/v1/projects/alpha/handoffs",
                headers=owner_headers,
                json={key: value for key, value in body.items() if key != "project_id"},
            )
            assert response.status_code == 201
            return "http", response.json()

        with ThreadPoolExecutor(max_workers=24) as pool:
            futures = [pool.submit(submit_record, index) for index in range(56)]
            futures += [pool.submit(submit_handoff, index) for index in range(16)]
            results = [future.result(timeout=60) for future in futures]

        returned_ids = [item[1]["event_id"] for item in results]
        assert len(returned_ids) == 72
        assert len(set(returned_ids)) == 72
        assert {item[0] for item in results} == {"http", "mcp"}

        # Cross-transport retries retain the original stable event IDs and payloads.
        first_record = _event(0)
        mcp_retry = _mcp_call(mcp, "context_record", first_record)
        assert mcp_retry["event_id"] == results[0][1]["event_id"]
        first_handoff = _handoff(0)
        http_retry = http.post(
            "/v1/projects/alpha/handoffs",
            headers=owner_headers,
            json={
                **{key: value for key, value in first_handoff.items() if key != "project_id"},
            },
        )
        assert http_retry.status_code == 201
        assert http_retry.json()["event_id"] == results[56][1]["event_id"]

        with engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT event_id::text, source_kind, source_id, event_kind
                FROM context_events WHERE project_id = 'alpha'
                ORDER BY idempotency_key
            """)).mappings().all()
        assert len(rows) == 72
        assert {row["event_id"] for row in rows} == set(returned_ids)
        assert {(row["source_kind"], row["source_id"]) for row in rows} == set(SOURCE_IDS.items())
        assert sum(row["event_kind"] == "handoff" for row in rows) == 16

        http_search = http.get(
            "/v1/projects/alpha/search",
            headers=owner_headers,
            params={"q": "acceptance", "limit": 100},
        )
        assert http_search.status_code == 200
        assert http_search.json()["total_count"] == 72
        mcp_search = _mcp_call(mcp, "context_search", {
            "project_id": "alpha", "query": "acceptance", "limit": 100
        })
        assert mcp_search == http_search.json()
        assert _mcp_call(mcp, "context_get", {"project_id": "alpha"}) == http.get(
            "/v1/projects/alpha/context", headers=owner_headers
        ).json()

        projection = http.post("/v1/projects/alpha/projection", headers=owner_headers)
        assert projection.status_code == 200
        assert len(projection.json()["projected_event_ids"]) == 72
        projected = _snapshot(alpha_root)
        assert "NOTES.md" in projected and "DECISIONS.md" in projected
        assert len([name for name in projected if name.startswith("HANDOFFS/")]) == 16
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in alpha_root.rglob("*.md"))
        for source_id in SOURCE_IDS.values():
            assert source_id in rendered
        rerun = http.post("/v1/projects/alpha/projection", headers=owner_headers)
        assert rerun.status_code == 200
        assert rerun.json()["projected_event_ids"] == []
        assert rerun.json()["files_changed"] == []
        assert _snapshot(alpha_root) == projected

        # Recreate all application state while preserving only PostgreSQL and projected files.
        http.close()
        app_engine.dispose()
        app_engine, service, http, mcp = build_stack()
        assert http.get("/health/ready").json() == {"status": "ready"}
        assert http.get(
            "/v1/scopes/acceptance-scope/binding", headers=owner_headers
        ).json()["project_id"] == "alpha"
        restarted_search = http.get(
            "/v1/projects/alpha/search",
            headers=owner_headers,
            params={"q": "acceptance", "limit": 100},
        ).json()
        assert restarted_search["total_count"] == 72
        restarted_context = _mcp_call(mcp, "context_get", {"project_id": "alpha"})
        assert restarted_context["latest_handoff"]["event_id"] in returned_ids

        # Every operation is non-enumerating across an unauthorized project.
        http_failures = []
        for method, path, kwargs in (
            ("put", "/v1/scopes/foreign/binding", {"json": {"project_id": "alpha", "session_id": "x"}}),
            ("get", "/v1/scopes/foreign/binding", {}),
            ("get", "/v1/projects/alpha/context", {}),
            ("get", "/v1/projects/alpha/search", {"params": {"q": "acceptance"}}),
            ("post", "/v1/projects/alpha/events", {"json": {key: value for key, value in _event(100).items() if key != "project_id"}}),
            ("post", "/v1/projects/alpha/handoffs", {"json": {key: value for key, value in _handoff(100).items() if key != "project_id"}}),
        ):
            response = getattr(http, method)(path, headers=outsider_headers, **kwargs)
            http_failures.append((response.status_code, response.json()))
        assert http_failures[0] == (404, {"detail": "project not found"})
        assert http_failures[1] == (404, {"detail": "scope is not bound"})
        assert all(item == (404, {"detail": "project not found"}) for item in http_failures[2:])

        denied_mcp = create_mcp_server(service, outsider)
        missing_mcp = create_mcp_server(service, outsider)
        mcp_cases = (
            ("project_bind", {"scope_id": "foreign", "project_id": "alpha", "session_id": "x"}, {"scope_id": "missing", "project_id": "missing", "session_id": "x"}),
            ("project_current", {"scope_id": "foreign"}, {"scope_id": "missing"}),
            ("context_get", {"project_id": "alpha"}, {"project_id": "missing"}),
            ("context_search", {"project_id": "alpha", "query": "acceptance"}, {"project_id": "missing", "query": "acceptance"}),
            ("context_record", _event(200), {**_event(201), "project_id": "missing"}),
            ("context_handoff", _handoff(200), {**_handoff(201), "project_id": "missing"}),
        )
        for name, unauthorized, absent in mcp_cases:
            messages = []
            for server, arguments in ((denied_mcp, unauthorized), (missing_mcp, absent)):
                with pytest.raises(ToolError) as caught:
                    _mcp_call(server, name, arguments)
                messages.append(str(caught.value))
            assert messages[0] == messages[1]

        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT count(*) FROM context_events WHERE project_id = 'alpha'"
            )).scalar_one() == 72
            assert connection.execute(text(
                "SELECT count(*) FROM context_events WHERE project_id = 'beta'"
            )).scalar_one() == 0
    finally:
        http.close()
        app_engine.dispose()
        engine.dispose()
