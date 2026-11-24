# Contitext

<!-- mcp-name: io.github.jessysw/contitext -->

**Project continuity for AI agents.**

Keep project state, decisions, checkpoints, and handoffs available across agents,
sessions, and machines. Contitext is a small, self-hosted Python service backed by
PostgreSQL, with REST and eight MCP tools. No LLM API key or embedding service is required.

An agent finishes a session by recording what changed and what comes next. Another
agent resumes from the same project context, selected manually or resolved through
opt-in trusted mappings, and continues from the recorded handoff.

**Current stable release: [0.8.3](https://github.com/jessysw/contitext/releases/tag/v0.8.3).**
Install with `python -m pip install contitext` or pin `contitext==0.8.3` for a
reproducible setup. This release unifies chat commands as `contitext:` across
supported agents, with input-method compatibility and shared parser fixtures.
Existing deployments should follow [the 0.8.3 upgrade guide](docs/upgrading-to-0.8.3.md)
and reinstall their agent instructions. See [chat command compatibility](docs/chat-commands.md)
for syntax and the distinction between instructions, parsers and native execution.

**New to Contitext? Follow [Getting started](docs/getting-started.md)** for both
deployment paths, two independently authenticated agents and a visible handoff.

See [release validation](docs/acceptance-0.8.3.md), [workspaces](docs/workspaces.md),
[upgrade and recovery](docs/upgrading-to-0.8.md), and [the release plan](docs/v0.8-plan.md).
The [0.8.x automation plan](docs/automation-0.8.md) records the feature deliveries.
See [agent coverage](docs/agent-coverage.md), [hook diagnostics](docs/hook-diagnostics.md)
and the [completed client plan](docs/clients-0.8.2.md) for capabilities and boundaries.
Releases use maintainer review, automated checks and documented operational
rehearsals. User feedback is welcome through [GitHub issues](https://github.com/jessysw/contitext/issues).
Contributions follow the [PR workflow](CONTRIBUTING.md#development-workflow).

## Installation options

All options run the same Contitext implementation and expose the same eight MCP
tools. None requires a private repository or a paid service.

| Option | Requirements | Operation |
| --- | --- | --- |
| Homebrew | Homebrew on macOS/Linux and your PostgreSQL 16+ database | `brew install jessysw/tap/contitext`; isolated native CLI/MCP |
| Python package | Standard CPython 3.11–3.14 and your PostgreSQL 16+ database | Install `contitext==0.8.3` from PyPI; run native stdio MCP and optionally REST |
| Docker Compose | Docker with Compose, Git, and Python 3.11–3.14 for bootstrap | Build the release source; Compose runs Contitext and PostgreSQL together |

Use the [installation guide](https://github.com/jessysw/contitext/blob/main/docs/installation.md)
for setup and the [Homebrew guide](docs/homebrew.md) for package upgrades.
Native installation does not require Docker. The database is required in every case; Contitext is not a standalone in-memory or SQLite store.
A native MCP client can launch `contitext mcp` directly without a REST process.

## Docker Compose quick start

Requires Docker with Compose, Git, and standard CPython 3.11–3.14.

```sh
git clone --branch v0.8.3 --depth 1 https://github.com/jessysw/contitext.git
cd contitext
python3 scripts/bootstrap.py
docker compose up --build -d --wait
curl --fail http://127.0.0.1:18791/health/ready
docker compose exec -T app python -m contitext.demo
```

The bootstrap script creates fresh local credentials in a private `.env`, seeds a
`demo` project, and preserves existing configuration. The demo **writes synthetic
events to that project** and demonstrates two agents handing work over through
the real HTTP API. Its final output includes:

```json
{
  "agent_b_resumed": "demo",
  "next_action": "Implement and test the first endpoint.",
  "idempotent_retry": "passed"
}
```

The API listens on localhost. PostgreSQL has no published host port. Data persists
in a Compose volume; `docker compose down` stops the service and preserves it.
See [installation](https://github.com/jessysw/contitext/blob/main/docs/installation.md) for Python-package setup, administration,
backup, and remote access.

For a real project, use `python3 scripts/bootstrap.py --project research --name "Research"`
and skip the synthetic demo. The [self-hosting workflow](https://github.com/jessysw/contitext/blob/main/docs/self-hosting.md)
covers project creation, access management, client setup, and backup recovery.
These commands are included in both the PyPI package and the Compose release.

## Connect an MCP client

The MCP Registry identifier is `io.github.jessysw/contitext`. The
[Registry setup guide](https://github.com/jessysw/contitext/blob/main/docs/mcp-registry.md)
explains the PyPI/stdio installation and required database configuration.

After the quick start, add this server to a client that supports stdio MCP. Replace
the directory with your own absolute checkout path:

```json
{
  "mcpServers": {
    "contitext": {
      "command": "docker",
      "args": ["compose", "--project-directory", "/absolute/path/to/contitext", "exec", "-T", "app", "contitext", "mcp"]
    }
  }
}
```

Client configuration formats differ. The same command can be used by any stdio MCP
client. Load [the agent protocol](https://github.com/jessysw/contitext/blob/main/integrations/PROJECT-CONTEXT-PROTOCOL.md) into the
client's instruction mechanism and restart its MCP session. Client settings are changed only when you explicitly run the
[adapter installer](https://github.com/jessysw/contitext/blob/main/docs/agent-installation.md). The MCP server runs locally inside the
existing app container and shares its database.

| Tool | Purpose |
| --- | --- |
| `project_list` | List projects accessible to the authenticated caller |
| `project_create` | Create a project owned by the caller without selecting it |
| `project_bind` | Explicitly select a project for a caller's conversation scope |
| `project_current` | Read that scope's current project |
| `context_get` | Get a bounded project overview, checkpoint, questions, decisions, and handoff |
| `context_record` | Append a note, decision, question, or checkpoint with provenance |
| `context_handoff` | Record completed work, current work, blockers, and the next action |
| `context_search` | Search project events using PostgreSQL full-text search |

Each caller uses a stable conversation scope. By default, select a project with
`contitext: use`. With [trusted local mappings](docs/project-resolution.md) and
an enabled lifecycle adapter, Contitext can resolve and bind an unbound scope
automatically from a configured full Git remote or directory. Existing selections
take precedence; unmatched or ambiguous mappings do not bind a project. Agents
read the resulting binding and never guess a project from a repository name.
Workspace membership and project ACLs are enforced on the server.
[API contracts and limits](https://github.com/jessysw/contitext/blob/main/docs/api.md)
describe what the server enforces and what the agent protocol requires.

## Commands

Terminal commands use the `contitext` executable:

```sh
contitext --help
contitext --version
contitext init --project research --name "Research"
contitext project list
contitext doctor
contitext migrate
contitext admin seed
contitext serve --host 127.0.0.1 --port 18791
contitext mcp
```

Use the [agent adapter installer](docs/agent-installation.md) to configure your
clients with backups and a shared protocol. After installation, use these **chat
instructions** in a conversation with the agent:

```text
contitext: help
contitext: list
contitext: create my-project --name "My Project"
contitext: use my-project
contitext: status
contitext: search publishing
contitext: checkpoint Documented the publishing workflow.
```

`contitext:` is the only chat prefix. Prefix and command names are
case-insensitive; an input-method full-width colon is accepted. Empty commands
show help and unknown commands show an error with available commands. Arguments
are preserved without Unicode normalization. These are agent instructions, not terminal
subcommands. The terminal CLI currently runs and administers the service; it does
not implement chat actions such as `use`, `status`, or `search`, and it does not
set a global default project. See the [command reference](https://github.com/jessysw/contitext/blob/main/docs/commands.md) for
CLI options, compatibility entry points, and conversation scope behavior.

## Optional automation

**Automatic project resolution and startup context loading are supported and
opt-in.** Start with the explicit workflow above, then configure
[trusted project mappings](docs/project-resolution.md) and enable the
[lifecycle adapter for your client](docs/agent-coverage.md). Manual selections
always win. [Context assembly](docs/context-assembly.md)
selects effective decisions, open questions and the relevant task handoff within
a documented budget. [Candidate checkpoints](docs/checkpoints.md) add opt-in
progress capture and durable retry; they do not create approved decisions.

Native command hooks cover Codex, Claude Code, Copilot CLI, Cursor desktop and
Gemini CLI on macOS/Linux. Hermes, OpenClaw and OpenCode 2 have optional native
plugin adapters; Zed retains explicit MCP. See [coverage](docs/agent-coverage.md)
for runtime-specific capture, activation and validation boundaries. A Docker
server can use the local Python client for hooks without exposing PostgreSQL.

## What it includes

- Private initialization, project and permission administration, diagnostics, and
  portable native/Docker/SSH MCP client configuration.
- Project discovery filtered by caller access, and atomic creation owned by the
  authenticated caller without an owner UUID or implicit conversation switch.
- Opt-in deterministic project resolution, startup context loading, bounded
  context assembly, and candidate checkpoints through supported lifecycle adapters.
- Atomic validation that every event or handoff write matches the caller's conversation binding.
- A durable, append-only event store with caller identity and source provenance.
- Reader, writer, and owner project ACLs shared by REST and MCP.
- Idempotent retries; conflicting reuse of an event key is rejected.
- PostgreSQL full-text retrieval with pagination, without an embedding dependency.
- Optional Markdown projection for local inspection and note-taking tools.
- Synthetic tests for isolation, concurrency, restart recovery, projection, and
  real MCP stdio calls.

Use Contitext when you need explicit project continuity across tools and machines.
It does not automatically capture every conversation, consolidate memories, build
a knowledge graph, or decide which facts are true. The default context call retains the project-wide
handoff; task-aware assembly selects a matching task or global fallback. Lifecycle
changes require explicit metadata, not inferred agreement.

## Read your context without an agent

Enable the optional Markdown reader to browse project state, decisions, notes,
questions, and handoffs in Obsidian or any Markdown reader. No Obsidian plugin,
subscription, or account is required for local viewing.

After a fresh Docker setup:

```sh
mkdir -p reader-vault
docker compose --profile reader up --build -d --wait
```

Open `reader-vault` as an Obsidian vault and start with `README.md`. The exporter
refreshes every 60 seconds and shows the last successful snapshot and refresh
status. Native installs use `contitext --env-file /absolute/private.env export
--output /absolute/reader-vault --watch 60`.

This is a generated, one-way reading copy. Edits are not imported. Keep personal
notes elsewhere. See the [reader guide](https://github.com/jessysw/contitext/blob/main/docs/obsidian.md)
for existing-install permissions, remote copies, and troubleshooting.

## Development

See [CONTRIBUTING.md](https://github.com/jessysw/contitext/blob/main/CONTRIBUTING.md) for the isolated PostgreSQL test setup.
See [SECURITY.md](https://github.com/jessysw/contitext/blob/main/SECURITY.md) for trust boundaries and vulnerability reporting.
Repository: [jessysw/contitext](https://github.com/jessysw/contitext).

## License

[Apache License 2.0](https://github.com/jessysw/contitext/blob/main/LICENSE).
