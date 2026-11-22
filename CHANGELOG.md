# Changelog

## Unreleased

- Add read-only hook diagnostics, content-free local outcomes, safe generated-hook
  removal and explicit timeout budgets. Exercise all eight automation bridges
  from installed wheel and Docker artifacts; distinguish runtime activation from
  configuration and contract test coverage.

- Export optional native adapters for Hermes memory-provider lifecycle, OpenClaw
  prompt/finalization hooks, and OpenCode 2 context/events. Preserve explicit
  scope bindings, keep compression lineage private, and require runtime-owned
  activation and permission review.

- Add native lifecycle adapters for Copilot CLI, Cursor desktop and Gemini CLI,
  including bounded startup, exact conversation identity, candidate capture where
  final response text is available, and safe retries without transcript ingestion.

- Add opt-in user-level MCP/instruction installers for Copilot, Cursor, OpenCode
  and Gemini CLI. Preserve restrictions and unrelated configuration; require an
  explicit OpenCode major-version layout and document runtime/profile differences.

## 0.8.1 — 2026-11-22

- Add opt-in candidate progress capture after responses, explicit intermediate
  checkpoints, and bounded compaction/end/interruption retries. Persist private
  pending work before network delivery; pin replay to the exact authorized
  binding and reject stale timestamps atomically.

- Add explicit task/candidate/lifecycle metadata and bounded context assembly.
  Select relevant handoffs, effective decisions and unresolved questions while
  preserving immutable history and the existing eight MCP tool names.
- Add an additive metadata migration, 0.8.0 integrity rehearsal, safe downgrade
  refusal and metadata visibility in Markdown readers.

- Add opt-in Codex and Claude Code session-start hydration, with bounded worker
  cleanup, explicit identity, binding recheck and failure-open behavior. Preserve
  unrelated client settings and require normal hook trust review.

- Add opt-in, connection-scoped local project mappings and authorization-checked
  MCP resolution. Preserve manual selections with atomic bind-if-unbound; reject
  ambiguous remotes and never infer a project from a basename.
- Deliver the four automation capabilities together after focused PRs, full CI
  and installed-artifact acceptance; retain explicit selection and progress writes.

## 0.8.0 — 2026-11-22

- Release workspace isolation, managed credentials, upgrade integrity checks and
  the complete native/Docker two-agent workflow as the normal 0.8 release.
- Align package, Registry, installation examples and security documentation with
  the stable version; preserve the runtime behavior validated for 0.8.0rc1.
- Use maintainer review, full CI and documented operational rehearsals for release
  acceptance. External testers and prerelease numbering are optional.

## 0.8.0rc1 — 2026-11-22 (prerelease)

- Define the self-hosted release plan, workspace/identity boundaries and acceptance gates.
- Add opt-in database-backed credentials with hash-only storage, private one-time
  file delivery, expiry, rotation, revocation, import and lifecycle audit metadata.
- Reauthenticate database credentials for each HTTP request, MCP tool call and
  Markdown reader refresh; preserve the default configuration authentication mode.
- Add an additive credential migration and refuse destructive downgrade once
  credential history exists.
- Add workspace membership, immutable project UUIDs, workspace-local slugs and
  explicit qualified references across REST, MCP, bindings, search and exports.
- Preserve historical data and permissions through a transactional migration;
  add owned workspace bootstrap and read-only upgrade integrity checks.
- Add per-client launchers and protected credential overlays so configuring a
  second agent cannot silently change the first agent's connection.
- Add workspace-aware diagnostics, a two-identity first-use tutorial, and
  namespace-aware reader, installer and Registry configuration guidance.

- Rehearse installed-wheel and Docker onboarding, restart and verified restoration;
  record candidate evidence separately from pending independent first-use tests.

## 0.7.1 — 2026-11-18

- Add authenticated, read-only Markdown exports for Obsidian and other readers.
- Show project state and complete event history with readable payloads and source metadata.
- Support selected projects or automatic discovery, periodic refresh, refresh status,
  safe output ownership, and removal of revoked projects on successful full refreshes.
- Add an opt-in Compose reader with automatic restart and freshness health checks.
- Add a complete getting-started tutorial and native, Docker, and remote reader guides.
- Align current release examples, security guidance, and all eight MCP tool listings.
- Preserve the database schema, existing curated Markdown, and all MCP contracts.

## 0.7.0 — 2026-11-17

- Add `!! contitext list` and `!! contitext create ID --name "Name"`, backed by
  `project_list` and `project_create` MCP tools and matching REST endpoints.
- List only projects granted to the authenticated caller, with bounded pagination.
- Create a project and its caller-owned ACL atomically without selecting a chat
  project, exposing an owner override, or overwriting existing project IDs.
- Default CLI project creation to the configured MCP identity; preserve explicit
  owner UUIDs as a trusted operator override.
- Respect writer fencing and preserve generic conflict errors for hidden IDs.
- Preserve existing bindings, schema, and the original six MCP tool contracts.
- Expand complete legacy tool allowlists while preserving custom restrictions.
- Document repository independence and distinguish status metadata from archival.
- Add PostgreSQL 18 CI coverage alongside the supported PostgreSQL 16 baseline.


- Add a repeatable adapter installer for Codex, Claude Code, Zed, Hermes, and
  OpenClaw, with configuration backups, dry runs, and explicit legacy migration.
- Document shared-server client setup without installing another database.

## 0.6.0 — 2026-11-17

### Self-hosting

- Support two documented installation paths: a native PyPI package with your own
  PostgreSQL database, or the public Docker Compose stack.
- Initialize private configuration with a chosen project and fresh credentials.
- Manage projects, principals, and access grants from the `contitext` CLI.
- Diagnose configuration/database/identity/access without writing data.
- Generate native, Docker, or SSH stdio MCP client configuration without embedding
  credentials. Native MCP can run without REST.
- Document client setup, credential changes, backup/recovery, and deployment migration.

### Integrity and recovery

- Require event and handoff writes to match the authenticated caller's persisted
  conversation binding. Validation and insertion share a transaction with rebinds.
- Seed Compose only on an empty deployment so restart does not restore revoked
  access or overwrite later project metadata.
- Accept explicitly configured legacy Markdown marker prefixes during recovery
  without rewriting curated content or duplicating projected events.
- Preserve literal project names across native and Compose configuration parsing.
- Normalize plain PostgreSQL URLs to the installed psycopg driver.

### Upgrade notes

No database migration is added; the six MCP tool schemas remain unchanged.
Unbound or mismatched writes now return HTTP 409 or an MCP tool error. Bind the
conversation explicitly before writing, and before retrying an event after
switching away from its project. A resumed session can keep its existing binding.

Administration requires trusted database access. Token additions/removals still
use protected configuration and require process restarts; ACL changes do not.
Existing data, identity IDs, scope IDs, tokens, and optional Markdown must be
preserved during a deployment migration. There is no automatic live cutover.

Validation includes 86 tests across Python 3.11–3.14, a Python 3.14 dependency-floor
job, installed-wheel acceptance, actual Compose/MCP restart behavior, and an
isolated database/Markdown restore and projection replay rehearsal.
