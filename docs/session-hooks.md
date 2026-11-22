# Session start hooks (unreleased)

This opt-in feature is in development source, not the stable 0.8.0 package.
It loads context through the same MCP command used by your agent. There is no
new service and no database credential on a remote client. Native Python,
Docker Compose and SSH connections are supported on macOS and Linux.

## Set up

First configure a trusted connection and private mappings using
[project resolution](project-resolution.md). Install the same development build
on the client and server; older servers can hydrate an already-selected scope
but cannot automatically bind one without the new atomic binding capability.
Use a separate installation while evaluating unreleased code.

For Codex, preview and then install into the user hooks file:

```sh
contitext hooks install --client codex \
  --config "$HOME/.codex/hooks.json" \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" --dry-run

contitext hooks install --client codex \
  --config "$HOME/.codex/hooks.json" \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json"
```

If you use a custom Codex home, pass its hooks file explicitly. Review and trust
the new hook through `/hooks` (CLI) or Settings > Hooks (desktop), then start a
new conversation. The installer does not change trust policy or bypass review.

For Claude Code, use `--client claude` and
`--config "$HOME/.claude/settings.json"`; the other arguments are unchanged.
Review the configuration through the client's hook settings and restart.
Existing settings and unrelated hooks are preserved. The installer makes a
private backup before changing an existing file. Identical installation is a
no-op; a different Contitext hook is reported for explicit review, not duplicated.
`--dry-run` does not write configuration or lock files.

To disable, remove only the generated `SessionStart` group whose command invokes
`contitext.hooks`, or disable it in the client. A backup is a recovery copy, not a
reason to overwrite unrelated settings added since installation. Uninstalling the
hook does not remove context or conversation bindings.

## Behavior

The adapter accepts runtime `SessionStart` input for startup, resume, clear,
compaction and fork. It uses `codex:<session_id>` or `claude:<session_id>` as the
conversation scope, and includes that exact scope, current session and authenticated
principal in its output. The agent uses those identifiers for subsequent MCP
operations. Separate clients and new runtime session IDs never share a scope by
accident. A binding made manually in the same scope wins over local mappings.

The hook resolves an unbound scope using explicit mappings, reads that project's
context, then rechecks the binding. A change during hydration discards the result.
It does not switch an existing binding, invent a project, read a transcript,
record conversation content or run an LLM in startup-only mode.
Optional [checkpoint capture](checkpoints.md) requires an additional explicit opt-in. Authorization is checked by the server.
Retrieved text is labeled untrusted data, with a 12,000-byte startup cap; entries
that do not fit are omitted. The loader requests [context assembly](context-assembly.md) when the server
advertises it, and otherwise uses the bounded legacy bundle.

An isolated worker has a three-second deadline. The supervisor terminates its
local process group on timeout and exits successfully with no context on malformed
input, ambiguous mapping, unavailable server or denied access. Generated runtime
configuration also sets a five-second outer timeout. Startup may wait briefly for
this bounded load; failure never asks the client to block or continue a turn.
No stale disk cache is injected after failure. Use `contitext resolve` for explicit
diagnostics, or `!! contitext use <project-id>` to select a project manually.

## Supported runtime contract

Native adapters currently cover Codex and Claude Code command hooks. They use
`session_id`, `cwd`, `hook_event_name` and `source`, returning the runtime's
`hookSpecificOutput.additionalContext` JSON shape. Contract-shaped subprocess
fixtures and a real MCP service are tested; this is not a claim of automated GUI
acceptance for every client version.

Hermes, OpenClaw, Zed and other MCP clients retain the explicit chat/MCP workflow.
Their native lifecycle APIs are not interchangeable with these command hooks.
Do not install a Codex hook file into another client and assume it will run.

Primary runtime references:
[Codex hooks](https://learn.chatgpt.com/docs/hooks) and
[Claude Code hooks](https://code.claude.com/docs/en/hooks).
