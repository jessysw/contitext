# Upgrade and recovery for Workspace support

Use this procedure to rehearse an upgrade to 0.8.0 against a copy of your database.
Installing the release does not migrate an existing database or restart a running
service. Complete the deployment checks below before a live cutover.

## New installation

In 0.8.0, `contitext init` creates private configuration for one owned
`personal` workspace and the requested initial project. The slug is configurable:

```sh
contitext init --workspace team --workspace-name "Team workspace" \
  --project research --name "Research" --output ./private.env
contitext --env-file ./private.env migrate
contitext --env-file ./private.env admin seed --if-empty
contitext --env-file ./private.env doctor
```

The seed explicitly grants its first principal workspace ownership and project
ownership. On a fresh database, guarded bootstrap removes the empty `legacy`
migration placeholder when a different workspace is requested; it never removes
a workspace containing a project or membership. Re-running `seed --if-empty`
preserves later metadata changes and revocations. Do not use an unguarded seed as
a recurring startup task: applying that explicit operator document can restore
the permissions it declares.

The generated configuration makes bare project IDs resolve in the selected
workspace. It creates no conversation binding. Start each new conversation with
an explicit `contitext: use team/research` (or its configured bare reference).
Additional workspaces use `contitext workspace create`; see [workspaces](workspaces.md).

## Existing deployment: preserve the old namespace

Existing project IDs map to `legacy/<old-id>`. UUIDs become internal keys while
the original slug, event/principal IDs, timestamps, payloads, ACLs and scope
identities remain intact. Every previously provisioned principal becomes a
member of `legacy`, preserving its existing ability to create projects. Membership
does not grant reads; existing project ACLs still determine those permissions.
No workspace owner is inferred from historical project ownership.

Keep this setting in every upgraded process that serves old bare-ID clients:

```dotenv
CONTITEXT_COMPATIBILITY_WORKSPACE=legacy
```

Do not replace an established private environment with newly generated `init`
output: that would create different credentials and principals. Preserve the
existing authentication mode for the schema comparison. Credential imports or
rotation are separate explicit operations after integrity has been verified.

## Read-only inventory and integrity baseline

The candidate CLI can inspect the actual 0.7.1 foundation schema, the credential
schema, or the Workspace schema without starting a server or writing to the
database:

```sh
contitext --env-file ./candidate.env upgrade-check
contitext --env-file ./candidate.env upgrade-check --snapshot ./before.json
```

The output includes the schema revision, target, project mapping, table counts
and normalized SHA-256 fingerprints. It compares projects, principals, ACLs,
events, bindings, projection offsets, credential/audit records, effective project
access and project-creation permissions. Raw event payloads, tokens and database
URLs are not written into the report. Project references and UUIDs are included;
keep the report private. `--snapshot` creates a new mode-0600 file and refuses to
overwrite an existing file.

Invalid historical slugs and unknown schemas fail the check. Fix their migration
plan before proceeding; no automatic renaming is attempted. A successful report
is neither a database backup nor proof that all writers have stopped.

## Rehearse with a real backup

1. Retain the old application version and its private configuration. Use the
   [backup procedure](self-hosting.md#backup-and-recovery-rehearsal) to create a
   private `pg_dump -Fc` backup, with PostgreSQL tools matching your server.
2. Create a **separate empty database** and restore the dump using
   `pg_restore --no-owner --no-acl --exit-on-error`. Set a separate candidate
   environment's `DATABASE_URL` to that copy. Keep the live service pointed at its
   original database.
3. Run `upgrade-check --snapshot ./before.json` against the restored old schema.
   Taking the baseline from the restored copy avoids comparing a live snapshot
   with a backup taken at a different moment.
4. Apply migrations with the candidate CLI, then compare before any new writes:

   ```sh
   contitext --env-file ./candidate.env migrate
   contitext --env-file ./candidate.env upgrade-check --compare ./before.json
   contitext --env-file ./candidate.env doctor
   ```

5. Require `ok: true` and `comparison.matches: true`. A mismatch returns a nonzero
   exit code and names the affected groups. Diagnose every difference before
   cutover; do not replace the baseline to hide it.
6. Read existing bindings and handoffs using a fresh MCP process. Test one writer
   and one reader identity and verify denied access. Run `mcp-smoke` only on this
   disposable copy: it intentionally creates synthetic projects and events.
7. Restore the same backup into another empty database and start the old version
   against it. Verify its old bindings/context and compare the integrity report.
   This proves the recovery path, not just that a backup file exists.

An owner can subsequently be assigned explicitly:

```sh
contitext --env-file ./candidate.env workspace member grant legacy OWNER_UUID \
  --role owner --operator
```

Choose the principal from `principal list`. Test this administration step on the
copy before using it on the live deployment.

## Live cutover and rollback

After release approval and a successful rehearsal, stop/drain **every** writer:
REST, stdio agents, scheduled jobs and operator writes. The optional writer fence
is additional protection, not a substitute for stopping old binaries. Take and
verify a final backup and capture its integrity baseline, then migrate with the
same tested candidate and settings. Compare before restarting clients. An old
binary must not run against the Workspace schema.

Populated namespace schemas deliberately reject automatic downgrade. Restore the
pre-upgrade backup into a separate database, verify it with the old binary and
only then repoint the service. Account for writes made after that backup; do not
silently discard them by restoring over a running database. The integrity report
cannot recover data and does not replace the dump or private configuration.

The pre-release `0003_workspaces` migration was corrected during P3 to preserve
project creation for principals without old ACLs. Anyone testing the earlier P2
development commit should rebuild the disposable database or restore the
pre-upgrade copy and rehearse again. Released 0.7.1 databases use the tested path
above; no historical released migration was changed.

## Recorded P3 rehearsal

The 2026-11-22 local rehearsal used PostgreSQL 18.4 and the actual `v0.7.1` source
at commit `5d00ef0b8a54ae12b217efbe8016893bb3e4896b`. The foundation migration's
SHA-256 is pinned in the regression test. Synthetic data included four principals
(one without ACLs), two projects, ten events across all five event kinds, distinct
grants, two conversation bindings and projection offsets.

A custom-format dump was restored into separate candidate and recovery
databases. The upgraded copy matched all normalized fingerprints, exercised all
eight real stdio MCP tools and retained the original binding in a fresh process.
The recovery copy ran the original 0.7.1 MCP server, read its original binding and
matched the pre-upgrade fingerprints. This is controlled local rehearsal evidence;
it does not claim production migration or independent user acceptance.
