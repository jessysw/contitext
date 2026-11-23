# Installation and operation

Contitext 0.8.3 supports two installation paths. Both use the same code, PostgreSQL
schema, operator commands, and eight MCP tools.

| Path | Install and run | Database |
| --- | --- | --- |
| Python package | PyPI package in a virtual environment; native CLI/MCP and optional REST | Supply PostgreSQL 16+ yourself |
| Docker Compose | Build the pinned public release and run its Compose stack | PostgreSQL 16 is included in the stack |

Standard CPython 3.11–3.14 is supported. Free-threaded Python builds are not in the
tested matrix. No paid service or private source repository is required.

## Option 1: Python package

Install in a virtual environment. Use the version below for a reproducible setup;
`python -m pip install contitext` selects the latest stable release for a fresh
installation. Existing deployments should follow the [upgrade guide](upgrading-to-0.8.md).

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install contitext==0.8.3
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
git clone --branch v0.8.3 --depth 1 https://github.com/jessysw/contitext.git
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

For separate identities and private credential overlays, follow
[Two independently authenticated agents](two-agents.md). Existing deployments
must follow [the 0.8 upgrade guide](upgrading-to-0.8.md) before changing binaries.

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
deployment. Credentials map to principal UUIDs; both workspace membership and project ACLs
control access. Fresh bootstrap creates the explicitly configured `personal`
workspace, and qualified references use `workspace/project`. See [workspaces](workspaces.md). A project is never selected for a
conversation merely because it was created or exists in a working directory.

## Remote use

Either installation can run on your own server. Generate an SSH stdio command with
`client-config --ssh HOST` plus `--compose` or `--config-file`; use an existing SSH
host alias and server-side absolute paths. Keep native database/token configuration
on that server. No particular host, key, account, or path is built into the package.

For remote REST access, use TLS and appropriate network controls. Do not expose
PostgreSQL publicly. Docker and database access are trusted operator capabilities,
not a tenant isolation boundary. Config-mode token changes require process restarts. In database mode, revocation
is checked on each invocation; see [credentials](credentials.md). Membership and
ACL changes are checked on subsequent requests without restarting.

## Human-readable Markdown reader

Use [Getting started](getting-started.md) for the full first-use workflow and
[Obsidian and the Markdown reader](obsidian.md) to enable readable exports.
The new `export` command reads the database directly, so it includes events that
were never projected to the older curated Markdown files. It does not change
those files or their projection offsets.

## Optional curated Markdown projection

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
there is no schema change. See the [release notes](../CHANGELOG.md).

Project listing and creation (introduced in 0.7) work before
project selection. Reload MCP and rerun the adapter installer to install the new
protocol. Clients with the complete legacy six-tool allowlist are expanded to
include the two new tools; custom restrictions remain unchanged. The database
schema and existing six tool contracts are unchanged.

In 0.7.1, enable the reader explicitly; existing services and the eight MCP tool
contracts are unchanged. There is no schema migration. Existing `.env` files are
preserved, so set the reader UID/GID as described in the reader guide when
upgrading an older Compose deployment. The optional reader is a separate process
with its own restart policy; it does not block context writes if export fails.
