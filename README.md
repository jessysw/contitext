# Contitext

<!-- mcp-name: io.github.jessysw/contitext -->

**Project continuity for AI agents.**

Keep project state, decisions, checkpoints, and handoffs available across agents,
sessions, and machines. Contitext is a small, self-hosted Python service backed by
PostgreSQL, with REST and six MCP tools. No LLM API key or embedding service is required.

An agent finishes a session by recording what changed and what comes next. Another
agent explicitly selects the same project, reads that context, and continues from
the recorded handoff.

**v0.5.4 is an early public release.** The core service is usable independently.
Companion integrations and broader memory features are on the [roadmap](https://github.com/jessysw/contitext/blob/main/docs/roadmap.md).

## Quick start

Requires Docker with Compose, Git, and standard CPython 3.11–3.14.

```sh
git clone https://github.com/jessysw/contitext.git
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

For a real project, see the [self-hosting workflow](docs/self-hosting.md):
initialize your project, manage access, check your installation, connect clients,
and verify backup recovery. New administration commands described there are in
the development branch; install this checkout to try them before the next release.

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
contitext migrate
contitext admin seed
contitext serve --host 127.0.0.1 --port 18791
contitext mcp
```

After installing the agent protocol in your MCP client, use these **chat
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
