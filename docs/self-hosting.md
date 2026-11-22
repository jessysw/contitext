# Self-hosting and replacing an existing deployment

This guide covers Contitext 0.8.0 for trusted personal or small-team deployments.
Choose the [Python package or Docker Compose installation](installation.md); both
provide the commands below. PostgreSQL 16+ is required. No private repository,
cloud account, LLM API key, or hosted control plane is needed.

## Start with your own project

For the source/Compose installation:

```sh
python3 scripts/bootstrap.py --project research --name "Research"
docker compose up --build -d --wait
docker compose exec -T app contitext doctor
docker compose exec -T app contitext project list
docker compose exec -T app contitext principal list
```

Bootstrap creates a mode-0600 `.env` with a random principal UUID, fresh credentials,
and an owner grant for `research`. It never overwrites existing configuration.
Compose applies that seed only to an empty deployment. Later restarts do not
restore revoked access or overwrite project metadata. No conversation is bound
automatically. Skip the synthetic demo when initializing a real project.

For a Python installation and an existing PostgreSQL database, set `DATABASE_URL`
through your private environment or secret manager first, then run:

```sh
contitext init --project research --name "Research" --output /absolute/private.env
contitext --env-file /absolute/private.env migrate
contitext --env-file /absolute/private.env admin seed --if-empty
contitext --env-file /absolute/private.env doctor
contitext --env-file /absolute/private.env client-config --config-file /absolute/private.env --executable /absolute/venv/bin/contitext
```

For MCP-only use, let the agent launch the generated stdio command. Run
`contitext --env-file /absolute/private.env serve --port 18791` separately only
when you also need REST. Use your normal process supervisor for an always-on REST
deployment; package installation does not register a system service.

`init` uses the existing `DATABASE_URL` if supplied. Without it, it creates the
configuration for the Compose `postgres` service, not a host PostgreSQL instance.
It does not install PostgreSQL or create a database. The file uses dotenv syntax;
load it with `--env-file`, never `source`. Keep it outside Git. Do not use an
untrusted dotenv file: it configures database access and process behavior.

## Manage projects and access

