# Commands

Contitext has two distinct interfaces: a terminal CLI and instructions that an
agent follows in a conversation. Neither interface infers a project from the
working directory, and the terminal CLI does not set a default chat project.

## Everyday project workflow

In an agent chat connected to your server:

```text
!! contitext list
!! contitext create my-project --name "My Project"
!! contitext use my-project
```

`list` returns projects the authenticated caller can access, including their IDs,
display names, statuses, and roles. It works before any project is selected.
`create` grants the authenticated, provisioned caller ownership of a new project
atomically. No owner UUID is needed. An unavailable ID fails without revealing
another project's metadata or overwriting anything. Neither command changes the
conversation's binding; `use` is a separate explicit step.

Project ID, display name, and repository are independent concepts. This release
has no repository association field or command. A project may span multiple
repositories or have none; working-directory changes never select a project.

## Workspace-qualified references

In 0.8 source, `workspace/project` is the unambiguous reference, for example
`!! contitext create personal/research --name "Research"`. Short IDs work only
inside the explicitly configured compatibility workspace (`personal` after fresh
init, `legacy` after the documented upgrade). Workspace membership permits
creation; membership plus a project ACL permits access. No config selects a chat.

## Terminal CLI

Repeat `--env-file` before the subcommand to load shared configuration then a
private client credential overlay; later files win without interpolation.
`client-config --credential-file /absolute/agent.env` generates that launch safely.

Run `contitext --help` to list commands. Use `contitext <command> --help` for
command-specific options. Help and version output do not require a database.

| Command | Purpose |
| --- | --- |
| `contitext workspace list` | List accessible workspaces and membership roles |
| `contitext workspace create team --name "Team"` | Create a workspace owned by the authenticated caller |
| `contitext workspace member grant team PRINCIPAL_UUID` | Grant membership as workspace owner |
| `contitext credential issue PRINCIPAL_UUID --name "Agent" --output /private/agent.env` | Issue a managed credential to a new private file |
| `contitext upgrade-check --snapshot /private/before.json` | Save a read-only integrity baseline before migration |
| `contitext --version` | Print the installed package version |
| `contitext init --project research --name "Research"` | Generate private `.env` and initial project seed; does not contact the database |
| `contitext --env-file /absolute/private.env doctor` | Check configuration, schema, MCP identity, and grants without writing |
| `contitext project list` / `show ID` | Inspect projects and access grants |
| `contitext project create ID --name NAME [--owner UUID]` | Create a project; defaults to the authenticated MCP identity |
| `contitext project update ID --name NAME --status STATUS` | Update metadata while preserving events and bindings |
| `contitext principal create NAME` / `list` | Provision and inspect identities; credentials are configured separately |
| `contitext access grant ID UUID --role writer` | Add or change a project grant |
| `contitext access revoke ID UUID` | Revoke project access without deleting history |
| `contitext access list ID` | Inspect project grants |
| `contitext client-config --compose /absolute/contitext --ssh server` | Print stdio MCP configuration using your SSH transport |
| `contitext migrate` | Apply bundled database migrations |
| `contitext admin seed` | Upsert projects, principals, and ACLs from `CONTITEXT_SEED_JSON` |
| `contitext serve` | Run the REST API; defaults to `127.0.0.1:8000` |
| `contitext serve --host 127.0.0.1 --port 18791` | Run the REST API at a specific address |
| `contitext mcp` | Run the stdio MCP server for an MCP client |
| `contitext export --output /absolute/reader-vault` | Export all projects accessible to the configured identity as readable Markdown |
| `contitext export --output /absolute/reader-vault --project research --watch 60` | Refresh a selected project every 60 seconds |
| `contitext mcp-smoke` | Exercise all eight MCP tools using synthetic records |

The migration, seed, project, principal, and access commands require trusted
database access. They are operator commands, not MCP tools or tenant APIs.
`--env-file` explicitly loads dotenv settings before any command; there is no
automatic configuration or project selection from the working directory. Treat
that file as credentials and never shell-source it. `admin seed --if-empty` only
initializes an empty deployment; plain `admin seed` intentionally reapplies
the supplied document. Project status is descriptive metadata, not an access
control: use `access revoke` to remove access. The API and
MCP server use the existing authentication and project ACL configuration described
in [installation](installation.md). The smoke command requires
`CONTITEXT_SMOKE_PROJECT_ID` and `CONTITEXT_MCP_TOKEN`. It **writes synthetic
events** to the selected project and **creates a synthetic project**. Run it only
in a designated test deployment.

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
| `contitext-mcp-smoke` | `contitext export --output /absolute/reader-vault` | Export all projects accessible to the configured identity as readable Markdown |
| `contitext export --output /absolute/reader-vault --project research --watch 60` | Refresh a selected project every 60 seconds |
| `contitext mcp-smoke` |

Without `--owner`, CLI creation resolves `CONTITEXT_MCP_TOKEN` against
`CONTITEXT_AUTH_TOKENS` and requires that identity to exist in the database. It
never chooses the first principal, a local OS user, or an arbitrary default.
Trusted operators can still supply `--owner UUID` (obtained with
`contitext principal list`) to create on another identity's behalf. MCP and REST
creation do not expose that override. The operator CLI's `project list` lists all
projects in the connected database; MCP/REST lists only the caller's grants.

## Agent chat instructions

Configure the MCP server and install the
[Contitext Agent Protocol](../integrations/PROJECT-CONTEXT-PROTOCOL.md) in the
agent's instruction mechanism first. The protocol is interpreted by the agent;
the service receives structured MCP calls, not the chat command text. It does not
add a universal command parser to every chat application.

The canonical prefix is `!! contitext`, using ASCII punctuation and one space:

```text
!! contitext list
!! contitext create my-project --name "My Project"
!! contitext use my-project
!! contitext current
!! contitext status
!! contitext search publishing
!! contitext record decision Use PostgreSQL for durable project events.
!! contitext checkpoint Documented the publishing workflow.
!! contitext handoff Documented the release process. Next: verify installation.
```

`!! ctx` is the shortcut. `!! context` is a legacy alias. Both map to the same
operations and enforce the same project-selection and handoff rules as the
canonical prefix. Accepted subcommands are `list`, `create`, `use`, `current`, `get`, `status`,
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

## Human-readable exports

`export` requires database configuration and `CONTITEXT_MCP_TOKEN`. It is an
operator-launched CLI using the authenticated caller's project ACLs, not a new
MCP tool or chat command. It never changes database records, projection offsets,
or conversation bindings. Repeat `--project ID` to select several projects; omit
it to discover all currently accessible projects on each refresh.

The output parent directory must exist. Use a dedicated empty folder, not an
existing notes vault or source checkout. The exporter refuses unrelated folders,
symlinks, competing writers, and a reader folder owned by another identity.
`--watch SECONDS` requires at least 10 seconds and runs until interrupted.
See [Obsidian and the Markdown reader](obsidian.md) for complete setup.
