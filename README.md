# Contitext

<!-- mcp-name: io.github.jessysw/contitext -->

**Project continuity for AI agents.**

Keep project state, decisions, checkpoints, and handoffs available across agents,
sessions, and machines. Contitext is a small, self-hosted Python service backed by
PostgreSQL, with REST and six MCP tools. No LLM API key or embedding service is required.

An agent finishes a session by recording what changed and what comes next. Another
agent explicitly selects the same project, reads that context, and continues from
the recorded handoff.

**v0.6.0 supports independent self-hosting.** Initialize your own projects, manage
access, connect agents, and preserve context across sessions.
Companion integrations and broader memory features are on the [roadmap](https://github.com/jessysw/contitext/blob/main/docs/roadmap.md).

## Installation options

Both options run the same Contitext implementation and expose the same six MCP
tools. Neither requires a private repository or a paid service.

| Option | Requirements | Operation |
| --- | --- | --- |
| Python package | Standard CPython 3.11–3.14 and your PostgreSQL 16+ database | Install `contitext==0.6.0` from PyPI; run native stdio MCP and optionally REST |
| Docker Compose | Docker with Compose, Git, and Python 3.11–3.14 for bootstrap | Build the pinned release; Compose runs Contitext and PostgreSQL together |

Use the [installation guide](https://github.com/jessysw/contitext/blob/main/docs/installation.md)
for either path. Python installation does not require Docker. The database is
required in both cases; Contitext is not a standalone in-memory or SQLite store.
A native MCP client can launch `contitext mcp` directly without a REST process.

## Docker Compose quick start

Requires Docker with Compose, Git, and standard CPython 3.11–3.14.

```sh
git clone --branch v0.6.0 --depth 1 https://github.com/jessysw/contitext.git
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
client's instruction mechanism and restart its MCP session. This release does not
automatically modify your agent settings. The MCP server runs locally inside the
existing app container and shares its database.

| Tool | Purpose |
| --- | --- |
| `project_bind` | Explicitly select a project for a caller's conversation scope |
| `project_current` | Read that scope's current project |
| `context_get` | Get a bounded project overview, checkpoint, questions, decisions, and handoff |
| `context_record` | Append a note, decision, question, or checkpoint with provenance |
| `context_handoff` | Record completed work, current work, blockers, and the next action |
| `context_search` | Search project events using PostgreSQL full-text search |

No project is inferred from the working directory or repository name. Each caller
uses a stable conversation scope and explicitly selects a project. Project ACLs
are enforced on the server. [API contracts and limits](https://github.com/jessysw/contitext/blob/main/docs/api.md) describe what
the server enforces and what the agent protocol requires.

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
!! contitext use demo
!! contitext status
!! contitext search publishing
!! contitext checkpoint Documented the publishing workflow.
```

`!! contitext` is the canonical chat prefix. `!! ctx` is a shortcut, and
`!! context` remains a legacy alias. These are agent instructions, not terminal
subcommands. The terminal CLI currently runs and administers the service; it does
not implement chat actions such as `use`, `status`, or `search`, and it does not
set a global default project. See the [command reference](https://github.com/jessysw/contitext/blob/main/docs/commands.md) for
CLI options, compatibility entry points, and conversation scope behavior.

## What it includes

- Private initialization, project and permission administration, diagnostics, and
  portable native/Docker/SSH MCP client configuration.
- Atomic validation that every write matches the caller's conversation binding.
- A durable, append-only event store with caller identity and source provenance.
- Reader, writer, and owner project ACLs shared by REST and MCP.
- Idempotent retries; conflicting reuse of an event key is rejected.
- PostgreSQL full-text retrieval with pagination, without an embedding dependency.
- Optional Markdown projection for local inspection and note-taking tools.
- Synthetic tests for isolation, concurrency, restart recovery, projection, and
  real MCP stdio calls.

Use Contitext when you need explicit project continuity across tools and machines.
It does not automatically capture every conversation, consolidate memories, build
a knowledge graph, or decide which facts are true. A project handoff is the latest
handoff for the whole project, not a task scheduler or a conflict-resolution system.

## Development

See [CONTRIBUTING.md](https://github.com/jessysw/contitext/blob/main/CONTRIBUTING.md) for the isolated PostgreSQL test setup.
See [SECURITY.md](https://github.com/jessysw/contitext/blob/main/SECURITY.md) for trust boundaries and vulnerability reporting.
Repository: [jessysw/contitext](https://github.com/jessysw/contitext).

## License

[Apache License 2.0](https://github.com/jessysw/contitext/blob/main/LICENSE).