The normal creation command uses the authenticated MCP identity; no owner UUID
is needed. List, create, and select projects directly from an agent chat as shown
in the [command reference](commands.md#everyday-project-workflow). For operators:

```sh
contitext project create client-work --name "Client work"
contitext project list
contitext project show client-work
contitext project update client-work --status paused
contitext principal create "Second operator"
contitext workspace member grant personal PRINCIPAL_UUID
contitext access grant personal/client-work PRINCIPAL_UUID --role reader
contitext access list client-work
contitext access revoke client-work PRINCIPAL_UUID
```

Prefix these commands with `docker compose exec -T app` for Compose, or add
`--env-file /absolute/private.env` immediately after `contitext` for native use.
IDs and grants are explicit; project creation never selects a chat project.
Creating an existing ID fails instead of overwriting it. Creation and the first
owner grant are one transaction. Revoking access preserves events and bindings;
subsequent API/MCP requests recheck the ACL. In-flight operations may finish.
A status such as `paused` is metadata, not a permission switch.

Project discovery and self-owned creation are also exposed through MCP/REST.
Principal administration, ACL management, and creating on another owner's behalf remain trusted database-operator capabilities. An authenticated,
provisioned identity with workspace membership may create projects in that workspace
even before it has any project grants;
this grants no access to existing projects. A bearer `owner` role does not grant
shell/database administration. For an explicit operator override, use
`project create ID --name NAME --owner UUID`; obtain UUIDs with `principal list`.
An operator can revoke the last owner and recover with `access grant`; history
is not deleted. Omitting an entry from a seed does not revoke it.

Principal creation does not issue a credential. Use the complete
[two-agent setup](two-agents.md) to enable database-mode credentials, grant
membership and project ACLs, and install separate connections. Database-mode
revocation takes effect on the next invocation, including an existing MCP session.
Config-mode token mapping changes require process restarts. A single trusted
operator can also share one identity, but separate credentials/principals make
agent-specific revocation and project permissions possible.
This release does not provide OAuth, a token administration UI, or tenant hosting.

## Connect clients and verify continuity

Generate generic MCP JSON, without embedding credentials:

```sh
contitext client-config --compose /absolute/path/to/contitext
contitext client-config --compose /absolute/path/to/contitext --ssh my-context-host
contitext client-config --config-file /absolute/private.env --executable /absolute/venv/bin/contitext
```

The SSH form uses your existing SSH configuration. `--compose` and `--config-file`
refer to paths on the server. Merge the generated server entry into the client's
configuration format; do not replace unrelated entries. The command does not
install SSH keys or modify client settings. Docker and database access are trusted
operator capabilities, not a sandbox for untrusted users.
If you started Compose with `-p NAME`, also pass `--compose-project NAME` when
generating the client configuration so it joins the same deployment.

Install the [agent protocol](../integrations/PROJECT-CONTEXT-PROTOCOL.md) in each
agent's instruction mechanism and restart its MCP session. Then:

1. Agent A: `!! contitext use research` and record a checkpoint and handoff.
2. Agent B, in a separate conversation: `!! contitext use research`, then
   `!! contitext status`. Verify it can retrieve A's handoff.
3. Restart the MCP client and verify its original scope binding still resolves.
4. Use `doctor` for non-mutating diagnostics. `mcp-smoke` writes synthetic events;
   run it only against a dedicated test project.

Writes require the authenticated caller's scope to be bound to the same project.
A missing/mismatched binding is HTTP 409 or an MCP tool error. Save the old
project's handoff before rebinding. Session IDs may change when a conversation
resumes. An idempotent retry after switching away requires rebinding first.

## Backup and recovery rehearsal

Keep a PostgreSQL dump, protected configuration, and any curated Markdown/Git
history separately. A database dump contains events and projection cursors, not
Markdown files, Git history, or secrets from the service environment.

For Compose, create a private backup without overwriting an existing file:

```sh
mkdir -p backups
chmod 700 backups
(umask 077; set -C; docker compose exec -T postgres sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > backups/rehearsal.dump)
```

Check the command's exit status; remove a failed partial dump before retrying.
`pg_dump` takes a consistent online snapshot. Do not commit or share the dump.
Use the same PostgreSQL major version or a supported newer target for restoration.

Restore into a **new, empty** database. The following example fails if the target
already exists and never drops an existing database:

```sh
docker compose exec -T postgres sh -c \
  'exec createdb -U "$POSTGRES_USER" contitext_restore_check' && \
docker compose exec -T postgres sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d contitext_restore_check --no-owner --no-acl --exit-on-error' \
  < backups/rehearsal.dump
```

For a native installation, use PostgreSQL's `pg_dump`, `createdb`, and `pg_restore`
utilities. Configure their standard `PGHOST`, `PGPORT`, `PGUSER`, and `PGDATABASE`
settings for the source database, with credentials in a protected `PGPASSFILE` or
your secret manager. These utilities do not read Contitext's dotenv file and do
not accept SQLAlchemy's `postgresql+psycopg://` scheme. Then:

```sh
mkdir -p backups
chmod 700 backups
(umask 077; set -C; pg_dump -Fc > backups/rehearsal.dump)
createdb contitext_restore_check && \
pg_restore -d contitext_restore_check --no-owner --no-acl --exit-on-error \
  backups/rehearsal.dump
```

Point a separate candidate service at that restored database using a separate
private configuration. Run migrations, `doctor`, read existing bindings/context,
and test writes only in the copy. Compare row counts and full records for projects,
principals, ACLs, bindings, events, and projection offsets. Restart the candidate
and repeat the reads. Never aim the destructive test suite at a real or restored
deployment database; tests require a separate database whose name contains `test`.

Keep curated Markdown alongside its matching projection offsets, and preserve
private Git history in a private archive. Migrations do not import Markdown as
events. If those files are missing or the snapshot was taken during a projection,
rehearse reconciliation in the copy before enabling projection against them.
If an earlier implementation used another event-marker prefix, configure
`CONTITEXT_LEGACY_MARKER_PREFIXES` on the candidate REST service and test a cursor
rewind in the copy. Accepted legacy blocks remain unchanged; new blocks use
`contitext`. Do not enable arbitrary prefixes from untrusted file content.

## Cut over only after rehearsal

1. Inventory all REST and MCP writers, private configuration, and Markdown roots.
2. Verify the candidate against a restored copy, including all clients you use.
3. At cutover, drain/stop every writer and take a final database and file backup.
4. Start the released Contitext package/image with preserved principal UUIDs,
   database records, tokens, and scope IDs. Do not reseed over existing grants.
5. Update client executable/configuration paths and the public agent protocol.
6. Verify bindings, handoffs, search, and a designated test-project write.

Retain the previous image, configuration, database backup, and private history
until acceptance. A rollback must account for writes made after cutover; do not
restore an old dump over them. The optional writer fence is an additional guard,
not a substitute for stopping all writers. After acceptance, archive the private
implementation and maintain only public Contitext code plus private deployment
configuration/data. The deployment is not migrated merely because the package
has been published.

## Human reading and Obsidian

Use the [Markdown reader guide](obsidian.md) to export current database state
without an agent. Generated reading copies can be rebuilt from PostgreSQL and do
not replace backups or curated Markdown. They are not imported on restore.
