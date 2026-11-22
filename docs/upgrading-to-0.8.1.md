# Upgrade to 0.8.1

This release adds optional automation and migration `0004_context_metadata`.
Existing data, identities, credentials, ACLs and bindings remain intact. No hook,
local mapping, automatic capture or production deployment is enabled by installing
the server package. Rehearse in a disposable copy before a live upgrade.

For an installation older than 0.8.0, first follow the
[workspace/credential upgrade procedure](upgrading-to-0.8.md). Keep the established
compatibility workspace setting; a project is never inferred from its directory.

## Existing 0.8.0 server

1. Stop or fence every writer: HTTP, independently launched stdio MCP processes,
   agents and exporters that can write projection offsets. Verify a PostgreSQL
   backup by restoring it into a separate test database.
2. Install 0.8.1 in a separate native environment, or prepare a checkout of its
   release tag for the Docker deployment. Keep the old binary and backup available.
3. With the **new** CLI and the old database schema, run
   `contitext --env-file /absolute/private/server.env upgrade-check --snapshot /absolute/private/before-081.json`.
   The check is read-only; it is not a backup or writer fence.
4. Run `contitext --env-file /absolute/private/server.env migrate`, then
   `contitext --env-file /absolute/private/server.env upgrade-check --compare /absolute/private/before-081.json`.
   The comparison must match before writers resume. Absent and null metadata are
   normalized; real metadata remains part of integrity fingerprints.
5. Run `doctor`, restart all service/MCP processes with the new build, and verify
   existing project access and a selected test conversation. Keep PostgreSQL's
   existing network boundaries; no new database host port is required.
6. Upgrade clients that will use optional mappings/hooks. Configure them explicitly
   using [project resolution](project-resolution.md), [session start](session-hooks.md)
   and, only when desired, [candidate checkpoints](checkpoints.md).

For Docker, perform these commands with the new image against the same named
volume while the old app is stopped/fenced. Use the exact Compose project name and
private environment from the existing deployment; do not run initialization against
an unrelated new volume and mistake it for a migration. The default entrypoint also
runs migrations, so take the backup and snapshot **before** starting the new app.

## Rollback and boundaries

The migration adds a nullable JSONB column and three indexes. Historical event
payloads are not interpreted as task IDs or lifecycle relations. Old data remains
null. Existing manual tool calls work; automatic binding and checkpoint replay
require capability discovery and have no unsafe old-server fallback.

Do not run an old binary on the new schema. An empty metadata migration can be
reversed in a rehearsal; once metadata exists, downgrade refuses to discard it.
Use a verified pre-upgrade backup and account for writes since that backup.
Pending hook files are private local copies and are not part of the PostgreSQL
backup. Preserve them when moving a client, and review connection/binding changes
before retrying; never retag stale work by editing its binding timestamp.
