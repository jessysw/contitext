# Automatic progress checkpoints

This opt-in 0.8.1 feature extends [session start hooks](session-hooks.md).
It captures **unverified progress candidates**, not approved decisions or a complete
transcript. Native hooks currently cover Codex and Claude Code on macOS and Linux.
Other MCP clients retain the explicit checkpoint and handoff workflow.

## Enable capture

Use the same private connection and mapping files as session-start loading. Add
`--checkpoints` and a dedicated state directory to the installer:

```sh
contitext hooks install --client codex \
  --config "$HOME/.codex/hooks.json" \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --checkpoints --state-dir "$HOME/.local/state/contitext-hooks" --dry-run
```

Review the output, then run without `--dry-run`. For Claude Code, change the client
and use its user `settings.json`. If you previously installed the startup-only
hook, explicitly remove that generated Contitext group before installing the new
one; the installer refuses duplicate/conflicting definitions. Preserve unrelated
hooks. Review and trust changed definitions through the runtime's normal UI.

The installer creates the state directory with mode 0700 and private files with
mode 0600. Keep it outside a repository and do not sync it into shared storage.
It contains conversation binding metadata and unsent progress excerpts. Disabling
hooks does not erase that data or remove server events.

## Events and guarantees

| Event | Action |
| --- | --- |
| SessionStart | Resolve/load as configured, retry matching pending work, remember the verified binding |
| Stop | Persist a bounded excerpt of `last_assistant_message` locally, then attempt a candidate checkpoint |
| PreCompact | Retry already-captured work; do not read transcripts or invent a fresh summary |
| SessionEnd | Bounded retry of already-captured work; does not keep the agent running |
| Interrupt (Codex) | Bounded retry; the runtime does not supply a new progress summary |
| Explicit intermediate checkpoint | Capture the summary supplied on stdin and attempt delivery |

Native capture uses the runtime's final assistant message, not user prompts,
command output, file contents or a transcript parser. Common token formats, bearer
credentials, password/token assignments, credential-bearing URLs and private-key
blocks are redacted before persistence. The excerpt is capped at 2400 UTF-8 bytes
plus a truncation marker. Pattern redaction is not a guarantee that every possible
secret or private fact is recognized; enable capture only for suitable sessions.

Local atomic writes and directory fsync precede network delivery. A two-second
worker deadline fits the generated three-second runtime timeout. Failure returns
success without blocking, asking for continuation or echoing private content.
The queue holds at most 256 candidates; full queues preserve existing records and
skip new capture until reviewed/drained. Each attempt sends at most eight matching
items. The same event/content is idempotent; when a runtime lacks a stable turn ID,
identical bounded excerpts are deliberately deduplicated.

Each pending record is pinned to the connection fingerprint, authenticated
principal, scope, project and binding timestamp. Replay never calls `project_bind`.
The server rechecks both project and timestamp under its binding row lock, closing
the gap between checking and writing. Revoked access, a different identity, a
manual switch, or switching away and back cannot redirect old work. Such items
remain pending for review. The first event after a manual switch refreshes local
binding metadata; subsequent captures use that binding. Use an explicit checkpoint
at the boundary when the same turn contains work for different projects.

The server must advertise both optional `event_metadata` and
`expected_binding_updated_at` on `context_record`; there is no unsafe old-server
fallback. Automatically captured records use `candidate: true`, are visible in
history and assembly's separate candidate section, and cannot replace a verified
checkpoint, supersede a decision or resolve a question.

## Intermediate checkpoint and recovery

Use the runtime's actual session ID. The session-start or a previous verified
lifecycle event must have captured its binding first:

```sh
printf '%s\n' 'Implemented the parser; validation is still pending.' | \
  contitext hooks checkpoint --client codex --session-id SESSION_ID \
  --source-id parser-milestone-1 \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --state-dir "$HOME/.local/state/contitext-hooks"

contitext hooks status --state-dir "$HOME/.local/state/contitext-hooks"

contitext hooks flush --client codex --session-id SESSION_ID \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --state-dir "$HOME/.local/state/contitext-hooks"
```

Status reports local counts without printing progress or secrets. Flush retries
only records matching the current authorized binding; it does not select a
project. To resolve a stale item, inspect its private `*.pending.json` locally,
review the summary and record it explicitly in the intended project before
manually archiving the pending copy. Do not edit binding timestamps to force replay.

`!! contitext checkpoint` and `!! contitext handoff` remain the explicit agent
commands for recording reviewed progress and an actual structured handoff. An
automatic candidate is not reported as a completed handoff. A machine crash or
SIGKILL can recover only content already captured; no hook can guarantee saving
work that was never supplied by the runtime. Normal exit is therefore not the
only checkpoint: Stop runs after responses, with optional intermediate capture.
