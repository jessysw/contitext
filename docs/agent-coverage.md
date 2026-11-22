# Agent coverage (unreleased)

The expanded installer targets below are development work for 0.8.2. The published
0.8.1 installer covers Codex, Claude Code, Zed, Hermes and OpenClaw. A successful
MCP connection is distinct from instruction loading and native lifecycle hooks.

## MCP and instructions

Use the source-tree installer from the matching release. It installs user-level
configuration for the default profile on macOS/Linux; it does not install an agent,
sign in, grant tool approval, select a project or enable automatic capture.

| Target | MCP configuration | Instruction surface |
| --- | --- | --- |
| `codex` | `~/.codex/config.toml` | `~/.codex/AGENTS.md` |
| `claude` | `~/.claude.json` | `~/.claude/CLAUDE.md` |
| `zed` | `~/.config/zed/settings.json` | `~/.config/zed/AGENTS.md` |
| `hermes` | `~/.hermes/config.yaml` | `~/.hermes/skills/contitext/SKILL.md` |
| `openclaw` | `~/.openclaw/openclaw.json` | `~/.openclaw/skills/contitext/SKILL.md` |
| `copilot` | `~/.copilot/mcp-config.json` | `~/.copilot/copilot-instructions.md` |
| `cursor` | `~/.cursor/mcp.json` | `~/.cursor/skills/contitext/SKILL.md` |
| `opencode` | `~/.config/opencode/opencode.json` or existing `.jsonc` | `~/.config/opencode/AGENTS.md` |
| `gemini` | `~/.gemini/settings.json` | `~/.gemini/GEMINI.md` |

Example after generating `client.json` through [agent setup](agent-installation.md):

```sh
sh scripts/install-agent-adapters.sh --config client.json \
  --target copilot --target cursor --target opencode --target gemini --dry-run
sh scripts/install-agent-adapters.sh --config client.json \
  --target copilot --target cursor --target opencode --target gemini
```

Identical reinstallation is a no-op. The installer preserves other MCP servers,
settings, JSON comments, custom tool restrictions and explicitly disabled entries.
It backs up changed files and refuses conflicting files or unknown launcher owners.
Each target has an independent safely quoted launcher. Credentials stay behind
the supplied connection, never in generated client JSON.

### Runtime and profile differences

- **Copilot:** the default portable configuration is shared by Copilot CLI and
  the current Copilot harness in VS Code. Older VS Code Local-harness profiles use
  a different `servers` format; they are not rewritten. In remote/Dev Container
  sessions, install in the home directory where the harness runs. A tool allowlist
  does not bypass runtime tool approval or organization policy.
- **Cursor:** the installed skill is available through native skill discovery;
  this does not mean it is injected into every turn. User MCP configuration and
  skills remain local unless the user explicitly configures another execution host.
- **OpenCode:** default `--opencode-major 2` writes `mcp.servers` and a command
  array. Use `--opencode-major 1` for V1's direct `mcp` mapping. The installer
  refuses the other layout instead of silently migrating it. It preserves an
  existing `.jsonc`; when both `.json` and `.jsonc` exist, resolve that ambiguity
  first. No global MCP timeout or unrelated server is changed.
- **Gemini CLI:** MCP and global `GEMINI.md` instructions are separate surfaces;
  the installer does not set `trust: true` or change sandbox/tool permissions.

The default-profile paths above are deliberate. For custom `COPILOT_HOME`,
`CODEX_HOME`, `HERMES_HOME`, `XDG_CONFIG_HOME` or extension-managed profiles, use
the runtime's documented configuration location; do not assume changing the
server connection also changes the runtime's selected profile. `--home` is an
explicit alternate OS-home installation root, not a runtime profile selector.

## Automation and validation

Native hooks cover Codex and Claude Code through [session hooks](session-hooks.md),
and Copilot CLI, Cursor desktop and Gemini CLI through their
[native command contracts](command-hook-clients.md). Optional
[native plugin adapters](plugin-clients.md) cover Hermes, OpenClaw and OpenCode 2.
Review their distinct activation and identity boundaries. Do not install one
runtime's hook configuration into another runtime.

Installer regression tests exercise real generated launchers, literal argument
handling, both OpenCode layouts, idempotence, JSONC preservation, restricted and
disabled entries, backups and refusal paths. These are configuration-contract
tests, not proof that every proprietary GUI has been independently exercised.
Use each client's MCP status interface, then confirm `!! contitext list`, explicit
selection and a handoff/read in a dedicated test project.

Primary references, checked 2026-11-22:
[Copilot CLI configuration](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference),
[VS Code Copilot configuration](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
[Cursor MCP](https://cursor.com/docs/mcp), [Cursor skills](https://cursor.com/docs/skills),
[OpenCode MCP](https://opencode.ai/docs/mcp-servers/),
[OpenCode instructions](https://opencode.ai/docs/instructions),
[Gemini MCP](https://geminicli.com/docs/tools/mcp-server/),
[Gemini context](https://geminicli.com/docs/cli/gemini-md/).

See [diagnostics and validation coverage](hook-diagnostics.md) for read-only
connection checks, safe disabling and the distinction between bridge tests and
authenticated host execution.
