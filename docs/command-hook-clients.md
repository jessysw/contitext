# Native command hooks (0.8.2 development)

Install MCP first using [agent installation](agent-installation.md), then create
an explicit private connection and mapping as described in [session hooks](session-hooks.md).
Hooks are optional. A mapping is an explicit authorization to resolve an unbound
conversation; an existing manual project selection always wins.

Use `contitext hooks install --client CLIENT --config ABSOLUTE_PATH
--connection ABSOLUTE_CLIENT_JSON --mappings ABSOLUTE_MAPPING_JSON --dry-run`
to inspect the proposed merge. Remove `--dry-run` to install. Add `--checkpoints
--state-dir ABSOLUTE_PRIVATE_DIRECTORY` only when you want candidate capture and
durable replay. Paths must be absolute; state is caller-owned mode 0700.

| Client | Default user configuration | Startup | Candidate capture | Flush boundaries |
| --- | --- | --- | --- | --- |
| Copilot CLI | `~/.copilot/hooks/contitext.json` | `sessionStart` | Explicit checkpoint; no transcript ingestion | `agentStop`, `preCompact`, `sessionEnd` |
| Cursor desktop | `~/.cursor/hooks.json` | `sessionStart` | `afterAgentResponse.text` | `preCompact`, `sessionEnd` |
| Gemini CLI | `~/.gemini/settings.json` | `SessionStart` | `AfterAgent.prompt_response` | `PreCompress`, `SessionEnd` |

The installer preserves unrelated hooks, tool restrictions and settings, makes
private backups, and refuses a conflicting Contitext command. Complete the
runtime's own trust/review process. No permission hook, retry decision, automatic
follow-up prompt or user-prompt capture is installed. Candidate progress remains
unconfirmed data, not an approved decision or completed handoff.

## Identity and limitations

- Copilot CLI supplies `sessionId`; its compatible snake-case form is accepted
  only when it agrees. The installer passes an explicit native event because
  camel-case input has no event-name field. `agentStop` exposes a transcript path,
  not final response text. Contitext does not read that file. Use an explicit MCP
  checkpoint/handoff or `contitext hooks checkpoint` for progress capture.
- Cursor uses `conversation_id` for the stable scope, never `generation_id`.
  Where available, `session_id` is retained; otherwise the stable conversation
  identifies the lifecycle session. Startup without an explicit cwd accepts
  exactly one workspace root. Ambiguous roots cause no automatic resolution.
  For CLI checkpoint/flush, provide both `--session-id` and `--conversation-id`.
- Gemini uses `session_id`. Hook timeouts in its settings are milliseconds;
  Copilot and Cursor use seconds. Gemini shutdown/compression notifications are
  best effort. Completed turn candidates are staged before network access;
  a hard kill cannot guarantee capture of a response the runtime never delivered.

These adapters target local execution, not managed cloud sandboxes. Cursor cloud
agents do not load local user hooks or guarantee the desktop session events.
Copilot cloud jobs need separate network and ephemeral-storage planning. The
Copilot CLI contract does not imply independent acceptance of every VS Code
harness version. Unsupported or malformed input returns no action. A bounded
worker prevents an unavailable server from stopping the agent.

Validation includes native configuration shapes, timeout units, conflict handling,
offline execution, real MCP startup/read, manual selection precedence and candidate
write/read. Contract tests do not represent an authenticated GUI demonstration.

Primary contracts checked 2026-11-22:
[Copilot hooks](https://docs.github.com/en/copilot/reference/hooks-reference),
[Cursor hooks](https://cursor.com/docs/hooks),
[Gemini hooks](https://geminicli.com/docs/hooks/reference/).
