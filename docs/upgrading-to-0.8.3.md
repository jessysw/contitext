# Upgrade to 0.8.3

This is an intentional breaking chat-syntax correction in the early 0.x series.
Use `contitext: status`, not `!! contitext status`. All bang-prefixed aliases and
the `ctx:` prefix are unsupported. ASCII and full-width colons work, with
case-insensitive prefix/command names and unchanged argument text. See the
[syntax contract](chat-commands.md).

1. Install the 0.8.3 Python package or deploy the matching Docker source using
   your usual backup and upgrade procedure. The schema remains
   `0004_context_metadata`; this release adds no migration.
2. Rerun the [agent adapter installer](agent-installation.md) from the 0.8.3
   source for each existing client. **Upgrading only the server is insufficient:**
   old instruction files continue advertising the old prefix until replaced.
3. If you explicitly installed a native plugin, export the updated module into a
   new directory, review it and activate it through that runtime. Keep the same
   private connection, mappings and pending-candidate directory. Follow
   [plugin setup](plugin-clients.md); exports never enable themselves.
4. Existing command hooks continue working. If you change their pinned Python
   executable, replace generated hooks with the supported disable/install flow,
   retain their outbox, and review the changed commands in the host's trust UI.
5. Reload MCP and start a new session so cached instructions are refreshed. Try
   `contitext: help`, `contitext: list` and `contitext: status`. Use
   `contitext: use <project>` if the conversation is unbound. Existing explicit
   project bindings and trusted mapping precedence remain unchanged.

The terminal CLI is still `contitext <subcommand>` with its existing management
commands; chat `use` and `status` do not become terminal subcommands. No `ctx`
executable, new MCP tool, ACL change or session-identity change is introduced.
Existing projects, history, credentials and candidate state are retained.

Installers affect only the clients you select. Review and replace manually copied
protocol files too; a server cannot overwrite instructions already loaded into a
running chat. Retain backups for rollback. Older releases use their historical
syntax, so do not mix an old instruction file with this guide.
