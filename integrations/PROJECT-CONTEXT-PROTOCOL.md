# Contitext Agent Protocol

This file is the canonical instruction source installed into supported agent instruction surfaces.

## Command recognition

Recognize only these prefixes, with either ASCII or full-width exclamation marks and with or without one space before the namespace:

- `!! context ...`
- `!!context ...`
- `！！ context ...`
- `！！context ...`
- the same four forms with `ctx` in place of `context`

Do not reinterpret `project`, `task`, `automation`, or any other command namespace as context commands. Reject unknown context subcommands rather than guessing.

## Scope and project invariant

There is no global, repository, topic, working-directory, or agent default project. In particular, `example-project` is only an example project identifier and must never be installed, stored, or inferred as a default. Select a project only through an explicit command in the current conversation, such as `!! context use example-project`, or through an already-existing runtime binding for the same conversation scope.

Use stable identifiers:

- `scope_id`: `<agent-or-client>:<stable-conversation-id>`; keep it unchanged for the conversation.
- `session_id`: the agent/client session identifier; keep it unchanged for the session.
- `source_id`: the stable message, thread, task, or artifact identifier that caused a write.
- `agent_id`/`principal_id`: the authenticated caller identity supplied by the runtime.

Never derive a project from the current directory, repository name, open files, prompt topic, or a previous unrelated conversation. If the scope is unbound, report that no project is selected and require an explicit `use` command.

## Strict MCP mapping

Map accepted commands only as follows:

- `context use <project-id>` / `ctx use <project-id>` → first call `project_current(scope_id)`. If the scope is unbound, call `project_bind(scope_id, project_id, session_id)` and then `context_get(project_id)`. If it is already bound to the requested project, keep the binding and call `context_get(project_id)`. If it is bound to a different project and the conversation contains material work not yet durably recorded, create a `context_handoff` for the old project before rebinding; then call `project_bind` for the requested project and `context_get` for it. Never silently overwrite a different project binding while material work is unsaved.
- `context current` → `project_current(scope_id)`.
- `context get` or `context status` → `project_current(scope_id)`, then `context_get(project_id)` using only the returned binding.
- `context search <query>` → confirm with `project_current(scope_id)`, then `context_search(project_id, query)`.
- `context record <note|decision|question|checkpoint> <text>` → confirm with `project_current(scope_id)`, then call `context_record(project_id, scope_id, session_id, agent_id, source_kind, source_id, event_kind, payload, idempotency_key)`. Set `payload` to a dictionary and set `event_kind` to exactly one of `note`, `decision`, `question`, or `checkpoint`; `status` is not a supported write event kind.
- `context checkpoint <summary> [next-action]` → confirm with `project_current(scope_id)`, then call `context_record(project_id, scope_id, session_id, agent_id, source_kind, source_id, event_kind, payload, idempotency_key)` with `event_kind` set to `checkpoint`, a dictionary `payload`, and a unique idempotency key.
- `context handoff <summary> <next-action> [blockers]` → confirm with `project_current(scope_id)`, then call `context_handoff(project_id, scope_id, session_id, agent_id, source_kind, source_id, summary, next_action, idempotency_key, completed, current, blockers)`. The fields through `idempotency_key` are required. Supply `completed`, `current`, and `blockers` as lists when present; use empty lists rather than strings when they have no entries.

Never call a project-scoped read or write using a project guessed from prose. Never represent a generic `context_record` call as a handoff.

## Lifecycle

At conversation start or before substantive project work:

1. Call `project_current` with the stable conversation scope.
2. If it returns a binding, call `context_get` for exactly that project.
3. If it is unbound, do not choose a project. Ask for or accept an explicit `context use <project-id>` command, call `project_bind`, and then call `context_get`.

During work, record a checkpoint after a material decision or durable change. Before transferring work or ending a substantial session, create a handoff with completed work, current state, blockers, and the next executable action.

Changing projects is a lifecycle boundary. Existing events already stored for the old project remain durable, but unrecorded chat content is not project context. Therefore, before `context use <new-project>` replaces a different active binding, write a handoff for the old project whenever material work has occurred since its latest checkpoint or handoff. If no material work occurred, state that explicitly and switch without creating a meaningless record. If the agent cannot determine whether work is unsaved, ask before switching rather than risking loss or cross-project contamination.

If the required MCP tools are unavailable, state that the context operation could not be performed. Do not claim that a bind, read, record, checkpoint, or handoff succeeded, and do not simulate durable context in chat memory.
