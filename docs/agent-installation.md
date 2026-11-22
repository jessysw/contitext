# Install agent adapters

Contitext runs once on your server or workstation. Each agent needs a stdio
connection and the same project-context protocol; it does not need a separate
PostgreSQL database or a copy of your project data.

The source-tree installer supports Codex, Claude Code, Zed, Hermes, and OpenClaw
on POSIX systems. It requires Python 3.11 or newer. Hermes configuration is read
using PyYAML from its existing Python environment; use `--yaml-python` if that
interpreter is elsewhere. No packages are installed by this script.

## Connect an agent

Obtain the installer from the public repository. Use the installer from the same release as your server.
The examples below cover 0.8.1. The protocol includes project listing and creation:

```sh
git clone --branch v0.8.1 --depth 1 https://github.com/jessysw/contitext.git
cd contitext
```

Generate a connection file using the installed CLI. For example, with a native
installation on a server already reachable through the SSH alias `context-host`:

```sh
contitext client-config \
  --ssh context-host \
  --config-file /absolute/private.env \
  --executable /absolute/venv/bin/contitext > client.json
```

For Docker Compose, use `--compose /absolute/compose-directory` instead of
`--config-file` and `--executable`. Add `--compose-project NAME` if the deployment
uses a non-default Compose project name. Establish and verify SSH connectivity
before installing a remote connection. Credentials stay on the server.

Preview and apply the changes for the clients you actually use:

```sh
sh scripts/install-agent-adapters.sh --config client.json \
  --target codex --target claude --dry-run
sh scripts/install-agent-adapters.sh --config client.json \
  --target codex --target claude
```

Repeat `--target` for `zed`, `hermes`, or `openclaw` as appropriate. The JSON may
also contain just `{"command": "/absolute/launcher", "args": []}`. Embedded
environment variables and credentials are rejected. If the default `python3`
is older than 3.11, set `CONTITEXT_INSTALL_PYTHON` to an existing supported Python.

The installer:

- Creates `~/.local/bin/contitext-mcp-TARGET` with safely quoted arguments, one
  launcher per client so configuring Claude cannot change Codex's credential.
- Migrates selected entries from the old shared launcher, preserving that file
  and unselected clients. Custom launchers still require explicit migration.
- Adds the `contitext` MCP entry to the selected clients' user configuration.
- Installs the canonical protocol in each client's instruction or skill file.
- Preserves unrelated configuration and instructions.
- Backs up changed files under `~/.local/state/contitext/adapter-backups/`.
- Refuses symlink destinations and ambiguous old/new server entries.
- Can be repeated with identical arguments without rewriting unchanged files.

Reload MCP or start a new agent session after installation. An already-running
session may retain its previous server name or instructions. Use the client's
MCP status command to check the connection, then start with:

```text
!! contitext list
!! contitext create your-project --name "Your Project"
!! contitext use your-project
!! contitext current
```

`!! ctx` is the shortcut and `!! context` remains a compatibility alias. Installation
does not select a default project, create a project, or migrate server data.

## Independent identities

Add `--credential-file /absolute/agent-b.env` to `client-config` and install its
JSON only for the intended `--target`. The file stays on the server. Native
launches load the shared config then the token overlay; Compose uses
`docker compose run --env-from-file`, which must appear in your installed
`docker compose run --help`. Upgrade Compose separately if it lacks this option.
No secret values enter shared JSON or shell command arguments. See the complete
[two-agent walkthrough](two-agents.md). Multiple targets in one installer call
intentionally receive the same connection; use separate calls for different identities.

## Replace an existing adapter

Use explicit legacy identifiers when replacing your own older adapter:

```sh
sh scripts/install-agent-adapters.sh --config client.json --target codex \
  --replace-server old-context \
  --replace-marker 'OLD CONTEXT' --dry-run
```

`--replace-marker LABEL` replaces an instruction block delimited by
`<!-- BEGIN LABEL MANAGED BLOCK -->` and its matching end marker.
For Hermes or OpenClaw, `--replace-skill OLD_DIRECTORY` also archives and removes
that old managed skill file. Unmanaged skill files are not removed. Review the
dry run, then repeat without `--dry-run`.

These flags migrate client configuration only. Preserve and migrate the server's
database, identities, bindings, credentials, and optional Markdown separately,
as described in [installation and operation](installation.md). Keep a private
rollback backup. Stop every old writer before the final database copy; never
run independent writable copies of the same logical deployment.

For a complete first installation, follow [Getting started](getting-started.md).
The optional [Markdown reader](obsidian.md) is configured on the service host;
installing an agent adapter does not enable or select a vault.

Optional native lifecycle hooks are installed separately through [session start](session-hooks.md)
and [candidate checkpoints](checkpoints.md). MCP installation alone does not enable capture.
