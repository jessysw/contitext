# Upgrade to 0.8.4

This release adds Homebrew distribution and release automation. The database
schema remains `0004_context_metadata`; no migration is added. MCP tools, ACLs,
workspace/project identity, chat syntax, session bindings and candidate state are
unchanged.

1. Use your existing installation method: upgrade the Python package, deploy the
   matching Docker source, or follow the [Homebrew upgrade guide](homebrew.md).
   You do not have to switch an existing deployment to Homebrew.
2. Retain private configuration, credentials, mappings, pending checkpoints and
   PostgreSQL data. Package upgrades do not replace those files or reseed data.
   Keep a backup and follow your normal operational procedure.
3. Restart long-lived Contitext processes and reload MCP connections after the
   package upgrade. Use `contitext --version` and `contitext doctor` with the
   deployment's existing environment to confirm the running installation.
4. Homebrew users should configure MCP with the stable absolute executable
   `$(brew --prefix)/opt/contitext/bin/contitext`. Newly generated Homebrew hooks
   and plugins use its verified `opt` Python path instead of a versioned Cellar
   directory. When changing installation method, explicitly refresh old profiles
   using the supported disable/install or export workflow, keeping private paths
   and completing the host's normal trust review. Installing a formula does not
   silently rewrite agent settings. If you used the bootstrap 0.8.3 Homebrew
   formula, refresh its generated hook/plugin profiles after upgrading and before
   removing the old keg: those older profiles may contain versioned Cellar paths.
5. Existing non-Homebrew hooks and instructions need no syntax change for this
   release. Users upgrading from before 0.8.3 must also follow the
   [chat-prefix migration](upgrading-to-0.8.3.md).

Homebrew installation does not start PostgreSQL or a server. Supply a UTF-8
PostgreSQL 16+ database for native use; Docker Compose can provide PostgreSQL.
Uninstalling the formula removes the package, not private configuration or data.

The existing [native-host acceptance boundaries](acceptance-0.8.3.md) remain in
force. Package and bridge tests are not new authenticated host-chat evidence.
Publishing 0.8.4 does not automatically upgrade a private deployment.
