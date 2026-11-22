"""Read-only checks and portable MCP client configuration."""
from __future__ import annotations

import os
from pathlib import Path
import shlex

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from contitext.auth import AuthenticationError
from contitext.config import ConfigurationError, Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.models import Principal, Workspace, WorkspaceMember
from contitext.migrations import HEAD_REVISION


def doctor() -> dict:
    checks = []

    def check(name, passed, detail):
        checks.append({"check": name, "ok": passed, "detail": detail})

    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        return {"ok": False, "checks": [{"check": "configuration", "ok": False, "detail": str(exc)}]}
    check("configuration", True, "PostgreSQL and token store configured")
    engine = create_database_engine(settings.database_url)
    try:
        with create_session_factory(engine)() as session:
            version = int(session.execute(text("SHOW server_version_num")).scalar_one())
            check("postgresql", version >= 160000, "PostgreSQL 16 or newer is required")
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            check("schema", revision == HEAD_REVISION, "Expected schema: " + HEAD_REVISION)
            if revision != HEAD_REVISION:
                check("upgrade", False, "Back up and rehearse the upgrade before running contitext migrate; see docs/upgrading-to-0.8.md")
                return {"ok": False, "checks": checks}
            try:
                identity = settings.credential_resolver(create_session_factory(engine)).resolve(os.environ.get("CONTITEXT_MCP_TOKEN", ""))
                exists = session.get(Principal, identity.principal_id) is not None
                check("mcp_identity", exists, "Configured MCP credential must refer to a provisioned principal")
                if not exists:
                    return {"ok": False, "checks": checks}
                memberships = session.execute(select(Workspace.slug, WorkspaceMember.role).join(
                    WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id,
                ).where(WorkspaceMember.principal_id == identity.principal_id).order_by(Workspace.slug)).all()
                check("workspace_membership", bool(memberships),
                      [{"workspace": slug, "role": role} for slug, role in memberships] or
                      "Ask a workspace owner to grant membership to this principal")
                compatibility = os.environ.get("CONTITEXT_COMPATIBILITY_WORKSPACE", "").strip()
                check("project_resolution", not compatibility or any(slug == compatibility for slug, _ in memberships),
                      "Use workspace/project; no short-ID alias configured" if not compatibility else
                      "Short IDs require membership in the configured compatibility workspace; qualified references remain available")
                from contitext.repository import Repository
                grants = Repository(create_session_factory(engine)).list_projects(identity).projects
                check("project_access", bool(grants), [{"project_id": p.project_id, "role": p.role.value} for p in grants] or
                      "Membership alone grants no project access. Ask for a project ACL or create your own project in an accessible workspace")
            except AuthenticationError:
                check("mcp_identity", False, "Set CONTITEXT_MCP_TOKEN to a valid, unexpired, non-revoked credential in the selected authentication mode")
    except SQLAlchemyError:
        check("database", False, "Cannot check database; verify connectivity and run contitext migrate")
    finally:
        engine.dispose()
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def client_config(args) -> dict:
    credential_file = getattr(args, "credential_file", None)
    if credential_file and not Path(credential_file).is_absolute():
        raise ValueError("--credential-file must be an absolute path on the server")
    if args.compose:
        directory = Path(args.compose)
        if not directory.is_absolute():
            raise ValueError("--compose must be an absolute directory on the server")
        command = ["docker", "compose", "--project-directory", str(directory), "--env-file", str(directory / ".env"), "-f", str(directory / "compose.yaml"), "run", "--rm", "--no-deps", "-T"]
        if credential_file:
            command += ["--env-from-file", credential_file]
        command += ["app", "contitext", "mcp"]
        if getattr(args, "compose_project", None):
            command[2:2] = ["--project-name", args.compose_project]
    else:
        if getattr(args, "compose_project", None):
            raise ValueError("--compose-project requires --compose")
        if not args.config_file or not Path(args.config_file).is_absolute():
            raise ValueError("provide an absolute --config-file path on the server")
        command = [args.executable, "--env-file", args.config_file]
        if credential_file:
            command += ["--env-file", credential_file]
        command += ["mcp"]
    if args.ssh:
        if args.ssh.startswith("-") or any(char.isspace() for char in args.ssh):
            raise ValueError("--ssh must be a host alias or user@host without whitespace")
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", args.ssh, shlex.join(command)]
    return {"mcpServers": {"contitext": {"command": command[0], "args": command[1:]}}}
