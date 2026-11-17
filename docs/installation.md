# Installation and operation

## Python package

Standard CPython 3.11–3.14 and PostgreSQL 16+ are supported.
Free-threaded Python builds are not included in the tested support matrix.
For a published release, install the package from PyPI:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install contitext==0.5.4
```

For a source checkout, use `python -m pip install .` instead.

Provide `DATABASE_URL` using the SQLAlchemy `postgresql+psycopg://` scheme and
`CONTITEXT_AUTH_TOKENS` using the JSON shape in `.env.example`. Supply
`CONTITEXT_SEED_JSON` with the projects, principal UUIDs, and ACLs you want to create.
The generic identifiers in `.env.example` are examples, not production credentials.

```sh
contitext migrate
contitext admin seed
contitext serve --host 127.0.0.1 --port 18791
```

Migrations are included in the installed package, so these commands work outside
the source checkout. `contitext admin seed` upserts the entries supplied and does
not revoke entries omitted from the seed. It requires database-owner privileges;
keep administration separate from untrusted clients.

For native stdio MCP, provide the same database/token-store configuration plus
`CONTITEXT_MCP_TOKEN`, then run `contitext mcp`. Client-side instructions are in
`integrations/PROJECT-CONTEXT-PROTOCOL.md`.

For clients that install from the official MCP Registry, see the
[Registry setup guide](mcp-registry.md).

See the [command reference](commands.md) for supported terminal commands and
agent chat instructions.

## Remote use

The quick start is intentionally local. For an HTTP deployment, use TLS, protect
administrative access, and issue separate bearer credentials and project ACLs to
each trusted client. Do not expose PostgreSQL publicly. A stdio MCP client may run
the existing command over your own SSH transport; no host or SSH identity is
hardcoded in this repository. Docker access and database credentials are trusted
administrator capabilities, not a tenant isolation boundary.

## Optional Markdown projection

Set `CONTITEXT_PROJECTS_ROOT` on the REST process. For each project, create a
directory containing `NOTES.md`, `DECISIONS.md`, `OPEN-QUESTIONS.md`, `STATUS.md`, and
a `HANDOFFS/` directory. The service appends deterministic event blocks and keeps
a database cursor. Paths and files must be ordinary files/directories, not
symlinks. The implementation requires POSIX no-follow directory operations; use
the Linux container when your host does not support them. Projection is optional
and is not enabled by the default Compose file.

## Backup and upgrades

Back up the PostgreSQL database and keep token configuration separately protected.
For the local Compose deployment:

```sh
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > contitext-backup.dump
```

The dump contains your private project data. Do not commit it. Test recovery into
a separate empty database before relying on a backup. Stop REST and MCP writers
before schema upgrades or restoration. A file specified by
`CONTITEXT_WRITER_FENCE_FILE` causes service writes to fail while the file exists;
it is an additional maintenance guard, not a replacement for draining/stopping all
writers. Keep the original deployment running until a separate migration rehearsal
has verified data, bindings, ACLs, and client behavior.
