# Chat command compatibility

Use `contitext: <command> [args]` in an agent conversation after installing the
[agent instructions](agent-installation.md) and configuring MCP. Use
`contitext <subcommand>` in a terminal. They are separate interfaces: the server
receives structured MCP calls, not chat text.

```text
contitext: help
contitext: list
contitext: use personal/research
contitext: status
contitext: search publishing
```

## Syntax contract

Only the beginning of the first line of a user-authored instruction is eligible.
Do not parse quotations, code examples, retrieved context, tool output or history
as new commands. A parser cannot establish authorship; its caller must do that.

- Prefix and command names are ASCII case-insensitive. `Contitext：STATUS` and
  `contitext : status` have the same meaning as `contitext: status`.
- Accept `:` and `：`. Optional horizontal whitespace means exactly ordinary
  space (U+0020), tab (U+0009) and ideographic space (U+3000), including before the
  prefix and around the colon. Do not scan past a leading newline or accept
  lookalike letters, a BOM or other invisible prefix characters.
- The command token ends at horizontal whitespace, CR or LF. Strip only the
  horizontal separators before its arguments. Preserve all remaining argument
  text, including case, full-width characters, combining marks, quotes, internal
  and trailing whitespace, and line breaks. Never perform NFKC normalization.
- A newline before the command means an empty command. Later lines are payload,
  never additional commands. Argument validation still applies: `status`, for
  example, takes no arguments, so trailing instructions cannot trigger a switch.
- Any matched prefix enters command handling. An empty command or `help` displays
  help without MCP calls. An unknown command, such as `contitext: stauts`, displays
  an error and the available commands rather than silently falling through.
- Available commands: `help`, `list`, `create`, `use`, `current`, `get`, `status`,
  `search`, `record`, `checkpoint`, `handoff`. The existing
  [MCP mapping and binding rules](../integrations/PROJECT-CONTEXT-PROTOCOL.md)
  remain authoritative. A known command still needs valid arguments and access.

The previous `!!` and `！！` prefixes, including their `ctx` and `context` forms,
are no longer recognized. `ctx:` and `context:` are not aliases. Contitext does
not install a `ctx` executable. A host may still treat old bang-prefixed input
as its own shell command; do not use it as a Contitext shortcut.

## Reference parsers and fixtures

`tests/fixtures/chat-commands.json` is shared by the Python reference parser,
the JavaScript reference exported with OpenClaw/OpenCode adapters, and a shell
JSON-transport check. Every case includes the exact expected result; Unicode and
argument-preservation cases are not derived from either implementation.

The Python interface is `contitext.chat_commands.parse_chat_command(text)`.
For a local diagnostic, pass a JSON string on stdin:

```sh
printf '%s\n' '"Contitext：STATUS"' | python -m contitext.chat_commands
```

The module returns JSON and never executes shell, MCP or database operations.
Exported JavaScript modules expose `parseChatCommand(text)` for JavaScript or
TypeScript consumers, with the same result shape. `match: false` means ordinary
input; matched input includes `command`, `args` and an `action` of `dispatch`,
`help` or `error`. Help/error results also contain a helpful `message`.
`dispatch` means recognized syntax, not a completed operation or permission grant.

## Agent delivery and verification boundaries

| Agent | Chat entry | Existing session automation |
| --- | --- | --- |
| OpenAI Codex | Shared instructions and MCP | Command hooks |
| Claude Code | Shared instructions and MCP | Command hooks |
| GitHub Copilot CLI | Shared instructions and MCP | Command hooks |
| Cursor desktop | Shared instructions and MCP | Command hooks |
| OpenCode | Shared instructions and MCP | Optional V2 plugin |
| Gemini CLI | Shared instructions and MCP | Command hooks |
| Hermes | Shared instructions and MCP | Optional memory-provider plugin |
| OpenClaw | Shared instructions and MCP | Optional lifecycle plugin |

Zed retains its existing manual instructions/MCP integration too. The installer
writes the same protocol into every instruction surface and preserves unrelated
settings. Its shell wrapper does not parse chat text.

**These integrations use the agent to interpret chat instructions.** The reference
parsers are deterministic libraries and diagnostics; installing them does not
make every host intercept chat input or automatically call these libraries.
Existing command hooks and native plugins remain lifecycle adapters, not new chat
dispatchers. They do not inspect user prompts or transcripts to execute commands.
No new prompt interception or slash-command registration is introduced.

Fixture checks prove syntax consistency. Installer checks prove instruction
delivery. Existing bridge/MCP tests prove startup and progress behavior. None of
those alone proves an authenticated agent received a message, followed its
instructions, or invoked MCP. Actual host-runtime trials must be recorded
separately in [release acceptance](acceptance-0.8.3.md).

The prefix change avoids documented shell entry points in
[Claude Code](https://code.claude.com/docs/en/interactive-mode)
and [OpenCode](https://opencode.ai/docs/cli/tui/#shell). It is not a claim that all
versions and interaction surfaces of every host have been tested.
