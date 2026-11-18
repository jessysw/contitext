# Installation and operation

Contitext 0.6.0 supports two installation paths. Both use the same code, PostgreSQL
schema, operator commands, and six MCP tools.

| Path | Install and run | Database |
| --- | --- | --- |
| Python package | PyPI package in a virtual environment; native CLI/MCP and optional REST | Supply PostgreSQL 16+ yourself |
| Docker Compose | Build the pinned public release and run its Compose stack | PostgreSQL 16 is included in the stack |

Standard CPython 3.11–3.14 is supported. Free-threaded Python builds are not in the
tested matrix. No paid service or private source repository is required.

## Option 1: Python package

Install from PyPI in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install contitext==0.6.0
```

Create a PostgreSQL 16+ database with your normal database administration tools.
Provide its `DATABASE_URL` through your private environment or secret manager,
using `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE` (URL-encode credentials).
Then initialize your own project and caller identity:

```sh
contitext init --project research --name "Research" --output /absolute/private.env
contitext --env-file /absolute/private.env migrate
contitext --env-file /absolute/private.env admin seed --if-empty
contitext --env-file /absolute/private.env doctor
contitext --env-file /absolute/private.env project list
contitext --env-file /absolute/private.env principal list
```

Use real absolute paths and an existing parent directory. `init` generates private
credentials, a principal UUID, and an initial owner grant; no seed JSON editing is
needed for this workflow. It never overwrites existing configuration and does not
install PostgreSQL or create a database. Without `DATABASE_URL`, it generates the
Compose configuration described below. Load the resulting mode-0600 file with
`--env-file`; never shell-source it or commit it to Git.

For an MCP client, generate its command configuration:

```sh
contitext client-config --config-file /absolute/private.env --executable /absolute/venv/bin/contitext
```

Merge the generated server entry into the client's configuration and install the
[agent protocol](https://github.com/jessysw/contitext/blob/main/integrations/PROJECT-CONTEXT-PROTOCOL.md)
in its instruction mechanism. The client launches a stdio process as needed.
**Native MCP does not require Docker or a running REST server.** If you also want
REST, run this separately under your normal process supervisor:

```sh
contitext --env-file /absolute/private.env serve --host 127.0.0.1 --port 18791
```

The package includes migrations and all operator commands, so it works outside a
source checkout. To develop from source, use `python -m pip install .` instead.
For Registry-assisted installation, see the [Registry setup guide](mcp-registry.md).

## Option 2: Docker Compose

Requires Docker with Compose, Git, and Python 3.11–3.14 for the dependency-free
bootstrap script. A separate host Python environment for Contitext is unnecessary.

```sh
git clone --branch v0.6.0 --depth 1 https://github.com/jessysw/contitext.git
cd contitext
python3 scripts/bootstrap.py --project research --name "Research"
docker compose up --build -d --wait
docker compose exec -T app contitext doctor
docker compose exec -T app contitext project list
```

Bootstrap creates `.env` with fresh credentials, a principal, and the project owner
grant. Compose builds the application, starts PostgreSQL, applies migrations, and
seeds only an empty deployment. Restarts preserve later metadata and access changes.
The API is bound to `127.0.0.1:18791`; PostgreSQL has no published host port. Data
lives in a named volume. `docker compose down` preserves it; `down -v` deletes it.

Generate client configuration from the running app:

```sh
docker compose exec -T app contitext client-config --compose /absolute/path/to/contitext
```

That path is the checkout directory on the Docker host, not a path inside the
container. Merge the generated entry into your MCP client and install the same
[agent protocol](https://github.com/jessysw/contitext/blob/main/integrations/PROJECT-CONTEXT-PROTOCOL.md).
If you used `docker compose -p NAME`, add `--compose-project NAME` when generating
client configuration. For the synthetic demo, use the default `demo` bootstrap
and follow the [README quick start](../README.md).

## Agent installation

Use the [repeatable adapter installer](agent-installation.md) to configure Codex,
Claude Code, Zed, Hermes, or OpenClaw and install their shared protocol. The same
installer supports either server deployment path and remote SSH connections.
It backs up client settings and does not migrate or duplicate the database.

## Projects, identities, and permissions

Use `project create/list/show/update`, `principal create/list`, and
`access grant/list/revoke` for daily administration. For native commands, provide
`--env-file`; for Compose, prefix the command with `docker compose exec -T app`.
The [operator workflow](self-hosting.md) contains complete examples and recovery
steps. The [command reference](commands.md) lists options and chat commands.

Operator commands require trusted database access; they are not MCP tools.
`admin seed` explicitly upserts the supplied document and does not revoke omitted
entries. `admin seed --if-empty` preserves later administration on an established
deployment. Configured bearer credentials map to principal UUIDs; project ACLs
control what those identities can access. A project is never selected for a
conversation merely because it was created or exists in a working directory.

## Remote use

Either installation can run on your own server. Generate an SSH stdio command with
`client-config --ssh HOST` plus `--compose` or `--config-file`; use an existing SSH
host alias and server-side absolute paths. Keep native database/token configuration
on that server. No particular host, key, account, or path is built into the package.

For remote REST access, use TLS and appropriate network controls. Do not expose
PostgreSQL publicly. Docker and database access are trusted operator capabilities,
not a tenant isolation boundary. Token changes require REST/MCP process restarts;
ACL changes are checked on subsequent requests without restarting.

## Optional Markdown projection

Set `CONTITEXT_PROJECTS_ROOT` on the REST process. For each project, create a
directory containing `NOTES.md`, `DECISIONS.md`, `OPEN-QUESTIONS.md`, `STATUS.md`, and
a `HANDOFFS/` directory. The service appends deterministic event blocks and keeps
a database cursor. Paths must be ordinary files/directories, not symlinks. The
implementation requires POSIX no-follow directory operations. Projection is
optional and is not enabled by the default Compose file; mount the directory
explicitly when enabling it in Docker.

For migration from an earlier marker namespace, set
`CONTITEXT_LEGACY_MARKER_PREFIXES` to explicitly trusted comma-separated prefixes.
Existing `<!-- PREFIX:event:UUID:begin -->` blocks then prevent duplicate projection
after a cursor rewind. New blocks use `contitext`; existing files are not rewritten.
The default accepts only Contitext's own markers.

## Backup, upgrades, and migration

Follow the [backup and recovery rehearsal](self-hosting.md#backup-and-recovery-rehearsal)
for your chosen installation. Preserve the database, private configuration, and
optional Markdown/Git history separately. Rehearse restoration into a new database
before changing a working deployment. Stop all REST and MCP writers for the final
cutover and retain a rollback path. Publishing a new package does not migrate or
restart existing deployments automatically.

When upgrading from 0.5.x, all event and handoff writes now require a matching
persisted scope binding. Bind explicitly before writing, including retries after
switching projects. Existing correctly bound conversations continue working;
there is no schema change. See the [0.6.0 release notes](../CHANGELOG.md).
