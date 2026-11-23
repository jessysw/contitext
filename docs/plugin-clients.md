# Native plugin clients

Hermes, OpenClaw and OpenCode already support explicit Contitext MCP calls.
The optional adapters below add native context loading and progress candidates.
They use the same authenticated MCP connection, project ACLs and explicit mappings.
They do not create a new server, call a model, select a memory service for you,
or enable themselves in another application.

## Export and review

Install Contitext in a durable Python environment on the machine running the agent.
Prepare the private connection and mappings using [project resolution](project-resolution.md).
Choose a **new absolute directory** for each export:

```sh
contitext plugins export --client openclaw \
  --output "$HOME/.local/share/contitext/plugins/openclaw-0.8.3" \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" --dry-run
```

Remove `--dry-run` to create the reviewable files. Substitute `hermes` or `opencode`
for the other clients. Add `--checkpoints --state-dir ABSOLUTE_PRIVATE_DIRECTORY`
to opt in to candidate capture. Without it, no assistant text is forwarded.

The export pins the current Python executable and private configuration paths.
Review `bridge.json` and the small runtime adapter. The bridge reads no transcript,
forwards no user prompt, and has a three-second worker inside a bounded runtime
callback. Slow or unavailable connections return no context rather than stale data. An existing export is never
overwritten. On upgrade, export to a new directory and review the new code before
changing the runtime's reference. Do not delete the pinned Python environment.

## Hermes

Export directly to a new `$HERMES_HOME/plugins/contitext` directory for your
selected profile. This is a native **memory provider**, using `prefetch`,
`sync_turn`, `on_pre_compress` and `on_session_switch`. It does not install a
replacement context compressor or alter Hermes' cached system prompt.

Use Hermes' memory-provider setup/selection to choose `contitext`; review the
effect on an existing selected provider first. Keep your existing Contitext MCP
configuration for explicit tools. If you want to retain another memory provider,
you can continue using Contitext through MCP without enabling this adapter.

The runtime must supply `agent_context=primary`. Subagent/cron contexts and older
hosts lacking that discriminator do not get automatic reads or writes. Queries,
user messages and transcript arrays are ignored. Only assistant output becomes
an unconfirmed progress candidate when capture is enabled.

Compression preserves the existing scope through an explicit `reason=compression`
transition. A private bounded identity map survives process restarts; it stores
only runtime IDs, never project contents. New/branch/resume transitions never
inherit a parent binding just because a parent ID was supplied. A switch with no
new cwd loads only an already-bound scope; select a project explicitly if needed.
Do not remove the exported `identities` directory during an upgrade: copy it
privately to the replacement export before enabling that export, retaining mode
0700 on the directory and 0600 on its files.

## OpenClaw

Load the exported directory using OpenClaw's normal local-plugin installation
and review process, then enable the `contitext` plugin. Its prompt enrichment
uses `before_prompt_build`; the runtime must permit conversation access and prompt
modification. Review and grant those capabilities through OpenClaw's own controls.
Contitext does not modify `plugins.allow`, approval policy or those permission gates.

Optional capture consumes only `before_agent_finalize.lastAssistantMessage`.
This is a finalization **attempt**, which another plugin may still revise, so it
remains a candidate. Compaction and session end flush already-staged candidates;
`endedTranscript` is never accessed. Missing session identity skips the hook.
The session ID, not a reusable chat routing key, defines the scope. Audience and
hook-lifetime checks run before returning loaded context on hosts providing them.

Inspect the loaded plugin through OpenClaw's plugin status/inspection interface.
Disable it through the runtime to stop automation while retaining explicit MCP.

## OpenCode 2

Add the exported **directory** to the `plugins` array in your selected
`opencode.json` or `opencode.jsonc`, preserving other entries:

```json
{"plugins": ["/absolute/path/to/contitext-opencode-plugin"]}
```

The adapter uses OpenCode 2's `id`/`setup` plugin contract and Promise SDK.
It reads each session's actual location, checks the owning plugin instance,
and injects fresh context at the native `context` hook. It does not use the
process cwd or copy another session's binding. A public `session.text.ended`
event can capture a completed assistant text segment; reasoning and tool events
are not subscribed to. Execution and compaction events flush pending candidates.
Unload disposes hook registrations and aborts the event subscription.

The OpenCode **V1 MCP installer remains supported** through `--opencode-major 1`.
This native plugin requires V2; copying it into a V1 installation does not provide
lifecycle automation. Remove the directory entry and reload to disable it.

## Verification and boundaries

Use a dedicated test project. Verify explicit MCP list/use/write/read first, then
enable the adapter and check the loaded scope and local outbox. Test a manual
project switch, an unavailable server and a new session. Automatic capture is
best effort: abrupt termination before the runtime emits a response cannot save
that response. Staged candidates remain pinned to their original binding and
are not reassigned after a switch.

Contract tests load the exported Python/JavaScript modules, exercise callback
payloads, isolation, compression lineage and private export behavior. Full runtime
acceptance and required permissions are reported separately; an exported file
does not prove an agent has loaded or trusted it.

Primary interfaces checked 2026-11-22:
[Hermes memory providers](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin),
[OpenClaw plugin hooks](https://docs.openclaw.ai/plugins/hooks),
[OpenCode server plugins](https://opencode.ai/docs/build/plugins/server).

See [diagnostics and validation coverage](hook-diagnostics.md) for read-only
connection checks, safe disabling and the distinction between bridge tests and
authenticated host execution.
