# 0.8.3 release acceptance

This release corrects the cross-agent chat prefix. It keeps the eight MCP tools,
database schema, authorization, project bindings and lifecycle automation intact.
The tracked work is one focused implementation/release PR.

## Evidence layers

| Layer | Validation | What it does not establish |
| --- | --- | --- |
| Syntax | Shared JSON fixtures run against Python, exported JavaScript and shell JSON transport | A host received or executed a chat command |
| Instruction delivery | Shell installer writes the identical protocol for all eight agents and Zed; reinstallation is idempotent | A model followed those instructions |
| Automation and MCP | Existing native-event, exported-plugin, startup, checkpoint, handoff, binding and real MCP regressions | Runtime trust or authenticated UI execution |
| Distribution | Installed wheel and Docker artifact acceptance, shared fixture inclusion, version/privacy checks | An existing private deployment was upgraded |

The shared fixture set covers `contitext: status`, `Contitext：status`, rejection
of `!! contitext status`, unknown-command errors, empty-command help, whitespace,
literal Unicode and preserved arguments. Lifecycle regressions use their existing
event contracts rather than interpreting arbitrary chat history as commands.

## Actual host-runtime evidence

| Agent | Prefix routing and MCP result in an authenticated host | Native automatic startup in this release |
| --- | --- | --- |
| OpenAI Codex | Not verified | Not verified |
| Claude Code | Not verified | Not verified |
| GitHub Copilot CLI | Not verified | Not verified |
| Cursor desktop | Not verified | Not verified |
| OpenCode | Not verified | Not verified |
| Gemini CLI | Not verified | Not verified |
| Hermes | Not verified | Not verified |
| OpenClaw | Not verified | Not verified |

These rows are not failures of the parser contract, and are not a claim of
end-to-end acceptance. Do not label the eight agents as fully runtime-verified
based on fixture or installer results. The current chat entry remains an
instruction interpreted by the agent; it is not a deterministic native command
dispatcher. See [compatibility boundaries](chat-commands.md).

## Release checks

Local validation on 2026-11-23:

- CPython 3.13 and disposable PostgreSQL 18: **307 tests passed**. The one
  Starlette/httpx deprecation warning is unrelated to command parsing.
- The 67 shared syntax cases pass in Python, both exported JavaScript adapters
  and shell JSON transport. All nine instruction targets pass legacy-block
  replacement and idempotent reinstallation checks.
- A fresh wheel installed outside the checkout completed initialization,
  migration, health checks and real stdio MCP write/read smoke checks. All eight
  installed lifecycle bridges loaded context and saved/read a candidate with
  idempotent retry. These are bridge tests, not authenticated agent-chat trials.
- Wheel and source archives pass metadata/content checks and include the shared
  fixtures and JavaScript parser. Source privacy checks found no unresolved
  credentials or private deployment identifiers; the existing synthetic key
  marker in a redaction test was reviewed separately.

Before publication, the exact release source must pass the existing full CI
matrix, installed wheel/Docker tests, package/privacy checks and documentation
consistency tests. [Release tracker #27](https://github.com/jessysw/contitext/issues/27)
records the final run links and artifact hashes, including Docker acceptance.
Historical [0.8.2 lifecycle and upgrade evidence](acceptance-0.8.2.md) remains
applicable to unchanged server behavior; it is not promoted to new host evidence.

Public publication and private deployment upgrades remain separate operations.
