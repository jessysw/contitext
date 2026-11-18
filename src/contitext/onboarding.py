"""Generate private configuration without installing or contacting services."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
from uuid import uuid4


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default="demo", help="Initial project identifier; never a conversation default.")
    parser.add_argument("--name", default=None, help="Project display name.")
    parser.add_argument("--principal-name", default="Local operator")
    parser.add_argument("--output", type=Path, default=Path(".env"))


def initialize(args) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.project):
        raise ValueError("project must contain only letters, numbers, dots, underscores, or hyphens")
    if not args.principal_name.strip() or (args.name is not None and not args.name.strip()):
        raise ValueError("names must not be empty")
    principal = str(uuid4())
    password, token = secrets.token_hex(24), secrets.token_urlsafe(32)
    identity = {"principal_id": principal, "name": args.principal_name}
    seed = {
        "projects": [{"id": args.project, "display_name": args.name or args.project, "status": "active"}],
        "principals": [{"id": principal, "name": identity["name"]}],
        "acls": [{"project_id": args.project, "principal_id": principal, "role": "owner"}],
    }
    database_url = os.environ.get("DATABASE_URL") or f"postgresql+psycopg://contitext:{password}@postgres:5432/contitext"
    if not database_url.startswith(("postgresql+psycopg://", "postgresql://")) or any(c in database_url for c in "\r\n\\'"):
        raise ValueError("DATABASE_URL must be a single-line PostgreSQL URL with URL-encoded credentials")
    def literal_json(value):
        # JSON unicode escapes avoid differing dotenv backslash and interpolation rules.
        return json.dumps(value, separators=(",", ":")).replace("\\\\", "\\u005c").replace("'", "\\u0027").replace("$", "\\u0024")
    values = {
        "POSTGRES_USER": "contitext", "POSTGRES_DB": "contitext", "POSTGRES_PASSWORD": password,
        "DATABASE_URL": database_url, "CONTITEXT_PORT": "18791",
        "CONTITEXT_AUTH_TOKENS": literal_json({token: identity}),
        "CONTITEXT_SEED_JSON": literal_json(seed),
        "CONTITEXT_MCP_TOKEN": token, "CONTITEXT_SMOKE_PROJECT_ID": args.project,
        "CONTITEXT_READER_UID": str(os.getuid()) if hasattr(os, "getuid") else "10001",
        "CONTITEXT_READER_GID": str(os.getgid()) if hasattr(os, "getgid") else "10001",
    }
    # Values contain no literal single quotes or ambiguous escaped backslashes.
    lines = ["# Private credentials. Do not commit, share, or shell-source this file."]
    for key, value in values.items():
        lines.append(f"{key}='{value}'")
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return {"configuration": str(args.output.resolve()), "project_id": args.project, "principal_id": principal}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        result = initialize(args)
    except FileExistsError:
        parser.error("configuration already exists; preserved without changes")
    except (ValueError, OSError):
        parser.error("cannot create configuration; check arguments, directory permissions, and DATABASE_URL")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
