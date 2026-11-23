# 0.8.3 release acceptance

This release corrects the cross-agent chat prefix. It keeps the eight MCP tools,
database schema, authorization, project bindings and lifecycle automation intact.
The release implementation and the later acceptance-evidence update are separate,
focused PRs; the published 0.8.3 artifacts are unchanged.

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

Updated 2026-11-23 after upgrading the maintainer's existing deployment and client
instructions to the published 0.8.3 artifacts. These are observed results on
macOS, not a claim about every model, client version or interaction surface.

| Agent / tested runtime | Authenticated chat and MCP evidence | Native automatic startup | Remaining boundary |
| --- | --- | --- | --- |
| OpenAI Codex CLI 0.166.0 | `status` and a full-width-colon follow-up completed `project_current` then `context_get`; unknown commands returned help and the old bang prefix was rejected | Verified in a fresh session after individually trusting the five installed hooks; the runtime injected the correct conversation binding | Plain headless execution with approval policy `never` rejects MCP calls. One separate session reported unavailable tools; the full-width follow-up succeeded in the known-good session through normal approval review |
| Claude Code 2.1.123, Sonnet 4.6 | `status`, full-width colon, unknown-command error and empty-command help verified | Verified: real `SessionStart` injected context and the following MCP call used that session's scope | **Observed failure:** one fresh-session old-prefix trial still executed a status read; complete chat-contract acceptance is not claimed |
| GitHub Copilot CLI | Not run: runtime was not installed in the maintainer test environment | Not run | Installer, shared fixtures and lifecycle bridge tests only |
| Cursor CLI 2026.04.30 / 2026.11.22 | Native skill discovery and MCP routing observed; interactive listing, explicit project binding, context retrieval and full-width `status` completed with one-time tool approvals | Desktop lifecycle was not exercised | **Observed failures:** Ask-mode trials treated `stauts` and the old bang prefix as status requests; MCP tool approval rejected those calls. CLI evidence is not desktop acceptance |
| OpenCode | Not run: runtime was not installed in the maintainer test environment | Not run | Installer, shared fixtures and optional V2 plugin bridge tests only |
| Gemini CLI 0.70.0 | MCP discovery connected, but Google rejected the signed-in individual OAuth client before model execution | Not established in an authenticated model session | Provider error: “This client is no longer supported for Gemini Code Assist for individuals”; no API-key/provider substitution was made |
| Hermes 0.23.3 | Project listing, explicit selection, status, full-width colon, unknown-command error, old-prefix rejection, checkpoint and handoff write/read verified in a real resumed session | Optional memory-provider plugin was not enabled | Skill explicitly selected with `--skills contitext`; automatic skill discovery/startup is not claimed |
| OpenClaw 2026.10.33 | Existing MCP launcher connected, but real `agent exec` trials made zero MCP calls after the configured provider fell back to a local model | Optional lifecycle plugin was not enabled | **Inconclusive host result:** a successful process exit did not demonstrate Contitext chat execution |

The Claude and Cursor instruction-following failures are tracked in
[issue #30](https://github.com/jessysw/contitext/issues/30). Do not advertise the old
prefix as supported or remove this observation after a favorable retry. Parser
fixtures still reject it deterministically; the failure occurred in the model's
interpretation of installed instructions. The optional command-punctuation
suggestion is deferred to [issue #29](https://github.com/jessysw/contitext/issues/29).
No parser behavior changed in this acceptance update.

### How these trials were assessed

- Success requires an actual tool invocation **and** its result, not the agent
  saying it would call a tool or a process returning exit code zero.
- Prompts were supplied as exact user inputs, with stdin closed for scripted
  invocations. Initial harness trials that appended unrelated stdin were excluded.
- Unknown/empty/legacy checks inspect assistant-issued tool calls separately
  from independent lifecycle loading. A startup hook may run even when the user
  input is not a Contitext command.
- Hermes explicitly selected an existing dedicated test project, then saved a
  unique checkpoint and structured handoff and read both back in the same scope.
  Cursor then read that same handoff through its own explicitly selected scope,
  verifying a real cross-agent handoff. No operational project was created or
  selected by guessing its repository name.
- Codex/Claude startup was tested using existing explicitly trusted repository
  mappings. The observed SSH path needed the existing configurable worker budget
  increased from 3 to 7 seconds; shutdown deadlines remained bounded.
- Raw transcripts contain private project context and remain private. This report
  publishes the runtime versions, tested actions, outcomes and limitations.

The current chat entry remains an instruction interpreted by the agent; it is
not a deterministic native command dispatcher. These results support the specific
paths above, **not** a claim that all eight hosts are fully runtime-verified.
See [compatibility boundaries](chat-commands.md).

## Existing deployment upgrade

The published artifacts were installed on the maintainer's six existing macOS
machines. All 20 previously configured adapters completed actual MCP
initialization, discovery of eight tools, `project_current` and `context_get`.
Private connection configuration was unchanged. This is connection evidence,
not twenty authenticated host-chat demonstrations. Two newly configured Cursor
and Gemini launchers also passed those MCP read checks; their host-runtime limits
are recorded separately above.

The application and optional Markdown reader run the 0.8.3 image and are healthy.
The PostgreSQL 18.7 container and persistent volume were retained. Backup restore
and isolated rehearsal passed before a fenced cutover; data-integrity checks
passed afterward. Existing mappings, bindings, credentials, checkpoint queues and
restart configuration were preserved. Only disposable rehearsal resources were
removed; rollback artifacts and the backup were retained.

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

The published release passed the full CI matrix, installed wheel/Docker tests,
package/privacy checks and documentation consistency tests. [Release tracker #27](https://github.com/jessysw/contitext/issues/27)
records the final run links and artifact hashes, including Docker acceptance.
Historical [0.8.2 lifecycle and upgrade evidence](acceptance-0.8.2.md) remains
applicable to unchanged server behavior; it is not promoted to new host evidence.

Public publication and private deployment upgrades remain separate operations.
