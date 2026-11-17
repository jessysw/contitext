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
from contitext.models import Principal, ProjectACL


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
            check("schema", revision == "0001_foundation", "Expected foundation schema")
            try:
                identity = settings.token_store.resolve(os.environ.get("CONTITEXT_MCP_TOKEN", ""))
                exists = session.get(Principal, identity.principal_id) is not None
                check("mcp_identity", exists, "Configured MCP credential must refer to a provisioned principal")
                grants = list(session.execute(select(ProjectACL.project_id, ProjectACL.role).where(ProjectACL.principal_id == identity.principal_id).order_by(ProjectACL.project_id)))
                check("project_access", bool(grants), [{"project_id": p, "role": r} for p, r in grants])
            except AuthenticationError:
                check("mcp_identity", False, "Set CONTITEXT_MCP_TOKEN to a credential in the configured token store")
    except SQLAlchemyError:
        check("database", False, "Cannot check database; verify connectivity and run contitext migrate")
    finally:
        engine.dispose()
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def client_config(args) -> dict:
    if args.compose:
        directory = Path(args.compose)
        if not directory.is_absolute():
            raise ValueError("--compose must be an absolute directory on the server")
        command = ["docker", "compose", "--project-directory", str(directory), "--env-file", str(directory / ".env"), "-f", str(directory / "compose.yaml"), "run", "--rm", "--no-deps", "-T", "app", "contitext", "mcp"]
        if getattr(args, "compose_project", None):
            command[2:2] = ["--project-name", args.compose_project]
    else:
        if getattr(args, "compose_project", None):
            raise ValueError("--compose-project requires --compose")
        if not args.config_file or not Path(args.config_file).is_absolute():
            raise ValueError("provide an absolute --config-file path on the server")
        command = [args.executable, "--env-file", args.config_file, "mcp"]
    if args.ssh:
        if args.ssh.startswith("-") or any(char.isspace() for char in args.ssh):
            raise ValueError("--ssh must be a host alias or user@host without whitespace")
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", args.ssh, shlex.join(command)]
    return {"mcpServers": {"contitext": {"command": command[0], "args": command[1:]}}}
