"""Initialization and actual legacy-schema upgrade integrity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from dotenv import dotenv_values
import pytest
from sqlalchemy import create_engine, text

from contitext.auth import PrincipalIdentity
from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.schemas import CreateProjectRequest
from contitext.upgrade import compare_snapshot, inspect_upgrade, write_snapshot
from test_cli import cli
from test_migrations import alembic_config, reset_schema


def seed_legacy(database_url):
    """Seed the unchanged foundation schema shipped by the v0.7.1 tag."""
    engine = create_engine(database_url)
    owner, reader, other, unassigned = [uuid4() for _ in range(4)]
    with engine.begin() as c:
        c.execute(text("INSERT INTO projects (id,display_name,status) VALUES ('alpha','Alpha','active'),('beta','Beta','paused')"))
        for principal, name in [(owner, "Owner"), (reader, "Reader"), (other, "Other"), (unassigned, "Unassigned")]:
            c.execute(text("INSERT INTO principals (id,name) VALUES (:id,:name)"), {"id": principal, "name": name})
        c.execute(text("INSERT INTO project_acl VALUES ('alpha',:owner,'owner'),('alpha',:reader,'reader'),('beta',:other,'owner')"), {"owner": owner, "reader": reader, "other": other})
        for project, principal in [("alpha", owner), ("beta", other)]:
            c.execute(text("INSERT INTO scope_bindings (principal_id,scope_id,project_id,session_id) VALUES (:principal,'shared-scope',:project,'old-session')"), {"principal": principal, "project": project})
            for index, kind in enumerate(("note", "decision", "question", "checkpoint", "handoff")):
                event_id = uuid4()
                c.execute(text("""INSERT INTO context_events
                    (event_id,project_id,principal_id,scope_id,session_id,agent_id,source_kind,source_id,event_kind,payload,idempotency_key)
                    VALUES (:id,:project,:principal,'shared-scope','old-session','original-agent','fixture',:source,:kind,CAST(:payload AS jsonb),:key)"""),
                    {"id": event_id, "project": project, "principal": principal, "source": f"source:{project}/{index}", "kind": kind,
                     "payload": json.dumps({"summary": f"Original {project} {kind}", "next_action": "Resume", "nested": {"unicode": "Å", "number": index}}), "key": f"shared-key-{index}"})
            c.execute(text("INSERT INTO projection_offsets (project_id,last_event_id) VALUES (:project,:event)"), {"project": project, "event": event_id})
    engine.dispose()
    return owner, reader, other, unassigned


@pytest.mark.parametrize("revision", ["0001_foundation", "0002_credentials"])
def test_legacy_integrity_access_and_old_binding_survive(test_database_url, postgres_available, monkeypatch, tmp_path, revision):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    config = alembic_config()
    command.upgrade(config, revision)
    # Verified from v0.7.1 commit 5d00ef0b8a54ae12b217efbe8016893bb3e4896b.
    migration = Path(__file__).parents[1] / "src/contitext/migrations/versions/0001_foundation.py"
    assert hashlib.sha256(migration.read_bytes()).hexdigest() == "7453a1ce087dfb1dda46e9557cea05990f963da4a544ff52f5718bc404fcb542"
    owner, reader, other, unassigned = seed_legacy(test_database_url)
    token = None
    if revision == "0002_credentials":
        from contitext.credentials import issue
        engine = create_engine(test_database_url)
        with create_session_factory(engine).begin() as session:
            _, token = issue(session, owner, "Pre-workspace agent")
        engine.dispose()
    before = inspect_upgrade(test_database_url)
    if token:
        assert token not in json.dumps(before)
        assert before["tables"]["credentials"]["count"] == 1
    assert before["ok"] and before["tables"]["context_events"]["count"] == 10
    baseline = tmp_path / "before.json"
    write_snapshot(before, baseline)
    assert baseline.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_snapshot(before, baseline)
    command.upgrade(config, "head")
    after = inspect_upgrade(test_database_url)
    compare_snapshot(after, baseline)
    assert after["ok"] and after["comparison"]["matches"]
    assert before["tables"] == after["tables"]
    engine = create_engine(test_database_url)
    repository = Repository(create_session_factory(engine), compatibility_workspace="legacy")
    try:
        assert repository.current_project(PrincipalIdentity(owner, "Owner"), "shared-scope").project_id == "alpha"
        assert repository.current_project(PrincipalIdentity(other, "Other"), "shared-scope").project_id == "beta"
        assert repository.get_context(PrincipalIdentity(reader, "Reader"), "alpha").latest_handoff.payload["next_action"] == "Resume"
        with engine.begin() as c:
            c.execute(text("UPDATE context_events SET payload=payload || CAST(:patch AS jsonb) WHERE event_id=(SELECT event_id FROM context_events LIMIT 1)"), {"patch": json.dumps({"unexpected": True})})
        tampered = inspect_upgrade(test_database_url)
        compare_snapshot(tampered, baseline)
        assert tampered["comparison"]["different"] == ["context_events"]
        # A previously provisioned principal could create projects without prior ACLs.
        repository.create_project(PrincipalIdentity(unassigned, "Unassigned"), CreateProjectRequest(project_id="new", display_name="New"))
        changed = inspect_upgrade(test_database_url)
        compare_snapshot(changed, baseline)
        assert not changed["ok"] and "projects" in changed["comparison"]["different"]
    finally:
        engine.dispose()


def test_snapshot_rejects_incomplete_or_malformed_baselines(migrated_database_url, tmp_path):
    # Empty namespace schema is a valid baseline; snapshot validation fails closed.
    before = inspect_upgrade(migrated_database_url)
    path = tmp_path / "baseline.json"
    write_snapshot(before, path)
    for bad in ({}, {"format": before["format"], "tables": {}}, []):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="invalid upgrade snapshot"):
            compare_snapshot(before, path)


def test_preflight_rejects_invalid_historical_ids_without_writing(test_database_url, postgres_available, monkeypatch):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    reset_schema(test_database_url)
    command.upgrade(alembic_config(), "0001_foundation")
    engine = create_engine(test_database_url)
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO projects (id,display_name,status) VALUES ('bad/old/id','Keep','active')"))
        result = inspect_upgrade(test_database_url)
        assert not result["ok"] and result["invalid_project_ids"]["count"] == 1
        with engine.connect() as c:
            assert c.execute(text("SELECT id FROM projects")).scalar_one() == "bad/old/id"
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_foundation"
    finally:
        engine.dispose()


@pytest.mark.parametrize("workspace", ["personal", "team"])
def test_new_install_has_one_owned_workspace_and_no_binding(migrated_database_url, monkeypatch, tmp_path, workspace):
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    config = tmp_path / "new.env"
    args = [] if workspace == "personal" else ["--workspace", workspace, "--workspace-name", "Team workspace"]
    result = cli("init", *args, "--project", "research", "--output", str(config), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    values = dotenv_values(config, interpolate=False)
    assert values["CONTITEXT_COMPATIBILITY_WORKSPACE"] == workspace
    seeded = cli("--env-file", str(config), "admin", "seed", "--if-empty", cwd=tmp_path)
    assert seeded.returncode == 0, seeded.stderr
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT slug FROM workspaces")).scalars().all() == [workspace]
            assert c.execute(text("SELECT role FROM workspace_members")).scalar_one() == "owner"
            assert c.execute(text("SELECT count(*) FROM scope_bindings")).scalar_one() == 0
            assert c.execute(text("SELECT count(*) FROM context_events")).scalar_one() == 0
        path = tmp_path / "inventory.json"
        report = cli("--env-file", str(config), "upgrade-check", "--snapshot", str(path), cwd=tmp_path)
        assert report.returncode == 0, report.stderr
        assert values["CONTITEXT_MCP_TOKEN"] not in path.read_text() + report.stdout + report.stderr
        checked = cli("--env-file", str(config), "upgrade-check", "--compare", str(path), cwd=tmp_path)
        assert checked.returncode == 0 and json.loads(checked.stdout)["comparison"]["matches"]
        # Re-running bootstrap cannot restore revoked project grants.
        with engine.begin() as c:
            c.execute(text("DELETE FROM project_acl"))
        assert cli("--env-file", str(config), "admin", "seed", "--if-empty", cwd=tmp_path).returncode == 0
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM project_acl")).scalar_one() == 0
        mismatch = cli("--env-file", str(config), "upgrade-check", "--compare", str(path), cwd=tmp_path)
        assert mismatch.returncode == 1
        assert "effective_project_access" in json.loads(mismatch.stdout)["comparison"]["different"]
    finally:
        engine.dispose()
