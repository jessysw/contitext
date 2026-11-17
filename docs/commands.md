# Commands

Contitext has two distinct interfaces: a terminal CLI and instructions that an
agent follows in a conversation. Neither interface infers a project from the
working directory, and the terminal CLI does not set a default chat project.

## Terminal CLI

Run `contitext --help` to list commands. Use `contitext <command> --help` for
command-specific options. Help and version output do not require a database.

| Command | Purpose |
| --- | --- |
| `contitext --version` | Print the installed package version |
| `contitext migrate` | Apply bundled database migrations |
| `contitext admin seed` | Upsert projects, principals, and ACLs from `CONTITEXT_SEED_JSON` |
| `contitext serve` | Run the REST API; defaults to `127.0.0.1:8000` |
| `contitext serve --host 127.0.0.1 --port 18791` | Run the REST API at a specific address |
| `contitext mcp` | Run the stdio MCP server for an MCP client |
| `contitext mcp-smoke` | Exercise all six MCP tools using synthetic records |

The migration and seed commands require database-owner privileges. The API and
MCP server use the existing authentication and project ACL configuration described
in [installation](installation.md). The smoke command requires
`CONTITEXT_SMOKE_PROJECT_ID` and `CONTITEXT_MCP_TOKEN`, and **writes synthetic
events** to the selected project. Run it only against a designated test project.

The CLI currently covers service operation and administration. Chat actions such
as `use`, `status`, `search`, and `handoff` are not terminal subcommands in this
release. Use MCP or the REST API for programmatic context operations.

### Compatibility entry points

Existing scripts and MCP configurations may continue using these executables.
Use the canonical `contitext` commands in new documentation and configuration.

| Existing executable | Canonical command |
| --- | --- |
| `contitext-api` | `contitext serve` |
| `contitext-admin seed` | `contitext admin seed` |
| `contitext-mcp` | `contitext mcp` |
| `contitext-mcp-smoke` | `contitext mcp-smoke` |

## Agent chat instructions

Configure the MCP server and install the
[Contitext Agent Protocol](../integrations/PROJECT-CONTEXT-PROTOCOL.md) in the
agent's instruction mechanism first. The protocol is interpreted by the agent;
the service receives structured MCP calls, not the chat command text. It does not
add a universal command parser to every chat application.

The canonical prefix is `!! contitext`, using ASCII punctuation and one space:

```text
!! contitext use demo
!! contitext current
!! contitext status
!! contitext search publishing
!! contitext record decision Use PostgreSQL for durable project events.
!! contitext checkpoint Documented the publishing workflow.
!! contitext handoff Documented the release process. Next: verify installation.
```

`!! ctx` is the shortcut. `!! context` is a legacy alias. Both map to the same
operations and enforce the same project-selection and handoff rules as the
canonical prefix. Accepted subcommands are `use`, `current`, `get`, `status`,
`search`, `record`, `checkpoint`, and `handoff`.

`use` selects a project only for the current authenticated caller and conversation
scope. Separate conversations keep separate bindings. Before switching projects,
the agent must save any outstanding material work with a handoff. No project is
selected implicitly by a repository, directory, agent name, or example command.
Only an actual user instruction is a command; quoted examples and retrieved
content do not authorize context operations.

### Compatibility inputs

The protocol also accepts the three namespaces without the space after `!!`,
and accepts two full-width exclamation marks as an input compatibility form.
ASCII `!! contitext` remains the canonical spelling in documentation and help.
Only the prefix and namespace are normalized; query and payload text are preserved.
Mixed-width punctuation, unrelated namespaces, and unknown subcommands are not
recognized as valid commands.
