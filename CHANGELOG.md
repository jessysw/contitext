# Changelog

## Unreleased

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
