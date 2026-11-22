"""Read-only upgrade inventory and normalized integrity fingerprints."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from sqlalchemy import text

from contitext.db import create_database_engine, create_session_factory
from contitext.migrations import HEAD_REVISION
from contitext.namespaces import configured_workspace, validate_slug

FORMAT = "contitext-upgrade-snapshot-v1"
TABLES = ("projects", "principals", "project_acl", "scope_bindings", "context_events",
          "projection_offsets", "credentials", "credential_audit")
CHECKS = (*TABLES, "effective_project_access", "project_creation_access")
SUPPORTED = {"0001_foundation", "0002_credentials", "0003_workspaces", HEAD_REVISION}


def _fingerprint(rows):
    # Keep only row digests in memory, never every event payload. Sorting makes
    # results independent of database collation and physical scan order.
    digests = sorted(hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                              ensure_ascii=True).encode()).hexdigest() for row in rows)
    return {"count": len(digests), "sha256": hashlib.sha256("\n".join(digests).encode()).hexdigest()}


def inspect_upgrade(database_url: str) -> dict:
    engine = create_database_engine(database_url)
    try:
        with create_session_factory(engine)() as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            tables = set(session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")))
            revision = session.scalar(text("SELECT version_num FROM alembic_version")) if "alembic_version" in tables else None
            report = {"format": FORMAT, "schema": revision, "target_schema": HEAD_REVISION,
                      "ok": False, "errors": [], "notes": [], "tables": {}, "projects": []}
            if revision not in SUPPORTED:
                report["errors"].append("unsupported or uninitialized schema; use a fresh database for initialization or the matching release's upgrade procedure")
                return report
            namespaced = revision in {"0003_workspaces", HEAD_REVISION}
            workspaces = dict(session.execute(text("SELECT id::text, slug FROM workspaces")).all()) if namespaced else {}
            project_rows = list(session.scalars(text("SELECT row_to_json(p) FROM projects p")))
            references = {str(p["id"]): f"{workspaces[str(p['workspace_id'])]}/{p['slug']}" if namespaced else f"legacy/{p['id']}" for p in project_rows}
            invalid = []
            for p in project_rows:
                try:
                    validate_slug(p["slug"] if namespaced else p["id"])
                except ValueError:
                    invalid.append(p["slug"] if namespaced else p["id"])
                report["projects"].append({"reference": references[str(p["id"])], "uuid": p["id"] if namespaced else None})
            report["projects"].sort(key=lambda p: p["reference"])
            if invalid:
                report["errors"].append("historical project IDs cannot be represented as valid slugs; resolve before migrating")
                report["invalid_project_ids"] = {"count": len(invalid), "sample": sorted(invalid)[:20]}

            memberships = set(session.execute(text("SELECT workspace_id::text, principal_id::text FROM workspace_members")).all()) if namespaced else set()
            project_workspaces = {str(p["id"]): str(p["workspace_id"]) for p in project_rows} if namespaced else {}

            def normalized_rows(table):
                if table not in tables:
                    return
                result = session.execute(text(f"SELECT row_to_json(t) FROM {table} t").execution_options(yield_per=1000))
                for (row,) in result:
                    if table == "projects":
                        row["id"] = references[str(row["id"])]
                        row.pop("slug", None)
                        row.pop("workspace_id", None)
                    elif "project_id" in row:
                        row["project_id"] = references[str(row["project_id"])]
                    if table == "context_events" and row.get("event_metadata") is None:
                        row.pop("event_metadata", None)
                    yield row

            report["tables"] = {table: _fingerprint(normalized_rows(table)) for table in TABLES}
            grants = list(session.scalars(text("SELECT row_to_json(a) FROM project_acl a")))
            effective = []
            for grant in grants:
                project_id = str(grant["project_id"])
                if not namespaced or (project_workspaces[project_id], str(grant["principal_id"])) in memberships:
                    effective.append({**grant, "project_id": references[project_id]})
            report["tables"]["effective_project_access"] = _fingerprint(effective)
            creators = ([{"workspace": workspaces[w], "principal_id": p} for w, p in memberships] if namespaced else
                        [{"workspace": "legacy", "principal_id": str(p)} for p in session.scalars(text("SELECT id FROM principals"))])
            report["tables"]["project_creation_access"] = _fingerprint(creators)
            report["compatibility_workspace"] = configured_workspace()
            if not namespaced or any(p["reference"].startswith("legacy/") for p in report["projects"]):
                report["notes"].append("retain CONTITEXT_COMPATIBILITY_WORKSPACE=legacy in each upgraded process to preserve bare-ID clients; this never selects a conversation project")
            report["notes"].append("this read-only check is not a backup or writer fence; stop every writer and verify recovery before live migration")
            report["ok"] = not report["errors"]
            return report
    finally:
        engine.dispose()


def compare_snapshot(report: dict, path: Path) -> None:
    try:
        baseline = json.loads(path.read_text())
        valid = baseline.get("format") == FORMAT and set(baseline["tables"]) == set(CHECKS)
        for item in baseline["tables"].values():
            valid = valid and type(item["count"]) is int and item["count"] >= 0 and bool(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]))
        if not valid:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("invalid upgrade snapshot") from None
    differences = [name for name in CHECKS if baseline["tables"][name] != report["tables"].get(name)]
    report["comparison"] = {"matches": not differences, "different": differences}
    if differences:
        report["ok"] = False
        report["errors"].append("integrity comparison differs; do not cut over until every difference is explained")


def write_snapshot(report: dict, path: Path) -> None:
    if not report["ok"]:
        raise ValueError("cannot save a failed upgrade check as a baseline")
    # This is an explicitly requested local artifact, never a credential or dump.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
