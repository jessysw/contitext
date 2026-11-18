# Changelog

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
