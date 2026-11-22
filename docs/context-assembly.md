# Context assembly and lifecycle metadata (unreleased)

This development feature is not in the stable 0.8.0 package. Upgrade the schema
before running the new server. The eight MCP tool names and existing required
arguments remain unchanged; old calls retain their top-level response shape.

## Request a bounded context bundle

```json
{"project_id":"personal/sample","task_id":"issue-14","token_budget":4000}
```

Pass these arguments to `context_get`, or use the equivalent `task_id` and
`token_budget` query parameters on the existing REST context endpoint. Omitting
both returns the legacy bundle. Supplying either enables assembly; the default
budget is 4000 and the accepted range is 1024–32000.

Selection is deterministic: the matching task's latest handoff takes priority,
with a project-wide handoff as fallback. Decisions and questions include the
selected task plus project-wide records, with task records first. No record from
another task is substituted. Without a task ID, assembly selects only project-wide
records. Task IDs are literal caller-supplied identifiers, not inferred from a
branch, title, current directory or prompt. Allowed characters are ASCII letters,
digits, dots, underscores, colons and hyphens, starting with a letter or digit;
maximum length is 128.

The response contains `project_id`, `task_id`, `context`, and budget accounting.
`context` separates handoff, effective decisions, unresolved questions, verified
checkpoint and unverified `progress_candidates`. Whole events are added in that
order; oversized events are omitted rather than truncated into misleading text.
Selection considers up to 20 decisions, 20 questions and 3 candidate checkpoints,
plus one handoff and one verified checkpoint. `omitted_events` counts selected
candidates omitted for space, not all historical events in the database. Search
retains access to the full authorized history.

`budget_unit` is **compact_json_utf8_bytes**. `used_budget` includes the complete
compact serialized response, including its own accounting fields, and never
exceeds `token_budget`. This is a conservative model-independent proxy, not an
exact model tokenizer count. Client formatting, hook instructions and transport
wrappers consume additional context. No tokenizer or model download is required.

Session-start hooks discover the optional assembly arguments and request a
4000-unit project-wide bundle. Custom task-specific hook commands may pass
`--task-id issue-14` to `python -m contitext.hooks`; standard runtime input does not
supply a portable task ID. Old servers keep the bounded legacy-loading path.

## Record explicit metadata

`context_record` and `context_handoff` accept optional `event_metadata`:

```json
{"task_id":"issue-14","candidate":false,"supersedes":null,"resolves":null}
```

- A new **decision** may set `supersedes` to an earlier decision's event UUID.
- A **note** may set `resolves` to an earlier question's event UUID and put the
  resolution explanation in its payload.
- A checkpoint with `candidate: true` is unverified progress. It is excluded from
  the verified checkpoint and returned separately by assembly.
- Candidates cannot supersede decisions or resolve questions. A relation must
  refer to an existing non-candidate event in the same project and task namespace.
  One event can carry at most one relation; an already-closed target is rejected.
- Exact retries remain idempotent. Two concurrent replacements of one decision
  cannot both become effective; the losing caller must reread current state.

All events remain immutable. Lifecycle operations append a new event rather than
editing or deleting history. Reopening a question is an explicit new question;
there is no implicit reopening or automatic candidate promotion. Ordinary old
payload fields such as `task_id`, `supersedes` or `resolved_event` gain no special
meaning. Historical question payload `resolved: true` retains its existing meaning.

Legacy `context_get` now also filters explicitly superseded/resolved records and
candidate checkpoints. Its project-wide latest-handoff behavior remains unchanged;
use assembly for task-aware handoff selection. Markdown readers retain history and
show metadata; they do not present a candidate as the latest verified checkpoint.

## Upgrade and rollback

Migration `0004_context_metadata` adds one nullable JSONB column and lookup indexes.
Existing IDs, payloads, timestamps, bindings, ACLs and credentials are preserved;
old metadata stays null. No historic task or lifecycle relationship is guessed.
`upgrade-check` recognizes the 0.8.0 schema and normalizes absent/null metadata for
before/after integrity comparison while including real metadata in fingerprints.

Follow the existing [backup, writer fence and upgrade procedure](upgrading-to-0.8.md)
in a disposable copy first, using the new build's `upgrade-check`, then `migrate`,
then comparison and real MCP verification. Do not run an old server binary against
the upgraded schema. After metadata has been written, downgrade refuses to discard
it; restore a verified pre-upgrade backup, accounting for subsequent writes.
