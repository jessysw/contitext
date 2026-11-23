# Upgrade to 0.8.2

This release expands client integration and diagnostics. The database schema stays
at `0004_context_metadata`; there is no new migration or database move. Existing
projects, credentials, ACLs, bindings and reader output remain compatible.
A 0.8.2 automation client works with a 0.8.1 server. Publishing the package does not
upgrade an existing deployment or activate any new client automatically.

## Server and native clients

Keep your normal verified backup and the current private environment/Compose
project name. Install the release into a separate Python environment, or rebuild
the existing Compose deployment from its matching source tag. Preserve the existing
PostgreSQL major version and data volume; this release does not require changing them.
Run `doctor`, check project access, and restart the processes you explicitly choose
to upgrade. For servers older than 0.8.1, complete the
[0.8.1 schema upgrade](upgrading-to-0.8.1.md) first.

Client launchers and hooks pin their Python executable. Upgrading a server does not
replace those local commands. Install the new client in a durable environment,
then use [agent installation](agent-installation.md) and [agent coverage](agent-coverage.md)
to review the correct client/profile. The installer preserves unrelated settings
and refuses a conflicting managed launcher instead of silently taking it over.

## Optional automation

- Use [hook diagnostics](hook-diagnostics.md) to inspect the old configuration and
  pending candidates. Preserve the same private outbox when replacing command hooks.
- Preview `hooks disable`, remove only generated hooks, then install the replacement
  from the new environment. Review changed commands through the client's own trust
  interface. Do not remove the old environment until nothing references it.
- For Hermes, OpenClaw or OpenCode 2, export a new plugin directory, review its code
  and change the runtime reference explicitly. Preserve Hermes identity files and
  any candidate outbox. See [plugin clients](plugin-clients.md).
- Existing MCP users can keep manual chat commands without hooks. New
  mappings and automatic candidate capture are opt-in, never inferred from a repo.

If automation is unavailable, disable the affected hook/plugin and use explicit
MCP commands. No database rollback is needed to disable a client adapter. Keep
pending candidates until you have checked their original project and binding;
never edit them to force delivery into a different conversation.
