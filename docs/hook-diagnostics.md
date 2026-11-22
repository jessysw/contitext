# Diagnose and disable automation

MCP access, installed configuration, runtime trust and observed hook execution are
separate checks. Installing a hook or exporting a plugin does not prove that the
agent has activated it. Explicit MCP commands remain usable without automation.

## Command hooks

For Codex, Claude Code, Copilot CLI, Cursor desktop or Gemini CLI, inspect the
configuration and initialize the existing MCP connection without selecting a
project or writing context:

```sh
contitext hooks doctor --client codex \
  --config "$HOME/.codex/hooks.json" \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --state-dir "$HOME/.local/state/contitext/hooks/codex" --timeout 7
```

Use the client and configuration path from [native command hooks](command-hook-clients.md).
Omit `--state-dir` for startup-only installations. `connection: ready` means the
MCP server initialized and advertised the required tools. `configured_events`
counts only generated Contitext commands. `runtime_activation: not_verified` is
intentional: complete the client's own hook review and check its runtime status.
The diagnostic never grants trust or calls a project write tool.

For capture-enabled installations, `contitext hooks status --state-dir ABSOLUTE_PATH`
reports pending/blocked counts and the latest local run. The latter contains only
a timestamp, client, event, outcome and capture-failure flag, never prompts,
response text, paths, session IDs or credentials. `context_loaded` confirms that
the bridge returned context, not that a GUI displayed it. `timeout`, `worker_error`
and `invalid_input` explain failures; `completed_without_context` is also expected
for flush events or a safely unresolved scope. An absent record means no observed
run, not a healthy or broken integration. Status also works with exported plugins
when capture is enabled.

If an SSH connection cannot finish within the default budget, measure it with
`hooks doctor`. An explicit `hooks install --timeout 7` allows a worker budget
between 0.1 and 10 seconds. Codex end/interrupt workers remain capped at two seconds
under the runtime's three-second limit. Timeout changes require replacement and
normal runtime review; they never silently replace an existing hook. A longer
budget can delay startup. Prefer the smallest budget that works for the connection.

To stop only the generated hooks while preserving unrelated handlers, MCP settings,
project bindings and pending candidates:

```sh
contitext hooks disable --client codex --config "$HOME/.codex/hooks.json" --dry-run
contitext hooks disable --client codex --config "$HOME/.codex/hooks.json"
```

The first command previews the result. The second makes a private backup and removes
only canonical Contitext commands for the specified client. Shell-wrapped or manually
rewritten commands require manual review. Reload the client afterwards. For an upgrade,
first flush outstanding candidates where possible, disable the old configuration,
then reinstall using the same private state directory and review the new command.
Do not restore an entire old backup over unrelated settings added later.

## Plugin runtimes

Hermes, OpenClaw and OpenCode 2 own plugin activation, permissions and unloading.
Use their native status/disable interfaces and [plugin-client instructions](plugin-clients.md).
`hooks disable` does not alter plugin selections. Preserve private outboxes and
Hermes identity files when exporting a replacement adapter.

## Verification coverage

The release suite exercises configuration preservation, native event shapes,
bounded outages, manual binding precedence, candidate retries and privacy.
Exported JavaScript modules run under Node.js 24 in CI. Both the installed wheel
and a fresh Docker source artifact exercise all eight automation bridges against
real MCP: startup, candidate write/read and idempotent retry. These bridge checks
do not use an LLM or authenticate every agent GUI.

Runtime-specific evidence is deliberately narrower:

- Codex hook review was exercised in the native CLI. Trust acceptance is separate
  from evidence of startup hydration; inspect actual run status in your profile.
- Hermes' exported provider was instantiated and registered against the installed
  `MemoryProvider` ABC. Full host startup could not be verified because that test
  installation had an incomplete dependency environment. A healthy Hermes runtime
  is a prerequisite; Contitext does not repair or update the host agent.
- OpenClaw callbacks and OpenCode 2's current Promise SDK/event shapes were checked
  against their runtime contracts and executed module fixtures. Full authenticated
  host sessions are not claimed.
- Copilot, Cursor, Gemini and Claude Code have native configuration/event and real
  MCP integration coverage. This is not a claim that every GUI/version was tested.

Start with explicit MCP use in a dedicated project. Enable automation only after
reviewing the client-specific identity, capture and permission boundaries.
