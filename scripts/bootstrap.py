#!/usr/bin/env python3
"""Generate a local demo configuration; never overwrite an existing .env."""

import json
import os
from pathlib import Path
import secrets
from uuid import uuid4


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    principal = str(uuid4())
    password, token = secrets.token_hex(24), secrets.token_urlsafe(32)
    identity = {"principal_id": principal, "name": "Local developer"}
    seed = {
        "projects": [{"id": "demo", "display_name": "Demo project", "status": "active"}],
        "principals": [{"id": principal, "name": identity["name"]}],
        "acls": [{"project_id": "demo", "principal_id": principal, "role": "owner"}],
    }
    values = {
        "POSTGRES_USER": "contitext",
        "POSTGRES_DB": "contitext",
        "POSTGRES_PASSWORD": password,
        "DATABASE_URL": f"postgresql+psycopg://contitext:{password}@postgres:5432/contitext",
        "CONTITEXT_PORT": "18791",
        "CONTITEXT_AUTH_TOKENS": json.dumps({token: identity}, separators=(",", ":")),
        "CONTITEXT_SEED_JSON": json.dumps(seed, separators=(",", ":")),
        "CONTITEXT_MCP_TOKEN": token,
        "CONTITEXT_SMOKE_PROJECT_ID": "demo",
    }
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; preserved without changes.")
    with os.fdopen(fd, "w") as file:
        file.write("# Generated local credentials. Do not commit or share this file.\n")
        for key, value in values.items():
            file.write(f"{key}='{value}'\n")
    print("Created .env with private permissions and fresh local credentials.")
    print("Next: docker compose up --build -d --wait")


if __name__ == "__main__":
    main()
