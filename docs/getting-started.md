# Getting started

This guide takes you from a fresh installation to a project handoff that another
agent session can read, then shows the same data in Obsidian. It uses Contitext
0.7.1, Docker Compose, and one local MCP client. No paid API or LLM key is needed
by Contitext; your agent has its own requirements.

You need Git, Docker with Compose, Python 3.11–3.14, and an installed supported
agent on macOS or Linux. The adapter installer and reader use POSIX filesystem
operations. For a native Python deployment with your own PostgreSQL 16+ database,
follow [the native installation steps](installation.md#option-1-python-package)
and then continue at step 2 using the native connection example below.

## 1. Start your service

```sh
git clone --branch v0.7.1 --depth 1 https://github.com/jessysw/contitext.git
cd contitext
python3 scripts/bootstrap.py --project welcome --name "Welcome"
docker compose up --build -d --wait
docker compose exec -T app contitext doctor
```

Expected: the containers become healthy and `doctor` prints `"ok": true`.
Bootstrap creates a private `.env` with credentials and an initial project.
Neither creating `welcome` nor starting the service selects a project in a chat.
Keep `.env` private; it is not a shell script. Re-running bootstrap preserves an
existing configuration by refusing to overwrite it.

## 2. Connect one agent

From the same checkout, generate a connection file for this local Compose stack:

```sh
docker compose exec -T app contitext client-config --compose "$(pwd)" > client.json
sh scripts/install-agent-adapters.sh --config client.json --target codex --dry-run
sh scripts/install-agent-adapters.sh --config client.json --target codex
```

For Claude Code, use `--target claude` instead. The other supported targets are
`zed`, `hermes`, and `openclaw`; see [agent installation](agent-installation.md).
Install only the clients you use. The installer backs up changed settings and
preserves unrelated settings. It also installs the protocol that explains the
chat commands to the agent.

For the native path, generate `client.json` with your actual absolute paths, then
run the same installer from the public checkout:

```sh
contitext client-config --config-file /absolute/private.env \
  --executable /absolute/venv/bin/contitext > client.json
```

Reload MCP or start a new agent session. Expected: the client reports a connected
`contitext` server with eight tools. If the GUI client cannot find `docker`, use
its absolute executable path in `client.json` and rerun the installer. For a
server on another machine, use the [SSH connection instructions](agent-installation.md)
instead of a local Docker path.

## 3. Create and select your first project

Send each instruction as a separate message to the agent:

```text
!! contitext list
```

Expected: `welcome` appears with its display name, status, and your role.
Create a separate project for this walkthrough:

```text
!! contitext create first-project --name "My First Project"
```

Expected: creation succeeds with you as owner, without an owner UUID. If the ID
already exists, use an available ID and substitute it in the following steps.
Creation does not switch the conversation. Select it explicitly:

```text
!! contitext use first-project
```

Expected: the agent confirms `first-project` and reads its context. Project IDs
and names do not need to match a Git repository.

## 4. Record a decision and hand off

Send these instructions separately:

```text
!! contitext record decision The health endpoint will return JSON.
!! contitext checkpoint The health endpoint response format is agreed.
!! contitext handoff The response format is agreed. Next action: implement the health endpoint.
```

Expected: the agent confirms actual MCP writes. A natural-language promise to
remember is not a stored record. If an MCP call fails, fix the connection and
verify the result before continuing.

## 5. Resume in another session

Open a fresh session in the same client, or another client connected to the same
Contitext service and authorized identity. Send:

```text
!! contitext use first-project
!! contitext status
```

Expected: the recorded decision, checkpoint, and handoff are returned, including
the next action to implement the health endpoint. You do not need to paste the
previous conversation. You can now ask this agent to continue the work.

Contitext shares recorded project state, not the entire unrecorded chat. Each
session selects its own project. The latest handoff is project-wide; concurrent
task scheduling and automatic conflict resolution are outside this release.

## 6. Read the same context yourself

For the fresh Compose setup above:

```sh
mkdir -p reader-vault
docker compose --profile reader up --build -d --wait
```

Expected: the optional `reader` container becomes healthy and `reader-vault`
contains `README.md`, `SYNC-STATUS.md`, and generated project pages. Open that
folder as an Obsidian vault, open `README.md`, and select **My First Project**.
The page shows your decision, checkpoint, and handoff. A Markdown editor also
works; no Obsidian plugin is needed. Refresh runs every 60 seconds.

For native installs, use a dedicated empty folder whose parent already exists:

```sh
contitext --env-file /absolute/private.env export \
  --output /absolute/reader-vault --watch 60
```

The exporter prints one JSON status per attempt. Stop a foreground watcher with
Ctrl-C. Generated files are reading copies; editing them does not change context
and the next export replaces them. The [reader guide](obsidian.md) explains
existing-install permissions, remote copies, supervision, and refresh failures.

## Finish or troubleshoot

- **Unknown chat command or only six tools:** update the adapter and reload MCP.
- **No selected project:** send an explicit `!! contitext use first-project`.
- **Project not found:** check the project ID and the configured identity's grants.
- **Empty or stale reader:** check `SYNC-STATUS.md`, its timestamp, and
  `docker compose --profile reader logs --tail 30 reader`.
- **Permission denied in the reader:** follow the UID/GID steps for existing
  deployments in the reader guide.
- **Stop this Compose deployment:** `docker compose --profile reader down` stops
  the containers and preserves the database volume and reading folder. Do not add
  `-v` unless you intend to delete the database volume.

Keep the database and credentials in your backup plan. Reading copies are
rebuildable exports, not a replacement for a database backup. See
[self-hosting](self-hosting.md) for recovery and [commands](commands.md) for the
full reference. For help, open an [issue](https://github.com/jessysw/contitext/issues)
with your version, installation path, and redacted error; omit credentials and
private project content.
