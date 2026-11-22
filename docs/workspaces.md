# Workspaces and project namespaces

This guide describes Workspace support in the 0.8.0rc1 candidate. It is not
available in stable 0.7.1. The upgrade
rehearsal and two-agent guides are implemented; final acceptance is tracked in the
[0.8 plan](v0.8-plan.md). Rehearse candidate migrations against a copy before changing a live service.

## Names and identities

A deployment contains workspaces. Each workspace has an immutable UUID and a
deployment-unique slug, such as `personal` or `team`. A project has an immutable
UUID and a slug unique within its workspace. Both `personal/research` and
`team/research` can exist and keep separate ACLs, events and idempotency keys.
Slugs are case-sensitive. New slugs contain 1–128 letters, digits, dots,
underscores or hyphens and start with a letter or digit.

The existing eight MCP tools keep their names and parameters. Their `project_id`
string accepts a **project reference**, normally `workspace/project`. The same
reference works in CLI arguments and REST paths, for example
`GET /v1/projects/team/research/context`. UUIDs are the internal keys for ACLs,
events, conversation bindings and projection offsets; callers need not copy them
to use a project. Workspace and project renaming or moving are not exposed.

```text
!! contitext list
!! contitext create personal/research --name "Research"
!! contitext use personal/research
```

Creation and listing never select a project. A conversation binding remains
specific to its authenticated principal and scope. Changing deployment settings
does not change an existing binding, even if another workspace has the same
project slug. A Workspace is not a repository association or a default project.

## Membership and project access

Both permissions are required:

1. Membership in the project's workspace (`member` or `owner`).
2. An explicit project ACL (`reader`, `writer` or `owner`).

A workspace member may create a project in that workspace and receives its owner
ACL. Workspace ownership permits membership administration but does not grant
access to other people's projects. Display names, `agent_id` and source metadata
never grant authority. Unknown and unauthorized projects return the same
`project not found` result.

Removing membership immediately denies subsequent project list, read, search,
write, bind, current-binding, projection and export calls. Project ACL revocation
is also checked on each call. Previously authorized transactions may finish;
membership/ACL mutations wait for transactions holding authorization locks. The
read-only Markdown exporter uses one consistent snapshot per refresh, so a
refresh already in progress may finish before a revocation becomes visible.

Membership removal retains project grants and history. An explicit membership
re-grant restores access allowed by those existing ACLs. Revoke unwanted project
grants as well before re-admitting a principal. Revocation cannot erase copies
already read or exported. The reader's managed-file cleanup and stale-copy
limitations still apply; see [the Obsidian guide](obsidian.md).

## Operator and owner commands

These commands require the configured database and installed development CLI.
Use the configured credential of the intended caller. Principal UUIDs are shown
by `contitext principal list`; credential issuance is described in
[the credential guide](credentials.md).

```sh
contitext workspace create personal --name "Personal workspace"
contitext workspace list
contitext workspace member list personal
contitext workspace member grant personal MEMBER_UUID --role member
contitext project create personal/research --name "Research"
contitext access grant personal/research MEMBER_UUID --role reader
contitext workspace member revoke personal MEMBER_UUID
```

`workspace create` defaults to the authenticated caller as the first owner.
Membership changes require an authenticated workspace owner. Removing or demoting
the last owner is rejected, including concurrent requests. Adding a member does
not create an ACL or bind a conversation. Project ACL grants reject principals
who are not members of that workspace.

Native CLI, database and unrestricted SSH access are trusted operator surfaces.
The existing `project`, `principal` and `access` commands administer the database
directly. Workspace membership commands have an explicit `--operator` override;
workspace creation accepts `--owner PRINCIPAL_UUID` for trusted provisioning.
These overrides are **not MCP tools or REST endpoints**. Do not give mutually
untrusted tenants database credentials or unrestricted SSH and expect workspace
ACLs to sandbox those privileges. This release is for trusted self-hosting, not
a hosted SaaS security boundary.

## Compatibility and migration boundary

Migration `0003_workspaces` creates the explicitly named `legacy` workspace and
maps existing string project IDs to slugs in it. Its stable UUID is
`00000000-0000-4000-8000-000000000001`. Projects receive new UUIDs; every existing
ACL, binding, event and projection offset is mapped to the corresponding UUID in
one PostgreSQL transaction. Event IDs, principal IDs, provenance, timestamps and
payloads are preserved. Existing provisioned principals become members, not workspace
owners; this preserves their prior ability to create projects without adding any
project read grants; an operator assigns ownership explicitly if needed.

Bare IDs are disabled unless the process explicitly configures:

```dotenv
CONTITEXT_COMPATIBILITY_WORKSPACE=legacy
```

With this setting, `research` means exactly `legacy/research`. Responses use bare
references for that workspace and qualified references for all others, allowing
old callers to keep using their original project IDs. There is no search across
workspaces, fallback to the only accessible match, or directory-based inference.
An absent or inaccessible configured workspace fails closed. New development
`init` output creates an owned `personal` workspace by default (or the explicit
`--workspace` choice) and configures short-name compatibility for that workspace.
The migration path for existing deployments remains `legacy`.

```sh
# Trusted operator: assign the migrated workspace its first owner.
contitext workspace member grant legacy OWNER_UUID --role owner --operator
```

Invalid historical slugs cause the migration to roll back rather than silently
rename data. Populated workspace schemas cannot be downgraded automatically:
flattening them could lose membership semantics or collide on project names.
Restore a verified pre-upgrade backup instead. Operational preflight, writer
fencing, backup/restore rehearsal and the complete old-client upgrade procedure
are P3/P5 work; the migration's unit/integration tests are not live-upgrade approval.

## Human-readable output

The authenticated Markdown reader uses each project's full resolved reference
when deriving its collision-resistant filename. Two workspaces with `research`
therefore export to separate pages. Explicit export selection accepts qualified
references and requires the same membership and ACL checks as other reads.

The optional owner-only incremental projector uses `workspace/project/` below
its configured root, or the existing `project/` directory for the explicitly
configured compatibility workspace. The operator must prepare those directories
and Markdown files first. Every path component is opened without following
symlinks; file and directory safety checks also apply at the workspace level.

## Validation scope

P2 tests exercise same-slug projects, UUID bindings and idempotency, scoped search
cursors, membership plus ACL checks, MCP/HTTP calls after revocation, CLI
ownership, concurrent last-owner removal and write/revoke ordering, reader and
projector separation, and transactional legacy-schema mapping. The complete
P3–P5 migration, client onboarding and release acceptance work remains separate.
